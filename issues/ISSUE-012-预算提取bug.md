# ISSUE-012 WorkingMemory 预算提取只认"预算"字样，句首数字丢失

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（确定性注入拿不到 budget；server /chat 的 config 事件不生成）

## 现象

`"8000 打游戏 2K 不要显示器"` 经 `WorkingMemory.update_prefs` 后 `prefs` 里没有 `budget`，导致：
1. `_apply_prefs_to_args` 确定性注入拿不到预算
2. server `/chat` 的 recommend 场景因 `prefs.get("budget")` 为空，不生成 config 事件

## 根因

M1 预算提取条件写成 `if m and "预算" in t or "预算" in t:`——Python 运算符优先级导致条件恒等于 `"预算" in t`，只有输入含"预算"两字才提取；"8000 打游戏"这类句首数字被漏掉。

## 解决方案

重写提取为三级匹配（从严格到宽松）：

```python
m = re.search(r"(\d{3,6})\s*(?:元|块|k\b|预算)", t)        # 数字+单位/关键词
if not m:
    m = re.search(r"(?:预算|不超过|以内|以下)\s*(\d{3,6})", t)  # 关键词+数字
if not m:
    m = re.match(r"^\s*(\d{3,6})(?![0-9])", t)              # 句首纯数字
```

同时避免把"对比 RTX 5060 和 RX 9070"里的 5060/9070 误当预算（只认句首数字）。

## 设计原则

- 需求要素提取是确定性注入的根基，规则要覆盖自然语言常见说法（句首数字、关键词+数字、数字+单位）
- 用 `(?![0-9])` 代替 `\b`（Unicode 下 `\b` 对汉字数字边界不敏感）
