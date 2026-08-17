"""vcp_live_price.py — videocardprices.com 真实 GPU 街价适配器（落地版）。

替代 cpAgent 原 browser_price.VideocardpricesAdapter（原版 fetch 直接 return None，
所有价格退化到 2026-08-13 快照）。本模块真实抓取首页、解析 19~28 款 GPU 的
最优美元价，按型号对齐后返回 live 源价格（带实时 fetched_at）。

设计要点：
- 复用 cpAgent 既有的 SSRF 白名单思想：仅请求 ALLOWED_DOMAINS 内的 URL。
- 解析失败 / 网络异常 → 返回 None，由 browser_price.search_price 自动降级到快照，
  绝不破坏现有链路（fail-safe）。
- 首页解析结果按 6h TTL 内存缓存，避免每次 fetch 重抓整页。
- 美元→人民币走 open.er-api.com 实时汇率，失败回退硬编码常量。

接入方式（见 集成说明.md）：把本文件放到 backend/，在 browser_price.py 顶部
`from .vcp_live_price import VideocardpricesAdapter` 替换原同名类即可，其余不变。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

# ---------- 配置 ----------
HOME_URL = "https://videocardprices.com/"
ALLOWED_DOMAINS = {"videocardprices.com", "open.er-api.com"}
FX_FALLBACK = 6.756905  # open.er-api.com 2026-08-13，仅作降级常量
CACHE_TTL = 6 * 3600     # 首页解析结果 6h 内复用
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cpAgent-price/1.0"

# 核心型号 token：用于把 "GIGABYTE AORUS GeForce RTX 5090 ..." 归一化成 "RTX5090"
_CORE = re.compile(
    r"(RTX\s?\d{3,4}(?:\s?(?:Ti|Super))?|RX\s?\d{3,4}(?:\s?XT)?|ARC\s?B\d{3})",
    re.I,
)
# 最优价（Best）链接：aria-label 含型号+渠道+价格，其后紧邻 >Best</span> 标记。
# 价格被 React 拆成 "$220<span>.<!-- -->00</span>"，故用 aria-label 里的完整价格字段。
_BEST_RE = re.compile(
    r'aria-label="([^"]*?) on (?:eBay|Amazon|Newegg) \([^)]*?\), \$(\d[\d,]*(?:\.\d{2})?)'
    r'.*?>Best</span>',
    re.S,
)


def _norm(model: str) -> str:
    """型号归一化：去空格大写 + 提取核心 token，便于跨源对齐。"""
    s = (model or "").upper().replace(" ", "")
    m = _CORE.search(s)
    return m.group(1).replace(" ", "") if m else s


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def _http_get(url: str, timeout: int = 15) -> str:
    if not is_allowed_url(url):
        raise ValueError(f"URL 不在白名单: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _usd_cny() -> float:
    """实时 USD→CNY 汇率；失败回退常量。"""
    try:
        raw = _http_get("https://open.er-api.com/v6/latest/USD")
        data = json.loads(raw)
        cny = data.get("rates", {}).get("CNY")
        if isinstance(cny, (int, float)):
            return float(cny)
    except Exception:
        pass
    return FX_FALLBACK


def _parse_vcp_home(html: str) -> Dict[str, Dict[str, Any]]:
    """解析首页：返回 {归一化型号: {"usd": float, "name": 原始短名}}。

    只取各卡带 "Best" 标记的最优价链接（aria-label 含型号+渠道+完整价格）。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for m in _BEST_RE.finditer(html):
        short_name = m.group(1).strip()
        try:
            usd = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        key = _norm(short_name)
        if key and key not in out:
            out[key] = {"usd": usd, "name": short_name}
    return out


class VideocardpricesAdapter:
    """真实 GPU 街价适配器（鸭子类型兼容 browser_price.PriceAdapter 接口）。"""

    name = "videocardprices"
    domains = ["videocardprices.com"]
    categories = ["gpu"]

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cached_at: float = 0.0

    def supports(self, category: str) -> bool:
        return category in self.categories

    def _ensure_loaded(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            now = time.time()
            if self._cache and (now - self._cached_at) < CACHE_TTL:
                return self._cache
            try:
                html = _http_get(HOME_URL, self.timeout)
                self._cache = _parse_vcp_home(html)
                self._cached_at = now
            except Exception:
                # 抓失败：保留旧缓存（若有），否则空 —— 上层会降级到快照
                pass
            return self._cache

    def fetch(self, model: str, category: str) -> Optional[Dict[str, Any]]:
        if category != "gpu":
            return None
        key = _norm(model)
        table = self._ensure_loaded()
        hit = table.get(key)
        if not hit:
            return None
        fx = _usd_cny()
        return {
            "model": model,
            "category": category,
            "price_cny": round(hit["usd"] * fx, 2),
            "price_low": round(hit["usd"] * fx, 2),
            "price_high": round(hit["usd"] * fx, 2),
            "source": "live",
            "confidence": 0.9,
            "fetched_at": time.time(),
        }


if __name__ == "__main__":
    # 本地验证：python vcp_live_price.py [本地html路径]
    # 不传路径则真实联网抓取。
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            html = f.read()
        table = _parse_vcp_home(html)
        print(f"[本地解析] 命中 {len(table)} 款 GPU：")
    else:
        a = VideocardpricesAdapter()
        # 触发一次真实抓取
        a._ensure_loaded()
        table = a._cache
        print(f"[真实抓取] 命中 {len(table)} 款 GPU，汇率≈{_usd_cny():.4f}：")
    fx = _usd_cny()
    for k, v in sorted(table.items(), key=lambda x: -x[1]["usd"]):
        print(f"  {v['name']:<28} ${v['usd']:>9.2f}  ≈ ¥{v['usd']*fx:>9.2f}")
