# -*- coding: utf-8 -*-
"""Rerank 工具 — 双模式

gpu       ：调用自建 GPU reranker 服务（RERANKER_API_URL，AutoDL 6008 映射地址）
dashscope ：DashScope gte-rerank API 降级（RERANK_MODE=dashscope）

返回与文档列表同序的分数列表，两种模式行为一致。
"""
from typing import List

import httpx

from app.engine.config.config import reranker_config
from app.engine.tool.logger import logger

MAX_RETRIES = 2
TIMEOUT = 30.0


def _rerank_via_gpu(query: str, documents: List[str]) -> List[float]:
    headers = {}
    if reranker_config.api_key:
        headers["Authorization"] = f"Bearer {reranker_config.api_key}"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
                resp = client.post(reranker_config.api_url,
                                   json={"query": query, "documents": documents})
                resp.raise_for_status()
                return resp.json()["scores"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("GPU rerank 调用失败（第 %d/%d 次）：%s", attempt, MAX_RETRIES, e)
    raise RuntimeError(f"GPU rerank 调用失败：{last_err}")


def _rerank_via_dashscope(query: str, documents: List[str]) -> List[float]:
    import dashscope
    from http import HTTPStatus

    dashscope.api_key = reranker_config.api_key
    resp = dashscope.TextReRank.call(
        model=reranker_config.model,
        query=query,
        documents=documents,
        top_n=len(documents),
        return_documents=False,
        instruct=reranker_config.instruct,
    )
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"dashscope rerank 调用失败：status={resp.status_code}; msg={resp.message}")
    scores = [0.0] * len(documents)
    for item in resp.output.results:
        scores[item.index] = item.relevance_score
    return scores


def rerank_documents(query: str, documents: List[str]) -> List[float]:
    """按 RERANK_MODE 选择实现；GPU 失败自动降级 dashscope（配置了 key 时）"""
    if not documents:
        return []
    mode = reranker_config.mode
    try:
        if mode == "gpu":
            return _rerank_via_gpu(query, documents)
        return _rerank_via_dashscope(query, documents)
    except Exception:
        if mode == "gpu" and reranker_config.api_key and reranker_config.model:
            logger.warning("GPU rerank 失败，降级 dashscope")
            return _rerank_via_dashscope(query, documents)
        raise
