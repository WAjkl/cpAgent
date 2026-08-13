# ISSUE-024 配置卡片锁死 22800 + 卡片与回答不一致 + key 管理

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：高（配置推荐三连 bug + 缺 key 管理界面）

## 现象

1. 问 3 万、5 万预算，配置总价始终 22800（RTX 4090 那套），大预算不会配旗舰卡
2. LLM 文字里说「手动挑了 41115 顶配」，但前端配置卡片还是 22800（两套数据不一致）
3. 联网模式问「1000 以下配置」却回「未配置 LLM」（误导，实为上下文过长 fallback）

## 根因

1. **GPU 预算 50% 硬上限**：`config_gen` 里 `gpu_budget = budget * 0.5`，5 万预算时 GPU 上限 2.5 万，RTX 5090（3.1 万）被过滤，只能配 RTX 4090 = 22800
2. **卡片与回答数据源不同**：前端 config 事件是 server **独立调 generate_config** 生成的；LLM 文字里是它自己手动挑的（绕过工具），两套结果没对齐
3. **fallback 文案误导**：`_fallback_answer` 不分「真没配 LLM」和「LLM 输出异常」，统一说「未配置 LLM」

## 解决方案

1. GPU 上限 0.5 → **0.65**（5 万预算时 5090 可入选）
2. `agent_loop` 主循环提取 generate_config 工具的 config，放进 `_finalize` 返回的 `config` 字段；server 的 config 事件**优先用 LLM 实际生成的 config**，无则确定性兜底
3. `_fallback_answer` 按 `llm.name == "mock"` 区分：真没配 →「请配置 key」；真实 LLM 异常 →「响应异常，请换问法」
4. 新增 key 管理：后端 `GET /keys/status`（configured/valid/masked，脱敏不泄露完整 key）+ `POST /keys`（写 .env）；前端上下文栏「API Key」区（红绿灯 + 脱敏 + 配置保存）

## 验证

- `generate_config(50000)` → 总价 37875、GPU RTX 5090（原来 22800/RTX 4090）
- key 状态：deepseek/tavily 均 configured+valid（绿灯）
- smoke 3/3 回归通过

## 设计原则

- 预算分配是「建议」不是「硬上限」：高预算时显卡占比可超 50%，硬限制会锁死配置档位
- 前端卡片必须与 LLM 回答同源（用 LLM 实际生成的 config），否则用户看到两套矛盾数据
- key 脱敏回显：后端只返回 `sk-****尾4位`，绝不把完整 key 传回前端
