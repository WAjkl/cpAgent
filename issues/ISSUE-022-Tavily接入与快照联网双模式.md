# ISSUE-022 Tavily 接入稳定搜索源 + 快照/联网双模式

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（联网搜索质量提升；新增按需联网开关）

## 内容

1. **Tavily 接入**（解决 ISSUE-021 挂账）：
   - `.env` 加 `TAVILY_KEY`；`web_search.py` 加 `_search_tavily`（POST api.tavily.com/search，返回 title/url/content AI 摘要）
   - 数据源优先级：Tavily → Bing → 百度（逐级降级）
   - 踩坑：`web_search.py` 未 import config 导致 `.env` 的 TAVILY_KEY 没加载（`os.getenv` 读到空），加 `from .. import config` 触发 `_load_dotenv`
   - 效果：摘要质量显著提升（返回具体价格/新闻内容，而非 Bing 的短 snippet）

2. **快照/联网双模式**：
   - `ToolRegistry.default(web_enabled)` 支持参数：快照模式 5 个本地工具，联网模式 +web_search/web_fetch
   - `agent_loop.run` 从 `prefs.mode` 读模式构建工具集（默认 snapshot）
   - 前端 `Prefs` 加 `mode: 'snapshot' | 'online'`，需求面板加「快照/联网」切换按钮
   - 链路：前端 toggle → prefs.mode → chatSSE → 后端 agent.run → 工具集切换

## 验证

- Tavily：`source=tavily, count=8`，摘要含「国内售价 18999 元」等具体信息
- 模式：snapshot 模式问「RTX 5090 行情」只调 search_price（不联网）；online 模式调 web_search+web_fetch（联网总结）

## 设计原则

- 联网是「按需」能力而非「默认」：快照模式零外呼、快、确定性；用户显式选联网才外呼
- 搜索源多级降级 + 进程内缓存，单源失效不拖垮整体
