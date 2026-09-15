# -*- coding: utf-8 -*-
"""Milvus 向量重建脚本 — 从 SQLite 现有切片重建全部向量

适用场景：Milvus 数据丢失/初次迁移失败（如 Milvus 启动前就跑了导入），
但 DB 中切片数据完好。复用引擎的导入节点，与正常导入链路完全同构：
  DB 读切片 → 主体识别（LLM，item_name 集合）→ GPU 批量编码 → Milvus 入库

用法（容器内）：
    python scripts/rebuild_milvus.py            # 重建全部文档
    python scripts/rebuild_milvus.py DOC-FIN-001  # 只重建指定 doc_id
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = "/app/data/kb.db"
BATCH = 32  # 与 task_manager 导入链路一致


def load_docs(only_doc_id: str | None):
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    units = [dict(r) for r in c.execute(
        "select id, doc_id, title, file_hash, is_enabled from knowledge_units"
        + (" where doc_id = ?" if only_doc_id else ""), 
        (only_doc_id,) if only_doc_id else ())]
    out = []
    for u in units:
        perms = [dict(scope_type=r["scope_type"],
                      scope_value=r["scope_value"])
                 for r in c.execute(
                     "select scope_type, scope_value from knowledge_permissions where unit_id = ?",
                     (u["id"],))]
        chunks = [dict(title=r["heading"] or "无标题", content=r["content"],
                       parent_title=r["heading"] or "无标题", part=0,
                       file_title=u["title"])
                  for r in c.execute(
                      "select heading, content from knowledge_chunks "
                      "where unit_id = ? order by chunk_index", (u["id"],))]
        out.append((u, perms, chunks))
    c.close()
    return out


def encode_chunks(chunks: list[dict]) -> list[dict]:
    from app.engine.utils.embedding_utils import generate_embeddings
    texts = [ch["content"] for ch in chunks]
    for i in range(0, len(texts), BATCH):
        vec = generate_embeddings(texts[i:i + BATCH])
        for j, ch in enumerate(chunks[i:i + BATCH]):
            ch["dense_vector"] = vec["dense"][j]
            ch["sparse_vector"] = vec["sparse"][j]
    return chunks


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    docs = load_docs(only)
    if not docs:
        print("没有可重建的文档")
        sys.exit(1)

    from app.engine.import_process.nodes.node_import_milvus import NodeImportMilvus
    from app.engine.import_process.nodes.node_item_name_recognition import (
        NodeItemNameRecognition)
    from app.engine.utils.milvus_utils import set_doc_enabled

    total = sum(len(ch) for _, _, ch in docs)
    print(f"待重建：{len(docs)} 个文档 / {total} 个切片")

    for n, (unit, perms, chunks) in enumerate(docs, 1):
        doc_id, title = unit["doc_id"], unit["title"]
        t0 = time.time()
        if not chunks:
            print(f"[{n}/{len(docs)}] {title}（{doc_id}）无切片，跳过")
            continue

        # 1. 主体识别（LLM + item_name 集合入库），回填 chunks 的 item_name
        rec = NodeItemNameRecognition()
        rec_state = {"file_title": title, "chunks": chunks,
                     "doc_id": doc_id, "permissions": perms}
        rec_result = rec.process(rec_state)
        chunks = rec_result["chunks"]

        # 2. 批量编码 + chunks 集合入库
        chunks = encode_chunks(chunks)
        imp = NodeImportMilvus()
        imp.process({"chunks": chunks, "doc_id": doc_id,
                     "file_hash": unit["file_hash"] or "", "permissions": perms})

        # 3. 禁用态同步（默认插入 enabled=True）
        if not unit["is_enabled"]:
            set_doc_enabled(doc_id, False)

        print(f"[{n}/{len(docs)}] {title}（{doc_id}）：{len(chunks)} 切片 "
              f"item_name={rec_result['item_name'][:20]} 耗时 {time.time()-t0:.1f}s")

    print("重建完成")


if __name__ == "__main__":
    main()
