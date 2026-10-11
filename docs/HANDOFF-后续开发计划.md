# 建安法规问答助手 — 后续开发计划（交接文档）

| 项目 | 内容 |
|------|------|
| 文档用途 | 交接给后续开发 Agent 的唯一入口文档，自包含，无需原对话上下文 |
| 撰写日期 | 2026-09-20 |
| 项目目录 | `D:\wdagent\2026-09-19-17-37-04`（下文均以「项目根目录」指代） |
| 当前状态 | **MVP（F1-F4）+ 迭代1（F5/F6/F7）+ 迭代1.5 清理 + 迭代2（2.1 埋点 SDK / 2.2 F8 反馈 / 2.3 时效标注表结构与 UI）已完成并通过本机全链路验收，服务可运行。下一步：公网发布（主理人）→ 迭代 3（前置 POC）** |
| 配套文档 | `docs/PRD.md`（需求）、`docs/UIUX.md`（视觉规范）、`README.md`（架构蓝图）、`docs/SPEC-ITER1.md`（迭代1契约）、`docs/ACCEPTANCE.md`（验收记录）、`docs/decisions/OPEN-DECISIONS.md`（未决登记册） |

---

## 一、项目是什么

**一句话定位**：面向建筑施工安全员/项目经理/监理的建安法规 RAG 问答 Web 应用——34 份本地法规文档构建知识库，检索 + 云端 LLM 生成回答，**每条回答可溯源到条款原文（逐字引用），答不出就明确承认**。

- 产品形态：浏览器即用的单页 Web 应用（FastAPI 后端 + 原生 JS 前端），无注册、无多租户。
- 目标用户与竞品分析详见 `docs/PRD.md` §2-§3。
- 成功指标：激活率 ≥50%、核心价值交付率 ≥85%、引用逐字准确率 ≥90%、首字符响应 p95 <5s、「未找到」误判率 ≤10%（PRD §12）。

## 二、当前完成度（截至 2026-09-20）

| 功能 | 状态 | 说明 |
|------|------|------|
| F1 问答+引用溯源 | ✅ 已验收 | SSE 流式，引用逐字比对 0 差异 |
| F2 流式渲染+状态提示 | ✅ 已验收 | 检索中/生成中双态提示，失败重试 |
| F3 示例问题引导 | ✅ 已验收 | 6 个示例问题 |
| F4 知识库来源展示 | ✅ 已验收 | 34 文档/422 条款片段 |
| F5 引用原文展开 | ✅ 已验收（迭代1） | 引用面板含「前文/后文」相邻条款折叠区 |
| F6 多轮追问 | ✅ 已验收（迭代1） | 近 3 轮 history + 检索改写 |
| F7 历史会话 | ✅ 已验收（迭代1） | 浏览器本地存储，侧边栏，刷新恢复 |
| 迭代1.5 清理 | ✅ 已验收（2026-09-20） | favicon 补齐；根目录阶段证据归档 docs/phase1-evidence/ |
| 2.1 埋点 SDK | ✅ 已验收（迭代2） | 9 事件 + sendBeacon + /api/track 内存计数（ADR-001）；tests/iter2_smoke.py 21/21 |
| F8 回答反馈 | ✅ 已验收（迭代2） | 有帮助/无帮助 + jz_feedback_v1 本地存储 + 来源页导出 JSON |
| 2.3 文档时效标注 | ✅ 表结构与 UI 已验收；**实际状态值待用户回填**（OPEN-DECISIONS 在案） | docs 表 valid_status/version_date + 来源页徽章 |
| 公网发布 | ❌ 未做 | PRD AC9.3，由主理人执行（前置清理已完成） |
| F9 知识库管理 | ❌ 未做 | 见下文迭代3 |

验收证据：`docs/ACCEPTANCE.md` 含 2026-09-19 全量验收 + 2026-09-20 真实 DeepSeek 全链路补验 + 迭代1 验收（E2E 11/11）+ 迭代1.5/2 验收（API 级 13/13 + E2E 21/21 + 迭代1 回归 11/11）。迭代2 契约见 `docs/SPEC-ITER2.md`，埋点通道决策见 `docs/decisions/ADR-001-埋点上报通道.md`。

## 三、技术架构与代码地图

```
项目根目录/
├── app/                     # FastAPI 后端
│   ├── main.py    (~266行)  # 路由 + SSE 流 + 限流 + 降级 + 兜底 + 静态挂载
│   ├── retrieval.py (~224行)# FTS5 检索 + get_chunk_context()（迭代1新增）
│   ├── llm.py       (~161行)# OpenAI 兼容客户端，stream_chat(sources, question, history=None)
│   └── config.py            # .env 加载（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 等）
├── web/                     # 原生前端（无框架）
│   ├── index.html (~122行)  # 含历史侧边栏 + 引用上下文容器 #citeContext
│   ├── style.css  (~463行)  # 工程蓝图蓝主题（#1D4ED8 体系），CSS 变量化
│   └── app.js     (~753行)  # SSE 渲染/引用面板/历史会话/trackEvent 封装
├── kb/
│   ├── kb.sqlite (2MB)      # docs 表(34行) + chunks 表(422行,含 doc_id/seq/clause/pages/text/chunk_id) + chunks_fts(FTS5)
│   └── *.txt                # 构建/抽取/服务运行日志
├── tools/                   # 知识库流水线：extract_docs / build_kb / ocr_scans / ocr_image.ps1 等
├── tests/
│   ├── api_test.py          # API 集成测试
│   ├── mock_llm.py          # mock LLM（无 Key 时的联调）
│   ├── 检索回归用例          # 内置于测试
│   └── iter1_smoke.py       # Playwright E2E 冒烟（11 用例，可重复执行）
├── knowledge_base/docs/     # 34 份原始法规文档（19 .doc / 12 docx / 6 PDF，其中部分已转 docx）
├── docs/                    # PRD / UIUX / SPEC-ITER1 / ACCEPTANCE / decisions/
├── .env                     # 已配置 DeepSeek Key（deepseek-chat）——勿提交、勿外泄
├── .env.example             # 环境变量模板
├── start.bat                # 一键启动
└── .venv/                   # Python 3.14 venv（FastAPI/uvicorn/httpx 等已装）
```

### 关键契约（改动前必读，均为验收红线）

1. **SSE 四事件流**：`POST /api/chat` 返回 `event: status`（检索中/生成中）→ `event: sources`（引用数组）→ 多个 `event: delta`（增量文本）→ `event: done`（含 `backend: llm|retrieval`）；错误走 `event: error`，降级/兜底走 `event: notice`。
2. **引用逐字契约**：sources 中 `excerpt`/`full` 字段必须与知识库 chunks 表 `text` 逐字一致，**禁止任何改写、省略号拼接、格式化**。这是产品生命线（PRD AC1.2）。
3. **API 端点清单**：
   - `GET /api/health` — 健康检查（llmConfigured/llmModel/docs/chunks）
   - `GET /api/sources` — 文档清单（totalDocs/indexedDocs/totalChunks）
   - `GET /api/examples` — 示例问题
   - `POST /api/chat` — 问答；请求体 `{question, history?}`，history 为 `[{role:"user"|"assistant", content}]` 最多 6 条（3 轮），assistant content 截断 500 字，非法条目丢弃（见 `_clean_history`）
   - `GET /api/chunk/{chunk_id}` — 条款详情（迭代1新增）：`{chunkId, docId, title, category, clause, pages, seq, text, prev|null, next|null}`，prev/next 为同文档相邻 seq 块；404 返回 `{"error":{"code":"not_found","message":"条款不存在"}}`
4. **前端会话存储契约**：`jz_sessions_v1`（会话数组，updatedAt 降序，上限 30 个，单会话 50 轮，title=首问前 24 字）、`jz_current_v1`（当前会话 id）、`jz_sidebar_v1`（侧边栏展开态）。所有读写 try/catch 静默降级。
5. **数据合规**：服务端不留存用户问题明文日志；问答记录仅存浏览器本地（PRD §10）。
6. **向后兼容红线**：`/api/chat` 不带 history 时，发送给 LLM 的 messages 必须与 v1 逐字节一致（AC-F6-2）。

## 四、运行与环境

```bash
# 启动服务（项目根目录）
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9000
# 访问 http://127.0.0.1:9000

# 后端自检
.venv/Scripts/python.exe -m py_compile app/main.py app/retrieval.py app/llm.py

# 前端语法自检
C:/Users/30832/.workbuddy/binaries/node/versions/22.22.2-3/node.exe --check web/app.js

# E2E 冒烟（需先启动服务；playwright 装在独立 venv）
C:/Users/30832/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/iter1_smoke.py
```

### 已知环境坑（前人踩过，勿重蹈）

| 坑 | 说明 / 绕法 |
|----|------------|
| 系统代理干扰本机请求 | Python urllib/requests 访问 127.0.0.1 会走代理返回 502。必须 `build_opener(ProxyHandler({}))` 或设置 `NO_PROXY` |
| 文件扫描工具不可靠 | Windows 下 Glob `*` 模式可能不返回目录、花括号组合模式失效。**列目录一律用 Python `os.walk`/`os.listdir` 交叉验证**，勿凭单一工具下结论 |
| PowerShell 输出通道偶发失效 | 本会话中 `Get-ChildItem` 输出为空。改用 managed Python（`C:/Users/30832/.workbuddy/binaries/python/versions/3.13.12/python.exe`）最可靠 |
| 项目从 C 盘迁到 D 盘 | 旧脚本（scan_kb.py、phase1 JSON）硬编码 `C:\Users\30832\WorkBuddy\...`。新脚本一律基于 `__file__` 相对定位 |
| C 盘仅剩 ~12GB | 不要往 C 盘装大依赖；playwright 浏览器复用 `%LOCALAPPDATA%\ms-playwright` 已有的 chromium-1234 |
| 0017 曾被误判为扫描件 | 实测文本层可用（5797 字符）。真正无文本层的只有 0003（已 OCR 入库）、0067（已提取）、0004（80MB 图集，未收录） |
| favicon | 已补 web/favicon.svg（迭代1.5），无 404 |

## 五、后续开发计划（按优先级排序）

> 节奏建议：**迭代1.5 清理 → 迭代2 运营监测 → 公网发布 → 迭代3 质量深化 → 迭代4 视数据触发**。每个迭代完成后跑 `tests/` 回归 + 更新 `docs/ACCEPTANCE.md`，再进下一个。

### 迭代 1.5：小清理（可选，约 0.5 天）

| 任务 | 涉及文件 | 验收 |
|------|----------|------|
| 补 favicon（工程蓝图蓝风格 SVG） | `web/` + `app/main.py` 静态资源 | 控制台无 404 |
| 根目录临时 txt/json 整理归档 | 根目录 `phase1_*.json` 等 → 移入 `docs/phase1-evidence/` | 功能不受影响，引用路径同步更新 |

### 迭代 2：运营监测（约 1 周）

**目标**：让 PRD §12 的成功指标第一次变得可测量。

#### 2.1 埋点 SDK（P0）

前端已有 `trackEvent()` 封装骨架与 `history_opened`/`session_switched`/`citation_opened` 三个事件。按 PRD §11 补齐 9 个必埋事件：

| 事件 | 触发时机 | 附加属性 |
|------|----------|----------|
| page_view | 首页加载 | referrer、device 类型 |
| first_question_sent | 新用户（无历史会话）发出第一个问题 | — |
| first_answer_with_citation | 首次收到带引用完整回答 | — |
| question_sent | 每次提问 | 问题字数、是否来自示例引导 |
| answer_completed | 回答完成 | 生成时长、引用条数 |
| answer_failed | 回答失败 | 错误类型分类 |
| session_start | 会话开始 | 本地会话 ID |
| source_panel_opened | 打开知识库来源页 | — |
| error_occurred | 前端/API 错误 | 脱敏后上报 |

- **属性规范**：每事件带 timestamp、device、page_version；不采集 PII、不上报 IP 明文与问题原文（PRD §11）。
- **上报通道（需架构决策）**：本地开发用控制台开关；公网后接自建 `POST /api/open` 计数端点或 Umami 类方案。**服务端只存计数与脱敏属性，不存问题明文**。
- 涉及文件：`web/app.js`（SDK + 埋点调用点）、`app/main.py`（若自建上报端点）。

#### 2.2 F8 回答反馈（P2，RICE 1.5）

- 每条 AI 回答下方加「有帮助 / 无帮助」文字按钮（Lucide 风格 SVG 图标，禁 emoji）。
- 本地暂存（`jz_feedback_v1`）+ 可导出 JSON，支撑「人工抽检 30 条回答」流程。
- 上报 `feedback_submitted` 事件（不含问题原文，只含会话内序号 + 评价）。
- 验收：评价后状态持久、刷新不丢；不破坏 SSE 渲染与错误重试。

#### 2.3 文档时效性标注（P1）

- 风险来源：PRD §13 第 4 条——34 份文档可能含已废止版本。
- 方案：kb.sqlite docs 表加 `valid_status`/`version_date` 列（可空），`tools/build_kb.py` 支持从清单文件注入，`/api/sources` 与来源页 UI 展示「现行有效 / 版本日期 / 待确认」。
- **阻塞项**：文档现行有效性需文档提供方（用户）逐份确认——先做表结构与 UI，状态值待用户回填。
- 涉及文件：`tools/build_kb.py`、`app/main.py`、`web/`（来源页）。

### 迭代 3：质量深化（约 2 周，公网发布后按数据启动）

#### 3.1 混合检索升级（核心）

- **动机**：BM25 单路召回的「未找到」误判率需压到 ≤10%（PRD §12）。
- **前置 POC（OPEN-DECIDIONS 在决项，未决不可跳过）**：本地 bge-small-zh 离线建索引（发布服务器无 GPU，索引离线构建、查询在线算）vs 云端 embedding API（增加延迟与费用）vs 仅 BM25 调优。POC 用固定测试问题集对比召回率/误判率后**落 ADR 到 `docs/decisions/`** 再实现。
- 技术要点：双路召回（BM25 + 向量）→ RRF 融合 → 现有 MIN_COVERAGE 阈值逻辑保留为兜底；向量表新增到 kb.sqlite（`chunk_id` + `embedding` BLOB）。
- 涉及文件：`app/retrieval.py`、`tools/build_kb.py`（建向量索引）、`requirements.txt`。

#### 3.2 0004 图集 OCR 补录（P2）

- 80MB 隐患示意图集（单页大图），本机 Windows.Media.Ocr 分块处理，耗时较长，离线跑。
- 完成后消除来源页「扫描件未收录」已知边界；OCR 文本入 chunks 时 `clause` 标注「图集页 N」。

#### 3.3 F9 知识库管理入口（P2，RICE 1.2）

- 管理员用的「重新解析 / 重建索引」触发入口（简单 CLI 或受保护的管理端点均可，MVP 建议先 CLI 包装 `tools/build_kb.py`）。
- 新增文档走同一流水线：COM 转 docx → 抽取文本 → 分块 → FTS5 索引。
- 验收：新增 1 份测试文档全流程不改代码完成入库并可问答。

### 迭代 4：进阶可选（按运营数据触发，不预先承诺）

| 功能 | 触发条件 | 要点 |
|------|----------|------|
| 访问口令 | 公网扩围后出现盗刷迹象 | 简单口令 → 服务端 session；Key 资损防线 |
| PWA 移动端 | 移动端使用占比可观 | manifest + 离线壳，工地弱网可用 |
| AI 整改文书草稿 | 问答价值验证后 | **PRD 明确不做清单项**，启动前需用户重新决策 |

### 公网发布（随时可做，AC9.3）

- 前置：迭代 1.5 清理完成 + 速率限制确认（已实现：按 IP 限流）+ `.env` 生产配置。
- 发布由主理人通过 WorkBuddy 站点发布流程执行；发布后立即观察 error_occurred 与盗刷迹象。

## 六、开发流程与红线（接手 Agent 必须遵守）

### P0 绝对规则（违反 = 退回重做）

1. **禁止 emoji 作为功能图标**——一律 Lucide 风格内联 SVG（加入 `web/app.js` 的 ICONS 表），尺寸 16/20/24px。
2. **禁止紫色→粉色渐变主视觉**；配色走工程蓝图蓝 #1D4ED8 体系的 CSS 变量，**禁止新增硬编码 hex**（确需新色先定义为变量）。
3. **禁止占位文案**（Lorem ipsum / Welcome to 等），所有文案为真实业务文案。
4. **禁止 bounce/弹性缓动**，沿用 `--ease-standard`。
5. 后端单文件 ≤300 行；改动不破坏 SSE 事件序列、限流、降级、兜底逻辑。

### 项目特有红线

- **引用逐字契约**（见 §三.2）：任何触碰 excerpt/full 的改动都要跑逐字比对回归。
- **数据合规**：服务端不留存问题明文；新增日志必须脱敏。
- **向后兼容**：无 history 的 /api/chat 与 v1 逐字节一致。

### 每迭代固定流程

1. 生成 Spec 增量契约（参照 `docs/SPEC-ITER1.md` 格式：现状基线 / 契约 / EARS 验收标准 / 明确不做）落 `docs/SPEC-ITERn.md`。
2. 开发 + 自检（py_compile / node --check / emoji 正则扫描 / 行数检查）。
3. 集成验收：重启 uvicorn → API 级测试 →（涉 UI 时）Playwright E2E（可扩展 `tests/iter1_smoke.py`）。
4. 结果追加 `docs/ACCEPTANCE.md`；新未决项落 `docs/decisions/OPEN-DECISIONS.md`（只追加 + 就地关闭纪律）。
5. 每次决策（选型/砍功能/用户拍板）写 ADR 到 `docs/decisions/ADR-XXX.md`（MADR 格式）。

### OPEN-DECISIONS 当前在决项（开工迭代3 前必须关闭第 1 条）

| 未决项 | 状态 | 关闭条件 |
|--------|------|----------|
| 混合检索向量方案选型（本地 bge-small-zh vs 云 embedding vs 仅 BM25 调优） | OPEN | POC 对比召回率后定稿 |
| 迭代4 是否启动（口令/PWA/AI 文书） | OPEN | 公网运营指标达阈值或出现盗刷 |

## 七、给接手 Agent 的快速上手清单

1. 读本文档 §一~§四 → 读 `docs/PRD.md` → 读 `docs/SPEC-ITER1.md` + `docs/ACCEPTANCE.md`。
2. 启动服务（§四命令），浏览器打开 http://127.0.0.1:9000 体验现状（引用展开/追问/历史侧边栏）。
3. 跑一遍 `tests/iter1_smoke.py` 确认基线全绿，再动任何代码。
4. 从迭代 1.5（清理）或迭代 2（埋点 SDK）开工；每完成一个功能按 §六.3 验收。
5. 所有改动遵守 §六 红线；遇到定不下来的事，落 OPEN-DECISIONS 而不是擅自发明契约。
