import json

from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker

from app.engine.config.config import milvus_config
from app.engine.tool.logger import logger

# 1. 定义一个全局单例对象
_milvus_client = None

# 2. 获取全局单例对象
def get_milvus_client():

    # 2.1 获取当前客户端对象
    global _milvus_client
    if _milvus_client is not None:
        return _milvus_client
    if not milvus_config.milvus_url:
        raise   ValueError('Milvus is empty')

    # 2.2 创建客户端对象
    _milvus_client = MilvusClient(uri=milvus_config.milvus_url)

    # 2.3 返回客户端
    return _milvus_client

def escape_milvus_string(value: str) -> str:
    """
    Milvus数据库过滤表达式中字符串的安全转义函数（防止解析失败）
    作用： 转义特殊字符（反斜杠、双引号），避免Milvus解析filter时报错
    参数 value: 需要转义的原始字符串
    返回 str: 转义后的安全字符串
    """
    # 转义反斜杠（\ → \\） 双引号（" → \"） 单引号（' → \'）
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    return value


def _json_array_like(field: str, value: str) -> str:
    """JSON 字符串数组元素匹配 → Milvus like 表达式

    dept_ids/role_ids/user_names 是 VARCHAR 存 JSON 数组（如 '["技术部"]'）。
    Milvus 2.4 的 contains 仅支持 ARRAY 类型字段，VARCHAR 需用 like；
    模式 '%"技术部"%' 带双引号整体匹配，避免"技术部"误匹配"信息技术部门"。
    值内 %/_/'/\\ 直接剔除（组织/角色名不应含通配符，防表达式注入）。
    """
    safe = value.replace("\\", "").replace("'", "").replace("%", "").replace("_", "")
    return f'{field} like \'%"{safe}"%\''


def build_permission_expr(user_dept: str | None, user_roles: list[str],
                          user_name: str | None) -> str:
    """四维权限 → Milvus 过滤表达式（kb-platform 权限引擎下沉向量库）

    dept_ids/role_ids/user_names 字段存 JSON 字符串数组（如 '["技术部"]'），
    like '%"技术部"%' 匹配带双引号的完整元素。
    任一维度命中即可访问（OR 逻辑，与 authz.check_permission 一致）。

    user 维度命中后仍会走 DB 二次复核（chat 服务侧 defense in depth）。
    """
    conds = ["scope_global == true"]
    if user_dept:
        conds.append(_json_array_like("dept_ids", user_dept))
    for role in user_roles or []:
        if role:
            conds.append(_json_array_like("role_ids", role))
    if user_name:
        conds.append(_json_array_like("user_names", user_name))
    return f"enabled == true && ({' || '.join(conds)})"


# ======================================================================
# kb-platform 平台侧运维操作（权限同步 / 删除 / 启停 / 健康检查）
# 由 knowledge 端点与 task_manager 调用，与导入节点共用同一 schema 约定
# ======================================================================
def permissions_to_scope_fields(permissions: list[dict] | None) -> dict:
    """[{"scope_type","scope_value"}] → {scope_global, dept_ids, role_ids, user_names}

    dept/role/user 维度存 JSON 字符串数组；global 存 bool。
    （原实现位于 node_item_name_recognition，收敛到此处供导入节点与
    权限同步复用，避免 schema 约定分散两处。）
    """
    if not permissions:
        permissions = []
    depts, roles, users, scope_global = [], [], [], False
    for p in permissions:
        st, sv = p.get("scope_type"), p.get("scope_value") or p.get("scope_name")
        if st == "global":
            scope_global = True
        elif st == "department" and sv:
            depts.append(sv)
        elif st == "role" and sv:
            roles.append(sv)
        elif st == "user" and sv:
            users.append(sv)
    return {
        "scope_global": scope_global,
        "dept_ids": json.dumps(depts, ensure_ascii=False),
        "role_ids": json.dumps(roles, ensure_ascii=False),
        "user_names": json.dumps(users, ensure_ascii=False),
    }


# upsert 时需显式取回的向量字段（query 的 "*" 不保证包含向量列）
_CHUNKS_ALL_FIELDS = [
    "chunk_id", "doc_id", "file_hash", "content", "title", "parent_title",
    "part", "file_title", "item_name", "scope_global", "dept_ids", "role_ids",
    "user_names", "enabled", "sparse_vector", "dense_vector",
]
_ITEM_ALL_FIELDS = [
    "pk", "doc_id", "file_title", "item_name", "scope_global", "dept_ids",
    "role_ids", "user_names", "enabled", "dense_vector", "sparse_vector",
]


def _upsert_doc_fields(doc_id: str, field_updates: dict, collections: list[tuple],
                       ) -> int:
    """按 doc_id 查回整行（含向量）→ 改字段 → upsert 写回

    Milvus 不支持局部更新，upsert 需携带完整行（含双向量）。
    collections: [(collection_name, output_fields, pk_field)]。
    返回两个集合合计更新的行数。
    """
    client = get_milvus_client()
    total = 0
    expr = f'doc_id == "{escape_milvus_string(doc_id)}"'
    for collection_name, output_fields, pk_field in collections:
        try:
            if not client.has_collection(collection_name):
                continue
            client.load_collection(collection_name)
            # 迭代器分页拉取 + 分批写回：大文档数万行含双向量，
            # 单次 query/upsert 均 500MB+，会超 gRPC 64MB 单消息上限
            it = client.query_iterator(collection_name=collection_name,
                                       batch_size=2000,
                                       filter=expr, output_fields=output_fields)
            try:
                while True:
                    try:
                        batch = it.next()
                    except StopIteration:
                        break
                    if not batch:
                        break
                    for row in batch:
                        if row.get(pk_field) is not None:
                            row.update(field_updates)
                    client.upsert(collection_name=collection_name, data=batch)
                    total += len(batch)
            finally:
                it.close()
        except Exception as e:  # noqa: BLE001
            logger.error("Milvus upsert 失败 collection=%s doc_id=%s：%s",
                         collection_name, doc_id, e)
            raise
    return total


def update_doc_permissions(doc_id: str, permissions: list[dict]) -> int:
    """权限变更同步：更新 chunks + item_name 两个集合的四维权限字段"""
    fields = permissions_to_scope_fields(permissions)
    return _upsert_doc_fields(doc_id, fields, [
        (milvus_config.chunks_collection, _CHUNKS_ALL_FIELDS, "chunk_id"),
        (milvus_config.item_name_collection, _ITEM_ALL_FIELDS, "pk"),
    ])


def set_doc_enabled(doc_id: str, enabled: bool) -> int:
    """启用/禁用同步：软控制，检索 expr 的 enabled == true 立即生效"""
    return _upsert_doc_fields(doc_id, {"enabled": bool(enabled)}, [
        (milvus_config.chunks_collection, _CHUNKS_ALL_FIELDS, "chunk_id"),
        (milvus_config.item_name_collection, _ITEM_ALL_FIELDS, "pk"),
    ])


def delete_doc_vectors(doc_id: str) -> int:
    """删除文档在 chunks + item_name 两个集合的全部向量（导入回滚/文档删除）"""
    client = get_milvus_client()
    expr = f'doc_id == "{escape_milvus_string(doc_id)}"'
    removed = 0
    for collection_name in (milvus_config.chunks_collection,
                            milvus_config.item_name_collection):
        try:
            if not client.has_collection(collection_name):
                continue
            client.delete(collection_name=collection_name, filter=expr)
            removed += 1
        except Exception as e:  # noqa: BLE001
            logger.error("Milvus 删除失败 collection=%s doc_id=%s：%s",
                         collection_name, doc_id, e)
            raise
    return removed


def check_milvus_ready() -> bool:
    """健康检查：Milvus 可连接（backend 启动 warmup / health 用）"""
    try:
        get_milvus_client().list_collections()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Milvus 健康检查失败：%s", e)
        return False

def create_hybrid_search_request(
        dense_vector, sparse_vector, dense_params=None, sparse_params=None, expr=None, limit=5
):
    """
    创建混合搜索请求

    分别创建稠密/稀疏向量的搜索请求，用于后续混合搜索融合
    :param dense_vector: 文本生成的稠密向量
    :param sparse_vector: 文本生成的稀疏向量
    :param dense_params: 稠密向量搜索参数，默认使用余弦相似度
    :param sparse_params: 稀疏向量搜索参数，默认使用内积相似度
    :param expr: 搜索过滤表达式，用于精准筛选数据
    :param limit: 单向量搜索返回结果数量，默认5
    :return: 搜索请求列表，包含[dense_req, sparse_req]
    """
    # 稠密向量默认搜索参数
    if dense_params is None:
        dense_params = {"metric_type": "COSINE"}
    # 稀疏向量默认搜索参数
    if sparse_params is None:
        sparse_params = {"metric_type": "IP"}

    # 构建稠密向量搜索请求类
    dense_req = AnnSearchRequest(
        data=[dense_vector],
        anns_field="dense_vector",
        param=dense_params,
        expr=expr,
        limit=limit
    )

    # 构建稀疏向量搜索请求，关联Milvus的sparse_vector字段
    sparse_req = AnnSearchRequest(
        data=[sparse_vector],
        anns_field="sparse_vector",
        param=sparse_params,
        expr=expr,
        limit=limit
    )

    return [dense_req, sparse_req]


def hybrid_search(
        collection_name, reqs, ranker_weights=(0.5, 0.5), norm_score=False,
        limit=5, output_fields=None, search_params=None
):
    """
    执行混合搜索

    :param collection_name: 集合名称
    :param reqs: 搜索请求列表，固定为[dense_req, sparse_req]
    :param ranker_weights: 加权融合权重，默认(0.5,0.5)，依次对应稠密/稀疏向量
    :param norm_score: 是否归一化评分后再融合，避免评分量级差异导致权重失效
    :param limit: 混合搜索最终返回结果数量，默认5
    :param output_fields: 需要返回的字段列表，默认返回item_name
    :param search_params: 搜索参数，如ef/topk等，默认None
    :return: 混合搜索结果列表，搜索失败返回None
    """
    try:
        # 初始化加权排名器：按权重融合稠密/稀疏向量的搜索结果
        # norm_score=True：先将两个向量评分归一化到0~1区间，再加权计算，避免一个得分特别大、另一个特别小导致权重失效。
        # 版本：V2.5
        rerank = WeightedRanker(ranker_weights[0], ranker_weights[1], norm_score=norm_score)

        # 执行混合搜索：融合稠密+稀疏向量结果，按权重重新排序
        client = get_milvus_client()
        res = client.hybrid_search(
            collection_name=collection_name,
            reqs=reqs,
            ranker=rerank,
            limit=limit,
            output_fields=output_fields,
            search_params=search_params
        )

        # 动态计算所有查询返回的结果总数
        logger.info(f"Milvus 混合搜索完成")
        return res
    except Exception as e:
        raise RuntimeError(f"执行Milvus混合搜索时发生错误: {e}")
if __name__ == '__main__':
    print(get_milvus_client())