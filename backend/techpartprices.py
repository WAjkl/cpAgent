"""techpartprices.py — techpartprices.com 公开 JSON API 适配器（Amazon UK 实时价）。

为 pc-build-mcp / cpAgent 补齐 CPU / 内存 / SSD / 主板 的真实实时价源
（GPU 已有 videocardprices.com）。techpartprices.com 提供公开只读 JSON API：
- 免费、无需 key / 注册（端点目录 /.well-known/api-catalog，llms.txt 公开说明）
- 覆盖 cpu / gpu / ram / storage / motherboard（Amazon UK 全新含税价，每天多次更新）
- 价格字段 priceGbp（英镑小数）；currentPrice 为便士（GBP pence）

设计要点（沿用 vcp_live_price 的既有约定）：
- 仅请求白名单域名（SSRF 防护）
- 型号按 q= 搜索，取「品类匹配 + 有库存 + 名称含型号核心 token」的首条
- GBP→CNY 走 open.er-api.com 实时汇率（1h 模块级缓存），失败回退常量
- 6h 内存缓存 TTL；任何异常返回 None → 上层降级到 hardware_db 快照（fail-safe）
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# ---------- 配置 ----------
API_BASE = "https://techpartprices.com/api/products"
ALLOWED_DOMAINS = {"techpartprices.com", "open.er-api.com"}
FX_FALLBACK_GBP = 9.12  # GBP→CNY 降级常量（2026-08 参考；实时汇率优先）
CACHE_TTL = 6 * 3600     # 型号搜索结果 6h 内复用
FX_CACHE_TTL = 3600      # 汇率 1h 内复用，避免每次 fetch 都请求汇率接口
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cpAgent-price/1.1"

# cpAgent 品类 → techpartprices API 可能的 category 字段值（集合）
# 实测：SSD 品类在 API 里可能是 ssd / nvme / hdd / external；内存是 ram
_CATEGORY_MAP = {
    "gpu": {"gpu"},
    "cpu": {"cpu"},
    "memory": {"ram", "memory"},
    "ssd": {"ssd", "nvme", "hdd", "external"},
    "motherboard": {"motherboard"},
}

_FX_LOCK = threading.Lock()
_FX: Dict[str, float] = {"value": 0.0, "at": 0.0}


def _norm(s: str) -> str:
    """大写去空格，便于 token 包含匹配。"""
    return (s or "").upper().replace(" ", "")


# 品牌/系列停用词：不作为型号核心 token 用于匹配（防止 "INTEL" 这类泛词命中错误型号）
_STOPWORDS = {
    "INTEL", "AMD", "NVIDIA", "CORSAIR", "SAMSUNG", "ASUS", "GIGABYTE", "MSI",
    "KINGSTON", "CRUCIAL", "SABRENT", "SEAGATE", "WESTERNDIGITAL", "WD", "PNY",
    "G.SKILL", "TEAMGROUP", "ADATA", "LEXAR", "SILICONPOWER", "PATRIOT", "ZOTAC",
    "POWERCOLOR", "SAPPHIRE", "RYZEN", "CORE", "GEFORCE", "RADEON", "GAMING",
    "PROCESSOR", "DESKTOP", "SOCKET", "WIFI", "DDR4", "DDR5", "PCIE", "M.2",
}


def _main_token(model: str) -> Optional[str]:
    """取型号里最有区分度的核心 token（优先含数字的最长 token，排除品牌停用词）。

    在带空格的原始字符串上提取（避免去空格把品牌+型号粘成一个 token）。
    例如：'Intel Core i5-14600K' → I5-14600K；'Corsair 32GB DDR5' → 32GB；
          'Samsung 990 PRO 2TB' → 990；'ASUS B650' → B650；'RTX 5070' → 5070。
    """
    s = (model or "").upper()
    toks = re.findall(r"[A-Z0-9][A-Z0-9-]{2,}", s)
    toks = [t for t in toks if t not in _STOPWORDS]
    if not toks:
        return None
    digit_toks = [t for t in toks if any(c.isdigit() for c in t)]
    pool = digit_toks or toks
    return max(pool, key=len)


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


def _gbp_cny() -> float:
    """实时 GBP→CNY 汇率（1h 缓存）；失败回退常量。"""
    now = time.time()
    with _FX_LOCK:
        if _FX["value"] and (now - _FX["at"]) < FX_CACHE_TTL:
            return _FX["value"]
    try:
        raw = _http_get("https://open.er-api.com/v6/latest/GBP")
        data = json.loads(raw)
        cny = data.get("rates", {}).get("CNY")
        if isinstance(cny, (int, float)) and cny > 0:
            with _FX_LOCK:
                _FX["value"] = float(cny)
                _FX["at"] = now
            return float(cny)
    except Exception:
        pass
    return FX_FALLBACK_GBP


class TechPartPricesAdapter:
    """techpartprices.com 公开 API 适配器（鸭子类型兼容 PriceAdapter 接口）。

    categories 含 gpu：GPU 的默认源仍是 videocardprices（注册顺序在前），
    本适配器作为 GPU 的第二备选，以及 cpu/memory/ssd/motherboard 的主源。
    """

    name = "techpartprices"
    domains = ["techpartprices.com"]
    categories = ["gpu", "cpu", "memory", "ssd", "motherboard"]

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}  # model_norm → quote
        self._cached_at: float = 0.0

    def supports(self, category: str) -> bool:
        return category in self.categories

    def _search(self, model: str, limit: int = 50) -> List[Dict[str, Any]]:
        url = API_BASE + "?q=" + urllib.parse.quote(model) + f"&limit={limit}"
        raw = _http_get(url, self.timeout)
        return (json.loads(raw).get("products") or [])

    def _search_candidates(self, model: str) -> List[Dict[str, Any]]:
        """按候选词依次搜索，返回第一个非空结果集（q 是词 AND 匹配，多词易 0 条）。

        候选：① 型号原文 → ② 去连字符（i5-14600K→i5 14600K）→ ③ 核心 token
        → ④ 品牌词。命中即停，控制请求数。
        """
        token = _main_token(model)
        brand = (model or "").strip().split()[0] if (model or "").strip() else None
        cands = [model]
        if model and "-" in model:
            cands.append(model.replace("-", " "))
        if token:
            cands.append(token)
        if brand and brand.lower() != (model or "").lower():
            cands.append(brand)
        seen: List[Dict[str, Any]] = []
        for q in cands:
            try:
                ps = self._search(q)
            except Exception:
                continue
            if ps:
                seen = ps
                break
        return seen

    def fetch(self, model: str, category: str) -> Optional[Dict[str, Any]]:
        api_cats = _CATEGORY_MAP.get(category)
        if not api_cats:
            return None
        key = _norm(model)

        # 1) 内存缓存命中
        with self._lock:
            now = time.time()
            if key in self._cache and (now - self._cached_at) < CACHE_TTL:
                return dict(self._cache[key])

        # 2) 联网搜索（候选词序列）
        products = self._search_candidates(model)
        if not products:
            return None  # fail-safe：交给上层降级到快照

        token = _main_token(model)
        best: Optional[Dict[str, Any]] = None
        for p in products:
            if p.get("category") not in api_cats:
                continue
            # 只在明确无货时跳过（inStock 可能是 int 1/0 或 bool）
            if p.get("inStock") is False or p.get("inStock") == 0:
                continue
            gbp = p.get("priceGbp")
            if gbp is None and isinstance(p.get("currentPrice"), (int, float)):
                gbp = p["currentPrice"] / 100.0  # currentPrice 是便士
            if not isinstance(gbp, (int, float)) or gbp <= 0:
                continue
            name = p.get("name") or ""
            if token and token not in _norm(name):
                continue  # 名称必须含型号核心 token，防止候选词带回近似型号
            best = p
            break
        if best is None:
            return None

        gbp = float(best["priceGbp"]) if isinstance(best.get("priceGbp"), (int, float)) else float(best["currentPrice"]) / 100.0
        cny = round(gbp * _gbp_cny(), 2)
        quote: Dict[str, Any] = {
            "model": model,
            "category": category,
            "price_cny": cny,
            "price_low": cny,
            "price_high": cny,
            "source": "live",
            "confidence": 0.9,
            "fetched_at": time.time(),
        }
        with self._lock:
            self._cache[key] = dict(quote)
            self._cached_at = time.time()
        return quote


if __name__ == "__main__":
    # 本地验证：python backend/techpartprices.py "Ryzen 7 7800X3D"
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "Ryzen 7 7800X3D"
    cat = sys.argv[2] if len(sys.argv) > 2 else "cpu"
    a = TechPartPricesAdapter()
    r = a.fetch(q, cat)
    if r:
        print(f"OK {cat}: {q} -> ¥{r['price_cny']} (source={r['source']})")
    else:
        print(f"MISS {cat}: {q} -> 无匹配（将降级到快照）")
