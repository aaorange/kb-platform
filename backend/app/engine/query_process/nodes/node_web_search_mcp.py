# -*- coding: utf-8 -*-
"""联网搜索节点（MCP）— 企业知识库默认关闭

修复课程版三处问题：未完成的循环体、params 拼写错（parems→params）、
Bearer 后缺空格。

实现方式：DashScope MCP streamable-http 的最小 JSON-RPC 客户端
（initialize → notifications/initialized → tools/call），不依赖 agents SDK。
"""
import json

import httpx

from app.engine.config.config import mcp_config
from app.engine.query_process.base import NodeBase
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger


class NodeWebSearchMcp(NodeBase):
    """联网搜索补充（WEB_MCP_ENABLE=1 时启用）"""

    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        if not mcp_config.enabled:
            return {"web_search_docs": []}
        try:
            query = state.get("rewritten_query")
            pages = self._mcp_call(query)
            docs = []
            for item in pages:
                snippet = item.get("snippet") or ""
                if not snippet:
                    continue
                docs.append({
                    "title": item.get("title") or "",
                    "content": snippet,
                    "url": item.get("url"),
                    "source": "web",
                })
            return {"web_search_docs": docs}
        except Exception as e:  # noqa: BLE001
            logger.exception("MCP 联网搜索失败：%s", e)
            return {"web_search_docs": []}

    def _mcp_call(self, query: str) -> list[dict]:
        """最小 MCP JSON-RPC 会话"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {mcp_config.api_key}",
        }
        with httpx.Client(timeout=30, headers=headers) as client:
            # 1. initialize
            init_resp = client.post(mcp_config.mcp_base_url, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "kb-platform", "version": "1.0"},
                },
            })
            init_resp.raise_for_status()
            # 2. initialized 通知
            client.post(mcp_config.mcp_base_url, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            # 3. tools/call
            call_resp = client.post(mcp_config.mcp_base_url, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "bailian_web_search",
                    "arguments": {"query": query, "count": 5},
                },
            })
            call_resp.raise_for_status()
            payload = self._parse_response(call_resp)
            content = payload.get("result", {}).get("content", [])
            if not content:
                return []
            data = json.loads(content[0].get("text", "{}"))
            return data.get("pages") or []

    @staticmethod
    def _parse_response(resp: httpx.Response) -> dict:
        """兼容 JSON 与 SSE 两种响应格式"""
        text = resp.text.strip()
        if text.startswith("{"):
            return json.loads(text)
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
