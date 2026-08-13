"""web_fetch 工具：抓取 URL 正文（简单 HTML 清洗）。

架构 6 章工具生态扩展。补全「搜索 → 抓正文 → 深入总结」链路：
LLM 调 web_search 拿到标题+链接后，可调 web_fetch(url) 抓正文深入阅读再总结。

数据源说明：jina reader（r.jina.ai，HTML 转 markdown 的免费服务）在国内不可达
（超时），故用「直接抓取 + 正则清洗」实现，清洗质量够 LLM 提炼正文用。

安全：
- 仅允许 http/https（防 SSRF 伪协议）
- 超时 + 大小上限，防抓取失控
"""
from __future__ import annotations

import re
import urllib.request
from typing import Any, Dict

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# 提取正文块（段落/标题/列表项/表格单元）
_BLOCK_RE = re.compile(
    r"<(p|h[1-6]|li|blockquote|td|dt|dd)[^>]*>([\s\S]*?)</\1>",
    re.I,
)

_ENTITY = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def _clean_html(html: str) -> str:
    """去 script/style/head/注释，提取正文块文本。"""
    html = re.sub(
        r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<head[\s\S]*?</head>|<nav[\s\S]*?</nav>|<footer[\s\S]*?</footer>",
        "",
        html,
        flags=re.I,
    )
    html = re.sub(r"<!--[\s\S]*?-->", "", html)
    texts = []
    for _tag, content in _BLOCK_RE.findall(html):
        t = re.sub(r"<[^>]+>", "", content)
        for k, v in _ENTITY.items():
            t = t.replace(k, v)
        t = t.strip()
        if t and len(t) > 1:
            texts.append(t)
    # 去重（相邻重复块）
    seen = set()
    out = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return "\n".join(out)


def web_fetch(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """抓取 URL 正文。返回 {url, ok, length, content} 或 {url, ok, error}。"""
    if not url.startswith(("http://", "https://")):
        return {"url": url, "ok": False, "error": "仅支持 http/https 链接"}
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        raw = urllib.request.urlopen(req, timeout=12).read()
        # 尝试 utf-8，失败退回忽略错误
        html = raw.decode("utf-8", "ignore")
        text = _clean_html(html)
        if not text:
            return {"url": url, "ok": False, "error": "未提取到正文（可能是 JS 渲染页面或反爬）"}
        return {"url": url, "ok": True, "length": len(text), "content": text[:max_chars]}
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:200]}
