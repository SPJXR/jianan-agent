# -*- coding: utf-8 -*-
"""打 v4 部署包（服务器更新用）。

内容：app/ web/ kb/kb.sqlite + 小向量索引 / models/bge-small-zh-v1.5
     （仅 tokenizer + model_int8.onnx，不含 92MB safetensors——
      服务器只跑 ONNX，无需 fp32 权重）/ requirements.txt / start.bat / docs

排除：.venv / __pycache__ / 日志 / ocr 中间产物 / bge-large / safetensors / tests
用法：python tools/make_v4_pkg.py
"""
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy-pkg" / "jianan-app-v5.tar.gz"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MODEL_FILES = [
    "config.json", "model_int8.onnx", "special_tokens_map.json",
    "tokenizer.json", "tokenizer_config.json", "vocab.txt",
    "1_Pooling/config.json",
]

def add(tar: tarfile.TarFile, arc: str, src: Path):
    tar.add(src, arcname=f"jianan-app/{arc}")
    print(f"  + {arc} ({src.stat().st_size/1024:.0f}KB)")

def main():
    OUT.parent.mkdir(exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tar:
        for d in ("app", "web", "docs"):
            for f in sorted((ROOT / d).rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    add(tar, f.relative_to(ROOT).as_posix(), f)
        add(tar, "kb/kb.sqlite", ROOT / "kb/kb.sqlite")
        add(tar, "kb/vec_index_bge-small-zh-v1.5.npz",
            ROOT / "kb/vec_index_bge-small-zh-v1.5.npz")
        for f in MODEL_FILES:
            add(tar, f"models/bge-small-zh-v1.5/{f}",
                ROOT / "models/bge-small-zh-v1.5" / f)
        for f in ("requirements.txt", "start.bat", "README.md"):
            add(tar, f, ROOT / f)
    mb = OUT.stat().st_size / 1048576
    print(f"\n完成: {OUT} ({mb:.1f}MB)")

if __name__ == "__main__":
    main()
