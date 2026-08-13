"""证据锚定：工具原始返回完整落盘 SQLite，回复中每个价格可回溯到原始记录。

架构文档 4.1 铁律：工具没返回的，禁止 LLM 填充。
实现：
1. 每次工具调用，原始返回整体落盘 evidence 表（JSON 快照 + 时间戳 + 会话/轮次）
2. 上下文只放摘要（由 agent_loop 控制）
3. 输出校验：从最终回复中提取价格数字，核对是否都能回溯到 evidence 记录；
   找不到来源的断言 → 标记 hallucination 风险（M4 对抗测试用）
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import EVIDENCE_DB_PATH


class EvidenceStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or EVIDENCE_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                turn_id TEXT,
                tool_name TEXT,
                tool_args TEXT,
                raw_result TEXT,
                created_at REAL
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        session_id: str,
        turn_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        raw_result: Any,
    ) -> str:
        """记录一次工具原始返回；返回证据 id。"""
        ev_id = uuid.uuid4().hex[:16]
        self._conn.execute(
            "INSERT INTO evidence (id, session_id, turn_id, tool_name, tool_args, raw_result, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                ev_id,
                session_id,
                turn_id,
                tool_name,
                json.dumps(tool_args, ensure_ascii=False),
                json.dumps(raw_result, ensure_ascii=False, default=str),
                time.time(),
            ),
        )
        self._conn.commit()
        return ev_id

    def get(self, ev_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM evidence WHERE id=?", (ev_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self._conn.execute("SELECT * FROM evidence WHERE id=?").description]
        return dict(zip(cols, row))

    def search_prices(self, session_id: str, turn_id: str) -> List[Dict[str, Any]]:
        """取该轮次全部工具返回中的 {model: price_cny} 映射（供输出校验）。"""
        rows = self._conn.execute(
            "SELECT tool_name, raw_result FROM evidence WHERE session_id=? AND turn_id=?",
            (session_id, turn_id),
        ).fetchall()
        price_map: List[Dict[str, Any]] = []
        for tool_name, raw_json in rows:
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            if tool_name == "query_hardware_db":
                for it in data.get("results", []):
                    price_map.append({
                        "model": it.get("model"),
                        "price": it.get("price_cny"),
                        "source": it.get("price_source"),
                        "confidence": it.get("confidence"),
                    })
            elif tool_name == "generate_config":
                # 配置单：提取各配件价格 + 总价
                cfg = data.get("config") or {}
                for part in (cfg.get("parts") or {}).values():
                    if isinstance(part, dict):
                        price_map.append({
                            "model": part.get("model"),
                            "price": part.get("price") or part.get("price_cny"),
                            "source": part.get("price_source"),
                            "confidence": part.get("confidence"),
                        })
            elif tool_name == "search_price":
                price_map.append({
                    "model": data.get("model"),
                    "price": data.get("price_cny"),
                    "source": data.get("source"),
                    "confidence": data.get("confidence"),
                })
        return price_map


# 价格数字提取（用于回复校验）：匹配 ¥1234 / 1234元 / 1234（裸数字）
_PRICE_RE = re.compile(r"¥\s?([\d,]+)|([\d,]+)\s*元")


def extract_prices(text: str) -> List[float]:
    out = []
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        out.append(float(raw.replace(",", "")))
    return out


def verify_reply_prices(reply: str, price_map: List[Dict[str, Any]], extra_known: Optional[List[float]] = None) -> Dict[str, Any]:
    """校验回复中的价格是否都能回溯到证据。

    已知集合 = 证据价格 ∪ 用户预算等已知值 ∪ 证据价格全和（合计）。
    注意：回复可能含「预算/合计/价差」等计算值，这里只做风险提示；
    无法解释的数字进 unmatched。"""
    reply_prices = extract_prices(reply)
    evidence_prices = set()
    for p in price_map:
        # 区间字符串取低值/高值
        if isinstance(p["price"], str):
            parts = [x.strip().replace(",", "") for x in p["price"].split("-")]
            nums = [float(x) for x in parts if x.replace(".", "").isdigit()]
            if nums:
                evidence_prices.add(min(nums))
                if len(nums) > 1:
                    evidence_prices.add(max(nums))
        elif isinstance(p["price"], (int, float)):
            evidence_prices.add(float(p["price"]))
    known = set(evidence_prices)
    for x in (extra_known or []):
        known.add(float(x))
    # 合计（全部证据价格之和）也视为可解释计算值
    if evidence_prices:
        known.add(round(sum(evidence_prices), 2))
    unmatched = [p for p in reply_prices if p not in known and p > 100]
    return {
        "ok": len(unmatched) == 0,
        "unmatched": unmatched,
        "evidence_count": len(evidence_prices),
        "reply_prices": reply_prices,
    }
