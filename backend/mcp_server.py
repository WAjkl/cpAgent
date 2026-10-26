# -*- coding: utf-8 -*-
"""cpAgent 的 MCP Server（stdio）。

把配置单生成能力按 MCP 协议暴露出去，任何支持 MCP 的客户端（Claude Desktop、
Cursor、Cherry Studio 等）都能直接当成一个工具调用，不用写 HTTP 客户端。

跑法：
    python -m backend.mcp_server

客户端侧配置（Claude Desktop / Cursor 的 mcpServers）：
    {
      "mcpServers": {
        "cpagent": {
          "command": "python",
          "args": ["-m", "backend.mcp_server"],
          "cwd": "<cpAgent 仓库根目录>"
        }
      }
    }

设计上的两条约束：
  1. 只暴露确定性能力（配置生成 / 预算校验 / 硬件查询），不暴露需要 LLM 的对话。
     原因：MCP 这一层是给别的 Agent 当工具用的，工具本身必须可复现，
     不能我调一次一个结果。
  2. 工具参数用扁平基础类型（number/str），不搞嵌套对象 —— 不同的客户端对
     JSON Schema 的支持程度不一样，扁平参数兼容性最好。
"""
import json
from typing import Any, Dict, List

from mcp.server.mcpserver import MCPServer

from .config_gen import generate_config
from .price_cache import PriceCache

mcp = MCPServer("cpAgent")

_cache: PriceCache = None


def _get_cache() -> PriceCache:
    global _cache
    if _cache is None:
        _cache = PriceCache()
        if _cache.count() == 0:
            _cache.seed_from_hardware_db()
    return _cache


def _summary(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """把一份配置单压成工具返回用的精简结构。

    完整结构有 6 个配件 × 20 个字段，直接塞给模型会挤掉别的上下文，
    所以只留"型号 + 价格 + 来源 + 新鲜度"，细节让调用方再查。
    """
    parts = cfg.get("parts", {})
    out_parts = []
    for cat, item in parts.items():
        if not isinstance(item, dict):
            continue
        out_parts.append({
            "category": cat,
            "model": item.get("model"),
            "price": item.get("price"),
            "source": item.get("price_source"),
            "fetched_at": item.get("fetched_at"),
            "confidence": item.get("confidence"),
            "level": item.get("level"),
        })
    return {
        "total_price": cfg.get("total_price"),
        "budget": cfg.get("budget"),
        "use_case": cfg.get("use_case"),
        "resolution": cfg.get("resolution"),
        "score": cfg.get("score"),
        "compatible": (cfg.get("compatibility") or {}).get("ok"),
        "problems": (cfg.get("compatibility") or {}).get("problems", []),
        "warnings": cfg.get("warnings", []),
        "parts": out_parts,
    }


@mcp.tool()
def generate_pc_config(budget: float, use_case: str = "gaming",
                       resolution: str = "", top_k: int = 1) -> str:
    """按预算生成电脑配置单。

    Args:
        budget: 预算，人民币，必须大于 0。
        use_case: 用途。支持 gaming（游戏）/ productivity（生产力）/ balanced（均衡）。
        resolution: 目标分辨率，如 "1080P" / "2K" / "4K"；不填则不限制。
        top_k: 返回几套方案。

    Returns:
        JSON 字符串：total_price / score / parts（每个配件带型号、价格、来源、
        抓取时间、置信度）/ warnings / problems。无可行解时返回 ok=false。
    """
    res = resolution or None
    cfgs = generate_config(float(budget), use_case, res, top_k=max(1, int(top_k)),
                           cache=_get_cache())
    if not cfgs:
        return json.dumps({
            "ok": False,
            "reason": "该预算/用途下无可行配置",
            "hint": "预算偏低，或分辨率要求把显卡卡死了；先调 check_budget 看下限",
            "budget": budget, "use_case": use_case, "resolution": res,
        }, ensure_ascii=False)
    return json.dumps({
        "ok": True,
        "count": len(cfgs),
        "configs": [_summary(c) for c in cfgs],
        "note": "价格带来源与抓取时间；level 为 expired 的配件装机前要刷新实时价",
    }, ensure_ascii=False)


@mcp.tool()
def check_budget(budget: float, resolution: str = "") -> str:
    """查一个预算能不能配出东西，以及能到什么性能档。

    给 Agent 用：先查可行性再决定要不要调 generate_pc_config，
    避免直接拿 422 当答案丢给用户。

    Args:
        budget: 预算，人民币。
        resolution: 目标分辨率，不填则不限制。

    Returns:
        JSON 字符串：feasible / 各用途下的分数与总价 / 预算利用率。
    """
    res = resolution or None
    rows: List[Dict[str, Any]] = []
    for uc in ("gaming", "productivity", "balanced"):
        cfgs = generate_config(float(budget), uc, res, top_k=1, cache=_get_cache())
        if not cfgs:
            rows.append({"use_case": uc, "feasible": False})
            continue
        c = cfgs[0]
        total = float(c.get("total_price") or 0)
        rows.append({
            "use_case": uc,
            "feasible": True,
            "total_price": total,
            "budget_usage_pct": round(total / float(budget) * 100, 1) if budget else None,
            "score": c.get("score"),
        })
    return json.dumps({
        "ok": True,
        "budget": budget,
        "resolution": res,
        "feasible": any(r.get("feasible") for r in rows),
        "by_use_case": rows,
    }, ensure_ascii=False)


@mcp.tool()
def list_hardware(category: str, limit: int = 5) -> str:
    """列硬件库里某个品类的候选，按价格升序。

    Args:
        category: cpu / gpu / memory / ssd / psu / motherboard。
        limit: 返回条数。

    Returns:
        JSON 字符串：型号、价格、关键参数。
    """
    from .config_gen import _load_db

    db = _load_db()
    items = db.get(category) or []
    if not items:
        return json.dumps({
            "ok": False,
            "reason": "未知品类",
            "available": [k for k in db.keys() if k != "meta"],
        }, ensure_ascii=False)

    def price(x):
        try:
            return float(x.get("price_cny") or 0)
        except (TypeError, ValueError):
            return 0.0

    items = sorted(items, key=price)[: max(1, int(limit))]
    return json.dumps({
        "ok": True,
        "category": category,
        "total_in_db": len(db.get(category) or []),
        "items": [{"model": i.get("model"), "price_cny": i.get("price_cny")} for i in items],
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()