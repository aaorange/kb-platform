# -*- coding: utf-8 -*-
"""验证 FAQ 新交互：候选问题点选 + 一键生成答案"""
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)

r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}
print("[0] admin 登录成功")

# 1. 候选问题
r = c.get(f"{BASE}/api/ops/faq-candidates", headers=H)
cands = r.json()
chat_n = sum(1 for x in cands if x["source"] == "chat")
gap_n = sum(1 for x in cands if x["source"] == "gap")
print(f"[1] 候选问题 {len(cands)} 条（问答记录 {chat_n} + 知识缺口 {gap_n}）")
for x in cands[:5]:
    print(f"    [{x['source']}] {x['question']} ×{x['count']}")
ok1 = r.status_code == 200 and len(cands) > 0
print(f"    → {'✅' if ok1 else '❌'}")

# 2. 一键生成答案
q = cands[0]["question"]
r = c.post(f"{BASE}/api/ops/faqs/generate-answer", headers=H, json={"question": q})
d = r.json()
t0 = time.time()
if r.status_code == 200:
    print(f"[2] 生成「{q}」→ 答案 {len(d['answer'])} 字，依据 {d['doc_ids']}")
    print(f"    答案预览：{d['answer'][:120]}...")
    ok2 = len(d["answer"]) > 50
else:
    print(f"[2] 生成失败：{r.json()}")
    ok2 = False
print(f"    → {'✅' if ok2 else '❌'}")

# 3. 保存 FAQ（带 doc_ids）
r = c.post(f"{BASE}/api/ops/faqs", headers=H,
           json={"question": q, "answer": d.get("answer", "测试答案"), "doc_ids": d.get("doc_ids", [])})
ok3 = r.status_code == 200
print(f"[3] 保存 FAQ：id={r.json().get('id')} → {'✅' if ok3 else '❌'}")

print("\n总评：", "全部通过 ✅" if (ok1 and ok2 and ok3) else "存在问题 ❌")
c.close()
