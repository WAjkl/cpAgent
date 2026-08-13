"""cpAgent 后端配置。

LLM 可插拔：deepseek（云端 API，OpenAI 兼容）/ ollama（本地）/ mock（规则引擎兜底）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 工程根目录（backend/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

def _load_dotenv() -> None:
    """从工程根 .env 加载环境变量（不覆盖已有环境变量，避免硬编码 key）。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _k, _, _v = line.partition("=")
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v


_load_dotenv()


# 数据与存储路径
DATA_DIR = ROOT / "data"
HARDWARE_DB_PATH = DATA_DIR / "hardware_db.json"
EVIDENCE_DB_PATH = DATA_DIR / "evidence.db"      # 证据锚定 SQLite（工具原始返回落盘）
PRICE_CACHE_PATH = DATA_DIR / "price_cache.db"   # 价格缓存（M2 启用）
LONGTERM_MEMORY_PATH = DATA_DIR / "longterm_memory.db"  # 长期记忆（M2 启用）


@dataclass
class LLMConfig:
    """LLM 提供方配置（可插拔）。"""

    provider: str = field(default_factory=lambda: os.getenv("CPAGENT_LLM_PROVIDER", "auto"))
    # deepseek
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    # ollama
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
    # 通用
    temperature: float = 0.2
    max_tokens: int = 3072
    timeout: int = 60


@dataclass
class AgentConfig:
    """Agent 循环配置。"""

    max_steps: int = 12          # ReAct 最大循环步数（防死循环）
    # 决策阶段（action JSON）用小上限，降低 JSON 截断概率、压低单步输出占用；
    # 最终回答（answer）才用大上限（见 LLMConfig.max_tokens）。
    decision_max_tokens: int = 1024
    evidence_enabled: bool = True
    validation_enabled: bool = True
    routing_enabled: bool = True


def get_llm_config() -> LLMConfig:
    return LLMConfig()


def get_agent_config() -> AgentConfig:
    return AgentConfig()
