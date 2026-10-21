# -*- coding: utf-8 -*-
"""迭代1 浏览器端 E2E 冒烟：F5 引用上下文 / F6 追问链路 / F7 历史会话持久化"""
import io
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
# 浏览器可执行文件：默认交给 playwright 自己解析；需要指定时设环境变量 JIANAN_CHROME。
# 这里原先写死了开发者本机的绝对路径，换一台机器就必然启动失败（2026-10-21 异机核验实测）。
CHROME = os.environ.get("JIANAN_CHROME", "")
BASE = "http://127.0.0.1:9000"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))


with sync_playwright() as p:
    _launch_kw = {"headless": True}
    if CHROME and os.path.exists(CHROME):
        _launch_kw["executable_path"] = CHROME
    browser = p.chromium.launch(**_launch_kw)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="load")

    # F7: 欢迎语文案已更新 + 侧边栏存在
    body = page.inner_text("body")
    check("F7 欢迎语更新", "自动保存" in body and "左侧历史" in body)
    new_chat = page.get_by_text("新对话", exact=False).first
    check("F7 侧边栏「新对话」按钮", new_chat.count() > 0 if hasattr(new_chat, "count") else new_chat is not None)

    # 发送示例问题（真实 LLM，等待回答完成）
    page.locator(".suggest-card").first.click()
    page.wait_for_selector(".answer-disclaimer", timeout=120000)
    ai_count_1 = page.locator(".msg-ai").count()
    check("问答完成（真实 LLM）", ai_count_1 >= 1, f"msg-ai={ai_count_1}")

    # F6: 继续追问（带 history 走新链路）
    page.fill("#input", "那检测的频次有什么要求？")
    page.click("#sendBtn")
    page.wait_for_selector(".answer-disclaimer >> nth=1", timeout=120000)
    ai_count_2 = page.locator(".msg-ai").count()
    check("F6 追问完成", ai_count_2 == 2, f"msg-ai={ai_count_2}")
    second_answer = page.locator(".msg-ai .answer").nth(1).inner_text()
    check("F6 追回答案含引用语义", ("30min" in second_answer or "30 分钟" in second_answer or "频次" in second_answer or "记录" in second_answer),
          second_answer[:60].replace("\n", " "))

    # F7: 会话已写入 localStorage
    raw = page.evaluate("() => window.localStorage.getItem('jz_sessions_v1')")
    sessions = json.loads(raw) if raw else []
    ok = len(sessions) == 1 and len(sessions[0]["turns"]) == 2 and all(t.get("sources") for t in sessions[0]["turns"])
    check("F7 会话入库（2 轮 + sources）", ok, f"sessions={len(sessions)} turns={len(sessions[0]['turns']) if sessions else 0}")

    # F5: 点击引用 chip，引用面板 + 上下文区
    page.locator(".cite-chip").first.click()
    page.wait_for_selector("#citationModal:not([hidden])", timeout=10000)
    try:
        page.wait_for_selector("#citeContext details", timeout=8000)
        n_ctx = page.locator("#citeContext details").count()
        ctx_text = page.locator("#citeContext").inner_text()
        check("F5 引用上下文渲染", n_ctx >= 1, f"details={n_ctx}")
    except Exception:
        ctx_hidden = page.evaluate("() => document.querySelector('#citeContext')?.hidden")
        check("F5 引用上下文渲染", False, f"citeContext hidden={ctx_hidden}")
    page.click("#citeClose")

    # F7: 刷新恢复当前会话
    page.reload(wait_until="load")
    page.wait_for_timeout(1200)
    restored = page.locator(".msg-ai").count()
    check("F7 刷新恢复会话", restored == 2, f"msg-ai={restored}")

    # F7: 新对话 → 欢迎态；历史切换回来
    page.get_by_text("新对话").first.click()
    page.wait_for_timeout(600)
    check("F7 新对话欢迎态", page.locator(".welcome").count() == 1)
    # 点击历史列表第一项（会话标题）
    items = page.locator(".session-item, [data-session-id]")
    if items.count() == 0:
        # 兜底：找包含首问标题片段的可点击列表项
        items = page.locator("aside button, .sidebar button, #historyPanel button").filter(has_text="有限空间")
    check("F7 历史列表项存在", items.count() >= 1, f"count={items.count()}")
    items.first.click()
    page.wait_for_timeout(800)
    check("F7 切回历史会话", page.locator(".msg-ai").count() == 2, f"msg-ai={page.locator('.msg-ai').count()}")

    page.screenshot(path="tests/iter1_smoke.png", full_page=False)
    browser.close()

fails = [r for r in results if not r[1]]
print()
print("RESULT: %d/%d PASS" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
