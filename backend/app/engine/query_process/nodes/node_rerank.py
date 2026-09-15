# -*- coding: utf-8 -*-
"""Rerank 精排节点 — Cross-Encoder 打分 + 断崖截断

修复课程版四处硬伤：
1. _step1 引用了不存在的 rrf_doc（应为循环变量）
2. {'score:score,**doc'} 是字符串字面量（应为 {**doc, 'score': score}）
3. SCORE_MIN 声明无值（类属性访问直接崩溃）
4. _step3 中 ranked_docs/reranked_docs 变量名混用
"""
from typing import Any, Dict, List

from app.engine.query_process.base import NodeBase
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger
from app.engine.utils.reranker_http_utils import rerank_documents


class NodeRerank(NodeBase):
    """RRF 结果精排：rerank 打分 → 降序 → 断崖截断"""

    name: str = "node_rerank"

    # 动态 topK 硬上限 / 下限
    RERANK_MAX_TOPK: int = 10
    RERANK_MIN_TOPK: int = 2
    # 断崖阈值：相对差 / 绝对差
    RERANK_GAP_RATIO: float = 0.25
    RERANK_GAP_ABS: float = 0.10
    # 最低入选分数（低于此值视为全部不相关）
    SCORE_MIN: float = 0.30

    def process(self, state: QueryGraphState) -> QueryGraphState:
        merged_docs = self._step1_merge_multi_source_docs(state)
        if not merged_docs:
            return {"reranked_docs": []}

        reranked_docs = self._step2_rerank_merged_docs(state, merged_docs)
        if not reranked_docs:
            return {"reranked_docs": []}

        cutoff_docs = self._step3_cliff_cutoff(reranked_docs)
        logger.info("Rerank 完成：%d 条候选 → %d 条入选", len(reranked_docs), len(cutoff_docs))
        return {"reranked_docs": cutoff_docs}

    def _step1_merge_multi_source_docs(self, state) -> List[Dict[str, Any]]:
        """RRF 切片 + web 文档统一为 rerank 输入结构"""
        merged: List[Dict[str, Any]] = []
        for doc in state.get("rrf_chunks") or []:
            if not isinstance(doc, dict):
                continue
            merged.append({
                "title": doc.get("item_name") or doc.get("title") or "",
                "content": doc.get("content"),
                "chunk_id": doc.get("chunk_id"),
                "doc_id": doc.get("doc_id"),
                "file_title": doc.get("file_title"),
                "url": doc.get("url"),
                "source": doc.get("source") or "local",
            })
        return [d for d in merged if d["content"]]

    def _step2_rerank_merged_docs(self, state, merged_docs) -> List[Dict[str, Any]]:
        user_query = state.get("rewritten_query") or state.get("original_query")
        contents = [doc["content"] for doc in merged_docs]
        try:
            rerank_scores = rerank_documents(user_query, contents)
        except Exception as e:  # noqa: BLE001
            logger.exception("rerank 调用失败：%s（降级使用 RRF 顺序）", e)
            return [{**doc, "score": 0.5} for doc in merged_docs]

        reranked = [{**doc, "score": float(score)} for doc, score in zip(merged_docs, rerank_scores)]
        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def _step3_cliff_cutoff(self, reranked_docs) -> List[Dict[str, Any]]:
        """断崖截断：分数骤降处截断，保留 [MIN, MAX] 区间"""
        if not reranked_docs:
            return []
        if reranked_docs[0]["score"] < self.SCORE_MIN:
            logger.info("最高分 %.3f 低于入选线 %.2f，判定无相关文档",
                        reranked_docs[0]["score"], self.SCORE_MIN)
            return []

        upper_bound = min(self.RERANK_MAX_TOPK, len(reranked_docs))
        lower_bound = min(self.RERANK_MIN_TOPK, upper_bound)
        cutoff_pos = upper_bound

        for index in range(lower_bound - 1, upper_bound - 1):
            current_score = reranked_docs[index]["score"]
            next_score = reranked_docs[index + 1]["score"]
            abs_gap = current_score - next_score
            rel_gap = abs_gap / (abs(current_score) + 1e-6)

            if abs_gap >= self.RERANK_GAP_ABS or rel_gap >= self.RERANK_GAP_RATIO:
                cutoff_pos = index + 1
                logger.info("断崖位置：%d（abs_gap=%.3f rel_gap=%.3f）", cutoff_pos, abs_gap, rel_gap)
                break

        return reranked_docs[:cutoff_pos]
