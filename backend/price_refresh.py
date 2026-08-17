"""price_refresh.py — 全品类实时价刷新（单点复用）。

供三处使用，避免逻辑重复：
- server.py 启动后台自动刷新（开箱即实时）
- POST /config 生成前按需预热（live 覆盖不足时）
- Agent 工具 refresh_prices（tool_registry 注册）

纪律：低频并发（2 worker + 0.8s 间隔），1 小时（min_interval）内不重复全量刷；
价格源：GPU→videocardprices.com，CPU/内存/SSD/主板→techpartprices.com
（Amazon UK），PSU 无免费稳定源保持 estimate。
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from .config import HARDWARE_DB_PATH
from .browser_price import search_price, PriceCache

CATS = ("gpu", "cpu", "memory", "ssd", "motherboard")  # PSU 无源

_LOCK = threading.Lock()
_LAST_FULL: Dict[str, float] = {"at": 0.0}  # 进程内全量刷新时间戳


def live_coverage(cache: Optional[PriceCache] = None) -> float:
    """缓存中 live 记录占比（0~1），用于判断是否需要预热。"""
    cache = cache or PriceCache()
    rows = cache.all()
    if not rows:
        return 0.0
    live = sum(1 for r in rows if r.get("source") == "live")
    return live / len(rows)


def refresh_all(
    cache: Optional[PriceCache] = None,
    min_interval: float = 3600.0,
    force: bool = False,
) -> Dict[str, Any]:
    """全品类实时价刷新进缓存；min_interval 内重复调用直接跳过。

    Args:
        cache: 共享 PriceCache（server 传 _price_cache）。
        min_interval: 距上次全量刷新的最小间隔（秒），默认 1h。
        force: True 时忽略 min_interval 强制刷新。
    """
    cache = cache or PriceCache()
    now = time.time()
    with _LOCK:
        if not force and (now - _LAST_FULL["at"]) < min_interval:
            return {"skipped": True, "reason": "间隔内已刷新", "last_at": _LAST_FULL["at"]}
        _LAST_FULL["at"] = now  # 先占位，防并发重刷

    db = json.loads(Path(HARDWARE_DB_PATH).read_text(encoding="utf-8"))
    jobs = [(it.get("model"), cat)
            for cat in CATS
            for it in db.get(cat, []) if it.get("model")]

    def _work(job):
        m, cat = job
        time.sleep(0.8)  # 低频间隔（并发 2，整体温和）
        try:
            q = search_price(m, cat, cache=cache, force_refresh=True)
        except Exception:
            q = {"source": None}
        return (m, cat, q)

    results: Dict[Any, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        for m, cat, q in ex.map(_work, jobs):
            results[(m, cat)] = q

    live = sum(1 for q in results.values() if q.get("source") == "live")
    return {
        "parts_total": len(jobs),
        "live": live,
        "estimate": len(jobs) - live,
        "skipped": False,
        "at": now,
    }


def warmup_if_needed(cache: Optional[PriceCache] = None, min_coverage: float = 0.5) -> Dict[str, Any]:
    """生成配置前预热：live 覆盖不足则强制刷新一次（首次生成会等待 ~30s）。"""
    cache = cache or PriceCache()
    if live_coverage(cache) >= min_coverage:
        return {"skipped": True, "reason": "live 覆盖已足够", "coverage": round(live_coverage(cache), 3)}
    return refresh_all(cache=cache, force=True)
