# -*- coding: utf-8 -*-
"""bge-small-zh-v1.5 ONNX int8 量化导出（ADR-002 线上部署形态）。

流程：transformers 权重 → torch.onnx.export（动态 seq 轴，查询侧实际长度推理）
→ onnxruntime 动态量化（QInt8 权重）→ models/bge-small-zh-v1.5/model_int8.onnx

产出文件名与 app/vector_search.py 的探测逻辑一致（model_int8.onnx）。
tokenizer 复用原目录文件，不额外复制。

用法：python tools/quantize_bge_small.py
"""
import io
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MODEL_DIR = ROOT / "models" / "bge-small-zh-v1.5"
TMP_DIR = ROOT / "models" / "_onnx_tmp"
OUT_INT8 = MODEL_DIR / "model_int8.onnx"
MAX_LEN = 512


def export_fp32():
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = AutoModel.from_pretrained(str(MODEL_DIR))
    model.eval()

    dummy = tok(["为这个句子生成表示以用于检索相关文章：测试"],
                return_tensors="pt", truncation=True, max_length=MAX_LEN)

    class Wrapper(torch.nn.Module):
        def forward(self, input_ids, attention_mask, token_type_ids):
            out = model(input_ids=input_ids, attention_mask=attention_mask,
                        token_type_ids=token_type_ids)
            return out.last_hidden_state

    TMP_DIR.mkdir(exist_ok=True)
    fp32 = TMP_DIR / "model.onnx"
    torch.onnx.export(
        Wrapper(),
        (dummy["input_ids"], dummy["attention_mask"], dummy["token_type_ids"]),
        str(fp32),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "last_hidden_state": {0: "batch", 1: "seq"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    return fp32


def main():
    from onnxruntime.quantization import quantize_dynamic, QuantType

    if OUT_INT8.exists():
        print(f"已存在，跳过导出: {OUT_INT8}")
        return

    print("[1/3] 导出 fp32 ONNX（动态 seq 轴）...")
    t0 = time.time()
    fp32 = export_fp32()
    print(f"    done in {time.time() - t0:.1f}s -> {fp32.name}")

    print("[2/3] 动态量化 int8 ...")
    quantize_dynamic(
        model_input=str(fp32),
        model_output=str(OUT_INT8),
        weight_type=QuantType.QInt8,
    )
    fp32_mb = fp32.stat().st_size / 1048576
    int8_mb = OUT_INT8.stat().st_size / 1048576
    print(f"    fp32={fp32_mb:.1f}MB -> int8={int8_mb:.1f}MB")

    print("[3/3] 清理临时目录 ...")
    shutil.rmtree(TMP_DIR)
    print(f"完成: {OUT_INT8}")


if __name__ == "__main__":
    main()
