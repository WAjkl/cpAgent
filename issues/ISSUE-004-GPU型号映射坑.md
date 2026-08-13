# ISSUE-004 AMD 显卡型号前缀导致映射失败

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（首轮构建 GPU 只落 11/17 条）

## 现象

`build_hardware_db.py` 首轮输出 `gpu: 11 条`，预期 17。检查原始 JSON 发现：

- NVIDIA/Intel：`model="RTX 5090"`、`model="Arc B580"` —— 与库映射 key 一致 ✅
- AMD：`model="Radeon RX 9070 XT"` —— 带 `Radeon ` 前缀，与库 key `RX 9070 XT` 不匹配 ❌

## 根因

videocardprices 对 AMD 卡的 JSON-LD `model` 字段统一带 "Radeon " 前缀，NVIDIA 不带；映射表按无前缀 key 编写。

## 解决方案

```python
norm = model.strip().replace("Radeon ", "")
```
归一化时剥离 "Radeon " 前缀。重跑后 GPU 17 条全部命中。

## 教训

外部数据源字段格式不一致是常态；**先抽样检查原始数据再写映射**，不要假设格式统一。
