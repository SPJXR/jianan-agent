# -*- coding: utf-8 -*-
"""知识库扩充一键流水线（路线图 B-4："产品最扎实的扩展路径"）。

把新增/替换文档后的全链串成一条命令：
    解析文档(extract_docs) → 建库分块(build_kb) → 向量索引(build_vec_index)
    → 护栏回归(qa14 + 混合零回归) → （可选）62 题全量评测

用法（项目根目录）：
    .venv/Scripts/python.exe tools/kb_pipeline.py                # 全链（解析→建库→向量→护栏）
    .venv/Scripts/python.exe tools/kb_pipeline.py --skip-extract # 文档未变，只重建索引
    .venv/Scripts/python.exe tools/kb_pipeline.py --with-eval    # 追加 62 题全量（真实 LLM 调用，
                                                                 #   需先另起服务或指定 --eval-base）

前置约定（新增文档操作手册，见 README「知识库更新」节）：
    1. 文件放入 knowledge_base/docs/，文件名前 4 位为文档编号（如 0077_xxx.pdf）
    2. 在 kb/docs_meta.json 登记 title / category / valid_status / note
    3. 运行本脚本；护栏全绿后才算入库成功
"""
import argparse
import io
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run_step(name: str, argv: list[str], fail_fast=True) -> bool:
    print(f"\n==== [{name}] {' '.join(argv)}", flush=True)
    r = subprocess.run([PY] + argv, cwd=BASE)
    ok = r.returncode == 0
    print(f"---- [{name}] exit={r.returncode} {'OK' if ok else 'FAIL'}")
    if not ok and fail_fast:
        sys.exit(f"流水线中止于 [{name}]。修复后重跑（已完成的步骤可用 --skip-* 跳过）。")
    return ok


def main():
    ap = argparse.ArgumentParser(description="知识库扩充一键流水线")
    ap.add_argument("--skip-extract", action="store_true",
                    help="跳过文档解析（文档未变、kb/text/ 已是最新时）")
    ap.add_argument("--skip-vector", action="store_true",
                    help="跳过向量索引重建（仅改了 .txt 后想快速验证时）")
    ap.add_argument("--with-eval", action="store_true",
                    help="护栏通过后追加 62 题全量评测（真实 LLM 调用）")
    ap.add_argument("--eval-base", default="http://127.0.0.1:9000",
                    help="62 题评测的目标服务地址（默认本机）")
    args = ap.parse_args()

    # 0) 前置自检：docs_meta 登记的编号都有对应文档文件
    import json
    meta = json.load(open(os.path.join(BASE, "kb", "docs_meta.json"), encoding="utf-8"))["docs"]
    docs_dir = os.path.join(BASE, "knowledge_base", "docs")
    files = {f[:4] for f in os.listdir(docs_dir)
             if f.lower().endswith((".doc", ".docx", ".pdf"))}
    unregistered = files - set(meta)
    if unregistered:
        sys.exit(f"发现未登记文档编号：{sorted(unregistered)}\n"
                 f"请先在 kb/docs_meta.json 补充 title/category/valid_status 后重跑。")

    if not args.skip_extract:
        run_step("解析文档", ["tools/extract_docs.py"])  # .doc 需本机 MS Word，扫描件走 Windows OCR
        # OCR 覆写步骤必须紧跟 extract（顺序坑固化，2026-10-24 两次踩坑）：
        # extract 会把 0067/0003/0080 的文本覆盖回空壳/乱码（OCR 来源文档无可用文本层），
        # 漏跑这一步 = 这些文档从索引里静默消失（A9 回归就是这样发生的）。
        run_step("OCR 覆写（0067/0003/0080）", ["tools/ocr_scans.py"])
        run_step("OCR 覆写（0080 切片拼贴）", ["tools/ocr_0080.py"])
    run_step("建库分块", ["tools/build_kb.py"])
    if not args.skip_vector:
        run_step("向量索引", ["tools/build_vec_index.py", "bge-small-zh-v1.5"])
    run_step("护栏：qa14 检索回归", ["tests/qa_regression.py"])
    run_step("护栏：混合检索零回归", ["tests/iter4_hybrid_test.py"])

    if args.with_eval:
        run_step("62 题全量评测", ["tools/run_eval.py", "--base", args.eval_base,
                                    "--tag", "pipeline", "--sleep", "3"])
        print("\n注意：62 题评测打的是运行中的服务——若刚重建索引，请先重启服务再带 --with-eval 重跑本步。")

    print("\n流水线完成：索引与护栏状态一致。下一步：重启线上服务（或 scp kb/ 两个索引文件）使其生效。")


if __name__ == "__main__":
    main()
