/* 建安法规问答助手 前端逻辑：SSE 流式渲染 + 引用溯源 + 知识库来源 + 多轮/历史 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const inputEl = $("#input");
const sendBtn = $("#sendBtn");
const charCountEl = $("#charCount");
const sidebarEl = $("#historySidebar");
const backdropEl = $("#historyBackdrop");

const ICONS = {
  sparkles: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  fileText: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>',
  searchX: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m13.5 8.5-5 5"/><path d="m8.5 8.5 5 5"/><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  circleAlert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
  retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
  quote: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/><path d="M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>',
  history: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  thumbsUp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>',
  thumbsDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>',
};

/* ---- 埋点 SDK（迭代2.1）：本地 console 开关（window.__TRACK_DEBUG__）+ sendBeacon 上报 ----
   合规：不上报问题原文/IP/PII；错误消息脱敏（SPEC-ITER2） ---- */
const PAGE_VERSION = "v2";
const K_FIRST_TRACKED = "jz_first_tracked_v1";

function deviceType() { return matchMedia("(max-width: 767px)").matches ? "mobile" : "desktop"; }

function sanitizeMessage(msg) {
  return String(msg)
    .replace(/"[^"]*"/g, "「…」")
    .replace(/‘[^’]*’/g, "「…」")
    .replace(/\d{4,}/g, "…")
    .slice(0, 120);
}

function trackEvent(name, props = {}) {
  try {
    const payload = {
      event: name,
      timestamp: new Date().toISOString(),
      ts: Date.now(),
      device: deviceType(),
      page_version: PAGE_VERSION,
      ...props,
    };
    if (window.__TRACK_DEBUG__) console.debug("[track]", payload);
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/track", new Blob(
        [JSON.stringify({ events: [payload] })], { type: "application/json" }));
    }
  } catch { /* 埋点失败静默降级，不影响主流程 */ }
}

function onceFlag(key) {
  try { return !!JSON.parse(LS.getItem(K_FIRST_TRACKED) || "{}")[key]; } catch { return false; }
}
function markOnce(key) {
  try {
    const flags = JSON.parse(LS.getItem(K_FIRST_TRACKED) || "{}");
    flags[key] = true;
    LS.setItem(K_FIRST_TRACKED, JSON.stringify(flags));
  } catch {}
}

(function trackPageView() {
  const props = {};
  if (document.referrer) props.referrer = document.referrer;
  trackEvent("page_view", props);
})();

/* 全局异常上报（脱敏） */
window.addEventListener("error", (e) => {
  trackEvent("error_occurred", { kind: "js", message: sanitizeMessage(e.message || "") });
});
window.addEventListener("unhandledrejection", (e) => {
  const reason = (e.reason && e.reason.message) || e.reason || "";
  trackEvent("error_occurred", { kind: "promise", message: sanitizeMessage(String(reason)) });
});

/* ================= 存储：会话历史（jz_sessions_v1 / jz_current_v1） ================= */
const LS = window.localStorage;
const K_SESSIONS = "jz_sessions_v1";
const K_CURRENT = "jz_current_v1";
const K_SIDEBAR = "jz_sidebar_v1";
const K_FEEDBACK = "jz_feedback_v1";   // F8：{ "<sessionId>/<turnIndex>": {rating, ts} }
const K_ROLE = "jz_role_v1";           // 迭代5：回答视角角色 id
const MAX_SESSIONS = 30;
const MAX_TURNS = 50;
const MAX_FEEDBACK = 500;

function lsGet(key) { try { return LS.getItem(key); } catch { return null; } }
function lsSet(key, val) { try { LS.setItem(key, val); } catch {} }
function lsGetJSON(key) { try { const v = lsGet(key); return v ? JSON.parse(v) : null; } catch { return null; } }

/* ---- F8 回答反馈存储（不含任何问答原文，SPEC-ITER2 §3） ---- */
function loadFeedback() {
  const obj = lsGetJSON(K_FEEDBACK);
  return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
}
function saveFeedback(obj) {
  const keys = Object.keys(obj);
  if (keys.length > MAX_FEEDBACK) {
    // 超上限时淘汰最早插入的记录（插入序保留）
    for (const k of keys.slice(0, keys.length - MAX_FEEDBACK)) delete obj[k];
  }
  lsSet(K_FEEDBACK, JSON.stringify(obj));
}
function feedbackKey(turn) {
  const idx = currentSession.turns.indexOf(turn);
  return idx >= 0 ? currentSession.id + "/" + idx : null;
}

function loadSessions() {
  const arr = lsGetJSON(K_SESSIONS);
  if (!Array.isArray(arr)) return [];
  return arr.filter((s) => s && s.id).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}
function saveSessions(arr) { lsSet(K_SESSIONS, JSON.stringify(arr.slice(0, MAX_SESSIONS))); }
function upsertSession(sess) {
  let arr = loadSessions().filter((s) => s.id !== sess.id);
  arr.push(sess);
  arr.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  if (arr.length > MAX_SESSIONS) arr = arr.slice(0, MAX_SESSIONS);
  saveSessions(arr);
}
function deleteSession(id) {
  const arr = loadSessions().filter((s) => s.id !== id);
  saveSessions(arr);
  if (currentSession && currentSession.id === id) {
    currentSession = makeSession();
    saveCurrentId(currentSession.id);
    messagesEl.innerHTML = "";
    renderWelcome();
  }
}
function saveCurrentId(id) { lsSet(K_CURRENT, id); }
function loadCurrentId() { return lsGet(K_CURRENT); }
function makeSession() {
  const id = "s_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  return { id, title: "", createdAt: Date.now(), updatedAt: Date.now(), turns: [] };
}

/* ================= 全局状态 ================= */
let currentSession = makeSession();   // 当前会话（首问落定才写入列表）
let currentRole = "default";          // 迭代5：当前回答视角（setupRoles 后以 /api/roles 为准）
let inProgressTurn = null;            // 正在流式生成、尚未落定的轮次
let generating = false;               // 同一会话同时只允许 1 个请求（PRD）
let lastQuestion = "";

// F7 前置：每条 AI 消息绑定自己的引用来源（替代全局 currentSources）
const msgSources = new WeakMap();
function getSources(aiMsg) { return msgSources.get(aiMsg) || []; }

/* ================= 欢迎态 ================= */
async function renderWelcome() {
  messagesEl.innerHTML = `
    <div class="welcome">
      <div class="welcome-hero">
        <div class="welcome-logo">${ICONS.sparkles.replace('stroke-width="2"', 'stroke-width="1.8"')}</div>
        <h1 class="welcome-title">建安法规问答助手</h1>
        <p class="welcome-desc">基于 34 份建筑安全法规与政策文档的专属知识库，每条回答都标注来源条款，可直接核对原文。</p>
      </div>
      <div class="welcome-suggest-label">试试这样问</div>
      <div class="suggest-grid" id="suggestGrid"></div>
      <p class="welcome-note">知识库未收录的内容本助手不会编造回答；对话自动保存在本浏览器中，可随时从左侧历史找回。</p>
    </div>`;
  try {
    const r = await fetch("/api/examples");
    const data = await r.json();
    const grid = $("#suggestGrid");
    data.examples.forEach((ex) => {
      const btn = document.createElement("button");
      btn.className = "suggest-card";
      btn.type = "button";
      btn.innerHTML = `${ICONS.search}<span class="suggest-tag">${escapeHtml(ex.tag)}</span><span>${escapeHtml(ex.q)}</span>`;
      btn.addEventListener("click", () => { sendQuestion(ex.q, { fromExample: true }); });
      grid.appendChild(btn);
    });
  } catch { /* 示例加载失败不阻塞首屏 */ }
}

/* ================= 发问与 SSE ================= */
function sendQuestion(q, opts = {}) {
  if (generating) return;
  const question = (q ?? inputEl.value).trim();
  if (!question) return;
  // 埋点：每次提问（PRD §11）；新用户首问仅一次性触发
  trackEvent("question_sent", { chars: question.length, from_example: !!opts.fromExample, role: currentRole });
  if (!onceFlag("first_question") && loadSessions().length === 0) {
    markOnce("first_question");
    trackEvent("first_question_sent");
  }
  inputEl.value = "";
  autoGrow();
  updateSendState();
  startChat(question);
}

function buildHistory() {
  // F6：最近 3 轮（6 条），assistant 截断至 500 字
  const h = [];
  for (const t of currentSession.turns.slice(-3)) {
    h.push({ role: "user", content: t.q });
    h.push({ role: "assistant", content: (t.a || "").slice(0, 500) });
  }
  return h;
}

function startChat(question) {
  generating = true;
  lastQuestion = question;
  updateSendState();
  if ($(".welcome")) messagesEl.innerHTML = "";

  const thisTurn = { q: question, a: "", sources: [] };
  inProgressTurn = thisTurn;

  const userMsg = document.createElement("div");
  userMsg.className = "msg msg-user";
  userMsg.innerHTML = `<div class="bubble"></div>`;
  userMsg.querySelector(".bubble").textContent = question;
  messagesEl.appendChild(userMsg);

  const aiMsg = document.createElement("div");
  aiMsg.className = "msg msg-ai";
  aiMsg.innerHTML = AI_SHELL;
  aiMsg.querySelector(".status-area").innerHTML =
    `<div class="status-line"><span class="spinner"></span><span class="status-text">正在检索法规库</span></div>`;
  messagesEl.appendChild(aiMsg);
  scrollBottom();

  const history = buildHistory();
  const body = { question, role: currentRole }; // 迭代5：角色随每次提问上送，后端校验回退
  if (history.length) body.history = history; // 不带 history 的路径不存在（有轮次才带）

  fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (resp) => {
    if (!resp.ok) {
      trackEvent("answer_failed", { error: "http_" + resp.status });
      let msg = "服务暂时不可用，请稍后重试";
      try { msg = (await resp.json()).error.message || msg; } catch {}
      throw new Error(msg);
    }
    return resp.body.getReader();
  })
    .then((reader) => handleStream(reader, aiMsg, thisTurn))
    .catch((err) => {
      renderError(aiMsg, err.message || "网络连接异常，请检查网络后重试", question);
      trackEvent("answer_failed", { error: "network" });
    });
}

async function handleStream(reader, aiMsg, thisTurn) {
  const decoder = new TextDecoder();
  let buf = "";
  const statusArea = aiMsg.querySelector(".status-area");
  const answerArea = aiMsg.querySelector(".answer-area");
  const sourcesArea = aiMsg.querySelector(".sources-area");
  const actionArea = aiMsg.querySelector(".action-area");
  let answerText = "";
  let backend = "";
  const t0 = performance.now();

  const applyStatus = (d) => {
    if (d.stage === "retrieving") {
      statusArea.innerHTML = `<div class="status-line"><span class="spinner"></span><span>正在检索 34 份法规文档</span></div>`;
    } else if (d.stage === "rewriting") {
      statusArea.innerHTML = `<div class="status-line"><span class="spinner"></span><span>命中较弱，正在换一种说法重新检索</span></div>`;
    } else if (d.stage === "retrieved") {
      statusArea.innerHTML = `<div class="status-line">${ICONS.check.replace('stroke-width="2"', 'stroke-width="2.2"')}<span class="status-hits">已检索完成 · 命中 ${d.docs} 份文档 ${d.hits} 处条款</span></div><div class="status-line"><span class="spinner"></span><span>正在组织回答</span></div>`;
    }
  };

  const renderAnswer = (caret) => {
    answerArea.innerHTML = `<div class="answer ${caret ? "caret" : ""}">${renderMarkdown(answerText, getSources(aiMsg))}</div>`;
    scrollBottom(true);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const lines = frame.split("\n");
      let event = "message", data = "";
      for (const ln of lines) {
        if (ln.startsWith("event:")) event = ln.slice(6).trim();
        else if (ln.startsWith("data:")) data += ln.slice(5).trim();
      }
      if (!data) continue;
      let d;
      try { d = JSON.parse(data); } catch { continue; }

      if (event === "status") applyStatus(d);
      else if (event === "sources") { const s = d.sources || []; msgSources.set(aiMsg, s); thisTurn.sources = s; }
      else if (event === "notice") {
        statusArea.innerHTML = "";
        answerArea.insertAdjacentHTML("afterbegin",
          `<div class="notice-bar">${ICONS.alert}<span>${escapeHtml(d.message)}</span></div>`);
      } else if (event === "delta") {
        if (!answerArea.querySelector(".answer")) { statusArea.innerHTML = ""; renderAnswer(true); }
        answerText += d.text;
        renderAnswer(true);
      } else if (event === "error") {
        statusArea.innerHTML = "";
        trackEvent("answer_failed", { error: sanitizeMessage(d.code || "unknown") });
        // 渲染中途失败轮不落定
        renderError(aiMsg, d.message, lastQuestion, answerText);
      } else if (event === "done") {
        backend = d.backend;
        statusArea.innerHTML = "";
        finishAnswer(true);
      }
    }
  }
  if (!backend) finishAnswer(false); // 流异常终止兜底（不落定）

  function finishAnswer(settle) {
    renderAnswer(false);
    renderSourcesRow(sourcesArea, getSources(aiMsg));
    renderDisclaimer(aiMsg);
    generating = false;
    updateSendState();
    if (settle) {
      thisTurn.a = answerText;
      thisTurn.sources = getSources(aiMsg);
      currentSession.turns.push(thisTurn);
      if (currentSession.turns.length > MAX_TURNS) currentSession.turns = currentSession.turns.slice(-MAX_TURNS);
      currentSession.updatedAt = Date.now();
      if (!currentSession.title) currentSession.title = thisTurn.q.slice(0, 24);
      inProgressTurn = null;
      upsertSession(currentSession);
      saveCurrentId(currentSession.id);
      renderHistoryList();
      // 埋点：新会话首次落定（PRD §11 session_start）；首次带引用回答（激活核心价值）
      if (currentSession.turns.length === 1) trackEvent("session_start", { sessionId: currentSession.id });
      if (!onceFlag("first_citation") && thisTurn.sources.length > 0) {
        markOnce("first_citation");
        trackEvent("first_answer_with_citation", { citations: thisTurn.sources.length });
      }
    }
    // 操作行需在轮次入库后渲染（F8 反馈按钮依赖 turnIndex）
    renderActions(actionArea, aiMsg, thisTurn, settle);
    if (backend === "llm" || backend === "retrieval") {
      trackEvent("answer_completed", { backend, ms: Math.round(performance.now() - t0), citations: getSources(aiMsg).length });
    }
  }
}

function renderError(aiMsg, msg, question, partial) {
  const answerArea = aiMsg.querySelector(".answer-area");
  const actionArea = aiMsg.querySelector(".action-area");
  answerArea.insertAdjacentHTML("beforeend",
    `<div class="error-bar">${ICONS.circleAlert}<span>${escapeHtml(msg)}</span></div>`);
  const retry = document.createElement("button");
  retry.className = "action-btn";
  retry.innerHTML = `${ICONS.retry}<span>重新生成</span>`;
  retry.addEventListener("click", () => {
    if (generating) return;
    // 移除该条 AI 消息后重发（本轮未落定，直接重发同 history）
    aiMsg.remove();
    startChat(question);
  });
  actionArea.appendChild(retry);
  generating = false;
  updateSendState();
  scrollBottom(true);
}

/* ================= 渲染：markdown-lite + 引用 chip ================= */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderCitations(escaped, sources) {
  // [数字] -> 引用 chip（仅映射存在的来源）
  return escaped.replace(/\[(\d{1,2})\]/g, (m, n) => {
    const s = (sources || []).find((x) => String(x.no) === n);
    if (!s) return m;
    const tip = `《${s.title}》${s.clause}`;
    return `<button class="cite-chip" data-cite="${s.no}" title="${escapeHtml(tip)}" aria-label="查看引用${n}：${escapeHtml(tip)}">${n}</button>`;
  });
}

function inlineMd(s) {
  return s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

/* ---- 硬换行合并：PDF/OCR 抽取文本常在固定列宽断行，显示时合并为连贯段落 ---- */
const CJK_RE = /[\u4e00-\u9fff]/;
const TERMINAL_LIKE = /[。！？；：…”"』」）】〕%°]$/;
const LIST_START_RE = /^(\d{1,3}\s*[.、)]|\d{1,2}\s(?=\S)|[-·•]\s|（[一二三四五六七八九十\d]{1,3}）|[一二三四五六七八九十]{1,3}、)/;
const TABLEISH_RE = /(\|.*\||^\s*\|)/;

function joinHardWrapLines(lines) {
  const out = [];
  for (const raw of lines) {
    const ln = String(raw).trim();
    if (!ln) continue;
    const prev = out[out.length - 1];
    if (
      prev && prev.length >= 6 &&
      !prev.startsWith("—") &&
      !TERMINAL_LIKE.test(prev) &&
      !LIST_START_RE.test(ln) && !TABLEISH_RE.test(prev) && !TABLEISH_RE.test(ln)
    ) {
      out[out.length - 1] = prev + (CJK_RE.test(prev.slice(-1)) || CJK_RE.test(ln[0]) ? "" : " ") + ln;
    } else {
      out.push(ln);
    }
  }
  return out;
}

/* ---- 分块：段落 / 列表项（含续行）/ 块引用 ---- */
function markdownBlocks(md) {
  const blocks = [];
  const LIST_LEAD_RE = /^(\d{1,3}\s*[.、)]|[-·•]\s|（[一二三四五六七八九十\d]{1,3}）|[一二三四五六七八九十]{1,3}、)(\s*)/;
  for (const raw of String(md).split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { blocks.push({ type: "gap" }); continue; }
    if (/^>\s?/.test(line)) {
      const inner = line.replace(/^>\s?/, "");
      const last = blocks[blocks.length - 1];
      if (last && last.type === "bq") last.lines.push(inner);
      else blocks.push({ type: "bq", lines: [inner] });
      continue;
    }
    const m = line.match(LIST_LEAD_RE);
    if (m) {
      blocks.push({ type: "li", lead: m[1].trim() + (m[2] && m[1].trim().length ? " " : ""), text: line.slice(m[0].length), cont: [] });
      continue;
    }
    const last = blocks[blocks.length - 1];
    if (last && last.type === "li") {
      // 无标点结尾的列表项 -> 后续行视为其硬换行续行
      const tail = last.cont.length ? last.cont[last.cont.length - 1] : last.text;
      if (!TERMINAL_LIKE.test(tail) && !LIST_START_RE.test(line)) { last.cont.push(line); continue; }
    }
    const prev = blocks[blocks.length - 1];
    if (prev && prev.type === "p") prev.lines.push(line);
    else blocks.push({ type: "p", lines: [line] });
  }
  return blocks;
}

function renderMarkdown(md, sources) {
  let html = "";
  for (const b of markdownBlocks(md)) {
    if (b.type === "gap") continue;
    if (b.type === "bq") {
      const rows = joinHardWrapLines(b.lines);
      html += `<blockquote>${rows.map((r) => `<div>${renderCitations(inlineMd(escapeHtml(r)), sources)}</div>`).join("")}</blockquote>`;
    } else if (b.type === "li") {
      const text = joinHardWrapLines([b.text, ...b.cont]).join("");
      html += `<p class="ans-li"><span class="li-lead">${escapeHtml(b.lead)}</span> ${renderCitations(inlineMd(escapeHtml(text)), sources)}</p>`;
    } else {
      for (const p of joinHardWrapLines(b.lines)) {
        html += `<p>${renderCitations(inlineMd(escapeHtml(p)), sources)}</p>`;
      }
    }
  }
  return html;
}

/* ================= 引用来源卡片行 ================= */
function clauseOf(s) {
  let c = (s.clause || "").replace(/^[-\s]+/, "").trim();
  if (s.pages && s.docId !== "0004") c += (c ? " · " : "") + s.pages;
  return c || "全文";
}

// 时效徽章（引用卡片与知识库来源抽屉共用同一套口径）
// 词表区分"试行"（已印发、现行有效）与"征求意见稿"（尚未生效），二者效力相反。
function validityBadge(vs) {
  return {
    effective: `<span class="badge badge-ok">现行有效</span>`,
    trial: `<span class="badge badge-ok">试行·现行有效</span>`,
    consultation: `<span class="badge badge-danger">征求意见稿·未生效</span>`,
    repealed: `<span class="badge badge-danger">已废止</span>`,
    na: `<span class="badge badge-muted">附件·无独立时效</span>`,
  }[(vs || "unknown")] || `<span class="badge badge-muted">时效待确认</span>`;
}

function renderSourcesRow(area, sources) {
  sources = sources || [];
  if (!sources.length) return;
  const row = sources.slice(0, 8).map((s) => `
    <button class="source-card" data-cite="${s.no}" type="button" aria-label="查看《${escapeHtml(s.title)}》原文">
      <div class="sc-title">${escapeHtml(s.title)}</div>
      <div class="sc-std">${escapeHtml(s.docId)} ${validityBadge(s.validStatus)}</div>
      <div class="sc-clause">${escapeHtml(clauseOf(s))}</div>
    </button>`).join("");
  area.innerHTML = `
    <div class="sources-block">
      <div class="sources-title">${ICONS.quote}<span>引用来源 · 命中 ${new Set(sources.map((s) => s.docId)).size} 份文档 ${sources.length} 处条款</span></div>
      <div class="sources-row">${row}</div>
    </div>`;
  // 点击事件统一由 document 委托处理（见底部）
}

// 引用 chip / 来源卡片的统一事件委托（按消息归属查找来源）
document.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-cite]");
  if (!chip) return;
  e.preventDefault();
  const msg = chip.closest(".msg-ai");
  const sources = msg ? getSources(msg) : [];
  const s = sources.find((x) => x.no === Number(chip.dataset.cite));
  if (s) openCitation(s);
});

function renderActions(area, aiMsg, turn, settled) {
  area.innerHTML = "";
  const copy = document.createElement("button");
  copy.className = "action-btn";
  copy.innerHTML = `${ICONS.copy}<span>复制</span>`;
  copy.addEventListener("click", async () => {
    const text = aiMsg.querySelector(".answer")?.innerText || "";
    try { await navigator.clipboard.writeText(text); copy.querySelector("span").textContent = "已复制"; } catch {}
    setTimeout(() => { const s = copy.querySelector("span"); if (s) s.textContent = "复制"; }, 1600);
  });
  const retry = document.createElement("button");
  retry.className = "action-btn";
  retry.innerHTML = `${ICONS.retry}<span>重新生成</span>`;
  retry.addEventListener("click", () => {
    if (generating) return;
    // 重新生成：剔除本次及之后轮次，重发同一 history（不含未完成轮）
    const idx = currentSession.turns.indexOf(turn);
    if (idx >= 0) currentSession.turns.length = idx;
    lastQuestion = turn.q;
    aiMsg.remove();
    startChat(turn.q);
  });
  area.append(copy, retry);
  if (settled) renderFeedbackButtons(area, turn);
}

/* ---- F8 回答反馈：有帮助/无帮助（仅已落定回答，SPEC-ITER2 §3） ---- */
function renderFeedbackButtons(area, turn) {
  const key = feedbackKey(turn);
  if (!key) return;
  const wrap = document.createElement("div");
  wrap.className = "feedback-group";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "回答反馈");
  const mk = (rating, icon, label) => {
    const b = document.createElement("button");
    b.className = "action-btn feedback-btn";
    b.type = "button";
    b.dataset.rating = rating;
    b.innerHTML = `${icon}<span>${label}</span>`;
    return b;
  };
  const up = mk("helpful", ICONS.thumbsUp, "有帮助");
  const down = mk("unhelpful", ICONS.thumbsDown, "无帮助");
  const applyState = () => {
    const cur = loadFeedback()[key];
    up.classList.toggle("is-selected", cur && cur.rating === "helpful");
    down.classList.toggle("is-selected", cur && cur.rating === "unhelpful");
  };
  const onClick = (rating) => {
    const fb = loadFeedback();
    const now = fb[key];
    const next = now && now.rating === rating ? null : rating; // 同项取消 / 切换
    if (next) fb[key] = { rating: next, ts: Date.now() };
    else delete fb[key];
    saveFeedback(fb);
    trackEvent("feedback_submitted", { rating: next || "revoked", turn_index: Number(key.split("/")[1]) });
    applyState();
  };
  up.addEventListener("click", () => onClick("helpful"));
  down.addEventListener("click", () => onClick("unhelpful"));
  applyState();
  wrap.append(up, down);
  area.appendChild(wrap);
}

function renderDisclaimer(aiMsg) {
  aiMsg.querySelector(".action-area").insertAdjacentHTML("afterend",
    `<div class="answer-disclaimer">本回答由 AI 基于知识库收录的法规文本生成，仅供参考。正式执行请以官方发布的现行有效版本为准。</div>`);
}

/* ================= 引用原文面板（含 F5 上下文） ================= */
function openCitation(s) {
  trackEvent("citation_opened", { docId: s.docId });
  $("#citeDocTitle").textContent = s.title;
  const metaBits = [s.docId, s.category, clauseOf(s)].filter(Boolean);
  $("#citeMeta").innerHTML = metaBits.map((b) => `<span class="std-no">${escapeHtml(b)}</span>`).join(" · ");
  // 高亮问题中的关键词（显示时合并硬换行；复制保留原文）
  const full = s.full || "";
  const rows = joinHardWrapLines(full.split("\n"));
  $("#citeFull").innerHTML = `<div class="cite-full">${rows.map((r) => `<div>${highlightTerms(escapeHtml(r))}</div>`).join("")}</div>`;
  $("#citeCopy").onclick = async () => {
    try { await navigator.clipboard.writeText(full); $("#citeCopy").textContent = "已复制"; } catch {}
    setTimeout(() => { $("#citeCopy").textContent = "复制条款"; }, 1600);
  };
  openModal("#citationModal");
  loadCitationContext(s);
}

async function loadCitationContext(s) {
  const el = $("#citeContext");
  if (!el) return;
  if (s.chunkId === undefined || s.chunkId === null) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  el.innerHTML = `<div class="cite-ctx-loading">正在加载相邻条款</div>`;
  try {
    const r = await fetch(`/api/chunk/${encodeURIComponent(s.chunkId)}`);
    if (!r.ok) throw new Error("not_found");
    const data = await r.json();
    renderContext(el, data);
  } catch {
    el.hidden = true; el.innerHTML = ""; // 接口失败静默隐藏
  }
}

function renderContext(el, data) {
  const block = (label, node) => {
    if (!node) return "";
    const pre = String(node.text || "").slice(0, 40);
    const rows = joinHardWrapLines(String(node.text || "").split("\n"));
    const body = rows.map((r) => `<div>${escapeHtml(r)}</div>`).join(""); // 逐字，不改写
    return `<details class="cite-ctx-block">
      <summary><span class="cite-ctx-label">${escapeHtml(label)}</span><span class="cite-ctx-sum">${escapeHtml(node.clause || "")} · ${escapeHtml(pre)}</span></summary>
      <div class="cite-ctx-body">${body}</div>
    </details>`;
  };
  const inner = block("前文", data.prev) + block("后文", data.next);
  if (!inner) { el.hidden = true; return; }
  el.innerHTML = `<div class="cite-ctx"><div class="cite-ctx-title">${ICONS.fileText}<span>相邻条款</span></div>${inner}</div>`;
}

function highlightTerms(escapedFull) {
  const terms = [...new Set((inputEl.value || lastQuestion || "")
    .split(/[^\u4e00-\u9fffA-Za-z0-9]+/).filter((t) => t.length >= 2))]
    .sort((a, b) => b.length - a.length).slice(0, 6);
  let out = escapedFull;
  for (const t of terms) {
    const safe = escapeHtml(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    out = out.replace(new RegExp(safe, "g"), (m) => `<mark>${m}</mark>`);
  }
  return out;
}

/* ================= 知识库来源面板 ================= */
let sourcesLoaded = false;
async function openSources() {
  openModal("#sourcePanel");
  trackEvent("source_panel_opened");
  updateFeedbackExport();
  if (sourcesLoaded) return;
  try {
    const r = await fetch("/api/sources");
    const data = await r.json();
    renderSourceList(data);
    sourcesLoaded = true;
  } catch {
    trackEvent("error_occurred", { kind: "api", api: "sources", message: "fetch_failed" });
    $("#sourceList").innerHTML = `<div class="source-loading">加载失败，请关闭后重试</div>`;
  }
}

function renderSourceList(data) {
  $("#sourceSummary").textContent = `共 ${data.totalDocs} 份文档（其中 ${data.indexedDocs} 份已建立检索索引，共 ${data.totalChunks} 个条款片段）`;
  const list = $("#sourceList");
  const groups = {};
  for (const d of data.docs) (groups[d.category || "其他"] ||= []).push(d);
  let html = "";
  for (const cat of Object.keys(groups).sort()) {
    html += `<div class="source-group-label">${escapeHtml(cat)}</div>`;
    for (const d of groups[cat]) {
      let badge = "";
      if (d.status === "scan") badge = `<span class="badge badge-warn">扫描图片版</span>`;
      else if (d.status === "low_text") badge = `<span class="badge badge-muted">文本极少</span>`;
      // 文档时效性标注（迭代2.3）：effective/repealed/draft/缺省 unknown=待确认
      const vBadge = validityBadge(d.valid_status);
      html += `
        <div class="doc-row">
          ${ICONS.fileText.replace('stroke-width="2"', 'stroke-width="1.8"')}
          <div class="doc-main">
            <div class="doc-title">${escapeHtml(d.title)}</div>
            <div class="doc-sub">
              <span>${escapeHtml(d.doc_id)}</span>
              ${d.note ? `<span>${escapeHtml(d.note)}</span>` : ""}
              ${d.version_date ? `<span>${escapeHtml(d.version_date)}</span>` : ""}
              ${d.n_chunks > 0 ? `<span class="doc-chunks">${d.n_chunks} 个片段</span>` : ""}
            </div>
          </div>
          ${vBadge}
          <span class="badge badge-cat">${escapeHtml(cat)}</span>
          ${badge}
        </div>`;
    }
  }
  list.innerHTML = html;
}

/* ---- F8 反馈导出（仅本地记录，不含问答原文，SPEC-ITER2 §3） ---- */
function updateFeedbackExport() {
  const btn = $("#exportFeedbackBtn");
  if (btn) btn.hidden = Object.keys(loadFeedback()).length === 0;
}

function exportFeedback() {
  const items = Object.entries(loadFeedback()).map(([key, v]) => {
    const [sessionId, turnIndex] = key.split("/");
    return { sessionId, turnIndex: Number(turnIndex), rating: v.rating, ts: v.ts };
  });
  const payload = { exportedAt: new Date().toISOString(), count: items.length, feedback: items };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "feedback-" + new Date().toISOString().slice(0, 10).replace(/-/g, "") + ".json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$("#exportFeedbackBtn")?.addEventListener("click", exportFeedback);

/* ================= 浮层控制 ================= */
function openModal(sel) { $(sel).hidden = false; document.body.style.overflow = "hidden"; }
function closeModals() {
  document.querySelectorAll(".modal").forEach((m) => (m.hidden = true));
  document.body.style.overflow = "";
}
document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModals));
$("#sourceBtn").addEventListener("click", openSources);
$("#sourceClose").addEventListener("click", closeModals);
$("#citeClose").addEventListener("click", closeModals);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });

/* ================= 历史侧边栏 ================= */
function isMobile() { return matchMedia("(max-width: 767px)").matches; }

function relTime(ts) {
  const d = Date.now() - ts;
  if (d < 60000) return "刚刚";
  if (d < 3600000) return Math.floor(d / 60000) + " 分钟前";
  if (d < 86400000) return Math.floor(d / 3600000) + " 小时前";
  if (d < 7 * 86400000) return Math.floor(d / 86400000) + " 天前";
  const dt = new Date(ts);
  return `${dt.getMonth() + 1}月${dt.getDate()}日`;
}

function renderHistoryList() {
  const list = $("#historyList");
  if (!list) return;
  const sessions = loadSessions();
  if (!sessions.length) {
    list.innerHTML = `<div class="history-empty">还没有历史对话<br>开始提问后会自动保存</div>`;
    return;
  }
  list.innerHTML = sessions.map((s) => {
    const active = currentSession && currentSession.id === s.id ? " is-active" : "";
    const title = s.title || "新对话";
    return `<div class="history-item${active}" data-sid="${escapeHtml(s.id)}">
      <button class="history-item-main" type="button" data-open="${escapeHtml(s.id)}" aria-label="打开对话">
        <div class="history-item-title">${escapeHtml(title)}</div>
        <div class="history-item-time">${relTime(s.updatedAt)}</div>
      </button>
      <button class="history-del" type="button" data-del="${escapeHtml(s.id)}" aria-label="删除对话">${ICONS.trash}</button>
    </div>`;
  }).join("");
}

$("#historyList")?.addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.stopPropagation();
    const id = del.dataset.del;
    if (confirm("确定删除该对话吗？此操作不可恢复。")) {
      deleteSession(id);
      renderHistoryList();
    }
    return;
  }
  const open = e.target.closest("[data-open]");
  if (open) switchSession(open.dataset.open);
});

function switchSession(id) {
  const sess = loadSessions().find((s) => s.id === id);
  if (!sess) return;
  trackEvent("session_switched");
  loadSession(sess);
}

function loadSession(sess) {
  currentSession = sess;
  saveCurrentId(sess.id);
  messagesEl.innerHTML = "";
  for (const turn of sess.turns) renderStoredTurn(turn);
  scrollBottom(true);
  renderHistoryList();
  closeHistoryDrawer();
}

function renderStoredTurn(turn) {
  const userMsg = document.createElement("div");
  userMsg.className = "msg msg-user";
  userMsg.innerHTML = `<div class="bubble"></div>`;
  userMsg.querySelector(".bubble").textContent = turn.q;
  messagesEl.appendChild(userMsg);

  const aiMsg = document.createElement("div");
  aiMsg.className = "msg msg-ai";
  aiMsg.innerHTML = AI_SHELL;
  messagesEl.appendChild(aiMsg);
  const sources = turn.sources || [];
  msgSources.set(aiMsg, sources);
  aiMsg.querySelector(".status-area").innerHTML = "";
  aiMsg.querySelector(".answer-area").innerHTML =
    `<div class="answer">${renderMarkdown(turn.a || "", sources)}</div>`;
  renderSourcesRow(aiMsg.querySelector(".sources-area"), sources);
  renderActions(aiMsg.querySelector(".action-area"), aiMsg, turn, true);
  renderDisclaimer(aiMsg);
}

function newChat() {
  if (generating) return;
  currentSession = makeSession();
  saveCurrentId(currentSession.id);
  messagesEl.innerHTML = "";
  renderWelcome();
  renderHistoryList();
  closeHistoryDrawer();
  inputEl.focus();
}

function toggleHistory() {
  if (isMobile()) {
    const open = sidebarEl.classList.toggle("history-sidebar--open");
    if (backdropEl) backdropEl.hidden = !open;
    if (open) trackEvent("history_opened");
  } else {
    const collapsed = sidebarEl.classList.toggle("history-sidebar--collapsed");
    lsSet(K_SIDEBAR, collapsed ? "collapsed" : "expanded");
    if (!collapsed) trackEvent("history_opened");
  }
}
function closeHistoryDrawer() {
  if (!sidebarEl) return;
  sidebarEl.classList.remove("history-sidebar--open");
  if (backdropEl) backdropEl.hidden = true;
}

function restoreSidebarState() {
  if (isMobile()) { sidebarEl.classList.remove("history-sidebar--collapsed"); return; }
  if (lsGet(K_SIDEBAR) === "collapsed") sidebarEl.classList.add("history-sidebar--collapsed");
}

$("#historyBtn")?.addEventListener("click", toggleHistory);
$("#historyClose")?.addEventListener("click", toggleHistory);
$("#newChatBtn")?.addEventListener("click", newChat);
backdropEl?.addEventListener("click", closeHistoryDrawer);

/* ================= 输入框 ================= */
function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 144) + "px";
}
function updateSendState() {
  const has = inputEl.value.trim().length > 0;
  sendBtn.disabled = !has || generating;
  charCountEl.textContent = inputEl.value.length ? `${inputEl.value.length}/2000` : "";
}
inputEl.addEventListener("input", () => { autoGrow(); updateSendState(); });
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendQuestion();
  }
});
sendBtn.addEventListener("click", () => sendQuestion());

function scrollBottom(force) {
  const main = $("#chatMain");
  const near = main.scrollHeight - main.scrollTop - main.clientHeight < 160;
  if (near || force) main.scrollTop = main.scrollHeight;
}

/* AI 消息外壳（流式生成与历史回看共用） */
const AI_SHELL = `
  <div class="ai-head">
    <span class="ai-avatar">${ICONS.sparkles}</span>
    <span class="ai-label">建安法规问答助手</span>
  </div>
  <div class="ai-content">
    <div class="status-area"></div>
    <div class="answer-area"></div>
    <div class="sources-area"></div>
    <div class="action-area"></div>
  </div>`;

/* ================= 角色选择（迭代5 / ADR-003） ================= */
const roleBar = $("#roleBar");
const roleSelect = $("#roleSelect");
const roleHint = $("#roleHint");

function updateRoleHint() {
  const opt = roleSelect.selectedOptions[0];
  roleHint.textContent = (opt && opt.dataset.short) || "";
}

async function setupRoles() {
  try {
    const r = await fetch("/api/roles");
    if (!r.ok) return;                       // 接口不可用：整条隐藏，行为与 V4 一致
    const data = await r.json();
    if (!Array.isArray(data.roles) || !data.roles.length) return;
    const saved = lsGet(K_ROLE);
    const valid = data.roles.some((o) => o.id === saved);
    currentRole = valid ? saved : (data.default || "default");
    for (const o of data.roles) {
      const opt = document.createElement("option");
      opt.value = o.id;
      opt.textContent = o.label;
      opt.dataset.short = o.short || "";
      roleSelect.appendChild(opt);
    }
    roleSelect.value = currentRole;
    updateRoleHint();
    roleSelect.addEventListener("change", () => {
      currentRole = roleSelect.value;
      lsSet(K_ROLE, currentRole);
      updateRoleHint();
      trackEvent("role_changed", { role: currentRole });
    });
    roleBar.hidden = false;
  } catch { /* 拉取失败不影响问答主流程 */ }
}

/* ================= 启动：恢复当前会话或欢迎态 ================= */
function init() {
  const curId = loadCurrentId();
  const cur = curId ? loadSessions().find((s) => s.id === curId) : null;
  if (cur && cur.turns && cur.turns.length) loadSession(cur);
  else renderWelcome();
  renderHistoryList();
  restoreSidebarState();
  setupRoles();
}
init();
updateSendState();
