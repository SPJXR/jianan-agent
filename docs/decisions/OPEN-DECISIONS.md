# OPEN-DECISIONS — 建安法规问答助手

> 悬而未决登记册（只追加 + 就地关闭）。每次 Phase 开始时复现到工作上下文最前面。

| Date | Source | Open Item | Related Constraints | Current Leaning | Blocked By | Resolves When | Status |
|------|--------|-----------|---------------------|-----------------|------------|---------------|--------|
| 2026-09-19 | Phase 0 | 用户云端 LLM API Key 未提供（DashScope/DeepSeek 等具体服务与密钥） | LLM 接口层需 OpenAI 兼容多服务商可切换；.env 配置 | 已选定 DeepSeek（deepseek-chat），.env.example 默认值即为此 | 等用户填入 Key | 验收前填入 .env；发布时配置到部署环境 | RESOLVED 2026-09-20（选型已定，Key 填入属运维动作） |
| 2026-09-19 | Phase 0 | 图片型文档文本化方案。Phase 1 实测修正：0017 文本层可用（移出本条）；实际无文本层为 0003（3页扫描法规）/ 0004（80MB隐患图集）/ 0067（图片型docx） | 本机装有 WPS/Word；Windows.Media.Ocr 可用；发布服务器无 GPU | 0003+0067 走 Windows OCR 预处理后入库；0004 图集跳过并在来源页标注已知边界 | 用户决策（2026-09-20） | 已决策 | RESOLVED 2026-09-20 |
| 2026-09-19 | Phase 0 | .doc 旧格式（约19份 .doc）解析转换通道 | 本机装有 WPS/Word，可用 COM 自动转换 docx | Word/WPS COM 批量转 docx 后统一管道解析 | 已实测验证 | phase1_doc_com_test.json：3/3 样本（0001/0005/0074）转换成功，段落与文字量正常 | RESOLVED 2026-09-19 实测关闭 |
| 2026-09-20 | 迭代规划 | 混合检索向量方案选型（本地 bge-small-zh CPU 推理 vs 云端 embedding API vs 暂缓仅调优 BM25） | 本机 RTX 4070 可跑本地模型；发布服务器无 GPU；云端 API 增加延迟与费用 | 倾向本地 bge-small-zh 离线建索引，BM25 兜底 | 待架构师 POC 对比召回率（「未找到」误判率指标 ≤10%） | 迭代3 启动前 POC 定稿 | RESOLVED 2026-09-22（POC 定稿：bge-small-zh-v1.5 + 条件补充融合，见 ADR-002；云端 API 未达标无需引入，「未找到」误判由生成层兜底维持 V3 行为） |
| 2026-09-20 | 迭代规划 | 迭代4 进阶功能（访问口令 / PWA / AI 整改文书）是否启动 | PRD 明确不做清单限制文书类功能；防盗刷仅公网扩围后需要 | 观望，按运营数据决定 | 等公网发布后指标（激活率 / 留存 / 盗刷迹象） | 指标达阈值或出现盗刷时 | OPEN |
| 2026-09-20 | 迭代2.3 | 34 份文档现行有效性（valid_status/version_date 实际值）待文档提供方逐份确认；表结构与来源页 UI 已就绪，当前全部缺省「时效待确认」 | PRD §13 第 4 条风险；误导用户风险高，不可自动判定 | 已知 0069（试行）/0070（征求意见稿）为同一指南两版本，其余未核实 | 用户在 kb/docs_meta.json 逐份补 valid_status(effective/repealed/draft/unknown) 与 version_date 后重跑 tools/build_kb.py | 用户回填完成并重建索引后关闭 | OPEN |

---

## 决议记录

- **2026-09-20 ADR-001**：埋点上报通道选定自建 `/api/track` 内存计数端点（sendBeacon + 白名单清洗 + 只存计数），不接第三方统计。详见 `docs/decisions/ADR-001-埋点上报通道.md`。

- **2026-09-22 ADR-002**：混合检索选定 bge-small-zh-v1.5 向量检索 + 条件补充融合（强命中 BM25 原排序 / 弱命中向量 top-5 置前），否决朴素 RRF 与加权融合（POC 数据均劣化）；关闭本表第一在决项。详见 `docs/decisions/ADR-002-混合检索条件补充方案.md` 与 `docs/research/POC-混合检索对比.md`。

- **2026-09-23 ADR-003**：B方向角色化提示词上线——`app/prompts.py` 5 套模板（default/safety/pm/supervisor/gov），契约规则 1~6 逐字不变，default 与 V4 逐字节一致；`/api/chat` 可选 role 参数（非法回退）+ `GET /api/roles` + 前端角色选择条。检索层零改动（qa_regression 14/14、iter4 9/9 原样通过）。顺带修复 main.py health() 缺失 import（线上曾恒返回旧格式）。详见 `docs/decisions/ADR-003-角色化提示词模板.md`、`docs/ACCEPTANCE.md` 迭代5 节。

- **2026-09-20 用户四项决策**：① 确认 Phase 1 三文档（PRD v1.0 / UIUX / README 蓝图）作为 Spec 与开发唯一依据；② LLM 服务选定 DeepSeek（deepseek-chat），Key 验收前填入 .env；③ 0003+0067 Windows OCR 入库、0004 跳过；④ 推进节奏为自动推进到本机验收，仅技术不可行或 QA 发现 P0 缺陷时上报用户。
