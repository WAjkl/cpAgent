# cpAgent 问题记录（issues）

> 用途：记录开发过程中遇到的问题 —— 现象、根因、解决方案、是否解决。
> 规则：每个问题一个文件；`状态` 四选一：✅已解决 / 🟡部分解决 / ⬜未解决 / 📌挂账。

## 索引

| 编号 | 标题 | 状态 | 解决方式摘要 |
|------|------|------|--------------|
| ISSUE-001 | 原 hardware_db.json 随目录删除，数据地基需从零重建 | ✅已解决 | 全网抓取重建 v2.1（67 条，37 live） |
| ISSUE-002 | web_search 服务持续不可用（duckduckgo 超时 / tavily、bocha 无凭证） | ✅已解决（换路） | 改用 http_request/urllib 直连数据源 |
| ISSUE-003 | TechPowerUp 反爬（Automated bot check）拦截 | ✅已解决（换源） | 换 videocardprices.com（JSON-LD 结构化） |
| ISSUE-004 | AMD 显卡 model 带 "Radeon " 前缀导致映射失败（GPU 只落 11/17） | ✅已解决 | model 归一化 strip "Radeon " 前缀 |
| ISSUE-005 | RTX 5060 Ti 别名匹配失败 + startswith 模糊匹配有串价风险（5070Ti↔5070） | ✅已解决 | 精确匹配 + 显式别名表，禁用模糊匹配 |
| ISSUE-006 | execute_code 工具环境异常（gateway `-c` 参数错误） | ✅已绕过 | 改用 venv Python + exec_command |
| ISSUE-007 | 内存/SSD/电源/主板无当日实测价源 | 📌挂账 | 知识库估算 + 明确标注 estimate，待 browser-price-mcp 接入后升级 live |
| ISSUE-008 | PassMark CPU 列表列序解析错误（Value 被当 Price，价格全错） | ✅已解决 | 抽样确认列序 `Name\|Mark\|Rank\|Value\|Price`，修正映射重抓重跑 |
| ISSUE-009 | 工具结果截断导致 LLM 误判"型号不存在"（RTX 5060 假阴性） | ✅已解决 | 工具 limit 10→30、摘要全量展示 |
| ISSUE-010 | LLM 习惯性调 final_answer 工具 + 证据校验死循环（预算/合计被误判） | ✅已解决 | prompt 明确无结束工具；校验加白名单+重试上限 1 次+审计标注 |
| ISSUE-011 | FastAPI 线程池触发 SQLite 跨线程错误 | ✅已解决 | sqlite3.connect 加 check_same_thread=False |
| ISSUE-012 | WorkingMemory 预算提取只认"预算"字样，句首数字丢失 | ✅已解决 | 三级匹配：数字+单位 / 关键词+数字 / 句首纯数字 |
| ISSUE-013 | 前端面板 prefs 未传给后端 + 步数上限无兜底 | ✅已解决 | chatSSE 带 prefs；agent.run 合并外部 prefs；步数上限 recommend 确定性兜底 |
| ISSUE-014 | M2 确定性模块集成 bug（字段约定/缓存未预热/贪心方向） | ✅已解决 | Path 包装+_upsert_quote 映射+seed 预热+价格升序同分取低价 |
| ISSUE-015 | Python 脚本 Windows GBK 控制台 emoji 报 UnicodeEncodeError | ✅已解决 | 测试输出改 ASCII 标记 [PASS]/[FAIL]/[WARN] |
| ISSUE-016 | electron-vite 配置踩坑（tsconfig composite + tailwind ESM） | ✅已解决 | 去 composite；配置文件改 CommonJS |
| ISSUE-017 | Playwright 代理拦截 localhost + dev server IPv6 监听 | ✅已解决 | newContext proxy bypass 回环地址；URL 用 localhost |
| ISSUE-018 | bash 写文件不可靠（heredoc 截断 + 多层转义断裂）+ bat 重定向笔误 | ✅已解决 | write_file→workspace+cp 中转；chr(10) 替代 
| ISSUE-019 | 证据校验只认 query_hardware_db，不认 generate_config/search_price 价格 | ✅已解决 | search_prices 增加 generate_config/search_price 分支 |
| ISSUE-020 | 联网搜索数据源探索 + web_search 工具落地 | ✅已解决 | DDG 被墙/Bing 反爬，百度可用；跳转链接不还原 |
| ISSUE-021 | 免费搜索源反爬 + LLM 反复抓取导致上下文膨胀 | ✅已解决（降级+限流缓解，稳定需搜索 API） | Bing 主源+百度降级+缓存；prompt 限制反复抓取；步数上限诚实兜底 |
| ISSUE-022 | Tavily 接入稳定搜索源 + 快照/联网双模式 | ✅已解决 | Tavily→Bing→百度降级；prefs.mode 切换工具集；前端 toggle |
| ISSUE-023 | 面板 prefs 只静默注入工具参数，LLM 看不到 → 反问已选信息 | ✅已解决 | _build_prefs_hint 把预算/用途/模式写进 user 消息 |
| ISSUE-024 | 配置卡片锁死 22800 + 卡片与回答不一致 + key 管理 | ✅已解决 | GPU 上限 0.5→0.65；config 同源；key 状态接口+前端红绿灯 |
；>nul |

## 统计

- 已解决：23　挂账：1
- 挂账项去向：M2 任务 2.2（browser-price-mcp 京东/慢慢买真实抓取）消化
