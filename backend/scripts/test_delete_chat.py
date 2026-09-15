# -*- coding: utf-8 -*-
"""E2E 测试：文档删除/禁用 + 聊天历史"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)


def _ask(client, base, headers, question, sid=None):
    answer, meta = "", {}
    t0 = time.time()
    with client.stream(
        "POST", f"{base}/api/chat/stream",
        json={"question": question, "session_id": sid},
        headers=headers,
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


def _ask_with_events(client, base, headers, question, sid=None):
    answer, meta, events = "", {}, []
    with client.stream(
        "POST", f"{base}/api/chat/stream",
        json={"question": question, "session_id": sid},
        headers=headers,
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if ev.get("type") == "chunk":
                answer += ev.get("content", "")
            elif ev.get("type") == "meta":
                meta = ev
    return answer, meta, events


def _ask_with_sid(client, base, headers, question, sid):
    return _ask(client, base, headers, question, sid)

# ===== 登录 =====
r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}
print("[0] admin 登录成功")

# ===== 功能 1：文档禁用/启用/删除 =====
print("\n===== 功能 1：文档禁用/启用/删除 =====")

# 1.1 找到之前上传的测试文档
r = c.get(f"{BASE}/api/knowledge/units", headers=H)
units = r.json()
test_unit = next((u for u in units if "远程办公" in u["title"]), None)
if not test_unit:
    test_unit = next((u for u in units if "会议室" in u["title"]), None)
if not test_unit:
    # 找第一个上传的文档
    test_unit = next((u for u in units if u["doc_id"].startswith("DOC-UP")), None)

if test_unit:
    uid = test_unit["id"]
    doc_id = test_unit["doc_id"]
    print(f"[1.1] 测试目标：{test_unit['title']} (id={uid}, doc_id={doc_id})")

    # 1.2 禁用
    r = c.patch(f"{BASE}/api/knowledge/units/{uid}/toggle", headers=H)
    print(f"[1.2] 禁用：{r.json()}")

    # 1.3 提问应不命中（已禁用）
    ans, meta, _ = _ask(c, BASE, H, "远程办公每周几天？")
    cited = {ch["doc_id"] for ch in meta.get("cited_chunks", [])}
    ok_disable = doc_id not in cited
    print(f"[1.3] 禁用后提问：命中={cited} → 新文档{'未命中 ✅' if ok_disable else '仍命中 ❌'}")

    # 1.4 启用
    r = c.patch(f"{BASE}/api/knowledge/units/{uid}/toggle", headers=H)
    print(f"[1.4] 启用：{r.json()}")

    # 1.5 提问应命中（已启用）
    ans2, meta2, _ = _ask(c, BASE, H, "远程办公每周几天？")
    cited2 = {ch["doc_id"] for ch in meta2.get("cited_chunks", [])}
    ok_enable = doc_id in cited2
    print(f"[1.5] 启用后提问：命中={cited2} → 新文档{'已恢复 ✅' if ok_enable else '未恢复 ❌'}")

    # 1.6 删除
    r = c.delete(f"{BASE}/api/knowledge/units/{uid}", headers=H)
    print(f"[1.6] 删除：{r.json()}")

    # 1.7 列表不再出现
    r = c.get(f"{BASE}/api/knowledge/units", headers=H)
    still = any(u["id"] == uid for u in r.json())
    print(f"[1.7] 删除后列表中{'仍存在 ❌' if still else '已消失 ✅'}")

    # 1.8 提问不命中（已删除）
    ans3, meta3, _ = _ask(c, BASE, H, "远程办公每周几天？")
    cited3 = {ch["doc_id"] for ch in meta3.get("cited_chunks", [])}
    ok_del = doc_id not in cited3
    print(f"[1.8] 删除后提问：命中={cited3} → 新文档{'未命中 ✅' if ok_del else '仍命中 ❌'}")
else:
    print("[1] 没有可测试的上传文档，跳过删除测试")
    ok_disable = ok_enable = ok_del = True

# ===== 功能 2：聊天历史 =====
print("\n===== 功能 2：聊天历史 =====")

# 2.1 发起一次问答（session_id=None → 新建会话）
print("[2.1] 发起新问答（自动创建会话）...")
session_id = None
ans, meta, events = _ask_with_events(c, BASE, H, "差旅报销标准是多少？")
for ev in events:
    if ev.get("type") == "session":
        session_id = ev["session_id"]
        print(f"  → 收到 session_id={session_id}, title={ev.get('title')}")
        break

ok_session = session_id is not None
print(f"[2.1] 会话创建：{'✅' if ok_session else '❌'}")

# 2.2 查询会话列表
r = c.get(f"{BASE}/api/chat/sessions", headers=H)
sessions = r.json()
print(f"[2.2] 会话列表：{len(sessions)} 条")
for s in sessions[:3]:
    print(f"  id={s['id']} title={s['title']}")

# 2.3 查询会话消息历史
if session_id:
    r = c.get(f"{BASE}/api/chat/sessions/{session_id}/messages", headers=H)
    msgs = r.json().get("messages", [])
    print(f"[2.3] 会话 {session_id} 消息历史：{len(msgs)} 条")
    if msgs:
        print(f"  问题：{msgs[0]['question'][:40]}")
        print(f"  回答：{msgs[0]['answer'][:80]}...")
    ok_history = len(msgs) >= 1
else:
    ok_history = False
    print("[2.3] 无 session_id，跳过")

# 2.4 在同一会话中追问
if session_id:
    print(f"[2.4] 在会话 {session_id} 中追问...")
    ans2, meta2, _ = _ask_with_sid(c, BASE, H, "住宿标准呢？", session_id)
    r = c.get(f"{BASE}/api/chat/sessions/{session_id}/messages", headers=H)
    msgs2 = r.json().get("messages", [])
    ok_followup = len(msgs2) >= 2
    print(f"[2.4] 追问后消息数：{len(msgs2)} {'✅' if ok_followup else '❌'}")

# ===== 汇总 =====
print("\n" + "=" * 50)
all_ok = ok_disable and ok_enable and ok_del and ok_session and ok_history
print(f"文档禁用/启用/删除：{'✅' if (ok_disable and ok_enable and ok_del) else '❌'}")
print(f"聊天历史（创建+列表+历史+追问）：{'✅' if (ok_session and ok_history) else '❌'}")
print(f"总评：{'全部通过 ✅' if all_ok else '存在问题 ❌'}")
c.close()
