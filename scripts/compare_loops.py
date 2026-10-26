# -*- coding: utf-8 -*-
"""手写 ReAct 循环 vs LangGraph 循环：同一批输入对拍。

为什么做这个：
    "为什么不用 LangGraph" 是 Agent 岗必问题。只回答"我自己写能控制细节"是嘴上的，
    跑一遍同一批 task、比对步数与答案，才算有证据。

对拍用什么模型：
    用 ScriptedLLM 回放固定的决策序列（不用真 LLM），这样两边输入完全一致、
    结果可复现，差异只可能来自"控制流写错没写错"。

跑法：
    python scripts/compare_loops.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent_loop import AgentLoop            # noqa: E402
from backend.config import AgentConfig              # noqa: E402
from backend.agent_loop_lg import LangGraphLoop     # noqa: E402
from backend.llm import LLMProvider                 # noqa: E402


class ScriptedLLM(LLMProvider):
    """按固定脚本返回决策 JSON，用完循环复用。让两条路吃到完全相同的模型输出。"""

    name = "scripted"

    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def chat(self, messages, temperature=0.2, max_tokens=1024) -> str:
        out = self.script[self.i % len(self.script)]
        self.i += 1
        return out


# 三个典型任务：正常两步、工具不存在要纠正、直接作答
TASKS = [
    {
        "name": "查CPU后作答",
        "input": "8000 打游戏 2K 不要显示器，先看看 CPU 有哪些",
        "script": [
            json.dumps({"action": "query_hardware_db",
                        "action_input": {"category": "cpu", "budget_max": 8000,
                                         "use_case": "gaming"}}, ensure_ascii=False),
            json.dumps({"answer": "按你的预算和用途，CPU 我从硬件库里筛了几颗，清单见上。"},
                       ensure_ascii=False),
        ],
    },
    {
        "name": "调用不存在的工具",
        "input": "8000 打游戏",
        "script": [
            json.dumps({"action": "no_such_tool", "action_input": {}}, ensure_ascii=False),
            json.dumps({"answer": "我先确认一下你的需求再给配置。"}, ensure_ascii=False),
        ],
    },
    {
        "name": "直接作答（不调工具）",
        "input": "你好",
        "script": [
            json.dumps({"answer": "你好，说下预算和用途我帮你配。"}, ensure_ascii=False),
        ],
    },
]


def run_one(cls, task):
    llm = ScriptedLLM(task["script"])
    # 关掉 LLM 路由：否则路由那一步会先吃掉一条脚本响应，两条路都一样被吃，
    # 但会让用例走不到工具调用，对拍就失去意义
    loop = cls(llm=llm, agent_cfg=AgentConfig(routing_enabled=False))
    out = loop.run(task["input"])
    return {
        "answer": out.get("answer", ""),
        "steps": len(out.get("trace", [])),
        "tools": [t.get("decision", {}).get("action")
                  for t in out.get("trace", []) if t.get("decision", {}).get("action")],
        "raw": out,
    }


def main():
    print("=" * 66)
    print("手写 ReAct 循环  vs  LangGraph StateGraph —— 同输入对拍")
    print("=" * 66)
    same = 0
    for t in TASKS:
        a = run_one(AgentLoop, t)
        b = run_one(LangGraphLoop, t)
        ok = (a["answer"] == b["answer"] and a["steps"] == b["steps"]
              and a["tools"] == b["tools"])
        same += ok
        print("\n[%s]" % t["name"])
        print("  手写      步数 %d ｜ 工具 %s" % (a["steps"], a["tools"] or "无"))
        print("  LangGraph 步数 %d ｜ 工具 %s" % (b["steps"], b["tools"] or "无"))
        print("  答案一致：%s" % ("是" if a["answer"] == b["answer"] else "否"))
        if a["answer"] != b["answer"]:
            print("    手写      : %s" % a["answer"][:70])
            print("    LangGraph : %s" % b["answer"][:70])
        print("  判定：%s" % ("✅ 一致" if ok else "❌ 不一致"))

    print("\n" + "=" * 66)
    print("结果：%d / %d 个任务两条路行为一致" % (same, len(TASKS)))
    print("=" * 66)
    return 0 if same == len(TASKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
