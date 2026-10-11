# -*- coding: utf-8 -*-
"""临时调试：fp32 ONNX 导出正确性定位（用后可删）。"""
import os
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = str(ROOT / "models" / "bge-small-zh-v1.5")
DBG = str(ROOT / "models" / "_dbg.onnx")

tok = AutoTokenizer.from_pretrained(MODEL_DIR)
model = AutoModel.from_pretrained(MODEL_DIR)
model.eval()

q = "为这个句子生成表示以用于检索相关文章：工地上挖坑底下干活有啥危险要注意的？"
enc = tok([q], return_tensors="pt", truncation=True, max_length=512)


class W(torch.nn.Module):
    def forward(self, input_ids, attention_mask, token_type_ids):
        return model(input_ids=input_ids, attention_mask=attention_mask,
                     token_type_ids=token_type_ids).last_hidden_state


w = W()
with torch.no_grad():
    out_pt = w(enc["input_ids"], enc["attention_mask"],
               enc["token_type_ids"]).numpy()
print("pt out shape:", out_pt.shape)

mask = enc["attention_mask"].numpy().astype(np.float32)[0]
emb_pt = (out_pt[0] * mask[:, None]).sum(0) / mask.sum()
emb_pt = emb_pt / np.linalg.norm(emb_pt)

torch.onnx.export(
    w, (enc["input_ids"], enc["attention_mask"], enc["token_type_ids"]), DBG,
    input_names=["input_ids", "attention_mask", "token_type_ids"],
    output_names=["last_hidden_state"],
    dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                  "token_type_ids": {0: "b", 1: "s"}, "last_hidden_state": {0: "b", 1: "s"}},
    opset_version=14, do_constant_folding=True)
print("dbg onnx size MB:", os.path.getsize(DBG) / 1048576)

import onnxruntime as ort
sess = ort.InferenceSession(DBG, providers=["CPUExecutionProvider"])
feeds = {k: v.numpy().astype(np.int64) for k, v in enc.items()}
out_ox = sess.run(None, feeds)[0]
print("onnx out shape:", out_ox.shape,
      "max diff vs pt:", float(np.abs(out_ox - out_pt).max()))
emb_ox = (out_ox[0] * mask[:, None]).sum(0) / mask.sum()
emb_ox = emb_ox / np.linalg.norm(emb_ox)
print("emb cosine pt vs onnx-fp32:", float(emb_pt @ emb_ox))
