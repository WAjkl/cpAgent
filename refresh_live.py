"""refresh_live.py — 命令行全品类实时价刷新（薄封装 price_refresh.refresh_all）。

让 config-gen 生成的配置单用上 live 价（而非 2026-08-13 快照）。
运行（仓库根目录，需联网）：
    python refresh_live.py

通常不需要手动跑：后端 `python -m backend.server` 启动时会后台自动刷新；
POST /config 生成前也会按需预热。本脚本用于手动强制刷新/无人值守定时。

价格源：
- GPU：videocardprices.com（美元全球街价，含 eBay used，作趋势/参考）
- CPU/内存/SSD/主板：techpartprices.com 公开 API（Amazon UK 全新含税价，GBP）
PSU（电源）无免费稳定实时源，保持快照估算。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.price_refresh import refresh_all  # noqa: E402

result = refresh_all(force=True)  # 命令行手动跑 = 强制刷新
print(result)
print("缓存已写入: backend/data/price_cache.db")
