# -*- coding: utf-8 -*-
"""导入 Milvus 节点 — 切片持久化（含四维权限字段）

相比课程版的三处关键改造：
1. Schema 增加 kb-platform 权限字段：doc_id / scope_global / dept_ids / role_ids /
   user_names / enabled / file_hash——权限过滤下沉到向量库 expr，检索时不再内存过滤
2. 幂等清理从 file_title（同标题不同版本会误删）改为 doc_id + file_hash
3. chunk 主键改用确定性 VARCHAR（doc_id-序号）：权限更新时可 upsert 精确定位
"""
from typing import Any, Dict, List

from pymilvus import DataType

from app.engine.config.config import milvus_config
from app.engine.import_process.base import NodeBase
from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger
from app.engine.utils.milvus_utils import (
    escape_milvus_string, get_milvus_client, permissions_to_scope_fields,
)


class NodeImportMilvus(NodeBase):
    """切片数据入库（向量 + 标量权限字段）"""

    name = "node_import_milvus"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        chunks, vector_dimension = self._step1_check_input(state)
        client = self._step2_prepare_collection(vector_dimension)
        self._step3_clean_old_data(client, state)
        updated_chunks = self._step4_insert_data(client, state, chunks)
        return {"chunks": updated_chunks}

    def _step1_check_input(self, state) -> tuple[List[Dict[str, Any]], int]:
        chunks = state.get("chunks")
        if not chunks or not isinstance(chunks, list):
            raise ValueError("chunks不能为空")
        first = chunks[0]
        if "dense_vector" not in first or "sparse_vector" not in first:
            raise ValueError("切片缺失向量字段（请确认上游向量化节点已执行）")
        return chunks, len(first["dense_vector"])

    def _step2_prepare_collection(self, vector_dimension: int):
        milvus_client = get_milvus_client()
        collection_name = milvus_config.chunks_collection
        if not milvus_client.has_collection(collection_name):
            self._create_chunks_collection(collection_name, milvus_client, vector_dimension)
            logger.info("已创建 chunks 集合：%s", collection_name)
        return milvus_client

    def _create_chunks_collection(self, collection_name, milvus_client, vector_dimension: int):
        schema = milvus_client.create_schema(auto_id=False, enable_dynamic_field=False)
        # 确定性主键：doc_id + 序号（权限 upsert / 精确删除的定位键）
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64,
                         is_primary=True)
        # 业务字段
        schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="file_hash", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="part", datatype=DataType.INT8)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        # 四维权限字段（global/dept/role/user + 启用开关）
        schema.add_field(field_name="scope_global", datatype=DataType.BOOL)
        schema.add_field(field_name="dept_ids", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="role_ids", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="user_names", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="enabled", datatype=DataType.BOOL)
        # 双向量
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dimension)

        index_params = milvus_client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector", index_name="dense_vector_index",
            index_type="AUTOINDEX", metric_type="COSINE",
        )
        index_params.add_index(
            field_name="sparse_vector", index_name="sparse_inverted_index",
            index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "normalize": True, "quantization": "none"},
        )
        milvus_client.create_collection(collection_name=collection_name, schema=schema,
                                        index_params=index_params)

    def _step3_clean_old_data(self, client, state):
        """幂等清理：按 doc_id（全新 doc_id 无残留，重试同 doc_id 才会命中）

        注意：不能联合 file_hash 清理——同内容并发上传时第二个任务会
        误删第一个任务刚入库的向量（DB 去重复核在前置端点与收尾双重兜底）。
        """
        doc_id = state.get("doc_id")
        if not doc_id:
            logger.warning("doc_id 缺失，跳过幂等清理（可能产生重复数据）")
            return
        try:
            client.delete(collection_name=milvus_config.chunks_collection,
                          filter=f'doc_id == "{escape_milvus_string(doc_id)}"')
        except Exception as e:  # noqa: BLE001
            logger.error("Milvus 幂等清理失败：%s", e)
            raise

    def _step4_insert_data(self, client, state, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        doc_id = state.get("doc_id") or ""
        file_hash = state.get("file_hash") or ""
        scope_fields = permissions_to_scope_fields(state.get("permissions"))

        data_to_insert = []
        for idx, item in enumerate(chunks):
            data_to_insert.append({
                "chunk_id": f"{doc_id}-{idx:04d}" if doc_id else str(item.get("chunk_id", idx)),
                "doc_id": doc_id,
                "file_hash": file_hash,
                "content": item["content"],
                "title": item.get("title") or "无标题",
                "parent_title": item.get("parent_title") or item.get("title") or "无标题",
                "part": item.get("part", 0),
                "file_title": item.get("file_title", ""),
                "item_name": item.get("item_name", ""),
                "enabled": True,
                **scope_fields,
                "sparse_vector": item["sparse_vector"],
                "dense_vector": item["dense_vector"],
            })
            item["chunk_id"] = data_to_insert[-1]["chunk_id"]

        # 分批插入：单条 chunk 约 6-7KB（dense 1024 维 + sparse + content），
        # 数万条全量一次 insert 会超 gRPC 单消息 64MB 上限（60MB 文档实测 515MB 被拒）
        INSERT_BATCH = 2000
        total_inserted = 0
        for i in range(0, len(data_to_insert), INSERT_BATCH):
            batch = data_to_insert[i:i + INSERT_BATCH]
            insert_result = client.insert(collection_name=milvus_config.chunks_collection,
                                          data=batch)
            total_inserted += insert_result.get("insert_count", len(batch))
        logger.info("Milvus 入库完成：%d 条（insert_count=%s）",
                    len(data_to_insert), total_inserted)
        return chunks
