# D9 F：旧六题补评与新四题对照

执行日期：2026-10-06。完成记录见 [task_f.json](/D:/course/paper-research-assistant/artifacts/d9/task_f.json)。F1、F2、F3 已完成各自记录范围；保留 D2-002 未完整回答的问题，新旧答案人审待提供。G 待执行，D7 继续暂缓。

F1 补的是旧批次 `d6_f_dev16_20261004` 中 D5-001–006 的独立 AI 评价。4 份回答、9 条结论、10 次实际引用与 2 份不足理由逐项核对；4 个回答完整有据，2 个资料外拒答合理。30 次展示与版本原文、segment 字符范围、对应 PDF 页核对；旧结果与首次历史分别绑定 SHA。见 [旧六题可读补评](/D:/course/paper-research-assistant/artifacts/d9/legacy_dev6_review.md)和 [完整 JSON](/D:/course/paper-research-assistant/artifacts/d9/legacy_dev6_review.json)。没有重新生成旧答案，没有改旧机器成绩，也没有继承 D8 的新 D5-006 审核。

F2 新建 `d9_f_dev4_20261006`，四题八模式首次均保存，各题只预占/运行一次。这里使用 D9 新策略、范围表和剩余预算；D8 四题结果及费用保留原样。

| 开发题 | 固定 RAG 首次 | Agent 首次 | 独立 AI 结论 |
|---|---|---|---|
| D2-001：两种记忆 | 回答，3 条结论 | 回答，7 条结论，无补查 | 两模式都完整有据 |
| D2-002：两种文档使用机制 | 本轮证据不足 | 回答，2 条相关事实，无补查 | 固定合理拒答；Agent 事实有据，但未解释“整段序列同一文档 / 每 token 可不同文档”，两模式均未完成可答题 |
| D2-003：摘要点名的基准 | 原始召回 5 条正文，资格后展示 0，聊天 0 | 一次摘要白名单补查，召回/展示/引用 1 条完整核定摘要 | 两模式守住来源边界；Agent 的 HotpotQA/Fever 两结论支持且整题完成 |
| D5-006：资料外项目日期 | 证据不足 | 证据不足，无补查 | 两模式合理拒答，没有编造日期 |

新 D2-003 的实际引用为 ReAct PDF 文件第 1 页的完整摘要 chunk `arxiv_2210.03629v3_r_22af23d03fcb87a8_p1_c6`，核定 segment 字符范围 `[0,1545)`；资格来自结构/文本/哈希匹配，而不是“第 1 页就是摘要”。首轮正文仍保存为原始召回，不能供摘要结论引用。固定拒答保住边界，但不算完成可答题。

新 D2-002 说明另一层问题：两条事实各自有引用支持，程序返回 `answered`，仍可能没回答题目。此处 Agent 提到了两模型的解码近似差异及单 token 分类等价性，缺少要求的 passage 使用机制。初审记为 `supported_related_facts_incomplete_answer`，不能记为完整完成或补查收益。该问题保留给 D10 开发验证，若修改源码、策略或范围表，需重建 prepared 批次。

本次程序可答生成状态为固定 1/3、Agent 3/3；AI 支持与完整性观察为固定 1/3、Agent 2/3。发布的 14 条结论均获自身引用组合支持；18 次实际引用中，14 次完整支持、4 次部分支持，部分引用缺失的 BART/DPR 名称由同条结论自己的另一条引用补足。引用定位、章节资格、事实支持、任务完整性分别判断。这是四道开发题观察，新答案人审 0/8，QA accuracy 未测量。

费用按实际发送与逻辑归属分开：

| 口径 | Embedding 请求 / tokens | 聊天 SDK/HTTP 尝试 / 已知 tokens |
|---|---:|---:|
| 实际全批次 | 5 / 191 | 8 / 16781 |
| 固定 RAG 独立运行的逻辑归属 | 4 / 165 | 3 / 6407 |
| Agent 独立运行的逻辑归属 | 5 / 191 | 5 / 10374 |

四个共同首轮实际各计一次；Agent 摘要补轮另计一次。逻辑 embedding 不能相加当实际费用。网络重试与输出修复均为 0；外层 HTTP 发送计数也核对为聊天 8、embedding 5、其他 0。

机器聊天总 `total_tokens` 保留为 null，`known_total_tokens=16781`。原因是 D2-003 固定模式没有聊天，空统计中 `usage_complete=false / total_tokens=null` 传入保守汇总；8 次实际聊天响应都成功且保存 usage。这里不能把 null 说成漏了一次付费用量，也不能追溯改写原首次统计。历史是导出前快照，history 与 case 的业务/结果/费用相同，仅导出状态由 `prepared` 变为 `completed`。

F3 新建 [完整 20 题 prepared manifest](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev20_prepared_20261006/manifest.json)。显式传入全部正式 dev ID，17 可答/3 资料外；绑定当前 33 份源码、175 份保护输入、公开模型/索引、D9 策略/范围和事后机器 rubric。准备时环境/API/HTTP 均为 0；state 为 prepared，attempt/output 为 0。四题冒烟与完整 20 题是两个独立批次，20 题真实执行及 40 模式评价留给 D10。

你现在可以这样检验，不用再发模型请求：

1. 打开 [八份首次人审材料](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/human_review.md)，先独立看题目、答案和实际引用，再看 [AI 汇总](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/ai_semantic_review.md)。
2. 优先比较 D2-003 的正文首轮与摘要补轮：固定为何停下，Agent 最终到底看到了哪一条摘要。
3. 再看 D2-002：区分“说的事实有据”和“题目要求的机制已解释”，不要仅依据 `answered` 通过。
4. 对照 [完整性核对](/D:/course/paper-research-assistant/artifacts/d9/task_f_integrity.md)，检查原始记录/费用/绑定与 20 题零尝试状态。以下命令只审计保存产物，新增 API 0：

```powershell
Set-Location D:\course\paper-research-assistant
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_d9_f_artifacts
```

新八模式逐项人审可填 [human_review_template.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/human_review_template.json)，未审保留 pending；若你只确认整体与 AI 相同，会另记总体确认，不伪造逐条分数。旧六题是另一个审查范围，此前的总体确认不自动套到这次材料。

下一步 G 汇总交接；完整 20 题和任何新版本复测分别留首次记录，验收题首次运行仍留 D11。当前没有全量人审准确率，也未证明严格 120 秒进程强制退出。
