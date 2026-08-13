# ISSUE-001 数据地基丢失，需从零重建

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（工程尚未启动，未造成返工）

## 现象

用户清空 `D:\SJKXJM\exp2_stu\Agent开发\cpAgent`，原 `data/hardware_db.json`（69 条：cpu 24 / gpu 28 / memory 3 / ssd 3 / psu 5 / motherboard 6）随之删除。`dir /a /s` 确认目录 0 文件。

## 根因

用户决定"推倒重来"（架构文档 17 行明确"与 cpAgent 的关系：推倒重来"），删除旧实现。

## 解决方案

1. 会话历史中保留的原库结构（schema/样例/meta）作为重建参考
2. 全网抓取真实数据源重建：
   - GPU：videocardprices.com 2026-08-13 实测美元街价（17 款）
   - CPU：PassMark 2026-08 实测美元价（8 款命中）
   - 汇率：open.er-api.com USD→CNY 6.756905（2026-08-13）
   - 内存/SSD/电源/主板：知识库快照估算（明确标注 estimate）
3. 新库 v2.1：**67 条**，schema 统一（price_low/high + price_source + confidence + fetched_at），数据质量分级写入 meta
4. 构建脚本 `scripts/build_hardware_db.py` 可复现

## 教训

数据是工程资产，删除前应备份；重建必须保留来源分级，不能凭记忆伪造"原数据"。
