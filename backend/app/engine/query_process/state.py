# -*- coding: utf-8 -*-
from typing import TypedDict, List


class QueryGraphState(TypedDict):
    """查询图状态 — 在引擎原版基础上增加 kb-platform 权限字段"""
    session_id: str  # 会话ID（kb-platform ChatSession.id 的字符串形式）
    message_id: str  # 消息ID

    original_query: str  # 用户原始问题

    # 检索过程中的中间数据
    embedding_chunks: list       # 普通向量检索回来的切片
    hyde_embedding_chunks: list  # 假设性文档向量检索的切片
    web_search_docs: list        # 网络搜索回来的文档

    # 排序过程中的数据
    rrf_chunks: list       # RRF 融合排序后的切片
    reranked_docs: list    # 重排序后的最终 Top-K 文档

    # 生成过程中的数据
    prompt: str   # 组装好的 Prompt
    answer: str   # 最终生成的答案
    image_urls: list  # 答案引用的图片URL

    # 辅助信息
    item_names: List[str]     # 提取出的文档主体名称
    rewritten_query: str      # 改写后的问题
    history: list             # 历史对话记录
    is_stream: bool           # 是否流式输出

    # ===== kb-platform 扩展字段 =====
    task_id: str      # SSE 事件路由键（兼容引擎节点签名）
    perm_expr: str    # 四维权限的 Milvus 过滤表达式（chat 服务注入）
    blocked_doc_ids: list  # 权限拦截探测命中的文档 ID（检索为空时无权限过滤重检索）
