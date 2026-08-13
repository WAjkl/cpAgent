# ISSUE-020 联网搜索数据源探索 + web_search 工具落地

- **日期**：2026-08-13
- **状态**：✅已解决（百度源可用）
- **影响**：中（实现 LLM「联网搜 → 挑选 → 总结」能力）

## 背景

用户问「配 LLM 后能否联网即时搜索再总结」。结论：DeepSeek API 本身**不支持联网**（文档无 web_search 参数，模型 deepseek-v4-flash/pro），必须加搜索工具。

## 数据源探索（ISSUE-002 的延续）

| 数据源 | 结果 |
|--------|------|
| DuckDuckGo html/lite | ❌ 连接失败（被墙，ISSUE-002 同因） |
| Bing | ❌ 302 重定向 + 反爬 |
| 百度 | ✅ 国内可达，抓取可行 |

## 落地

新增 `backend/tools/web_search.py`：
- 抓 `https://www.baidu.com/s?wd=关键词`
- 正则解析 `<h3>` 结果块的标题 + href
- 过滤明显广告（淘宝/京东/天猫/广告 等词）
- 百度跳转链接参数已加密（`baidu.com/link?url=` 的 url 参数是乱码），**不做真实 URL 还原**，保留原始 href（点击仍可跳转）
- 注册进 tool_registry，SYSTEM_PROMPT 提示「需要实时行情/新闻时调 web_search」
- agent_loop `_summarize` 增加 web_search 分支，展示清晰标题列表

## 验证

问「RTX 5090 最新行情」→ LLM 主动调 web_search ×3 + 查本地库 query_hardware_db/search_price，给出诚实回答（本地价 31074，说明搜索无历史价格故无法判断涨跌）。问「最近新显卡发布」→ web_search ×3 + 本地摘要，输出 1049 字总结。

## 设计原则

- 搜索结果质量：百度结果含广告与聚合页，LLM 需自己挑选；摘要未提取（百度新版摘要结构复杂，挂账）
- 联网搜索给的是「线索」（标题），不保证「事实」；价格仍以本地库 live 价为锚，联网作为补充
