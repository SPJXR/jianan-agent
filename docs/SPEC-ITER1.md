# Spec 增量 — 迭代 1：体验深化（F5 / F6 / F7）

> 生成日期：2026-09-20
> 基于：docs/PRD.md v1.0（§5 RICE、§11 数据、§13 风险）+ 现有已验收代码（MVP F1-F4）
> 状态：已锁定（开发唯一依据）
> P0 团队规则全程有效：功能图标仅用现有 Lucide 风格内联 SVG（ICONS 表），禁止 emoji；主色工程蓝 #1D4ED8；禁止占位文案；禁止 bounce 缓动。

---

## 0. 现状基线（开发前必读）

- 引用契约已存在：`_sources_payload` 产出 `{no, docId, title, category, clause, pages, excerpt(逐字), full(逐字)}`。
- 前端已有：引用 chip（`.cite-chip`）、引用原文面板（`openCitation`，展示 `s.full` + 关键词高亮）、知识库来源抽屉、连续会话消息流。
- **前端重构点（F7 前置）**：`currentSources` 是全局变量，历史回看时无法区分各条消息的来源。必须改为「每条 AI 消息绑定自己的 sources」（闭包或 WeakMap），chip 事件委托按消息归属查找。
- kb.sqlite：`chunks(chunk_id INTEGER PK, doc_id, seq, clause, pages, text)`；`docs(doc_id, filename, title, category, status, note, ocr, pages, chars)`。`seq` 从 0 连续递增（同 doc 内）。

## 1. F5 引用原文展开 — 相邻条款上下文

### API（新增）

`GET /api/chunk/{chunk_id}`

- 200：
```json
{
  "chunkId": 123, "docId": "0069", "title": "...", "category": "...",
  "clause": "第X条", "pages": "P12", "seq": 5, "text": "本条款逐字全文",
  "prev": {"seq": 4, "clause": "...", "pages": "...", "text": "逐字"} | null,
  "next": {"seq": 6, "clause": "...", "pages": "...", "text": "逐字"} | null
}
```
- `prev` = 同 doc_id 且 seq-1 的块；`next` = seq+1；不存在则为 null（首/末块）。
- 404：`{"error": {"code": "not_found", "message": "条款不存在"}}`。
- 性能：单次查询 < 200ms（本地）。实现放 `app/retrieval.py` 新函数 `get_chunk_context(chunk_id)`，路由加在 `app/main.py` 静态挂载之前。

### 前端

- 引用原文面板（`#citationModal`）原文区块下方新增「上下文」区：
  - 打开面板时异步拉取 `/api/chunk/{chunkId}`——因此 sources payload 必须携带 `chunkId`（后端在 `_sources_payload` 中追加该字段，向前兼容）。
  - 渲染「前文 / 后文」两个灰底折叠块（`<details>`，默认收起，摘要行显示该块 clause + 前 40 字）；展开显示逐字全文（复用 `joinHardWrapLines`）。
  - prev/next 为 null 则不渲染对应块；接口失败静默隐藏上下文区（不阻塞主原文展示）。
  - 「复制条款」行为不变（仅复制本条款逐字全文）。
- 逐字性红线：上下文文本与 kb.sqlite 存储逐字一致，不做任何改写。

## 2. F6 多轮追问

### API（扩展，向后兼容）

`POST /api/chat` 请求体新增可选字段：

```json
{ "question": "那检测频率呢？", "history": [ {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."} ] }
```

- `history`：最近对话，最多取 **3 轮（6 条）**；assistant 内容截断至 500 字；非法条目（role 不符/空 content/超 2000 字）直接丢弃；字段缺省时行为与 v1 完全一致。
- 检索改写：检索 query = 当前 question + 上一条 user 提问（若存在且与当前不同）——只影响检索词召回，`MIN_COVERAGE` 等阈值逻辑不变。
- LLM messages：system 不变 → history（user/assistant 交替，user 为原始问题纯文本）→ 本次 user（`法规片段：\n{context}\n\n用户问题：{question}`，格式不变）。
- `app/llm.py` 的 `stream_chat(sources, question)` 增加 `history` 参数。
- SSE 事件序列不变。

### 前端

- 维护会话轮次数组（每轮 `{q, a, sources}`，在 `finishAnswer` 时落定）；发送时携带最近 3 轮 history。
- 「重新生成」重发同一 history（不含本次未完成轮）。
- 欢迎语提示语不变。

## 3. F7 历史会话（浏览器本地存储，服务端不留存）

### 存储契约

- key：`jz_sessions_v1` → 数组 `[{id, title, createdAt, updatedAt, turns}]`，按 `updatedAt` 降序；上限 **30 个会话**，超出淘汰最旧；单会话 turns 上限 **50** 轮。
- key：`jz_current_v1` → 当前会话 id。
- `turns[i] = {q, a, sources: [_sources_payload 同构数组]}`（a 为完整 markdown 文本，渲染时走 `renderMarkdown`；sources 供引用面板还原）。
- title = 首问前 24 字。存储读写须 try/catch（隐私模式 / 配额满不报错，静默降级为无历史）。

### UI

- 左侧历史侧边栏：桌面端默认展开、可收起（记忆展开态）；移动端（<768px）为抽屉，由顶栏新增「历史」按钮呼出。
- 结构：顶部「新对话」按钮（icon：plus/文件，用 Lucide 内联 SVG）→ 会话列表（标题 + 相对时间如「5 分钟前」，当前会话高亮）→ 每项 hover 出删除按钮（确认后删除，误删不可恢复需确认文案）。
- 行为：
  - 问答完成即写入/更新当前会话；刷新页面后自动恢复当前会话视图（只读回看态，输入框可用，继续提问续写同一会话）。
  - 点击历史会话：切换渲染该会话全部 turns（逐字还原，引用可点开），并置为当前会话。
  - 「新对话」：清空消息区显示欢迎态，创建新会话记录（首问落定才真正入库）。
- 欢迎语文案更新：「刷新页面对话不会保留」→「对话自动保存在本浏览器中，可随时从左侧历史找回」。
- 免责声明、欢迎示例问题、SSE 渲染逻辑均不变。

## 4. 验收标准（EARS）

| 编号 | 功能 | 标准 | 优先级 |
|------|------|------|--------|
| AC-F5-1 | F5 | When 点击任一引用 chip，Then 面板显示本条款逐字全文 + 前后相邻条款上下文（存在时），文本与 kb.sqlite 逐字一致 | P0 |
| AC-F5-2 | F5 | If 条款为文档首/末块，Then prev/next 为 null 且不渲染空区块；If 接口失败，Then 仅隐藏上下文区，主原文正常 | P0 |
| AC-F6-1 | F6 | When 第二问为指代性追问（如「那检测频率呢」），Then 检索 query 含上一问关键词且回答基于命中条款并带引用 | P0 |
| AC-F6-2 | F6 | If 请求不带 history 字段，Then 全链路行为与 v1 完全一致（回归） | P0 |
| AC-F7-1 | F7 | When 一轮问答完成，Then 会话写入浏览器本地存储；When 刷新页面，Then 自动恢复当前会话视图 | P0 |
| AC-F7-2 | F7 | When 点击历史会话，Then 逐字还原全部问答与引用，引用面板可打开且内容一致 | P0 |
| AC-F7-3 | F7 | When 新建对话，Then 进入欢迎态且旧会话保留；When 删除会话，Then 需确认且列表即时更新 | P1 |
| AC-F7-4 | F7 | If 会话达 30 个上限，Then 新会话自动淘汰最旧，不报错 | P1 |

## 5. 明确不做（本迭代）

- 服务端会话存储 / 多设备同步（PRD 数据合规约束）
- 追问的查询改写用 LLM（首版用规则拼接，避免额外延迟与费用）
- 引用上下文的跨文档拼接（仅同文档相邻 seq）
- 历史会话导出 / 搜索

## 6. 变更记录

| 日期 | 变更 | 原因 | 影响范围 |
|------|------|------|----------|
| 2026-09-20 | v1.0 锁定 | 迭代 1 启动 | app/main.py、app/retrieval.py、app/llm.py、web/app.js、web/index.html、web/style.css |
