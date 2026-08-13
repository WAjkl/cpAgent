# ISSUE-016 electron-vite 脚手架配置踩坑（tsconfig composite + tailwind/postcss ESM）

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（M3 脚手架 typecheck/build 首次跑通前卡住）

## 现象与根因

1. **tsconfig composite 与 --noEmit 冲突**：tsconfig 用了 `composite: true`（为了 project references），但 `typecheck` 脚本是 `tsc --noEmit`，两者矛盾（composite 项目不允许关闭 emit）。
2. **MODULE_TYPELESS_PACKAGE_JSON 警告**：`tailwind.config.js` / `postcss.config.js` 写了 `export default`（ESM），但 `package.json` 无 `"type": "module"`，vite 报 `Module type ... is not specified and it doesn't parse as CommonJS`，重解析有性能开销。

## 解决方案

1. 去掉 `composite: true`；根 `tsconfig.json` 改为 `{ "extends": "./tsconfig.web.json" }`，node/web 两个配置独立 `tsc --noEmit` 检查
2. `tailwind.config.js` / `postcss.config.js` 改 CommonJS `module.exports = {...}`（保持 package.json 无 type:module，避免 electron 主进程 ESM/CJS 之争）

## 设计原则

- 项目引用（references）才需要 composite；纯 typecheck 场景直接去掉
- electron-vite 默认主进程 CJS 输出，配置文件统一走 CommonJS 最省心
