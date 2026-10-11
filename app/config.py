# -*- coding: utf-8 -*-
"""服务配置：从环境变量 / .env 读取（管理员配置，不在前端暴露）"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()

# ---- LLM（OpenAI 兼容接口，默认适配阿里云 DashScope）----
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen-plus")
LLM_TIMEOUT_FIRST = float(os.environ.get("LLM_TIMEOUT_FIRST", "60"))   # 首 token 超时
LLM_TIMEOUT_TOTAL = float(os.environ.get("LLM_TIMEOUT_TOTAL", "120"))  # 总超时
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1200"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))

# ---- 应用 ----
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "9000"))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "8"))
# 检索评分窗口（迭代6，ADR-005 调优）：答案块可能排 9~16 位（同文档表格碎片/
# 邻近条款稀释，如 0012 附件3 颜色块排 13、0065 一类高层块排 15），仅取窗口内
# 与 top-8 主证据同文档的块补进上下文。POC 窗口扫描：15/16/18 均恢复 PM-06，
# 16 较 15 留 1 位缓冲（hybrid 向量融合可能带来 ±1~2 位排名漂移），18 无额外收益。
RECALL_WINDOW = int(os.environ.get("RECALL_WINDOW", "16"))
MIN_COVERAGE = float(os.environ.get("MIN_COVERAGE", "0.25"))  # 低于此相关度走"未找到"兜底
# 低于此相关度视为弱命中，触发「口语 -> 法规术语」LLM 改写后二次检索（两阶段检索）
REWRITE_MIN_COVERAGE = float(os.environ.get("REWRITE_MIN_COVERAGE", "0.5"))

# ---- 混合检索（ADR-002：条件补充方案）----
# HYBRID=0 秒级降级回 BM25 单路；模型/索引加载失败也自动回退（不影响可用性）
HYBRID = os.environ.get("HYBRID", "1") == "1"
VECTOR_MODEL_DIR = os.environ.get("VECTOR_MODEL_DIR", "models/bge-small-zh-v1.5")
VECTOR_INDEX_PATH = os.environ.get("VECTOR_INDEX_PATH", "kb/vec_index_bge-small-zh-v1.5.npz")
VECTOR_TOP_K = int(os.environ.get("VECTOR_TOP_K", "5"))      # 弱命中时向量路置前条数
VECTOR_BM25_KEEP = int(os.environ.get("VECTOR_BM25_KEEP", "3"))  # 弱命中时 BM25 追加条数
# auto: 优先 ONNX int8（服务器轻量部署），否则回退 sentence-transformers
VECTOR_BACKEND = os.environ.get("VECTOR_BACKEND", "auto")

# 固定文案（PRD 要求）
DISCLAIMER = "本回答由 AI 基于知识库收录的法规文本生成，仅供参考。正式执行请以官方发布的现行有效版本为准。"
NO_ANSWER_TEXT = "知识库中未找到与该问题直接相关的条款。"


def llm_configured() -> bool:
    return bool(LLM_API_KEY)
