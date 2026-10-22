# 建安法规问答助手

一个轻量的、专注建安法规的、每条回答都能给出处的小型专属知识库问答助手（Web 聊天应用）。

- **资料库**：`knowledge_base/docs/` 下 34 份建筑安全法规与政策文档（住建部规章、有限空间作业指南、危大工程严重缺陷清单、禁限用技术目录、开工一件事流程、电子证照标准等）
- **回答可溯源**：回答中的 `[1]` `[2]` 引用标注与「引用来源」卡片，逐字对应知识库条款原文，点击可查看原文面板
- **答不出就承认**：知识库无相关内容时明确回答"未找到"，不编造条款
- **离线可用**：未配置模型服务时自动降级为「检索原文片段」展示，不中断使用

对应产品文档见 `docs/PRD.md`（MVP 需求）与 `docs/UIUX.md`（设计规范）。

## 快速开始

```bat
:: Windows 双击或命令行运行
start.bat
```

首次运行会自动：创建虚拟环境 → 按 `requirements.lock` 安装依赖 → 启动服务，并在 6 秒后打开浏览器。
（若分发包内已含 `kb/kb.sqlite`，则**不会**重建索引；只有索引缺失时才会去解析文档，那一步需要本机装有 MS Word。）

失败时脚本会**停下来打印原因并等待按键**，完整安装输出写入 `install_log.txt`。

- 访问地址：http://127.0.0.1:9000
- 手动分步执行（不依赖 `uv`，任何装了 Python 3.9+ 的机器都可用）：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe tools\extract_docs.py   :: 仅索引缺失时需要（.doc 要 MS Word，扫描件走 Windows OCR）
.venv\Scripts\python.exe tools\build_kb.py       :: 分块 + 建 SQLite FTS5 索引
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9000
```

**要求可复现环境时改用锁定版本**（评审/队员建议用这条，版本与开发环境完全一致）：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
:: 需要跑浏览器 E2E 测试或做离线量化时，再补装开发依赖：
:: .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 一键核验

```bat
.venv\Scripts\python.exe tools\verify_all.py
```

把全部**可机器复算的主张**串成一条命令：引用逐字契约、时效降权与鉴权单元用例、14 题检索回归、混合检索零回归、API 契约与各轮冒烟/E2E。结果自动写入 `docs/核验报告.md`（含时间戳与代码版本）。当前状态：**9 PASS / 0 FAIL / 2 SKIPPED**。

只跑不依赖服务的部分：`tools\verify_all.py --offline`。

防假绿规则写在脚本头部：退出码单独不可信（部分脚本恒返回 0），必须再匹配判定行，无判定行记 FAIL 不放行；缺开发依赖记为可操作的 SKIPPED 而非误报产品缺陷；SKIPPED 不等于通过。

## 配置模型服务（管理员）

复制 `.env.example` 为 `.env`，填入 API Key 后重启：

```ini
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxxx
LLM_MODEL=qwen-plus
```

兼容任何 OpenAI 兼容接口（含本地 Ollama：`LLM_BASE_URL=http://127.0.0.1:11434/v1`）。

| 模式 | 行为 |
|------|------|
| 已配置 Key | 检索 → 云端 LLM 流式生成，回答内嵌 `[n]` 引用标注 |
| 未配置 / Key 失效 / 超时 | 提示条说明原因，直接展示检索命中的条款原文（逐字），相关度低时自动截断并警示 |
| 检索相关度过低 | 直接回答"知识库中未找到与该问题直接相关的条款" |

Key 仅存于服务端 `.env`，不出现在前端；内置按 IP 限流（默认 20 次/分钟）。

## 目录结构

```text
├── app/                    # FastAPI 后端
│   ├── main.py             # SSE 流式问答 /api/chat、来源、示例、健康检查、限流
│   ├── retrieval.py        # jieba 分词 + FTS5 trigram(BM25) + 覆盖率重排
│   ├── llm.py              # OpenAI 兼容流式客户端（首 token 60s 超时、错误分类）
│   ├── track.py            # 埋点计数端点（仅存计数，合规脱敏）
│   └── config.py           # .env 配置加载
├── web/                    # 静态前端（无构建步骤）
│   ├── index.html          # 聊天主页 + 引用面板 + 知识库来源抽屉
│   ├── style.css           # 工程蓝图设计语言（docs/UIUX.md）
│   ├── favicon.svg         # 工程蓝图蓝安全帽图标
│   └── app.js              # SSE 渲染 / 引用 chip / 来源卡片 / 埋点 SDK / 回答反馈
├── tools/                  # 知识库构建与核验流水线
│   ├── extract_docs.py     # .doc→Word COM 转 docx、.docx/.pdf 解析
│   ├── ocr_image.ps1       # Windows.Media.Ocr 中文 OCR（扫描件）
│   ├── ocr_scans.py        # 0003/0004/0067 扫描图 OCR
│   ├── build_kb.py         # 表格感知分块 + FTS5 索引
│   ├── build_vec_index.py  # 条款向量索引（bge-small-zh-v1.5）
│   ├── quantize_bge_small.py # fp32→int8 离线量化（95.8MB→23MB，纯 CPU 推理）
│   ├── backfill_validity.py # 34 份文档时效核定 → docs_meta.json + 核查台账
│   ├── verify_verbatim.py  # 引用逐字契约校验（414 片段 0 不一致，可重跑）
│   ├── verify_all.py       # 一键总校验，自动生成 docs/核验报告.md
│   ├── trial_report.py     # 试用数据汇总与交叉校验（区分埋点/自报/交叉）
│   ├── make_shots.py       # 参赛截图自动拍摄（本机 Edge）
│   └── check_mobile.py     # 390×844 移动端适配实测（溢出/触控目标/字号）
├── kb/
│   ├── docs_meta.json      # 34 份文档人工核定标题/分类/时效状态
│   ├── text/               # 抽取出的纯文本（引用溯源的数据源）
│   └── kb.sqlite           # 检索索引（414 个条款片段）
├── knowledge_base/docs/    # 原始 34 份文档
├── docs/                   # 产品与设计文档、验收记录
│   ├── PRD.md / UIUX.md / SPEC-ITER*.md
│   ├── ACCEPTANCE.md       # 分轮次验收记录（带日期，不回填改写）
│   ├── 技术架构与测试说明.md  # 参赛材料 C2
│   ├── 原创性与第三方资源清单.md # 参赛材料 C3
│   ├── 核验报告.md          # 由 verify_all.py 自动生成，勿手改
│   ├── 法规时效核查台账.md   # 由 backfill_validity.py 自动生成，勿手改
│   ├── decisions/          # ADR-001~007 技术决策与否决记录
│   ├── eval/               # 评测集与结果（题目初稿 AI 起草、学生逐题筛选定稿；无分类标记字段）
│   ├── research/           # 论文精读与 POC 记录
│   └── screenshots/        # 参赛截图 10 张（含移动端实拍）
├── tests/                  # 接口测试 / 检索回归 / 冒烟与 E2E / mock LLM
├── requirements.lock       # 15 项运行时依赖锁定版本（复现环境用这个）
├── requirements-dev.txt    # 测试与离线量化依赖（生产不需要）
├── .env.example            # 配置模板
└── start.bat               # 一键启动
```

## 接口

| 接口 | 说明 |
|------|------|
| `POST /api/chat` | SSE 流式问答。事件：`status`（检索中/命中数）→ `sources`（引用契约：docId/title/clause/pages/excerpt/full 逐字原文）→ `delta`（文本增量）→ `done` / `error` / `notice` |
| `GET /api/sources` | 34 份文档清单（标题、分类、片段数、状态、时效性标注） |
| `GET /api/examples` | 首屏示例问题（均已验证可被知识库回答） |
| `GET /api/health` | 服务与模型配置状态 |
| `GET /api/chunk/{chunk_id}` | 条款详情（含同文档前后相邻条款，引用面板上下文用） |
| `POST /api/track` | 埋点上报（sendBeacon，白名单清洗，仅存事件名计数，不存属性明细/问题原文） |
| `GET /api/track/stats` | 事件计数（持久化于 `data/track.sqlite`，重启不丢；`?history=1` 返回最近 30 天逐日汇总） |

## 知识库更新

替换/新增 `knowledge_base/docs/` 文档后，按 doc 编号在 `kb/docs_meta.json` 登记标题与分类，重跑：

```bat
.venv\Scripts\python.exe tools\extract_docs.py
.venv\Scripts\python.exe tools\build_kb.py
```

## 已知边界

- 0004（施工安全隐患示意图）为扫描图片版，仅少量文字可检索；0002 为空表格模板
- 0069（试行版）与 0070（征求意见稿）为同一指南的两个版本，来源页已分别标注
- 34 份文档的时效状态分两批核定（首批 2026-10-11、第二批 2026-10-12）：`effective` 8 份、`trial` 4 份、`consultation` 1 份、`na`（附件/表格/示例/讲话/指导读物类）20 份，**仅剩 1 份 `unknown`（0001 涉企行政检查事项清单）**。0001 是**故意保持未定**的：公开渠道取不到母文件文号，且本地版写"房地产开发企业监督检查（3项）"而 2025-10 地方转引版同条已作"（7项）"，清单随年度动态更新、本地版很可能已过时——这种情况必须继续显示「时效待确认」徽章，不能为了台账好看标成现行有效。逐条依据、来源链接与核查批次见 `docs/法规时效核查台账.md`；回填脚本 `tools/backfill_validity.py`（改完须重跑 `tools/build_kb.py`，元数据重建不改片段内容，`chunks_hash` 保持 `2e65efd1315806ff…` 不变）。**第二批的依据是转发件与第三方法规库，尚未逐份回发文机关官网比对原件，台账中已单列「需人工复核」**。已核定为征求意见稿/已废止的文档在检索中乘性降权、不再充当第一依据，但**未核定的 `unknown` 一律不降权**，以免把"还没查"变成"检索变差"（决策与取舍见 docs/decisions/ADR-006）
- 埋点计数已持久化（`data/track.sqlite`，重启不丢），仍只存「日期+事件名+计数」，不存问题原文与用户身份（见 docs/decisions/ADR-001 增补）；`/api/track/stats` 已加鉴权：配置 `TRACK_STATS_TOKEN` 则校验口令，未配置则仅本机可访问
- 回答反馈（有帮助/无帮助）存于浏览器本地 `jz_feedback_v1`，可在知识库来源页导出 JSON
