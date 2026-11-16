# -*- coding: utf-8 -*-
"""一键总校验：把项目全部可机器复算的主张串成一条命令，输出一页核验报告。

    python tools/verify_all.py            # 全量（需要本机 9000 端口的服务，脚本自启自停）
    python tools/verify_all.py --offline  # 只跑不依赖服务的部分

设计原则（防假绿）：
1. **退出码单独不可信**。部分脚本恒返回 0（如 api_test），因此每项都必须
   再匹配一条"判定行"才算通过；找不到判定行一律记 UNKNOWN→FAIL，不默认通过。
2. **失败即非零退出**，便于接入 CI 或答辩现场演示。
3. 依赖公网实例的测试标记为 SKIPPED 并写明原因，**绝不当作通过**。
4. **运行环境本身会污染结果**。2026-11-16 实测：从带 `NO_PROXY=...,[::1],::1` 的
   shell 启动服务时，httpx 0.28.1 解析该条目即在构造客户端时抛
   `InvalidURL: Invalid port: ':1]'`，`/api/chat` 的 LLM 调用全部失败——报告里的
   FAIL 测的是执行环境，不是被测代码。从这类 shell 跑之前先清掉代理变量：
   `env -u NO_PROXY -u HTTP_PROXY -u HTTPS_PROXY .venv/Scripts/python.exe tools/verify_all.py`
   （Windows cmd 用 `set NO_PROXY=`）。判断依据：`tests/_verify_all_server.log`
   里若出现 `InvalidURL`，先怀疑环境，再怀疑代码。
"""
import argparse
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

# Windows 控制台默认 GBK，中文与部分符号会直接抛 UnicodeEncodeError 把整个流程打断
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORT = 9000
URL = f"http://127.0.0.1:{PORT}"
REPORT_MD = os.path.join(BASE, "docs", "核验报告.md")
REPORT_JSON = os.path.join(BASE, "tests", "verify_all.json")


def verdict(text, pass_re, fail_re):
    """返回 'PASS' / 'FAIL' / 'UNKNOWN'。判定行缺失即为 UNKNOWN。

    用 MULTILINE：unittest 的结论行是独立一行的 "OK"，不加 MULTILINE 会漏判。
    """
    if re.search(fail_re, text, re.MULTILINE):
        return "FAIL"
    if re.search(pass_re, text, re.MULTILINE):
        return "PASS"
    return "UNKNOWN"


# 统一的"通过"判定形态：RESULT: PASS / ALL PASS / RESULT: n/m PASS / n/m PASS / unittest OK
PASS_ANY = r"RESULT: PASS|ALL PASS|RESULT: (\d+)/\1 PASS|\b\d+/\d+ PASS|^OK$"

# name, argv, needs_server, pass_re, fail_re
CHECKS = [
    ("引用逐字契约（片段 vs 源文本逐字比对）",
     [PY, "tools/verify_verbatim.py"], False,
     r"0 处不一致|不一致: 0", r"不一致: [1-9]\d*|不一致 \d*[1-9]"),
    ("时效降权与鉴权单元用例（unittest）",
     [PY, "-m", "unittest", "tests.validity_test", "tests.track_stats_auth_test"], False,
     r"^OK$|Ran \d+ tests.*OK", r"FAILED|ERROR:"),
    ("库内题检索回归（14 题阈值）",
     [PY, "tests/qa_regression.py"], False,
     r"RESULT: PASS", r"RESULT: FAIL"),
    ("混合检索零回归（HYBRID on/off 对比）",
     [PY, "tests/iter4_hybrid_test.py"], False,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
    ("迭代2 API 契约（时效列/逐字快照/chat 事件序列）",
     [PY, "tests/iter2_api_test.py"], True,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
    ("迭代1 冒烟（SSE 事件序列与降级）",
     [PY, "tests/iter1_smoke.py"], True,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
    ("迭代2 冒烟（多轮/历史/限流）",
     [PY, "tests/iter2_smoke.py"], True,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
    ("迭代3 口语改写（两阶段检索）",
     [PY, "tests/iter3_rewrite_test.py"], True,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
    ("迭代5 角色化（契约不变性 15 项）",
     [PY, "tests/iter5_role_test.py"], True,
     PASS_ANY, r"RESULT: FAIL|^FAIL "),
]

SKIPPED = [
    ("线上实例全量验收（online_v3_test）",
     "本项需要可访问公网实例的环境才能真实覆盖（BASE 读环境变量 JIANAN_EVAL_BASE；"
     "按 2026-10-22 的决定，默认值不跟随实例迁移改代码，因此脚本默认值 "
     "http://47.109.98.111:9000 指向的是那台**旧实例**，仅作回滚用；"
     "现行实例为 http://8.137.188.115:9000，跑线上验收必须显式设置环境变量）。"
     "本机核验不探测公网、不产生真实模型费用，故列 SKIPPED 而非 PASS。"
     "**未验证不等于通过**。转为真实覆盖：在可访问实例的环境执行 "
     "`set JIANAN_EVAL_BASE=http://8.137.188.115:9000 && python tests/online_v3_test.py`，"
     "该项约 15 次 /api/chat 会产生真实模型费用与埋点计数。"),
    ("早期接口查看脚本（api_test）",
     "该脚本为 CASE 1-4 的原始 print 输出、**没有判定行**，无法机器判定通过与否。"
     "其断言已被「迭代2 API 契约」覆盖，故不计入本报告的通过/失败统计；"
     "需要人工查看原始响应时单独运行。"),
]


def port_open(p):
    s = socket.socket()
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def start_server():
    log = open(os.path.join(BASE, "tests", "_verify_all_server.log"), "wb")
    proc = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app",
                             "--host", "127.0.0.1", "--port", str(PORT)],
                            cwd=BASE, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            with urllib.request.urlopen(URL + "/api/health", timeout=3) as r:
                if r.status == 200:
                    return proc, json.loads(r.read().decode())
        except Exception:
            time.sleep(1)
    proc.terminate()
    return None, None


def stop_server(proc):
    if not proc:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE,
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_one(name, argv, pass_re, fail_re, timeout=600):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")  # 子进程默认跟随控制台 GBK，会乱码
    try:
        p = subprocess.run(argv, cwd=BASE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        text = (p.stdout or "") + (p.stderr or "")
        v = verdict(text, pass_re, fail_re)
        if p.returncode != 0 and v == "PASS":
            v = "FAIL"  # 判定行为正但退出码非零 → 以失败论，不自我豁免
        return v, p.returncode, text
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1, f"执行超过 {timeout} 秒"
    except Exception as exc:
        return "ERROR", -1, f"{type(exc).__name__}: {exc}"


STALE_HINT = "缺少 persistent 字段 → 该实例跑的是改动前的旧代码"


def probe_running():
    """确认 9000 上的服务是当前代码，而不是历史遗留实例。

    复用陌生实例会让所有断言在旧行为上"通过"或"失败"，结论完全失真。
    """
    try:
        with urllib.request.urlopen(URL + "/api/track/stats", timeout=5) as r:
            body = json.loads(r.read().decode())
        if "persistent" not in body:
            return None, STALE_HINT
        with urllib.request.urlopen(URL + "/api/health", timeout=5) as r:
            return json.loads(r.read().decode()), None
    except Exception as exc:
        return None, f"9000 端口有监听但接口不可用：{type(exc).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    rows = []
    proc = None
    health = None
    stale_reason = None
    if not args.offline and any(c[2] for c in CHECKS):
        if port_open(PORT):
            health, stale_reason = probe_running()
            if health:
                print(f"[info] 复用已在运行且代码版本一致的服务 :{PORT}")
        else:
            proc, health = start_server()
            if proc is None:
                stale_reason = "uvicorn 在 60 秒内未就绪"
                rows.append(("服务启动（uvicorn :9000）", "ERROR", -1, stale_reason))
        if stale_reason:
            print(f"[warn] {stale_reason}；依赖服务的检查将标记为 ERROR 而非静默跳过")

    for name, argv, needs_server, _p, _f in CHECKS:
        if needs_server:
            if args.offline:
                rows.append((name, "SKIPPED", None, "--offline 模式未启动服务，未执行（不等于通过）"))
                continue
            if health is None or stale_reason:
                rows.append((name, "ERROR", None,
                             stale_reason or "无可用服务实例，未执行（不等于通过）"))
                continue
        v, rc, text = run_one(name, argv, _p, _f)
        detail = ""
        m = re.search(r"(不一致: \d+|RESULT: [^\n]{0,90}|Ran \d+ tests[^\n]*|\d+/\d+ PASS)", text)
        if m:
            detail = m.group(0).strip()
        if v == "UNKNOWN":
            detail = detail or (text.strip().splitlines() or ["未找到判定行（退出码单独不可信，按失败处理）"])[-1][:160]
            v = "FAIL"
        if v in ("ERROR", "TIMEOUT"):
            detail = (text or "").strip().replace("\n", " ")[:220] or "无输出"
        # 缺开发依赖 ≠ 产品缺陷：判为 SKIPPED 并给出可操作的安装指令，
        # 否则会把这个环境差异误报成作品有问题（已在全新 lock 环境中实测到）。
        if v == "FAIL":
            m = re.search(r"No module named '([A-Za-z0-9_.]+)'", text)
            if m:
                v = "SKIPPED"
                detail = ("缺少开发依赖 `%s`；执行 `python -m pip install -r requirements-dev.txt` "
                          "后重跑本项" % m.group(1))
        # 未配模型 Key 同样不等于产品缺陷：迭代3「口语改写」要求 LLM 可用，
        # app/main.py 的判断是 `... and config.llm_configured()`，无 Key 时改写分支根本不进入，
        # 口语题必然打不中预期文档。2026-10-21 异机核验在无 Key 环境实测到 RESULT: 3/8 PASS，
        # 且每例先打印"管理员尚未配置模型服务"。按 SKIPPED 记并写清恢复条件，不记成 FAIL。
        if v == "FAIL" and ("管理员尚未配置模型服务" in text or "llm_configured" in text):
            v = "SKIPPED"
            detail = ("本项需要可用的模型服务（.env 里的 LLM_API_KEY）：未配置时系统按设计不进入"
                      "口语改写分支，必然不命中预期文档。配上任意 OpenAI 兼容 Key 后重跑本项。")
        rows.append((name, v, rc, detail))
        print(f"  {v:8s} {name}  {detail}")

    stop_server(proc)

    for name, why in SKIPPED:
        rows.append((name, "SKIPPED", None, why))
        print(f"  SKIPPED  {name}")

    passed = sum(1 for r in rows if r[1] == "PASS")
    failed = sum(1 for r in rows if r[1] in ("FAIL", "ERROR", "TIMEOUT"))
    skipped = sum(1 for r in rows if r[1] == "SKIPPED")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    head = git_head()

    meta = {}
    try:
        vc = json.load(open(os.path.join(BASE, "tests", "verbatim_check.json"), encoding="utf-8"))
        meta["verbatim"] = f"{vc['verbatim_ok']}/{vc['total']} 逐字命中，不一致 {vc['mismatch']}"
        meta["strict"] = vc["strict"]
        meta["collapsed"] = vc["collapsed_ws"]
    except Exception:
        meta["verbatim"] = "未生成"
    snap = os.path.join(BASE, "tests", "chunks_snapshot.json")
    if os.path.exists(snap):
        s = json.load(open(snap, encoding="utf-8"))
        meta["chunks"] = f"{s['n_chunks']} 片段，chunks_hash {s['chunks_hash'][:16]}…"
    if health:
        meta["health"] = json.dumps(health, ensure_ascii=False)

    lines = [
        "# 核验报告（一键复现）",
        "",
        f"- 生成时间：{stamp}",
        f"- 代码版本：`{head}`",
        f"- 复现命令：`python tools/verify_all.py`（本报告由该命令自动生成，非手工整理）",
        f"- 结果：**{passed} PASS / {failed} FAIL / {skipped} SKIPPED**",
        "",
    ]
    if meta.get("chunks"):
        lines.append(f"- 索引基线：{meta['chunks']}")
    if meta.get("verbatim"):
        lines.append(f"- 引用逐字契约：{meta['verbatim']}"
                     + (f"（完全原样 {meta.get('strict')} 条 + 折叠空白对齐 {meta.get('collapsed')} 条）"
                        if meta.get('strict') is not None else ""))
    if meta.get("health"):
        lines.append(f"- 服务健康检查：`{meta['health']}`")
    lines += ["", "| 检查项 | 结论 | 退出码 | 关键数字 / 说明 |", "|---|---|---|---|"]
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIPPED": "⏭ SKIPPED",
            "ERROR": "❌ ERROR", "TIMEOUT": "⏱ TIMEOUT"}
    for name, v, rc, detail in rows:
        lines.append(f"| {name} | {icon.get(v, v)} | {rc if rc is not None else '—'} | {detail} |")
    lines += ["", "## 阅读须知", "",
              "1. **退出码单独不可信**：本项目部分脚本恒返回 0。因此每项除退出码外还须匹配到"
              "一条判定行才计为通过；找不到判定行记为 FAIL 而非 PASS——宁可误报也不默认放行。",
              "2. SKIPPED **不等于通过**。表中已逐条写明未执行的原因，未执行项一律不计入通过。",
              "3. 本报告只覆盖「可机器复算的主张」。应用成效类主张（试用数据、专家抽检）"
              "不在本报告范围内，另见参赛材料《建安 agent 试用数据采集规程》"
              "（该文档在竞赛材料目录，不在本仓库内）。", ""]

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "git_head": head,
                   "summary": {"pass": passed, "fail": failed, "skipped": skipped},
                   "meta": meta,
                   "checks": [{"name": n, "verdict": v, "exit": rc, "detail": d}
                              for n, v, rc, d in rows]}, f, ensure_ascii=False, indent=1)

    print(f"\n汇总：{passed} PASS / {failed} FAIL / {skipped} SKIPPED  → {os.path.relpath(REPORT_MD, BASE)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
