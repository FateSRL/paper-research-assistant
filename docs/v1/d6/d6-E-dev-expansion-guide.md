# D6 任务 E：开发集补至 20 题（四道新题复核、合并与补跑）

日期：2026-10-04。**任务 E 已完成：正式开发集达到 20 题，四道新题首次运行全部 answered；本次独立审核已修正文档口径。** 原合并记录载明用户确认“每个题都很合理”；本次 AI 审核不新增人工确认或答案准确率。

记录入口：[本次审核与中文要点](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit.md)、[审核 JSON](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit.json)、[合并记录](/D:/course/paper-research-assistant/artifacts/d6/dev_merge_four_record.json)。[原候选复核包](/D:/course/paper-research-assistant/artifacts/d6/dev_candidate_review.md)和[原重叠审计](/D:/course/paper-research-assistant/artifacts/d6/dev_overlap_audit.json)保留为合并前历史快照，原 SHA 不变；其中“待人工确认”“期望要点（中文）”下列英文，以及“人工阅读”的旧表述，以本次补充说明为准。

## 1. 选题与来源

四题取自 B 的[四个预留事实族](/D:/course/paper-research-assistant/artifacts/d6/dev_fact_family_reservations.json)，预留文件本身只是来源建议，不能算人审或正式题集。

| 题 | 类型 | 被评分事实 | PDF 文件页序 |
|---|---|---|---|
| D6-001 | fact | 混合精度、8 张各 32GB V100；训练和推理也可单卡进行 | RAG p17 |
| D6-002 | fact | Jeopardy 生成问题的 factuality / specificity 人评定义 | RAG p5 |
| D6-003 | method | 用 ReAct 生成的 3,000 条正确轨迹自举微调 PaLM-8B/62B | ReAct p5 |
| D6-004 | retrieval_paraphrase | ALFWorld Figure 5 中编辑推理文本后成功的单个示例 | ReAct p14，图注 p15 |

D6-004 原文“Act 17/23”是图中的步骤标签；实际修改的是推理文字，不能理解为直接修改两个工具动作，也不能外推为所有任务都能可靠纠错。

## 2. 来源与重叠复核

- 四段引文与固定 PDF 对应文件页、过滤片段及只读 SQLite chunk 一致；固定 PDF SHA 与页码正确，整页截图经 AI 查看核对。
- 本次 **AI 语义复核**阅读四题与旧 16 道开发题、20 道冻结验收题的问题和期望点，共 144 对。没有发现被评分答案事实相同的重复问法；这不是额外的人工复核或自动相似度成绩。
- D6-002 与 D6-B-003 共享 Jeopardy 评估背景，但分别问人评定义与自动 Q-BLEU 指标；与 D6-B-019 **实际共享同一 p5:b4 背景段**，后者问索引语料的人工事实审核比例及资料不足的理由。评分对象不同，不能把这一关联仅写成通用关键词误报。
- D6-003 与 D6-B-008 都涉及轨迹，但前者问 3,000 条正确轨迹与 8B/62B 自举微调，后者问冻结 540B 模型与人工 few-shot 示例。共享术语，方法和评分事实不同。

原审计的“全部仅关键词误报、完全无事实重叠”过强；当前结论为：**未发现同题近义改写，存在共享背景证据与相关术语，已在补充审核中说明。** 冻结验收题及其标注未改，也未运行验收问答。

## 3. 合并核对

- 原合并记录载明四题已通过用户复核，以 human_verified 并入 eval/dev.jsonl；本次保留该记录和状态。
- 原 16 条含换行与合并前备份逐字节相同；新增四条与候选仅人审元数据不同。
- 正式开发集 16 → 20，分布为 10 fact / 4 method / 3 retrieval_paraphrase / 3 unanswerable；17 道可答、3 道无答案。
- 正式 dev SHA：87c5ef08… → abf2fcb0…；候选、原复核包、合并前备份与合并记录的完整哈希匹配。

## 4. 四题首次运行与答案审核

新批次 d6_e_dev20_20261004 只运行四道新题，另外 16 题在本批未重复运行；此前结果由各自旧批次保留。

| 指标 | 结果 |
|---|---|
| 程序终态 | 4 answered |
| 精确全部标注引文命中（返回 / 展示） | 4/4、4/4 |
| 最终引用定位合法 | 12/12 次引用出现；涉及 7 个独立 chunk，拦截 0 |
| 重试 / 修复 | 0 / 0 |
| 用量 | embedding 4 次 / 162 tokens；聊天 4 次 / 9666 tokens |
| 时间 | 四题 CLI 记录耗时合计 25.129732 秒；批次创建至最后更新时间约 36.8 秒 |

本次逐条 AI 对照实际引用原文：10 条结论中 9 条直接有据，1 条核心有据但表述含歧义（D6-003 把“also for other baselines”改写成“and other baselines”，可能误读为混合训练数据）。补充材料给出更严谨的中文说法；原始付费输出完整保留。D6-004 的支持范围限于论文的 ALFWorld 示范。

上述机器统计不是答案准确率；本次 AI 评价也不能写成人工成绩。原批次 summary 的 not_reviewed / human pending 保留为当时快照，本次评价另存[审核记录](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit.json)。

## 5. 当前开发集与检索对照范围

- 20 道开发题由 D5 十题 d5_f_dev10_20261004、D6 六题 d6_f_dev16_20261004、D6-E 四题 d6_e_dev20_20261004 三个不同题集版本的首跑批次覆盖。聚合时必须标明批次。
- C 的 top-k 对照发生在 E 扩充前，范围为 **16 道开发题、其中 13 道可答**；没有对新增四题做 top-5/10/20 对照。
- C 中 D2-003 的全部标注依据在 top-10 找回；D2-002 的第二段依据排第 11，需要 top-20 才全部找回。D2-004 的目标排第 17，top-20 返回但被 8000 字符展示预算截断。问答默认值仍为 top-5，旧失败结果保留。
- 题目标注的 human_verified 不等于生成答案全量人审通过。此前三题整题抽审和本次四题 AI 审核分别记录，未提供全批逐条人工支持率。

## 6. 本次修正的核对范围

[85 项独立离线核对](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit_checks_20261004_130657_817208.json)通过，覆盖字节保留、合并哈希、候选到正式题的差异、预留来源、四题预占/首跑/历史绑定，以及从原始结果重算全部机器统计。已有 F 校验器的 67 项纯读取核对也通过，旧 F 记录未覆盖。

本次新增模型请求 0 次；正式题集、验收冻结、原始批次及历史输出均保留。修改前文件备份见[审核预检](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit_preflight_20261004_130657_817208.json)。
