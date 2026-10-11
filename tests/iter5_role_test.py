# -*- coding: utf-8 -*-
"""迭代5（角色化提示词 / B方向，ADR-003）回归测试。

断言：
1. 角色清单：default 恒在首位，共 5 套，label/short 齐全
2. 契约完整性：任意角色的系统提示词都逐句包含契约规则 1~6 关键句
   （逐字引用 / 诚实拒答 / 越界拒答 —— PRD 产品生命线）
3. default 模板与 V4 现网系统提示词逐字节一致（回归红线）
4. 非法 role（None/空/未登记）一律回退 default
5. /api/roles 端点返回 5 套角色
6. /api/chat 的 done 事件回显 role；非法 role 回退为 default
   （结构断言走无 LLM 路径，测试不依赖外网）
7. 真实 LLM 抽样（仅本机配置了 Key 时执行）：同一问题不同角色均正常出答

用法：.venv/Scripts/python.exe tests/iter5_role_test.py
"""
import asyncio
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import config, prompts  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))


# V4 现网系统提示词（迁移前 llm.py 内联字面量，逐字节快照）
V4_SYSTEM = (
    "你是建筑安全法规问答助手，严格依据用户提供的法规片段回答问题，规则：\n"
    "1. 只使用片段中的内容，禁止编造任何条款、数字或结论。\n"
    "2. 回答结构：先一两句话给出结论要点，再分条说明依据条款；"
    "引用某片段时在句末标注其编号，如 [1]、[2]。\n"
    "3. 片段列表按相关度排序，但靠前的片段也可能与问题无关：请先通读全部片段再判断。"
    "只要任一片段包含与问题相关的条款，就必须基于该片段回答并标注其编号；"
    "不要因为部分片段无关就放弃回答。\n"
    "4. 只有当所有片段都与问题明显无关时，才只输出一句："
    "知识库中未找到与该问题直接相关的条款。建议用户换个问法或查看知识库来源。\n"
    "5. 不回答与建筑安全法规知识无关的问题，回复：本助手仅提供建安法规知识问答。\n"
    "6. 用简体中文，语言平实准确，不使用 markdown 表格。"
)

# 契约规则关键句（任意角色模板必须逐字包含）
CONTRACT_PHRASES = [
    "只使用片段中的内容，禁止编造任何条款、数字或结论",
    "引用某片段时在句末标注其编号，如 [1]、[2]",
    "只要任一片段包含与问题相关的条款，就必须基于该片段回答并标注其编号",
    "知识库中未找到与该问题直接相关的条款",
    "本助手仅提供建安法规知识问答",
    "用简体中文，语言平实准确，不使用 markdown 表格",
]


def parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析为 [(event, data_dict)]。"""
    out = []
    ev = ""
    for line in raw.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            try:
                out.append((ev, json.loads(line[5:])))
            except json.JSONDecodeError:
                pass
    return out


# ================= 1~4. 提示词模块（纯单元，无网络） =================
roles = prompts.available_roles()
check("T1 角色数量=5", len(roles) == 5, str([r["id"] for r in roles]))
check("T2 default 恒在首位", roles[0]["id"] == "default")
check("T3 id 唯一且 label/short 齐全",
      len({r["id"] for r in roles}) == 5
      and all(r["label"] and r["short"] for r in roles))

check("T4 default 模板与 V4 逐字节一致",
      prompts.system_prompt("default") == V4_SYSTEM)

all_ok, bad = True, []
for r in roles:
    p = prompts.system_prompt(r["id"])
    for phrase in CONTRACT_PHRASES:
        if phrase not in p:
            all_ok, bad = False, bad + [f'{r["id"]}:{phrase[:12]}']
check("T5 契约规则 1~6 逐句存在于所有角色", all_ok, "; ".join(bad))

check("T6 非法 role 回退 default",
      prompts.normalize_role(None) == "default"
      and prompts.normalize_role("") == "default"
      and prompts.normalize_role("hacker") == "default"
      and prompts.normalize_role(123) == "default")
check("T7 角色模板互不相同",
      len({prompts.system_prompt(r["id"]) for r in roles}) == 5)

# ================= 5~6. API 层（ASGI 内存请求，不依赖外网） =================
real_key = config.LLM_API_KEY
config.LLM_API_KEY = ""  # 结构断言走「未配置 LLM」路径，避免测试依赖外网


async def api_tests():
    import httpx
    from app import main

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/roles")
        data = r.json()
        check("T8 /api/roles 200 且 5 套", r.status_code == 200 and len(data["roles"]) == 5)
        check("T9 /api/roles 含 default 字段", data.get("default") == "default")

        done_events = {}
        for tag, payload in [
            ("missing", {"question": "帮我写一首关于安全的诗"}),
            ("bogus", {"question": "帮我写一首关于安全的诗", "role": "hacker"}),
            ("safety", {"question": "帮我写一首关于安全的诗", "role": "safety"}),
        ]:
            resp = await client.post("/api/chat", json=payload)
            raw = resp.text
            done = [d for e, d in parse_sse_events(raw) if e == "done"]
            done_events[tag] = done[0] if done else {}

        check("T10 缺省 role -> done.role=default",
              done_events["missing"].get("role") == "default",
              str(done_events["missing"]))
        check("T11 非法 role -> done.role=default",
              done_events["bogus"].get("role") == "default")
        check("T12 合法 role -> done.role=safety 正确回显",
              done_events["safety"].get("role") == "safety"
              and done_events["safety"].get("backend") in ("no_answer", "retrieval"),
              str(done_events["safety"]))

        # health 修复验证：不再因 NameError 恒为 degraded
        r = await client.get("/api/health")
        h = r.json()
        check("T13 health status=ok 且含 hybrid 字段",
              h.get("status") == "ok" and "hybrid" in h, json.dumps(h, ensure_ascii=False)[:160])


asyncio.run(api_tests())
config.LLM_API_KEY = real_key  # 还原

# ================= 7. 真实 LLM 抽样（仅配置了 Key 时执行） =================
if config.llm_configured():
    async def llm_sample():
        import httpx
        from app import main

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            q = "桩头凿除有什么规定？"
            for role in ("default", "pm"):
                events = []
                async with client.stream("POST", "/api/chat",
                                         json={"question": q, "role": role}) as resp:
                    buf = []
                    async for line in resp.aiter_lines():
                        buf.append(line)
                    events = parse_sse_events("\n".join(buf))
                done = [d for e, d in events if e == "done"]
                answer = "".join(d.get("text", "") for e, d in events if e == "delta")
                ok = bool(done) and done[0].get("role") == role and len(answer) > 50
                check(f"T14 真实LLM role={role} 正常出答且回显", ok,
                      f"chars={len(answer)} backend={done[0].get('backend') if done else '-'}")
                print("  样例[", role, "]:", answer[:120].replace(chr(10), " "))

    asyncio.run(llm_sample())
else:
    print("INFO 未配置 LLM Key，跳过 T14 真实抽样（结构断言已覆盖）")

# ================= 汇总 =================
fails = [n for n, ok in results if not ok]
print()
if fails:
    print("RESULT: FAIL —", ", ".join(fails))
    raise SystemExit(1)
print(f"RESULT: PASS — 全部 {len(results)} 项通过")
