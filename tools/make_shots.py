# -*- coding: utf-8 -*-
"""生成参赛作品截图（数媒限 10 张）与移动端适配实拍。

    python tools/make_shots.py            # 全部 10 张
    python tools/make_shots.py --only 1,2,9

说明：
- 浏览器用本机 Edge（channel="msedge"），不下载 chromium 发行包。
- 降级模式截图会另起一个 **清空 LLM_API_KEY** 的服务实例，确保拍到的是真实降级行为，
  而不是人为摆拍。
- 每张图写完后打印尺寸，便于确认不是空白页。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

if hasattr(sys.stdout, "buffer"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "docs", "screenshots")
PY = sys.executable
Q_MAIN = "有限空间作业前需要检测哪些气体？"
Q_OUTSIDE = "美国OSHA对脚手架的要求"

SHOTS = [
    ("01-首页-欢迎与示例问题", "desktop", "home"),
    ("02-完整问答-行内引用标注", "desktop", "answer"),
    ("03-引用原文面板-条款全文与上下文", "desktop", "cite"),
    ("04-知识库来源-时效徽章", "desktop", "sources"),
    ("05-角色化-项目经理视角同一问题", "desktop", "role"),
    ("06-库外问题-诚实拒答", "desktop", "refuse"),
    ("07-降级模式-未配置Key时展示原文", "desktop", "degraded"),
    ("08-移动端-首页", "mobile", "home"),
    ("09-移动端-问答与引用", "mobile", "answer"),
    ("10-移动端-来源抽屉", "mobile", "sources"),
]


def wait_server(url, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=3) as r:
                if r.status == 200:
                    return json.loads(r.read().decode())
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"服务未在 {timeout}s 内就绪：{url}")


def launch(port, clear_key=False):
    env = dict(os.environ)
    if clear_key:
        env["LLM_API_KEY"] = ""
    log = open(os.path.join(BASE, "tests", f"_shots_{port}.log"), "wb")
    p = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app",
                          "--host", "127.0.0.1", "--port", str(port)],
                         cwd=BASE, stdout=log, stderr=subprocess.STDOUT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        h = wait_server(url)
    except RuntimeError:
        p.terminate()
        raise
    return p, url, h


def pick_role(page, label):
    """按显示名选中某个回答视角，并确认真的选上了。

    必须在 goto **之后**调用：角色 id 持久化在 localStorage（app.js:929），
    而每次建 context 都注入了 localStorage.clear()，所以 goto 前选好的角色
    会被重新加载的页面重置成 default —— 上一版就把「项目经理」拍成了「通用」。
    """
    page.wait_for_selector("#roleBar:not([hidden])", timeout=15000)
    opts = page.locator("#roleSelect option")
    val = None
    for i in range(opts.count()):
        if label in (opts.nth(i).inner_text() or ""):
            val = opts.nth(i).get_attribute("value")
            break
    if val is None:
        raise RuntimeError(f"roleSelect 里没有「{label}」，实际选项数={opts.count()}")
    page.select_option("#roleSelect", val)
    got = page.evaluate("document.querySelector('#roleSelect').value")
    if got != val:
        raise RuntimeError(f"角色未生效：期望 {val}，实际 {got}")
    page.wait_for_timeout(200)


def ask(page, url, q, role=None):
    page.goto(url, wait_until="load")
    page.wait_for_selector("#input", timeout=20000)
    if role:
        pick_role(page, role)
    page.fill("#input", q)
    page.wait_for_function("!document.querySelector('#sendBtn').disabled", timeout=10000)
    page.click("#sendBtn")
    # 等回答真正结束：反馈按钮在答案完成后才出现
    page.wait_for_selector(".msg-ai .feedback-btn", timeout=90000)
    page.wait_for_timeout(700)


def capture(page, url, kind, path):
    if kind == "home":
        page.goto(url, wait_until="load")
        page.wait_for_selector(".suggest-card", timeout=20000)
        page.wait_for_timeout(500)
    elif kind == "answer":
        ask(page, url, Q_MAIN)
    elif kind == "cite":
        ask(page, url, Q_MAIN)
        page.click(".msg-ai .cite-chip")
        page.wait_for_selector("#citationModal:not([hidden])", timeout=15000)
        page.wait_for_timeout(500)
    elif kind == "sources":
        ask(page, url, Q_MAIN)
        page.click("#sourceBtn")
        page.wait_for_selector(".doc-row", timeout=15000)
        page.wait_for_timeout(500)
    elif kind == "role":
        # 与 02 用同一个问题，才能拍出「同一问题、不同视角」的对照；
        # 换问题就只是另一张普通问答截图，证明不了角色化能力。
        ask(page, url, Q_MAIN, role="项目经理")
    elif kind == "refuse":
        ask(page, url, Q_OUTSIDE)
    elif kind == "degraded":
        ask(page, url, Q_MAIN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    want = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    os.makedirs(OUT, exist_ok=True)

    from playwright.sync_api import sync_playwright

    procs = []
    try:
        p1, url1, h1 = launch(9120)
        procs.append(p1)
        print(f"[主实例] {h1.get('status')} llmConfigured={h1.get('llmConfigured')} "
              f"chunks={h1.get('chunks')} hybrid={h1.get('hybrid', {}).get('backend')}")
        p2 = url2 = None
        if not want or 7 in want:
            p2, url2, h2 = launch(9121, clear_key=True)
            procs.append(p2)
            print(f"[降级实例] llmConfigured={h2.get('llmConfigured')}（应为 False）")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge")
            for i, (name, mode, kind) in enumerate(SHOTS, 1):
                if want and i not in want:
                    continue
                vp = {"width": 1440, "height": 900} if mode == "desktop" else {"width": 390, "height": 844}
                ctx = browser.new_context(viewport=vp, device_scale_factor=2,
                                          is_mobile=(mode == "mobile"), has_touch=(mode == "mobile"))
                page = ctx.new_page()
                page.add_init_script("try{localStorage.clear()}catch(e){}")
                target = url2 if kind == "degraded" else url1
                path = os.path.join(OUT, name + ".png")
                try:
                    capture(page, url=target, kind=kind, path=path)
                    if kind != "cite":
                        # 回答类截图必须从顶部拍：降级提示条、问题气泡、引用来源都在上方。
                        # 滚动容器是 #chatMain（style.css:141），且带 scroll-behavior:smooth
                        # —— 直接 scrollTo 是动画，截图时往往还没滚到位，必须先关掉平滑。
                        page.evaluate(
                            "const el=document.querySelector('#chatMain');"
                            "el.style.scrollBehavior='auto'; el.scrollTop=0; window.scrollTo(0,0);")
                        page.wait_for_timeout(200)
                        top = page.evaluate("document.querySelector('#chatMain').scrollTop")
                        # 阈值 40px：渲染后应用会自己回滚十几像素，仍能看到顶部内容；
                        # 阈值定太紧会对着可用的图报假红（实测 scrollTop=13 时截图完好）。
                        if top and int(top) > 40:
                            print(f"       [warn] 未回到顶部 scrollTop={top}，该图不可用")
                    page.screenshot(path=path, full_page=(kind == "home"))
                    kb = os.path.getsize(path) // 1024
                    print(f"  [{i:02d}] OK  {name}.png  {kb} KB")
                except Exception as exc:
                    print(f"  [{i:02d}] !!  {name} 失败：{type(exc).__name__}: {str(exc)[:110]}")
                    try:
                        page.screenshot(path=path)
                        print(f"       已保存失败现场（不作为交付图）")
                    except Exception:
                        pass
                ctx.close()
            browser.close()
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=15)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
