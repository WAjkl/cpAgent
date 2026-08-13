# ISSUE-015 Python 脚本在 Windows GBK 控制台输出 emoji 报 UnicodeEncodeError

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：低（测试脚本在 Windows 控制台直接崩溃，重复踩了两次）

## 现象

`python scripts/test_m2.py` 与 `scripts/smoke_test.py` 在 Windows 控制台报：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2705' in position ...
```

## 根因

Windows 控制台默认 GBK 编码；Python 3 的 `print` 输出 emoji（✅❌⚠️）时，GBK 无法编码这些字符，直接抛异常。`smoke_test.py` 是 M1 遗留，`test_m2.py` 是 M2 新增，两个都踩了。

## 解决方案

测试脚本输出改用 ASCII 标记：`✅ PASS`→`[PASS]`、`❌ FAIL`→`[FAIL]`、`⚠️`→`[WARN]`。

## 设计原则

- 跨平台 Python 脚本的 `print` 避免 emoji / 非 GBK 字符
- 若确需输出 Unicode，开头加 `sys.stdout.reconfigure(encoding='utf-8')`，或运行前 `set PYTHONIOENCODING=utf-8`
