"""问题类型路由：规则预分类 + LLM 判断交叉，冲突走保守路径（宁多问一句）。

架构文档 1 章：LLM 首个 Thought 判断问题类型。
工程落地（M1）：规则预分类（关键词，零成本）与 LLM 判断交叉；
冲突时走保守路径 clarify（多问一句，不误调工具）。

类型：
    recommend     —— 装机推荐（含预算/用途/分辨率等要素）
    compare       —— 配件对比（两个型号对比）
    qa            —— 答疑（价格趋势、规格解释、兼容性问答等）
    clarify       —— 信息不足，需要追问
    greeting      —— 打招呼/闲聊
    other         —— 其他
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# 规则预分类关键词
_RULES: Dict[str, list] = {
    "recommend": [
        "推荐", "装机", "配置", "配一台", "帮我配", "预算", "打游戏", "游戏机",
        "生产力", "设计", "剪辑", "渲染", "编程", "办公机", "整机", "多少钱能配",
        "2k", "4k", "1080p", "分辨率",
    ],
    "compare": [
        "对比", "哪个好", "选哪个", "vs", "还是", "比较", "区别", "差距",
    ],
    "qa": [
        "为什么", "是什么", "怎么选", "怎么看", "能装吗", "兼容", "够用吗",
        "值不值得", "涨", "降", "价格", "行情", "介绍", "科普",
    ],
    "greeting": [
        "你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "感谢",
    ],
    "clarify": [
        "?", "？", "帮我", "建议", "怎么办",
    ],
}


def rule_classify(text: str) -> str:
    """规则预分类：返回类型（或 other）。"""
    t = text.lower().strip()
    scores = {k: 0 for k in _RULES}
    for typ, kws in _RULES.items():
        for kw in kws:
            if kw.lower() in t:
                scores[typ] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def llm_classify(text: str, llm) -> str:
    """LLM 判断问题类型；失败返回 None（由上层按规则结果处理）。"""
    prompt = {
        "role": "user",
        "content": (
            "你是装机顾问的问题分类器。判断下面用户输入属于哪一类，只输出一个词：\n"
            "recommend=装机推荐(含预算/用途/分辨率要素) | compare=配件对比 | "
            "qa=答疑(行情/规格/兼容性解释) | clarify=信息不足需追问 | greeting=打招呼 | other=其他\n\n"
            f"用户输入：{text}\n输出："
        ),
    }
    try:
        out = llm.chat([prompt], temperature=0.0, max_tokens=16).strip().lower()
        for typ in ("recommend", "compare", "qa", "clarify", "greeting", "other"):
            if typ in out:
                return typ
    except Exception:
        pass
    return "other"


def route(text: str, llm=None, llm_routing: bool = True) -> Dict[str, str]:
    """路由入口。返回 {type, method}；method=rule/llm/fallback。"""
    rule = rule_classify(text)
    if not llm_routing or llm is None:
        return {"type": rule, "method": "rule"}
    llm_t = llm_classify(text, llm)
    if llm_t == "other" and rule != "other":
        # LLM 拿不准，信任规则
        return {"type": rule, "method": "rule"}
    if llm_t != rule and rule != "other":
        # 冲突：走保守路径 clarify（宁多问一句）
        return {"type": "clarify", "method": "conflict", "rule": rule, "llm": llm_t}
    return {"type": llm_t, "method": "llm"}
