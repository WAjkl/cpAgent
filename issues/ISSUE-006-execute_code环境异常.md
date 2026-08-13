# ISSUE-006 execute_code 工具环境异常

- **日期**：2026-08-13
- **状态**：✅已绕过
- **影响**：低（换执行通道后无阻塞）

## 现象

`execute_code` 调用 Python 时报错：

```
Usage: opensquilla-gateway.exe [OPTIONS] COMMAND [ARGS]...
No such option: -c
```

工具底层把代码通过 `-c` 传给了 opensquilla-gateway.exe，而该 CLI 不支持 `-c` 选项（参数错位）。

## 根因

execute_code 运行器参数构造与 gateway CLI 不兼容（环境侧问题，非业务代码问题）。

## 解决方案

绕过：改用 `exec_command` 调用 venv Python（`C:\Users\ASUS\.workbuddy\binaries\python\envs\default\Scripts\python.exe`）执行脚本文件（先写临时 .py 再运行）。全程无阻塞。

## 教训

执行环境有坑时先探测可用通道；venv Python + 临时脚本文件是 Windows 下稳定组合。
