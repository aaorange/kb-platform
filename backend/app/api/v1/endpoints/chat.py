# -*- coding: utf-8 -*-
"""AI 问答 API — SSE 流式 + 聊天历史"""
import asyncio
import json
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db, async_session
from app.core.deps import get_current_user
from app.models import User, ChatSession, ChatLog, KnowledgeGap, KnowledgeUnit, FAQ
from app.schemas import ChatRequest, FeedbackRequest
from app.services.chat import stream_chat, question_hash

router = APIRouter(prefix="/chat", tags=["AI 问答"])


@router.get("/sessions")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的聊天会话列表"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id, "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某个会话的完整问答历史"""
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.logs))
        .where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"session_id": session_id, "messages": []}
    return {
        "session_id": session_id,
        "title": session.title,
        "messages": [
            {
                "id": log.id,
                "question": log.question,
                "answer": log.answer,
                "cited_chunk_ids": log.cited_chunk_ids or [],
                "blocked_doc_ids": log.blocked_chunk_ids or [],
                "faq_hit": log.faq_hit,
                "feedback": log.feedback or 0,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in sorted(session.logs, key=lambda x: x.id)
        ],
    }


@router.post("/logs/{log_id}/feedback")
async def submit_feedback(
    log_id: int,
    req: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """问答反馈：1=赞 -1=踩 0=取消（仅本人会话内的日志可评价）"""
    if req.value not in (-1, 0, 1):
        raise HTTPException(400, "value 只能是 1 / -1 / 0")

    result = await db.execute(
        select(ChatLog)
        .join(ChatSession, ChatLog.session_id == ChatSession.id)
        .where(ChatLog.id == log_id, ChatSession.user_id == user.id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(404, "问答记录不存在")

    log.feedback = req.value
    await db.commit()
    return {"message": "反馈已记录", "log_id": log_id, "feedback": req.value}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除聊天会话"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "会话不存在")
    await db.delete(session)
    await db.commit()
    return {"message": "会话已删除"}


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式问答 — 核心端点"""
    user_dept = user.department.name if user.department else None
    user_roles = [r.name for r in user.roles]

    # 会话历史（引擎实体提取/指代消解/答案生成用，取最近 6 轮）
    history: list[dict] = []
    if req.session_id:
        hres = await db.execute(
            select(ChatLog)
            .where(ChatLog.session_id == req.session_id)
            .order_by(ChatLog.id.desc())
            .limit(6)
        )
        for log in reversed(hres.scalars().all()):
            if log.answer:
                history.append({"role": "user", "text": log.question})
                history.append({"role": "assistant", "text": log.answer})

    # 各文档的权限映射（FAQ 缓存命中时的权限复核用）
    from app.models import KnowledgePermission
    doc_perms: dict[str, list[dict]] = {}
    perm_rows = await db.execute(
        select(KnowledgePermission.unit_id, KnowledgePermission.scope_type,
               KnowledgePermission.scope_value, KnowledgeUnit.doc_id)
        .join(KnowledgeUnit, KnowledgePermission.unit_id == KnowledgeUnit.id)
        .where(KnowledgeUnit.is_enabled == True)
    )
    for unit_id, scope_type, scope_value, doc_id in perm_rows:
        doc_perms.setdefault(doc_id, []).append(
            {"scope_type": scope_type, "scope_value": scope_value}
        )

    redis_client = None
    try:
        client = aioredis.from_url(settings.REDIS_URL)
        await client.ping()
        redis_client = client
    except Exception:
        redis_client = None  # Redis 未启动时降级：跳过 FAQ 缓存，走完整检索链路

    async def persist_log(full_answer: str, meta_data: dict) -> tuple[int, int]:
        """问答日志落库：session 创建 + ChatLog + FAQ 计数 + 知识缺口"""
        async with async_session() as db2:
            session_id = req.session_id
            if not session_id:
                session = ChatSession(user_id=user.id, title=req.question[:50])
                db2.add(session)
                await db2.flush()
                session_id = session.id

            log = ChatLog(
                session_id=session_id,
                question=req.question,
                answer=full_answer,
                cited_chunk_ids=[c["chunk_id"] for c in meta_data.get("cited_chunks", [])],
                blocked_chunk_ids=meta_data.get("blocked_doc_ids", []),
                faq_hit=meta_data.get("faq_hit", False),
                token_count=meta_data.get("token_count", 0),
                response_ms=meta_data.get("response_ms", 0),
            )
            db2.add(log)
            await db2.flush()

            # FAQ 命中计数
            if meta_data.get("faq_hit") and meta_data.get("faq_id"):
                fr = await db2.execute(select(FAQ).where(FAQ.id == meta_data["faq_id"]))
                faq_row = fr.scalar_one_or_none()
                if faq_row:
                    faq_row.hit_count += 1

            # 知识缺口记录
            if meta_data.get("gap"):
                qh = question_hash(req.question)
                result = await db2.execute(
                    select(KnowledgeGap).where(KnowledgeGap.question_hash == qh)
                )
                gap = result.scalar_one_or_none()
                if gap:
                    gap.frequency += 1
                else:
                    db2.add(KnowledgeGap(
                        question=req.question, question_hash=qh, frequency=1,
                    ))

            await db2.commit()
            return session_id, log.id

    async def event_generator():
        full_answer = ""
        meta_data = {}
        completed = False
        persist_result = None
        try:
            async for event in stream_chat(
                req.question, user_dept, user_roles, user.username, redis_client,
                history=history, doc_perms=doc_perms,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "meta":
                    meta_data = event
                    if event.get("full_answer"):
                        full_answer = event["full_answer"]
                elif event.get("type") == "faq_hit":
                    full_answer = event.get("answer", "")
            completed = True
        finally:
            # 客户端中途断开（generator 被 cancel）也会走到这里：
            # shield 保证已生成部分的日志仍然落库，Redis 连接仍然释放
            try:
                persist_result = await asyncio.shield(
                    persist_log(full_answer, meta_data)
                )
            except (Exception, asyncio.CancelledError):
                pass
            if redis_client:
                try:
                    await asyncio.shield(redis_client.close())
                except (Exception, asyncio.CancelledError):
                    pass

        # 正常完成时推送 session_id / log_id 给前端（断开路径不会执行到这里）
        if completed and persist_result:
            session_id, log_id = persist_result
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'title': req.question[:50]}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'log', 'log_id': log_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
