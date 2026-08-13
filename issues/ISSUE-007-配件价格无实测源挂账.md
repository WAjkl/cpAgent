# ISSUE-007 内存/SSD/电源/主板无当日实测价源

- **日期**：2026-08-13
- **状态**：📌挂账（部分解决）
- **影响**：中（43 条为 estimate，装机前必须刷新价格；不影响架构开发，影响推荐价可信度）

## 现象

- GPU：videocardprices.com 有结构化实测价 ✅（17 条 live）
- CPU：PassMark 有实测美元价 ✅（8 条 live）
- 内存/SSD/电源/主板：无当日可直抓的结构化价格源（京东/淘宝反爬强，比价站无稳定 JSON-LD）

## 根因

配件价格数据分散在各电商/比价站，均无公开 API；直连抓取成本高、稳定性差。

## 解决方案（当前）

1. 知识库快照估算（2026-08 行情），明确标注 `price_source: "estimate"`、`confidence: 0.4`
2. meta.data_quality 写入分级说明："estimate 快照估算，装机前必须 browser-price-mcp 刷新"
3. UI 层按新鲜度灰点显示（对应前端 4.4"价格来源与时间戳"）

## 后续消化（M2）

- 任务 2.2 browser-price-mcp：京东/慢慢买适配器（Playwright 低频 + 缓存）
- 适配器到位后，逐条把 estimate 升级为 live
- 兜底：任何时刻都保留"快照价 + 需核实"显示语义，禁止把 estimate 伪装成实时价

## 教训

"全网数据"不等于"全类别都有好源"；数据地基要按类别分级，宁可标 estimate 也不编造实测。
