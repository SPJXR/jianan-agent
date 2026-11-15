# -*- coding: utf-8 -*-
"""打 v7 服务器部署包（2026-11-15，发布用）。

与历史 v5.2 包的差别：
- KB 414 块 -> 509 块（37 份文档，含 3.3 时效标注所需 valid_status 列）
- 向量索引只带 bge-small（509 块，与 KB 对齐）；**排除 414 块 bge-large 旧索引**
- 新增 app/feedback.py（ADR-011 反馈台账）、3.1/3.3 上下文装配、2.4 兜底修复
- 新增 kb/docs_meta.json、.env.example、requirements.lock、deploy/ 运维工件、
  精选核验工具与 DEPLOY-INFO.txt
- 显式排除：.env（含真实 API Key）、data/、tests/、baselines/、日志、
  __pycache__、旧 KB 备份、large 索引

用法：.venv/Scripts/python.exe tools/make_v7_pkg.py
产出：deploy-pkg/jianan-app-v7-20261115.tar.gz + deploy-pkg/v7-manifest-20261115.txt
"""
import hashlib
import io
import os
import sqlite3
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy-pkg" / "jianan-app-v7-20261115.tar.gz"
MANIFEST = ROOT / "deploy-pkg" / "v7-manifest-20261115.txt"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

MODEL_FILES = [
    "config.json", "model_int8.onnx", "special_tokens_map.json",
    "tokenizer.json", "tokenizer_config.json", "vocab.txt",
    "1_Pooling/config.json",
]
TOOL_FILES = [
    "verify_verbatim.py", "verify_all.py", "run_eval.py",
    "run_unit_tests.py", "kb_pipeline.py", "build_kb.py",
    "build_vec_index.py",
]
EXCLUDE_SUFFIX = (".log", ".pyc", ".tmp", ".bak")
EXCLUDE_NAMES = {".env", "__pycache__", "jianan.db"}


def want(f: Path) -> bool:
    if not f.is_file():
        return False
    parts = set(f.parts)
    if "__pycache__" in parts or ".git" in parts:
        return False
    if f.name in EXCLUDE_NAMES or f.suffix in EXCLUDE_SUFFIX:
        return False
    if f.name.startswith("_") or f.name.startswith("~$"):
        return False
    # 旧 KB 备份 / 旧 large 索引 / 中间构建日志 一律不入包
    if f.name.startswith("kb_") or f.name.startswith("build_log") \
            or f.name.startswith("extract_log") or "bge-large" in f.name:
        return False
    return True


def add(tar: tarfile.TarFile, arc: str, src: Path):
    tar.add(src, arcname=f"jianan-app/{arc}")
    return src.stat().st_size


def precheck():
    """发布硬闸：KB 与要入包的索引必须严格对齐，.env 必须存在但绝不入包。"""
    con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
    ids_db = {r[0] for r in con.execute("select chunk_id from chunks")}
    cols = [r[1] for r in con.execute("pragma table_info(docs)")]
    con.close()
    p = ROOT / "kb" / "vec_index_bge-small-zh-v1.5.npz"
    z = np.load(p, allow_pickle=False)
    ids_vec = {int(i) for i in z["chunk_ids"]}
    assert len(ids_db) == len(ids_vec) == 509 and ids_db == ids_vec, \
        f"KB/向量索引不对齐：db={len(ids_db)} vec={len(ids_vec)}"
    assert "valid_status" in cols, "docs 表缺 valid_status（3.3 时效标注依赖）"
    assert (ROOT / ".env").exists(), "本机 .env 缺失（服务器需单独上传）"
    for f in MODEL_FILES:
        assert (ROOT / "models" / "bge-small-zh-v1.5" / f).exists(), f
    return len(ids_db)


def main():
    n = precheck()
    print(f"[预检] KB/向量索引对齐 {n} 块；valid_status 列就位；模型文件齐")
    OUT.parent.mkdir(exist_ok=True)
    files, total = [], 0
    with tarfile.open(OUT, "w:gz") as tar:
        for d in ("app", "web", "docs", "deploy"):
            for f in sorted((ROOT / d).rglob("*")):
                if want(f):
                    size = add(tar, f.relative_to(ROOT).as_posix(), f)
                    files.append((f.relative_to(ROOT).as_posix(), size))
                    total += size
        for rel in [
            "kb/kb.sqlite", "kb/docs_meta.json",
            "kb/vec_index_bge-small-zh-v1.5.npz",
        ]:
            f = ROOT / rel
            size = add(tar, rel, f)
            files.append((rel, size))
            total += size
        for m in MODEL_FILES:
            rel = f"models/bge-small-zh-v1.5/{m}"
            size = add(tar, rel, ROOT / rel)
            files.append((rel, size))
            total += size
        for t in TOOL_FILES:
            rel = f"tools/{t}"
            size = add(tar, rel, ROOT / rel)
            files.append((rel, size))
            total += size
        for rel in ("requirements.txt", "requirements.lock", ".env.example",
                    "start.bat", "README.md"):
            size = add(tar, rel, ROOT / rel)
            files.append((rel, size))
            total += size

        info = """建安智能体 v7 服务器部署包 · DEPLOY-INFO
生成日期：2026-11-15 | git HEAD：a0c782a | KB：37 份文档 / 509 个片段
向量索引：kb/vec_index_bge-small-zh-v1.5.npz（509 块，已与 KB 严格对齐）

【包内包含】
app/ web/ docs/ deploy/、kb/kb.sqlite、kb/docs_meta.json、
kb/vec_index_bge-small-zh-v1.5.npz、models/bge-small-zh-v1.5/（ONNX int8）、
tools/ 精选核验脚本、requirements.txt / requirements.lock、.env.example、
start.bat、README.md、本文件。

【刻意排除】
.env（含真实 API Key，必须单独上传）、data/、tests/、baselines/、
__pycache__、*.log、旧 KB 备份、vec_index_bge-large-zh-v1.5.npz（414 块旧索引）。

【Windows Server 部署】
1) 上传本包与 .env 到服务器（.env 单独传，勿放进包、勿进任何公开仓库）。
2) mkdir C:\\jianan -Force
   tar -xzf jianan-app-v7-20261115.tar.gz -C C:\\jianan --strip-components=1
   （必须带 --strip-components=1，否则会嵌套 C:\\jianan\\jianan-app\\ 而跑旧代码）
3) move 上传的 .env 到 C:\\jianan\\.env
4) python -m venv C:\\jianan\\.venv
   C:\\jianan\\.venv\\Scripts\\python.exe -m pip install -r C:\\jianan\\requirements.lock
   （若服务器缺 VC++ 运行库，先装 vc_redist.x64.exe，onnxruntime DLL 依赖）
5) 启动：.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9000
   验证：curl http://127.0.0.1:9000/api/health （llmConfigured=true 且 hybrid ok）
6) HTTPS 反代/备份/日志轮转见 deploy/README-ops.md；端口排除段检查见部署手册。

【发布后必做】
按同日同批次口径重跑 62 题评测重定标（本机 tools/run_eval.py），
确认 48/54 基线未漂移；线上版本落后本地时先用旧目录做回滚备份再切换。

【注意】
本包含 docs/ 内部文档与运维工件，仅供服务器部署，勿外发或上传公开代码仓库。
详细部署说明见 deploy-pkg/v7-部署说明-20261115.md。
"""
        data = info.encode("utf-8")
        ti = tarfile.TarInfo("jianan-app/DEPLOY-INFO.txt")
        ti.size, ti.mtime = len(data), int(time.time())
        tar.addfile(ti, io.BytesIO(data))
        files.append(("DEPLOY-INFO.txt", len(data)))
        total += len(data)

    # 复开校验：包内不得出现 .env / large 索引 / __pycache__ / data/
    with tarfile.open(OUT, "r:gz") as tar:
        names = tar.getnames()
    bad = [x for x in names
           if x.endswith("/.env") or x.endswith(".env") and ".env.example" not in x
           or "bge-large" in x or "__pycache__" in x
           or "/data/" in x or "/tests/" in x]
    # .env.example 是白名单，重新精确过滤
    bad = [x for x in bad if not x.endswith(".env.example")]
    assert not bad, f"包内含禁入文件：{bad[:5]}"
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write(f"v7 部署包清单 | 生成 {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"包: {OUT.name} | {OUT.stat().st_size/1048576:.2f} MB | "
                f"{len(files)} 个文件 | SHA256 {sha}\n")
        f.write(f"KB/向量索引对齐 {n} 块（bge-small）| .env 未入包（单独上传）\n\n")
        for rel, size in files:
            f.write(f"{size:>10}  {rel}\n")
    print(f"[完成] {OUT.name} | {OUT.stat().st_size/1048576:.2f} MB | "
          f"{len(files)} 文件 | SHA256 {sha[:16]}…")
    print(f"[校验] 包内无 .env / large 旧索引 / __pycache__ / data / tests")
    print(f"[清单] {MANIFEST.name}")


if __name__ == "__main__":
    main()
