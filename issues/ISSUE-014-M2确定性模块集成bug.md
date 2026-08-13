# ISSUE-014 M2 确定性模块集成 bug（字段约定不一致 + 缓存未预热 + 贪心方向）

- **日期**：2026-08-13
- **状态**：✅已解决
- **影响**：中（price_cache/browser_price/config_gen 三模块首次联调连续踩坑）

## 现象与根因（5 处）

1. **db_path 无 Path 包装**：`PriceCache(db_path='...')` 传字符串时报 `AttributeError: 'str' object has no attribute 'parent'`。根因：`self.db_path.parent.mkdir` 假设入参是 Path。
2. **字段命名约定不一致**：适配器返回 `price_cny/price_low/price_high`，而 `PriceCache.upsert` 参数是 `price/low/high`，`cache.upsert(**quote)` 报 `unexpected keyword argument 'price_cny'`。
3. **循环变量拼写错误**：`config_gen.py` 穷举里 `int(p.get("wattage_w"))` 应为 `psu`，触发 `UnboundLocalError`（外层 `p` 是价格变量）。
4. **缓存未预热**：`generate_config` 默认空缓存，`_part_out` 查 freshness 全返回 None，配置单 `price_freshness` 全 `unknown`。
5. **贪心方向错误**：电源候选按瓦数降序，9060 XT（需求 550W）被配了 850W 过剩电源。

## 解决方案

1. `db_path = Path(db_path or PRICE_CACHE_PATH)`
2. 新增 `_upsert_quote()` 做字段映射（price_cny→price、price_low→low、price_high→high）
3. 变量名改 `psu`
4. `generate_config` 开头 `if cache.count() == 0: cache.seed_from_hardware_db()`
5. 电源按价格升序 + 排序加第二键 `total_price`（同分取低价）

## 设计原则

- 确定性模块之间的**字段命名在设计期统一**（price vs price_cny 两套命名是隐患）
- 缓存层**先预热再用**，否则新鲜度标记静默丢失
- 贪心排序要考虑「够用即止」：瓦数满足需求后按价格升序，而非盲目降序
