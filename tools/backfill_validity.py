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

    # ---- 第二批（2026-10-12）：对首批 11 份 unknown 的二次核查 ----
    # 元组可带第 5 项作为核查日期，缺省沿用 CHECKED。
    "0003": ("effective", "2018",
             "住房城乡建设部办公厅《关于印发震后建筑安全评估专家队工作办法的通知》"
             "建办质〔2018〕33号；原文成文日期未取到，辽宁省住建厅转发件"
             "辽住建安〔2018〕16号日期为 2018-08-02；未检索到废止或替代文件。"
             "注意建办质〔2018〕34号是《第二届成员名单》、《震后房屋建筑安全应急评估"
             "管理暂行办法》是另一份文件，均不得顶替本件",
             "https://zjt.ln.gov.cn/zjt/tftz/53F3ACB27394430095051FB02F16F417/index.shtml",
             "2026-10-12"),
    "0005": ("na", "2021-01-18",
             "建办科〔2021〕2号《住房和城乡建设部办公厅关于进一步加强历史文化街区和"
             "历史建筑保护工作的通知》附件2（参考样式），无独立时效；母通知 2024 年仍被引用",
             "https://www.mct.gov.cn/preview/whhlyqyzcxxfw/zhgl/202104/t20210430_924136.html",
             "2026-10-12"),
    "0006": ("na", "2021-01-18",
             "同一母通知建办科〔2021〕2号 附件1（划定与确定标准·参考），参考性文件，无独立时效",
             "http://xxgk.jl.gov.cn/zcbm/fgw_98022/xxgkmlqy/202103/P020210302731959479061.pdf",
             "2026-10-12"),
    "0017": ("na", "2016-05-27",
             "住房和城乡建设部工程质量安全监管司《关于做好〈工程项目施工人员安全指导手册〉"
             "宣传发放工作的通知》建质安函〔2016〕47号（2016-05-27），手册上传官网供免费发放；"
             "属宣传指导读物而非规范性文件，未见新版或替代（出版单位与 ISBN 未取到官方来源）",
             "https://www.waizi.org.cn/law/11130.html", "2026-10-12"),
    "0029": ("na", "",
             "田园建筑优秀实例推荐基本要求（附件1，推荐性清单），无独立时效属性；"
             "与 0030 推荐表同属一份母通知，母通知文号未取到",
             "", "2026-10-12"),
    "0048": ("na", "2011-12-16",
             "财政部办公厅、住房城乡建设部办公厅《关于组织实施2012年度太阳能光电建筑应用"
             "示范的通知》财办建〔2011〕187号 附件1；年度性申报大纲，仅对当年度示范有效，"
             "未见废止声明（另有目录把日期标为 2012-01-05，以正文为准待复核）",
             "https://law.training.sdufe.edu.cn/library/detail/66446", "2026-10-12"),
    "0050": ("na", "2011-12-16",
             "同一母通知财办建〔2011〕187号 附件2",
             "https://law.training.sdufe.edu.cn/library/detail/66446", "2026-10-12"),
    "0051": ("na", "2011-01-27",
             "《关于组织实施太阳能光电建筑应用一体化示范的通知》财办建〔2011〕9号 附件1；"
             "与 0048/0050 分属不同年度、不同文件，三者标题相似但**不得互相顶替**"
             "（辽宁转发件把本件写作'财建〔2011〕9号'，疑为笔误）",
             "https://law.training.sdufe.edu.cn/library/detail/66112", "2026-10-12"),
    "0075": ("effective", "2024-09-10",
             "建办质〔2024〕43号通知（即 0074 的母通知）附带的电子证照信息标准；"
             "2024-10-01 起全国试运行、2024-12-31 前全面换发，至今未见替代。"
             "本地正文含'2025年1月1日以后出厂'的字段要求，与 2024 版结构一致。"
             "**标准号与标准自身发布日未出现在本地文本中，需人工比对封面**",
             "https://www.bcebca.org.cn/ShowNews.aspx?id=13124", "2026-10-12"),
    "0076": ("effective", "2024-09-10",
             "同 0075，同一通知的另一份电子证照信息标准",
             "https://www.bcebca.org.cn/ShowNews.aspx?id=13124", "2026-10-12"),
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

# 仍属规范性文件/技术标准，但未取到可靠文号或废止信息 → 保持 unknown 并记录原因
# 值为 (原因, 核查日期)
STILL_UNKNOWN = {
    "0001": ("涉企行政检查事项清单：住建部确曾公布，但公开网络未取到母文件文号与日期。"
             "本地版为'房地产开发企业监督检查（3项）/城市供排水监督检查（9项）'，"
             "而 2025-10 沧州市转引的《河北省住房城乡建设领域涉企行政检查事项主要检查标准》"
             "同一条目已写作'（7项）'——清单随年度动态更新，本地版**很可能已过时**。"
             "保持 unknown，界面继续显示「时效待确认」，不得当作现行检查依据",
             "2026-10-12"),
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
        cdate = CHECKED
        if doc_id in EVIDENCE:
            rec = EVIDENCE[doc_id]
            status, vdate, basis, url = rec[:4]
            cdate = rec[4] if len(rec) > 4 else CHECKED
            note_add = f"时效核查（{cdate}）：{basis}" + (f"；来源 {url}" if url else "")
        elif doc_id in NON_NORMATIVE:
            status, vdate = "na", ""
            basis = NON_NORMATIVE[doc_id]
            url = ""
            note_add = f"时效核查（{CHECKED}）：{basis}，无独立时效属性"
        elif doc_id in STILL_UNKNOWN:
            status, vdate = "unknown", ""
            basis, cdate = STILL_UNKNOWN[doc_id]
            url = ""
            note_add = f"时效待核（{cdate}）：{basis}"
        else:
            status, vdate, basis, url = "unknown", "", "本次未核查", ""
            note_add = ""

        rows.append((doc_id, title, status, vdate, basis, url, cdate))
        if args.dry_run or not note_add:
            continue
        entry["valid_status"] = status
        entry["version_date"] = vdate
        # note 是**现状描述**（会显示在来源卡片上），不是观测日志：
        # 上一轮写的"时效待核（2026-10-11）"若留着，二次核查改完就会出现
        # 一句说待核、一句说已核。历史由台账与 git 记录，这里整段重写。
        old = (entry.get("note") or "").strip()
        keep = "｜".join(s for s in old.split("｜")
                         if s.strip() and not s.strip().startswith(("时效核查（", "时效待核（")))
        entry["note"] = f"{keep}｜{note_add}" if keep else note_add

    if not args.dry_run:
        with open(META, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # 台账
    counts = {}
    for _, _, s, *_ in rows:
        counts[s] = counts.get(s, 0) + 1
    passes = sorted({r[6] for r in rows})
    lines = [
        "# 34 份法规文档时效核查台账",
        "",
        f"核查日期：{'、'.join(passes)}（分批推进，每批日期标在逐条记录里）　|　"
        "核查方式：公开渠道检索 + 语料正文就地核对　|　**需人工抽查确认后方可视为定稿**",
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
              "| doc_id | 文档 | 状态 | 版本/施行日期 | 核查 | 依据 | 来源 |",
              "|---|---|---|---|---|---|---|"]
    for doc_id, title, status, vdate, basis, url, cdate in rows:
        link = f"[链接]({url})" if url else "—"
        lines.append(f"| {doc_id} | {title[:28]} | `{status}` | {vdate or '—'} | "
                     f"{cdate} | {basis} | {link} |")
    unk = [r[0] for r in rows if r[2] == "unknown"]
    recheck = [r[0] for r in rows
               if r[6] == max(passes) and r[2] in ("effective", "trial", "na")]
    lines += ["", "## 尚未解决的部分", "",
              f"{len(unk)} 份仍为 `unknown`（{('、'.join(unk)) or '无'}），原因见上表。这些条目在界面上继续显示"
              "**「时效待确认」**徽章——这是有意为之：宁可显式承认未核，也不要给出未经验证的「现行有效」。",
              "",
              "## 需人工复核的部分",
              "",
              f"第二批（{max(passes)}）新核定的 {len(recheck)} 份（{'、'.join(recheck)}）"
              "依据的是公开检索到的转发件与第三方法规库，**尚未逐份回到发文机关官网或"
              "国家法律法规数据库（flk.npc.gov.cn）比对原件**，其中 0075/0076 的标准号与"
              "标准自身发布日未出现在本地正文里，需人工比对封面后才能写成定论。",
              "",
              "**下一步**：由队员对上述条目逐份复核原件；优先处理仍为 `unknown` 的规范性文件。",
              ""]
    if not args.dry_run:
        with open(LEDGER, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    print(("DRY-RUN，未写入。" if args.dry_run else "已写入 docs_meta.json 与台账。"))
    print("状态分布：", {STATUS_LABEL[k]: v for k, v in sorted(counts.items(), key=lambda x: -x[1])})


if __name__ == "__main__":
    main()
