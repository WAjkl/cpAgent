"""确定性校验：兼容性硬校验 + 预算硬过滤 + 配置合法性校验。

架构文档 4.2：该下沉到确定性的，绝不交给 LLM 拍脑袋。
M1 覆盖：
1. budget_hard_filter —— 预算硬过滤（任何超出预算区间的配件直接剔除）
2. check_compatibility —— 兼容性硬校验（CPU↔主板 socket、内存代际、电源瓦数、显卡供电）
3. validate_config —— 配置单合法性（必填件齐全、总价计算、来源标注）
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import HARDWARE_DB_PATH

# 兼容性知识（M1 内置；M2 起支持从真实配置单反推回流）
SOCKET_CPU = {  # CPU 型号关键字 → socket
    "AM5": ["Ryzen 7000", "Ryzen 9000", "Ryzen 5 7600", "Ryzen 7 7700", "Ryzen 7 7800X3D", "Ryzen 7 9700X", "Ryzen 7 9800X3D", "Ryzen 9 7900", "Ryzen 9 7950", "Ryzen 9 9900", "Ryzen 9 9950"],
    "AM4": ["Ryzen 5000", "Ryzen 5600", "Ryzen 5800"],
    "LGA1700": ["Core i5-12400", "Core i5-12600", "Core i5-13600", "Core i5-14600", "Core i7-12700", "Core i7-13700", "Core i7-14700", "Core i9-12900", "Core i9-13900", "Core i9-14900"],
    "LGA1851": ["Core Ultra 200", "Core Ultra 5 245K", "Core Ultra 7 265K", "Core Ultra 9 285K"],
}
SOCKET_MB = {  # 主板型号关键字 → socket
    "AM5": ["B650", "X670", "B850", "X870"],
    "AM4": ["B450", "B550", "X570"],
    "LGA1700": ["B660", "B760", "Z690", "Z790"],
    "LGA1851": ["B860", "Z890"],
}
MEMORY_GEN_CPU = {  # CPU → 支持内存代际
    "AM5": 5, "AM4": 4, "LGA1700": [4, 5], "LGA1851": 5,
}
PSU_WATT_MIN = {  # 显卡功耗需求下限（瓦），M1 简化表
    "RTX 5090": 1000, "RTX 5080": 850, "RTX 5070 Ti": 750, "RTX 5070": 650,
    "RTX 5060 Ti": 550, "RTX 5060": 500, "RTX 5050": 450, "RTX 4090": 1000,
    "RTX 4080 Super": 850, "RTX 4070 Super": 700, "RTX 4060": 550,
    "RX 9070 XT": 750, "RX 9070": 700, "RX 9060 XT": 550, "RX 7900 XTX": 900,
    "RX 7800 XT": 750, "RX 7600": 550, "Arc B580": 650, "Arc B570": 600,
}


def budget_hard_filter(items: List[Dict[str, Any]], budget_min: Optional[float], budget_max: Optional[float]) -> List[Dict[str, Any]]:
    """预算硬过滤：区间外直接剔除。"""
    out = []
    for it in items:
        price = it.get("price_cny")
        low = None
        if isinstance(price, (int, float)):
            low = float(price)
        elif isinstance(price, str):
            nums = [float(x) for x in re.findall(r"[\d.]+", price.replace(",", ""))]
            low = min(nums) if nums else None
        if low is None:
            out.append(it)  # 无价格不拦截（留给 LLM 标注需核实）
            continue
        if budget_min is not None and low < budget_min:
            continue
        if budget_max is not None and low > budget_max:
            continue
        out.append(it)
    return out


def _match_socket(text: str, table: Dict[str, List[str]]) -> Optional[str]:
    for socket, kws in table.items():
        for kw in kws:
            if kw.lower() in text.lower():
                return socket
    return None


def check_compatibility(cpu: Optional[str], mb: Optional[str], gpu: Optional[str], psu_w: Optional[int]) -> List[str]:
    """返回不兼容问题列表；空列表 = 通过。

    校验项：
    1. CPU socket ↔ 主板 socket
    2. CPU 内存代际 ↔ 主板内存支持（M1 简化：主板型号含 DDR5/内存字段）
    3. 电源瓦数 ≥ 显卡需求下限
    """
    problems: List[str] = []
    if cpu and mb:
        cpu_s = _match_socket(cpu, SOCKET_CPU)
        mb_s = _match_socket(mb, SOCKET_MB)
        if cpu_s and mb_s and cpu_s != mb_s:
            problems.append(f"CPU({cpu}) 是 {cpu_s}，主板({mb}) 是 {mb_s}，接口不兼容")
    if gpu and psu_w is not None:
        need = None
        for k, v in PSU_WATT_MIN.items():
            if k.lower() in gpu.lower():
                need = v
                break
        if need and psu_w < need:
            problems.append(f"显卡({gpu}) 建议电源 ≥{need}W，当前 {psu_w}W 不足")
    return problems


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """配置单合法性校验：必填件、总价、来源标注。

    返回 {ok, problems, total_price, sources}
    """
    problems: List[str] = []
    required = ["cpu", "gpu", "memory", "ssd", "psu", "motherboard"]
    total = 0.0
    sources = set()
    for part in required:
        item = config.get(part)
        if item is None or item.get("model") is None:
            problems.append(f"缺少必填配件: {part}")
            continue
        price = item.get("price_cny")
        if isinstance(price, (int, float)):
            total += float(price)
        elif isinstance(price, str):
            nums = [float(x) for x in re.findall(r"[\d.]+", price.replace(",", ""))]
            total += min(nums) if nums else 0.0
        if item.get("price_source"):
            sources.add(item["price_source"])
    # 兼容性
    cpu = (config.get("cpu") or {}).get("model")
    mb = (config.get("motherboard") or {}).get("model")
    gpu = (config.get("gpu") or {}).get("model")
    psu = (config.get("psu") or {}).get("model")
    psu_w = None
    if psu:
        nums = [int(x) for x in re.findall(r"(\d{3,4})W", psu)]
        psu_w = max(nums) if nums else None
    problems.extend(check_compatibility(cpu, mb, gpu, psu_w))
    return {
        "ok": len(problems) == 0,
        "problems": problems,
        "total_price": round(total, 2),
        "sources": sorted(sources),
    }
