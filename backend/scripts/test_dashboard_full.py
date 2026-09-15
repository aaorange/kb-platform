# -*- coding: utf-8 -*-
"""验证 /ops/dashboard/full 端点"""
import json
import httpx

BASE = "http://localhost:8000"
c = httpx.Client(trust_env=False, timeout=60)

r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

import time
time.sleep(5)
r = c.get(f"{BASE}/api/ops/dashboard/full", headers=H)
if r.status_code != 200:
    print(f"HTTP {r.status_code}: {r.text[:500]}")
    raise SystemExit(1)

d = r.json()
print(f"=== 卡片指标 ===")
print(f"PV={d['pv']} UV={d['uv']} 覆盖率={d['coverage_pct']}%(命中{d['hit_questions']}/{d['pv']}) "
      f"满意度={d['satisfaction_pct']}% 文档={d['total_units']} 缺口={d['total_gaps']} "
      f"Token={d['token_total']} 平均响应={d['avg_response_ms']}ms")

print(f"\n=== 30天趋势（最近5天） ===")
for t in d["trend"][-5:]:
    print(f"  {t['date']}: {t['count']} 次 / {t['tokens']} tokens")

print(f"\n=== 分类分布 ===")
for cat in d["category_dist"]:
    print(f"  {cat['name']}: {cat['value']} 次")

print(f"\n=== 文档热度 TOP5 ===")
for doc in d["doc_heat"][:5]:
    print(f"  {doc['title']}: {doc['count']} 次")

print(f"\n=== 高频问题 TOP3 ===")
for q in d["top_questions"][:3]:
    print(f"  {q['question']}: ×{q['count']}")

print(f"\n=== 拦截分析 ===")
print(f"  涉及拦截的提问: {d['blocked']['question_count']} 次")
for doc in d["blocked"]["docs"]:
    print(f"  {doc['title']}: 拦截 {doc['count']} 次")

print(f"\n=== 满意度趋势 ===")
for s in d["satisfaction_trend"]:
    print(f"  {s['date']}: 👍{s['pos']} 👎{s['neg']} 好评率{s['rate']}%")

ok = (d["pv"] > 0 and len(d["trend"]) == 30 and d["coverage_pct"] > 0
      and d["category_dist"] and d["doc_heat"] and d["blocked"]["question_count"] > 0
      and d["satisfaction_trend"])
print(f"\n总评: {'全部模块有数据 ✅' if ok else '部分模块无数据，请检查 ⚠️'}")
c.close()
