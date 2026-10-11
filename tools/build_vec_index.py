# -*- coding: utf-8 -*-
"""构建向量索引（A方向混合检索升级，POC 双模型）。

从 kb/kb.sqlite 读取全部 chunks，用指定 bge 模型编码（归一化），
输出 kb/vec_index_<name>.npz：
  - chunk_ids: (N,) 文本 chunk_id 列表（与 kb.sqlite 对齐）
  - vectors:   (N, dim) L2 归一化向量矩阵（float32）

用法：
  python tools/build_vec_index.py bge-small-zh-v1.5
  python tools/build_vec_index.py bge-large-zh-v1.5

bge 系列检索指令前缀（官方推荐，短查询侧）：
  「为这个句子生成表示以用于检索相关文章：」
语料侧（passage）不加前缀——不对称编码是 bge v1.5 的标准用法。
"""
import sys
import sqlite3
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def main(model_name: str):
    from sentence_transformers import SentenceTransformer

    model_dir = ROOT / "models" / model_name
    out_path = ROOT / "kb" / f"vec_index_{model_name}.npz"

    con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
    # 语料侧编码 anchor + text（ADR-005 表格感知分块）：锚点行（文档标题 ›
    # 最近类别/章节）为表格明细块补足语义；查询侧仍不加锚点（不对称编码）。
    rows = con.execute(
        "SELECT chunk_id, COALESCE(anchor, ''), text FROM chunks ORDER BY chunk_id"
    ).fetchall()
    con.close()
    chunk_ids = [r[0] for r in rows]
    texts = [(r[1] + "\n" + r[2]) if r[1] else r[2] for r in rows]
    print(f"chunks: {len(texts)} | model: {model_name}")

    model = SentenceTransformer(str(model_dir))
    t0 = time.time()
    vecs = model.encode(texts, batch_size=32, normalize_embeddings=True,
                        show_progress_bar=False, convert_to_numpy=True)
    vecs = vecs.astype(np.float32)
    dt = time.time() - t0
    print(f"encoded in {dt:.1f}s | dim={vecs.shape[1]}")

    np.savez_compressed(out_path, chunk_ids=np.array(chunk_ids), vectors=vecs)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"saved: {out_path.name} ({size_mb:.1f} MB)")

    # 自检：加载回读，确认 chunk_id 对齐且范数≈1
    z = np.load(out_path, allow_pickle=False)
    assert list(z["chunk_ids"]) == chunk_ids, "chunk_id 不对齐"
    norms = np.linalg.norm(z["vectors"], axis=1)
    assert abs(norms.mean() - 1.0) < 1e-3, f"归一化异常: mean_norm={norms.mean()}"
    print("self-check OK: chunk_id 对齐，向量已归一化")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "bge-small-zh-v1.5"
    main(name)
