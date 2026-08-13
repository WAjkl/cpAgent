"""cpAgent 后端 CLI 入口（M1 演示）。

用法：
    python -m backend.main --text "8000 打游戏 2K 不要显示器"
    python -m backend.main --text "RTX 5060 和 RX 9070 哪个好" --provider mock
    python -m backend.main --interactive
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保 backend 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent_loop import AgentLoop  # noqa: E402
from backend.config import AgentConfig, LLMConfig  # noqa: E402
from backend.evidence import EvidenceStore  # noqa: E402
from backend.llm import resolve_provider  # noqa: E402


def build_agent(provider: str):
    llm_cfg = LLMConfig()
    if provider:
        llm_cfg.provider = provider
    llm = resolve_provider(llm_cfg)
    agent = AgentLoop(llm=llm, agent_cfg=AgentConfig(), llm_cfg=llm_cfg, evidence=EvidenceStore())
    return agent


def run_once(agent: AgentLoop, text: str, session_id: str = "cli"):
    print("=" * 70)
    print(f"[用户] {text}")
    result = agent.run(text, session_id=session_id)
    print(f"[路由] {result['routing']}")
    print(f"[回答]\n{result['answer']}")
    if result.get("trace"):
        print("\n[轨迹]")
        for t in result["trace"]:
            d = t.get("decision", {})
            print(f"  step{t['step']}: thought={d.get('thought', '')[:60]}")
            if d.get("action"):
                print(f"           action={d['action']}({json.dumps(d.get('action_input', {}), ensure_ascii=False)[:120]})")
            if t.get("result"):
                print(f"           observe={t['result'][:150]}")
            if t.get("evidence_check"):
                ec = t["evidence_check"]
                print(f"           证据校验: ok={ec['ok']} unmatched={ec['unmatched']}")
    print(f"[证据记录] {len(result['evidence_ids'])} 条")
    return result


def interactive(agent: AgentLoop):
    print("cpAgent 装机顾问（M1 CLI）—— 输入问题，Ctrl+C 退出")
    session_id = "interactive"
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见 👋")
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit", "q"):
            break
        run_once(agent, text, session_id=session_id)


def main():
    parser = argparse.ArgumentParser(description="cpAgent 后端 CLI")
    parser.add_argument("--text", help="单次提问")
    parser.add_argument("--provider", default="", help="LLM provider: auto/deepseek/ollama/mock")
    parser.add_argument("--interactive", action="store_true", help="交互模式")
    args = parser.parse_args()

    agent = build_agent(args.provider)
    if args.interactive:
        interactive(agent)
    elif args.text:
        run_once(agent, args.text)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
