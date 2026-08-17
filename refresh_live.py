"""refresh_live.py — 把 GPU 真实街价刷新进 price_cache.db。

让 config-gen 生成的配置单用上 live 价（而非 2026-08-13 快照）。
运行（仓库根目录，需联网）：
    python refresh_live.py

每日跑一次即可保持 GPU 价格新鲜；内存/SSD/电源/主板仍为快照估算
（后续接入京东/慢慢买适配器后可一并刷新）。

注：videocardprices.com 为美元全球街价（含 eBay used），与国内京东
零售价有差距，作趋势/参考用；中国实际成交价以京东为准。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.browser_price import search_price, PriceCache

REPO = os.path.dirname(os.path.abspath(__file__))
db = json.load(open(os.path.join(REPO, "data", "hardware_db.json"), encoding="utf-8"))
gpus = [g["model"] for g in db["gpu"]]

cache = PriceCache()
ok = fail = 0
for m in gpus:
    q = search_price(m, "gpu", cache=cache, force_refresh=True)
    if q.get("source") == "live":
        ok += 1
        print(f"  {m:<24} live  ¥{q['price_cny']}")
    else:
        fail += 1
        print(f"  {m:<24} {q.get('source'):<8} ¥{q.get('price_cny')} (站点未覆盖/降级)")

print(f"\nGPU 实时刷新完成：{ok} live / {fail} 降级快照")
print("缓存已写入:", cache.db_path)
