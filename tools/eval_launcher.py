# -*- coding: utf-8 -*-
"""评测委托器：以完全脱离的方式启动 run_eval，日志实时落盘（-u 行缓冲）。"""
import os
import subprocess
import sys

WD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(WD, ".venv", "Scripts", "python.exe")
OUT = os.path.join(WD, "docs", "eval", "results")

JOBS = [
    ("run_local", ["tools/run_eval.py", "--base", "http://127.0.0.1:9001",
                   "--tag", "local-v5.1", "--sleep", "3.5"]),
    ("run_online", ["tools/run_eval.py", "--base", "http://8.137.11.193:9000",
                    "--tag", "online-v5", "--sleep", "3.5"]),
]

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

for name, args in JOBS:
    log = open(os.path.join(OUT, name + ".log"), "w", encoding="utf-8")
    subprocess.Popen(
        [PY, "-u"] + args, cwd=WD, stdout=log, stderr=subprocess.STDOUT,
        creationflags=DETACHED, close_fds=False)
    print(f"launched {name}")

print("all launched")
