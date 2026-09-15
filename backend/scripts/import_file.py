# -*- coding: utf-8 -*-
"""单文件引擎导入脚本 — v1 数据迁移 / 手动补录用

与生产上传链路（task_manager）完全同构：引擎图（解析/切片/主体识别/
GPU 编码/Milvus 入库）→ DB 收尾。区别在于本脚本同步执行、不走任务表。

典型用法（容器内）：
    # 迁移 v1 旧库导出的文档文本
    python scripts/import_file.py /app/data/migration/rl_book.md \
        --title "强化学习修订版" --category "技术资料" \
        --permissions '[{"scope_type":"global"}]'

    # 指定 doc_id（沿用 v1 旧 ID，保持外部引用一致）
    python scripts/import_file.py xx.md --doc-id DOC-UP-44FB45A0 ...
"""
import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import async_session
from app.models import KnowledgeUnit, KnowledgePermission, KnowledgeChunk


def import_via_engine(file_path: str, file_title: str, doc_id: str,
                      file_hash: str, permissions: list) -> dict:
    from app.engine.import_process.main_graph import kb_import_app

    init_state = {
        "task_id": f"migrate-{doc_id}",
        "local_file_path": file_path,
        "local_dir": str(Path(file_path).parent / "output"),
        "file_title": file_title,
        "doc_id": doc_id,
        "file_hash": file_hash,
        "permissions": permissions,
    }
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        from app.engine.config.config import mineru_config
        init_state["pdf_parse_mode"] = "mineru" if mineru_config.api_token else "local"

    return kb_import_app.invoke(init_state)


async def main():
    parser = argparse.ArgumentParser(description="单文件引擎导入（Milvus + DB）")
    parser.add_argument("file", help="待导入文件路径（.md/.pdf）")
    parser.add_argument("--title", required=True, help="文档标题")
    parser.add_argument("--category", default="未分类", help="分类")
    parser.add_argument("--doc-id", default=None, help="指定 doc_id（默认自动生成）")
    parser.add_argument("--permissions", default='[{"scope_type":"global"}]',
                        help='权限 JSON，如 [{"scope_type":"department","scope_value":"研发部"}]')
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(f"文件不存在：{file_path}")
        sys.exit(1)
    if file_path.suffix.lower() not in (".md", ".pdf"):
        print("仅支持 .md / .pdf（txt/docx 请先转 md）")
        sys.exit(1)

    permissions = json.loads(args.permissions)
    doc_id = args.doc_id or f"DOC-UP-{uuid.uuid4().hex[:8].upper()}"
    file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

    print(f"开始引擎导入：{file_path.name} → doc_id={doc_id}")
    final_state = await asyncio.to_thread(
        import_via_engine, str(file_path), args.title, doc_id, file_hash, permissions,
    )
    chunks = final_state.get("chunks") or []
    md_content = final_state.get("md_content") or ""
    if not chunks:
        print("导入失败：切片为空")
        sys.exit(1)
    print(f"引擎完成：{len(chunks)} 个切片已入 Milvus")

    async with async_session() as db:
        dup = await db.execute(select(KnowledgeUnit.id).where(KnowledgeUnit.file_hash == file_hash))
        if dup.scalar_one_or_none() is not None:
            from app.engine.utils.milvus_utils import delete_doc_vectors
            await asyncio.to_thread(delete_doc_vectors, doc_id)
            print("内容相同的文档已存在，已回滚向量入库")
            sys.exit(0)

        unit = KnowledgeUnit(
            doc_id=doc_id,
            title=args.title,
            file_name=file_path.name,
            category=args.category,
            source_format=file_path.suffix.lstrip(".").lower(),
            char_count=len(md_content),
            is_enabled=True,
            file_hash=file_hash,
        )
        db.add(unit)
        await db.flush()
        for perm in permissions:
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

    print(f"DB 收尾完成：unit_id={unit_id} doc_id={doc_id} 切片 {len(chunks)} 个")


if __name__ == "__main__":
    asyncio.run(main())
