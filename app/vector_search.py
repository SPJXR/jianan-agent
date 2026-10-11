# -*- coding: utf-8 -*-
"""向量检索模块（ADR-002：bge-small-zh-v1.5，条件补充方案的向量路）。

- 双后端：优先 ONNX int8 量化模型（服务器无 GPU 轻量部署），不存在则回退
  sentence-transformers（本地开发用）。两者共享同一 tokenizer 与
  「CLS pooling + L2 归一化」逻辑（bge 官方池化方式，见 _OnnxEncoder 注释），
  排序一致性由 tests 验证。
- 查询侧加 bge 官方指令前缀（不对称编码，与 tools/build_vec_index.py 一致）。
- 索引 kb/vec_index_*.npz 由离线脚本产出，本模块只读。
- 任何加载失败（文件缺失/依赖缺失/损坏）→ available()=False，
  调用方（retrieval.hybrid_search）自动回退 BM25 单路，不影响主服务。
"""
import os
import sqlite3
import threading

import numpy as np

from . import config

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_lock = threading.Lock()
_state = {"tried": False, "ok": False, "backend": "", "err": "", "enc": None,
          "ids": None, "vecs": None}


def _try_load():
    """进程内首次调用时加载模型与索引（约 1~2s，仅一次）。"""
    with _lock:
        if _state["tried"]:
            return
        _state["tried"] = True
        if not config.HYBRID:
            _state["err"] = "HYBRID=off"
            return
        model_dir = os.path.join(BASE, config.VECTOR_MODEL_DIR)
        index_path = os.path.join(BASE, config.VECTOR_INDEX_PATH)
        try:
            if not os.path.exists(index_path):
                raise FileNotFoundError(f"向量索引不存在: {index_path}")
            z = np.load(index_path, allow_pickle=False)
            _state["ids"] = [int(i) for i in z["chunk_ids"]]
            _state["vecs"] = np.ascontiguousarray(z["vectors"], dtype=np.float32)

            backend = config.VECTOR_BACKEND
            onnx_path = os.path.join(model_dir, "model_int8.onnx")
            if backend == "onnx" or (backend == "auto" and os.path.exists(onnx_path)):
                _state["enc"] = _OnnxEncoder(model_dir, onnx_path)
                _state["backend"] = "onnx-int8"
            else:
                _state["enc"] = _StEncoder(model_dir)
                _state["backend"] = "sentence-transformers"
            _state["ok"] = True
        except Exception as e:  # 任何失败都降级，不抛出
            _state["err"] = f"{type(e).__name__}: {e}"


class _OnnxEncoder:
    """ONNX int8 量化 bge 编码器：tokenize → BERT → CLS pooling → L2 归一化。

    bge 系列用 CLS 池化（models/bge-small-zh-v1.5/1_Pooling/config.json：
    pooling_mode_cls_token=true，mean=false）——与 sentence-transformers 行为
    一致，否则排序会系统性偏离（2026-09-22 量化验证发现）。"""

    def __init__(self, model_dir: str, onnx_path: str):
        import onnxruntime as ort
        from transformers import AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.sess = ort.InferenceSession(
            onnx_path, providers=["CPUExecutionProvider"])
        self.dim = self.sess.get_inputs()[0].shape
        self.max_len = 512

    def encode(self, text: str) -> np.ndarray:
        # padding=True：单条自然长度（动态 seq 轴），比 max_length=512 快约 25 倍
        batch = self.tok([text], padding=True, truncation=True,
                         max_length=self.max_len, return_tensors="np")
        feeds = {k: v.astype(np.int64) for k, v in batch.items()
                 if k in {i.name for i in self.sess.get_inputs()}}
        out = self.sess.run(None, feeds)[0]  # (1, L, dim)
        emb = out[0, 0]  # CLS token（位置 0）即句向量，无需 mask
        emb = emb / (np.linalg.norm(emb) + 1e-12)
        return emb.astype(np.float32)


class _StEncoder:
    """sentence-transformers 编码器（本地开发回退路径，行为与 POC 一致）。"""

    def __init__(self, model_dir: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_dir)

    def encode(self, text: str) -> np.ndarray:
        v = self.model.encode([text], normalize_embeddings=True,
                              convert_to_numpy=True)[0]
        return np.asarray(v, dtype=np.float32)


def available() -> bool:
    """向量路是否可用（不可用时 retrieval 自动回退 BM25 单路）。"""
    if not config.HYBRID:
        return False
    _try_load()
    return _state["ok"]


def backend_info() -> dict:
    """诊断信息：/api/health 与运维排查用。"""
    if not config.HYBRID:
        return {"hybrid": False}
    _try_load()
    return {
        "hybrid": True,
        "ok": _state["ok"],
        "backend": _state["backend"] or None,
        "n_chunks": len(_state["ids"]) if _state["ok"] else 0,
        "err": _state["err"] or None,
    }


def top_k(question: str, k: int = 5) -> list[dict]:
    """向量检索 top-k。返回字段与 retrieval.search() 对齐（score=余弦相似度），
    另附 sim 原值。失败/不可用返回空列表（调用方回退）。"""
    if not available():
        return []
    try:
        qv = _state["enc"].encode(QUERY_PREFIX + question)
        sims = _state["vecs"] @ qv
        order = np.argsort(-sims)[:k]
        ids = [(_state["ids"][i], float(sims[i])) for i in order]
    except Exception:
        return []
    if not ids:
        return []
    con = sqlite3.connect(os.path.join(BASE, "kb", "kb.sqlite"))
    con.row_factory = sqlite3.Row
    try:
        out = []
        for chunk_id, sim in ids:
            r = con.execute(
                """SELECT c.chunk_id, c.doc_id, d.title, d.category, d.note, d.valid_status,
                          c.clause, c.pages, c.anchor, c.text
                   FROM chunks c JOIN docs d ON d.doc_id = c.doc_id
                   WHERE c.chunk_id = ?""", (chunk_id,)).fetchone()
            if not r:
                continue  # 索引与库不对齐时跳过，不中断
            h = dict(r)
            h["rank"] = None
            h["sim"] = round(sim, 4)
            h["score"] = round(sim, 4)
            h["coverage"] = 0.0  # 覆盖率是 BM25 判据，向量块不参与（ADR-002）
            h["via"] = "vector"
            out.append(h)
        return out
    finally:
        con.close()
