# -*- coding: utf-8 -*-
"""打 v5.2 部署包（服务器更新用）。

v5.2 = v5.1 + ADR-005 表格感知分块（kb.sqlite 414 块 + anchor 列）
             + FTS5 双列 / 检索覆盖率含锚点 / 向量索引 anchor+text 编码
             + RECALL_WINDOW 14->16 + supplement <=6 截断（main.py）
v5.1 = v4 内容 + 迭代5 角色化提示词（app/prompts.py、前端角色选择条）
             + main.py health() 修复

内容：app/ web/ docs/ / kb/kb.sqlite + 小向量索引 / models/bge-small-zh-v1.5
     （仅 tokenizer + model_int8.onnx，不含 92MB safetensors——
      服务器只跑 ONNX，无需 fp32 权重）/ requirements.txt / start.bat / README
排除：.venv / __pycache__ / 日志 / ocr 中间产物 / bge-large / safetensors / tests
用法：python tools/make_v5_pkg.py
"""
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy-pkg" / "jianan-app-v5.2.tar.gz"
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
