# ISSUE-008 PassMark CPU 列表列序解析错误（Value 被当 Price）

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：高（首轮 CPU 价格全错：9950X3D 被算成 ¥548，实际 ¥3845）

## 现象

构建后 CPU live 价格离谱：
- Ryzen 9 9950X3D = ¥548（实际约 ¥3845）
- Core Ultra 9 285K = ¥866（实际约 ¥3547）
- i9-14900K = ¥507（实际约 ¥2696）

## 根因

PassMark `cpu-list/` 表格列序为 `Name | CPU Mark | Rank | Value | Price`，但首版解析按 `Name | Rank | Value | Price | CPU Mark` 取列：
- `cells[3]` = **Value**（性能/价格比，如 123.21）被误当价格
- `cells[4]` = **Price**（如 $569.00）被误当 CPU Mark

`cpu_hit()` 还取了 `price < best[0]`（最低价），进一步放大了异常。

## 解决方案

1. 抽样打印单行 cells 确认真实列序（`['AMD Ryzen 9 9950X3D', '70,106', '123', '123.21', '$569.00']`）
2. 修正映射：`cpu_mark = cells[1]`（去逗号）、`price_usd = cells[4]`（去 `$`/`*`）
3. 重抓 Intel + AMD 两页（`/cpu-list/intel`、`/cpu-list/amd`），去重合并 4492 条
4. 重跑构建 → CPU 20/20 live，价格合理（9950X3D ¥3845、9800X3D ¥2804）
5. 修正后必须人工抽查 5+ 个型号价格合理性（本次抽了 6 个）

## 附加发现

- PassMark 默认页 `/cpu-list/` 只有 Intel；AMD 在 `/cpu-list/amd`（ChangeTab 里写死）
- 13700K $449.99 > 14700K $289.99 是真实市场倒挂（13 代停产溢价），非解析错误，保留并标注

## 教训

**任何外部表格解析，先打印一行 cells 确认列序再写映射**；解析完成后必须人工抽查价格量级合理性，不能只看"跑通了"。
