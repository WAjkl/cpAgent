# ISSUE-013 前端面板 prefs 未传给后端 + 步数上限无确定性兜底

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：高（用户面板选的分辨率/预算被忽略，agent 反复反问或卡步数上限）

## 现象

1. 用户在需求面板选了 2K 分辨率（可能还有预算），发「帮我配」，agent 仍反问「分辨率是 1080p / 2K / 4K」
2. 某些输入下 agent 返回「抱歉，我尝试了多步仍未能完成（达到步数上限）」

## 根因

1. **prefs 丢失**：前端 `chatSSE` 只发 `message + session_id`，没发面板 prefs；后端 `agent.run` 也只从 message 文本提取要素（`WorkingMemory.update_prefs`）。用户在面板选的 2K 根本没进后端。
2. **步数上限无兜底**：LLM 输出不稳定时，ReAct 循环反复「缺字段 / 调工具」卡满 12 步，返回固定兜底文案，辜负了已经给到的预算/分辨率信息。

## 解决方案

1. 前端 `api.ts` 的 `chatSSE` 增加 `prefs` 参数并放入 body；`chatStore.sendMessage` 传融合后的 `newPrefs`
2. 后端 `ChatRequest` 加 `prefs` 字段；`agent.run` 加 `prefs` 参数并合并进 `WorkingMemory`（外部 prefs 覆盖文本提取）
3. 步数上限处：`recommend` 且已有 `budget` → 确定性兜底 `generate_config` 生成配置单，不再返回「达到步数上限」

## 验证

- TestClient 带 `prefs={'budget':8000,'use_case':'gaming','resolution':'2K'}` 发「帮我配」→ SSE 出 config 事件（2K / 7290 / RX 9060 XT）；不带 prefs → 正确识别信息不足
- FakeLLM（每次返回缺字段 JSON 逼满 12 步）→ 不再「达到步数上限」，而是兜底出含真实型号的配置单

## 设计原则

- 面板控件选的信息是「明确事实」，必须随请求传给后端，不能只靠 LLM 从自然语言猜
- 确定性兜底永远优先于「诚实放弃」：能算出来的配置单，绝不让步数上限吞掉
