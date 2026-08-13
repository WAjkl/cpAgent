"""长期记忆（SQLite）：用户偏好 + 历史配置单，跨会话持久化。

架构 M2 任务 2.4。与短期 WorkingMemory（对话内）互补：
- sessions 表：会话级偏好（预算/用途/分辨率/排除），跨轮次、跨会话可召回
- configs 表：历史配置单（M3 前端「历史配置库」直接读这里）

关键能力："第二次对话记得上次预算偏好"——新会话可从最近会话召回
默认偏好，作为确定性注入的兜底。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import LONGTERM_MEMORY_PATH


class LongTermMemory:
    """长期记忆（SQLite）。线程内单连接，写即 commit。"""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or LONGTERM_MEMORY_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_prefs TEXT,
                updated_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS configs (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                config TEXT,
                total_price REAL,
                use_case TEXT,
                created_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dialogue (
                session_id TEXT PRIMARY KEY,
                history TEXT,
                updated_at REAL
            )
            """
        )
        self._conn.commit()

    # ---------- 偏好 ----------
    def remember_prefs(self, session_id: str, prefs: Dict[str, Any]) -> None:
        """保存/更新会话偏好（合并覆盖）。"""
        existing = self.recall_prefs(session_id) or {}
        merged = {**existing, **{k: v for k, v in prefs.items() if v not in (None, "", [])}}
        self._conn.execute(
            "INSERT INTO sessions (session_id, user_prefs, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET user_prefs=excluded.user_prefs, updated_at=excluded.updated_at",
            (session_id, json.dumps(merged, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def recall_prefs(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT user_prefs FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def recall_latest_prefs(self) -> Optional[Dict[str, Any]]:
        """跨会话召回最近一次偏好（"第二次对话记得上次预算"）。"""
        row = self._conn.execute(
            "SELECT user_prefs FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    # ---------- 对话历史（跨轮回灌） ----------
    def remember_dialogue(self, session_id: str, history: List[Dict[str, str]], max_turns: int = 3) -> None:
        """追加本轮对话并截断到最近 max_turns 轮（每轮 user/assistant 两条），供下一轮注入上下文。"""
        trimmed: List[Dict[str, str]] = []
        for m in history[-max_turns * 2:]:
            trimmed.append({
                "role": m.get("role", "user"),
                "content": (m.get("content") or "")[:500],
            })
        self._conn.execute(
            "INSERT INTO dialogue (session_id, history, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET history=excluded.history, updated_at=excluded.updated_at",
            (session_id, json.dumps(trimmed, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def recall_dialogue(self, session_id: str) -> List[Dict[str, str]]:
        row = self._conn.execute(
            "SELECT history FROM dialogue WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return []
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return []

    # ---------- 历史配置 ----------
    def save_config(self, session_id: str, config: Dict[str, Any]) -> str:
        cfg_id = config.get("id") or f"cfg-{uuid.uuid4().hex[:10]}"
        self._conn.execute(
            "INSERT INTO configs (id, session_id, config, total_price, use_case, created_at) VALUES (?,?,?,?,?,?)",
            (
                cfg_id,
                session_id,
                json.dumps(config, ensure_ascii=False, default=str),
                float(config.get("total_price") or 0),
                config.get("use_case") or "",
                time.time(),
            ),
        )
        self._conn.commit()
        return cfg_id

    def list_configs(self, session_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if session_id:
            rows = self._conn.execute(
                "SELECT config FROM configs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT config FROM configs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for (raw,) in rows:
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out

    def get_config(self, cfg_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT config FROM configs WHERE id=?", (cfg_id,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT session_id, user_prefs, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for sid, prefs, ts in rows:
            try:
                p = json.loads(prefs)
            except (json.JSONDecodeError, TypeError):
                p = {}
            out.append({"session_id": sid, "prefs": p, "updated_at": ts})
        return out
