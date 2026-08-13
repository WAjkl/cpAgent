"""短期工作记忆（对话内）：保存用户偏好/预算/已提要素，供多轮使用。

架构文档 2.4 记忆系统：短期（对话内）+ 长期（M2 SQLite）。
M1 实现短期：WorkingMemory 维护 user_prefs（预算区间/用途/分辨率/排除配件），
由 agent_loop 每轮从用户输入提取并合并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WorkingMemory:
    session_id: str
    prefs: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, str]] = field(default_factory=list)  # 最近的对话消息（摘要级）

    def update_prefs(self, text: str) -> None:
        """从用户输入提取要素并入 prefs。M1 简单规则提取。"""
        t = text.lower()
        # 预算：数字+单位/关键词，或 关键词+数字，或 句首纯数字（"8000 打游戏"）
        m = re.search(r"(\d{3,6})\s*(?:元|块|k\b|预算)", t)
        if not m:
            m = re.search(r"(?:预算|不超过|以内|以下)\s*(\d{3,6})", t)
        if not m:
            m = re.match(r"^\s*(\d{3,6})(?![0-9])", t)
        if m:
            val = int(m.group(1))
            if val < 100:
                val *= 1000  # 8k → 8000
            self.prefs["budget"] = val
        # 用途
        if any(k in t for k in ("游戏", "打游戏", "gaming")):
            self.prefs["use_case"] = "gaming"
        elif any(k in t for k in ("生产力", "设计", "剪辑", "渲染", "编程", "production")):
            self.prefs["use_case"] = "productivity"
        elif "均衡" in t:
            self.prefs["use_case"] = "balanced"
        # 分辨率
        if "2k" in t:
            self.prefs["resolution"] = "2K"
        elif "4k" in t:
            self.prefs["resolution"] = "4K"
        elif "1080" in t:
            self.prefs["resolution"] = "1080p"
        # 排除配件
        if any(k in t for k in ("不要显示器", "不含显示器", "无显示器", "不要屏幕")):
            self.prefs.setdefault("exclude", []).append("monitor")
        if any(k in t for k in ("不要外设", "不要键鼠", "无外设")):
            self.prefs.setdefault("exclude", []).append("peripherals")

    def add_history(self, role: str, content: str, max_len: int = 12) -> None:
        self.history.append({"role": role, "content": content[:500]})
        if len(self.history) > max_len:
            self.history = self.history[-max_len:]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "prefs": self.prefs,
            "history_len": len(self.history),
        }
