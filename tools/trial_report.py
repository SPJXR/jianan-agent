# -*- coding: utf-8 -*-
"""试用数据汇总与交叉校验：把记录表 + 对照计时表 + 服务端埋点合成一份可审计的分析报告。

    python tools/trial_report.py
    python tools/trial_report.py --records docs/试用记录表.csv --timing docs/对照计时表.csv

设计原则（防自证与防假绿）：
1. **每个指标标注来源**：[埋点]=服务端被动计数，[自报]=用户填写记录表，[交叉]=两者比对。
   绝不把自报数据包装成实测。
2. **数据缺失时拒绝出结论**，输出"未采集/样本不足"，不补数、不外推。
3. **交叉校验不通过时显式报警**（含"埋点为 0 说明没真用""一个错误都没有反而可疑"
   "引用点开率过低说明没验证到核心主张"），而不是静默出报告。
4. 示例行（S01，模板里的格式演示）自动排除并说明。
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

if hasattr(sys.stdout, "buffer"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_MD = os.path.join(BASE, "docs", "试用数据分析报告.md")
OUT_JSON = os.path.join(BASE, "tests", "trial_report.json")
EXAMPLE_IDS = {"S01"}          # 模板中的格式演示行，不计入样本
TASKS = (1, 2, 3)


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return round(v[f] + (v[c] - v[f]) * (k - f), 1)


def load_csv(path, key_col="编号"):
    if not os.path.exists(path):
        return None, f"文件不存在：{os.path.basename(path)}"
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f)]
    rows = [r for r in rows if (r.get(key_col) or "").strip()]
    real = [r for r in rows if (r.get(key_col) or "").strip() not in EXAMPLE_IDS]
    return {"all": rows, "real": real, "dropped": len(rows) - len(real)}, "ok"


def load_track(path):
    """埋点计数：优先读 JSON（/api/track/stats?history=1 的导出），否则读 data/track.sqlite。"""
    if path and path.endswith(".json") and os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))
        if "history" in d:
            agg = Counter()
            for day in d["history"]:
                agg.update(day.get("counts", {}))
            return dict(agg), "多日汇总（JSON 导出）"
        return d.get("counts", d), "单日（JSON 导出）"
    db = os.path.join(BASE, "data", "track.sqlite")
    if os.path.exists(db):
        con = sqlite3.connect(db)
        try:
            rows = con.execute("SELECT event, SUM(n) FROM track_counts GROUP BY event").fetchall()
        except sqlite3.Error as exc:
            return None, f"读取 track.sqlite 失败：{exc}"
        finally:
            con.close()
        return {e: int(n or 0) for e, n in rows}, "全量累计（data/track.sqlite）"
    return None, "未提供埋点数据（既无 JSON 导出也无 data/track.sqlite）"


def ratio(a, b):
    return round(a / b * 100, 1) if b else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=os.path.join(BASE, "docs", "试用记录表.csv"))
    ap.add_argument("--timing", default=os.path.join(BASE, "docs", "对照计时表.csv"))
    ap.add_argument("--track", default=os.path.join(BASE, "docs", "track_stats.json"))
    ap.add_argument("--min-n", type=int, default=15, help="低于该样本量只出可行性结论")
    args = ap.parse_args()

    warnings = []
    rec, msg = load_csv(args.records)
    if rec is None:
        warnings.append(f"记录表缺失（{msg}）——激活率、引用可核查率、自报耗时均无法计算")
    tim, tmsg = load_csv(args.timing)
    if tim is None:
        warnings.append(f"对照计时表缺失（{tmsg}）——检索提效对照实验无法计算")
    track, track_src = load_track(args.track)
    if track is None:
        warnings.append(f"埋点数据缺失（{track_src}）——无法做交叉校验，自报数据无从验证")

    out = {}

    # ---------- 来自记录表（自报） ----------
    if rec:
        people = rec["real"]
        n = len(people)
        answered = asked = checkable = 0
        task_times = []
        for r in people:
            for t in TASKS:
                q = (r.get(f"任务{t}问题原文") or "").strip()
                got = (r.get(f"任务{t}是否拿到答案") or "").strip()
                chk = (r.get(f"任务{t}引用是否可核查") or "").strip()
                sec = (r.get(f"任务{t}耗时秒") or "").strip()
                if not q:
                    continue
                asked += 1
                if got in ("是", "y", "Y", "yes"):
                    answered += 1
                if chk in ("是", "y", "Y", "yes"):
                    checkable += 1
                if sec.isdigit():
                    task_times.append(int(sec))
        activated = sum(1 for r in people
                        if any((r.get(f"任务{t}问题原文") or "").strip() for t in TASKS))
        ratings = [int(r["总体评分1-5"]) for r in people
                   if (r.get("总体评分1-5") or "").strip().isdigit()]
        out["records"] = {
            "n_people": n,
            "n_tasks_answered": asked,
            "activated": activated,
            "activation_rate_pct": ratio(activated, n),
            "answer_got_rate_pct": ratio(answered, asked),
            "citation_checkable_rate_pct": ratio(checkable, asked),
            "self_report_time_median_s": pct(task_times, 50),
            "self_report_time_p95_s": pct(task_times, 95),
            "rating_median": pct(ratings, 50) if ratings else None,
            "dropped_example_rows": rec["dropped"],
        }
        if n < args.min_n:
            warnings.append(f"样本量 n={n} < {args.min_n}：只能作为可行性验证（pilot），"
                            "不得写成效果结论，报告中已按此定性")

    # ---------- 来自对照计时表 ----------
    if tim and tim["real"]:
        groups = {}
        for r in tim["real"]:
            cond = (r.get("条件") or "").strip()
            sec = (r.get("耗时秒") or "").strip()
            ok = (r.get("是否找对") or "").strip()
            if not cond:
                continue
            g = groups.setdefault(cond, {"times": [], "ok": 0, "n": 0})
            g["n"] += 1
            if ok in ("是", "y", "Y"):
                g["ok"] += 1
            if sec.replace(".", "", 1).isdigit():
                g["times"].append(float(sec))
        out["paired_timing"] = {
            c: {"n": g["n"], "找对率%": ratio(g["ok"], g["n"]),
                "中位耗时s": pct(g["times"], 50), "P95耗时s": pct(g["times"], 95)}
            for c, g in groups.items()}
        if len(groups) < 2:
            warnings.append("对照计时表只有一个条件的数据，无法构成对照")
    elif tim:
        warnings.append("对照计时表只有表头/模板行，无实测数据")

    # ---------- 埋点与交叉校验 ----------
    checks = []
    if track:
        out["track_source"] = track_src
        out["track_counts"] = dict(sorted(track.items()))
        qs = track.get("question_sent", 0)
        fq = track.get("first_question_sent", 0)
        fac = track.get("first_answer_with_citation", 0)
        af = track.get("answer_failed", 0) + track.get("error_occurred", 0)
        co = track.get("citation_opened", 0)
        out["track_derived"] = {
            "交付率%（埋点：first_answer_with_citation/first_question_sent）": ratio(fac, fq),
            "引用点开率%（埋点：citation_opened/question_sent）": ratio(co, qs),
        }
        # 校验 1：埋点提问数 vs 记录表任务数
        if rec:
            expect = out["records"]["n_tasks_answered"]
            checks.append(("埋点提问数与记录表任务数是否吻合",
                           f"question_sent={qs} vs 记录表={expect}",
                           "差很多 → 有人只填表没真用，需剔除该样本" if abs(qs - expect) > max(3, expect * 0.2) else "吻合"))
        # 校验 2：零错误反而可疑
        checks.append(("埋点中是否存在失败样本",
                       f"answer_failed+error_occurred={af}",
                       "为 0 反而可疑：说明样本没真用过或埋点未生效" if af == 0 else "有失败记录，符合真实使用"))
        # 校验 3：引用点开率
        rate = ratio(co, qs)
        checks.append(("引用点开率是否达到 50%（核心主张是否被验证）",
                       f"{rate}%",
                       "过低 → 用户根本没点引用，本次只验证了'能跑'，未验证'可溯源'"
                       if (rate is None or rate < 50) else "用户在真实核查出处"))
    else:
        checks.append(("埋点交叉校验", "未执行", "缺埋点数据，自报数据无从验证"))

    verdict_fail = [c for c in checks if c[2].startswith(("差很多", "过低", "为 0 反而"))]

    # ---------- 输出 ----------
    lines = ["# 试用数据分析报告", "",
             f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
             "- 生成命令：`python tools/trial_report.py`（本报告由脚本自动汇总，非手工填写）",
             "- 数据来源标注：**[埋点]** 服务端被动计数｜**[自报]** 用户填写记录表｜**[交叉]** 两者比对", ""]
    if out.get("records"):
        lines += ["## 一、记录表指标（自报）", "", "| 指标 | 数值 |", "|---|---|"]
        for k, v in out["records"].items():
            lines.append(f"| {k} | {v if v is not None else '—'} |")
        lines.append("")
    if out.get("paired_timing"):
        lines += ["## 二、检索提效对照（实测计时）", "", "| 条件 | n | 找对率% | 中位耗时s | P95耗时s |", "|---|---|---|---|---|"]
        for c, g in out["paired_timing"].items():
            lines.append(f"| {c} | {g['n']} | {g['找对率%']} | {g['中位耗时s']} | {g['P95耗时s']} |")
        lines.append("")
    if track:
        lines += ["## 三、埋点计数", "", f"来源：{track_src}", "", "| 事件 | 计数 |", "|---|---|"]
        for k, v in out["track_counts"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
        for k, v in out["track_derived"].items():
            lines.append(f"- {k}：**{v}**")
        lines.append("")
    lines += ["## 四、交叉校验", "", "| 校验项 | 观测 | 结论 |", "|---|---|---|"]
    for name, obs, concl in checks:
        lines.append(f"| {name} | {obs} | {concl} |")
    lines.append("")
    if warnings:
        lines += ["## 五、警告与限制", ""]
        lines += [f"- ⚠️ {w}" for w in warnings]
        lines.append("")
    lines += ["## 六、结论口径", "",
              "本报告的任何数字，写入参赛材料时必须同时带上：样本量、采集方式、"
              "以及'金标准/预期由项目方自行标注'与'自报偏差'两项声明。"
              "样本量不足时定性为可行性验证（pilot），不作效果结论。", ""]

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "warnings": warnings, "metrics": out,
                   "cross_checks": [{"name": a, "obs": b, "conclusion": c} for a, b, c in checks],
                   "blocking_warnings": len(verdict_fail)}, f, ensure_ascii=False, indent=1)

    print("\n".join(lines))
    print(f"\n已写入 {os.path.relpath(OUT_MD, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
