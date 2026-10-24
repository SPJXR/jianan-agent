# -*- coding: utf-8 -*-
"""synonyms 模块单元自测"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app import synonyms  # noqa: E402

CASES = [
    # "挖坑底下干活"同时命中长短两个键（长键"挖坑底下干活"+短键"挖坑"），四个目标词都应展开
    ("工地上挖坑底下干活有啥危险要注意的？",
     ["有限空间作业", "基坑作业", "有限空间", "基坑"]),
    ("考特种作业证有年龄限制没？", []),  # "考证"二字不连续出现，不触发（该题本来检索就命中）
    ("密目网着火了怎么办", ["密目式安全网", "防火", "阻燃"]),
    ("有限空间作业前需要检测哪些气体？", []),   # 规范术语不触发映射
    ("", []),
    ("塔吊安装需要什么资质", ["建筑起重机械"]),
]

fail = 0
for q, expect in CASES:
    got = synonyms.expand(q)
    ok = set(got) == set(expect)
    if not ok:
        fail += 1
    print(("PASS" if ok else "FAIL"), repr(q[:16]), "->", got, ("" if ok else f"expect={expect}"))

print("RESULT:", "PASS" if fail == 0 else f"FAIL ({fail})")
sys.exit(0 if fail == 0 else 1)
