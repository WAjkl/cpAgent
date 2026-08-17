"""browser-price-mcp v0：站点价格适配器 + 缓存降级 + 入口白名单。

架构 M2 任务 2.2，落地为进程内函数工具（不依赖真实 MCP 协议）：
- 入口白名单：只允许访问白名单域名，杜绝 SSRF / 任意 URL 抓取
- 站点适配器模式：每个站点一个适配器，返回统一 PriceQuote
- 缓存降级：先查 price_cache，命中新鲜直接返回；miss/过期 → 适配器；
  适配器失败 → 降级到 hardware_db 快照价 + 标 estimate（灰）

真实抓取（京东/慢慢买）反爬高风险，留挂账（见 issues/ISSUE-007）：
本模块交付完整框架 + 白名单 + 降级链路，videocardprices 适配器作为
可工作的参考实现；京东/慢慢买适配器留骨架，接入后自动生效。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .config import HARDWARE_DB_PATH
from .price_cache import PriceCache, _parse_price, _snapshot_epoch
from .vcp_live_price import VideocardpricesAdapter  # 真实抓取（替代原 v0 骨架）

# ---------- 入口白名单（SSRF 防护）----------
ALLOWED_DOMAINS = {
    "videocardprices.com",   # GPU 街价（M0 已抓，JSON-LD）
    "passmark.com",          # CPU 实测美元价（M0 已抓）
    "open.er-api.com",       # USD/CNY 汇率
    # 待接入（M2 挂账）：item.jd.com / manmanbuy.com 等，反爬登录墙
}

# 站点 → 适配器映射（可扩展）
_ADAPTERS: Dict[str, "PriceAdapter"] = {}


def is_allowed_url(url: str) -> bool:
    """URL 入口白名单校验：仅 http/https，且 host 属于白名单域名（含子域）。"""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    # 精确域名或其子域
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


class PriceAdapter:
    """站点价格适配器基类。子类实现 fetch()，返回统一 PriceQuote 或 None。"""

    name = "base"
    domains: List[str] = []
    categories: List[str] = []  # 支持查询的类别

    def supports(self, category: str) -> bool:
        return category in self.categories

    def fetch(self, model: str, category: str) -> Optional[Dict[str, Any]]:
        """返回 {model, category, price_cny, price_low, price_high, source, confidence, fetched_at} 或 None（失败）。"""
        raise NotImplementedError


class HttpAdapter(PriceAdapter):
    """通用 HTTP 抓取适配器：白名单校验 + 超时 + UA。"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def _get(self, url: str, timeout: Optional[int] = None) -> str:
        if not is_allowed_url(url):
            raise ValueError(f"URL 不在白名单: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cpAgent price fetch)"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            return resp.read().decode("utf-8", "ignore")


class HardwareDbAdapter(PriceAdapter):
    """内置数据适配器：从 hardware_db.json 读 M0 已抓的价格（快照）。

    source 沿用条目自身 price_source（live/estimate），不做网络请求，
    是 v0 的稳定兜底数据源（等价于"已具备的 videocardprices/PassMark 数据"）。
    """

    name = "hardware_db"
    categories = ["cpu", "gpu", "memory", "ssd", "psu", "motherboard"]

    def __init__(self, db_path=None):
        self._db = None
        self._db_path = db_path or HARDWARE_DB_PATH

    def _load(self) -> Dict[str, Any]:
        if self._db is None:
            with open(self._db_path, encoding="utf-8") as f:
                self._db = json.load(f)
        return self._db

    def fetch(self, model: str, category: str) -> Optional[Dict[str, Any]]:
        db = self._load()
        items = db.get(category) or []
        for it in items:
            if it.get("model") == model:
                price = _parse_price(it.get("price_cny"))
                if price is None:
                    return None
                return {
                    "model": model,
                    "category": category,
                    "price_cny": price,
                    "price_low": _parse_price(it.get("price_low")),
                    "price_high": _parse_price(it.get("price_high")),
                    "source": it.get("price_source", "estimate"),
                    "confidence": float(it.get("confidence", 0.5)),
                    "fetched_at": _snapshot_epoch(it.get("fetched_at")),
                }
        return None


# VideocardpricesAdapter 已由 vcp_live_price 模块提供（真实抓取 + 解析 +
# 实时汇率，fail-safe 降级到 hardware_db）。详见 backend/vcp_live_price.py。


# ---------- 适配器注册 ----------
def _ensure_adapters() -> List[PriceAdapter]:
    if not _ADAPTERS:
        # 注册顺序即优先级：先真实站点，后内置兜底
        for a in (VideocardpricesAdapter(), HardwareDbAdapter()):
            register_adapter(a)
    return list(_ADAPTERS.values())


def register_adapter(adapter: PriceAdapter) -> None:
    if adapter.name in _ADAPTERS:
        raise ValueError(f"适配器重复注册: {adapter.name}")
    _ADAPTERS[adapter.name] = adapter


# ---------- 主入口 ----------
def search_price(
    model: str,
    category: str,
    cache: Optional[PriceCache] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """按型号搜价：缓存优先 → 适配器 → hardware_db 快照降级。

    返回 PriceQuote：{model, category, price_cny, price_low, price_high,
                      source, confidence, fetched_at, level, degraded, from}
    """
    cache = cache or PriceCache()

    # 1) 缓存命中
    rec = cache.get(model)
    if rec and not force_refresh:
        level = cache.freshness_of(rec)["level"]
        if level == "fresh":
            return {**rec, "level": level, "degraded": False, "from": "cache"}
        # stale/expired → 尝试适配器刷新
        fresh = _try_adapters(model, category)
        if fresh:
            _upsert_quote(cache, fresh)
            return {**fresh, "level": cache.freshness_of(fresh)["level"], "degraded": False, "from": fresh["source"]}
        # 刷新失败 → 旧缓存 + 标降级
        return {**rec, "level": level, "degraded": True, "from": "cache(stale)"}

    # 2) 缓存 miss / 强制刷新 → 适配器
    fresh = _try_adapters(model, category)
    if fresh:
        _upsert_quote(cache, fresh)
        return {**fresh, "level": cache.freshness_of(fresh)["level"], "degraded": False, "from": fresh["source"]}

    # 3) 全失败 → hardware_db 快照降级
    fb = _try_adapter_fetch(model, category, "hardware_db")
    if fb:
        _upsert_quote(cache, fb)
        return {**fb, "level": cache.freshness_of(fb)["level"], "degraded": True, "from": "hardware_db"}

    return {
        "model": model, "category": category,
        "price_cny": None, "price_low": None, "price_high": None,
        "source": None, "confidence": 0.0, "fetched_at": None,
        "level": "unknown", "degraded": True, "from": "none",
    }


def _upsert_quote(cache: PriceCache, quote: Dict[str, Any]) -> None:
    """把 PriceQuote 写入缓存（字段名映射：price_cny→price、price_low→low、price_high→high）。"""
    if not quote or quote.get("price_cny") is None:
        return
    cache.upsert(
        model=quote["model"],
        category=quote.get("category") or "unknown",
        price=quote["price_cny"],
        low=quote.get("price_low"),
        high=quote.get("price_high"),
        source=quote.get("source") or "estimate",
        confidence=quote.get("confidence") or 0.5,
        fetched_at=quote.get("fetched_at"),
    )


def _try_adapters(model: str, category: str) -> Optional[Dict[str, Any]]:
    """按优先级遍历适配器（真实站点在前，hardware_db 兜底在后），返回首个成功。"""
    for a in _ensure_adapters():
        if a.name == "hardware_db":
            continue  # hardware_db 是最终兜底，不参与"刷新"
        if not a.supports(category):
            continue
        try:
            q = a.fetch(model, category)
        except Exception:
            q = None
        if q:
            return q
    return None


def _try_adapter_fetch(model: str, category: str, adapter_name: str) -> Optional[Dict[str, Any]]:
    a = _ADAPTERS.get(adapter_name) or next((x for x in _ensure_adapters() if x.name == adapter_name), None)
    if not a or not a.supports(category):
        return None
    try:
        return a.fetch(model, category)
    except Exception:
        return None


def refresh_prices(models: List[str], category: str, cache: Optional[PriceCache] = None) -> List[Dict[str, Any]]:
    """批量刷新价格（强制走适配器），返回每个型号的 PriceQuote。"""
    cache = cache or PriceCache()
    return [search_price(m, category, cache=cache, force_refresh=True) for m in models]


def freshness(model: str, cache: Optional[PriceCache] = None) -> Optional[Dict[str, Any]]:
    """返回某型号的新鲜度状态点（供前端绿/黄/灰点）。"""
    cache = cache or PriceCache()
    return cache.freshness(model)


def price_summary(cache: Optional[PriceCache] = None) -> Dict[str, Any]:
    """价格缓存整体状态（前端上下文栏价格快照用）。"""
    cache = cache or PriceCache()
    rows = cache.all()
    dist = {"fresh": 0, "stale": 0, "expired": 0}
    for r in rows:
        lv = cache.freshness_of(r)["level"]
        dist[lv] = dist.get(lv, 0) + 1
    return {"total": len(rows), "distribution": dist}
