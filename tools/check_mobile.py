# -*- coding: utf-8 -*-
"""移动端适配实测检查（数媒 D7/截图之外的真检查）。

截图只能证明"看起来没坏"，证明不了横向溢出、点不动、iOS 自动放大这些问题。
本脚本在 390×844 移动视口下量四个界面，逐条判定：

1. 无横向溢出：documentElement.scrollWidth <= clientWidth，且没有元素右边缘越界。
2. 主操作可点：发送/引用/来源/关闭等可点元素命中框 >= 24px（WCAG 2.2 SC 2.5.8 的
   合格线）。24~44px 之间只打 INFO，因为 44px 是 AAA 建议而非缺陷，
   把建议当闸会刷出一屏假故障。
3. 输入框不触发 iOS 自动放大：font-size >= 16px。
4. 输入区未被遮挡：提问后 #input 的矩形仍在视口内。

    python tools/check_mobile.py            # 自己起服务、跑完自动关
    python tools/check_mobile.py --url http://8.137.11.193:9000   # 查线上实例
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "tools"))

# stdout 的 UTF-8 包装交给 make_shots 做；这里不能再包一次，
# 两个 TextIOWrapper 共用同一个 buffer，先被回收的那个会把 buffer 关掉。
from make_shots import launch, ask, Q_MAIN  # noqa: E402

TAP_AA = 24    # WCAG 2.2 SC 2.5.8 Target Size (Minimum) —— 低于此值算不合格
TAP_AAA = 44   # WCAG 2.x SC 2.5.5 Target Size (Enhanced) —— 介于两者之间只是建议，不是缺陷
VIEWPORT = {"width": 390, "height": 844}

JS_OVERFLOW = """
() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  const inScroller = (el) => {
    // 引用来源卡片行是**故意的**横向滚动容器（style.css:256 .sources-row
    // { overflow-x:auto }），卡片越出视口是轮播的正常状态，不是溢出。
    // 上一版没排除这类祖先，把 4 个轮播卡片报成了越界缺陷。
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    // 只判右边界。左边界为负是离屏抽屉的正常状态
    // （style.css:470 .history-sidebar { transform: translateX(-100%) }），
    // 上一版把 left < -1 也判成越界，对着一个本来就该在屏幕外的面板报了假红。
    if (r.right > vw + 1 && !inScroller(el)) {
      bad.push({tag: el.tagName.toLowerCase(),
                cls: (el.className || '').toString().slice(0, 40),
                left: Math.round(r.left), right: Math.round(r.right)});
    }
    if (bad.length >= 8) break;
  }
  return {vw, sw: document.documentElement.scrollWidth, bad};
}
"""

JS_TAP = """
(sels) => sels.map(s => {
  const el = document.querySelector(s);
  if (!el) return {sel: s, missing: true};
  const r = el.getBoundingClientRect();
  return {sel: s, w: Math.round(r.width), h: Math.round(r.height),
          fs: parseFloat(getComputedStyle(el).fontSize)};
})
"""


class Report:
    def __init__(self):
        self.rows, self.fails, self.infos = [], 0, 0

    def check(self, view, name, ok, detail=""):
        self.rows.append((view, name, "PASS" if ok else "FAIL", detail))
        if not ok:
            self.fails += 1
        print(f"  [{'  OK' if ok else 'FAIL'}] {view:10s} {name}"
              + (f"  {detail}" if detail else ""))

    def info(self, view, name, detail=""):
        self.infos += 1
        print(f"  [INFO] {view:10s} {name}  {detail}")


def measure(rep, page, view, tap_selects):
    o = page.evaluate(JS_OVERFLOW)
    rep.check(view, "无横向溢出", o["sw"] <= o["vw"] + 1,
              f"scrollWidth={o['sw']} clientWidth={o['vw']}")
    rep.check(view, "无元素越界", not o["bad"],
              "" if not o["bad"] else "越界元素: " + "; ".join(
                  f"{b['tag']}.{b['cls']}[{b['left']},{b['right']}]" for b in o["bad"]))
    for t in page.evaluate(JS_TAP, tap_selects):
        sel = t["sel"]
        if t.get("missing"):
            rep.check(view, f"存在 {sel}", False, "未找到该节点")
            continue
        side = min(t["w"], t["h"])
        if sel == "#input":
            rep.check(view, f"{sel} 字号≥16px（防 iOS 自动放大）",
                      t["fs"] >= 16, f"fontSize={t['fs']}")
        rep.check(view, f"{sel} 命中框≥{TAP_AA}px（WCAG AA）",
                  side >= TAP_AA, f"{t['w']}×{t['h']}")
        if side >= TAP_AA and side < TAP_AAA:
            rep.info(view, f"{sel} 低于 44px 触控建议", f"{t['w']}×{t['h']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    args = ap.parse_args()

    proc = None
    url = args.url
    if not url:
        proc, url, h = launch(9130)
        print(f"[服务] {url} chunks={h.get('chunks')} llmConfigured={h.get('llmConfigured')}")
    print(f"[视口] {VIEWPORT['width']}×{VIEWPORT['height']} (iPhone 12 逻辑分辨率)\n")

    rep = Report()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge")
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2,
                                      is_mobile=True, has_touch=True)
            page = ctx.new_page()
            page.add_init_script("try{localStorage.clear()}catch(e){}")

            page.goto(url, wait_until="load")
            page.wait_for_selector("#input", timeout=20000)
            measure(rep, page, "首页", ["#input", "#sendBtn", "#historyBtn", "#sourceBtn"])

            ask(page, url, Q_MAIN)
            measure(rep, page, "问答结果", ["#input", "#sendBtn", ".msg-ai .cite-chip"])
            box = page.evaluate("(()=>{const r=document.querySelector('#input')"
                                ".getBoundingClientRect();"
                                "return {top:r.top,bottom:r.bottom,vh:innerHeight};})()")
            rep.check("问答结果", "输入框未被顶出视口",
                      0 <= box["top"] < box["vh"] and box["bottom"] <= box["vh"] + 1,
                      f"top={box['top']:.0f} bottom={box['bottom']:.0f} vh={box['vh']}")

            page.click(".msg-ai .cite-chip")
            page.wait_for_selector("#citationModal:not([hidden])", timeout=15000)
            page.wait_for_timeout(400)
            measure(rep, page, "引用面板", ["#citeClose", "#citeCopy"])
            page.click("#citeClose")
            page.wait_for_timeout(300)

            page.click("#sourceBtn")
            page.wait_for_selector(".doc-row", timeout=15000)
            page.wait_for_timeout(400)
            measure(rep, page, "来源抽屉", ["#sourceClose", ".doc-row"])
            page.click("#sourceClose")
            page.wait_for_timeout(300)

            page.click("#historyBtn")
            page.wait_for_selector(".history-sidebar--open", timeout=15000)
            page.wait_for_timeout(400)
            measure(rep, page, "历史抽屉", ["#historyClose", "#newChatBtn"])
            browser.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()

    print(f"\n结论：{len(rep.rows) - rep.fails}/{len(rep.rows)} 通过，失败 {rep.fails} 项，"
          f"另有 {rep.infos} 项低于 44px 触控建议（不计失败）")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
