# -*- coding: utf-8 -*-
"""回填 34 份文档的时效状态，并生成可复核的核查台账。

设计原则：
1. **只有拿到文号/公告号或印发日期等硬证据的文档才写 effective / trial / consultation / repealed**；
   拿不到证据的一律保持 unknown，不猜。
2. 纯附件、表格、报名表、征订单、示例、讲话稿标 `na`（无独立时效属性）——这是按文档类型判定，
   不需要外部证据，但必须写明理由。
3. 每条都留来源链接与核查日期，输出到 docs/法规时效核查台账.md，供人工抽查。

用法：
    python tools/backfill_validity.py            # 写入 docs_meta.json + 生成台账
    python tools/backfill_validity.py --dry-run  # 只打印将要写入的内容
"""
import argparse
import json
import os
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(BASE, "kb", "docs_meta.json")
LEDGER = os.path.join(BASE, "docs", "法规时效核查台账.md")
CHECKED = "2026-10-11"

# status: effective 现行有效 / trial 试行（现行有效）/ consultation 征求意见稿（未生效）
#         repealed 已废止 / na 非规范性文件（无独立时效）/ unknown 待确认
EVIDENCE = {
    "0011": ("effective", "2016-12-13", "建质〔2016〕253号 印发",
             "https://www.waizi.org.cn/law/15327.html"),
    "0012": ("effective", "2020-08-17", "住房城乡建设部印发《震后房屋建筑安全应急评估技术指南》的通知",
             "https://www.sxjzy.org/h-nd-1798.html"),
    "0063": ("effective", "2026-06-01",
             "住房和城乡建设部令第60号（2025-12-17 公布），取代建质〔2008〕75号；"
             "语料正文含'第60号'与'2026年6月1日起施行'，已就地核对",
             "https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=105695"),
    "0064": ("effective", "2026-06-01", "同 0063（PDF 版式副本，正文含第60号令与施行日期）",
             "https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=105695"),
    "0069": ("trial", "2025-06-23",
             "住房城乡建设部办公厅关于印发《房屋市政工程有限空间识别及施工安全作业指南（试行）》的通知；"
             "试行稿已印发施行，属现行有效的试行性文件",
             "https://www.jsjlztb.org.cn/m/zfwj8-2.html"),
    "0070": ("consultation", "2025-03-01",
             "同指南的征求意见稿，未生效；已由 0069 试行版取代，不得作为施工依据",
             "https://www.grandall.com.cn/ghsd/info.aspx?itemid=34422"),
    "0071": ("trial", "2024-12-31", "建办质〔2024〕63号 印发（试行）；各地 2025-01 转发",
             "https://www.sxjzy.org/h-nd-37531.html"),
    "0072": ("effective", "2025-08-03",
             "住房城乡建设部公告2024年第186号发布（2024-12-03），"
             "自发布之日起 9 个月后即 2025-08-03 起实施",
             "https://zjt.xinjiang.gov.cn/xjzjt/c113175/202412/22979485f90048bb974d2d6c63205c4f.shtml"),
    "0073": ("trial", "2024-11-25", "建办质〔2024〕56号 印发（试行）",
             "https://www.bcebca.org.cn/ShowNews.aspx?id=13440"),
    "0074": ("trial", "2024-09-10",
             "建办质〔2024〕43号《关于开展建筑起重机械备案证和房屋市政工程施工安全监督人员"
             "考核合格证书电子化工作的通知》的附件业务规程（试行）；电子证照自 2024-10-01 起换发",
             "https://www.bcebca.org.cn/ShowNews.aspx?id=13124"),
}

# 按文档类型判定为非规范性文件：附件表格、示例、报名表、征订单、讲话、示意图扫描件
NON_NORMATIVE = {
    "0002": "联系人信息表（附件表格模板）",
    "0004": "施工安全隐患示意图（扫描图片版，图示材料）",
    "0026": "专项行动实施情况汇总表（附件表格）",
    "0030": "田园建筑优秀实例推荐表（附件表格）",
    "0049": "太阳能光电建筑应用财政补助资金申请汇总表（附件表格）",
    "0052": "同上（早期版附件表格）",
    "0053": "建筑安全培训班报名表（报名表）",
    "0057": "在全国建筑安全生产联络员第十二次会议上的讲话（2010 年讲话稿）",
    "0062": "《建筑施工特种作业人员安全技术考核培训教材》征订单",
    "0065": "建设项目开工'一件事'申请表（示例）",
    "0066": "建设项目开工'一件事'材料清单（示例）",
    "0067": "建设项目开工'一件事'办理流程（示例流程图）",
    "0068": "建设项目开工'一件事'数据服务清单（附件清单）",
}

# 仍属规范性文件/技术标准，但本次未取到可靠文号或废止信息 → 保持 unknown 并记录原因
STILL_UNKNOWN = {
    "0001": "涉企行政检查事项清单，随年度公告更新，未取到本年度文号",
    "0003": "震后建筑安全评估专家队工作办法，未取到文号与印发日期",
    "0005": "保护标志牌参考样式（附件2），未确认其主文件是否仍有效",
    "0006": "历史文化街区划定和历史建筑确定标准（参考），参考性文件，未确认现行版本",
    "0017": "工程项目施工人员安全指导手册（指导读物，无文号）",
    "0029": "田园建筑优秀实例推荐基本要求（附件1），未确认主通知状态",
    "0048": "太阳能光电建筑应用集中示范区实施方案编制大纲（附件1），未确认主通知状态",
    "0050": "太阳能光电建筑一体化应用示范项目实施方案编制大纲（附件2），同上",
    "0051": "太阳能光电建筑应用一体化示范项目实施方案编制大纲（附件1），同上",
    "0075": "一体化政务服务平台电子证照 建筑起重机械备案证 信息标准，未确认标准现行版本",
    "0076": "一体化政务服务平台电子证照 施工安全监督人员考核合格证书 信息标准，同上",
}

STATUS_LABEL = {
    "effective": "现行有效", "trial": "试行·现行有效", "consultation": "征求意见稿·未生效",
    "repealed": "已废止", "na": "附件·无独立时效", "unknown": "待确认",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(META, encoding="utf-8") as f:
        blob = json.load(f)
    docs = blob["docs"]

    rows = []
    for doc_id in sorted(docs):
        entry = docs[doc_id]
        title = entry.get("title", "")
        if doc_id in EVIDENCE:
            status, vdate, basis, url = EVIDENCE[doc_id]
            note_add = f"时效核查（{CHECKED}）：{basis}；来源 {url}"
        elif doc_id in NON_NORMATIVE:
            status, vdate = "na", ""
            basis = NON_NORMATIVE[doc_id]
            url = ""
            note_add = f"时效核查（{CHECKED}）：{basis}，无独立时效属性"
        elif doc_id in STILL_UNKNOWN:
            status, vdate = "unknown", ""
            basis = STILL_UNKNOWN[doc_id]
            url = ""
            note_add = f"时效待核（{CHECKED}）：{basis}"
        else:
            status, vdate, basis, url = "unknown", "", "本次未核查", ""
            note_add = ""

        rows.append((doc_id, title, status, vdate, basis, url))
        if args.dry_run or not note_add:
            continue
        entry["valid_status"] = status
        entry["version_date"] = vdate
        old = (entry.get("note") or "").strip()
        if note_add not in old:
            entry["note"] = f"{old}｜{note_add}" if old else note_add

    if not args.dry_run:
        with open(META, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # 台账
    counts = {}
    for _, _, s, *_ in rows:
        counts[s] = counts.get(s, 0) + 1
    lines = [
        "# 34 份法规文档时效核查台账",
        "",
        f"核查日期：{CHECKED}　|　核查方式：公开渠道检索 + 语料正文就地核对　|　**需人工抽查确认后方可视为定稿**",
        "",
        "状态词表（`kb/docs_meta.json` 的 `valid_status`）：",
        "",
        "| 取值 | 含义 | 检索侧处理 |",
        "|---|---|---|",
        "| `effective` | 现行有效 | 不降权 |",
        "| `trial` | 试行，已印发施行，属现行有效 | **不降权**（与征求意见稿效力相反，见 ADR-006） |",
        "| `consultation` | 征求意见稿，尚未生效 | ×0.15 重降权，界面标红 |",
        "| `repealed` | 已废止 | ×0.35 降权，界面标红 |",
        "| `na` | 附件表格/示例/报名表/征订单/讲话稿等，无独立时效属性 | 不降权 |",
        "| `unknown` | 待确认 | **不降权**（避免把「还没查」变成「检索变差」） |",
        "",
        "## 统计",
        "",
    ]
    for k in ("effective", "trial", "consultation", "repealed", "na", "unknown"):
        if counts.get(k):
            lines.append(f"- {STATUS_LABEL[k]}（`{k}`）：**{counts[k]}** 份")
    lines += ["", "## 逐条记录", "",
              "| doc_id | 文档 | 状态 | 版本/施行日期 | 依据 | 来源 |",
              "|---|---|---|---|---|---|"]
    for doc_id, title, status, vdate, basis, url in rows:
        link = f"[链接]({url})" if url else "—"
        lines.append(f"| {doc_id} | {title[:28]} | `{status}` | {vdate or '—'} | {basis} | {link} |")
    lines += ["", "## 尚未解决的部分", "",
              f"{counts.get('unknown', 0)} 份仍为 `unknown`，原因见上表。这些条目在界面上继续显示"
              "**「时效待确认」**徽章——这是有意为之：宁可显式承认未核，也不要给出未经验证的「现行有效」。",
              "",
              "**下一步**：由队员逐份到发文机关官网或国家法律法规数据库（flk.npc.gov.cn）复核，"
              "优先处理仍为 `unknown` 的规范性文件（0001、0003、0005、0006、0029、0048、0050、0051、0075、0076）。",
              ""]
    if not args.dry_run:
        with open(LEDGER, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    print(("DRY-RUN，未写入。" if args.dry_run else "已写入 docs_meta.json 与台账。"))
    print("状态分布：", {STATUS_LABEL[k]: v for k, v in sorted(counts.items(), key=lambda x: -x[1])})


if __name__ == "__main__":
    main()
