# -*- coding: utf-8 -*-
"""种子数据初始化 v2 — 引擎版（DB + Milvus 双写）

v1 只写 SQLite；v2 检索走 Milvus 混合检索，种子文档必须经引擎导入图
完成「切片 → 主体识别 → GPU 编码 → Milvus 入库（含四维权限字段）」，
与生产上传链路完全一致，保证检索质量与权限下沉行为相同。

流程：
1. 重建表结构（drop_all + create_all）
2. 创建部门（5）/角色（4）/用户（6 个测试账号）
3. 逐份导入种子文档（documents.jsonl 的 raw_text → 引擎图 → DB 收尾）

前置条件（容器内执行时均满足）：
- Milvus 可达（MILVUS_URI）
- GPU 编码服务可达（EMBEDDING_API_URL）
- LLM 可达（LLM_API_KEY，主体识别用）

用法：
    python scripts/seed.py
"""
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 把 backend 目录加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import async_session, engine
from app.core.security import hash_password
from app.models import (
    Base, Department, Role, User, UserRole,
    KnowledgeUnit, KnowledgePermission, KnowledgeChunk,
)

# 本地开发: kb-platform/data/processed；容器内挂载: /app/data/processed
_candidates = [
    Path(__file__).resolve().parent.parent.parent / "data" / "processed",
    Path("/app/data/processed"),
]
SEED_DATA_DIR = next((p for p in _candidates if p.exists()), _candidates[0])


DEPARTMENTS = ["研发部", "人力资源部", "财务部", "客服部", "总经理办公室"]
ROLES = [
    ("普通用户", "默认角色"),
    ("HR专员", "人力资源部专用"),
    ("财务专员", "财务部专用"),
    ("管理层", "M4 及以上"),
]
USERS = [
    ("admin", "admin123", "管理员", "总经理办公室", ["管理层"], True),
    ("zhangwei", "user123", "张伟", "研发部", ["普通用户"], False),
    ("lina", "user123", "李娜", "人力资源部", ["HR专员"], False),
    ("wangqiang", "user123", "王强", "财务部", ["财务专员"], False),
    ("zhaomin", "user123", "赵敏", "总经理办公室", ["管理层"], False),
    ("chenchen", "user123", "陈晨", "研发部", ["普通用户", "管理层"], False),
]


def _import_doc_via_engine(doc: dict) -> dict:
    """单份种子文档走引擎导入图（同步，返回 final_state）

    与 task_manager.run_ingest_task 阶段 2 等价：临时 md → 导入图
    （解析/切片/主体识别/GPU 编码/Milvus 入库）。
    """
    from app.engine.import_process.main_graph import kb_import_app

    work_dir = tempfile.mkdtemp(prefix="seed-")
    try:
        title = doc["title"]
        md_path = Path(work_dir) / f"{title}.md"   # 文件名即 file_title（entry 节点从文件名取）
        md_path.write_text(doc["raw_text"], encoding="utf-8")

        raw = doc["raw_text"].encode("utf-8")
        init_state = {
            "task_id": f"seed-{doc['doc_id']}",
            "local_file_path": str(md_path),
            "local_dir": os.path.join(work_dir, "output"),
            "file_title": title,
            "doc_id": doc["doc_id"],
            "file_hash": hashlib.sha256(raw).hexdigest(),
            "permissions": doc.get("permissions") or [],
        }
        return kb_import_app.invoke(init_state)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def seed():
    async with async_session() as db:
        # 1. 建表（重建，种子脚本语义即重置）
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        print("[1/5] 表结构已创建")

        # 2. 部门
        dept_map = {}
        for name in DEPARTMENTS:
            dept = Department(name=name)
            db.add(dept)
            await db.flush()
            dept_map[name] = dept.id
        await db.commit()
        print(f"[2/5] 部门已创建：{len(dept_map)} 个")

        # 3. 角色
        role_map = {}
        for name, desc in ROLES:
            role = Role(name=name, description=desc)
            db.add(role)
            await db.flush()
            role_map[name] = role.id
        await db.commit()
        print(f"[3/5] 角色已创建：{len(role_map)} 个")

        # 4. 用户
        for username, password, display_name, dept_name, role_names, is_admin in USERS:
            user = User(
                username=username,
                hashed_password=hash_password(password),
                display_name=display_name,
                dept_id=dept_map.get(dept_name),
                is_admin=is_admin,
            )
            db.add(user)
            await db.flush()
            for rn in role_names:
                db.add(UserRole(user_id=user.id, role_id=role_map[rn]))
        await db.commit()
        print(f"[4/5] 用户已创建：{len(USERS)} 个")

    # 5. 种子文档：引擎导入（Milvus）→ DB 收尾
    docs_file = SEED_DATA_DIR / "documents.jsonl"
    if not docs_file.exists():
        print("[5/5] 跳过知识库导入：documents.jsonl 不存在")
        return

    docs = [json.loads(line) for line in docs_file.read_text(encoding="utf-8").splitlines() if line]
    print(f"[5/5] 开始引擎导入 {len(docs)} 份文档（Milvus + GPU 编码）...")

    for i, doc in enumerate(docs, start=1):
        # 5a. 引擎图（同步阻塞，线程化避免阻塞事件循环）
        final_state = await asyncio.to_thread(_import_doc_via_engine, doc)
        chunks = final_state.get("chunks") or []
        md_content = final_state.get("md_content") or ""
        if not chunks:
            print(f"  [{i}/{len(docs)}] {doc['title']}：切片为空，跳过 DB 写入！")
            continue

        # 5b. DB 收尾（与 task_manager 阶段 3 一致）
        async with async_session() as db:
            dup = await db.execute(
                select(KnowledgeUnit.id).where(KnowledgeUnit.doc_id == doc["doc_id"])
            )
            if dup.scalar_one_or_none() is not None:
                print(f"  [{i}/{len(docs)}] {doc['title']}：已存在，跳过")
                continue

            unit = KnowledgeUnit(
                doc_id=doc["doc_id"],
                title=doc["title"],
                file_name=doc["file_name"],
                category=doc["category"],
                source_format=doc["source_format"],
                char_count=len(md_content) or doc.get("char_count", 0),
                is_enabled=True,
                file_hash=hashlib.sha256(doc["raw_text"].encode("utf-8")).hexdigest(),
            )
            db.add(unit)
            await db.flush()
            for perm in doc.get("permissions", []):
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
        print(f"  [{i}/{len(docs)}] {doc['title']}：{len(chunks)} 个切片已入库")

    print("\n===== 种子数据初始化完成 =====")
    print("测试账号：")
    for u, p, name, dept, roles, is_admin in USERS:
        tag = " (管理员)" if is_admin else ""
        print(f"  {u} / {p}  —  {name} @ {dept}  角色: {','.join(roles)}{tag}")


if __name__ == "__main__":
    asyncio.run(seed())
