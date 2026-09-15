# -*- coding: utf-8 -*-
"""SSE 事件队列 — 替代原 sse_utils（asyncio 队列版）

查询图在线程中同步执行，事件通过线程安全的 queue.Queue 传回
chat 端点的异步生成器，由其转成 SSE 推给前端。
"""
import queue
import threading

# 事件类型（与原 SSEEvent 枚举对齐，前端事件协议不变）
FINAL = "final"
DELTA = "delta"
ERROR = "error"
META = "meta"

_tls = threading.local()


def set_event_queue(q: "queue.Queue"):
    """chat 服务运行查询图前注入事件队列"""
    _tls.queue = q


def get_event_queue() -> "queue.Queue | None":
    return getattr(_tls, "queue", None)


def push_sse_event(task_id, event_type: str, data: dict):
    """节点内推送事件；无队列时（脚本/调试）仅打日志"""
    q = get_event_queue()
    payload = {"type": event_type, **(data or {})}
    if q is not None:
        q.put(payload)
    else:
        from app.engine.tool.logger import logger
        logger.debug("sse(%s): %s", event_type, payload)


class SSEEvent:
    """兼容原 mcp SSEEvent 枚举的引用方式"""
    FINAL = FINAL
    DELTA = DELTA
    ERROR = ERROR
    META = META
