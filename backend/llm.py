"""LLM 抽象层：DeepSeek（云端）/ Ollama（本地）/ Mock（规则兜底）。

统一接口：
    llm.chat(messages, temperature=..., max_tokens=...) -> str
    llm.complete_json(prompt) -> dict   # 要求 LLM 只输出 JSON 对象（容错解析）

诚实纪律：任何 provider 失败都抛出 LLMError，由上层走保守路径（绝不编造）。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .config import LLMConfig


class LLMError(RuntimeError):
    pass


class LLMProvider:
    """LLM 提供方基类。"""

    name = "base"

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 1024) -> str:
        raise NotImplementedError

    def complete_json(self, messages: List[Dict[str, str]], temperature: float = 0.0, max_tokens: int = 1024) -> Dict[str, Any]:
        """要求模型只输出 JSON 对象；做容错解析（去 markdown 代码块围栏）。"""
        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json_loose(text)


class DeepSeekProvider(LLMProvider):
    """DeepSeek 云端 API（OpenAI 兼容）。"""

    name = "deepseek"

    def __init__(self, cfg: LLMConfig):
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url.rstrip("/")
        self.model = cfg.deepseek_model
        self.timeout = cfg.timeout
        if not self.api_key:
            raise LLMError("DeepSeek provider 需要 DEEPSEEK_API_KEY")

    def chat(self, messages, temperature=0.2, max_tokens=1024) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            raise LLMError(f"DeepSeek HTTP {e.code}: {body}") from e
        except Exception as e:
            raise LLMError(f"DeepSeek 请求失败: {e}") from e
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"DeepSeek 响应结构异常: {str(data)[:300]}") from e


class OllamaProvider(LLMProvider):
    """Ollama 本地（OpenAI 兼容 /api/chat）。"""

    name = "ollama"

    def __init__(self, cfg: LLMConfig):
        self.base_url = cfg.ollama_base_url.rstrip("/")
        self.model = cfg.ollama_model
        self.timeout = cfg.timeout

    def chat(self, messages, temperature=0.2, max_tokens=1024) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise LLMError(f"Ollama 请求失败: {e}") from e
        try:
            return data["message"]["content"]
        except KeyError as e:
            raise LLMError(f"Ollama 响应结构异常: {str(data)[:300]}") from e


class MockProvider(LLMProvider):
    """Mock 兜底：无凭证/无网络时用规则引擎模拟，保证 CLI 可演示。

    不做真正推理；只用于开发期冒烟与离线演示。生产必须接真实 LLM。
    """

    name = "mock"

    def __init__(self, cfg: Optional[LLMConfig] = None):
        self.cfg = cfg

    def chat(self, messages, temperature=0.2, max_tokens=1024) -> str:
        # 简单回声 + 固定 JSON 动作（由 agent_loop 的规则分支接管）
        last = messages[-1]["content"] if messages else ""
        return f"[mock] {last}"


def parse_json_loose(text: str) -> Dict[str, Any]:
    """容错解析 LLM 输出的 JSON 对象：剥离 markdown 围栏、截取首个 { } 块。"""
    if not text:
        raise LLMError("LLM 返回空文本")
    t = text.strip()
    # 剥离 ```json ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    # 截取首个平衡的 {...}
    start = t.find("{")
    if start < 0:
        raise LLMError(f"LLM 输出非 JSON: {text[:200]}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start : i + 1], strict=False)  # strict=False 容忍 LLM 输出的真实换行等控制字符
                except json.JSONDecodeError as e:
                    raise LLMError(f"JSON 解析失败: {e} | {t[start:i+1][:200]}") from e
    # 遍历完仍未闭合 → JSON 被 max_tokens 截断：尝试正则抢救已写完的 answer 字段
    rescued = _rescue_truncated(t[start:])
    if rescued is not None:
        return rescued
    raise LLMError(f"JSON 块不完整: {text[:200]}")


def _unescape(s: str) -> str:
    """还原 JSON 字符串转义（\n \t \r \" \\），保留其他字符原样。"""
    out: List[str] = []
    i, n = 0, len(s)
    mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in mapping:
            out.append(mapping[s[i + 1]])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _rescue_truncated(fragment: str) -> Optional[Dict[str, Any]]:
    """截断 JSON 容错：正则提取已写完的 answer 字段值（值可能未闭合引号）。

    成功返回 {"answer": <部分内容>, "_truncated": True}，供上层用更大 max_tokens 重试
    或直接兜底；找不到 answer 字段返回 None（交回原 LLMError 路径）。
    """
    m = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', fragment, re.S)
    if not m:
        return None
    return {"answer": _unescape(m.group(1)), "_truncated": True}


def resolve_provider(cfg: Optional[LLMConfig] = None) -> LLMProvider:
    """按配置解析 provider；provider=auto 时按可用性选择。"""
    cfg = cfg or LLMConfig()
    provider = cfg.provider
    if provider == "auto":
        if cfg.deepseek_api_key:
            return DeepSeekProvider(cfg)
        return MockProvider(cfg)
    if provider == "deepseek":
        return DeepSeekProvider(cfg)
    if provider == "ollama":
        return OllamaProvider(cfg)
    if provider == "mock":
        return MockProvider(cfg)
    raise LLMError(f"未知 LLM provider: {provider}")
