# -*- coding: utf-8 -*-
"""AI 鉴权问答引擎 v2 — LangGraph 查询图版

链路：
1. FAQ 缓存前置匹配（Redis 精确匹配 + 来源文档权限复核）
2. 四维权限构造 Milvus 过滤表达式（权限过滤下沉向量库）
3. 工作线程跑查询图：实体提取/对齐 → 向量+HyDE 多路检索 → RRF
   → Rerank 断崖截断 → LLM 流式生成（SSE 事件进线程安全队列）
4. 异步侧消费队列，翻译为平台事件协议 chunk/meta/done
5. 问答日志落库由 chat 端点的 persist_log 统一完成

相比 v1：本地模型/npz 检索与内存权限过滤全部移除，检索质量由
Milvus 混合检索(dense+sparse)+HyDE+RRF+Rerank 承担；澄清链路
（无关问题先答后澄清）随 v1 检索器一并移除。
"""
import asyncio
import hashlib
import json
import logging
import queue
import time
import uuid
from typing import AsyncGenerator

import redis.asyncio as aioredis

logger = logging.getLogger("kb.chat")

# 队列轮询间隔（秒）：事件推送延迟上限
_QUEUE_POLL_INTERVAL = 0.05


def question_hash(q: str) -> str:
    return hashlib.md5(q.strip().lower().encode()).hexdigest()


async def check_faq_cache(question: str, redis_client, user_dept, user_roles, user_name,
                          doc_perms: dict[str, list[dict]] | None = None) -> dict | None:
    """FAQ 缓存前置匹配 — 带权限复核

    缓存值含 source_doc_ids 时：须对全部来源文档有权才命中，否则降级走完整检索链路
    """
    qh = question_hash(question)
    cached = await redis_client.get(f"faq:{qh}")
    if not cached:
        return None
    faq = json.loads(cached)

    source_docs = faq.get("source_doc_ids") or []
    if source_docs and doc_perms is not None:
        from app.services.authz import check_permission
        for doc_id in source_docs:
            perms = doc_perms.get(doc_id)
            if not perms or not check_permission(user_dept, user_roles, user_name, perms):
                return None  # 无权命中该 FAQ 的任一来源文档 → 放弃缓存
    return faq


def _run_query_graph(question: str, history: list[dict], perm_expr: str,
                     task_id: str, event_q: "queue.Queue") -> dict:
    """工作线程：注入历史/事件队列 → 同步执行查询图，返回最终 state

    set_recent_history / set_event_queue 均为 thread-local，必须与
    graph.invoke 同线程调用，因此整个函数跑在 to_thread 里。
    """
    from app.engine.query_process.main_graph import KBQueryWorkflow
    from app.engine.utils.mongo_history_utils import set_recent_history
    from app.engine.utils.sse_utils import set_event_queue

    set_event_queue(event_q)
    set_recent_history(history)

    workflow = KBQueryWorkflow()
    return workflow.run({
        "session_id": "kb",
        "message_id": "",
        "task_id": task_id,
        "original_query": question,
        "perm_expr": perm_expr,
        "history": history,
        "is_stream": True,
    })


async def stream_chat(
    question: str,
    user_dept: str | None,
    user_roles: list[str],
    user_name: str,
    redis_client: aioredis.Redis | None = None,
    history: list[dict] | None = None,
    doc_perms: dict[str, list[dict]] | None = None,
) -> AsyncGenerator[dict, None]:
    """完整的 AI 鉴权问答流式生成（查询图引擎版）

    yield 事件类型：
      {"type": "faq_hit", "answer": "...", "cited": []}
      {"type": "chunk", "content": "delta"}  — 流式文本片段
      {"type": "meta", "cited_chunks": [...], "blocked_count": 0, "faq_hit": bool,
       "image_urls": [...], "full_answer": str, "response_ms": int}
      {"type": "done"}
    """
    start = time.time()

    # 1. FAQ 缓存前置（带权限复核）
    if redis_client:
        faq = await check_faq_cache(question, redis_client, user_dept, user_roles,
                                    user_name, doc_perms)
        if faq:
            yield {"type": "faq_hit", "answer": faq["answer"], "cited": []}
            yield {"type": "meta", "cited_chunks": [], "blocked_count": 0,
                   "faq_hit": True, "faq_id": faq.get("faq_id"),
                   "response_ms": int((time.time() - start) * 1000)}
            yield {"type": "done"}
            return

    # 2. 四维权限 → Milvus 过滤表达式
    from app.engine.utils.milvus_utils import build_permission_expr
    perm_expr = build_permission_expr(user_dept, user_roles, user_name)

    # 3. 工作线程跑查询图，事件队列桥接
    event_q: queue.Queue = queue.Queue()
    task_id = uuid.uuid4().hex[:12]
    graph_task = asyncio.create_task(
        asyncio.to_thread(_run_query_graph, question, history or [],
                          perm_expr, task_id, event_q)
    )

    full_answer = ""
    image_urls: list = []
    got_delta = False
    while not graph_task.done() or not event_q.empty():
        try:
            ev = event_q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(_QUEUE_POLL_INTERVAL)
            continue

        etype = ev.get("type")
        if etype == "delta":
            got_delta = True
            delta = ev.get("delta", "")
            if delta:
                full_answer += delta
                yield {"type": "chunk", "content": delta}
        elif etype == "final":
            # 正常链路 answer 已通过 delta 流出；反问链路无 delta，整句补发
            full_answer = ev.get("answer") or full_answer
            image_urls = ev.get("image_urls") or []
            if ev.get("answer") and not got_delta:
                yield {"type": "chunk", "content": ev["answer"]}
        elif etype == "error":
            logger.error("查询图推送错误事件：%s", ev.get("error"))

    # 引擎异常（Milvus/GPU 服务不可达等）：兜底提示而非 500
    try:
        final_state = await graph_task
    except Exception as e:  # noqa: BLE001
        logger.exception("查询图执行失败：%s", e)
        if not full_answer:
            full_answer = "抱歉，知识检索服务暂时不可用，请稍后重试。"
            yield {"type": "chunk", "content": full_answer}
        yield {"type": "meta", "cited_chunks": [], "blocked_count": 0,
               "faq_hit": False, "full_answer": full_answer,
               "response_ms": int((time.time() - start) * 1000)}
        yield {"type": "done"}
        return

    # 4. 元数据：引用溯源（rerank 幸存切片）+ 权限拦截文档
    reranked = (final_state or {}).get("reranked_docs") or []
    blocked_doc_ids = (final_state or {}).get("blocked_doc_ids") or []
    cited = [
        {
            "chunk_id": d.get("chunk_id"),
            "doc_id": d.get("doc_id"),
            "heading": d.get("title") or d.get("item_name") or "",
            "content_preview": (d.get("content") or "")[:100],
        }
        for d in reranked if isinstance(d, dict)
    ]
    # 反问/权限拦截路径（有 answer 无 delta）不算知识缺口
    is_clarify = bool((final_state or {}).get("answer")) and not got_delta
    yield {
        "type": "meta",
        "cited_chunks": cited,
        "blocked_count": len(blocked_doc_ids),
        "blocked_doc_ids": blocked_doc_ids,  # persist_log 落库 → Dashboard 拦截分析
        "faq_hit": False,
        "gap": not reranked and not is_clarify,  # 检索无相关切片 → 端点记入知识缺口
        "image_urls": image_urls,
        "full_answer": full_answer,
        "token_count": len(full_answer) // 2,
        "response_ms": int((time.time() - start) * 1000),
    }
    yield {"type": "done"}
