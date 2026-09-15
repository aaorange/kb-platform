# -*- coding: utf-8 -*-
"""验证：lina（HR部门）问同样的问题能答上"""
import json
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)


def ask(headers, question):
    answer, meta = "", {}
    with c.stream("POST", f"{BASE}/api/chat/stream",
                  json={"question": question, "session_id": None}, headers=headers) as resp:
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
    return answer, meta


# lina = 人力资源部 HR专员
r = c.post(f"{BASE}/api/auth/login", json={"username": "lina", "password": "user123"})
HL = {"Authorization": f"Bearer {r.json()['access_token']}"}
print("[lina · 人力资源部] 提问：上班迟到15分钟怎么办\n")
ans, meta = ask(HL, "上班迟到15分钟怎么办")
print(ans[:600])
print(f"\n引用：{[x['chunk_id'] for x in meta.get('cited_chunks', [])]}")
print(f"被拦截文档数：{meta.get('blocked_count')}")
c.close()
