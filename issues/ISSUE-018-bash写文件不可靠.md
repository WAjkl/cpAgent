# ISSUE-018 bash 写文件不可靠（heredoc 截断 + 多层转义断裂）+ bat 重定向笔误

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（开发流程反复踩，浪费多轮排查）

## 现象与根因

1. **heredoc 长文件截断**：bash `cat > file <<'EOF'` 写 >250 行文件时，文件末尾被截断（heredoc 到 EOF 前中断）。
2. **多层转义断裂**：用 python patch 脚本改文件，写入内容里的 `"\n"` 经过「JSON 字符串 → bash heredoc → python 字符串字面量」多层传输，`\\n` 最终变成真实换行，写出的代码字符串断裂（`SyntaxError: unterminated string literal`）。
3. **bat 重定向笔误**：`start-cpagent.bat` 里 `>nul` 误写成 `>/dev/null`（Unix 习惯带入 Windows，Windows 空设备是 `nul`）。

## 解决方案

1. 长文件**不用 heredoc**，改用「write_file 写 workspace + bash cp 中转」（sandbox 限制 write_file 不能写工程目录时的标准做法）
2. 需要写入文件内容的换行符用 `chr(10)` 表达，彻底避免 `\n` 字面量的多层转义
3. Windows bat 重定向空设备统一 `>nul`

## 设计原则

- 受 sandbox 写限制时，「write_file → workspace + cp」是最可靠路径，比 heredoc 稳
- patch 脚本里写入目标代码时，换行用 `chr(10)` 或三引号字符串，绝不用 `\n` 字面量拼
