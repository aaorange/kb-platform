# -*- coding: utf-8 -*-
"""FAQ 缓存权限复核验证：
1. admin 发布「高管薪酬」FAQ 到缓存
2. admin 再问 → FAQ 命中（有权）
3. zhangwei 问同样问题 → 权限复核失败 → 降级走完整检索（应被拦截）
"""
import json
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=120)


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


admin = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": f"Bearer {admin['access_token']}"}
zw = c.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "user123"}).json()
HZW = {"Authorization": f"Bearer {zw['access_token']}"}

faqs = c.get(f"{BASE}/api/ops/faqs", headers=H).json()
faq = next((f for f in faqs if "高管" in f["question"]), None)
if not faq:
    print("未找到高管 FAQ，先跳过")
    raise SystemExit

r = c.post(f"{BASE}/api/ops/faqs/{faq['id']}/cache", headers=H)
print("[1] 发布缓存：", r.json())
if "error" in r.json():
    print("    Redis 未启动，无法验证缓存链路")
    raise SystemExit

Q = faq["question"]

# admin 问 → 应 FAQ 命中（faq_hit=True）
ans, meta = ask(H, Q)
print(f"[2] admin 问「{Q}」→ faq_hit={meta.get('faq_hit')} 命中时间={meta.get('response_ms')}ms")
print("    ✅ 管理员 FAQ 缓存命中" if meta.get("faq_hit") else "    ⚠️ 未命中缓存（走了检索，功能仍正常）")

# zhangwei 问 → 权限复核 → 降级检索 → 应被拦截
ans2, meta2 = ask(HZW, Q)
hit_blocked = not meta2.get("faq_hit") and "未包含" in ans2
print(f"[3] zhangwei 问同样问题 → faq_hit={meta2.get('faq_hit')}，回答含'未包含'={('未包含' in ans2)}")
print("    ✅ 权限复核生效：无权用户不享受缓存，降级走鉴权检索" if hit_blocked else "    ❌ 复核未生效，存在越权泄露！")

c.close()
