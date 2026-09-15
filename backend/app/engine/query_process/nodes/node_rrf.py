# -*- coding: utf-8 -*-
"""RRF 融合排序节点 — 多路召回结果加权融合

相比课程版的三处修复：
1. chunk_data.setdefault((chunk_id, doc)) → setdefault(chunk_id, doc)（原写法直接 TypeError）
2. 排序/截断移出循环（原版处理完第一路就 return，第二路结果全部丢弃）
3. web_search_docs 纳入第三路融合（原版只在 rerank 节点里预留了、实际从未合并）
"""
from app.engine.query_process.base import NodeBase
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger

RRF_K = 60  # 平滑常数


class NodeRrf(NodeBase):
    """Reciprocal Rank Fusion：向量 / HyDE / Web 三路加权融合"""

    name: str = "node_rrf"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        embedding_list = [d.get("entity") for d in (state.get("embedding_chunks") or [])
                          if isinstance(d, dict) and d.get("entity")]
        hyde_list = [d.get("entity") for d in (state.get("hyde_embedding_chunks") or [])
                     if isinstance(d, dict) and d.get("entity")]
        web_docs = [d for d in (state.get("web_search_docs") or []) if isinstance(d, dict)]

        rrf_inputs = [
            (embedding_list, 1.0),
            (hyde_list, 0.8),
            (web_docs, 0.5),
        ]

        rrf_chunks = [doc for doc, _ in self._rrf_merge(rrf_inputs, max_results=10)]
        return {"rrf_chunks": rrf_chunks}

    def _rrf_merge(self, rrf_inputs, k: int = RRF_K, max_results: int | None = None):
        """融合各路结果：score = Σ weight/(k+rank)，按累计得分降序"""
        chunk_scores: dict = {}
        chunk_data: dict = {}

        for docs, weight in rrf_inputs:
            for rank, doc in enumerate(docs, start=1):
                # 本地切片用 chunk_id，web 文档用 url 作去重键
                key = doc.get("chunk_id") or doc.get("url") or id(doc)
                chunk_scores[key] = chunk_scores.get(key, 0.0) + weight / (k + rank)
                chunk_data.setdefault(key, doc)

        unsorted_results = [(chunk_data[cid], score) for cid, score in chunk_scores.items()]
        unsorted_results.sort(key=lambda x: x[1], reverse=True)
        logger.info("RRF 融合完成：%d 路召回 → %d 条候选",
                    len(rrf_inputs), len(unsorted_results))
        return unsorted_results[:max_results] if max_results else unsorted_results
