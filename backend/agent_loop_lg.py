# -*- coding: utf-8 -*-
"""LangGraph 版 Agent 循环：与手写 AgentLoop 等价，用于对照实验。

为什么单独写一份：
    手写循环的好处是每一步的失败处理都能改（工具超时、模型给不存在的工具、
    步数跑满怎么收敛），代价是别人读你的代码要先理解你的控制流。
    LangGraph 把控制流显式化成「状态 + 节点 + 条件边」，团队协作时可读性更好。
    这里把同一套逻辑用 StateGraph 重写一遍，跑同一批输入比对输出，
    用来回答"你为什么不直接用框架"——因为两种我都写过，能说清各自的代价。

设计上刻意与原实现保持一致：
    工具注册表 / 系统提示 / LLM 接口 / 价格回溯校验 / 证据落盘 全部复用 AgentLoop，
    只有 for-step 循环被换成图。这样两边结果可比。

用法：
    from backend.agent_loop_lg import LangGraphLoop
    loop = LangGraphLoop(llm=my_llm)
    out = loop.run("8000 打游戏 2K 不要显示器")
"""
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .agent_loop import SYSTEM_PROMPT, AgentLoop


class AgentState(TypedDict, total=False):
    """图上流动的状态。只放"下一步需要看到的东西"，不放内部临时变量。"""
    messages: List[Dict[str, str]]      # 对话上下文（含工具观察）
    step: int                            # 已执行的决策轮次
    trace: List[Dict[str, Any]]          # 每步决策记录（与原实现同构）
    decision: Dict[str, Any]             # 本轮 LLM 输出
    tool_name: str
    tool_args: Dict[str, Any]
    answer: str
    config: Optional[Dict[str, Any]]
    evidence_ids: List[str]
    check_retries: int                   # 价格回溯失败重试次数（最多 1）
    status: str                          # running / done / max_steps
    session_id: str
    turn_id: str
    prefs: Dict[str, Any]                # 面板/文本提取出的预算、用途等


class LangGraphLoop:
    """用 StateGraph 表达 ReAct 循环。

    节点：
        decide   —— 问 LLM 要一步决策（action+args 或 answer）
        act      —— 执行工具，把摘要写回上下文
        verify   —— 回答前做价格回溯校验，失败可回 decide 修正一次
        settle   —— 收尾（正常答案 或 步数上限的诚实收敛）

    边：
        START → decide
        decide --有 action--> act → decide
        decide --有 answer--> verify --通过--> settle → END
                                       --失败且未重试--> decide
        decide --非法输出--> verify 之外的重问路径也走 decide
    """

    def __init__(self, llm=None, registry=None, agent_cfg=None,
                 llm_cfg=None, evidence=None):
        # 复用原实现的全部组件，保证对照公平
        self.core = AgentLoop(llm=llm, registry=registry,
                              agent_cfg=agent_cfg, llm_cfg=llm_cfg,
                              evidence=evidence)
        self.cfg = self.core.cfg
        self.graph = self._build()

    # ---------- 图构建 ----------
    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("decide", self._decide)
        g.add_node("act", self._act)
        g.add_node("verify", self._verify)
        g.add_node("settle", self._settle)

        g.add_edge(START, "decide")
        g.add_conditional_edges(
            "decide", self._after_decide,
            {"act": "act", "verify": "verify", "decide": "decide", "settle": "settle"},
        )
        g.add_edge("act", "decide")
        g.add_conditional_edges(
            "verify", self._after_verify,
            {"decide": "decide", "settle": "settle"},
        )
        g.add_edge("settle", END)

        # checkpointer 让同一 thread_id 的多轮对话保留状态（等价于原实现的 history 回灌）
        return g.compile(checkpointer=MemorySaver())

    # ---------- 节点 ----------
    def _decide(self, st: AgentState) -> Dict[str, Any]:
        step = st.get("step", 0) + 1
        messages = list(st.get("messages", []))
        trace = list(st.get("trace", []))

        if step > self.cfg.max_steps:
            return {"status": "max_steps", "step": step, "messages": messages, "trace": trace}

        input_tokens = self.core._estimate_tokens(messages)
        decision = self.core._ask_decision(messages, step)
        trace.append({"step": step, "decision": decision, "input_tokens": input_tokens})
        return {"step": step, "decision": decision, "trace": trace, "status": "running"}

    def _act(self, st: AgentState) -> Dict[str, Any]:
        messages = list(st.get("messages", []))
        trace = list(st.get("trace", []))
        evidence_ids = list(st.get("evidence_ids", []))
        decision = st.get("decision") or {}
        name = decision.get("action")
        args = self.core._apply_prefs_to_args(
            name, decision.get("action_input") or {}, st.get("prefs") or {})

        messages.append({"role": "assistant",
                         "content": __import__("json").dumps(decision, ensure_ascii=False)})

        tool = self.core.registry.get(name)
        if tool is None:
            messages.append({"role": "user",
                             "content": f"工具 {name} 不存在。注意：没有 final_answer 之类的结束工具"
                                        f"——配件查完后直接输出 answer 结束。请从可用工具中选择，只输出 JSON。"})
            return {"messages": messages, "trace": trace}

        try:
            raw = tool.invoke(args)
        except Exception as e:                       # 工具失败不炸图，回上下文让模型改
            messages.append({"role": "user",
                             "content": f"工具调用失败: {e}。请修正参数重试，或直接给出回答。只输出 JSON。"})
            return {"messages": messages, "trace": trace}

        # 证据落盘（原文）+ 净化 + 摘要进上下文
        ev_id = None
        if self.cfg.evidence_enabled:
            ev_id = self.core.evidence.record(
                st.get("session_id", ""), st.get("turn_id", ""), name, args, raw)
            evidence_ids.append(ev_id)

        from .sanitize import sanitize
        limit = 3000 if name == "web_fetch" else 800
        summary = self.core._summarize(name, sanitize(raw, max_str_len=limit))
        if ev_id:
            summary = f"{summary}\n[证据: {ev_id}]"

        messages.append({"role": "user",
                         "content": f"工具 {name} 返回（摘要）：\n{summary}"})
        trace[-1]["result"] = summary

        upd = {"messages": messages, "trace": trace, "evidence_ids": evidence_ids}
        if name == "generate_config" and isinstance(raw, dict) and raw.get("config"):
            upd["config"] = raw["config"]
        return upd

    def _verify(self, st: AgentState) -> Dict[str, Any]:
        """价格回溯校验：回答里的价格必须能对回工具返回。
        对不上先让模型改一次（防死循环），还不行就放行 + 审计标注。"""
        messages = list(st.get("messages", []))
        trace = list(st.get("trace", []))
        decision = st.get("decision") or {}
        answer = decision.get("answer", "")
        retries = st.get("check_retries", 0)

        price_map = []
        if self.cfg.evidence_enabled:
            price_map = self.core.evidence.search_prices(
                st.get("session_id", ""), st.get("turn_id", ""))

        from .evidence import verify_reply_prices
        budget = (st.get("prefs") or {}).get("budget")
        check = verify_reply_prices(answer, price_map,
                                    extra_known=[budget] if budget else None)
        trace[-1]["evidence_check"] = check

        if check["ok"]:
            return {"answer": answer, "trace": trace, "status": "done"}

        if retries < 1:
            messages.append({"role": "assistant",
                             "content": __import__("json").dumps(decision, ensure_ascii=False)})
            messages.append({"role": "user",
                             "content": f"校验发现以下价格无法回溯到工具返回：{check['unmatched']}。"
                                        f"请修正：要么引用工具返回的真实价格，要么明确标注'需核实'。只输出 JSON。"})
            return {"messages": messages, "check_retries": retries + 1,
                    "trace": trace, "status": "running"}

        note = (f"\n\n> ⚠️ 审计提示：以下数字未回溯到工具返回"
                f"（可能是预算/合计/差价等计算值或需核实项）：{check['unmatched']}")
        return {"answer": answer + note, "trace": trace, "status": "done"}

    def _settle(self, st: AgentState) -> Dict[str, Any]:
        """收尾。步数跑满时按原实现的策略诚实收敛，不硬编答案。"""
        trace = st.get("trace", [])
        if st.get("status") == "done" and st.get("answer"):
            return {}

        prefs = st.get("prefs") or {}
        if st.get("status") == "max_steps" and prefs.get("budget"):
            try:
                from .config_gen import generate_config
                cfgs = generate_config(prefs["budget"], prefs.get("use_case") or "gaming",
                                       prefs.get("resolution"), top_k=1)
                if cfgs:
                    c = cfgs[0]
                    rows = "\n".join(f"- {k}：{v.get('model')} ¥{v.get('price')}"
                                     for k, v in c["parts"].items())
                    msg = (f"已按你的需求生成配置单（预算 ¥{c['budget']:.0f}、用途 {c['use_case']}）"
                           f"总价 ¥{c['total_price']:.0f}：\n{rows}\n\n"
                           f"⚠️ estimate 配件为估算价，装机前需实时刷新。")
                    return {"answer": msg}
            except Exception:
                pass

        if any(t.get("decision", {}).get("action") for t in trace):
            return {"answer": "我尝试了联网搜索和本地库查询，但未能整理出完整答案。"
                              "你可以换个更具体的问题，或直接给我一个链接，我用 web_fetch 抓取后帮你整理。"}
        return {"answer": "抱歉，我尝试了多步仍未能完成（达到步数上限）。请补充信息，或换个问法。"}

    # ---------- 条件边 ----------
    def _after_decide(self, st: AgentState) -> str:
        if st.get("status") == "max_steps":
            return "settle"
        d = st.get("decision") or {}
        if d.get("action"):
            return "act"
        if d.get("answer"):
            return "verify"
        # 非法输出：提示重问（与原实现一样，靠下一轮纠正）
        return "decide"

    def _after_verify(self, st: AgentState) -> str:
        return "settle" if st.get("status") == "done" else "decide"

    # ---------- 对外入口 ----------
    def run(self, user_input: str, session_id: Optional[str] = None,
            turn_id: Optional[str] = None, prefs: Optional[Dict[str, Any]] = None,
            history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """与原 AgentLoop.run 同签名、同返回结构，便于直接对拍。"""
        import uuid

        session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        turn_id = turn_id or f"turn-{uuid.uuid4().hex[:8]}"

        from .memory import WorkingMemory
        mem = WorkingMemory(session_id=session_id)
        mem.update_prefs(user_input)
        for k, v in (prefs or {}).items():
            if v is not None:
                mem.prefs[k] = v
        mem.add_history("user", user_input)

        from .tool_registry import ToolRegistry
        mode = mem.prefs.get("mode", "snapshot")
        self.core.registry = ToolRegistry.default(web_enabled=(mode == "online"))

        from .router import route
        routing = route(user_input, self.core.llm if self.core.cfg.routing_enabled else None,
                        llm_routing=self.core.cfg.routing_enabled)
        if routing["type"] == "greeting":
            return self.core._finalize(
                session_id, turn_id, mem,
                "你好！我是装机顾问 👋 可以帮你：\n- 按预算/用途出配置单（比如「8000 打游戏 2K 不要显示器」）\n- 对比配件（比如「RTX 5060 和 RX 9070 哪个好」）\n- 答疑行情/兼容性\n\n想怎么配？",
                routing=routing, trace=[])

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT.replace("{tools}", self.core.registry.prompt_block())},
        ]
        if history:
            messages.append({"role": "user", "content": self.core._format_history(history)})
        messages.append({"role": "user",
                         "content": user_input + self.core._build_prefs_hint(mem.prefs)})

        init: AgentState = {
            "messages": messages, "step": 0, "trace": [], "decision": {},
            "evidence_ids": [], "check_retries": 0, "status": "running",
            "session_id": session_id, "turn_id": turn_id, "prefs": mem.prefs,
        }

        # recursion_limit：每个「决策+执行」算两步，留一点余量给校验回环
        cfg = {"configurable": {"thread_id": session_id},
               "recursion_limit": self.cfg.max_steps * 2 + 4}
        try:
            final = self.graph.invoke(init, cfg)
        except Exception as e:                      # 递归上限等异常 → 走同样的收敛
            if "recursion" in str(e).lower():
                final = dict(init, status="max_steps")
                final.update(self._settle(final))
            else:
                raise

        answer = final.get("answer") or ""
        mem.add_history("assistant", answer)
        timeout = final.get("status") == "max_steps"
        return self.core._finalize(session_id, turn_id, mem, answer, routing=routing,
                                   trace=final.get("trace", []),
                                   evidence_ids=final.get("evidence_ids", []),
                                   timeout=timeout, config=final.get("config"))
