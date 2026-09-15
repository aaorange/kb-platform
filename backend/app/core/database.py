# -*- coding: utf-8 -*-
"""数据库引擎与 Session"""
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings

engine = create_async_engine(settings.db_url, echo=settings.DEBUG, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def ensure_schema():
    """轻量自动迁移：项目无 alembic，启动时幂等地补齐新列/索引，避免线上手工 ALTER

    目前仅处理 knowledge_units.file_hash（上传幂等去重）。
    """
    def _migrate(sync_conn):
        insp = inspect(sync_conn)
        cols = {c["name"] for c in insp.get_columns("knowledge_units")}
        if cols and "file_hash" not in cols:
            sync_conn.execute(text(
                "ALTER TABLE knowledge_units ADD COLUMN file_hash VARCHAR(64)"
            ))
        idx_names = {i["name"] for i in insp.get_indexes("knowledge_units")}
        if "ux_units_file_hash" not in idx_names:
            # 首次加列时全为 NULL，唯一索引必建成功；若历史数据已存在重复则降级普通索引
            try:
                sync_conn.execute(text(
                    "CREATE UNIQUE INDEX ux_units_file_hash ON knowledge_units(file_hash)"
                ))
            except Exception:
                sync_conn.execute(text(
                    "CREATE INDEX ix_units_file_hash ON knowledge_units(file_hash)"
                ))

    async with engine.begin() as conn:
        await conn.run_sync(_migrate)
