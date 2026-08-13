# ISSUE-003 硬件数据源反爬拦截（TechPowerUp）

- **日期**：2026-08-13
- **状态**：✅已解决（换源）
- **影响**：中（GPU 规格库无法直抓，但未阻塞整体目标）

## 现象

`https://www.techpowerup.com/gpu-specs/` 返回 "Automated bot check in progress"，页面加载 JS 反爬（Token + WebSocket + drag captcha 多阶段），无 headless 浏览器无法绕过。

## 根因

TechPowerUp 部署了 Cloudflare 风格 PoW/验证码反爬（`/.firewall` 接口 + TOKEN 挑战）。

## 解决方案

不硬刚（符合"遇 WAF/反爬不硬刚"原则）：
1. GPU 价格换 videocardprices.com —— JSON-LD Product 结构，`offers.price` 直接可解析
2. GPU 规格（架构/显存/性能分）用知识库内嵌 + `perf_notes` 标注"近似值待校准"
3. 后续如需精确规格，browser-price-mcp 阶段用 Playwright 无头浏览器 + 低频策略

## 教训

爬数据优先找"结构化友好"源；反爬强的站点不要投入头铁，换源或换形态。
