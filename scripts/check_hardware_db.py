# -*- coding: utf-8 -*-
"""
cpAgent 硬件库自检脚本（M1 前置）
=================================
校验 data/hardware_db.json：
  - 必填字段齐全（每类别各自 schema）
  - 无 null 价格、价格区间合法（low <= price <= high）
  - 型号无重复
  - confidence 在 (0,1]
  - price_source 属于 {live, estimate}
退出码：0 = 通过；1 = 有问题（打印明细）
"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "hardware_db.json")

REQUIRED = {
    "cpu": ["model", "brand", "arch", "cores_threads", "socket", "boost_ghz", "tdp_w",
            "ludashi_score", "gaming_pct", "tier", "price_cny", "price_low", "price_high",
            "price_source", "price_note", "fetched_at", "confidence", "use_case"],
    "gpu": ["model", "brand", "arch", "vram_gb", "vram_type", "perf_pct", "tier",
            "price_cny", "price_low", "price_high", "price_source", "price_note",
            "fetched_at", "confidence", "use_case"],
    "memory": ["model", "brand", "type", "kit", "cas", "price_cny", "price_low", "price_high",
               "price_source", "price_note", "fetched_at", "confidence", "use_case"],
    "ssd": ["model", "brand", "interface", "capacity_gb", "read_mb_s", "write_mb_s",
            "price_cny", "price_low", "price_high", "price_source", "price_note",
            "fetched_at", "confidence", "use_case"],
    "psu": ["model", "brand", "wattage_w", "cert", "standard", "price_cny", "price_low",
            "price_high", "price_source", "price_note", "fetched_at", "confidence", "use_case"],
    "motherboard": ["model", "brand", "socket", "chipset", "form", "price_cny", "price_low",
                    "price_high", "price_source", "price_note", "fetched_at", "confidence", "use_case"],
}

def main():
    if not os.path.exists(DB):
        print(f"[FAIL] 缺失 {DB}")
        return 1
    db = json.load(open(DB, encoding="utf-8"))
    problems = []
    total = 0
    for cat, fields in REQUIRED.items():
        items = db.get(cat, [])
        total += len(items)
        models = [it.get("model") for it in items]
        for it in items:
            for f in fields:
                if f not in it:
                    problems.append(f"{cat}/{it.get('model')} 缺字段 {f}")
            p = it.get("price_cny")
            if p is None:
                problems.append(f"{cat}/{it.get('model')} price_cny=None")
            lo, hi = it.get("price_low"), it.get("price_high")
            if lo is not None and hi is not None and not (lo <= p <= hi):
                problems.append(f"{cat}/{it.get('model')} 价格区间非法 low={lo} price={p} high={hi}")
            if it.get("price_source") not in ("live", "estimate"):
                problems.append(f"{cat}/{it.get('model')} price_source={it.get('price_source')}")
            c = it.get("confidence")
            if not (isinstance(c, (int, float)) and 0 < c <= 1):
                problems.append(f"{cat}/{it.get('model')} confidence={c}")
        dup = {m for m in set(models) if models.count(m) > 1}
        if dup:
            problems.append(f"{cat} 重复型号: {dup}")
    if problems:
        print(f"[FAIL] 共 {len(problems)} 个问题:")
        for p in problems[:50]:
            print("  -", p)
        return 1
    print(f"[OK] 自检通过：{total} 条记录（{list(REQUIRED.keys())}），schema/价格/重复/来源全部合法")
    return 0

if __name__ == "__main__":
    sys.exit(main())
