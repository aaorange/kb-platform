# -*- coding: utf-8 -*-
"""知识管理 API：文档列表、文档上传导入（后台任务）、权限配置"""
import asyncio
import hashlib
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.engine.utils import milvus_utils
from app.models import User, KnowledgeUnit, KnowledgePermission
from app.schemas import KnowledgeUnitOut, PermissionUpdate, PermissionConfig
from app.services import task_manager
from app.services.ingest import SUPPORTED_EXTS

logger = logging.getLogger("kb.knowledge")

router = APIRouter(prefix="/knowledge", tags=["知识管理"])


async def _retry_async(fn, *args, attempts: int = 3, delay: float = 1.0):
    """向量库同步重试：降低瞬时 IO 失败导致 DB/向量库不一致的概率"""
    for i in range(attempts):
        try:
            return await fn(*args)
        except Exception:
            if i == attempts - 1:
                raise
            await asyncio.sleep(delay)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("未分类"),
    permissions: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """上传知识文档：流式落盘 + SHA256 去重 + 秒回 task_id；解析/编码/入库转后台任务"""
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(400, f"不支持的格式 {ext}，仅支持 md / txt / docx / pdf")

    try:
        perms = json.loads(permissions) if permissions else []
    except json.JSONDecodeError:
        raise HTTPException(400, "permissions 参数不是合法 JSON")
    for p in perms:
        if p.get("scope_type") not in ("global", "department", "role", "user"):
            raise HTTPException(400, f"非法权限维度：{p.get('scope_type')}")
        if p.get("scope_type") != "global" and not p.get("scope_value"):
            raise HTTPException(400, "department/role/user 权限必须填写 scope_value")

    # 流式落盘（1MB/块）+ 边写边算 SHA256，避免 50MB 全量驻留内存
    hasher = hashlib.sha256()
    tmp_dir = os.path.join(settings.UPLOAD_DIR, "tasks")
    os.makedirs(tmp_dir, exist_ok=True)
    # 落盘保留原始扩展名：.md 走"原样进图"分支时引擎入口按后缀识别类型，
    # 统一 .bin 会导致 .md 上传被拒（"不支持的文件类型：bin"）
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{ext}")
    size = 0
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        with open(tmp_path, "wb") as out:
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > max_bytes:
                    raise HTTPException(400, f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 上限")
                hasher.update(block)
                out.write(block)
    except HTTPException:
        os.remove(tmp_path)
        raise
    file_hash = hasher.hexdigest()

    # 幂等去重：内容相同的文档直接返回已有记录（504 重试/重复上传不再重复入库）
    result = await db.execute(
        select(KnowledgeUnit).where(KnowledgeUnit.file_hash == file_hash)
    )
    existing = result.scalar_one_or_none()
    if existing:
        os.remove(tmp_path)
        return {
            "message": f"内容相同的文档「{existing.title}」已存在，无需重复导入",
            "duplicated": True,
            "task_id": None,
            "unit": {
                "id": existing.id, "doc_id": existing.doc_id,
                "title": existing.title,
            },
        }

    task_id = task_manager.create_task(
        tmp_path, file.filename, title, category, perms, file_hash
    )
    asyncio.create_task(task_manager.run_ingest_task(task_id))
    return {"message": "已接收，正在后台处理", "task_id": task_id, "duplicated": False}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, _: User = Depends(require_admin)):
    """后台导入任务进度查询（前端 2s 轮询）"""
    t = task_manager.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在或已过期")
    return {
        "task_id": task_id,
        "status": t["status"],
        "progress": t["progress"],
        "message": t["message"],
        "file_name": t["file_name"],
        "unit_id": t.get("unit_id"),
        "doc_id": t.get("doc_id"),
    }


@router.get("/units", response_model=list[KnowledgeUnitOut])
async def list_units(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(
        select(KnowledgeUnit).options(selectinload(KnowledgeUnit.permissions))
        .order_by(KnowledgeUnit.id)
    )
    units = result.scalars().all()
    return [
        KnowledgeUnitOut(
            id=u.id, doc_id=u.doc_id, title=u.title, file_name=u.file_name,
            category=u.category, char_count=u.char_count, is_enabled=u.is_enabled,
            permissions=[
                PermissionConfig(scope_type=p.scope_type, scope_value=p.scope_value)
                for p in u.permissions
            ],
            created_at=u.created_at,
        )
        for u in units
    ]


@router.get("/units/{unit_id}/preview")
async def preview_unit(
    unit_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """文档在线预览：管理员可预览全部，普通用户须对该文档有权"""
    result = await db.execute(
        select(KnowledgeUnit)
        .options(selectinload(KnowledgeUnit.chunks), selectinload(KnowledgeUnit.permissions))
        .where(KnowledgeUnit.id == unit_id)
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(404, "知识单元不存在")

    if not user.is_admin:
        from app.services.authz import check_permission
        perms = [
            {"scope_type": p.scope_type, "scope_value": p.scope_value}
            for p in unit.permissions
        ]
        user_dept = user.department.name if user.department else None
        if not check_permission(user_dept, [r.name for r in user.roles], user.username, perms):
            raise HTTPException(403, "您没有查看该文档的权限")

    chunks = sorted(unit.chunks, key=lambda c: c.chunk_index)
    return {
        "id": unit.id, "doc_id": unit.doc_id, "title": unit.title,
        "file_name": unit.file_name, "category": unit.category,
        "source_format": unit.source_format, "char_count": unit.char_count,
        "is_enabled": unit.is_enabled,
        "chunk_count": len(chunks),
        "chunks": [
            {"chunk_index": c.chunk_index, "heading": c.heading, "content": c.content}
            for c in chunks
        ],
    }


@router.put("/units/{unit_id}/permissions")
async def update_permissions(
    unit_id: int,
    req: PermissionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(KnowledgeUnit).options(selectinload(KnowledgeUnit.permissions))
        .where(KnowledgeUnit.id == unit_id)
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="知识单元不存在")

    # 清除旧权限
    for old_perm in unit.permissions:
        await db.delete(old_perm)

    # 写入新权限
    new_perms = []
    for perm in req.permissions:
        db.add(KnowledgePermission(
            unit_id=unit_id,
            scope_type=perm.scope_type,
            scope_value=perm.scope_value,
        ))
        new_perms.append({"scope_type": perm.scope_type, "scope_value": perm.scope_value})

    await db.commit()

    # 同步更新 Milvus 的四维权限字段（重试 3 次；仍失败则返回警告，需人工重试）
    warning = None
    try:
        await _retry_async(
            run_in_threadpool, milvus_utils.update_doc_permissions, unit.doc_id, new_perms
        )
    except Exception:
        logger.exception("Milvus 权限同步失败 unit_id=%s doc_id=%s", unit_id, unit.doc_id)
        warning = "数据库权限已更新，但向量库同步失败，检索侧权限可能未生效，请重试或联系管理员"

    resp = {"message": "权限更新成功", "unit_id": unit_id, "permission_count": len(req.permissions)}
    if warning:
        resp["warning"] = warning
    return resp


@router.patch("/units/{unit_id}/toggle")
async def toggle_unit(
    unit_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """启用/禁用知识文档（软控制，不删数据；Milvus enabled 字段同步，检索立即生效）"""
    result = await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == unit_id))
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(404, "知识单元不存在")
    unit.is_enabled = not unit.is_enabled
    await db.commit()

    warning = None
    try:
        await _retry_async(
            run_in_threadpool, milvus_utils.set_doc_enabled, unit.doc_id, unit.is_enabled
        )
    except Exception:
        logger.exception("Milvus 启停同步失败 unit_id=%s doc_id=%s", unit_id, unit.doc_id)
        warning = "数据库已更新，但向量库同步失败，检索侧状态可能未生效，请重试或联系管理员"

    resp = {"message": f"已{'启用' if unit.is_enabled else '禁用'}", "is_enabled": unit.is_enabled}
    if warning:
        resp["warning"] = warning
    return resp


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """删除知识文档：DB 删除 + 向量库删除"""
    result = await db.execute(
        select(KnowledgeUnit)
        .options(selectinload(KnowledgeUnit.permissions), selectinload(KnowledgeUnit.chunks))
        .where(KnowledgeUnit.id == unit_id)
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(404, "知识单元不存在")

    doc_id = unit.doc_id
    title = unit.title

    # DB 删除（级联删除权限 + 切片）
    await db.delete(unit)
    await db.commit()

    # 向量库删除（chunks + item_name 两集合，重试 3 次；仍失败则返回警告，残留向量待人工清理）
    warning = None
    removed = -1
    try:
        removed = await _retry_async(
            run_in_threadpool, milvus_utils.delete_doc_vectors, doc_id
        )
    except Exception:
        logger.exception("向量库删除失败（DB 已删除）doc_id=%s", doc_id)
        warning = "数据库已删除，但向量库清理失败，可能有残留向量，请重试或联系管理员"

    resp = {"message": f"已删除「{title}」", "doc_id": doc_id, "vectors_removed": removed}
    if warning:
        resp["warning"] = warning
    return resp
