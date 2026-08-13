# ISSUE-002 web_search 服务持续不可用

- **日期**：2026-08-13
- **状态**：✅已解决（换路）
- **影响**：高（原计划用全网搜索补数据，全部超时/无凭证）

## 现象

- 默认 provider duckduckgo：`search request timed out`（多次重试均失败）
- tavily：`auth_missing`
- bocha：`auth_missing`
- web_discover：同样走 duckduckgo，超时

## 根因

- duckduckgo 出口超时（网络/服务侧问题，非本机可控）
- tavily/bocha 未配置 API 凭证

## 解决方案

放弃 web_search，改用**直连数据源**（`http_request` / Python `urllib`）：
- videocardprices.com（GPU 价格，JSON-LD 结构化，可解析）
- cpubenchmark.net / PassMark（CPU 价格 + 跑分）
- open.er-api.com（汇率）

结果反而拿到**结构化、可解析、带日期**的实测数据，比搜索摘要更可靠。

## 教训

搜索服务是"软依赖"；关键任务要有直连源兜底。后续 browser-price-mcp 的站点白名单应优先选有结构化数据（JSON-LD/API）的站点。
