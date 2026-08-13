"""工具注册表：进程内函数工具（smolagents 风格）。

架构文档 6 章"工具（MCP）"落地为 P0 进程内函数工具 + registry；
MCP 作为可选接入层，不阻塞主循环。

M1 工具：query_hardware_db / get_hardware_summary
M2 工具：search_price（搜价）/ generate_config（配置生成）/ get_price_summary（价格状态）

工具定义三要素：
    name        —— 工具名（LLM 调用时的 action）
    description —— 给 LLM 看的自然语言说明（含参数说明）
    fn          —— 实现函数（纯函数，返回可 JSON 序列化对象）
    schema      —— 参数 JSON Schema（供校验/生成提示词）
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional


class Tool:
    def __init__(self, name: str, description: str, fn: Callable, schema: Optional[Dict[str, Any]] = None):
        self.name = name
        self.description = description
        self.fn = fn
        self.schema = schema or {"type": "object", "properties": {}, "required": []}

    def invoke(self, arguments: Dict[str, Any]) -> Any:
        """调用工具；参数必须是 dict。返回结果（可 JSON 序列化）。"""
        if not isinstance(arguments, dict):
            raise TypeError(f"工具 {self.name} 参数必须是对象，收到 {type(arguments).__name__}")
        return self.fn(**arguments)

    def to_prompt(self) -> str:
        """转成给 LLM 看的工具说明。"""
        return f"- {self.name}({json.dumps(self.schema, ensure_ascii=False)}): {self.description}"


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list(self) -> List[str]:
        return list(self._tools.keys())

    def invoke(self, name: str, arguments: Dict[str, Any]) -> Any:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"未知工具: {name}")
        return tool.invoke(arguments)

    def prompt_block(self) -> str:
        """全部工具说明（注入 SystemPrompt）。"""
        lines = ["可用工具："]
        for t in self._tools.values():
            lines.append(t.to_prompt())
        return "\n".join(lines)

    @classmethod
    def default(cls, web_enabled: bool = True) -> "ToolRegistry":
        """默认注册表：M1 硬件库查询 + M2 搜价/配置生成/价格状态。"""
        reg = cls()
        from .tools.hardware_db import query_hardware_db, get_hardware_summary

        reg.register(Tool(
            name="query_hardware_db",
            description=(
                "查询装机硬件库（CPU/GPU/内存/SSD/电源/主板）。"
                "参数：category 必填（cpu/gpu/memory/ssd/psu/motherboard 之一）；"
                "可选 budget_max（预算上限，元）；可选 budget_min（预算下限）；"
                "可选 use_case（游戏优先 gaming / 生产力优先 productivity / 均衡 balanced，用于排序）。"
                "返回结构化列表：每条含 model/price_cny/price_source/confidence/关键规格。"
            ),
            fn=query_hardware_db,
            schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["cpu", "gpu", "memory", "ssd", "psu", "motherboard"]},
                    "budget_max": {"type": "number"},
                    "budget_min": {"type": "number"},
                    "use_case": {"type": "string", "enum": ["gaming", "productivity", "balanced"]},
                },
                "required": ["category"],
            },
        ))
        reg.register(Tool(
            name="get_hardware_summary",
            description="获取硬件库整体摘要（各类别条目数、live/estimate 分布、数据快照日期）。用于答疑与澄清。",
            fn=get_hardware_summary,
            schema={"type": "object", "properties": {}, "required": []},
        ))

        # ---------- M2 工具 ----------
        from .browser_price import price_summary, search_price
        from .config_gen import generate_config as _generate_config

        reg.register(Tool(
            name="search_price",
            description=(
                "按型号实时搜价。参数：model 必填（如 'RTX 5090'），category 必填。"
                "返回价格/来源/新鲜度（fresh/stale/expired）/是否降级（degraded）。"
                "搜价失败会降级到快照价并标注，禁止把降级价当实时价。"
            ),
            fn=search_price,
            schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "category": {"type": "string", "enum": ["cpu", "gpu", "memory", "ssd", "psu", "motherboard"]},
                },
                "required": ["model", "category"],
            },
        ))
        reg.register(Tool(
            name="generate_config",
            description=(
                "生成装机配置单（确定性算法：预算穷举 + 游戏/生产力双维度打分 + 兼容硬校验）。"
                "参数：budget 必填（总预算，元）；use_case 可选（gaming/productivity/balanced，默认 gaming）；"
                "resolution 可选（2K/4K/1080p）。返回 {config: 配置单} 或 {config: null, reason}。"
                "配置单含六大件明细/总价/双维度评分/兼容性/价格新鲜度。"
            ),
            fn=_config_tool,
            schema={
                "type": "object",
                "properties": {
                    "budget": {"type": "number"},
                    "use_case": {"type": "string", "enum": ["gaming", "productivity", "balanced"]},
                    "resolution": {"type": "string"},
                },
                "required": ["budget"],
            },
        ))
        reg.register(Tool(
            name="get_price_summary",
            description="获取价格缓存整体状态（总数 + fresh/stale/expired 分布），用于向用户说明价格新鲜度。",
            fn=price_summary,
            schema={"type": "object", "properties": {}, "required": []},
        ))

        # ---------- 联网搜索（仅「联网模式」注册；快照模式不联网）----------
        if web_enabled:
            # ---------- 联网搜索（给 LLM 提供「联网搜 → 挑选 → 总结」能力）----------
            from .tools.web_search import web_search

            reg.register(Tool(
                name="web_search",
                description=(
                    "联网搜索最新资料/行情/新闻（百度源）。参数：query 必填（搜索关键词），limit 可选（返回条数，默认 8）。"
                    "返回标题+链接列表。用于回答实时价格、新品发布、行情走势、新闻等本地硬件库没有的最新信息；"
                    "搜索后基于标题挑选相关结果，再总结给用户。"
                ),
                fn=web_search,
                schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "number"},
                    },
                    "required": ["query"],
                },
            ))

            from .tools.web_fetch import web_fetch

            reg.register(Tool(
                name="web_fetch",
                description=(
                    "抓取指定 URL 的网页正文（清洗 HTML 后返回纯文本）。参数：url 必填（http/https 链接）。"
                    "用于 web_search 搜到标题后，抓取具体页面正文深入阅读再总结。"
                ),
                fn=web_fetch,
                schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ))

        return reg


def _config_tool(budget: float, use_case: str = "gaming", resolution: Optional[str] = None) -> Dict[str, Any]:
    """config-gen 工具包装：返回 LLM 友好的 {config: {...}} 或 {config: null, reason}。"""
    from .config_gen import generate_config

    cfgs = generate_config(budget, use_case, resolution, top_k=1)
    if not cfgs:
        return {"config": None, "reason": f"预算 {budget} 元 / 用途 {use_case} 下无可行配置（预算过低或条件过严）"}
    return {"config": cfgs[0]}
