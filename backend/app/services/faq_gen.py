# -*- coding: utf-8 -*-
"""FAQ 自动生成：Milvus 混合检索 Top-5 → LLM 生成标准答案 → 草稿（管理员审核后发布）

同步实现，由 ops 端点放线程池执行，不阻塞事件循环。
管理员视角全库检索（enabled 即可见），FAQ 发布时由管理员确认来源。
"""
import httpx

from app.core.config import settings

FAQ_SYSTEM_PROMPT = """你是企业知识库的 FAQ 撰写助手。请严格按以下规则输出标准答案：

1. 仅依据下方【检索资料】中的内容回答，不可编造或补充外部知识
2. 输出简洁准确的标准答案，要点式回答
3. 如资料中未包含问题的信息，直接输出：资料中未包含此内容

【检索资料】
{context}

【问题】
{question}"""


def _search_top_chunks(question: str, top_k: int = 5) -> list[dict]:
    """Milvus 混合检索（dense+sparse），管理员视角：仅过滤 enabled"""
    from app.engine.config.config import milvus_config
    from app.engine.utils.embedding_utils import generate_embeddings
    from app.engine.utils.milvus_utils import create_hybrid_search_request, hybrid_search

    embeddings = generate_embeddings([question])
    reqs = create_hybrid_search_request(
        dense_vector=embeddings["dense"][0],
        sparse_vector=embeddings["sparse"][0],
        expr="enabled == true",
        limit=top_k,
    )
    res = hybrid_search(
        collection_name=milvus_config.chunks_collection,
        reqs=reqs,
        ranker_weights=(0.8, 0.2),
        norm_score=True,
        output_fields=["chunk_id", "doc_id", "content", "item_name", "file_title"],
        limit=top_k,
    )
    return res[0] if res else []


def generate_faq_for_question(question: str) -> dict | None:
    """对单条高频问题生成 FAQ 草稿

    返回 {"answer": str, "doc_ids": [...]}，检索无结果返回 None
    """
    candidates = _search_top_chunks(question)
    if not candidates:
        return None

    parts = []
    for i, hit in enumerate(candidates, 1):
        ent = hit.get("entity") or {}
        content = ent.get("content") or ""
        if not content:
            continue
        parts.append(f"[片段{i}] 来源：{ent.get('file_title') or ent.get('doc_id')}\n{content}")
    if not parts:
        return None

    prompt = FAQ_SYSTEM_PROMPT.format(
        context="\n\n".join(parts), question=question)
    with httpx.Client(timeout=120, trust_env=False) as client:
        resp = client.post(
            f"{settings.LLM_API_BASE}/chat/completions",
            json={
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "你是企业知识库的 FAQ 撰写助手，输出简洁准确的标准答案。"},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "max_tokens": 1500,
                "thinking": {"type": "disabled"},
            },
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()

    answer = data["choices"][0]["message"]["content"].strip()
    if not answer:
        return None
    doc_ids = list({
        (hit.get("entity") or {}).get("doc_id")
        for hit in candidates if (hit.get("entity") or {}).get("doc_id")
    })
    return {"answer": answer, "doc_ids": doc_ids}
