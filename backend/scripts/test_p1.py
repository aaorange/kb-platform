# -*- coding: utf-8 -*-
"""P1 功能 E2E 测试：文档预览 + 用户编辑/禁用 + 问答反馈 + FAQ 自动生成"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)


def login(username, password):
    r = c.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    d = r.json()
    return d["access_token"], {"Authorization": f"Bearer {d['access_token']}"}


def ask(headers, question, sid=None):
    """SSE 问答，返回 (answer, meta, events)"""
    answer, meta, events = "", {}, []
    with c.stream("POST", f"{BASE}/api/chat/stream",
                  json={"question": question, "session_id": sid}, headers=headers) as resp:
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
            elif ev.get("type") in ("meta",):
                meta = ev
    return answer, meta, events


admin_token, H = login("admin", "admin123")
print("[0] admin 登录成功")

# ===== 功能 1：文档在线预览 =====
print("\n===== 功能 1：文档在线预览 =====")
r = c.get(f"{BASE}/api/knowledge/units", headers=H)
units = r.json()
unit = units[0]
r = c.get(f"{BASE}/api/knowledge/units/{unit['id']}/preview", headers=H)
p = r.json()
ok1 = (r.status_code == 200 and p["chunk_count"] > 0 and
       all(k in p["chunks"][0] for k in ("heading", "content")))
print(f"[1.1] admin 预览「{unit['title']}」：{p['chunk_count']} 切片，"
      f"首切片标题={p['chunks'][0]['heading'][:25]} → {'✅' if ok1 else '❌'}")

# 普通用户预览无权限文档 → 403
zw_token, HZW = login("zhangwei", "user123")
hr_unit = next((u for u in units if any(pp["scope_type"] == "department" and "人力" in (pp.get("scope_value") or "")
                                        for pp in u["permissions"])), None)
if hr_unit:
    r = c.get(f"{BASE}/api/knowledge/units/{hr_unit['id']}/preview", headers=HZW)
    ok1b = r.status_code == 403
    print(f"[1.2] zhangwei 预览 HR 专属「{hr_unit['title']}」→ HTTP {r.status_code} "
          f"{'✅ 已拦截' if ok1b else '❌ 未拦截'}")
else:
    ok1b = True
    print("[1.2] 无 HR 部门文档，跳过")

# ===== 功能 2：用户编辑/禁用/重置密码 =====
print("\n===== 功能 2：用户编辑/禁用/重置密码 =====")
r = c.get(f"{BASE}/api/org/users", headers=H)
users = r.json()
zhangwei = next(u for u in users if u["username"] == "zhangwei")
depts = c.get(f"{BASE}/api/org/departments", headers=H).json()
hr_dept = next(d for d in depts if d["name"] == "人力资源部")

# 2.1 改部门到 HR
r = c.patch(f"{BASE}/api/org/users/{zhangwei['id']}", headers=H,
            json={"dept_id": hr_dept["id"]})
ok2 = r.json().get("dept_name") == "人力资源部"
print(f"[2.1] 张伟调岗到人力资源部：{'✅' if ok2 else '❌'}")

# 2.2 HR 部门文档现在能预览（验证权限联动）
r = c.get(f"{BASE}/api/knowledge/units/{hr_unit['id']}/preview", headers=HZW) if hr_unit else None
ok2b = r is not None and r.status_code == 200
print(f"[2.2] 调岗后预览 HR 文档：HTTP {r.status_code if r else '-'} "
      f"{'✅ 权限联动生效' if ok2b else '❌'}")

# 2.3 改回研发部
r = c.get(f"{BASE}/api/org/users", headers=H)
zw_dept = next(u for u in r.json() if u["username"] == "zhangwei")["dept_id"]
r = c.get(f"{BASE}/api/org/users", headers=H)
dev_dept = next(d for d in depts if d["name"] == "研发部")
c.patch(f"{BASE}/api/org/users/{zhangwei['id']}", headers=H, json={"dept_id": dev_dept["id"]})
print("[2.3] 已改回研发部")

# 2.4 禁用用户 → 登录被拒
c.patch(f"{BASE}/api/org/users/{zhangwei['id']}", headers=H, json={"is_active": False})
r = c.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "user123"})
ok2c = r.status_code == 403
print(f"[2.4] 禁用后登录：HTTP {r.status_code}（{r.json().get('detail')}）→ {'✅' if ok2c else '❌'}")

# 2.5 启用回来
c.patch(f"{BASE}/api/org/users/{zhangwei['id']}", headers=H, json={"is_active": True})
r = c.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "user123"})
ok2d = r.status_code == 200
print(f"[2.5] 启用后登录：HTTP {r.status_code} → {'✅' if ok2d else '❌'}")

# 2.6 重置密码
r = c.post(f"{BASE}/api/org/users/{zhangwei['id']}/reset-password", headers=H,
           json={"new_password": "newpass123"})
r = c.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "newpass123"})
ok2e = r.status_code == 200
print(f"[2.6] 重置密码后新密码登录：HTTP {r.status_code} → {'✅' if ok2e else '❌'}")
# 改回原密码，避免影响后续使用
c.post(f"{BASE}/api/org/users/{zhangwei['id']}/reset-password", headers=H,
       json={"new_password": "user123"})

# ===== 功能 3：问答反馈 =====
print("\n===== 功能 3：问答反馈 =====")
_, _, events = ask(H, "年假有多少天？")
log_id = next((e.get("log_id") for e in events if e.get("type") == "log"), None)
ok3 = log_id is not None
print(f"[3.1] SSE 推送 log_id={log_id} → {'✅' if ok3 else '❌'}")

if log_id:
    r = c.post(f"{BASE}/api/chat/logs/{log_id}/feedback", headers=H, json={"value": 1})
    ok3b = r.status_code == 200
    print(f"[3.2] 点赞：{r.json()} → {'✅' if ok3b else '❌'}")

    # 会话历史中带 feedback
    sessions = c.get(f"{BASE}/api/chat/sessions", headers=H).json()
    if sessions:
        msgs = c.get(f"{BASE}/api/chat/sessions/{sessions[0]['id']}/messages", headers=H).json()["messages"]
        fb = next((m["feedback"] for m in msgs if m["id"] == log_id), None)
        ok3c = fb == 1
        print(f"[3.3] 历史记录中的 feedback={fb} → {'✅' if ok3c else '❌'}")
    else:
        ok3c = False
        print("[3.3] 无会话 ❌")

    # 他人会话的日志不可评价
    r = c.post(f"{BASE}/api/chat/logs/{log_id}/feedback", headers=HZW, json={"value": -1})
    ok3d = r.status_code == 404
    print(f"[3.4] zhangwei 评价 admin 的日志：HTTP {r.status_code} → {'✅ 已拦截' if ok3d else '❌'}")

    # 看板反馈统计
    d = c.get(f"{BASE}/api/ops/dashboard", headers=H).json()
    ok3e = d.get("feedback_positive", 0) >= 1
    print(f"[3.5] 看板反馈统计：赞={d.get('feedback_positive')} 踩={d.get('feedback_negative')} → "
          f"{'✅' if ok3e else '❌'}")
else:
    ok3b = ok3c = ok3d = ok3e = False
    print("[3.x] 无 log_id，全部失败")

# ===== 功能 4：FAQ 自动生成 =====
print("\n===== 功能 4：FAQ 自动生成 =====")
r = c.post(f"{BASE}/api/ops/faqs/auto-generate", headers=H, json={"count": 3})
d = r.json()
gen = d.get("generated", [])
print(f"[4.1] 自动生成：{d.get('message')}")
for g in gen:
    print(f"  - 「{g['question']}」(被问 {g['ask_count']} 次，来源 {len(g['doc_ids'])} 篇文档)")
ok4 = r.status_code == 200 and len(gen) >= 1
print(f"    → {'✅' if ok4 else '❌'}")

# 4.2 生成的 FAQ 是草稿状态
faqs = c.get(f"{BASE}/api/ops/faqs", headers=H).json()
drafts = [f for f in faqs if not f["is_published"]]
ok4b = len(drafts) >= 1
print(f"[4.2] 草稿状态 FAQ：{len(drafts)} 条 → {'✅' if ok4b else '❌'}")

# ===== 汇总 =====
print("\n" + "=" * 50)
results = {
    "文档预览": ok1 and ok1b,
    "用户编辑/禁用/重置密码": ok2 and ok2b and ok2c and ok2d and ok2e,
    "问答反馈": ok3 and ok3b and ok3c and ok3d and ok3e,
    "FAQ 自动生成": ok4 and ok4b,
}
all_ok = all(results.values())
for name, ok in results.items():
    print(f"{name}：{'✅' if ok else '❌'}")
print(f"总评：{'全部通过 ✅' if all_ok else '存在问题 ❌'}")
c.close()
