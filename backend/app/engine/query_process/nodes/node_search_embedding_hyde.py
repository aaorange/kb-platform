# -*- coding: utf-8 -*-
"""HyDE 检索节点 — 假设性文档生成 + 向量检索

相比课程版：
1. 删除 IDE 误导入（torch.utils.jit / node_rerank 循环引用）
2. item_names 缺失不再报错（与 node_search_embedding 行为对齐）
3. 权限 expr 注入（与主检索路径同等约束）
"""
from app.engine.config.config import milvus_config
from app.engine.query_process.base import NodeBase
from app.engine.query_process.prompt import HYDE_PROMPT
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger
from app.engine.utils.embedding_utils import generate_embeddings
from app.engine.utils.llm_utils import get_llm_client
from app.engine.utils.milvus_utils import create_hybrid_search_request, escape_milvus_string, hybrid_search


class NodeSearchEmbeddingHyde(NodeBase):
    """HyDE：LLM 生成假设性答案 → 拼接问题编码 → 混合检索（提高召回率）"""

    name: str = "node_search_embedding_hyde"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        try:
            rewritten_query, item_names = self._step1_validate_param(state)
            hyde_doc = self._step2_create_hyde_doc(rewritten_query)
            res = self._step3_search_embedding_hyde(
                rewritten_query=rewritten_query,
                hyde_doc=hyde_doc,
                item_names=item_names,
                perm_expr=state.get("perm_expr"),
            )
            return {"hyde_embedding_chunks": res}
        except Exception as e:  # noqa: BLE001
            logger.exception("HyDE 检索失败：%s", e)
            return {"hyde_embedding_chunks": []}

    def _step1_validate_param(self, state):
        query = state.get("rewritten_query")
        if not query:
            raise ValueError("未指定用户问题")
        item_names = state.get("item_names") or []
        return query, item_names

    def _step2_create_hyde_doc(self, rewritten_query: str) -> str:
        try:
            llm = get_llm_client()
            hyde_prompt = HYDE_PROMPT.format(rewritten_query=rewritten_query)
            response = llm.invoke(hyde_prompt)
            return response.content
        except Exception as e:  # noqa: BLE001
            logger.exception("假设性文档生成失败：%s", e)
            raise

    def _step3_search_embedding_hyde(self, rewritten_query, hyde_doc, item_names, perm_expr=None):
        # 1. 问题 + 假设文档 拼接编码
        embeddings = generate_embeddings([rewritten_query + "\n" + hyde_doc])
        dense_vector = embeddings.get("dense")[0]
        sparse_vector = embeddings.get("sparse")[0]

        # 2. 过滤表达式：权限 AND 主体名
        conds = []
        if perm_expr:
            conds.append(f"({perm_expr})")
        if item_names:
            escaped = ",".join(f'"{escape_milvus_string(name)}"' for name in item_names)
            conds.append(f"item_name in [{escaped}]")
        expr = " && ".join(conds) if conds else None

        # 3. 混合检索
        reqs = create_hybrid_search_request(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            expr=expr,
            limit=10,
        )
        res = hybrid_search(
            collection_name=milvus_config.chunks_collection,
            reqs=reqs,
            ranker_weights=(0.8, 0.2),
            norm_score=True,
            output_fields=["chunk_id", "doc_id", "content", "item_name", "file_title"],
            limit=10,
        )
        return res[0] if res else []
