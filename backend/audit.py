"""审计与成本归因：把每一次 LLM 调用和每一个高风险动作记成可查的账。

为什么需要它（企业视角，不是技术炫技）：
  行业调研里 79% 的企业在过去 12 个月经历过 AI 成本超支，85% 的企业对成本预估偏差超过 10%；
  而 Gartner 和 Forrester 都把「全链路审计追踪」列为企业级 AI 部署的基本门槛。
  企业最先问的三个问题不是「模型多聪明」，而是：
    1. 这次调用花了多少钱？谁花的？（成本账）
    2. 为什么给出这个结论？依据在哪？（责任账）
    3. 这个动作人批过吗？（责任账）

  已有 evidence.py 解决了「工具原始返回可追溯」，但没有成本维度。
  本模块补的就是成本 + 动作审批，两者用同一个 trace_id 串起来，
  一次查询就能还原「这一轮问了什么、调了什么、花了多少、谁批的」。

设计取舍：
  · 用 SQLite 单文件，不引入 Prometheus/ELK —— 个人项目上那套是负担，
    但表结构按生产口径设计，将来换存储只改这一层。
  · 审计失败绝不影响主流程（全部 try/except 吞掉并降级为日志），
    因为「记账」不能成为「业务」的单点故障。
"""
from __future__ import annotations

import contextvars
import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import AUDIT_DB_PATH

# 当前请求的追踪上下文。用 contextvars 而不是传参：
# llm.py / 工具层不必知道 session 的存在，set 一次就能被深层调用读到。
_trace_ctx: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "cpagent_trace", default={}
)

# 每百万 token 的人民币单价。DeepSeek 官方价会调整，所以做成可配，
# 并且允许在 config 里覆盖 —— 写死价格是审计系统最常见的坑：
# 价格一变，历史账目就对不上了。
DEFAULT_PRICES = {
    "deepseek-chat": {"in": 1.0, "out": 2.0},      # 元 / 百万 token
    "deepseek-reasoner": {"in": 4.0, "out": 16.0},
    "ollama": {"in": 0.0, "out": 0.0},             # 本地推理，电费不计
    "mock": {"in": 0.0, "out": 0.0},
}


def set_trace(session_id: str = "", turn_id: str = "", user_id: str = "local") -> str:
    """在请求入口调用一次，生成 trace_id 并绑定到当前上下文。"""
    trace_id = uuid.uuid4().hex[:12]
    _trace_ctx.set({"trace_id": trace_id, "session_id": session_id or "",
                    "turn_id": turn_id or "", "user_id": user_id})
    return trace_id


def current_trace() -> Dict[str, str]:
    return _trace_ctx.get() or {}


class AuditStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or AUDIT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init()

    def _init(self) -> None:
        c = self._conn
        # 每次 LLM 调用一行：成本账的原子单位
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_llm (
                id TEXT PRIMARY KEY,
                trace_id TEXT, session_id TEXT, turn_id TEXT, user_id TEXT,
                provider TEXT, model TEXT,
                prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
                cost_cny REAL, latency_ms INTEGER,
                ok INTEGER, error TEXT, created_at REAL
            )""")
        # 每个高风险动作一行：责任账里「人批没批」的凭据
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_action (
                id TEXT PRIMARY KEY,
                trace_id TEXT, session_id TEXT,
                action TEXT, risk_level TEXT,
                args_digest TEXT,
                decision TEXT,          -- auto / notify / require_approval
                approved INTEGER,        -- NULL=未决, 0=拒绝, 1=批准
                approved_by TEXT,
                created_at REAL
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_llm_trace ON audit_llm(trace_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_llm_session ON audit_llm(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_act_trace ON audit_action(trace_id)")
        self._conn.commit()

    # ---------- 写入 ----------
    def log_llm(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int,
                latency_ms: int, ok: bool = True, error: str = "") -> float:
        """记一次调用，返回本次成本（元）。异常一律吞掉，不影响业务。"""
        try:
            ctx = current_trace()
            pt, ct = int(prompt_tokens or 0), int(completion_tokens or 0)
            price = DEFAULT_PRICES.get(model) or DEFAULT_PRICES.get(provider) or {"in": 0, "out": 0}
            cost = (pt / 1e6) * price["in"] + (ct / 1e6) * price["out"]
            self._conn.execute(
                "INSERT INTO audit_llm (id,trace_id,session_id,turn_id,user_id,provider,model,"
                "prompt_tokens,completion_tokens,total_tokens,cost_cny,latency_ms,ok,error,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:16], ctx.get("trace_id", ""), ctx.get("session_id", ""),
                 ctx.get("turn_id", ""), ctx.get("user_id", "local"),
                 provider, model, pt, ct, pt + ct, cost, latency_ms,
                 1 if ok else 0, error[:300], time.time()),
            )
            self._conn.commit()
            return cost
        except Exception:
            return 0.0

    def log_action(self, action: str, risk_level: str, decision: str,
                   args: Optional[Dict[str, Any]] = None,
                   approved: Optional[bool] = None, approved_by: str = "") -> None:
        """记一个动作的审批结果。risk_level: read / write_reversible / write_irreversible"""
        try:
            ctx = current_trace()
            self._conn.execute(
                "INSERT INTO audit_action (id,trace_id,session_id,action,risk_level,args_digest,"
                "decision,approved,approved_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:16], ctx.get("trace_id", ""), ctx.get("session_id", ""),
                 action, risk_level,
                 json.dumps(args or {}, ensure_ascii=False, default=str),   # 存全量：批准后要按原参数执行，截断会丢参
                 decision, None if approved is None else (1 if approved else 0),
                 approved_by, time.time()),
            )
            self._conn.commit()
        except Exception:
            pass

    # ---------- 查询（成本账的三个视角）----------
    def cost_of_trace(self, trace_id: str) -> Dict[str, Any]:
        """查一轮对话的完整账单：花了多少、调了几次、用了什么模型。"""
        cur = self._conn.execute(
            "SELECT provider, model, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), "
            "SUM(cost_cny), AVG(latency_ms) FROM audit_llm WHERE trace_id=? GROUP BY provider, model",
            (trace_id,))
        rows = cur.fetchall()
        total = sum((r[5] or 0) for r in rows)
        return {"trace_id": trace_id, "total_cny": round(total, 6),
                "calls": sum(r[2] for r in rows), "by_model": [
                    {"provider": r[0], "model": r[1], "calls": r[2],
                     "prompt_tokens": r[3] or 0, "completion_tokens": r[4] or 0,
                     "cost_cny": round(r[5] or 0, 6), "avg_latency_ms": round(r[6] or 0)}
                    for r in rows]}

    def cost_of_session(self, session_id: str) -> Dict[str, Any]:
        cur = self._conn.execute(
            "SELECT COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(cost_cny) "
            "FROM audit_llm WHERE session_id=?", (session_id,))
        r = cur.fetchone()
        return {"session_id": session_id, "calls": r[0] or 0,
                "prompt_tokens": r[1] or 0, "completion_tokens": r[2] or 0,
                "total_cny": round(r[3] or 0, 6)}

    def overview(self, since_hours: int = 24) -> Dict[str, Any]:
        """近 N 小时总览：按模型、按会话、成功率。企业看板的第一屏。"""
        since = time.time() - since_hours * 3600
        cur = self._conn.execute(
            "SELECT provider, model, COUNT(*), SUM(cost_cny), AVG(latency_ms), "
            "SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) FROM audit_llm "
            "WHERE created_at>=? GROUP BY provider, model ORDER BY SUM(cost_cny) DESC", (since,))
        models = [{"provider": r[0], "model": r[1], "calls": r[2],
                   "cost_cny": round(r[3] or 0, 6), "avg_latency_ms": round(r[4] or 0),
                   "success_rate": round((r[5] or 0) / r[2], 3) if r[2] else 0}
                  for r in cur.fetchall()]
        total = sum(m["cost_cny"] for m in models)
        top = self._conn.execute(
            "SELECT session_id, COUNT(*), SUM(cost_cny) FROM audit_llm WHERE created_at>=? "
            "GROUP BY session_id ORDER BY SUM(cost_cny) DESC LIMIT 5", (since,)).fetchall()
        return {"window_hours": since_hours, "total_cny": round(total, 6),
                "total_calls": sum(m["calls"] for m in models),
                "by_model": models,
                "top_sessions": [{"session_id": s[0], "calls": s[1],
                                  "cost_cny": round(s[2] or 0, 6)} for s in top]}

    def pending_approvals(self) -> List[Dict[str, Any]]:
        """待人工确认的动作。渐进式自主里「必须人批」那档就靠它。"""
        cur = self._conn.execute(
            "SELECT id, trace_id, action, risk_level, args_digest, created_at "
            "FROM audit_action WHERE decision='require_approval' AND approved IS NULL "
            "ORDER BY created_at DESC LIMIT 20")
        return [{"id": r[0], "trace_id": r[1], "action": r[2], "risk_level": r[3],
                 "args": r[4], "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r[5]))}
                for r in cur.fetchall()]


# 全局单例：模块级拿同一个连接，避免每次调用都开库
_store: Optional[AuditStore] = None


def get_store() -> AuditStore:
    global _store
    if _store is None:
        _store = AuditStore()
    return _store
