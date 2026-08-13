"""价格缓存（SQLite）：型号→价格→时间戳→新鲜度分级。

架构 M2 任务 2.3。为 browser-price-mcp 与 config-gen 提供价格缓存层：
- 缓存命中且新鲜 → 直接用
- 缓存命中但过期 → 用旧价但标 stale/expired，提示刷新
- 搜价失败 → 降级到 hardware_db 快照价 + 标 estimate（灰）

新鲜度分级（供前端状态点 / config-gen 提示）：
    fresh   绿 —— live/站点实时价，< 3 天
    stale   黄 —— live/站点实时价，3~7 天
    expired 灰 —— live/站点实时价 > 7 天，或 estimate 快照估算价
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PRICE_CACHE_PATH, HARDWARE_DB_PATH

FRESH_DAYS = 3
STALE_DAYS = 7


class PriceCache:
    """价格缓存（SQLite）。线程内单连接，写即 commit。"""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or PRICE_CACHE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_cache (
                model TEXT PRIMARY KEY,
                category TEXT,
                price_cny REAL,
                price_low REAL,
                price_high REAL,
                source TEXT,
                confidence REAL,
                fetched_at REAL
            )
            """
        )
        self._conn.commit()

    # ---------- 写 ----------
    def upsert(
        self,
        model: str,
        category: str,
        price: float,
        low: Optional[float] = None,
        high: Optional[float] = None,
        source: str = "estimate",
        confidence: float = 0.5,
        fetched_at: Optional[float] = None,
    ) -> None:
        """写入/更新一条价格记录。fetched_at 缺省为当前时间。"""
        self._conn.execute(
            """
            INSERT INTO price_cache (model, category, price_cny, price_low, price_high, source, confidence, fetched_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(model) DO UPDATE SET
                category=excluded.category,
                price_cny=excluded.price_cny,
                price_low=excluded.price_low,
                price_high=excluded.price_high,
                source=excluded.source,
                confidence=excluded.confidence,
                fetched_at=excluded.fetched_at
            """,
            (
                model, category, float(price),
                float(low) if low is not None else None,
                float(high) if high is not None else None,
                source, float(confidence),
                fetched_at if fetched_at is not None else time.time(),
            ),
        )
        self._conn.commit()

    # ---------- 读 ----------
    def get(self, model: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT model, category, price_cny, price_low, price_high, source, confidence, fetched_at FROM price_cache WHERE model=?",
            (model,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_many(self, models: List[str]) -> Dict[str, Dict[str, Any]]:
        out = {}
        for m in models:
            r = self.get(m)
            if r:
                out[m] = r
        return out

    def all(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT model, category, price_cny, price_low, price_high, source, confidence, fetched_at FROM price_cache ORDER BY fetched_at DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]

    # ---------- 新鲜度 ----------
    @staticmethod
    def freshness_of(record: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        """根据一条缓存记录计算新鲜度。estimate 源一律判灰（需刷新）。"""
        now = now if now is not None else time.time()
        source = record.get("source", "estimate")
        fetched_at = record.get("fetched_at") or now
        age_days = (now - fetched_at) / 86400.0
        if source == "estimate":
            level = "expired"  # 快照估算价，装机前必须刷新
        elif age_days < FRESH_DAYS:
            level = "fresh"
        elif age_days < STALE_DAYS:
            level = "stale"
        else:
            level = "expired"
        return {
            "model": record.get("model"),
            "level": level,
            "age_days": round(age_days, 2),
            "source": source,
            "fetched_at": fetched_at,
            "price_cny": record.get("price_cny"),
        }

    def freshness(self, model: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        rec = self.get(model)
        if not rec:
            return None
        return self.freshness_of(rec, now=now)

    # ---------- 预热 ----------
    def seed_from_hardware_db(self) -> int:
        """从 data/hardware_db.json 全量预热缓存（source/confidence 照搬）。"""
        with open(HARDWARE_DB_PATH, encoding="utf-8") as f:
            db = json.load(f)
        n = 0
        for cat, items in db.items():
            if not isinstance(items, list):
                continue
            for it in items:
                price = _parse_price(it.get("price_cny"))
                if price is None:
                    continue
                # fetched_at：统一用快照日期（2026-08-13 00:00 本地）
                self.upsert(
                    model=it["model"],
                    category=cat,
                    price=price,
                    low=_parse_price(it.get("price_low")),
                    high=_parse_price(it.get("price_high")),
                    source=it.get("price_source", "estimate"),
                    confidence=float(it.get("confidence", 0.5)),
                    fetched_at=_snapshot_epoch(it.get("fetched_at")),
                )
                n += 1
        return n

    def _row_to_dict(self, row) -> Dict[str, Any]:
        cols = ["model", "category", "price_cny", "price_low", "price_high", "source", "confidence", "fetched_at"]
        return dict(zip(cols, row))


def _parse_price(price: Any) -> Optional[float]:
    """价格解析：数字直接返回；区间字符串取低值。"""
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    if isinstance(price, str):
        parts = [p.strip().replace(",", "") for p in price.split("-")]
        nums = [float(p) for p in parts if p.replace(".", "").isdigit()]
        return min(nums) if nums else None
    return None


def _snapshot_epoch(date_str: Optional[str]) -> float:
    """把 'YYYY-MM-DD' 快照日期转成 epoch 秒（本地 00:00）。"""
    if not date_str:
        return time.time()
    try:
        return time.mktime(time.strptime(date_str, "%Y-%m-%d"))
    except ValueError:
        return time.time()
