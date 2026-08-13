"""hardware-db 查询工具。

数据地基：data/hardware_db.json（v2.1，schema 统一）。
查询语义：
- 按 category 过滤
- 按 budget_min/max 过滤（price_cny 为区间字符串时取低值参与过滤）
- 按 use_case 排序（gaming 按 game 相关分、productivity 按生产力相关分）
- 返回结构化数据，携带 price_source/confidence（供证据锚定与 UI 新鲜度）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import HARDWARE_DB_PATH

# 缓存避免重复读盘
_db_cache: Optional[Dict[str, Any]] = None


def _load_db() -> Dict[str, Any]:
    global _db_cache
    if _db_cache is None:
        with open(HARDWARE_DB_PATH, encoding="utf-8") as f:
            _db_cache = json.load(f)
    return _db_cache


def _parse_price(price: Any) -> Optional[float]:
    """价格解析：数字直接返回；区间字符串 '34000-36800' 取低值；None 返回 None。"""
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    if isinstance(price, str):
        parts = [p.strip().replace(",", "") for p in price.split("-")]
        nums = [float(p) for p in parts if p.replace(".", "").isdigit()]
        return min(nums) if nums else None
    return None


def _sort_key(item: Dict[str, Any], use_case: Optional[str]) -> tuple:
    """排序键：优先按性能分（gaming/productivity 对应字段），兜底按价格。"""
    if use_case == "gaming":
        score = item.get("gaming_pct") or item.get("perf_pct") or item.get("ludashi_score") or 0
        return (0 - float(score),)
    if use_case == "productivity":
        score = item.get("prod_pct") or item.get("ludashi_score") or item.get("perf_pct") or 0
        return (0 - float(score),)
    # balanced：性能分 + 价格双键（性能优先，价格升序）
    score = item.get("gaming_pct") or item.get("perf_pct") or item.get("ludashi_score") or 0
    price = _parse_price(item.get("price_cny")) or 0
    return (0 - float(score), price)


def query_hardware_db(
    category: str,
    budget_max: Optional[float] = None,
    budget_min: Optional[float] = None,
    use_case: Optional[str] = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """查询硬件库。返回 {query, results, count, notice}。"""
    db = _load_db()
    if category not in db:
        raise ValueError(f"未知类别: {category}，可选 {list(db.keys())}")

    items = db[category]
    results: List[Dict[str, Any]] = []
    for it in items:
        price = _parse_price(it.get("price_cny"))
        if budget_min is not None and price is not None and price < budget_min:
            continue
        if budget_max is not None and price is not None and price > budget_max:
            continue
        results.append(it)

    # 排序
    results.sort(key=lambda it: _sort_key(it, use_case))
    results = results[:limit]

    return {
        "query": {
            "category": category,
            "budget_min": budget_min,
            "budget_max": budget_max,
            "use_case": use_case,
            "limit": limit,
        },
        "count": len(results),
        "results": results,
        "notice": (
            "estimate 条目为快照估算价，装机前必须实时刷新；"
            "所有价格均携带 price_source 与 fetched_at，禁止把 estimate 当实时价。"
        ),
    }


def get_hardware_summary() -> Dict[str, Any]:
    """硬件库整体摘要（答疑/澄清用）。"""
    db = _load_db()
    meta = db.get("meta", {})
    cats = {}
    for cat, items in db.items():
        if not isinstance(items, list):
            continue
        live = sum(1 for it in items if it.get("price_source") == "live")
        cats[cat] = {"count": len(items), "live": live, "estimate": len(items) - live}
    return {
        "meta": {
            "name": meta.get("name"),
            "version": meta.get("version"),
            "snapshot_date": meta.get("snapshot_date"),
            "currency": meta.get("currency"),
            "price_warning": meta.get("price_warning"),
        },
        "categories": cats,
        "total": sum(c["count"] for c in cats.values()),
    }
