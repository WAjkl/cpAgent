"""config-gen-mcp：配置单生成器（预算穷举 + 游戏/生产力双维度打分 + 兼容硬校验）。

架构 M2 任务 2.1。落地为进程内函数工具。

算法：分层候选 + 约束穷举（非全排列）：
  1. GPU 候选：预算 50% 内 + 分辨率下限，按性能排序取 top
  2. CPU 候选：按 use_case 性能排序取 top
  3. 主板：按 CPU socket 匹配（兼容硬约束）
  4. 内存：按 CPU 内存代际匹配（DDR4/DDR5）
  5. SSD / 电源：按容量 / 瓦数（满足 GPU 需求）取 top
  6. 穷举组合 → 预算硬过滤 + 兼容校验 → 双维度打分 → top-K

输出 schema 对齐前端「配置单卡片」：六大件明细 + 总价 + 用途标签 +
性能双进度条(game/productivity) + 兼容性校验 + 价格来源/新鲜度。
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .config import HARDWARE_DB_PATH
from .price_cache import PriceCache, _parse_price
from .validators import PSU_WATT_MIN, check_compatibility

# 各层候选上限（控制组合数，避免指数爆炸）
GPU_TOP = 8
CPU_TOP = 6
MB_TOP = 3
MEM_TOP = 3
SSD_TOP = 3
PSU_TOP = 4

# 分辨率 → GPU 最低性能分（perf_pct，5090=100）
RES_MIN_GPU = {"4K": 80, "2K": 45, "1080p": 25}

# 电源需求兜底（validators.PSU_WATT_MIN 缺失时的默认）
PSU_NEED_DEFAULT = 550


def _load_db() -> Dict[str, Any]:
    with open(HARDWARE_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _gpu_perf(gpu: Dict[str, Any]) -> float:
    return float(gpu.get("perf_pct") or 0)


def _cpu_gaming(cpu: Dict[str, Any]) -> float:
    return float(cpu.get("gaming_pct") or 0)


def _cpu_prod(cpu: Dict[str, Any]) -> float:
    # passmark_mark 归一化到 0-100（~70000 封顶）
    return min(float(cpu.get("passmark_mark") or 0) / 700.0, 100.0)


def _memory_gen(mem: Dict[str, Any]) -> int:
    t = (mem.get("type") or "").upper()
    if "DDR5" in t:
        return 5
    if "DDR4" in t:
        return 4
    return 0


def _score(parts: Dict[str, Dict[str, Any]]) -> Tuple[float, float]:
    """返回 (gaming_score, productivity_score)，各 0-100。"""
    gpu = parts.get("gpu") or {}
    cpu = parts.get("cpu") or {}
    mem = parts.get("memory") or {}
    ssd = parts.get("ssd") or {}

    g_perf = _gpu_perf(gpu)
    c_gaming = _cpu_gaming(cpu)
    c_prod = _cpu_prod(cpu)

    # 内存：代际 + 容量
    mem_gen = _memory_gen(mem)
    mem_bonus = 10 if mem_gen == 5 else (6 if mem_gen == 4 else 4)
    mem_prod_bonus = 15 if mem_gen == 5 else (8 if mem_gen == 4 else 5)

    # SSD：接口 + 容量
    ssd_iface = (ssd.get("interface") or "").lower()
    ssd_bonus = 9 if "4.0" in ssd_iface else 6
    ssd_prod_bonus = min(float(ssd.get("capacity_gb") or 512) / 100.0, 10.0)

    gaming = round(g_perf * 0.45 + c_gaming * 0.35 + mem_bonus + ssd_bonus, 1)
    prod = round(c_prod * 0.55 + g_perf * 0.20 + mem_prod_bonus + ssd_prod_bonus, 1)
    return (min(gaming, 100.0), min(prod, 100.0))


def _score_key(use_case: str, scores: Tuple[float, float]) -> float:
    gaming, prod = scores
    if use_case == "gaming":
        return gaming
    if use_case == "productivity":
        return prod
    return (gaming + prod) / 2.0


def _part_out(item: Dict[str, Any], cache: Optional[PriceCache] = None) -> Dict[str, Any]:
    """把硬件条目转成配置单 part 对象（附新鲜度/来源，供前端状态点）。"""
    out = dict(item)
    out["price"] = _parse_price(item.get("price_cny"))
    if cache:
        f = cache.freshness(item.get("model", ""))
        if f:
            out["level"] = f["level"]
    return out


def generate_config(
    budget: float,
    use_case: str = "gaming",
    resolution: Optional[str] = None,
    exclude: Optional[List[str]] = None,
    top_k: int = 1,
    cache: Optional[PriceCache] = None,
) -> List[Dict[str, Any]]:
    """生成配置单。返回 top-K 份（按 use_case 对应维度降序）。

    无可行解时返回空列表（诚实收敛，不硬凑）。
    """
    db = _load_db()
    cache = cache or PriceCache()
    if cache.count() == 0:
        cache.seed_from_hardware_db()
    # 若 price_cache 中有 live 记录（refresh_live.py 刷新），用实时价覆盖快照价
    live_map: Dict[str, float] = {}
    for _r in cache.all():
        if _r.get("source") == "live":
            live_map[_r["model"]] = _r["price_cny"]
    use_case = use_case if use_case in ("gaming", "productivity", "balanced") else "gaming"

    # ---------- 1. 分层候选 ----------
    # 显卡预算上限放宽到 65%：高预算（如 5 万）时旗舰卡占比可超 50%，否则锁死在 RTX 4090 一档
    gpu_budget = budget * 0.65
    gpus = [g for g in db.get("gpu", []) if _parse_price(g.get("price_cny")) <= gpu_budget]
    if resolution in RES_MIN_GPU:
        gpus = [g for g in gpus if _gpu_perf(g) >= RES_MIN_GPU[resolution]]
    gpus.sort(key=lambda g: -_gpu_perf(g))
    gpus = gpus[:GPU_TOP]

    cpus = sorted(db.get("cpu", []), key=lambda c: -(_cpu_gaming(c) if use_case == "gaming" else _cpu_prod(c)))
    cpus = cpus[:CPU_TOP]

    mb_by_socket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for mb in db.get("motherboard", []):
        mb_by_socket[mb.get("socket", "?")].append(mb)

    mem_by_gen: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for mem in db.get("memory", []):
        mem_by_gen[_memory_gen(mem)].append(mem)

    ssds = sorted(db.get("ssd", []), key=lambda s: -float(s.get("capacity_gb") or 0))[:SSD_TOP]
    psus = sorted(db.get("psu", []), key=lambda p: _parse_price(p.get("price_cny")) or 0)

    # ---------- 2. 约束穷举 ----------
    configs: List[Dict[str, Any]] = []
    for gpu in gpus:
        gpu_name = gpu.get("model", "")
        psu_need = _psu_need(gpu_name)
        psus_ok = [p for p in psus if float(p.get("wattage_w") or 0) >= psu_need][:PSU_TOP]
        for cpu in cpus:
            socket = cpu.get("socket")
            mbs = mb_by_socket.get(socket, [])[:MB_TOP]
            mems = mem_by_gen.get(_mem_gen_of_cpu(socket), [])[:MEM_TOP]
            if not mbs or not mems:
                continue
            for mb in mbs:
                for mem in mems:
                    for ssd in ssds:
                        for psu in psus_ok:
                            parts = {}
                            for _k, _it in (("cpu", cpu), ("gpu", gpu), ("memory", mem),
                                           ("ssd", ssd), ("psu", psu), ("motherboard", mb)):
                                _it2 = dict(_it)
                                if _it2.get("model") in live_map:
                                    _it2["price_cny"] = live_map[_it2["model"]]
                                    _it2["price_source"] = "live"
                                parts[_k] = _it2
                            total = sum(_parse_price(p.get("price_cny")) or 0 for p in parts.values())
                            if total > budget:
                                continue
                            problems = check_compatibility(
                                cpu.get("model"), mb.get("model"),
                                gpu.get("model"), int(psu.get("wattage_w") or 0),
                            )
                            if problems:
                                continue
                            gaming, prod = _score(parts)
                            configs.append({
                                "parts": {k: _part_out(v, cache) for k, v in parts.items()},
                                "total_price": round(total, 2),
                                "gaming_score": gaming,
                                "productivity_score": prod,
                            })

    # ---------- 3. 排序取 top-K ----------
    configs.sort(key=lambda c: (-_score_key(use_case, (c["gaming_score"], c["productivity_score"])), c["total_price"]))
    configs = configs[:top_k]

    # ---------- 4. 组装输出 ----------
    out: List[Dict[str, Any]] = []
    for c in configs:
        parts = c["parts"]
        comp = check_compatibility(
            parts["cpu"].get("model"), parts["motherboard"].get("model"),
            parts["gpu"].get("model"), int(parts["psu"].get("wattage_w") or 0),
        )
        levels = defaultdict(int)
        warnings: List[str] = []
        for p in parts.values():
            levels[p.get("level", "unknown")] += 1
            if p.get("price_source") == "estimate":
                warnings.append(f"{p.get('model')} 为估算价，装机前需实时刷新")
        out.append({
            "id": f"cfg-{uuid.uuid4().hex[:10]}",
            "total_price": c["total_price"],
            "use_case": use_case,
            "resolution": resolution,
            "budget": budget,
            "score": {"gaming": c["gaming_score"], "productivity": c["productivity_score"]},
            "parts": parts,
            "compatibility": {"ok": len(comp) == 0, "problems": comp},
            "price_freshness": dict(levels),
            "warnings": warnings,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    return out


def _psu_need(gpu_model: str) -> int:
    for k, v in PSU_WATT_MIN.items():
        if k.lower() in gpu_model.lower():
            return v
    return PSU_NEED_DEFAULT


def _mem_gen_of_cpu(socket: Optional[str]) -> int:
    """CPU socket → 内存代际（AM5/LGA1851=DDR5，AM4=DDR4，LGA1700 兼容 DDR4/DDR5 取 DDR5）。"""
    if socket in ("AM5", "LGA1851"):
        return 5
    if socket == "AM4":
        return 4
    if socket == "LGA1700":
        return 5  # 优先 DDR5
    return 5


def generate_best_config(
    budget: float,
    use_case: str = "gaming",
    resolution: Optional[str] = None,
    exclude: Optional[List[str]] = None,
    cache: Optional[PriceCache] = None,
) -> Optional[Dict[str, Any]]:
    """生成最优配置单（top-1）；无解返回 None。"""
    cfgs = generate_config(budget, use_case, resolution, exclude, top_k=1, cache=cache)
    return cfgs[0] if cfgs else None
