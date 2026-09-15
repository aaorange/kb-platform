# -*- coding: utf-8 -*-
"""文档导入后台任务管理 v2 — LangGraph 导入引擎版

上传接口只做「流式落盘 + SHA256 去重 + 建任务 + 秒回 task_id」，
解析/切片/实体识别/编码/Milvus 入库全部由 app/engine 导入图完成：
  entry → pdf_to_md / md_img → document_split → item_name_recognition
  → bge_embedding（GPU 远程双向量）→ import_milvus（含四维权限字段）

本模块只负责：引擎输入准备（txt/docx → md）+ 进度上报 + DB 收尾。

与 v1 的关键差异：
- 引擎先行写 Milvus（权限字段随切片下沉），本模块 DB 收尾；
  DB 失败时按 doc_id 清理两个集合的向量（回滚语义与 v1 一致）
- doc_id 在任务启动时预生成，导入节点幂等清理与 DB 关联共用
- 进度：graph 解析阶段 1-8%，编码 progress_cb 8-90%，DB 收尾 92-100%

约束：
- 任务表是进程内状态，backend 必须单 worker 运行
- 后端重启会丢失未完成任务的进度（已入库数据不受影响）
"""
import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models import KnowledgeUnit, KnowledgePermission, KnowledgeChunk
from app.services.ingest import parse_file

logger = logging.getLogger("kb.tasks")

_tasks: dict[str, dict] = {}
_import_semaphore = asyncio.Semaphore(1)  # 同时只允许 1 个导入任务，防 OOM
_MAX_TASKS = 200  # 任务注册表上限，FIFO 淘汰已完成任务


def create_task(file_path: str, file_name: str, title: str, category: str,
                permissions: list[dict], file_hash: str) -> str:
    if len(_tasks) >= _MAX_TASKS:
        # 只淘汰最旧的已结束任务，绝不踢掉运行中的任务
        done_states = {"completed", "failed", "duplicate"}
        for tid in list(_tasks):
            if _tasks[tid]["status"] in done_states:
                _tasks.pop(tid, None)
                break
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "status": "pending",  # pending|parsing|encoding|saving|completed|duplicate|failed
        "progress": 0,
        "message": "排队中",
        "file_path": file_path,
        "file_name": file_name,
        "title": title,
        "category": category,
        "permissions": permissions,
        "file_hash": file_hash,
        "created_at": datetime.utcnow(),
    }
    return task_id


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def _update(task_id: str, **fields):
    t = _tasks.get(task_id)
    if t:
        t.update(fields)


def _prepare_engine_input(t: dict, work_dir: str) -> dict:
    """引擎输入准备：txt/docx 转换为 md（引擎入口只认 pdf/md），并建好目录

    返回 {'file_path': 进图文件路径, 'pdf_parse_mode': pdf 模式 or None}
    """
    src = t["file_path"]
    file_name = t["file_name"]
    stem = os.path.splitext(file_name)[0] or "document"
    ext = os.path.splitext(file_name)[1].lower()

    output_dir = os.path.join(work_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    if ext in (".txt", ".docx"):
        with open(src, "rb") as f:
            content = f.read()
        md_text = parse_file(file_name, content, work_dir)
        if not md_text or not md_text.strip():
            raise ValueError("文档内容为空或无法提取文本")
        md_path = os.path.join(work_dir, f"{stem}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return {"file_path": md_path, "pdf_parse_mode": None}

    if ext == ".pdf":
        # MinerU 已配置则走外部解析（扫描件/图文混排），否则 pypdf 本地降级
        from app.engine.config.config import mineru_config
        mode = "mineru" if mineru_config.api_token else "local"
        return {"file_path": src, "pdf_parse_mode": mode}

    # .md 原样进图
    return {"file_path": src, "pdf_parse_mode": None}


async def run_ingest_task(task_id: str):
    """后台导入主流程：引擎图（解析→切片→编码→Milvus）→ DB 收尾

    顺序刻意为「向量库先行、DB 收尾」：引擎阶段失败时 DB 尚未写入，零残留；
    仅当 DB 写入失败才需回滚向量（delete_doc_vectors 清理两个集合）。
    """
    t = _tasks.get(task_id)
    if not t:
        return
    work_dir = os.path.join(settings.UPLOAD_DIR, "tasks", task_id)
    doc_id = f"DOC-UP-{uuid.uuid4().hex[:8].upper()}"
    try:
        async with _import_semaphore:
            # ---- 阶段 1：引擎输入准备 ----
            _update(task_id, status="parsing", progress=1, message="解析文档中")
            prepared = await asyncio.to_thread(_prepare_engine_input, t, work_dir)

            # ---- 阶段 2：导入图（解析/切片/实体识别/编码/Milvus 入库）----
            from app.engine.import_process.main_graph import kb_import_app

            def on_progress(done: int, total: int):
                _update(task_id, status="encoding",
                        progress=8 + int(done / max(total, 1) * 82),
                        message=f"向量化中 {done}/{total}")

            stem = os.path.splitext(t["file_name"])[0] or "document"
            init_state = {
                "task_id": task_id,
                "local_file_path": prepared["file_path"],
                "local_dir": os.path.join(work_dir, "output"),
                "file_title": stem,
                "doc_id": doc_id,
                "file_hash": t["file_hash"],
                "permissions": t["permissions"],
                "progress_cb": on_progress,
            }
            if prepared["pdf_parse_mode"]:
                init_state["pdf_parse_mode"] = prepared["pdf_parse_mode"]

            final_state = await asyncio.to_thread(kb_import_app.invoke, init_state)
            chunks = final_state.get("chunks") or []
            md_content = final_state.get("md_content") or ""
            if not chunks:
                raise ValueError("导入完成但切片为空（文档可能是空文件）")

            # ---- 阶段 3：写 DB（先做去重复核，防并发上传同一文件）----
            _update(task_id, status="saving", progress=92, message="写入数据库")
            async with async_session() as db:
                dup = await db.execute(
                    select(KnowledgeUnit.id).where(KnowledgeUnit.file_hash == t["file_hash"])
                )
                if dup.scalar_one_or_none() is not None:
                    await asyncio.to_thread(_remove_vectors, doc_id)
                    _update(task_id, status="duplicate", progress=100,
                            message="内容相同的文档已存在，已跳过")
                    return

                unit = KnowledgeUnit(
                    doc_id=doc_id,
                    title=t["title"] or t["file_name"],
                    file_name=t["file_name"],
                    category=t["category"] or "未分类",
                    source_format=os.path.splitext(t["file_name"])[1].lstrip(".").lower() or "md",
                    char_count=len(md_content),
                    is_enabled=True,
                    file_hash=t["file_hash"],
                )
                db.add(unit)
                await db.flush()
                for perm in t["permissions"]:
                    db.add(KnowledgePermission(
                        unit_id=unit.id,
                        scope_type=perm["scope_type"],
                        scope_value=perm.get("scope_value") or perm.get("scope_name"),
                    ))
                for idx, chunk in enumerate(chunks):
                    db.add(KnowledgeChunk(
                        unit_id=unit.id,
                        chunk_index=idx,
                        heading=(chunk.get("title") or "")[:512],
                        content=chunk.get("content") or "",
                    ))
                await db.commit()
                unit_id = unit.id

        _update(task_id, status="completed", progress=100,
                message=f"导入成功：{len(chunks)} 个切片已向量化",
                unit_id=unit_id, doc_id=doc_id)
    except Exception as e:
        logger.exception("导入任务 %s（%s）失败", task_id, t["file_name"])
        _update(task_id, status="failed", progress=100, message=f"导入失败：{e}")
        # 兜底清理：向量已入库但 DB 未写成功时，移除两个集合的残留向量
        try:
            await asyncio.to_thread(_remove_vectors, doc_id)
            logger.info("已清理 doc_id=%s 的残留向量", doc_id)
        except Exception:
            logger.error("清理 doc_id=%s 残留向量失败，请人工核查 Milvus", doc_id)
    finally:
        # 清理临时文件与工作目录（图片已托管 MinIO，本地无需保留）
        try:
            os.remove(t["file_path"])
        except OSError:
            pass
        shutil.rmtree(work_dir, ignore_errors=True)


def _remove_vectors(doc_id: str) -> int:
    from app.engine.utils.milvus_utils import delete_doc_vectors
    return delete_doc_vectors(doc_id)
