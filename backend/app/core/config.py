# -*- coding: utf-8 -*-
"""应用配置 — 从环境变量读取"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "KB Platform"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    CORS_ORIGINS: str = "*"  # 逗号分隔的允许来源，生产建议收紧为前端域名

    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://kb_admin:kb_password@localhost:5432/kb_platform"
    # SQLite fallback for local dev without Postgres
    DATABASE_URL_DEV: str = "sqlite+aiosqlite:///./kb_platform.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Milvus（引擎混合检索，MILVUS_URI 空时启动自检会拦截生产启动）
    MILVUS_URI: str = ""
    MILVUS_COLLECTION: str = "knowledge_chunks_v2"

    # LLM（引擎查询图与 FAQ 生成共用）
    LLM_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen-flash"

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    @property
    def db_url(self) -> str:
        if self.DEBUG:
            return self.DATABASE_URL_DEV
        return self.DATABASE_URL

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
