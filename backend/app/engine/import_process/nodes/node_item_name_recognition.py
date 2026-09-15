# -*- coding: utf-8 -*-
"""主体识别节点 — 文档实体识别与标签提取（商品名泛化为文档主体）

相比课程版：
1. SystemMessage 从"商品识别专家"泛化为"文档主体识别"
2. item_name 集合增加权限四维字段（doc_id/scope_global/dept_ids/role_ids/enabled），
   实体确认阶段同样受权限过滤——防止通过反问选项泄露无权文档的实体名
3. 幂等清理按 file_title 改为 file_title + doc_id 双重保险
"""
from typing import Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pymilvus import DataType

from app.engine.config.config import lm_config, milvus_config
from app.engine.import_process.base import NodeBase
from app.engine.import_process.prompt import NAME_RECOGNITION
from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger
from app.engine.utils.embedding_utils import generate_embeddings
from app.engine.utils.llm_utils import get_llm_client
from app.engine.utils.milvus_utils import (
    escape_milvus_string, get_milvus_client, permissions_to_scope_fields,
)


class NodeItemNameRecognition(NodeBase):
    """主体识别：LLM 识别文档主体名 → 回填切片 → 生成双向量 → 存 item_name 集合"""

    name = "node_item_name_recognition"

    DEFAULT_ITEM_NAME_CHUNK_K = 5  # 取前5个切片作为识别上下文
    MAX_CHARS = 2500               # 总上下文字符限制

    def process(self, state: ImportGraphState):
        file_title, chunks = self._step1_get_inputs(state)
        context = self._step2_build_context(chunks)
        item_name = self._step3_call_llm(file_title, context)
        chunks = self._step4_update_chunks(chunks, item_name)
        dense_vector, sparse_vector = self._step5_generate_vectors(item_name)
        self._step6_save_to_milvus(state, file_title, item_name, dense_vector, sparse_vector)

        logger.info("识别文档主体完成：%s", item_name)
        return {"chunks": chunks, "item_name": item_name}

    def _step1_get_inputs(self, state) -> Tuple[str, List[Dict]]:
        file_title = state.get("file_title")
        if not file_title:
            raise ValueError("标题不能为空")
        chunks = state.get("chunks")
        if not chunks or not isinstance(chunks, list):
            raise ValueError("文本片段不能为空")
        return file_title, chunks

    def _step2_build_context(self, chunks: List[Dict]) -> str:
        parts: List[str] = []
        total_chars = 0
        for idx, chunk in enumerate(chunks[:self.DEFAULT_ITEM_NAME_CHUNK_K], start=1):
            piece = f"切片{idx}\n标题：{chunk.get('title')}\n内容：{chunk.get('content')}"
            parts.append(piece)
            total_chars += len(piece)
            if total_chars > self.MAX_CHARS:
                logger.warning("识别上下文超限，已截断")
                break
        return "\n\n".join(parts).strip()[:self.MAX_CHARS]

    def _step3_call_llm(self, file_title: str, context: str) -> str:
        try:
            prompt = NAME_RECOGNITION.format(file_title=file_title, context=context)
            llm = get_llm_client(model=lm_config.item_model)
            messages = [
                SystemMessage(content="你是文档主体识别专家，只输出识别到的主体名称字符串"),
                HumanMessage(content=prompt),
            ]
            response = llm.invoke(messages)
            item_name = response.content.strip().replace("\n", "").replace("\r", "").replace("\t", "").replace(" ", "")
            return item_name or file_title
        except Exception as e:  # noqa: BLE001
            logger.exception("主体识别 LLM 调用失败：%s", e)
            return file_title

    def _step4_update_chunks(self, chunks: List[Dict], item_name: str) -> List[Dict]:
        for chunk in chunks:
            chunk["item_name"] = item_name
        return chunks

    def _step5_generate_vectors(self, item_name: str):
        vectors = generate_embeddings([item_name])
        return vectors["dense"][0], vectors["sparse"][0]

    def _step6_save_to_milvus(self, state: ImportGraphState, file_title: str, item_name: str,
                              dense_vector, sparse_vector):
        try:
            milvus_client = get_milvus_client()
            collection_name = milvus_config.item_name_collection

            if not milvus_client.has_collection(collection_name):
                self._create_item_name_collection(collection_name, milvus_client)

            # 幂等：删除同 doc_id 旧记录（doc_id 缺失时退化为 file_title）
            doc_id = state.get("doc_id")
            if doc_id:
                filter_expr = f'doc_id == "{escape_milvus_string(doc_id)}"'
            else:
                filter_expr = f'file_title == "{escape_milvus_string(file_title)}"'
            milvus_client.delete(collection_name=collection_name, filter=filter_expr)

            data = {
                "doc_id": doc_id or file_title,
                "file_title": file_title,
                "item_name": item_name,
                "dense_vector": dense_vector,
                "sparse_vector": sparse_vector,
                "enabled": True,
                **permissions_to_scope_fields(state.get("permissions")),
            }
            milvus_client.insert(collection_name=collection_name, data=[data])
        except Exception as e:  # noqa: BLE001
            logger.error("主体名持久化失败：%s（不影响切片主流程）", e)

    def _create_item_name_collection(self, collection_name, milvus_client):
        schema = milvus_client.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field(field_name="pk", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="scope_global", datatype=DataType.BOOL)
        schema.add_field(field_name="dept_ids", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="role_ids", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="user_names", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="enabled", datatype=DataType.BOOL)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = milvus_client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector", index_name="dense_vector_index",
            index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 128},
        )
        index_params.add_index(
            field_name="sparse_vector", index_name="sparse_vector_index",
            index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "normalize": True, "quantization": "none"},
        )
        milvus_client.create_collection(collection_name=collection_name, schema=schema, index_params=index_params)
        logger.info("已创建 item_name 集合：%s", collection_name)
