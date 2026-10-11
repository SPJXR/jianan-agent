# Spec 增量 — 迭代 1.5 + 迭代 2：清理 / 运营监测

> 生成日期：2026-09-20
> 基于：docs/PRD.md v1.0（§11 埋点、§12 成功指标、§13 风险）+ docs/HANDOFF-后续开发计划.md §五 + 已验收代码（MVP F1-F4 + 迭代1 F5-F7）
> 状态：已锁定（开发唯一依据）
> P0 团队规则全程有效：功能图标仅用 Lucide 风格内联 SVG（ICONS 表），禁止 emoji；主色工程蓝 #1D4ED8（禁止新增硬编码 hex）；禁止占位文案；禁止 bounce 缓动；后端单文件 ≤300 行。

---

## 0. 现状基线（开发前必读）

- 前端已有 `trackEvent(name, props)` 骨架（console.debug 开关 `window.__TRACK_DEBUG__`），已埋 3 事件：`page_view`（无属性）、`question_sent`（from_example/chars，示例与输入框两处）、`citation_opened`、`source_panel_opened`、`history_opened`、`session_switched`、`answer_completed`（backend/ms/citations）、`answer_failed`（error:network）。
- `answer_failed` 目前仅网络层 catch 有埋点；SSE `error` 事件路径未埋。
- 后端 `app/main.py` 266 行，红线 ≤300 行 → 新端点空间有限，埋点计数端点逻辑须精简，或允许略超（见 §6 明确决策）。
- kb.sqlite：`docs(doc_id, filename, title, category, status, note, ocr, pages, chars)`；`kb/docs_meta.json` 为人工核定元数据源。
- `/api/sources` 返回 `docs: [doc_stats 行]`，`doc_stats()` 在 `app/retrieval.py`。
- 前端来源面板 `renderSourceList(data)` 按 category 分组渲染 doc-row，已有 badge（扫描图片版/文本极少）。

## 1. 迭代 1.5：小清理

### 1.1 favicon

- `web/favicon.svg`：工程蓝图蓝风格（#1D4ED8 体系，`--color-primary`），图形复用顶栏 brand-logo 的安全帽图标路径。
- `web/index.html` `<head>` 加 `<link rel="icon" type="image/svg+xml" href="favicon.svg">`。
- 验收：页面加载控制台无 favicon 404。

### 1.2 根目录临时文件归档

- 根目录 `phase1_doc_com_test.json`、`phase1_pdf_docx_test.json`、`docs_list.txt`、`env_check.txt`、`office_check.txt`、`py_check.txt`、`py_check2.txt`、`scan_kb.py` → 移入 `docs/phase1-evidence/`（新建）。
- README 无引用这些文件（已核对）；移动后跑 `py_compile` + 服务健康检查确认无路径依赖。
- 验收：根目录仅保留运行必需文件；服务启动正常。

## 2. 迭代 2.1：埋点 SDK（P0）

### 契约

- 每事件公共属性：`timestamp`(ISO 字符串)、`ts`(ms)、`device`("mobile"|"desktop")、`page_version`("v2")。
- 事件清单（PRD §11 全集，命名 `{对象}_{动作}`）：

| 事件 | 触发点 | 附加属性 |
|------|--------|----------|
| page_view | 页面加载（保持现有） | referrer（document.referrer 非空时） |
| first_question_sent | 无历史会话（`jz_sessions_v1` 为空）的用户首次提问时，随 question_sent 一并触发（一次性，`jz_first_tracked_v1` 标记） | — |
| first_answer_with_citation | 首次收到 done 事件且 citations ≥ 1（一次性，同上标记 `jz_first_tracked_v1` 的 `first_citation` 子键） | citations |
| question_sent | 每次提问（保持现有两处，补齐属性） | chars（字符数）、from_example |
| answer_completed | done 且 backend ∈ {llm, retrieval}（保持现有） | backend、ms、citations |
| answer_failed | SSE error 事件 / fetch 非 200 / 网络异常（补齐 SSE error 路径） | error（脱敏错误码） |
| session_start | 首问落定新会话入库时 | sessionId |
| source_panel_opened | 保持现有 | — |
| citation_opened | 保持现有（PRD 命名 citation_clicked 的落地名，沿用现有代码） | docId |
| error_occurred | 前端未捕获异常（window.onerror / unhandledrejection）、API 请求失败 | message（截断 120 字、去数字与引号脱敏） |
| feedback_submitted | F8 反馈提交（迭代2.2 新增） | rating、turnIndex |

- **合规红线**：不上报问题原文、IP 明文、任何 PII；`error_occurred` 的 message 脱敏（剔除连续 ≥4 位数字与引号包裹内容）。
- **上报通道**：`navigator.sendBeacon("/api/track", JSON.stringify(payload))`；失败静默（不影响主流程）。本地调试沿用 `window.__TRACK_DEBUG__` console 开关，两者并存。
- **服务端** `POST /api/track`：
  - 请求体 `{"events": [{event, ts, ...}]}`，单次 ≤20 条，字段白名单校验，非法整体丢弃。
  - 内存计数器 `_track_counts`（`{event名: {"count": n, "day": YYYYMMDD}}`，按自然日滚动清零），**不落盘、不存属性明细**（合规：服务端只存计数）。
  - `GET /api/track/stats`：返回 `{"counts": {...}, "day": "YYYYMMDD"}`（供运营查看，公网发布前可加口令，属 Backlog）。
  - 限流：复用 IP 限流（独立更宽松额度，60 次/分钟，防 beacon 风暴）。
- 涉及文件：`web/app.js`（trackEvent 增强 + 埋点调用点）、`app/main.py`（端点）。

### 验收（EARS）

| 编号 | 标准 | 优先级 |
|------|------|--------|
| AC-T1-1 | When 加载页面，Then page_view 携带 timestamp/device/page_version 并 sendBeacon 到 /api/track，服务端计数 +1 | P0 |
| AC-T2-1 | When 新用户（无历史会话）首次提问，Then question_sent 与 first_question_sent 均触发一次；再次提问不再触发 first_* | P0 |
| AC-T3-1 | When 首次带引用回答完成，Then first_answer_with_citation 触发一次 | P1 |
| AC-T4-1 | When SSE error 事件到达，Then answer_failed 携带错误码触发 | P0 |
| AC-T5-1 | When 首问落定入库，Then session_start 携带 sessionId 触发 | P1 |
| AC-T6-1 | If 上报请求失败，Then 静默降级，不影响问答主流程 | P0 |
| AC-T7-1 | Given POST /api/track 上报 20+ 超限或字段非法，Then 服务端 400 丢弃且不计数 | P1 |
| AC-T8-1 | When GET /api/track/stats，Then 返回当日各事件计数；重启服务计数清零属已知边界（内存计数，明确不做持久化） | P1 |
| AC-T9-1 | 所有上报 payload 不含问题原文（程序化断言） | P0 |

## 3. 迭代 2.2：F8 回答反馈

### 契约

- 每条**已落定**的 AI 回答（含历史回看）action 区追加两个文字按钮：「有帮助」「无帮助」（Lucide thumbs-up / thumbs-down 内联 SVG，16px）。
- 点击后：按钮组变为已选态（选中高亮，另一个置灰），持久化到 `jz_feedback_v1`：`{"<sessionId>/<turnIndex>": {"rating": "helpful"|"unhelpful", "ts": ms}}`，上限 500 条（FIFO 淘汰）。
- turnIndex 以会话内轮次序号为准（`currentSession.turns.indexOf(turn)`）；历史回看时按同 key 还原已选态。
- 同一轮可改评（点击另一个切换），再次点击同项为取消。
- 触发 `feedback_submitted` 埋点：`{rating, turnIndex}`（无原文）。
- **导出**：来源面板底部加「导出反馈记录」按钮（仅当本地有反馈时显示），下载 `feedback-YYYYMMDD.json`（含 rating/ts/turnIndex/sessionId，不含问答原文）。
- 验收：评价后刷新页面状态保持；不破坏 SSE 渲染与错误重试；进行中（未落定）的回答无反馈按钮。

### 验收（EARS）

| 编号 | 标准 | 优先级 |
|------|------|--------|
| AC-F8-1 | When 回答落定，Then 显示有帮助/无帮助按钮；When 点击，Then 状态持久且刷新后保持 | P0 |
| AC-F8-2 | When 点击反馈，Then feedback_submitted 埋点触发且不含原文；jz_feedback_v1 结构符合契约 | P0 |
| AC-F8-3 | When 打开来源面板且本地有反馈记录，Then 可导出 JSON；无记录时不显示导出入口 | P1 |
| AC-F8-4 | If 反馈记录达 500 条上限，Then 淘汰最旧不报错 | P1 |

## 4. 迭代 2.3：文档时效性标注

### 契约

- `kb/docs_meta.json` 每份文档支持可选字段 `valid_status`（`"effective"`|`"repealed"`|`"draft"`|`"unknown"`，缺省 `"unknown"`=待确认）与 `version_date`（自由文本，如 `"2021-03-01"` 或 `"住建部令第51号（2018修正）"`）。
- `tools/build_kb.py`：docs 表新增列 `valid_status TEXT DEFAULT 'unknown'`、`version_date TEXT`，从 docs_meta.json 注入；重建索引幂等。
- `app/retrieval.py` `doc_stats()` 输出追加这两列。
- 前端来源面板 doc-row：`effective` → 蓝色徽章「现行有效」；`repealed` → 警示徽章「已废止」；`draft` → 中性徽章「征求意见稿/试行」；`unknown` → 灰徽章「时效待确认」；`version_date` 非空时在 doc-sub 追加展示。
- **阻塞项**：34 份文档的 valid_status 实际值需用户逐份确认——本迭代只做表结构 + UI，meta 中缺省全部 unknown，`docs/decisions/OPEN-DECISIONS.md` 登记待回填。
- 兼容性：旧 kb.sqlite 无新列时 `/api/sources` 须正常（build 后才有值；为避免强制重建，doc_stats 查询用 `try/except` 或检列存在——实现时选择「直接重建索引」方案，构建流水线幂等且 422 片段逐字不变，需跑逐字比对回归）。

### 验收（EARS）

| 编号 | 标准 | 优先级 |
|------|------|--------|
| AC-V1-1 | When 重跑 build_kb.py，Then docs 表含 valid_status/version_date 且 34 行数据完整、chunks 逐字不变（回归比对） | P0 |
| AC-V2-1 | When 打开知识库来源页，Then 每份文档显示时效徽章（缺省「时效待确认」）与版本信息（有则显示） | P0 |
| AC-V3-1 | When 人工在 docs_meta.json 回填某文档 valid_status=effective 并重建，Then 来源页该文档显示「现行有效」 | P1 |

## 5. 明确不做（本迭代）

- 埋点属性明细服务端持久化（只存内存计数，合规优先）
- Umami/第三方统计接入（通道抽象已留，公网后再决策）
- 反馈数据的云端汇总（本地导出已满足 30 条人工抽检流程）
- 文档 valid_status 的批量回填（用户阻塞项，只留登记）
- 混合检索 POC（迭代 3，OPEN-DECISIONS 在决项）

## 6. 变更记录

| 日期 | 变更 | 原因 | 影响范围 |
|------|------|------|----------|
| 2026-09-20 | v1.0 锁定 | 迭代 1.5+2 启动 | web/（favicon/app.js/index.html/style.css）、app/main.py、app/retrieval.py、tools/build_kb.py、kb/docs_meta.json、docs/ |
