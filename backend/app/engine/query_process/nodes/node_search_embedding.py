# -*- coding: utf-8 -*-
"""向量检索节点 — 改写问题 → Milvus 混合检索（dense+sparse）

相比课程版：
1. 权限 expr 注入：state['perm_expr']（chat 服务按用户四维权限构造），
   与 item_name 过滤 AND 组合——权限过滤下沉到向量库
2. item_names 缺失不再报错（无实体问题走全库检索，配合权限过滤）
3. output_fields 补充 doc_id（引用溯源需要）
"""
from typing import Tuple

from app.engine.config.config import milvus_config
from app.engine.query_process.base import NodeBase
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger
from app.engine.utils.embedding_utils import generate_embeddings
from app.engine.utils.milvus_utils import create_hybrid_search_request, escape_milvus_string, hybrid_search


class NodeSearchEmbedding(NodeBase):
    """基于确认主体名 + 改写问题的 Milvus 混合检索"""

    name: str = "node_search_embedding"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        try:
            rewritten_query, item_names = self._step1_validate_param(state)
            res = self._step2_search_embedding(
                rewritten_query=rewritten_query,
                item_names=item_names,
                perm_expr=state.get("perm_expr"),
            )
            return {"embedding_chunks": res}
        except Exception as e:  # noqa: BLE001
            logger.exception("向量搜索失败：%s", e)
            return {"embedding_chunks": []}

    def _step1_validate_param(self, state) -> Tuple[str, list]:
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            raise ValueError("未指定用户问题")
        item_names = state.get("item_names") or []
        return rewritten_query, item_names

    def _step2_search_embedding(self, rewritten_query, item_names, perm_expr=None):
        # 1. 改写问题 → 双向量
        embeddings = generate_embeddings([rewritten_query])
        dense_vector = embeddings.get("dense")[0]
        sparse_vector = embeddings.get("sparse")[0]

        # 2. 组装过滤表达式：权限 expr AND 主体名过滤
        conds = []
        if perm_expr:
            conds.append(f"({perm_expr})")
        if item_names:
            escaped = ",".join(f'"{escape_milvus_string(name)}"' for name in item_names)
            conds.append(f"item_name in [{escaped}]")
        else:
            logger.info("未指定主体名，配合权限过滤进行检索")
        expr = " && ".join(conds) if conds else None

        # 3. 混合检索请求
        reqs = create_hybrid_search_request(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            expr=expr,
            limit=10,
        )

        # 4. 执行检索
        res = hybrid_search(
            collection_name=milvus_config.chunks_collection,
            reqs=reqs,
            ranker_weights=(0.8, 0.2),
            norm_score=True,
            output_fields=["chunk_id", "doc_id", "content", "item_name", "file_title"],
            limit=10,
        )
        return res[0] if res else []
