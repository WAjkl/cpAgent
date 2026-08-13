# ISSUE-019 证据校验只认 query_hardware_db，不认 generate_config/search_price 价格

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：高（LLM 配好后推荐场景偶发 fallback、多余修正循环）

## 现象

配 DeepSeek 后跑 smoke，推荐场景「8000 打游戏 2K」偶发 FAIL（回答长度 42 = mock fallback），且 trace 里出现多余的价格修正循环。

## 根因

`evidence.search_prices` 只解析 `query_hardware_db` 的返回价格，不解析 `generate_config`（配置单）和 `search_price` 的价格。LLM 用 generate_config 出配置单后，回答里的价格被判「无法回溯到工具返回」，触发修正循环；修正后仍无法回溯（因为 search_prices 就是不认 generate_config），只能放行 + 审计标注。偶发情况下叠加 LLM 随机性，最终走到 fallback。

## 解决方案

`search_prices` 增加两个分支：
- `generate_config`：遍历 `config.parts` 各配件提取 model/price/source
- `search_price`：提取单条 model/price/source

## 验证

修复后 smoke 3/3 稳定通过（推荐 860 字 / 对比 731 字 / 答疑 521 字）。

## 设计原则

证据锚定的「可回溯价格集合」必须覆盖**所有会返回价格的工具**，新增含价格工具时同步更新 search_prices。
