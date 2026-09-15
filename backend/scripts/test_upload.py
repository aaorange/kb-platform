# -*- coding: utf-8 -*-
"""端到端测试：上传文档 → 列表出现 → 提问命中 → 权限隔离验证"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)

# 1. admin 登录
r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
admin_token = r.json()["access_token"]
H = {"Authorization": f"Bearer {admin_token}"}
print("[1] admin 登录成功")

# 2. 上传文档（研发部部门可见 + 管理层角色可见）
with open("test_data/远程办公管理制度.md", "rb") as f:
    r = c.post(
        f"{BASE}/api/knowledge/upload",
        files={"file": ("远程办公管理制度.md", f, "text/markdown")},
        data={
            "title": "远程办公管理制度",
            "category": "HR",
            "permissions": json.dumps([
                {"scope_type": "department", "scope_value": "研发部"},
                {"scope_type": "role", "scope_value": "管理层"},
            ]),
        },
        headers=H,
    )
print("[2] 上传:", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:300])
doc_id = r.json()["unit"]["doc_id"]
t_up = r.elapsed.total_seconds()
print(f"    上传耗时 {t_up:.1f}s（含 bge-m3 向量化）")

# 3. 列表出现
r = c.get(f"{BASE}/api/knowledge/units", headers=H)
titles = [(u["doc_id"], u["title"]) for u in r.json()]
found = any(d == doc_id for d, _ in titles)
print(f"[3] 知识列表共 {len(titles)} 份，新文档 {'已出现 ✅' if found else '未出现 ❌'}")

# 4. admin 提问（应命中新文档 —— 通过管理层角色）
def ask(question, token):
    answer, meta = "", {}
    t0 = time.time()
    with c.stream(
        "POST", f"{BASE}/api/chat/stream",
        json={"question": question, "session_id": None},
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
    return answer, meta, time.time() - t0

ans, meta, dt = ask("远程办公每周最多几天？补贴怎么算？", admin_token)
cited_docs = {ch["doc_id"] for ch in meta.get("cited_chunks", [])}
print(f"[4] admin 提问（角色命中）: {dt:.1f}s 引用文档={cited_docs}")
hit = doc_id in cited_docs
print(f"    命中新上传文档：{'✅' if hit else '❌'}")
print(f"    回答片段：{ans[:150]}")

# 5. 研发部张伟提问（应命中 —— 部门权限）
r = c.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "user123"})
zw_token = r.json()["access_token"]
ans2, meta2, dt2 = ask("远程办公期间宽带费能报销多少？", zw_token)
cited2 = {ch["doc_id"] for ch in meta2.get("cited_chunks", [])}
print(f"[5] 研发部张伟提问（部门命中）: {dt2:.1f}s 引用文档={cited2}")
print(f"    命中：{'✅' if doc_id in cited2 else '❌'} | 回答片段：{ans2[:100]}")

# 6. HR 李娜提问（应被拦截 —— 非研发部、非管理层）
r = c.post(f"{BASE}/api/auth/login", json={"username": "lina", "password": "user123"})
ln_token = r.json()["access_token"]
ans3, meta3, dt3 = ask("远程办公每周可以几天？", ln_token)
cited3 = {ch["doc_id"] for ch in meta3.get("cited_chunks", [])}
blocked3 = meta3.get("blocked_doc_ids", [])
print(f"[6] HR 李娜提问（应拦截）: 引用={cited3} 被拦截={blocked3}")
ok3 = doc_id not in cited3 and doc_id in blocked3
print(f"    权限隔离：{'✅ 李娜看不到新文档' if ok3 else '❌ 泄露或未标记'}")

print()
print("=" * 50)
print(f"上传功能 E2E：{'全部通过 ✅' if (r.status_code and found and hit and doc_id in cited2 and ok3) else '存在问题，见上 ❌'}")
c.close()
