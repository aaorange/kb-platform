# -*- coding: utf-8 -*-
"""P1 功能迁移：chat_logs.feedback + faqs.source_doc_ids"""
import asyncio
from sqlalchemy import text
from app.core.database import engine


async def main():
    async with engine.begin() as conn:
        # chat_logs.feedback
        try:
            await conn.execute(text("ALTER TABLE chat_logs ADD COLUMN feedback INTEGER DEFAULT 0"))
            print("已添加 chat_logs.feedback")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("chat_logs.feedback 已存在，跳过")
            else:
                raise

        # faqs.source_doc_ids
        try:
            await conn.execute(text("ALTER TABLE faqs ADD COLUMN source_doc_ids JSON"))
            print("已添加 faqs.source_doc_ids")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("faqs.source_doc_ids 已存在，跳过")
            else:
                raise

    print("迁移完成")

asyncio.run(main())
