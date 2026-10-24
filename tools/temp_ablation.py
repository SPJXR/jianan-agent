# -*- coding: utf-8 -*-
"""B-2 温度消融驱动：同一代码基线，LLM_TEMPERATURE ∈ {0, 0.1, 0.2, 0.3} 各跑一次
62 题全量评测（run_eval），产出 4 份结果 JSON 供对比定标。

用法（后台跑，约 40~60 分钟）：
    .venv/Scripts/python.exe tools/temp_ablation.py

防呆（2026-10-24 首跑踩坑后加固）：
- netstat 输出按字节读再 replace 解码（中文 Windows 控制台是 GBK，text=True 会抛异常）
- 每个温度启动前轮询等待 9000 端口真正释放（TIME_WAIT 也不放过）
- health 200 之外还校验本驱动拉起的子进程存活——防止误把旧服务当新温度
    （首跑 temp=0 就因端口未释放 + bind 失败，把 0.2 旧服务错当 temp=0 评测）
- 消融期间禁止修改 app/ 与 tools/run_eval.py（保证 4 组样本同口径）
"""
import io
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORT = 9000
TEMPS = ["0", "0.1", "0.2", "0.3"]
SLEEP_BETWEEN = 120  # 等限流桶清空 + 规避 DeepSeek 服务端瞬时故障串


def _port_pids() -> list[str]:
    """占用 PORT 的监听进程 PID 列表（字节读 + replace 解码，防 GBK 崩溃）"""
    r = subprocess.run(["netstat", "-ano"], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    pids = []
    for ln in out.splitlines():
        if f":{PORT}" in ln and "LISTENING" in ln:
            parts = ln.split()
            if parts:
                pids.append(parts[-1])
    return pids


def stop_server(timeout=30):
    """杀掉 9000 监听进程并等待端口真正释放"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        pids = _port_pids()
        if not pids:
            return True
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        time.sleep(1.5)
    return not _port_pids()


def start_server(temp: str):
    env = dict(os.environ)
    env["LLM_TEMPERATURE"] = temp
    log = open(os.path.join(BASE, "kb", f"server_temp_{temp}.log"), "w", encoding="utf-8")
    return subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=BASE, env=env, stdout=log, stderr=subprocess.STDOUT)


def wait_health(proc, timeout=90):
    """health 200 且子进程仍存活才算就绪（防误读旧服务）"""
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False  # 子进程已退出（典型：端口被占 bind 失败）
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1.5)
    return False


def main():
    print(f"温度消融开始：{TEMPS}，每温度 62 题", flush=True)
    for t in TEMPS:
        if not stop_server():
            print(f"[temp={t}] 端口 {PORT} 无法释放，中止", flush=True)
            return 1
        time.sleep(2)
        proc = start_server(t)
        try:
            if not wait_health(proc):
                print(f"[temp={t}] 服务启动失败（见 kb/server_temp_{t}.log），中止", flush=True)
                return 1
            print(f"[temp={t}] 服务就绪（pid={proc.pid}），开始 62 题评测", flush=True)
            r = subprocess.run(
                [PY, os.path.join(BASE, "tools", "run_eval.py"),
                 "--base", f"http://127.0.0.1:{PORT}",
                 "--tag", f"temp-{t}", "--sleep", "5"],
                cwd=BASE, capture_output=True)
            out = r.stdout.decode("utf-8", "replace")
            tail = out.strip().splitlines()
            for ln in tail[-12:]:
                print(f"  [temp={t}] {ln}", flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        time.sleep(SLEEP_BETWEEN)
    stop_server()
    time.sleep(2)
    proc = start_server("0.2")
    ok = wait_health(proc)
    print(f"消融结束，恢复默认服务 temp=0.2：{'ok' if ok else 'FAILED'}（pid={proc.pid}）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
