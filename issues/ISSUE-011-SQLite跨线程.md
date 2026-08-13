# ISSUE-011 FastAPI 线程池触发 SQLite 跨线程错误

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：高（M2.6 server 的 /config、/chat 端点全部报错）

## 现象

`POST /config` 首次请求报 `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`，FastAPI 端点全部 500。

## 根因

- FastAPI 对同步 `def` 端点用 `run_in_threadpool` 丢到线程池执行
- `PriceCache` / `LongTermMemory` / `EvidenceStore` 的 sqlite3 连接在主线程（模块导入时）创建
- 线程池线程复用时跨线程访问同一 sqlite3 连接 → sqlite3 的线程亲和性限制触发

## 解决方案

三个 SQLite 类的 `sqlite3.connect(str(path))` 统一加 `check_same_thread=False`：

```python
self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
```

v0（桌面单用户）场景可接受；若未来多并发，需改为连接池或每请求独立连接 + 写锁。

## 设计原则

- 单例缓存（PriceCache/LongTermMemory）跨线程共享时，SQLite 连接必须 `check_same_thread=False`
- 桌面端单用户低并发；服务端多并发需引入连接池（挂账到 M4 性能与稳定性）
