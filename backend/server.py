"""cpAgent FastAPI + SSE 服务（M2 任务 2.6）。

接口（对齐前端文档第六章约定）：
    POST /chat                      流式对话（SSE），返回 status/delta/config/done 事件
    POST /config                    直接生成配置单（非流式，供配置卡片）
    GET  /conversations             会话列表
    GET  /conversations/{sid}/configs  某会话的历史配置
    GET  /hardware/summary          硬件库摘要
    GET  /health                    健康检查

启动：python -m backend.server  （默认 127.0.0.1:8765）
或：  uvicorn backend.server:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent_loop import AgentLoop
from .config import ROOT, AgentConfig, LLMConfig
from .config_gen import generate_config
from .evidence import EvidenceStore
from .llm import resolve_provider
from .longterm_memory import LongTermMemory
from .price_cache import PriceCache
from .tools.hardware_db import get_hardware_summary

app = FastAPI(title="cpAgent 装机顾问", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 桌面端 Electron 跨域；生产可收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 全局单例（进程内共享） ----------
_llm_cfg = LLMConfig()
_agent_cfg = AgentConfig()
_price_cache = PriceCache()
_longterm = LongTermMemory()
_evidence = EvidenceStore()
_agent: Optional[AgentLoop] = None


def get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        llm = resolve_provider(_llm_cfg)
        _agent = AgentLoop(llm=llm, agent_cfg=_agent_cfg, llm_cfg=_llm_cfg, evidence=_evidence)
    return _agent


def _sse(payload: Dict[str, Any]) -> str:
    """把 dict 序列化为一条 SSE data 事件。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- 请求模型 ----------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = True
    prefs: Optional[Dict[str, Any]] = None


class ConfigRequest(BaseModel):
    budget: float = Field(..., gt=0, le=1_000_000)
    use_case: str = "gaming"
    resolution: Optional[str] = None
    top_k: int = 1


# ---------- key 管理（配置 + 校验 + 红绿灯状态） ----------
_ENV_FILE = ROOT / ".env"


def _read_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _write_env(updates: Dict[str, str]) -> None:
    env = _read_env()
    env.update({k: v for k, v in updates.items() if v})
    _ENV_FILE.write_text("".join(f"{k}={v}" + chr(10) for k, v in env.items()), encoding="utf-8")


def _verify_deepseek(key: str) -> bool:
    try:
        body = json.dumps({"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
        req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body.encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def _verify_tavily(key: str) -> bool:
    try:
        body = json.dumps({"query": "test", "max_results": 1})
        req = urllib.request.Request("https://api.tavily.com/search", data=body.encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


class KeysRequest(BaseModel):
    deepseek_key: Optional[str] = None
    tavily_key: Optional[str] = None


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "****"
    return key[:5] + "****" + key[-4:]


@app.get("/keys/status")
def keys_status() -> Dict[str, Any]:
    env = _read_env()
    ds = env.get("DEEPSEEK_API_KEY", "")
    tv = env.get("TAVILY_KEY", "")
    return {
        "deepseek": {"configured": bool(ds), "valid": _verify_deepseek(ds) if ds else False, "masked": _mask_key(ds)},
        "tavily": {"configured": bool(tv), "valid": _verify_tavily(tv) if tv else False, "masked": _mask_key(tv)},
    }


@app.post("/keys")
def save_keys(req: KeysRequest) -> Dict[str, Any]:
    updates: Dict[str, str] = {}
    if req.deepseek_key:
        updates["DEEPSEEK_API_KEY"] = req.deepseek_key.strip()
        os.environ["DEEPSEEK_API_KEY"] = req.deepseek_key.strip()
    if req.tavily_key:
        updates["TAVILY_KEY"] = req.tavily_key.strip()
        os.environ["TAVILY_KEY"] = req.tavily_key.strip()
    _write_env(updates)
    global _agent
    _agent = None  # 让下次请求重新解析 provider
    return {"ok": True, "saved": list(updates.keys())}


# ---------- 接口 ----------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "cpAgent", "provider": _llm_cfg.provider}


@app.get("/hardware/summary")
def hardware_summary() -> Dict[str, Any]:
    return get_hardware_summary()


@app.post("/config")
def make_config(req: ConfigRequest) -> Dict[str, Any]:
    """直接生成配置单（确定性算法，不依赖 LLM）。"""
    cfgs = generate_config(req.budget, req.use_case, req.resolution, top_k=req.top_k, cache=_price_cache)
    if not cfgs:
        raise HTTPException(status_code=422, detail="该预算/用途下无可行配置（预算过低或条件过严）")
    # 落历史配置库
    for c in cfgs:
        _longterm.save_config("api", c)
    return {"configs": cfgs, "count": len(cfgs)}


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    agent = get_agent()
    session_id = req.session_id or f"sess-{uuid.uuid4().hex[:8]}"

    # 长期记忆兜底：新会话注入历史偏好（第二次对话记得上次预算）
    if not req.session_id:
        latest = _longterm.recall_latest_prefs()
        if latest:
            _longterm.remember_prefs(session_id, latest)

    # 跨轮回灌：读回该会话前几轮对话摘要，注入本轮上下文
    history = _longterm.recall_dialogue(session_id)

    # 同步跑 agent 循环（M2 v0；逐 token 流式待 M3/M4 接入 LLM stream）
    result = agent.run(req.message, session_id=session_id, prefs=req.prefs, history=history)

    # 存回本轮对话（追加到历史，最多保留 3 轮）
    _answer = result.get("answer") or ""
    _new_history = history + [{"role": "user", "content": req.message}]
    if _answer:
        _new_history.append({"role": "assistant", "content": _answer})
    _longterm.remember_dialogue(session_id, _new_history)

    # 保存本次偏好到长期记忆（conversations 会话列表来源）
    _prefs = (result.get("memory") or {}).get("prefs") or {}
    if _prefs:
        _longterm.remember_prefs(session_id, _prefs)

    async def event_stream():
        # 1) 状态事件（路由结果）
        yield _sse({"type": "status", "session_id": session_id, "routing": result.get("routing")})

        # 2) 回答分块（模拟流式，前端逐字渲染）
        answer = result.get("answer") or ""
        chunk = 24
        for i in range(0, len(answer), chunk):
            yield _sse({"type": "delta", "text": answer[i:i + chunk]})
            await asyncio.sleep(0.015)

        # 3) 配置单事件：优先用 LLM 实际生成的 config（agent_loop 返回），否则确定性兜底生成
        prefs = (result.get("memory") or {}).get("prefs") or {}
        config = result.get("config")
        if config is None and result.get("routing", {}).get("type") == "recommend" and prefs.get("budget"):
            try:
                cfgs = generate_config(
                    prefs["budget"],
                    prefs.get("use_case") or "gaming",
                    prefs.get("resolution"),
                    top_k=1,
                    cache=_price_cache,
                )
                if cfgs:
                    config = cfgs[0]
            except Exception as e:  # 配置生成失败不影响主回答
                yield _sse({"type": "warn", "text": f"配置生成失败: {e}"})
        if config:
            _longterm.save_config(session_id, config)
            yield _sse({"type": "config", "config": config})

        # 4) 结束事件
        yield _sse({
            "type": "done",
            "session_id": session_id,
            "turn_id": result.get("turn_id"),
            "evidence_ids": result.get("evidence_ids") or [],
            "timeout": result.get("timeout", False),
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/conversations")
def conversations() -> Dict[str, Any]:
    return {"sessions": _longterm.list_sessions()}


@app.get("/conversations/{session_id}/configs")
def conversation_configs(session_id: str) -> Dict[str, Any]:
    return {"configs": _longterm.list_configs(session_id=session_id)}


def main() -> None:
    import uvicorn

    uvicorn.run("backend.server:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
