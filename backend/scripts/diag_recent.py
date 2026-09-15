# -*- coding: utf-8 -*-
"""诊断：最近提问为何查不到"""
import asyncio
import json
from sqlalchemy import select, desc
from app.core.database import async_session
from app.models import ChatLog


async def main():
    async with async_session() as db:
        result = await db.execute(
            select(ChatLog).order_by(desc(ChatLog.id)).limit(10)
        )
        logs = result.scalars().all()
        print(f"最近 {len(logs)} 条问答记录：\n")
        for log in reversed(logs):
            print(f"--- [{log.id}] {log.created_at} faq_hit={log.faq_hit} ---")
            print(f"Q: {log.question}")
            print(f"A: {log.answer[:200] if log.answer else '(空)'}")
            print(f"cited={log.cited_chunk_ids}")
            print(f"blocked={log.blocked_chunk_ids}")
            print()

asyncio.run(main())
