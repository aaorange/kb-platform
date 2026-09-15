# -*- coding: utf-8 -*-
"""测试检索和问答"""
import json
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)

# admin 登录
r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

# 1. 查知识单元列表，确认权限
units = c.get(f"{BASE}/api/knowledge/units", headers=H).json()
hr_units = [u for u in units if "考勤" in u["title"]]
print("=== 考勤制度权限 ===")
for u in hr_units:
    perms = [f"{p['scope_type']}:{p.get('scope_value', '')}" for p in u["permissions"]]
    print(f"{u['doc_id']} {u['title']}: {', '.join(perms)}")

# 2. 预览文档，确认切片存在
for u in hr_units:
    r = c.get(f"{BASE}/api/knowledge/units/{u['id']}/preview", headers=H)
    data = r.json()
    print(f"\n=== {u['doc_id']} 切片数: {data['chunk_count']} ===")
    for chunk in data["chunks"][:3]:
        print(f"  [{chunk['chunk_index']}] {chunk['heading'][:50]}")
        print(f"      {chunk['content'][:80]}...")

# 3. 实际问答
print("\n=== 问答测试 ===")
answer, meta = "", {}
with c.stream("POST", f"{BASE}/api/chat/stream",
              json={"question": "上班迟到15分钟怎么办", "session_id": None}, headers=H) as resp:
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

print(f"回答前 300 字:\n{answer[:300]}")
print(f"\n引用片段:")
for chunk in meta.get("cited_chunks", []):
    print(f"  {chunk['chunk_id']} / {chunk.get('heading', '')}")
print(f"被拦截文档: {meta.get('blocked_count')}")

c.close()
