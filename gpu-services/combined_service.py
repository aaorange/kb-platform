# -*- coding: utf-8 -*-
"""BGE 合并 GPU 服务 — bge-m3 双向量化 + bge-reranker-large 精排（单端口）

为什么合并：AutoDL 自定义服务只开放 6006 一个端口，embedding(6006) 与
reranker(6008) 分开部署时后者公网不可达。本服务在同一进程加载两个模型，
同时暴露 /v1/embeddings 与 /v1/rerank。

部署：AutoDL GPU 实例（见 start.sh），模型 /root/autodl-tmp/models/BAAI/
验证：curl http://127.0.0.1:6006/health
     curl http://127.0.0.1:6006/v1/embeddings -H "Content-Type: application/json" \
          -d '{"texts":["万用表如何测电压"]}'
     curl http://127.0.0.1:6006/v1/rerank -H "Content-Type: application/json" \
          -d '{"query":"怎么测交流电压","documents":["将旋钮置于 V AC 档","电阻测量需断电"]}'
"""
import logging
import os
import time
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bge_combined_service")

API_KEY = os.getenv("EMBEDDING_API_KEY", "")  # 与业务侧 .env 共享同一密钥

BGE_M3_PATH = os.getenv("BGE_M3_PATH", "/root/autodl-tmp/models/BAAI/bge-m3")
BGE_RERANKER_PATH = os.getenv("BGE_RERANKER_LARGE", "/root/autodl-tmp/models/BAAI/bge-reranker-large")
EMBED_DEVICE = os.getenv("BGE_DEVICE", "cuda:0")
RERANK_DEVICE = os.getenv("BGE_RERANKER_DEVICE", "cuda:0")
EMBED_FP16 = os.getenv("BGE_FP16", "true").lower() in ("1", "true", "yes")
RERANK_FP16 = os.getenv("BGE_RERANKER_FP16", "true").lower() in ("1", "true", "yes")
INNER_BATCH = int(os.getenv("BGE_INNER_BATCH", "64"))

_ef = None        # BGEM3EmbeddingFunction 单例
_reranker = None  # FlagReranker 单例


def get_embedder():
    global _ef
    if _ef is not None:
        return _ef
    from pymilvus.model.hybrid import BGEM3EmbeddingFunction

    logger.info("加载 BGE-M3：%s device=%s fp16=%s", BGE_M3_PATH, EMBED_DEVICE, EMBED_FP16)
    _ef = BGEM3EmbeddingFunction(model_name=BGE_M3_PATH, device=EMBED_DEVICE, use_fp16=EMBED_FP16)
    logger.info("BGE-M3 加载完成")
    return _ef


def get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    from FlagEmbedding import FlagReranker

    logger.info("加载 reranker：%s device=%s fp16=%s", BGE_RERANKER_PATH, RERANK_DEVICE, RERANK_FP16)
    _reranker = FlagReranker(model_name_or_path=BGE_RERANKER_PATH, device=RERANK_DEVICE,
                             use_fp16=RERANK_FP16)
    logger.info("reranker 加载完成")
    return _reranker


class EmbeddingsRequest(BaseModel):
    texts: List[str] = Field(..., description="待编码文本列表")


class EmbeddingsResponse(BaseModel):
    """sparse 的 key 是 token_id（int）；JSON 序列化自动转字符串键，
    业务侧 embedding_utils 按字符串键解析后转回 int"""
    dense: List[List[float]]
    sparse: List[Dict[int, float]]


class RerankRequest(BaseModel):
    query: str = Field(..., description="用户问题（改写后）")
    documents: List[str] = Field(..., description="候选文档内容列表")


class RerankResponse(BaseModel):
    scores: List[float]


app = FastAPI(title="BGE Combined GPU Service (embedding + rerank)")


def check_auth(authorization: Optional[str]):
    if not API_KEY:
        return
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
def health():
    """业务侧 warmup 探测：ok=true 即服务可达（模型懒加载，loaded 表示是否已加载）"""
    return {
        "ok": True,
        "models": {
            "bge-m3": {"loaded": _ef is not None, "device": EMBED_DEVICE, "fp16": EMBED_FP16},
            "bge-reranker-large": {"loaded": _reranker is not None, "device": RERANK_DEVICE,
                                   "fp16": RERANK_FP16},
        },
    }


@app.post("/v1/embeddings", response_model=EmbeddingsResponse)
def embeddings(req: EmbeddingsRequest, authorization: Optional[str] = Header(None)):
    """生成 dense + sparse 双向量（Milvus 混合检索依赖两者，缺一不可）"""
    check_auth(authorization)
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts 不能为空")
    ef = get_embedder()
    t0 = time.time()
    try:
        dense_all: List[List[float]] = []
        sparse_all: List[Dict[str, float]] = []
        for i in range(0, len(req.texts), INNER_BATCH):
            batch = req.texts[i:i + INNER_BATCH]
            result = ef.encode_documents(batch)
            dense_all.extend(v.tolist() for v in result["dense"])
            csr = result["sparse"]
            for row in range(len(batch)):
                lo, hi = csr.indptr[row], csr.indptr[row + 1]
                sparse_all.append(dict(zip(csr.indices[lo:hi].tolist(), csr.data[lo:hi].tolist())))
        logger.info("编码 %d 条耗时 %.2fs", len(req.texts), time.time() - t0)
        return EmbeddingsResponse(dense=dense_all, sparse=sparse_all)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("编码失败")
        raise HTTPException(status_code=500, detail=f"embedding failed: {exc}") from exc


@app.post("/v1/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest, authorization: Optional[str] = Header(None)):
    """对 (query, document) 成对打分，返回与 documents 同序的分数列表"""
    check_auth(authorization)
    if not req.documents:
        raise HTTPException(status_code=400, detail="documents 不能为空")
    model = get_reranker()
    pairs = [(req.query, doc) for doc in req.documents]
    t0 = time.time()
    try:
        scores = model.compute_score(sentence_pairs=pairs)
        if isinstance(scores, (int, float)):
            scores = [float(scores)]
        elif hasattr(scores, "tolist"):
            scores = scores.tolist()
        logger.info("rerank %d 对耗时 %.2fs", len(pairs), time.time() - t0)
        return RerankResponse(scores=[float(s) for s in scores])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("rerank 失败")
        raise HTTPException(status_code=500, detail=f"rerank failed: {exc}") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6006, log_level="info")
