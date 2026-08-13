# -*- coding: utf-8 -*-
"""
cpAgent 数据地基构建脚本 v2.1（2026-08-13）
=============================================
输入：
  - ../_gpu_prices_raw.json  (videocardprices.com 2026-08-13 实测 USD 街价)
  - ../_cpu_prices_raw.json  (PassMark CPU 列表 2026-08 实测 USD 价 + CPU Mark)
输出：
  - ../data/hardware_db.json (统一 schema 的硬件库 v2.1)

诚实分级（数据质量标注，禁止把估算伪装成实测）：
  - gpu.price        : source=live    videocardprices.com 2026-08-13 实测（美元街价×汇率）
  - cpu.price        : source=live    PassMark 2026-08 实测美元价（渠道价可能偏差）
  - memory/ssd/psu/motherboard.price : source=estimate 快照估算，装机前必须 browser-price-mcp 刷新
  - perf 分          : source=approx  相对性能近似（RTX5090=100 / 鲁大师综合分），待实测校准
"""
import json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX_USD_CNY = 6.756905  # open.er-api.com 2026-08-13

def load(name):
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        print(f"[WARN] 缺失输入文件 {name}，相关类别将退化为估算")
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

GPU_RAW = load("_gpu_prices_raw.json")
CPU_RAW = load("_cpu_prices_raw.json")

def usd2cny(usd):
    try:
        return round(float(usd) * FX_USD_CNY)
    except Exception:
        return None

# videocardprices 型号 → 库型号的显式别名（避免 startswith 误匹配 5070Ti/5070）
GPU_ALIAS = {
    "RTX 5060 Ti": "RTX 5060 Ti 8GB",
}

def gpu_price_from_raw(model_norm):
    """按归一化型号找 videocardprices 实测美元价，返回 (price_cny, note) 或 None。
    精确匹配优先；别名表兜底；禁止 startswith 模糊匹配（防 5070Ti/5070 串价）。"""
    for raw in GPU_RAW:
        m = (raw.get("model") or "").strip().replace("Radeon ", "")
        if raw.get("price_usd") is None:
            continue
        if m == model_norm or GPU_ALIAS.get(m) == model_norm:
            usd = float(raw["price_usd"])
            cny = usd2cny(usd)
            note = f"videocardprices 2026-08-13 美元街价 ${usd} ×6.757 换算；国内实际零售以京东为准（2026-08 显卡暴涨期）"
            return cny, "live", note
    return None

# ---------------------------------------------------------------------------
# GPU 目录：model -> (arch, vram_gb, vram_type, perf_pct, tier, use_case, est_cny)
# 有 videocardprices 实测价的自动用实测，否则用 est_cny 估算。
# ---------------------------------------------------------------------------
GPU_CATALOG = [
    ("RTX 5090",        "Blackwell",     32, "GDDR7",  100.0, "T0", "4K/8K游戏+AI",         None),
    ("RTX 5080",        "Blackwell",     16, "GDDR7",   72.0, "T0", "4K游戏+AI",             None),
    ("RTX 5070 Ti",     "Blackwell",     16, "GDDR7",   62.0, "T1", "4K/2K游戏",             None),
    ("RTX 5070",        "Blackwell",     12, "GDDR7",   53.0, "T1", "2K游戏",                None),
    ("RTX 5060 Ti 8GB", "Blackwell",      8, "GDDR7",   44.0, "T2", "1080p/2K游戏",          None),
    ("RTX 5060",        "Blackwell",      8, "GDDR7",   37.0, "T2", "1080p游戏",             None),
    ("RTX 5050",        "Blackwell",      8, "GDDR7",   31.0, "T3", "1080p游戏",             None),
    ("RX 9070 XT",      "RDNA4",          16, "GDDR6",  68.0, "T1", "4K/2K游戏",             None),
    ("RX 9070",         "RDNA4",          16, "GDDR6",  58.0, "T1", "2K游戏",                None),
    ("RX 9060 XT",      "RDNA4",          16, "GDDR6",  48.0, "T2", "2K/1080p游戏",          None),
    ("RX 7900 XTX",     "RDNA3",          24, "GDDR6",  78.0, "T0", "4K游戏（停产清仓）",    None),
    ("RTX 4070 Super",  "Ada Lovelace",   12, "GDDR6X", 55.0, "T1", "2K/4K游戏（上代）",     None),
    ("RTX 4060",        "Ada Lovelace",    8, "GDDR6",  32.0, "T3", "1080p游戏（上代）",     None),
    ("RX 7800 XT",      "RDNA3",          16, "GDDR6",  50.0, "T2", "2K游戏（上代）",        None),
    ("RX 7600",         "RDNA3",           8, "GDDR6",  27.0, "T3", "1080p游戏（上代）",     None),
    ("Arc B580",        "Battlemage",     12, "GDDR6",  35.0, "T3", "1080p游戏",             None),
    ("Arc B570",        "Battlemage",     10, "GDDR6",  28.0, "T3", "1080p游戏",             None),
    # ---- 以下为估算补充（2026-08 常见上代型号，无当日实测价）----
    ("RTX 4090",        "Ada Lovelace",   24, "GDDR6X", 96.0, "T0", "4K游戏+AI（上代旗舰）", 15999),
    ("RTX 4080 Super",  "Ada Lovelace",   16, "GDDR6X", 80.0, "T0", "4K游戏（上代）",         8499),
    ("RTX 4060 Ti",     "Ada Lovelace",    8, "GDDR6",  38.0, "T3", "1080p游戏（上代）",     3199),
    ("RX 7900 XT",      "RDNA3",          20, "GDDR6",  74.0, "T1", "4K游戏（上代）",         5499),
    ("RX 7700 XT",      "RDNA3",          12, "GDDR6",  46.0, "T2", "2K游戏（上代）",         3499),
]

def gpu_brand(model):
    if model.startswith("RTX"):
        return "NVIDIA"
    if model.startswith("RX"):
        return "AMD"
    return "Intel"

gpus = []
for (model, arch, vram, vtype, perf, tier, use, est) in GPU_CATALOG:
    hit = gpu_price_from_raw(model)
    if hit:
        price, src, note = hit
        conf = 0.9
    else:
        price = est
        src = "estimate"
        note = "快照估算（2026-08 行情），装机前需 browser-price-mcp 实时刷新"
        conf = 0.5
    gpus.append({
        "model": model, "brand": gpu_brand(model), "arch": arch,
        "vram_gb": vram, "vram_type": vtype, "perf_pct": perf, "tier": tier,
        "msrp_usd": None, "price_cny": price,
        "price_low": price, "price_high": price,
        "price_source": src, "price_note": note,
        "fetched_at": "2026-08-13", "confidence": conf, "use_case": use,
    })
gpus.sort(key=lambda x: -x["perf_pct"])

# ---------------------------------------------------------------------------
# CPU：PassMark 实测价优先，估算兜底
# ---------------------------------------------------------------------------
def cpu_hit(model_key):
    best = None
    for o in CPU_RAW:
        n = o["name"]
        if re.search(model_key, n, re.I):
            try:
                price = float(re.sub(r"[^\d.]", "", o["price_usd"]))
            except Exception:
                continue
            mark = float(re.sub(r"[^\d.]", "", o["cpu_mark"]))
            if best is None or price < best[0]:
                best = (price, mark, o["name"])
    return best

CPU_CATALOG = [
    ("AMD Ryzen 9 9950X3D",    "AMD", "Zen 5 + 3D V-Cache", "16C/32T", "AM5", 5.7, 170, 1446426, 103, "T0", "顶级游戏+生产力",  r"Ryzen 9 9950X3D", 5599),
    ("AMD Ryzen 9 9950X",      "AMD", "Zen 5",               "16C/32T", "AM5", 5.7, 170, 1390000,  95, "T0", "生产力+游戏",      r"Ryzen 9 9950X", 4599),
    ("AMD Ryzen 9 9900X3D",    "AMD", "Zen 5 + 3D V-Cache", "12C/24T", "AM5", 5.5, 120, 1250000,  97, "T0", "游戏+生产力",      r"Ryzen 9 9900X3D", 4299),
    ("AMD Ryzen 9 9900X",      "AMD", "Zen 5",               "12C/24T", "AM5", 5.6, 120, 1200000,  88, "T1", "生产力+游戏",      r"Ryzen 9 9900X", 3299),
    ("AMD Ryzen 7 9800X3D",    "AMD", "Zen 5 + 3D V-Cache", "8C/16T",  "AM5", 5.2, 120,  940000, 100, "T0", "游戏天花板",       r"Ryzen 7 9800X3D", 3499),
    ("AMD Ryzen 7 9700X",      "AMD", "Zen 5",               "8C/16T",  "AM5", 5.5,  65,  890000,  80, "T1", "均衡",              r"Ryzen 7 9700X", 2199),
    ("AMD Ryzen 7 7800X3D",    "AMD", "Zen 4 + 3D V-Cache", "8C/16T",  "AM5", 5.0, 120,  820000,  96, "T1", "游戏（上代）",      r"Ryzen 7 7800X3D", 2799),
    ("AMD Ryzen 7 7700X",      "AMD", "Zen 4",               "8C/16T",  "AM5", 5.4, 105,  820000,  78, "T2", "均衡（上代）",      r"Ryzen 7 7700X", 1899),
    ("AMD Ryzen 5 9600X",      "AMD", "Zen 5",               "6C/12T",  "AM5", 5.4,  65,  720000,  72, "T2", "性价比游戏",        r"Ryzen 5 9600X", 1399),
    ("AMD Ryzen 5 7500F",      "AMD", "Zen 4",               "6C/12T",  "AM5", 5.0,  65,  620000,  70, "T3", "入门游戏",          r"Ryzen 5 7500F", 899),
    ("AMD Ryzen 5 7600",       "AMD", "Zen 4",               "6C/12T",  "AM5", 5.1,  65,  650000,  68, "T3", "入门游戏",          r"Ryzen 5 7600", 1099),
    ("AMD Ryzen 5 5600",       "AMD", "Zen 3",               "6C/12T",  "AM4", 4.4,  65,  480000,  55, "T3", "入门（AM4）",       r"Ryzen 5 5600", 699),
    ("Intel Core Ultra 9 285K", "Intel", "Arrow Lake-S",     "24C/24T", "LGA1851", 5.7, 125, 1330000,  90, "T0", "生产力+游戏",      r"Core Ultra 9 285K", 4399),
    ("Intel Core Ultra 7 265K", "Intel", "Arrow Lake-S",     "20C/20T", "LGA1851", 5.5, 125, 1150000,  85, "T1", "生产力+游戏",      r"Core Ultra 7 265K", 2999),
    ("Intel Core Ultra 5 245K", "Intel", "Arrow Lake-S",     "14C/14T", "LGA1851", 5.2, 125,  950000,  78, "T2", "均衡",              r"Core Ultra 5 245K", 1999),
    ("Intel Core i9-14900K",   "Intel", "Raptor Lake-R",    "24C/32T", "LGA1700", 6.0, 125, 1250000,  92, "T0", "生产力旗舰（上代）", r"i9-14900K", 3899),
    ("Intel Core i7-14700K",   "Intel", "Raptor Lake-R",    "20C/28T", "LGA1700", 5.6, 125, 1120000,  84, "T1", "生产力（上代）",    r"i7-14700K", 2899),
    ("Intel Core i7-13700K",   "Intel", "Raptor Lake",      "16C/24T", "LGA1700", 5.4, 125,  950000,  80, "T2", "均衡（上代）",      r"i7-13700K", 2499),
    ("Intel Core i5-14600K",   "Intel", "Raptor Lake-R",    "14C/20T", "LGA1700", 5.3, 125,  870000,  76, "T2", "性价比（上代）",    r"i5-14600K", 1899),
    ("Intel Core i5-12400F",   "Intel", "Alder Lake-S",     "6C/12T",  "LGA1700", 4.4,  65,  560000,  62, "T3", "入门（上代）",      r"i5-12400F", 799),
]

cpus = []
for (model, brand, arch, ct, socket, boost, tdp, lu, game, tier, use, pm_key, est) in CPU_CATALOG:
    hit = cpu_hit(pm_key)
    if hit:
        usd, mark, pm_name = hit
        price = usd2cny(usd)
        note = f"PassMark 2026-08 美元价 ${usd} ×6.757 换算；国内京东盒装价可能偏高（参考估 {est}）"
        src = "live"
        conf = 0.8
    else:
        price = est
        mark = None
        note = "快照估算（2026-08 京东盒装行情），装机前需 browser-price-mcp 实时刷新"
        src = "estimate"
        conf = 0.5
    cpus.append({
        "model": model, "brand": brand, "arch": arch, "cores_threads": ct,
        "socket": socket, "boost_ghz": boost, "tdp_w": tdp,
        "ludashi_score": lu, "gaming_pct": game, "passmark_mark": mark,
        "tier": tier, "price_cny": price,
        "price_low": price, "price_high": price,
        "price_source": src, "price_note": note,
        "fetched_at": "2026-08-13", "confidence": conf, "use_case": use,
    })

# ---------------------------------------------------------------------------
# 内存 / SSD / 电源 / 主板：规格知识 + 快照估算（2026-08 暴涨期）
# ---------------------------------------------------------------------------
memory = [
    {"model": "英睿达 16GB DDR5 5600 普条", "brand": "Crucial", "type": "DDR5-5600", "kit": "1×16GB", "cas": "CL46", "price_cny": 259,  "price_low": 239,  "price_high": 299,  "price_source": "estimate", "price_note": "2026-08 内存暴涨约400%快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "入门"},
    {"model": "金士顿 FURY Beast 16GB", "brand": "Kingston", "type": "DDR5-6000", "kit": "1×16GB", "cas": "CL30", "price_cny": 299,  "price_low": 279,  "price_high": 329,  "price_source": "estimate", "price_note": "2026-08 内存暴涨约400%快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "入门"},
    {"model": "金士顿 FURY Beast 32GB", "brand": "Kingston", "type": "DDR5-6000", "kit": "2×16GB", "cas": "CL30", "price_cny": 599,  "price_low": 549,  "price_high": 699,  "price_source": "estimate", "price_note": "2026-08 内存暴涨约400%快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "主流"},
    {"model": "芝奇 Trident Z5 Neo 32GB", "brand": "G.Skill", "type": "DDR5-6000", "kit": "2×16GB", "cas": "CL30", "price_cny": 649,  "price_low": 599,  "price_high": 749,  "price_source": "estimate", "price_note": "AMD EXPO 特调；2026-08 内存暴涨约400%快照估算", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "AMD 平台主流"},
    {"model": "金士顿 FURY Beast 64GB", "brand": "Kingston", "type": "DDR5-6000", "kit": "2×32GB", "cas": "CL30", "price_cny": 1099, "price_low": 999,  "price_high": 1299, "price_source": "estimate", "price_note": "2026-08 内存暴涨约400%快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "大内存"},
    {"model": "芝奇 Trident Z5 64GB", "brand": "G.Skill", "type": "DDR5-6400", "kit": "2×32GB", "cas": "CL32", "price_cny": 1299, "price_low": 1199, "price_high": 1499, "price_source": "estimate", "price_note": "2026-08 内存暴涨约400%快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "生产力大内存"},
]

ssd = [
    {"model": "致态 TiPlus7100 1TB", "brand": "致态", "interface": "NVMe PCIe 4.0", "capacity_gb": 1024, "read_mb_s": 7000, "write_mb_s": 6000, "price_cny": 599,  "price_low": 549,  "price_high": 699,  "price_source": "estimate", "price_note": "2026-08 SSD 普涨快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "性价比"},
    {"model": "西数 SN850X 1TB", "brand": "WD", "interface": "NVMe PCIe 4.0", "capacity_gb": 1024, "read_mb_s": 7300, "write_mb_s": 6300, "price_cny": 749,  "price_low": 699,  "price_high": 849,  "price_source": "estimate", "price_note": "2026-08 SSD 普涨快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "主流"},
    {"model": "三星 990 PRO 1TB", "brand": "Samsung", "interface": "NVMe PCIe 4.0", "capacity_gb": 1024, "read_mb_s": 7450, "write_mb_s": 6900, "price_cny": 799,  "price_low": 749,  "price_high": 899,  "price_source": "estimate", "price_note": "2026-08 SSD 普涨快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "主流旗舰"},
    {"model": "致态 TiPro7000 2TB", "brand": "致态", "interface": "NVMe PCIe 4.0", "capacity_gb": 2048, "read_mb_s": 7400, "write_mb_s": 6700, "price_cny": 1199, "price_low": 1099, "price_high": 1399, "price_source": "estimate", "price_note": "2026-08 SSD 普涨快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "大容量"},
    {"model": "三星 990 PRO 2TB", "brand": "Samsung", "interface": "NVMe PCIe 4.0", "capacity_gb": 2048, "read_mb_s": 7450, "write_mb_s": 6900, "price_cny": 1399, "price_low": 1299, "price_high": 1599, "price_source": "estimate", "price_note": "2026-08 SSD 普涨快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "大容量"},
]

psu = [
    {"model": "长城 X6 650W 金牌全模组", "brand": "长城", "wattage_w": 650, "cert": "80Plus金牌", "standard": "ATX", "price_cny": 399,  "price_low": 369,  "price_high": 459,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "入门/主流"},
    {"model": "长城 G7 750W 金牌全模组", "brand": "长城", "wattage_w": 750, "cert": "80Plus金牌", "standard": "ATX", "price_cny": 549,  "price_low": 499,  "price_high": 649,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "主流"},
    {"model": "海韵 Focus GX-750 ATX3", "brand": "Seasonic", "wattage_w": 750, "cert": "80Plus金牌", "standard": "ATX 3.0", "price_cny": 799,  "price_low": 749,  "price_high": 899,  "price_source": "estimate", "price_note": "12VHPWR 原生；快照估算", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "主流"},
    {"model": "全汉 Hydro G PRO 850W", "brand": "FSP", "wattage_w": 850, "cert": "80Plus金牌", "standard": "ATX", "price_cny": 799,  "price_low": 749,  "price_high": 899,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "中高端"},
    {"model": "振华 LEADEX III 850W 金牌", "brand": "SuperFlower", "wattage_w": 850, "cert": "80Plus金牌", "standard": "ATX", "price_cny": 899,  "price_low": 849,  "price_high": 999,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "中高端"},
    {"model": "海盗船 RM1000e ATX3.1", "brand": "Corsair", "wattage_w": 1000, "cert": "80Plus金牌", "standard": "ATX 3.1", "price_cny": 1199, "price_low": 1099, "price_high": 1399, "price_source": "estimate", "price_note": "12V-2x6 原生；快照估算", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "RTX50系高端"},
]

motherboard = [
    {"model": "微星 B650M 迫击炮 WiFi", "brand": "MSI", "socket": "AM5", "chipset": "B650", "form": "M-ATX", "price_cny": 899,  "price_low": 849,  "price_high": 999,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "AM5 入门"},
    {"model": "华硕 TUF GAMING B650M-PLUS WiFi", "brand": "ASUS", "socket": "AM5", "chipset": "B650", "form": "M-ATX", "price_cny": 999,  "price_low": 949,  "price_high": 1099, "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "AM5 主流"},
    {"model": "技嘉 B650E AORUS ELITE AX", "brand": "GIGABYTE", "socket": "AM5", "chipset": "B650E", "form": "ATX", "price_cny": 1299, "price_low": 1199, "price_high": 1499, "price_source": "estimate", "price_note": "PCIe5.0 显卡槽；快照估算", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "AM5 中高端"},
    {"model": "华硕 ROG STRIX X670E-A 吹雪", "brand": "ASUS", "socket": "AM5", "chipset": "X670E", "form": "ATX", "price_cny": 2299, "price_low": 2099, "price_high": 2599, "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "AM5 旗舰"},
    {"model": "微星 B760M 迫击炮 WiFi", "brand": "MSI", "socket": "LGA1700", "chipset": "B760", "form": "M-ATX", "price_cny": 899,  "price_low": 849,  "price_high": 999,  "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "LGA1700 入门"},
    {"model": "华硕 TUF GAMING Z890-PLUS WiFi", "brand": "ASUS", "socket": "LGA1851", "chipset": "Z890", "form": "ATX", "price_cny": 1799, "price_low": 1699, "price_high": 1999, "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "Core Ultra 主流"},
    {"model": "微星 Z890 Tomahawk WiFi", "brand": "MSI", "socket": "LGA1851", "chipset": "Z890", "form": "ATX", "price_cny": 2199, "price_low": 1999, "price_high": 2499, "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "Core Ultra 中高端"},
    {"model": "华硕 ROG STRIX Z790-A 吹雪", "brand": "ASUS", "socket": "LGA1700", "chipset": "Z790", "form": "ATX", "price_cny": 2199, "price_low": 1999, "price_high": 2499, "price_source": "estimate", "price_note": "快照估算；装机前必刷新", "fetched_at": "2026-08-13", "confidence": 0.4, "use_case": "LGA1700 中高端"},
]

# ---------------------------------------------------------------------------
# 组装输出
# ---------------------------------------------------------------------------
db = {
    "meta": {
        "name": "桌面装机硬件库（性能排名 + 参考价）",
        "version": "2.1",
        "snapshot_date": "2026-08-13",
        "currency": "CNY（人民币）",
        "fx_usd_cny": FX_USD_CNY,
        "price_warning": "2026年8月为暴涨期：GDDR7/HBM短缺+AI数据中心抢产能，显卡中端暴涨约28-39%、内存暴涨约400%、SSD普涨。本库价格为快照参考，装机前必须实时刷新。",
        "perf_notes": "CPU性能分=鲁大师综合分(2026-07快照)；CPU游戏分=Tom's Hardware 1080p相对分(9800X3D=100)；GPU性能分=光栅相对分(RTX5090=100，近似值待校准)。",
        "sources": [
            "videocardprices.com GPU street price (2026-08-13 实测)",
            "PassMark CPU Benchmarks (2026-08 实测美元价)",
            "open.er-api.com USD/CNY 汇率 (2026-08-13)",
            "鲁大师天梯榜(2026-07-16)",
            "Tom's Hardware CPU/GPU Hierarchy(2026)",
            "Techrankup GPU ranking(2026-06)",
            "华强北/电商渠道价(2026-08-06)",
            "新浪/网易/今日头条 2026-08 价格报道",
        ],
        "data_quality": {
            "gpu_price": "live（videocardprices.com 2026-08-13 实测美元街价 ×6.757）",
            "cpu_price": "live（PassMark 2026-08 实测美元价 ×6.757，京东盒装可能偏高）",
            "memory_ssd_psu_motherboard_price": "estimate（快照估算，装机前必须 browser-price-mcp 刷新）",
            "perf_score": "approx（相对性能近似，待实测校准）",
            "fetched_at": "2026-08-13",
        },
    },
    "cpu": cpus,
    "gpu": gpus,
    "memory": memory,
    "ssd": ssd,
    "psu": psu,
    "motherboard": motherboard,
}

out = os.path.join(BASE, "data", "hardware_db.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=1)

print("== 生成完成 v2.1 ==")
for k in ("cpu", "gpu", "memory", "ssd", "psu", "motherboard"):
    live = sum(1 for it in db[k] if it.get("price_source") == "live")
    print(f"  {k}: {len(db[k])} 条 (live {live} / estimate {len(db[k])-live})")
print("  文件:", out)
