# -*- coding: utf-8 -*-
"""给 chat_sessions 表加 updated_at 列"""
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN updated_at DATETIME"))
            await conn.execute(text("UPDATE chat_sessions SET updated_at = created_at WHERE updated_at IS NULL"))
            print("已添加 updated_at 列")
            # 删表重建（SQLite 不支持改默认值，直接用应用层 onupdate 即可）
            await conn.execute(text("ALTER TABLE chat_sessions RENAME TO chat_sessions_old"))
            await conn.execute(text("""CREATE TABLE chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title VARCHAR(200) DEFAULT '新对话',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""))
            await conn.execute(text("""INSERT INTO chat_sessions(id, user_id, title, created_at, updated_at)
                SELECT id, user_id, title, created_at, COALESCE(updated_at, created_at) FROM chat_sessions_old"""))
            await conn.execute(text("DROP TABLE chat_sessions_old"))
            print("已重建 chat_sessions 表（含 updated_at 默认值）")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("updated_at 列已存在，跳过")
            else:
                raise

asyncio.run(main())
