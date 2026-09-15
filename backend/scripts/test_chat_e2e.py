# -*- coding: utf-8 -*-
"""端到端验证：登录 → SSE 问答（检索→权限过滤→LLM流式生成）→ 引用溯源"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=180)


def login(username, password):
    r = c.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    d = r.json()
    print(f"[登录] {d['user']['display_name']} @ {d['user']['dept_name']} | 角色: {d['user']['roles']}")
    return d["access_token"]


def ask(token, question):
    """SSE 流式问答，返回 (拼接回答, meta)"""
    answer = ""
    meta = {}
    t0 = time.time()
    with c.stream(
        "POST",
        f"{BASE}/api/chat/stream",
        json={"question": question, "session_id": None},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        buf = ""
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "chunk":
                if not answer:
                    print(f"  [首字延迟] {time.time() - t0:.2f}s")
                answer += ev.get("content", "")
            elif ev.get("type") == "meta":
                meta = ev
    return answer, meta, time.time() - t0


# ===== 场景 1：admin 提问全局知识（应正常回答 + 引用溯源）=====
print("\n===== 场景 1：admin 提问（客服全局文档）=====")
admin_token = login("admin", "admin123")
q1 = "客服退换货政策是什么？7天无理由退货有什么条件？"
answer, meta, elapsed = ask(admin_token, q1)
print(f"  [总耗时] {elapsed:.2f}s | [引用] {len(meta.get('cited_chunks', []))} 个切片 | [拦截] {meta.get('blocked_count', 0)} 篇")
for i, ch in enumerate(meta.get("cited_chunks", []), 1):
    print(f"    片段{i}: {ch['doc_id']} / {ch['heading'][:30]}")
print("  [回答节选]", answer[:200].replace("\n", " "))

# ===== 场景 2：普通用户提问受限知识（应被权限拦截）=====
print("\n===== 场景 2：张伟（研发部普通用户）提问（高管薪酬文档应被拦截）=====")
zw_token = login("zhangwei", "user123")
q2 = "高管的年度绩效奖金是怎么计算的？股权激励的授予条件是什么？"
answer2, meta2, elapsed2 = ask(zw_token, q2)
print(f"  [总耗时] {elapsed2:.2f}s | [引用] {len(meta2.get('cited_chunks', []))} 个切片 | [拦截] {meta2.get('blocked_count', 0)} 篇")
if meta2.get("blocked_doc_ids"):
    print(f"  [被拦截文档] {meta2['blocked_doc_ids']}")
print("  [回答]", answer2[:200].replace("\n", " "))

c.close()
print("\n===== 端到端验证完成 =====")
