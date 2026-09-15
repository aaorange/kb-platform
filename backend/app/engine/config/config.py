# -*- coding: utf-8 -*-
"""引擎配置 — 替代原 atguigu/config/config.py

统一从环境变量（kb-platform .env）读取，保持引擎节点期望的 dataclass 结构不变。
原项目的 mongo_history/sse/task 配置不移植（历史留 SQLite，任务用 kb-platform task_manager）。
"""
import os
from dataclasses import dataclass


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    vl_model: str
    vl_base_url: str
    vl_api_key: str
    llm_model: str
    item_model: str
    llm_temperature: float


_llm_base = os.getenv("LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
_llm_key = os.getenv("LLM_API_KEY", "")

lm_config = LLMConfig(
    base_url=_llm_base,
    api_key=_llm_key,
    vl_model=os.getenv("VL_MODEL", "qwen3-vl-flash"),
    vl_base_url=os.getenv("VL_API_BASE", _llm_base),
    vl_api_key=os.getenv("VL_API_KEY", _llm_key),
    llm_model=os.getenv("LLM_MODEL", "qwen-flash"),
    item_model=os.getenv("ITEM_MODEL", "qwen-flash"),
    llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
)


@dataclass
class EmbeddingConfig:
    """GPU 远程编码服务：bge-m3 hybrid（dense+sparse 双向量）"""
    api_url: str
    api_key: str
    bge_device: str
    bge_fp16: bool


embedding_config = EmbeddingConfig(
    api_url=os.getenv("EMBEDDING_API_URL", ""),
    api_key=os.getenv("EMBEDDING_API_KEY", ""),
    bge_device=os.getenv("BGE_DEVICE", "cuda:0"),
    bge_fp16=os.getenv("BGE_FP16", "true").lower() in ("1", "true", "yes"),
)


@dataclass
class RerankerConfig:
    """Rerank 服务模式：gpu（本地 GPU 服务）/ dashscope（云端 API 降级）"""
    mode: str
    api_url: str
    api_key: str
    model: str
    instruct: str


reranker_config = RerankerConfig(
    mode=os.getenv("RERANK_MODE", "gpu"),
    api_url=os.getenv("RERANKER_API_URL", ""),
    api_key=os.getenv("RERANKER_API_KEY", ""),
    model=os.getenv("TEXT_RERANK_MODEL", ""),
    instruct=os.getenv("TEXT_RERANK_INSTRUCT", ""),
)


@dataclass
class MilvusConfig:
    milvus_url: str
    chunks_collection: str
    item_name_collection: str


milvus_config = MilvusConfig(
    milvus_url=os.getenv("MILVUS_URI", ""),
    chunks_collection=os.getenv("MILVUS_COLLECTION", "knowledge_chunks_v2"),
    item_name_collection=os.getenv("MILVUS_ITEM_COLLECTION", "kb_item_names"),
)


@dataclass
class MinIOConfig:
    endpoint: str        # 容器内操作端点（如 minio:9000）
    public_url: str      # 浏览器读图的 URL 前缀（含协议与路径，如 http://host/kb-img）
    access_key: str
    secret_key: str
    bucket_name: str
    img_dir: str


minio_config = MinIOConfig(
    endpoint=os.getenv("MINIO_ENDPOINT", ""),
    public_url=os.getenv("MINIO_PUBLIC_URL", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", ""),
    secret_key=os.getenv("MINIO_SECRET_KEY", ""),
    bucket_name=os.getenv("MINIO_BUCKET_NAME", "knowledge-base"),
    img_dir=os.getenv("MINIO_IMG_DIR", "upload-images"),
)


@dataclass
class McpConfig:
    """联网搜索开关：企业知识库默认关闭"""
    enabled: bool
    mcp_base_url: str
    api_key: str


mcp_config = McpConfig(
    enabled=os.getenv("WEB_MCP_ENABLE", "0") in ("1", "true", "True"),
    mcp_base_url=os.getenv("MCP_DASHSCOPE_BASE_URL", ""),
    api_key=os.getenv("LLM_API_KEY", ""),
)


@dataclass
class MinerUConfig:
    """MinerU PDF 解析服务：纯文本 PDF 走本地 pypdf 降级，仅扫描件/图文混排走 MinerU"""
    api_token: str
    base_url: str


mineru_config = MinerUConfig(
    api_token=os.getenv("MINERU_API_TOKEN", ""),
    base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net/api/v4"),
)
