# -*- coding: utf-8 -*-
"""复测：admin 问高管年薪（验证 scope_name 兼容修复）"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=180)

r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["access_token"]
print("[登录] admin（总经理办公室 / 管理层）")

answer = ""
meta = {}
t0 = time.time()
with c.stream(
    "POST", f"{BASE}/api/chat/stream",
    json={"question": "高管年薪由哪几部分构成", "session_id": None},
    headers={"Authorization": f"Bearer {token}"},
) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "chunk":
            answer += ev.get("content", "")
        elif ev.get("type") == "meta":
            meta = ev

print(f"[总耗时] {time.time() - t0:.2f}s | [引用] {len(meta.get('cited_chunks', []))} | [拦截] {meta.get('blocked_count', 0)} 篇")
for i, ch in enumerate(meta.get("cited_chunks", []), 1):
    print(f"  片段{i}: {ch['doc_id']} / {ch['heading'][:30]}")
print(f"[被拦截文档] {meta.get('blocked_doc_ids', [])}")
print()
print("[回答]", answer[:400])
c.close()
