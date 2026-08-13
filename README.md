# cpAgent

cpAgent 是桌面装机顾问 Agent：说一句「8000 打游戏 2K 不要显示器」，即可得到可回溯、可校验、价格新鲜的配置单，并支持配件对比、行情答疑与多轮追问。

核心坚持「LLM 做大脑、确定性规则做手脚、真实数据做地基」：配置单由确定性算法生成，价格与规格全部锚定工具返回和本地硬件库，每条标注来源与快照时间，从机制上杜绝 LLM 编造。

内置 67 条硬件库，支持快照/联网双模式、价格刷新与跨会话记忆。LLM 可插拔（DeepSeek / Ollama / Mock）。

技术栈：Electron + React 18 + TypeScript + Tailwind + Zustand，后端 FastAPI + ReAct 循环 + SQLite。

## 快速开始

```bash
# 后端（127.0.0.1:8765）
python -m backend.server

# 前端
cd frontend && npm install && npm run dev
```

在工程根目录 `.env` 配置 `DEEPSEEK_API_KEY`，或用 `CPAGENT_LLM_PROVIDER=ollama` 接本地模型。

详细路线图见 `PROJECT_PLAN.md`，问题记录见 `issues/`。
