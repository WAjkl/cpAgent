"""refresh_live.py — 把 GPU/CPU/内存/SSD/主板 实时价刷新进 price_cache.db。

让 config-gen 生成的配置单用上 live 价（而非 2026-08-13 快照）。
运行（仓库根目录，需联网）：
    python refresh_live.py

每日跑一次即可保持价格新鲜；PSU（电源）无免费稳定实时源，保持快照估算。

价格源：
- GPU：videocardprices.com（美元全球街价，含 eBay used，作趋势/参考）
- CPU/内存/SSD/主板：techpartprices.com 公开 API（Amazon UK 全新含税价，GBP）
两者与国内京东零售价有差距，作参考；中国实际成交价以京东为准。
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.browser_price import search_price, PriceCache

REPO = os.path.dirname(os.path.abspath(__file__))
db = json.load(open(os.path.join(REPO, "data", "hardware_db.json"), encoding="utf-8"))

CATS = ("gpu", "cpu", "memory", "ssd", "motherboard")  # PSU 无源，保持快照
jobs = [(it["model"], cat) for cat in CATS for it in db.get(cat, []) if it.get("model")]

cache = PriceCache()


def work(job):
    m, cat = job
    time.sleep(0.8)  # 低频间隔（配合并发 2，对公开 API 保持礼貌）
    q = search_price(m, cat, cache=cache, force_refresh=True)
    return (m, cat, q)


ok = fail = 0
by_cat = {}
with ThreadPoolExecutor(max_workers=2) as ex:
    for m, cat, q in ex.map(work, jobs):
        is_live = q.get("source") == "live"
        ok += 1 if is_live else 0
        fail += 0 if is_live else 1
        bc = by_cat.setdefault(cat, {"total": 0, "live": 0, "estimate": 0})
        bc["total"] += 1
        bc["live"] += 1 if is_live else 0
        bc["estimate"] += 0 if is_live else 1
        tag = "live" if is_live else "estimate"
        print(f"  [{cat:<11}] {m:<30} {tag:<9} ¥{q.get('price_cny')}")

print(f"\n全品类实时刷新完成：{ok} live / {fail} 降级快照")
for cat, v in by_cat.items():
    print(f"  {cat:<11} total={v['total']:<3} live={v['live']:<3} estimate={v['estimate']}")
print("缓存已写入:", cache.db_path)
