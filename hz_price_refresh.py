# -*- coding: utf-8 -*-
"""hz_price_refresh.py —— 国内硬件价采集器（零 API key，抓中关村在线公开报价）

为什么不用项目自带的 refresh_live.py：
  它的价源是 videocardprices.com（美元全球街价，含 eBay 二手）和 techpartprices.com
  （Amazon UK 含税英镑价），比国内实际售价高 1.5–3 倍。
  实测：RTX 4080 Super 会被算成 25681 元（国内约 8500），三星 990 PRO 2TB 比 1TB 还便宜。
  所以那套数据只能当"趋势参考"，不能当国内报价。

本采集器抓的是中关村在线（detail.zol.com.cn）各品类列表页里的「参考价」，
那是国内电商均价口径，量级正确。不需要任何 API key，只要联网。

用法：
    python hz_price_refresh.py --once      # 跑一次（推荐先用这个验证）
    python hz_price_refresh.py --loop      # 常驻，每 60 分钟跑一次
    python hz_price_refresh.py --loop --interval 30

数据安全：
  · 每个新价必须通过三道校验才写入（型号匹配度、价格量级、同品类中位数）
  · 不通过就保留原价，并在日志里记明原因
  · 写前自动备份 hardware_db.json
"""
import argparse
import json
import os
import re
import shutil
import statistics
import sys
import time
from datetime import datetime

import requests

sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ---------------- 路径 ----------------
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "hardware_db.json")
LOG_PATH = os.path.join(HERE, "data", "price_refresh.log")

# ---------------- 抓取配置 ----------------
BASE = "https://detail.zol.com.cn"
CATS = {
    "cpu": "/cpu/",
    "gpu": "/vga/",
    "memory": "/memory/",
    "psu": "/power/",
    "motherboard": "/motherboard/",
    # ssd 页面结构特殊（卡片不是 data-follow-id），暂不抓，保留快照
}
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 品牌中英对照（型号归一化用）
BRAND_ZH = {
    "samsung": "三星", "crucial": "英睿达", "kingston": "金士顿", "corsair": "海盗船",
    "asus": "华硕", "msi": "微星", "gigabyte": "技嘉", "asrock": "华擎",
    "wd": "西数", "western digital": "西数", "seagate": "希捷", "intel": "英特尔",
    "amd": "amd", "nvidia": "nvidia", "seasonic": "海韵", "super flower": "振华",
    "great wall": "长城", "g.skill": "芝奇", "team": "十铨", "adata": "威刚",
    "lexar": "雷克沙", "kioxia": "铠侠", "toshiba": "东芝", "huntkey": "航嘉",
    "fsp": "全汉", "antec": "安钛克", "deepcool": "九州风神",
}


def log(msg, also_print=True):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    if also_print:
        print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------- 解析 ----------------
def parse_cards(raw):
    """按 data-follow-id 切段解析产品卡片，避免嵌套 <li> 截断。

    中关村列表页卡片结构（实测）：
      <li data-follow-id="p2179829" ...>
        <h3><a href="..." title="AMD Ryzen 5 9600">...</a></h3>
        <div class="price-row"><b class="price-type">1349</b></div>
      </li>
    型号名后面常粘着广告文案（"高品质PCB板材，三风扇..."），要切开。
    """
    pos = [m.start() for m in re.finditer(r'data-follow-id="p\d+"', raw)]
    out = []
    for i, p in enumerate(pos):
        end = pos[i + 1] if i + 1 < len(pos) else min(p + 4000, len(raw))
        seg = raw[p:end]
        mh = re.search(r'<h3[^>]*>\s*<a[^>]*title="([^"]{2,90})"', seg)
        mp = re.search(r'<b class="price-type">([\d,]+)</b>', seg)
        if not (mh and mp):
            continue
        name = clean_name(mh.group(1))
        price = int(mp.group(1).replace(",", ""))
        if name and 50 <= price <= 200000:
            out.append((name, price))
    return out


def clean_name(s):
    """去掉广告尾巴，只留型号主体。"""
    s = re.sub(r"\s+", " ", s).strip()
    # 广告文案通常以中文描述词开头，且很长；用第一个中文字符串之前的英文型号部分
    s = re.split(r"[，,。；;]", s)[0]
    # 去掉 "支持50系显卡"、"全套压纹线" 这类尾巴
    s = re.sub(r"\s*(支持|金牌|全模|ATX\d?[.\d]*|全套|酷炫|智能|高性能|强化|快易拆|"
               r"高品质|三风扇|定制|限量|超频|白色|黑色|红色|樱花|雪装).*$", "", s)
    return s.strip()[:70]


# ---------------- 型号匹配 ----------------
def norm_model(s):
    """归一化成可比对的 token 串：小写、品牌中英统一、去掉装饰符号。"""
    t = (s or "").lower()
    for en, zh in BRAND_ZH.items():
        t = t.replace(en, zh)
    t = t.replace("×", "*").replace("（", "(").replace("）", ")")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def key_tokens(s):
    """提取关键 token：型号数字、容量、系列词，用于相似度判断。"""
    t = norm_model(s)
    toks = set()
    # 型号数字（如 4070 5090 9800 9700 265k 7500）
    for m in re.findall(r"\b\d{4,5}[a-z]{0,2}\b", t):
        toks.add(m)
    # 容量（16gb / 32gb / 1tb / 2tb / 750w）
    for m in re.findall(r"\b\d{1,4}\s?(gb|tb|w)\b", t):
        toks.add("".join(m))
    for m in re.findall(r"\b\d{1,4}(gb|tb|w)\b", t.replace(" ", "")):
        toks.add(m)
    # 关键系列词
    for w in ["x3d", "ti", "super", "pro", "plus", "max", "beast", "fury",
              "trident", "sn850", "sn770", "990", "970", "b650", "b760", "x870",
              "z890", "focus", "leadex", "core", "rm", "gx"]:
        if w in t:
            toks.add(w)
    return toks


def model_codes(s):
    """提取「型号编码」——连续的数字+字母组合，如 9950x3d / 9070xt / 5070ti / 265k。

    这是防止把 9950X3D 匹配成 9800X3D 的关键：两者系列词都是 x3d，
    但型号编码完全不同，必须精确对比。
    """
    t = norm_model(s).replace(" ", "")
    codes = set()
    # 数字开头、可带字母后缀的编码（4-5 位数字 + 可选字母数字后缀）
    for m in re.findall(r"\d{3,5}[a-z0-9]{0,4}", t):
        codes.add(m)
    return codes


def match_score(db_name, zol_name):
    """返回 0-1 的匹配分。低于 0.6 视为不同产品，丢弃。

    三道硬门槛（任一不过直接 0 分）：
      1. 型号编码必须完全一致——9950x3d ≠ 9800x3d，9070 ≠ 9070xt
      2. 容量不能冲突——16gb ≠ 32gb
      3. 品类隐含：不同品类不会进入同一次比较
    """
    a, b = norm_model(db_name), norm_model(zol_name)
    if not a or not b:
        return 0.0

    codes_a, codes_b = model_codes(db_name), model_codes(zol_name)
    if codes_a and codes_b:
        # 必须有一方包含另一方的全部编码（允许 zol 名字多带后缀）
        if not (codes_a <= codes_b or codes_b <= codes_a):
            return 0.0
    elif codes_a or codes_b:
        # 一方有型号编码另一方没有 → 不是同一个产品
        return 0.0

    ta, tb = key_tokens(db_name), key_tokens(zol_name)
    caps_a = {x for x in ta if x.endswith(("gb", "tb", "w"))}
    caps_b = {x for x in tb if x.endswith(("gb", "tb", "w"))}
    if caps_a and caps_b and not (caps_a & caps_b):
        return 0.0

    def grams(x):
        return {x[i:i + 2] for i in range(len(x) - 1)}

    ga, gb = grams(a), grams(b)
    jac = len(ga & gb) / max(len(ga | gb), 1)
    return min(jac * 1.6 + 0.15, 1.0)


# ---------------- 抓一个品类 ----------------
def fetch_category(cat, path, retries=2):
    url = BASE + path
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                log("  [%s] HTTP %s，跳过" % (cat, r.status_code))
                time.sleep(2)
                continue
            raw = r.content.decode("gb18030", errors="ignore")
            rows = parse_cards(raw)
            log("  [%s] 解析到 %d 条" % (cat, len(rows)))
            return rows
        except Exception as e:
            log("  [%s] 第 %d 次失败：%s" % (cat, attempt + 1, e))
            time.sleep(2)
    return []


# ---------------- 主流程 ----------------
def refresh_once(apply=True):
    print("=" * 70)
    log("开始刷新国内硬件价（源：中关村在线参考价）")

    if not os.path.exists(DB_PATH):
        log("找不到 hardware_db.json：%s" % DB_PATH)
        return 1

    hw = json.load(open(DB_PATH, encoding="utf-8"))
    backup = DB_PATH.replace(".json", ".backup-%s.json" % time.strftime("%Y%m%d-%H%M"))

    # 抓取
    scraped = {}
    for cat, path in CATS.items():
        scraped[cat] = fetch_category(cat, path)
        time.sleep(1.2)          # 温和访问，间隔 1.2 秒

    # 匹配 + 校验
    total_changed, total_kept, total_skip = 0, 0, 0
    report = []

    for cat, rows in scraped.items():
        items = hw.get(cat) or []
        if not items or not rows:
            continue
        zol_prices = [p for _, p in rows]
        zol_med = statistics.median(zol_prices)

        # ---- 一对一分配 ----
        # 不能「每个 db 条目各自挑最像的」，否则同一个源商品会被多条重复使用
        # （实测过：9950X3D / 9900X3D / 9800X3D / 7800X3D 全被匹配到同一个 2199）。
        # 做法：先算出所有候选对，按分数降序贪心分配，一个源商品只能用一次。
        cand = []
        for idx, it in enumerate(items):
            for zn, zp in rows:
                sc = match_score(it.get("model", ""), zn)
                if sc >= 0.6:
                    cand.append((sc, idx, zn, zp))
        cand.sort(key=lambda x: -x[0])

        used_db, used_zol = set(), set()
        assignment = {}
        for sc, idx, zn, zp in cand:
            if idx in used_db or zn in used_zol:
                continue
            used_db.add(idx)
            used_zol.add(zn)
            assignment[idx] = (sc, zn, zp)

        for idx, it in enumerate(items):
            name = it.get("model", "")
            old = it.get("price_cny")
            if idx not in assignment:
                total_skip += 1
                continue
            best_p, zname, new = assignment[idx]

            # 校验 1：价格量级（相对原价 0.4–2.5 倍）
            if old and not (old * 0.4 <= new <= old * 2.5):
                report.append((cat, name, old, new, "量级异常(%.1f×)" % (new / old), best_p))
                total_kept += 1
                continue
            # 校验 2：同品类中位数 0.2–5 倍（防止抓成别的品类价格）
            if zol_med and not (zol_med * 0.2 <= new <= zol_med * 5):
                report.append((cat, name, old, new, "偏离品类中位数", best_p))
                total_kept += 1
                continue

            if old and abs(new - old) / old < 0.03:
                total_kept += 1
                continue

            report.append((cat, name, old, new, "采用", best_p))
            it["price_cny"] = new
            it["price_low"] = round(new * 0.92)
            it["price_high"] = round(new * 1.10)
            it["price_source"] = "zol-live"
            it["fetched_at"] = time.strftime("%Y-%m-%d")
            it["confidence"] = 0.75
            it["price_note"] = "中关村在线参考价（国内电商均价口径），匹配源：%s" % zname[:36]
            total_changed += 1

    # 汇总
    log("结果：更新 %d 条 / 保留 %d 条 / 未匹配 %d 条" % (total_changed, total_kept, total_skip))
    if report:
        print("\n%-11s %-34s %8s %8s  %-14s %s" % ("品类", "型号", "原价", "新价", "说明", "匹配分"))
        print("-" * 92)
        for cat, name, old, new, note, sc in sorted(report, key=lambda x: x[0]):
            print("%-11s %-34s %8s %8s  %-14s %.2f" %
                  (cat, name[:34], old if old else "-", new, note, sc))

    if apply and total_changed:
        shutil.copyfile(DB_PATH, backup)
        hw["meta"]["last_refresh"] = time.strftime("%Y-%m-%d %H:%M")
        hw["meta"]["price_scope"] = "国内参考价（中关村在线，零 API key）"
        json.dump(hw, open(DB_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log("已写回，备份：%s" % os.path.basename(backup))
    elif not total_changed:
        log("本次无价格变化，未写文件")

    log("刷新完成")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="跑一次")
    ap.add_argument("--loop", action="store_true", help="常驻，定时跑")
    ap.add_argument("--interval", type=int, default=60, help="间隔分钟，默认 60")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写文件")
    a = ap.parse_args()

    if a.loop:
        log("常驻模式启动，每 %d 分钟刷新一次（Ctrl+C 停止）" % a.interval)
        while True:
            try:
                refresh_once(apply=not a.dry_run)
            except Exception as e:
                log("本轮异常：%s: %s" % (type(e).__name__, e))
            log("下一轮在 %d 分钟后" % a.interval)
            time.sleep(a.interval * 60)
    else:
        return refresh_once(apply=not a.dry_run)


if __name__ == "__main__":
    sys.exit(main() or 0)
