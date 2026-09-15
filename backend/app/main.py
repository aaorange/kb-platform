# -*- coding: utf-8 -*-
"""FastAPI 主应用"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import ensure_schema

model_ready = False
embedding_ready = False
milvus_ready = False

_DEFAULT_SECRET = "dev-secret-key-change-in-production"


def startup_sanity_check():
    """生产启动自检：危险/缺失配置直接拒绝启动，避免带病上线

    v2 引擎依赖 Milvus 与 GPU 编码服务，缺配置时所有问答/导入必然失败，
    不如启动即拦截。注：本项目生产环境合法使用 SQLite（data 卷挂载）。
    """
    if settings.DEBUG:
        print("[Config] DEBUG=True：使用 SQLite 开发库，请勿用于生产")
        return
    problems = []
    if settings.SECRET_KEY == _DEFAULT_SECRET:
        problems.append("SECRET_KEY 仍为默认值，任何人可伪造 JWT（请在 .env 中设置）")
    if not settings.MILVUS_URI:
        problems.append("MILVUS_URI 未配置：v2 引擎依赖 Milvus 混合检索")
    if not settings.LLM_API_KEY:
        problems.append("LLM_API_KEY 未配置：实体提取/答案生成不可用")
    import os
    if not os.getenv("EMBEDDING_API_URL"):
        problems.append("EMBEDDING_API_URL 未配置：GPU bge-m3 编码服务不可达")
    if problems:
        raise RuntimeError("生产启动自检失败：" + "；".join(problems))


def warmup_store():
    """后台预热：检查 GPU 编码服务 + Milvus 连通性（v2 引擎无本地模型，秒级完成）

    model_ready 语义 = 查询图所需的外部依赖全部就绪：
    - GPU bge-m3 编码服务（远程，EMBEDDING_API_URL）
    - Milvus（混合检索）
    """
    global model_ready, embedding_ready, milvus_ready
    try:
        from app.engine.utils.embedding_utils import check_embedding_service
        from app.engine.utils.milvus_utils import check_milvus_ready

        embedding_ready = check_embedding_service()
        milvus_ready = check_milvus_ready()
        model_ready = embedding_ready and milvus_ready
        print(f"[Warmup] 编码服务={'OK' if embedding_ready else 'FAIL'}，"
              f"Milvus={'OK' if milvus_ready else 'FAIL'}")
    except Exception as e:
        print(f"[Warmup] 预热失败（将在首次提问时重试）：{e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_sanity_check()
    print(f"[{settings.APP_NAME}] 启动中...")
    await ensure_schema()  # 轻量自动迁移（file_hash 列等）
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, warmup_store)
    yield
    print(f"[{settings.APP_NAME}] 关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "model_ready": model_ready,          # 引擎整体就绪（编码服务 + Milvus）
        "embedding_ready": embedding_ready,  # GPU bge-m3 编码服务
        "milvus_ready": milvus_ready,        # Milvus 向量库
    }
