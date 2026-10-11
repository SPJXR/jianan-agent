# -*- coding: utf-8 -*-
"""R2 评测 vs v5.1 基线题级对比（防御式字段访问）。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

new = {r["id"]: r for r in json.load(
    open("docs/eval/results/eval_local-r2_20261002.json", encoding="utf-8"))["rows"]}
old = {r["id"]: r for r in json.load(
    open("docs/eval/results/eval_local-v51_20260925.json", encoding="utf-8"))["rows"]}


def g(r, k, d=None):
    return r.get(k, d)


def okv(r):
    if "ok" in r:
        return r["ok"]
    return bool(r.get("ret_hit")) and (r.get("ans_cov", 0) or 0) >= 1 and r.get("citation")


print("== R2 全部未达标题（fact）==")
for r in new.values():
    if g(r, "type") == "fact" and not g(r, "ok"):
        o = old.get(r["id"], {})
        print(f"{r['id']}: ret={g(r,'ret_hit')} ctx={g(r,'ctx_cov',0):.2f} "
              f"ans={g(r,'ans_cov',0):.2f} cite={g(r,'citation')} top3={g(r,'top3')}")
        print(f"   miss={g(r,'miss_kw')}")
        print(f"   v51: ok={okv(o) if o else '-'} ctx={g(o,'ctx_cov',0):.2f} "
              f"ans={g(o,'ans_cov',0):.2f} cite={g(o,'citation')}")
        print(f"   ans: {g(r,'answer','')[:80]}")

print()
print("== v5.1 未过但 R2 修复 ==")
for r in new.values():
    o = old.get(r["id"], {})
    if g(r, "type") == "fact" and g(r, "ok") and o and not okv(o):
        print(f"{r['id']}: ctx {g(o,'ctx_cov',0):.2f}->{g(r,'ctx_cov',0):.2f} "
              f"ans {g(o,'ans_cov',0):.2f}->{g(r,'ans_cov',0):.2f}")

print()
print("== v5.1 过但 R2 劣化 ==")
for r in new.values():
    o = old.get(r["id"], {})
    if g(r, "type") == "fact" and (not g(r, "ok")) and o and okv(o):
        print(f"{r['id']}: ctx {g(o,'ctx_cov',0):.2f}->{g(r,'ctx_cov',0):.2f} "
              f"ans {g(o,'ans_cov',0):.2f}->{g(r,'ans_cov',0):.2f} "
              f"cite {g(o,'citation')}->{g(r,'citation')} miss={g(r,'miss_kw')}")

print()
print("== 两版都未过（存量）==")
for r in new.values():
    o = old.get(r["id"], {})
    if g(r, "type") == "fact" and (not g(r, "ok")) and o and not okv(o):
        print(f"{r['id']}: R2 ret={g(r,'ret_hit')} ctx={g(r,'ctx_cov',0):.2f} "
              f"ans={g(r,'ans_cov',0):.2f} cite={g(r,'citation')} | "
              f"v51 ret={g(o,'ret_hit')} ctx={g(o,'ctx_cov',0):.2f} ans={g(o,'ans_cov',0):.2f}")
