# -*- coding: utf-8 -*-
"""迭代2 浏览器端 E2E 冒烟：埋点 SDK 事件链 / F8 反馈持久化 / 时效徽章 / favicon

覆盖 SPEC-ITER2 验收：AC-T1/T2/T3/T5/T9、AC-F8-1/2/3、AC-V2-1、迭代1.5 favicon。
运行前置：服务已启动（127.0.0.1:9000）。
"""
import io
import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
CHROME = r"C:/Users/30832/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe"
BASE = "http://127.0.0.1:9000"

results = []
sent = []  # 捕获的埋点事件

def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # 拦截 /api/track 上报（sendBeacon），捕获事件用于断言
    def handle(route, request):
        try:
            data = json.loads(request.post_data or "{}")
            sent.extend(data.get("events", []))
        except Exception:
            pass
        route.fulfill(status=200, body='{"accepted": 0}')
    page.route("**/api/track", handle)

    page.goto(BASE, wait_until="load")

    # favicon（迭代1.5）
    r = page.request.get(BASE + "/favicon.svg")
    check("1.5 favicon 200", r.status == 200 and "svg" in r.headers.get("content-type", ""))

    # AC-T1-1 page_view 公共属性
    pv = [e for e in sent if e.get("event") == "page_view"]
    ok_pv = bool(pv) and all(
        "timestamp" in e and e.get("device") in ("mobile", "desktop") and e.get("page_version")
        for e in pv)
    check("T1 page_view 携带 timestamp/device/page_version", ok_pv, json.dumps(pv[:1], ensure_ascii=False))

    # 首屏欢迎态存在
    check("首屏欢迎态", page.locator(".welcome").count() > 0)

    # 提问（走真实 LLM）：点击示例问题卡片
    page.locator(".suggest-card").first.click()
    page.wait_for_selector(".msg-ai .answer-disclaimer", timeout=120000)
    check("真实 LLM 回答完成", page.locator(".msg-ai .answer").count() == 1)

    names = [e.get("event") for e in sent]

    # AC-T2-1 首问事件
    check("T2 question_sent(from_example)", "question_sent" in names and any(
        e.get("event") == "question_sent" and e.get("from_example") for e in sent))
    check("T2 first_question_sent 触发一次", names.count("first_question_sent") == 1)

    # AC-T5-1 session_start
    ss = [e for e in sent if e.get("event") == "session_start"]
    check("T5 session_start 携带 sessionId", len(ss) == 1 and bool(ss[0].get("sessionId")))

    # AC-T3-1 首次带引用回答
    fa = [e for e in sent if e.get("event") == "first_answer_with_citation"]
    check("T3 first_answer_with_citation 触发一次", len(fa) == 1 and fa[0].get("citations", 0) >= 1,
          json.dumps(fa, ensure_ascii=False))

    # answer_completed
    ac = [e for e in sent if e.get("event") == "answer_completed"]
    check("T1 answer_completed 携带 backend/ms/citations",
          bool(ac) and all(("backend" in e and "ms" in e and "citations" in e) for e in ac))

    # AC-F8-1 反馈按钮
    fb = page.locator(".msg-ai .feedback-btn")
    check("F8-1 已落定回答显示反馈按钮", fb.count() == 2)
    page.get_by_role("button", name="有帮助").click()
    fb_store = page.evaluate("JSON.parse(localStorage.getItem('jz_feedback_v1') || '{}')")
    fb_ok = len(fb_store) == 1
    if fb_ok:
        k, v = next(iter(fb_store.items()))
        fb_ok = v.get("rating") == "helpful" and "/0" in k and "ts" in v
    check("F8-2 点击有帮助后 jz_feedback_v1 写入", fb_ok, json.dumps(fb_store, ensure_ascii=False))
    check("F8-1 选中态高亮", page.locator(".msg-ai .feedback-btn.is-selected").count() == 1)
    check("F8-2 feedback_submitted 埋点触发", any(
        e.get("event") == "feedback_submitted" and e.get("rating") == "helpful" for e in sent))

    # AC-T9-1 上报不含问题原文
    q_text = page.evaluate("localStorage.getItem('jz_current_v1') ? Object.values(JSON.parse(localStorage.getItem('jz_sessions_v1')))[0].turns[0].q : ''")
    leaked = [e for e in sent if q_text and q_text in json.dumps(e, ensure_ascii=False)]
    check("T9 上报 payload 不含问题原文", not leaked, f"q={q_text[:20]}...")

    # AC-F8-1 刷新后保持
    page.reload(wait_until="load")
    page.wait_for_selector(".msg-ai .feedback-btn", timeout=30000)
    check("F8-1 刷新后反馈选中态保持",
          page.locator(".msg-ai .feedback-btn.is-selected").count() == 1)
    check("F7 刷新后当前会话恢复", page.locator(".msg-ai").count() == 1)

    # AC-V2-1 时效徽章
    # 原断言写死「34 份全部待确认」，那是时效核定前的状态；核定后待确认数会随台账推进而减少。
    # 改为与 /api/sources 的数据层交叉核对：界面"时效待确认"数必须等于数据层 unknown 数。
    page.click("#sourceBtn")
    page.wait_for_selector(".doc-row", timeout=15000)
    n_badge = page.locator(".badge-muted", has_text="时效待确认").count()
    n_rows = page.locator(".doc-row").count()
    try:
        import httpx
        api_unknown = sum(1 for doc in httpx.get(f"{BASE}/api/sources", timeout=15).json()["docs"]
                          if (doc.get("valid_status") or "unknown") == "unknown")
    except Exception as exc:
        api_unknown = None
        check("V2 可读取 /api/sources 作为基准", False, repr(exc))
    check("V2 来源页列出全部 34 份文档", n_rows == 34, f"rows={n_rows}")
    check("V2 界面待确认徽章数与数据层 unknown 数一致",
          api_unknown is not None and n_badge == api_unknown,
          f"界面={n_badge} 数据层={api_unknown}")

    # AC-F8-3 导出入口（有反馈时可见）
    exp = page.locator("#exportFeedbackBtn")
    check("F8-3 有反馈记录时导出按钮可见", exp.is_visible())
    check("F8-3 导出按钮可见性埋点联动（source_panel_opened）",
          any(e.get("event") == "source_panel_opened" for e in sent))

    # 关闭来源面板，再验证引用面板
    page.keyboard.press("Escape")
    page.wait_for_selector("#sourcePanel[hidden]", state="attached", timeout=10000)

    # 引用面板 → citation_opened（沿用事件名）
    page.click(".msg-ai .cite-chip")
    page.wait_for_selector("#citationModal:not([hidden])", timeout=10000)
    check("F5 引用面板可打开", page.locator("#citeFull").count() > 0)
    check("citation_opened 埋点", any(e.get("event") == "citation_opened" for e in sent))

    browser.close()

print()
n_pass = sum(1 for _, ok in results if ok)
print(f"RESULT: {n_pass}/{len(results)} PASS")
sys.exit(0 if n_pass == len(results) else 1)
