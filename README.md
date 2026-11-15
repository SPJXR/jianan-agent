# 建安法规问答助手

一个轻量的、专注建安法规的、每条回答都能给出处的小型专属知识库问答助手（Web 聊天应用）。

- **资料库**：`knowledge_base/docs/` 下 37 份建筑安全法规与政策文档（住建部规章、有限空间作业指南、危大工程严重缺陷清单、禁限用技术目录、开工一件事流程、电子证照标准等）
- **回答可溯源**：回答中的 `[1]` `[2]` 引用标注与「引用来源」卡片，逐字对应知识库条款原文，点击可查看原文面板
- **答不出就承认**：知识库无相关内容时明确回答"未找到"，不编造条款
- **离线可用**：未配置模型服务时自动降级为「检索原文片段」展示，不中断使用

对应产品文档见 `docs/PRD.md`（MVP 需求）与 `docs/UIUX.md`（设计规范）。

## 版本与口径（2026-11-15，最新）

> 下文各历史段落中的「34 份文档 / 414 个片段 / ADR-001~007 / 9 PASS 2 SKIPPED」等为当时快照，按项目「带日期记录不回填改写」的约定保留；**当前状态一律以本节为准**。

| 项 | 当前值 | 复算入口 |
|---|---|---|
| 知识库 | **37 份文档 / 509 个片段** | `kb/kb.sqlite` count 查询 |
| 时效状态 | 现行有效 12 / 试行 4 / 征求意见稿 1 / 未核定 20 | `kb/docs_meta.json` |
| 全量评测 | **48/54**（fact）、拒答 5/5、边界 3/3（2026-11-06；本周未重跑） | `docs/eval/results/eval_ctx-31_20261106.json` |
| 决策资产 | **11 份 ADR（ADR-001~011）** + OPEN-DECISIONS 登记册 | `docs/decisions/` |
| 提交历史 | 56 次细粒度提交 | `git log` |
| 评测量尺 | 段计数 / 错误复制率 / 位置分桶 / 句级支持性 / 弃答审计（本周新增，均为离线复算） | `docs/eval/*.md` + `tools/` |
| 论文素材 | 9 份提取件，本周精读 6 篇，证据链汇编见 `docs/research/` | `docs/research/毕设相关工作-论文证据链汇编-20261115.md` |

**官方测试入口**：`.venv/Scripts/python.exe tools/run_unit_tests.py`（5 个白名单守卫模块、45 用例，每模块独立子进程）。`unittest discover -s tests` 不适用于本仓库——`tests/` 下 40+ 个历史 POC / 联网 API / 诊断脚本会在模块顶层包装 `sys.stdout`，导致连锁假错误；这些历史件只读归档，不为发布而改。

**服务器部署**：发布包见 `deploy-pkg/jianan-app-v7-20261115.tar.gz`，配套 `deploy-pkg/v7-部署说明-20261115.md` 与 `deploy/README-ops.md`。要点：`.env`（含 API Key）**不进包、单独上传**；包内向量索引为 `kb/vec_index_bge-small-zh-v1.5.npz`（509 块，与 KB 对齐），仓库内 `vec_index_bge-large-zh-v1.5.npz` 是 414 块的旧索引，**切勿入包**。部署后须按同日同批次口径重跑 62 题重定标。

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

## 降级模式与演示（A-2）

三种方式让应用在**无可用模型服务**时仍可运行/演示：

| 方式 | 效果 |
|------|------|
| 不配置 `.env` 的 `LLM_API_KEY` | 检索原文降级展示（提示"管理员尚未配置模型服务"） |
| 环境变量 `LLM_DISABLED=1` | 显式降级开关——已配 Key 也能强制走降级（Windows cmd 无法设空变量，故用此开关） |
| 双击 `start_demo_degraded.bat` | 一键启动降级演示实例（自带开关与提示横幅） |

降级行为：正常问题直接逐字展示命中条款原文（相关度低时截断并警示"请勿作为依据"）；库外问题仍走"未找到"诚实兜底，不会因为降级而编造。

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

## 检索与评测工具链（B 档）

| 工具 | 说明 |
|------|------|
| `tools/run_eval.py` | 62 题全量评测；含 **ctx_hit 判据**（预期文档是否真正进入 LLM 上下文，区分「没召回」vs「召回了被截断」）；`--set eval_set_mt.json` 跑多轮指代组 |
| `tools/grid_search.py` | 覆盖率权重 × 召回窗口网格定标（2026-10-24 结论：网格已饱和，现值 2.0/16 确认最优，见 `docs/eval/网格搜索-20261024.md`） |
| `tools/temp_ablation.py` | 生成温度消融（同代码 4 温度 × 62 题，结论见 ADR-009） |
| `tools/kb_pipeline.py` | 知识库扩充一键流水线：解析 → 建库 → 向量索引 → 护栏回归（→ 可选 62 题全量） |
| `kb/synonyms.json` | 口语→法规术语召回映射（ADR-008）：只扩召回不进覆盖率分母，`SYNONYMS=0` 可关 |

口语同义映射与多轮指代改写上线后，弱命中题可省一次 LLM 改写调用；改写链路（ADR-007 只加分不翻盘）保持不变。

## 开发护栏（pre-commit）

```bat
git config core.hooksPath .githooks
```

一次性安装后，每次提交自动跑 14 题检索回归（约 20 秒，离线不调 LLM），防止检索层改动无护栏上线。应急绕过：`git commit --no-verify`（须在提交信息里说明理由）。

## 服务器运维（B-3）

`deploy/` 目录提供 Windows 服务器（与部署手册 v5.2 一致）的运维工件：每日备份（kb.sqlite + 向量索引，保留 7 份）、日志轮转（>50MB 归档）、Caddy HTTPS 反代配置，安装步骤见 `deploy/README-ops.md`。

## 知识库更新

替换/新增 `knowledge_base/docs/` 文档后，按 doc 编号在 `kb/docs_meta.json` 登记标题、分类与时效状态，然后跑一键流水线（解析 → 建库 → 向量索引 → 护栏，一步到位）：

```bat
.venv\Scripts\python.exe tools\kb_pipeline.py
```

或分步执行 `tools\extract_docs.py` → `tools\build_kb.py` → `tools\build_vec_index.py bge-small-zh-v1.5`。

## 已知边界

- 知识库现含 **37 份文档**（2026-10-24 两批变更：+0077 重大事故隐患判定标准 2024 版 / +0078 工贸企业有限空间作业安全规定 / +0079 有限空间作业安全指导手册 / +0080 GB 55034-2022 全文强制通用规范（openstd 切片 PDF 拼贴 OCR，工具 tools/ocr_0080.py）；-0001 涉企检查清单**下架**（kb/retired/ 留证，理由见法规时效核查台账）。网页来源与抓取时间见 `kb/web_sources.json`）
- 扩库后同主题跨部门文档（住建指南 vs 应急部手册）存在排序竞争，窗口内已加每文档块数上限（PER_DOC_CAP=4，POC 见 tests/poc_doc_cap.py）；按场景加权文档来源的精化排序列入下一迭代
- 0004（施工安全隐患示意图）为扫描图片版，仅少量文字可检索；0002 为空表格模板
- 0069（试行版）与 0070（征求意见稿）为同一指南的两个版本，来源页已分别标注
- 34 份文档的时效状态分两批核定（首批 2026-10-11、第二批 2026-10-12）：`effective` 8 份、`trial` 4 份、`consultation` 1 份、`na`（附件/表格/示例/讲话/指导读物类）20 份，**仅剩 1 份 `unknown`（0001 涉企行政检查事项清单）**。0001 是**故意保持未定**的：公开渠道取不到母文件文号，且本地版写"房地产开发企业监督检查（3项）"而 2025-10 地方转引版同条已作"（7项）"，清单随年度动态更新、本地版很可能已过时——这种情况必须继续显示「时效待确认」徽章，不能为了台账好看标成现行有效。逐条依据、来源链接与核查批次见 `docs/法规时效核查台账.md`；回填脚本 `tools/backfill_validity.py`（改完须重跑 `tools/build_kb.py`，元数据重建不改片段内容，`chunks_hash` 保持 `2e65efd1315806ff…` 不变）。**第二批的依据是转发件与第三方法规库，尚未逐份回发文机关官网比对原件，台账中已单列「需人工复核」**。已核定为征求意见稿/已废止的文档在检索中乘性降权、不再充当第一依据，但**未核定的 `unknown` 一律不降权**，以免把"还没查"变成"检索变差"（决策与取舍见 docs/decisions/ADR-006）
- 埋点计数已持久化（`data/track.sqlite`，重启不丢），仍只存「日期+事件名+计数」，不存问题原文与用户身份（见 docs/decisions/ADR-001 增补）；`/api/track/stats` 已加鉴权：配置 `TRACK_STATS_TOKEN` 则校验口令，未配置则仅本机可访问
- 回答反馈（有帮助/无帮助）存于浏览器本地 `jz_feedback_v1`，可在知识库来源页导出 JSON
