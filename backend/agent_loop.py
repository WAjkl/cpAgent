"""ReAct 循环：思考→行动→观察→再思考，直到给出可回溯回答。

架构文档 1 章核心循环实现。
工程约束：
- max_steps 上限防死循环
- 工具原始返回完整落盘 evidence（证据锚定）；上下文只放摘要（压缩）
- 工具输出进 LLM 前做结构净化（防 prompt injection，M2 sanitize 层）
- LLM 输出非法 JSON 重试一次；再失败走规则兜底（诚实收敛，不编造）
- 最终回答做价格回溯校验（evidence.verify_reply_prices）
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import AgentConfig, LLMConfig
from .evidence import EvidenceStore, verify_reply_prices
from .llm import LLMError, MockProvider, resolve_provider
from .memory import WorkingMemory
from .router import route
from .sanitize import sanitize
from .tool_registry import ToolRegistry

SYSTEM_PROMPT = """你是「装机顾问」Agent，帮助用户配置电脑、回答硬件问题。

【幻觉铁律】
1. 所有价格、性能分、规格必须来自工具调用返回的数据；工具没返回的，禁止编造。
2. 回答中出现的每个价格，必须能在工具返回中找到对应型号；找不到就明确说"该型号无价格数据，需核实"。
3. estimate 数据（快照估算价）必须标注"估算价，装机前需实时刷新"；禁止把估算说成实时价。

【工作方式】
- 每次输出必须是单个 JSON 对象，二选一：
  A. 调用工具：{"thought": "分析", "action": "工具名", "action_input": {"参数": 值}}
  B. 最终回答：{"thought": "分析", "answer": "给用户的完整回答"}
- 工具参数必须符合工具 schema；一次只能调用一个工具。
- 需要多个数据时，先调用一个工具拿到结果，再继续下一步（可多次调用）。
- 没有 final_answer 之类的"结束工具"：所有配件查完后，直接输出 answer 结束。
- 回答用简体中文，结构清晰（可用表格/列表），价格标注来源与快照时间。
- ★ answer 不要重复完整配置单表格：配置单数据会由系统在下方卡片自动展示，answer 只需写「总价 ¥X，详见下方卡片」+ 一两句要点点评（如兼容性、升级建议）。避免把整套表格写进 answer 导致输出超长被截断。
- 装机推荐优先调用 generate_config 工具直接生成配置单，再基于返回结果回答。
- 需要实时行情/新品发布/新闻等本地库没有的最新信息时，调用 web_search 联网搜索，再挑选总结。
- 搜索到标题后如需看正文细节，可调用 web_fetch 抓取该 URL 的正文深入阅读。
- web_fetch 抓取失败或正文质量差时不要反复重试（最多试 2 次），优先基于已有的搜索摘要回答。

- 预算分配建议：显卡不超过总预算 50%，其余按 CPU>主板>内存>SSD>电源 分配；整机总价必须 ≤ 用户预算（估算价按区间低值计）。
- 如果工具返回 0 条，说明过滤条件太紧，放宽预算或改查其他类别。

【可用工具】
{tools}"""


class AgentLoop:
    def __init__(
        self,
        llm=None,
        registry: Optional[ToolRegistry] = None,
        agent_cfg: Optional[AgentConfig] = None,
        llm_cfg: Optional[LLMConfig] = None,
        evidence: Optional[EvidenceStore] = None,
    ):
        self.llm_cfg = llm_cfg or LLMConfig()
        self.llm = llm or resolve_provider(self.llm_cfg)
        self.registry = registry or ToolRegistry.default()
        self.cfg = agent_cfg or AgentConfig()
        self.evidence = evidence or EvidenceStore()

    # ---------- 主入口 ----------
    def run(self, user_input: str, session_id: Optional[str] = None, turn_id: Optional[str] = None, prefs: Optional[Dict[str, Any]] = None, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        turn_id = turn_id or f"turn-{uuid.uuid4().hex[:8]}"
        # 绑定追踪上下文：这一轮里所有 LLM 调用和工具调用都会挂到同一个 trace_id 上，
        # 之后才能回答「这一轮花了多少钱、为什么给这个结论」。必须在任何 LLM 调用之前。
        try:
            from .audit import set_trace
            set_trace(session_id=session_id, turn_id=turn_id)
        except Exception:
            pass
        mem = WorkingMemory(session_id=session_id)
        mem.update_prefs(user_input)
        # 合并前端面板传入的偏好（用户明确选过，覆盖文本提取）
        if prefs:
            for _k, _v in prefs.items():
                if _v is not None:
                    mem.prefs[_k] = _v
        mem.add_history("user", user_input)

        # 根据模式构建工具集（快照模式不联网；联网模式才注册 web_search/web_fetch）
        _mode = mem.prefs.get("mode", "snapshot")
        self.registry = ToolRegistry.default(web_enabled=(_mode == "online"))

        # 问题类型路由
        routing = route(user_input, self.llm if self.cfg.routing_enabled else None, llm_routing=self.cfg.routing_enabled)
        if routing["type"] == "greeting":
            return self._finalize(
                session_id, turn_id, mem,
                "你好！我是装机顾问 👋 可以帮你：\n- 按预算/用途出配置单（比如「8000 打游戏 2K 不要显示器」）\n- 对比配件（比如「RTX 5060 和 RX 9070 哪个好」）\n- 答疑行情/兼容性\n\n想怎么配？",
                routing=routing, trace=[],
            )

        # 元问题（你是谁/你能做什么/怎么用）：直接答能力，不进 ReAct 循环。
        # 必须在注入 prefs 之前短路——否则「你能做什么」会被记忆里的
        # 预算/用途带去跑一轮推荐，用户问能力却收到一份配置单。
        if routing["type"] == "meta":
            return self._finalize(
                session_id, turn_id, mem,
                "我是装机顾问，一个按预算和用途出配置单的 Agent。\n\n"
                "**能做的事**\n"
                "- 出配置单：给预算 + 用途 + 分辨率，比如「8000 打游戏 2K 不要显示器」，"
                "我会出 CPU / 显卡 / 主板 / 内存 / SSD / 电源整套，并做兼容性校验\n"
                "- 讲理由：为什么这么配、哪块能省、以后怎么升级\n"
                "- 对比配件：比如「RTX 5060 和 RX 9070 哪个好」\n"
                "- 答疑：行情趋势、规格解释、兼容性问题\n\n"
                "**关于价格**：具体型号和价格都来自硬件库，不是模型估的，"
                "所以配置单可以拿去店里核对。库里的快照价我每次都会标注来源和时间。\n\n"
                "**做不到的**：不带显示器外设的话我会说明；预算过低或条件冲突时，"
                "我会直接告诉你没有可行配置，不会硬凑一套。\n\n"
                "想配什么？说预算和用途就行。",
                routing=routing, trace=[],
            )

        # 把面板偏好明确写进给 LLM 的消息（否则 LLM 看不到面板选的预算/用途，会反问）
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT.replace("{tools}", self.registry.prompt_block())},
        ]
        # 跨轮回灌：上一轮对话摘要（多轮追问「再便宜点/换个显卡」不丢上下文）
        if history:
            messages.append({"role": "user", "content": self._format_history(history)})
        # 面板偏好只在真正要用到需求要素的问题上注入。
        # 无条件注入会让槽位绑架意图：用户问「你能做什么」，
        # 消息变成「你能做什么 + [预算100/游戏]」，模型就会当成新一轮推荐去答。
        _prefs_hint = (
            self._build_prefs_hint(mem.prefs)
            if routing["type"] in ("recommend", "compare", "qa", "clarify")
            else ""
        )
        messages.append({"role": "user", "content": user_input + _prefs_hint})
        trace: List[Dict[str, Any]] = []
        evidence_ids: List[str] = []
        check_retries = 0
        last_config = None

        for step in range(1, self.cfg.max_steps + 1):
            # 1) LLM 决策（JSON）；记录本步输入 token（可观测性，供对抗测试/排查）
            input_tokens = self._estimate_tokens(messages)
            decision = self._ask_decision(messages, step)
            trace.append({"step": step, "decision": decision, "input_tokens": input_tokens})

            if decision.get("action"):
                # 2) 执行工具（确定性注入：预算/用途来自 WorkingMemory，不让 LLM 乱算）
                tool_name = decision["action"]
                tool_args = decision.get("action_input") or {}
                tool = self.registry.get(tool_name)
                if tool is None:
                    messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                    messages.append({"role": "user", "content": f"工具 {tool_name} 不存在。注意：没有 final_answer 之类的结束工具——配件查完后直接输出 answer 结束。请从可用工具中选择，只输出 JSON。"})
                    continue
                tool_args = self._apply_prefs_to_args(tool_name, tool_args, mem.prefs)

                # 2.5) 风险闸（渐进式自主）
                # 企业落地最难的不是让 Agent 能干活，是给它划边界：
                #   只读       → 直接执行
                #   可逆写     → 执行 + 事后通知（审计里留痕，人能回溯）
                #   不可逆写   → 不执行，挂起等人工批准
                # 这一层必须是代码里的硬约束。靠提示词说"请谨慎"在生产环境等于没做：
                # 模型只要输出一次错误的 action，钱就花出去了，且不可回滚。
                _risk = getattr(tool, "risk_level", "read")
                try:
                    from .audit import get_store as _audit_store
                    if _risk == "write_irreversible":
                        _audit_store().log_action(tool_name, _risk, "require_approval",
                                                  tool_args, approved=None)
                        messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                        messages.append({"role": "user", "content":
                                         f"动作 {tool_name} 属于不可逆操作，已挂起等待人工批准，本次未执行。"
                                         f"请先用已有信息给出回答，并告知用户需要确认这一步。"})
                        trace.append({"step": step, "blocked_by_risk": tool_name, "risk_level": _risk})
                        continue
                    _audit_store().log_action(
                        tool_name, _risk,
                        "auto" if _risk == "read" else "notify",
                        tool_args, approved=True)
                except Exception:
                    pass

                try:
                    raw_result = tool.invoke(tool_args)
                except Exception as e:
                    messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                    messages.append({"role": "user", "content": f"工具调用失败: {e}。请修正参数重试，或直接给出回答。只输出 JSON。"})
                    continue

                # 3) 证据落盘（原文）+ 净化 + 摘要进上下文（压缩 + 防注入）
                ev_id = None
                if self.cfg.evidence_enabled:
                    ev_id = self.evidence.record(session_id, turn_id, tool_name, tool_args, raw_result)
                    evidence_ids.append(ev_id)
                if tool_name == "generate_config" and isinstance(raw_result, dict) and raw_result.get("config"):
                    last_config = raw_result["config"]
                safe = sanitize(raw_result) if tool_name != "web_fetch" else sanitize(raw_result, max_str_len=3000)
                summary = self._summarize(tool_name, safe)
                if ev_id:
                    summary = f"{summary}\n[证据: {ev_id}]"

                messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                messages.append({"role": "user", "content": f"工具 {tool_name} 返回（摘要）：\n{summary}"})
                trace[-1]["result"] = summary
                continue

            if decision.get("answer"):
                # 4) 输出校验（价格回溯；预算/合计视为已知计算值）
                price_map = self.evidence.search_prices(session_id, turn_id) if self.cfg.evidence_enabled else []
                check = verify_reply_prices(decision["answer"], price_map, extra_known=[mem.prefs.get("budget")] if mem.prefs.get("budget") else None)
                trace[-1]["evidence_check"] = check
                if not check["ok"] and check_retries < 1:
                    # 有无法回溯的价格 → 提醒一次让 LLM 修正（最多 1 次，防死循环）
                    check_retries += 1
                    unmatched = check["unmatched"]
                    messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                    messages.append({
                        "role": "user",
                        "content": f"校验发现以下价格无法回溯到工具返回：{unmatched}。请修正：要么引用工具返回的真实价格，要么明确标注'需核实'。只输出 JSON。",
                    })
                    continue
                if not check["ok"]:
                    # 仍无法回溯 → 放行 + 审计标注（监控不拦截，M4 对抗测试可据此判定）
                    answer = decision["answer"] + (
                        f"\n\n> ⚠️ 审计提示：以下数字未回溯到工具返回（可能是预算/合计/差价等计算值或需核实项）：{check['unmatched']}"
                    )
                else:
                    answer = decision["answer"]
                mem.add_history("assistant", answer)
                return self._finalize(session_id, turn_id, mem, answer, routing=routing, trace=trace, evidence_ids=evidence_ids, config=last_config)

            # 3) 非法 JSON/缺字段 → 提示重试
            messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
            messages.append({"role": "user", "content": "输出必须包含 action+action_input 或 answer 字段的 JSON 对象。只输出 JSON。"})

        # 达到 max_steps → 诚实收敛（不硬编）
        # 达到步数上限：recommend 且已有预算 → 确定性兜底生成配置单，不辜负已给信息
        if routing["type"] == "recommend" and mem.prefs.get("budget"):
            try:
                from .config_gen import generate_config
                _cfgs = generate_config(
                    mem.prefs["budget"],
                    mem.prefs.get("use_case") or "gaming",
                    mem.prefs.get("resolution"),
                    top_k=1,
                )
                if _cfgs:
                    _c = _cfgs[0]
                    _nl = chr(10)
                    _rows = _nl.join(f"- {_k}：{_v.get('model')} ¥{_v.get('price')}" for _k, _v in _c["parts"].items())
                    msg = (
                        f"已按你的需求生成配置单（预算 ¥{_c['budget']:.0f}、用途 {_c['use_case']}）总价 ¥{_c['total_price']:.0f}：{_nl}{_rows}{_nl}{_nl}"
                        f"⚠️ estimate 配件为估算价，装机前需实时刷新。"
                    )
                    mem.add_history("assistant", msg)
                    return self._finalize(session_id, turn_id, mem, msg, routing=routing, trace=trace, evidence_ids=evidence_ids, timeout=True)
            except Exception:
                pass

        # 其他场景：已调过工具（搜索/查库/抓取）但未收敛 → 诚实回答，不甩步数上限文案
        if trace and any(t.get("decision", {}).get("action") for t in trace):
            msg = "我尝试了联网搜索和本地库查询，但未能整理出完整答案。你可以换个更具体的问题，或直接给我一个链接，我用 web_fetch 抓取后帮你整理。"
            mem.add_history("assistant", msg)
            return self._finalize(session_id, turn_id, mem, msg, routing=routing, trace=trace, evidence_ids=evidence_ids, timeout=True)

        msg = "抱歉，我尝试了多步仍未能完成（达到步数上限）。请补充信息，或换个问法。"
        mem.add_history("assistant", msg)
        return self._finalize(session_id, turn_id, mem, msg, routing=routing, trace=trace, evidence_ids=evidence_ids, timeout=True)

    # ---------- 内部 ----------
    def _ask_decision(self, messages: List[Dict[str, str]], step: int) -> Dict[str, Any]:
        """让 LLM 输出决策 JSON。

        决策/回答分离 max_tokens：
        - 决策阶段（action JSON）用小上限 self.cfg.decision_max_tokens，几百 token 足够，
          避免超长输出把 JSON 撑爆、降低截断概率；
        - 若解析出 answer 但被截断（配置单/长回答写一半），用大上限
          self.llm_cfg.max_tokens 重试一次，抢救完整回答。
        失败重试 3 次（缓解偶发输出异常），再失败返回兜底。
        """
        last_err = None
        for attempt in range(3):
            try:
                raw = self.llm.chat(messages, temperature=0.2, max_tokens=self.cfg.decision_max_tokens)
                from .llm import parse_json_loose
                decision = parse_json_loose(raw)
                if decision.get("_truncated") and decision.get("answer") is not None:
                    # answer 被截断 → 用大上限重试一次生成完整回答
                    decision.pop("_truncated", None)
                    raw = self.llm.chat(messages, temperature=0.2, max_tokens=self.llm_cfg.max_tokens)
                    return parse_json_loose(raw)
                decision.pop("_truncated", None)
                return decision
            except LLMError as e:
                last_err = e
        return {"thought": f"LLM 输出异常: {last_err}", "answer": self._fallback_answer(messages)}

    def _fallback_answer(self, messages: List[Dict[str, str]]) -> str:
        """兜底回答：区分「真没配 LLM」和「LLM 输出异常」两种情况，不误导用户。"""
        if getattr(self.llm, "name", "") == "mock":
            return "当前未配置 LLM。请在设置里配置 DeepSeek API Key 后再试。"
        return "抱歉，我暂时无法正常响应（可能上下文过长或输出异常）。请换个问法，或简化问题后重试。"

    @staticmethod
    def _estimate_tokens(messages: List[Dict[str, str]]) -> int:
        """粗略估算 messages 的 token 数（用于 trace 可观测性，非精确计量）。

        中英文混合无法精确，这里按 2 字符 ≈ 1 token 折中，保证单调一致即可。
        """
        total = 0
        for m in messages:
            total += (len(m.get("content") or "") + 1) // 2
        return total

    @staticmethod
    def _format_history(history: List[Dict[str, str]]) -> str:
        """把上一轮对话摘要格式化成注入上下文的文本。"""
        lines = ["[以下是本对话前几轮的内容摘要，供你理解上下文、避免重复提问；其中出现的价格仅供参考，回答前如需价格请重新调用工具。]"]
        for m in history:
            role = "用户" if m.get("role") == "user" else "助手"
            lines.append(f"{role}: {m.get('content', '')}")
        return chr(10).join(lines)

    @staticmethod
    def _build_prefs_hint(prefs: Dict[str, Any]) -> str:
        """把面板偏好拼成给 LLM 的提示（明确告知，避免反问已选信息）。"""
        parts = []
        if prefs.get("budget"):
            parts.append(f"预算 {prefs['budget']} 元")
        if prefs.get("use_case"):
            _uc = {"gaming": "游戏", "productivity": "生产力", "balanced": "均衡"}.get(prefs["use_case"], prefs["use_case"])
            parts.append(f"用途 {_uc}")
        if prefs.get("resolution"):
            parts.append(f"分辨率 {prefs['resolution']}")
        if prefs.get("exclude"):
            parts.append("排除 " + "、".join(prefs["exclude"]))
        if prefs.get("mode") == "online":
            parts.append("联网模式")
        if not parts:
            return ""
        return chr(10) + chr(10) + "[用户已通过面板选定] " + "；".join(parts) + "。请直接据此生成/回答，不要再询问这些信息。"

    def _apply_prefs_to_args(self, tool_name: str, args: Dict[str, Any], prefs: Dict[str, Any]) -> Dict[str, Any]:
        """确定性注入：把 WorkingMemory 里已知的预算/用途/分辨率自动合并进工具参数。

        原则：LLM 可能算错预算、漏传参数；已知事实由确定性层兜底。
        - query_hardware_db：budget → budget_max；use_case 未传时注入
        - generate_config：budget/use_case/resolution 未传时注入
        """
        if tool_name == "query_hardware_db":
            out = dict(args)
            budget = prefs.get("budget")
            if budget:
                bmax = out.get("budget_max")
                if bmax is None or bmax > budget:
                    out["budget_max"] = budget
            use_case = prefs.get("use_case")
            if use_case and not out.get("use_case"):
                out["use_case"] = use_case
            return out
        if tool_name == "generate_config":
            out = dict(args)
            budget = prefs.get("budget")
            if budget and not out.get("budget"):
                out["budget"] = budget
            use_case = prefs.get("use_case")
            if use_case and not out.get("use_case"):
                out["use_case"] = use_case
            resolution = prefs.get("resolution")
            if resolution and not out.get("resolution"):
                out["resolution"] = resolution
            return out
        return args

    def _summarize(self, tool_name: str, raw_result: Any) -> str:
        """工具返回 → 上下文摘要（压缩 + 防注入净化：只保留结构化字段，截断长度）。"""
        if tool_name == "query_hardware_db":
            data = raw_result if isinstance(raw_result, dict) else {}
            results = data.get("results", [])[:20]  # 全部列出，避免 LLM 误判"型号不存在"
            if not results:
                return f"查询 {data.get('query', {}).get('category')} 返回 0 条（过滤条件太紧）。可放宽 budget 或查看全部条目。提示: {data.get('notice', '')[:100]}"
            lines = [f"查询 {data.get('query', {}).get('category')} 共 {data.get('count', 0)} 条:"]
            for it in results:
                price = it.get("price_cny")
                src = it.get("price_source", "?")
                conf = it.get("confidence", "?")
                extra = ""
                for k in ("cores_threads", "vram_gb", "capacity", "watt", "socket", "chipset"):
                    if it.get(k) is not None:
                        extra += f" {k}={it[k]}"
                lines.append(f"- {it.get('model')} | 价格={price} | 来源={src} conf={conf}{extra}")
            lines.append(f"提示: {data.get('notice', '')[:100]}")
            return "\n".join(lines)
        if tool_name == "get_hardware_summary":
            data = raw_result if isinstance(raw_result, dict) else {}
            return json.dumps(data, ensure_ascii=False)[:800]
        if tool_name == "search_price":
            data = raw_result if isinstance(raw_result, dict) else {}
            return (
                f"搜价 {data.get('model')}: 价格={data.get('price_cny')} "
                f"来源={data.get('source')} 新鲜度={data.get('level')} 降级={data.get('degraded')}"
            )
        if tool_name == "generate_config":
            data = raw_result if isinstance(raw_result, dict) else {}
            cfg = data.get("config")
            if not cfg:
                return f"配置生成失败: {data.get('reason', '未知原因')}"
            parts = cfg.get("parts", {})
            lines = [f"配置单 总价={cfg.get('total_price')} 用途={cfg.get('use_case')} 兼容={cfg.get('compatibility', {}).get('ok')}"]
            for k in ("cpu", "gpu", "motherboard", "memory", "ssd", "psu"):
                v = parts.get(k) or {}
                lines.append(f"- {k}: {v.get('model')} | 价格={v.get('price')} | 来源={v.get('price_source')}")
            if cfg.get("warnings"):
                lines.append("警告: " + "; ".join(cfg["warnings"][:3]))
            return "\n".join(lines)
        if tool_name == "web_fetch":
            data = raw_result if isinstance(raw_result, dict) else {}
            if not data.get("ok"):
                return f"抓取 {data.get('url')} 失败：{data.get('error')}"
            content = data.get("content") or ""
            length = data.get("length") or len(content)
            preview_len = 800  # 原文已落盘 evidence，上下文只放预览，防膨胀
            if len(content) > preview_len:
                return (
                    f"抓取 {data.get('url')} 正文（共 {length} 字，原文已落盘，仅预览前 {preview_len} 字）："
                    + chr(10) + content[:preview_len]
                    + chr(10) + "[内容过长已截断，请基于预览回答；如需原文细节可再抓取该 URL]"
                )
            return f"抓取 {data.get('url')} 正文（{length} 字）：" + chr(10) + content
        if tool_name == "web_search":
            data = raw_result if isinstance(raw_result, dict) else {}
            results = data.get("results", [])
            if not results:
                return f"搜索「{data.get('query')}」返回 0 条结果（可换个关键词重试）。"
            lines = [f"搜索「{data.get('query')}」共 {data.get('count', 0)} 条："]
            for it in results:
                lines.append(f"- {it.get('title')}\n  {it.get('url')}")
            return chr(10).join(lines)
        if tool_name == "get_price_summary":
            return json.dumps(raw_result, ensure_ascii=False, default=str)[:400]
        # 未知工具：仅保留 JSON 结构（丢弃叙述文本）
        try:
            return json.dumps(raw_result, ensure_ascii=False, default=str)[:800]
        except Exception:
            return str(raw_result)[:800]

    def _finalize(self, session_id, turn_id, mem, answer, routing=None, trace=None, evidence_ids=None, timeout=False, config=None) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "answer": answer,
            "routing": routing or {"type": "unknown", "method": "none"},
            "trace": trace or [],
            "evidence_ids": evidence_ids or [],
            "memory": mem.snapshot(),
            "timeout": timeout,
            "config": config,
        }
