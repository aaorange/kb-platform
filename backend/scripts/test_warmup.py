# -*- coding: utf-8 -*-
"""验证冷启动优化：服务秒起 + 模型后台预热 + 首问无冷启动"""
import json
import time
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=300)

# 1. 服务启动响应性（模型还在后台加载）
t0 = time.time()
while True:
    try:
        r = c.get(f"{BASE}/api/health", timeout=2)
        break
    except Exception:
        time.sleep(0.5)
boot_time = time.time() - t0
print(f"服务响应时间: {boot_time:.1f}s（应为 1~3s，不含模型加载）")
print(f"健康检查: {r.json()}")

# 2. 等模型预热完成
print("\n等待模型后台预热...")
start = time.time()
while True:
    h = c.get(f"{BASE}/api/health").json()
    if h.get("model_ready"):
        break
    if time.time() - start > 180:
        print("预热超时（180s）")
        raise SystemExit(1)
    time.sleep(2)
print(f"模型预热完成，总耗时 {time.time() - start:.1f}s")

# 3. 首问延迟（应无冷启动，约 5s 级别）
r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

print("\n首问测试：差旅报销标准是什么？")
t1 = time.time()
answer, meta = "", {}
with c.stream("POST", f"{BASE}/api/chat/stream",
              json={"question": "差旅报销标准是什么", "session_id": None}, headers=H) as resp:
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
total = time.time() - t1
print(f"首问总耗时: {total:.1f}s（优化前 58s+）")
print(f"命中 {len(meta.get('cited_chunks', []))} 个片段")
print(f"回答开头: {answer[:80]}")
c.close()
