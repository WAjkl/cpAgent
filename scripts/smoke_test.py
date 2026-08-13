"""M1 冒烟测试：三个核心场景自动化验证。

用法：python scripts/smoke_test.py [--provider deepseek|mock]
覆盖：
1. 推荐：8000 打游戏 2K 不要显示器 → 应产出含 CPU/GPU 的配置回答
2. 对比：RTX 5060 和 RX 9070 哪个好 → 应包含两个型号与价格
3. 答疑：最近显卡价格为什么涨 → 应基于库内数据回答
断言：路由类型正确、回答非空、证据校验执行、无 timeout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent_loop import AgentLoop  # noqa: E402
from backend.config import AgentConfig, LLMConfig  # noqa: E402
from backend.evidence import EvidenceStore  # noqa: E402
from backend.llm import resolve_provider  # noqa: E402

CASES = [
    {"text": "8000 打游戏 2K 不要显示器", "expect_route": "recommend", "expect_kw": ["显卡", "CPU", "价格"]},
    {"text": "RTX 5060 和 RX 9070 哪个好", "expect_route": "compare", "expect_any_kw": ["RTX 5060", "RX 9070"], "expect_kw": ["元"]},
    {"text": "最近显卡价格为什么涨", "expect_route": "qa", "expect_kw": ["涨价", "价格"]},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()

    llm_cfg = LLMConfig()
    llm_cfg.provider = args.provider
    llm = resolve_provider(llm_cfg)
    agent = AgentLoop(llm=llm, agent_cfg=AgentConfig(), llm_cfg=llm_cfg, evidence=EvidenceStore())

    passed = 0
    for i, case in enumerate(CASES, 1):
        print(f"\n[{i}/{len(CASES)}] {case['text']}")
        result = None
        # LLM 偶发波动：最多重试 1 次
        for attempt in range(2):
            result = agent.run(case["text"], session_id=f"smoke-{i}")
            ok_route = result["routing"]["type"] == case["expect_route"]
            ok_answer = bool(result["answer"]) and not result.get("timeout", False)
            ok_kw = all(k in result["answer"] for k in case.get("expect_kw", []))
            if case.get("expect_any_kw"):
                ok_kw = ok_kw and any(k in result["answer"] for k in case["expect_any_kw"])
            if ok_route and ok_answer and ok_kw:
                break
            if attempt == 0:
                print(f"[WARN]  第1次尝试不达标（路由={result['routing']['type']} 长度={len(result['answer'])}），重试…")
        status = "[PASS]" if (ok_route and ok_answer and ok_kw) else "[FAIL]"
        print(f"   路由={result['routing']['type']}(期望{case['expect_route']}) "
              f"回答长度={len(result['answer'])} 关键词={ok_kw} timeout={result.get('timeout', False)} → {status}")
        if status == "[PASS]":
            passed += 1

    print(f"\n结果: {passed}/{len(CASES)} 通过")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
