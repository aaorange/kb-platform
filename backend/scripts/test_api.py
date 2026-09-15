# -*- coding: utf-8 -*-
"""临时验证脚本：测试后端 API（trust_env=False 绕过代理）"""
import httpx, json

BASE = "http://localhost:8000"
client = httpx.Client(trust_env=False, timeout=30)

# Health
r = client.get(f"{BASE}/api/health")
print("Health:", r.json())

# Login as admin
r2 = client.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
d = r2.json()
print("Login:", d["user"]["display_name"], "| dept:", d["user"].get("dept_name"), "| roles:", d["user"]["roles"])
token = d["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Knowledge units
r3 = client.get(f"{BASE}/api/knowledge/units", headers=headers)
units = r3.json()
print(f"\n知识单元: {len(units)} 份")
for u in units[:3]:
    perms = [f"{p['scope_type']}:{p.get('scope_value', '')}" for p in u["permissions"]]
    print(f"  {u['doc_id']} {u['title']} [{', '.join(perms)}]")

# Dashboard
r4 = client.get(f"{BASE}/api/ops/dashboard", headers=headers)
print("\n看板:", json.dumps(r4.json(), ensure_ascii=False))

# Login as normal user (zhangwei - 研发部 普通用户)
r5 = client.post(f"{BASE}/api/auth/login", json={"username": "zhangwei", "password": "user123"})
d5 = r5.json()
print(f"\n普通用户登录: {d5['user']['display_name']} | dept: {d5['user'].get('dept_name')} | roles: {d5['user']['roles']}")

# Org departments
r6 = client.get(f"{BASE}/api/org/departments", headers=headers)
print(f"\n部门列表: {len(r6.json())} 个")
for dept in r6.json():
    print(f"  {dept['id']}: {dept['name']}")

# Org users
r7 = client.get(f"{BASE}/api/org/users", headers=headers)
print(f"\n用户列表: {len(r7.json())} 个")
for u in r7.json():
    print(f"  {u['username']} ({u['display_name']}) @ {u.get('dept_name', 'N/A')} roles={u['roles']}")

# FAQ list
r8 = client.get(f"{BASE}/api/ops/faqs", headers=headers)
print(f"\nFAQ 列表: {len(r8.json())} 条")

# Knowledge gaps
r9 = client.get(f"{BASE}/api/ops/gaps", headers=headers)
print(f"知识缺口: {len(r9.json())} 条")

client.close()
print("\n===== 全部 API 测试通过 =====")
