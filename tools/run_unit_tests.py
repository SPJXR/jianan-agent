# -*- coding: utf-8 -*-
"""官方测试入口（2026-11-15）：只跑纯离线单元守卫，每个模块独立进程。

背景：`unittest discover -s tests` 会把 tests/ 下 40+ 个历史 POC、联网 API
脚本与诊断脚本一起 import；其中若干脚本在模块顶层做了
`sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，会关闭底层流并
连锁污染后续模块（12 个 "I/O operation on closed file" 假错误）。
这些脚本是只读归档性质的中间产物，不为发布而改；本入口用**白名单 +
独立子进程**给出可机判的健康门，避免任何模块间流污染。

用法：.venv/Scripts/python.exe tools/run_unit_tests.py
"""
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

GUARDS = [
    ("tests.feedback_ledger_test", "台账/引用/句级统计"),
    ("tests.abstention_audit_test", "弃答路径审计"),
    ("tests.pos_bucket_test", "位置分桶"),
    ("tests.validity_ctx_test", "时效标注契约"),
    ("tests.adjacent_ctx_test", "相邻注入契约"),
]


def main():
    total, failed = 0, 0
    for name, label in GUARDS:
        r = subprocess.run([sys.executable, "-m", "unittest", name],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"Ran (\d+) test", out)
        n = int(m.group(1)) if m else 0
        total += n
        ok = r.returncode == 0
        failed += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<18} {name}  ({n} 用例)")
        if not ok:
            print("        " + out.strip().splitlines()[-1][:120])
    print(f"\n守卫模块 {len(GUARDS)} 个 | 用例 {total} | 失败模块 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
