# -*- coding: utf-8 -*-
"""运营 API：FAQ 管理 + FAQ 自动生成 + 知识缺口 + 数据看板"""
import hashlib
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, func, desc, case as sql_case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models import User, FAQ, KnowledgeGap, ChatLog, ChatSession, KnowledgeUnit, KnowledgeChunk
from app.schemas import FAQOut, FAQCreate, FAQAutoGen, FAQQuestion, GapOut, DashboardStats

router = APIRouter(prefix="/ops", tags=["运营管理"])


# ===== FAQ =====
@router.get("/faqs", response_model=list[FAQOut])
async def list_faqs(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(select(FAQ).order_by(desc(FAQ.hit_count)))
    return result.scalars().all()


@router.post("/faqs", response_model=FAQOut)
async def create_faq(req: FAQCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    import hashlib
    qh = hashlib.md5(req.question.strip().lower().encode()).hexdigest()
    faq = FAQ(question=req.question, answer=req.answer, source_question_hash=qh,
              source_doc_ids=req.doc_ids)
    db.add(faq)
    await db.commit()
    await db.refresh(faq)
    return faq


@router.post("/faqs/{faq_id}/cache")
async def publish_faq_cache(faq_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """发布 FAQ 到 Redis 缓存（含来源文档，供命中时权限复核）"""
    import redis.asyncio as aioredis

    result = await db.execute(select(FAQ).where(FAQ.id == faq_id))
    faq = result.scalar_one_or_none()
    if not faq:
        return {"error": "FAQ 不存在"}

    redis_client = aioredis.from_url(settings.REDIS_URL)
    try:
        await redis_client.ping()
    except Exception:
        await redis_client.aclose() if hasattr(redis_client, "aclose") else await redis_client.close()
        return {"error": "Redis 未启动，无法写入 FAQ 缓存"}
    qh = faq.source_question_hash
    await redis_client.set(f"faq:{qh}", json.dumps({
        "answer": faq.answer, "faq_id": faq.id,
        "source_doc_ids": faq.source_doc_ids or [],
    }, ensure_ascii=False))
    await redis_client.close()
    return {"message": "FAQ 已写入缓存", "faq_id": faq_id}


@router.post("/faqs/auto-generate")
async def auto_generate_faqs(
    req: FAQAutoGen,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """FAQ 自动生成：取高频已命中问题 → 检索 Top-5 → LLM 生成答案 → 存为草稿

    仅统计有引用切片的问题（知识库已能回答），排除已有 FAQ 的问题
    """
    # 1. 高频问题（有引用、未生成过 FAQ）
    top_q = await db.execute(
        select(ChatLog.question, func.count(ChatLog.id).label("cnt"))
        .where(func.json_array_length(ChatLog.cited_chunk_ids) > 0)
        .group_by(ChatLog.question)
        .order_by(desc("cnt"))
        .limit(req.count * 2)
    )
    rows = top_q.all()

    existing = await db.execute(select(FAQ.source_question_hash))
    existing_hashes = {r[0] for r in existing.all()}

    candidates = []
    for q, cnt in rows:
        qh = hashlib.md5(q.strip().lower().encode()).hexdigest()
        if qh not in existing_hashes and q not in [c[0] for c in candidates]:
            candidates.append((q, cnt))
        if len(candidates) >= req.count:
            break

    if not candidates:
        return {"message": "没有可生成的高频问题（需先产生带引用的问答记录）", "generated": []}

    # 2. 逐条生成（检索→LLM，CPU/IO 密集放线程池）
    from app.services.faq_gen import generate_faq_for_question
    generated, skipped = [], []
    for q, cnt in candidates:
        try:
            result = await run_in_threadpool(generate_faq_for_question, q)
        except Exception as e:
            skipped.append({"question": q, "reason": str(e)[:100]})
            continue
        if not result:
            skipped.append({"question": q, "reason": "检索无结果"})
            continue

        qh = hashlib.md5(q.strip().lower().encode()).hexdigest()
        faq = FAQ(
            question=q,
            answer=result["answer"],
            source_question_hash=qh,
            source_doc_ids=result["doc_ids"],
            is_published=False,  # 草稿，管理员审核后再发布
        )
        db.add(faq)
        generated.append({"question": q, "ask_count": cnt, "doc_ids": result["doc_ids"]})

    await db.commit()
    return {
        "message": f"已生成 {len(generated)} 条 FAQ 草稿，请在列表中审核后发布到缓存",
        "generated": generated, "skipped": skipped,
    }


@router.get("/faq-candidates")
async def faq_candidates(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """新增 FAQ 的候选问题：高频已命中问答 + 知识缺口池（按频次排序）"""
    # 高频问答（带引用 = 知识库能答上）
    chat_rows = await db.execute(
        select(ChatLog.question, func.count(ChatLog.id).label("cnt"))
        .group_by(ChatLog.question)
        .order_by(desc("cnt"))
        .limit(20)
    )
    existing = await db.execute(select(FAQ.source_question_hash))
    existing_hashes = {r[0] for r in existing.all()}

    candidates = []
    seen = set()
    for q, cnt in chat_rows:
        qh = hashlib.md5(q.strip().lower().encode()).hexdigest()
        if qh in existing_hashes or q in seen:
            continue
        seen.add(q)
        candidates.append({"question": q, "count": cnt, "source": "chat"})

    # 知识缺口（知识库答不上的高频问题）
    gap_rows = await db.execute(
        select(KnowledgeGap.question, KnowledgeGap.frequency)
        .where(KnowledgeGap.status == "open")
        .order_by(desc(KnowledgeGap.frequency))
        .limit(20)
    )
    for q, freq in gap_rows:
        qh = hashlib.md5(q.strip().lower().encode()).hexdigest()
        if qh in existing_hashes or q in seen:
            continue
        seen.add(q)
        candidates.append({"question": q, "count": freq, "source": "gap"})

    return candidates[:30]


@router.post("/faqs/generate-answer")
async def generate_faq_answer(
    req: FAQQuestion,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """对指定问题一键生成 FAQ 答案（检索 Top-5 → LLM）"""
    from app.services.faq_gen import generate_faq_for_question
    try:
        result = await run_in_threadpool(generate_faq_for_question, req.question)
    except Exception as e:
        raise HTTPException(500, f"生成失败：{str(e)[:200]}")
    if not result:
        raise HTTPException(400, "检索无相关资料，无法生成答案")
    return result


# ===== Knowledge Gaps =====
@router.get("/gaps", response_model=list[GapOut])
async def list_gaps(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(
        select(KnowledgeGap).where(KnowledgeGap.status == "open")
        .order_by(desc(KnowledgeGap.frequency))
    )
    return result.scalars().all()


# ===== Dashboard =====
@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    # PV = 问答总数，UV = 提问用户数
    pv_result = await db.execute(select(func.count(ChatLog.id)))
    pv = pv_result.scalar()

    uv_result = await db.execute(
        select(func.count(func.distinct(ChatSession.user_id)))
        .select_from(ChatLog)
        .join(ChatSession, ChatLog.session_id == ChatSession.id)
    )
    uv = uv_result.scalar() or 0

    units_result = await db.execute(select(func.count(KnowledgeUnit.id)))
    total_units = units_result.scalar() or 0

    chunks_result = await db.execute(select(func.count(KnowledgeChunk.id)))
    total_chunks = chunks_result.scalar() or 0

    faq_result = await db.execute(select(func.count(FAQ.id)).where(FAQ.is_published))
    total_faq = faq_result.scalar() or 0

    gap_result = await db.execute(select(func.count(KnowledgeGap.id)).where(KnowledgeGap.status == "open"))
    total_gaps = gap_result.scalar() or 0

    token_result = await db.execute(select(func.sum(ChatLog.token_count)))
    token_total = token_result.scalar() or 0

    avg_result = await db.execute(select(func.avg(ChatLog.response_ms)))
    avg_ms = int(avg_result.scalar() or 0)

    # 高频问题 TOP 5
    top_q_result = await db.execute(
        select(ChatLog.question, func.count(ChatLog.id).label("cnt"))
        .group_by(ChatLog.question)
        .order_by(desc("cnt"))
        .limit(5)
    )
    top_questions = [{"question": r[0], "count": r[1]} for r in top_q_result]

    # 反馈统计
    fb_pos_result = await db.execute(
        select(func.count(ChatLog.id)).where(ChatLog.feedback == 1)
    )
    fb_pos = fb_pos_result.scalar() or 0
    fb_neg_result = await db.execute(
        select(func.count(ChatLog.id)).where(ChatLog.feedback == -1)
    )
    fb_neg = fb_neg_result.scalar() or 0

    return DashboardStats(
        pv=pv, uv=uv, total_units=total_units, total_chunks=total_chunks,
        total_faq=total_faq, total_gaps=total_gaps,
        top_questions=top_questions, token_total=token_total, avg_response_ms=avg_ms,
        feedback_positive=fb_pos, feedback_negative=fb_neg,
    )


@router.get("/dashboard/full")
async def dashboard_full(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """增强看板：卡片指标 + 30天趋势 + 知识覆盖率 + 分类分布 + 文档热度 + 拦截分析 + 满意度趋势"""
    today = datetime.utcnow().date()
    since = datetime.combine(today - timedelta(days=29), datetime.min.time())

    # --- 基础卡片指标 ---
    pv = (await db.execute(select(func.count(ChatLog.id)))).scalar() or 0
    uv = (await db.execute(
        select(func.count(func.distinct(ChatSession.user_id)))
        .select_from(ChatLog).join(ChatSession, ChatLog.session_id == ChatSession.id)
    )).scalar() or 0
    total_units = (await db.execute(select(func.count(KnowledgeUnit.id)))).scalar() or 0
    total_chunks = (await db.execute(select(func.count(KnowledgeChunk.id)))).scalar() or 0
    total_faq = (await db.execute(select(func.count(FAQ.id)).where(FAQ.is_published))).scalar() or 0
    total_gaps = (await db.execute(
        select(func.count(KnowledgeGap.id)).where(KnowledgeGap.status == "open")
    )).scalar() or 0
    token_total = int((await db.execute(select(func.sum(ChatLog.token_count)))).scalar() or 0)
    avg_ms = int((await db.execute(select(func.avg(ChatLog.response_ms)))).scalar() or 0)
    fb_pos = (await db.execute(
        select(func.count(ChatLog.id)).where(ChatLog.feedback == 1)
    )).scalar() or 0
    fb_neg = (await db.execute(
        select(func.count(ChatLog.id)).where(ChatLog.feedback == -1)
    )).scalar() or 0

    # 高频问题 TOP 10
    top_q = (await db.execute(
        select(ChatLog.question, func.count(ChatLog.id).label("cnt"))
        .group_by(ChatLog.question).order_by(desc("cnt")).limit(10)
    )).all()
    top_questions = [{"question": r[0], "count": r[1]} for r in top_q]

    # --- 1. 近 30 天趋势（问答量 + Token） ---
    trend_rows = (await db.execute(
        select(
            func.date(ChatLog.created_at).label("day"),
            func.count(ChatLog.id).label("cnt"),
            func.sum(ChatLog.token_count).label("tokens"),
        ).where(ChatLog.created_at >= since).group_by("day").order_by("day")
    )).all()
    trend_map = {str(r[0]): {"count": r[1], "tokens": int(r[2] or 0)} for r in trend_rows}
    trend = []
    for i in range(30):
        d = str(today - timedelta(days=29 - i))
        t = trend_map.get(d)
        trend.append({"date": d[5:], "count": t["count"] if t else 0,
                      "tokens": t["tokens"] if t else 0})

    # --- 2. 知识覆盖率（有引用回答占比） ---
    hit_q = (await db.execute(
        select(func.count(ChatLog.id)).where(func.json_array_length(ChatLog.cited_chunk_ids) > 0)
    )).scalar() or 0
    coverage = round(hit_q / pv * 100, 1) if pv else 0.0

    # --- 3/4/5. 引用与拦截的 JSON 聚合 ---
    logs_rows = (await db.execute(
        select(ChatLog.cited_chunk_ids, ChatLog.blocked_chunk_ids)
    )).all()
    doc_cite_count, doc_block_count = {}, {}
    blocked_q = 0
    for cited, blocked in logs_rows:
        for d in {cid.rsplit("-", 1)[0] for cid in (cited or [])}:
            doc_cite_count[d] = doc_cite_count.get(d, 0) + 1
        if blocked:
            blocked_q += 1
            for d in set(blocked):
                doc_block_count[d] = doc_block_count.get(d, 0) + 1

    units_rows = (await db.execute(
        select(KnowledgeUnit.doc_id, KnowledgeUnit.title, KnowledgeUnit.category)
    )).all()
    unit_map = {r[0]: {"title": r[1], "category": r[2]} for r in units_rows}

    # 文档热度 TOP 10
    doc_heat = sorted(doc_cite_count.items(), key=lambda x: -x[1])[:10]
    doc_heat = [{"doc_id": d, "title": unit_map.get(d, {}).get("title") or d, "count": c}
                for d, c in doc_heat]

    # 问题分类分布（引用文档 → 分类）
    cat_count = {}
    for d, c in doc_cite_count.items():
        cat = unit_map.get(d, {}).get("category") or "未分类"
        cat_count[cat] = cat_count.get(cat, 0) + c
    category_dist = [{"name": k, "value": v}
                     for k, v in sorted(cat_count.items(), key=lambda x: -x[1])]

    # 拦截分析
    top_blocked = sorted(doc_block_count.items(), key=lambda x: -x[1])[:5]
    blocked_docs = [{"doc_id": d, "title": unit_map.get(d, {}).get("title") or d, "count": c}
                    for d, c in top_blocked]

    # --- 6. 满意度趋势（按天 赞/踩/好评率） ---
    fb_rows = (await db.execute(
        select(
            func.date(ChatLog.created_at).label("day"),
            func.sum(sql_case((ChatLog.feedback == 1, 1), else_=0)).label("pos"),
            func.sum(sql_case((ChatLog.feedback == -1, 1), else_=0)).label("neg"),
        ).where(ChatLog.feedback != 0).group_by("day").order_by("day")
    )).all()
    satisfaction = []
    for r in fb_rows:
        pos, neg = int(r[1] or 0), int(r[2] or 0)
        rate = round(pos / (pos + neg) * 100) if (pos + neg) else None
        satisfaction.append({"date": str(r[0])[5:], "pos": pos, "neg": neg, "rate": rate})

    return {
        # 卡片
        "pv": pv, "uv": uv, "total_units": total_units, "total_chunks": total_chunks,
        "total_faq": total_faq, "total_gaps": total_gaps, "token_total": token_total,
        "avg_response_ms": avg_ms, "feedback_positive": fb_pos, "feedback_negative": fb_neg,
        "hit_questions": hit_q, "coverage_pct": coverage,
        "satisfaction_pct": round(fb_pos / (fb_pos + fb_neg) * 100, 1) if (fb_pos + fb_neg) else None,
        # 图表
        "trend": trend,
        "category_dist": category_dist,
        "doc_heat": doc_heat,
        "top_questions": top_questions,
        "blocked": {"question_count": blocked_q, "docs": blocked_docs},
        "satisfaction_trend": satisfaction,
    }
