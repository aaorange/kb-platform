# -*- coding: utf-8 -*-
"""混合向量化节点 — 远程 GPU bge-m3 服务生成 dense+sparse 双向量

相比课程版：
1. batch_size 3 → 64：原值是为本地小显存设的，远程 GPU 服务吞吐完全不受限
2. 支持 state['progress_cb'] 进度回调（task_manager 上报进度条用）
3. 编码文本 = 主体名 + 切片内容（主体名前置增强语义，保留原设计）
"""
from typing import Dict, List

from app.engine.import_process.base import NodeBase
from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger
from app.engine.utils.embedding_utils import generate_embeddings

BATCH_SIZE = 64


class NodeBGEEmbedding(NodeBase):
    """切片 → 双向量绑定"""

    name = "node_bge_embedding"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        chunks = self._step1_validate_input(state)
        progress_cb = state.get("progress_cb")
        output_data = self._step2_generate_embeddings(chunks, progress_cb)
        return {"chunks": output_data}

    def _step1_validate_input(self, state) -> List[Dict]:
        chunks = state.get("chunks")
        if not chunks or not isinstance(chunks, list):
            raise ValueError("chunks不能为空")
        return chunks

    def _step2_generate_embeddings(self, chunks: List[Dict], progress_cb=None) -> List[Dict]:
        output_data = []
        total = len(chunks)

        for start in range(0, total, BATCH_SIZE):
            batch_chunks = chunks[start:start + BATCH_SIZE]
            texts = [f"{chunk.get('item_name', '')} \n{chunk['content']}" for chunk in batch_chunks]

            vectors = generate_embeddings(texts)
            dense_vectors = vectors["dense"]
            sparse_vectors = vectors["sparse"]

            for j, chunk in enumerate(batch_chunks):
                chunk["dense_vector"] = dense_vectors[j]
                chunk["sparse_vector"] = sparse_vectors[j]
                output_data.append(chunk)

            if progress_cb:
                progress_cb(min(start + BATCH_SIZE, total), total)

        logger.info("向量化完成：%d 条切片", total)
        return output_data
