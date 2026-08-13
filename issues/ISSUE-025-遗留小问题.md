# ISSUE-025 遗留小问题（上传 GitHub 时发现）

- **日期**：2026-08-13
- **状态**：⚠️ 挂账（3 项小问题，均不影响主流程）
- **影响**：低

## 1. test_m2 tool_registry 断言失败（pre-existing）

- **现象**：`scripts/test_m2.py:122` 断言 `len(r.list()) == 5`，但 `ToolRegistry.default()` 默认 `web_enabled=True` 已注册 7 个工具（本地 5 + `web_search` + `web_fetch`），测试 30/31，仅此项 FAIL。
- **根因**：M2 联网工具（ISSUE-020/022）新增后，测试断言未同步。
- **改法**：断言改为 `len(ToolRegistry.default(web_enabled=False).list()) == 5`（测快照模式），或期望值直接改为 7。

## 2. EvidenceStore db_path 传 str 报错

- **现象**：`EvidenceStore(db_path="临时路径.db")` 抛 `AttributeError: 'str' object has no attribute 'parent'`。
- **根因**：`evidence.py:25` 未做 `Path()` 转换（`longterm_memory.py` 的 `__init__` 做了 `Path(db_path or ...)`）。
- **改法**：`self.db_path = Path(db_path or EVIDENCE_DB_PATH)`，与 longterm_memory 对齐。

## 3. start-cpagent.bat 硬编码本机路径

- **现象**：`start-cpagent.bat` 写死 `C:\Users\<user>\miniconda3\python.exe`。
- **根因**：一键启动脚本绑定了作者本机 Python 环境。
- **改法**：改用 PATH 里的 `python`（或环境变量指定解释器），既避免换机失效，也避免公开仓库泄露本机用户名/路径。

## 设计原则

- 测试断言应跟随工具注册的默认行为同步更新，避免"新增功能 → 旧断言失败"的隐性漂移。
- 存储类构造函数对路径参数统一做 `Path()` 归一化。
