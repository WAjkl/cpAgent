"""web_search 工具：联网搜索（Tavily 主源 + Bing/百度降级 + 缓存）。

架构 6 章工具生态扩展。给 LLM 提供「联网搜索 → 挑选 → 总结」能力。

数据源优先级（均含降级）：
1. Tavily：专为 LLM 设计的搜索 API，返回 title/url/content（AI 摘要），需 TAVILY_KEY
2. Bing（cn.bing.com）：国内可达、真实 URL + 摘要，免费但可能限流
3. 百度：可达但频繁抓取触发「百度安全验证」反爬
（DuckDuckGo 被墙，弃用）

缓存：进程内 60 秒 TTL，同一 query 不重复请求。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple

from .. import config  # noqa: F401  触发 config._load_dotenv 加载 .env（TAVILY_KEY）

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_TAG_RE = re.compile(r"<[^>]+>")

# 进程内缓存：query -> (timestamp, result_dict)
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 60.0


def _clean(text: str) -> str:
    t = _TAG_RE.sub("", text)
    for k, v in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&ensp;", " "), ("&#0183;", ""), ("&#169;", "")):
        t = t.replace(k, v)
    return " ".join(t.split())


def _search_tavily(query: str, limit: int) -> List[Dict[str, str]]:
    """Tavily 搜索 API（需 TAVILY_KEY），返回 title/url/content 摘要。"""
    key = os.getenv("TAVILY_KEY", "")
    if not key:
        return []
    url = "https://api.tavily.com/search"
    body = json.dumps({"query": query, "max_results": limit, "search_depth": "basic"})
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    results: List[Dict[str, str]] = []
    for it in data.get("results", []):
        results.append({
            "title": (it.get("title") or "")[:80],
            "url": (it.get("url") or "")[:200],
            "summary": (it.get("content") or "")[:400],
        })
    return results[:limit]


def _search_bing(query: str, limit: int) -> List[Dict[str, str]]:
    """cn.bing.com 搜索，解析 b_algo 结果块（真实 URL + 摘要）。"""
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&setlang=zh-CN"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")

    results: List[Dict[str, str]] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S):
        m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.S)
        if not m:
            continue
        title = _clean(m.group(2))
        if not title:
            continue
        summ = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        summary = _clean(summ.group(1)) if summ else ""
        results.append({"title": title[:80], "url": m.group(1)[:200], "summary": summary[:300]})
    return results[:limit]


def _search_baidu(query: str, limit: int) -> List[Dict[str, str]]:
    """百度搜索（可能触发安全验证，作最后降级）。"""
    url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
    if "百度安全验证" in html or "wappass" in html:
        return []

    results: List[Dict[str, str]] = []
    for b in re.findall(r"<h3[^>]*>.*?</h3>", html, re.S):
        m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        title = _clean(m.group(2))
        if title and not any(w in title for w in ("广告", "淘宝", "天猫", "京东")):
            results.append({"title": title[:80], "url": m.group(1)[:200], "summary": ""})
    return results[:limit]


def web_search(query: str, limit: int = 8) -> Dict[str, Any]:
    """联网搜索（Tavily 主源 → Bing → 百度，逐级降级 + 缓存）。"""
    query = query.strip()
    cached = _cache.get(query)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    results: List[Dict[str, str]] = []
    source = "tavily"
    try:
        results = _search_tavily(query, limit)
    except Exception:
        results = []
    if not results:
        source = "bing"
        try:
            results = _search_bing(query, limit)
        except Exception:
            results = []
    if not results:
        source = "baidu"
        try:
            results = _search_baidu(query, limit)
        except Exception:
            results = []

    out: Dict[str, Any] = {
        "query": query,
        "source": source,
        "count": len(results),
        "results": results,
        "notice": "搜索源可能被限流；返回 0 条时可换关键词或稍后重试。",
    }
    _cache[query] = (time.time(), out)
    return out


def web_search_summarize(query: str, limit: int = 6) -> Dict[str, Any]:
    """同 web_search（别名）。"""
    return web_search(query, limit)
