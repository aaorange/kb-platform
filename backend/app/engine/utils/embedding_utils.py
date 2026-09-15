# -*- coding: utf-8 -*-
"""编码工具 — 调用远程 GPU bge-m3 服务生成 dense+sparse 双向量

替代原本地 BGEM3EmbeddingFunction：backend 不再加载模型（省 2GB 内存），
GPU 服务地址由 EMBEDDING_API_URL 配置（AutoDL 6006 映射地址）。
"""
import threading

import httpx

from app.engine.config.config import embedding_config
from app.engine.tool.logger import logger

_client: httpx.Client | None = None
_lock = threading.Lock()

MAX_RETRIES = 3  # 网络抖动重试（AutoDL 公网链路）
TIMEOUT = 60.0   # 千切片批量编码的上限


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                if not embedding_config.api_url:
                    raise ValueError("EMBEDDING_API_URL 未配置：请在 .env 设置 GPU 编码服务地址")
                headers = {}
                if embedding_config.api_key:
                    headers["Authorization"] = f"Bearer {embedding_config.api_key}"
                _client = httpx.Client(timeout=TIMEOUT, headers=headers)
    return _client


def check_embedding_service() -> bool:
    """健康检查：GPU 服务可达且模型已加载（backend 启动 warmup / health 用）"""
    try:
        url = embedding_config.api_url.replace("/v1/embeddings", "/health")
        resp = _get_client().get(url, timeout=5)
        data = resp.json()
        return resp.status_code == 200 and data.get("ok") is True
    except Exception as e:  # noqa: BLE001
        logger.warning("编码服务健康检查失败：%s", e)
        return False


def generate_embeddings(texts: list[str]) -> dict:
    """文本 → {dense: [[float]], sparse: [{token_id: weight}]}

    与原 BGEM3EmbeddingFunction 返回结构完全一致，引擎节点无感切换。
    """
    if not texts:
        return {"dense": [], "sparse": []}

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _get_client().post(
                embedding_config.api_url,
                json={"texts": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "dense": data["dense"],
                "sparse": [{int(k): float(v) for k, v in sv.items()} for sv in data["sparse"]],
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("编码服务调用失败（第 %d/%d 次）：%s", attempt, MAX_RETRIES, e)
    raise RuntimeError(f"编码服务调用失败（已重试 {MAX_RETRIES} 次）：{last_err}")
