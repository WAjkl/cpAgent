"""工具输出净化层（防 prompt injection）。

架构 M2 任务 2.5。所有工具返回进 LLM 前必须经过净化：
1. 字符串截断 + 危险指令模式剥离（防网页文本注入 LLM）
2. 结构长度上限（list/dict 条数、递归深度），防爆上下文
3. 只保留结构化数据（str/int/float/bool/None/dict/list），其余转 str

与 agent_loop._summarize 的关系：_summarize 负责"压缩为上下文摘要"，
本模块负责"进 LLM 前的安全净化"——所有工具原始返回（尤其 browser-price
抓取的网页内容）在序列化给 LLM 前先 sanitize，从根上阻断注入。
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

# 危险指令模式（prompt injection 特征），命中即替换为 [filtered]
DANGER_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?previous", re.I),
    re.compile(r"do\s+not\s+follow\s+(the\s+)?(above\s+)?instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(a\s+)?different", re.I),
    re.compile(r"system\s*(message|prompt|role)?\s*:", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>", re.I),
    re.compile(r"\[system\]", re.I),
    re.compile(r"assistant\s*:\s*", re.I),
    re.compile(r"forget\s+(all\s+)?your\s+(rules|instructions|prompt)", re.I),
]

# 默认上限
DEFAULT_MAX_STR = 200
DEFAULT_MAX_ITEMS = 50
DEFAULT_MAX_DEPTH = 6


def sanitize_string(s: str, max_len: int = DEFAULT_MAX_STR) -> str:
    """字符串净化：危险模式剥离 + 长度截断。"""
    if not isinstance(s, str):
        s = str(s)
    for pat in DANGER_PATTERNS:
        s = pat.sub("[filtered]", s)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s


def sanitize(
    data: Any,
    max_str_len: int = DEFAULT_MAX_STR,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_depth: int = DEFAULT_MAX_DEPTH,
    _depth: int = 0,
) -> Any:
    """递归净化工具输出：只保留结构化类型，剥离危险文本，限制体积。

    规则：
    - str → sanitize_string（剥离注入 + 截断）
    - dict → 逐个 key/value 递归（key 也走字符串净化）
    - list → 截断条数后逐项递归
    - int/float/bool/None → 原样保留
    - 其他类型（对象等）→ str 后净化
    """
    if _depth >= max_depth:
        return "[depth-limit]"
    if isinstance(data, str):
        return sanitize_string(data, max_str_len)
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            kk = sanitize_string(str(k), 100)
            out[kk] = sanitize(v, max_str_len, max_items, max_depth, _depth + 1)
        return out
    if isinstance(data, (list, tuple)):
        return [sanitize(v, max_str_len, max_items, max_depth, _depth + 1) for v in list(data)[:max_items]]
    if isinstance(data, (int, float, bool)) or data is None:
        return data
    # 其他类型：转 str 净化
    return sanitize_string(str(data), max_str_len)


def sanitize_with_whitelist(
    data: Any,
    field_whitelist: Optional[set],
    max_str_len: int = DEFAULT_MAX_STR,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> Any:
    """按字段白名单净化（只保留 schema 字段，丢弃叙述文本）。

    field_whitelist: 顶层允许保留的字段名集合（None 表示不限制）。
    用于 query_hardware_db 等结构化工具：只留 model/price_cny 等，丢弃 notice 等叙述。
    """
    if isinstance(data, dict) and field_whitelist is not None:
        filtered = {k: v for k, v in data.items() if k in field_whitelist}
        return sanitize(filtered, max_str_len=max_str_len, max_items=max_items)
    return sanitize(data, max_str_len=max_str_len, max_items=max_items)
