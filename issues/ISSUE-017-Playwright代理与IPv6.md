# ISSUE-017 本地端到端验证的 Playwright 代理 + IPv6 监听问题

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：低（验证环境问题，非产品 bug，但排查有技巧值得留档）

## 现象

Playwright MCP 打开 `http://localhost:5174`（前端 dev server）报 `ERR_PROXY_CONNECTION_FAILED`；尝试绕过代理后，`http://127.0.0.1:5174` 报 `ERR_CONNECTION_REFUSED`。

## 根因

1. **全局代理拦截 localhost**：playwright-mcp 启动参数配了 `--proxy-server=http://127.0.0.1:8080`（渗透用的 Burp 代理），所有请求（含 localhost）都走代理，代理不稳时本地也连不上。
2. **IPv6 监听**：electron-vite dev server 监听在 IPv6 `[::1]:5174`，`127.0.0.1`（IPv4）连不上；`localhost` 才解析到 `::1`。

## 解决方案

用 `browser_run_code_unsafe` 新建 context 时显式绕过代理：

```js
browser.newContext({ proxy: { server: 'http://127.0.0.1:8080', bypass: 'localhost,127.0.0.1,::1,[::1]' } })
```

URL 用 `http://localhost:5174`（而非 127.0.0.1）走 IPv6。

## 设计原则

- 验证本地服务时注意 playwright 全局代理会拦截 loopback，需 bypass
- dev server 访问用 `localhost`（可能监听 ::1），别默认 127.0.0.1
