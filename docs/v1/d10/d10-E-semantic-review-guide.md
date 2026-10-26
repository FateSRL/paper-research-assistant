# D10 E：语义评价日志、学习路线与参考答案

执行日期：2026-10-07（Asia/Shanghai）。**E 已完成 D10 开发批次 20 题、两模式共 40 份输出的 AI 事后语义评价。** 逐题评价保存于 [dev_comparison.md](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md)，人工复核仍为 `pending`。本轮新增真实 API 调用 0、测试 0、哈希检查 0；原始 JSON 的首次结果、机器指标与 `semantic_support_status` 不回写。

## 1. E 工作日志

E 使用 [D 工作日志](/D:/course/paper-research-assistant/docs/v1/d10/d10-D-development-run-guide.md)中已完成的 `d10_d_dev20_20261007_195707` 批次。正式开发集为 17 道可答题、3 道负题，每题各有固定 RAG / Agent 两份结果；没有再次执行问答，也没有读取验收题。

评价逐题核对原问题、来源限制与必要内容，再按每条 Claim 自身的实际 `citation_ids`，对照最终 `context.shown_evidence` 和对应 `answer.evidence_sources` 判断支持程度。多个引用共同支持一条 Claim 时按引用并集判断；未被引用的相邻片段不能替该 Claim 补证，未展示 PDF 或标注中的正确答案也不能替本轮回答补证。负题没有事实 Claim 时，单独检查不足理由、选定范围与是否猜答，不把零 Claim 算成事实支持率。

本次把以下三个问题分别记录：

| 评价问题 | 判断依据 | 本次用途 |
|---|---|---|
| 程序是否发布答案 | 保存结果的 `status=answered` | 说明执行状态，不能据此认定语义正确 |
| 是否覆盖必要内容 | 原问题与逐项 `expected_points`，结合实际回答 | 判断回答是否回应所求内容，包括合理不足 |
| 是否完整且全部有据 | 必要内容、每条实际引用的语义支持、来源限定和题目具体范围 | 使用严格 `complete_supported_answer`，保留归属与表述缺口 |

E 的交付是逐题 AI 评价与本页独立日志，不改程序回答，不把 AI 观察登记成人工确认，也不建立新的校验器或测试入口。

## 2. 本次结果怎样理解

| 指标 | 固定 RAG | Agent |
|---|---:|---:|
| 可答题的程序 `answered` | 15/17 | 17/17 |
| 正题必要内容覆盖 | 15/17 | 17/17 |
| 严格 `complete_supported_answer` | 13/17 | 15/17 |
| 正题必要内容点覆盖 | 34/38 | 38/38 |
| 负题合理拒答 | 3/3 | 3/3 |
| 事实 Claim 总数 | 39 | 50 |
| `supported` | 38 | 48 |
| `partial` | 1 | 2 |
| `unsupported` | 0 | 0 |

事实 Claim 共 89 条：86 条 `supported`、3 条 `partial`。负题拒答分别以 3 道负题为分母；正题完整支持分别以 17 道可答题为分母。它们均为本次开发批次的 AI 事后观察，不是人工准确率或验收成绩。

Agent 的 17/17 程序回答与 17/17 必要内容覆盖，可以说明其回应了全部可答题的所求内容；严格完整支持仍是 15/17。**`answered` 不等于完整有据。** 必要内容点覆盖也不能替代来源支持：答案写出了题目要求的值，仍可能没有用自己的引用证明该值属于题目指定的实验。

## 3. 关键发现与保留问题

| 题目与模式 | 本轮事实与评价 | E 的结论 |
|---|---|---|
| D2-002 Agent | 真实执行了一次补查；最终 4 条 Claim 均由其实际引用支持，并完整解释 RAG-Sequence / RAG-Token 的机制 | 当前开发题上的动作与机制回答已有改进证据，不需要为此重跑旧题 |
| D2-002 固定 RAG | 对机制题仍返回不足 | 该模式未覆盖本题必要内容；保留首次不足，不用 Agent 答案补固定模式 |
| D2-003 Agent | 一次补查后在所要求的摘要来源内完成回答 | 来源限定与必要内容均满足，是有答案增益的补查 |
| D3-004 两模式 | 实际引用支持连续三次失败停止的规则，但引用本身没有独立证明 Section 4.2 / HotpotQA 实验归属 | 必要数字已答出，两模式仍不计严格整题完整支持；不能从题面或标注补实验归属 |
| D3-004 Agent Claim 1 | Claim 自己包含实验归属，因此三连败规则 `supported`，实验归属部分缺支持 | 整条记 `partial`；不是停止次数被判错 |
| D3-004 固定 RAG Claim | 只陈述 Reflexion runs 的停止规则，实际引用支持这条较窄表述 | Claim 记 `supported`，但原问题的章节与实验范围仍未获独立证明，整题严格不计 |
| D6-003 两模式 Claim 2 | 关于生成者的表述存在歧义，引用不足以完全支持回答中的归属 | 两条均记 `partial`，两模式本题不计严格完整支持 |
| D5-005 Agent | 在选定 RAG 范围内补查后新增 3 段展示，仍没有 Reflexion / HotpotQA 停止规则；最终理由准确限于本轮证据 | 合理拒答，额外调用没有答案增益；保留为成本观察，不新增拦截规则 |

这 3 条 `partial` 来自 D6-003 两模式的 Claim 2，以及 D3-004 Agent 的 Claim 1。D3-004 固定模式没有 `partial` Claim，却仍未满足整题严格完整支持，说明 Claim 支持与整题完成需要分别判断。

F 按本次开发评价直接冻结当前 D 批次与提示版本，保留上述已知问题，不继续修改代码或通过重复调用追求分数。G 交接仍待执行；本页不把尚未发生的验收或用户确认记为完成。

## 4. 调用、验证与保存边界

E 全部复用已保存的 D 请求统计：实际整个 D 批次为 **23 次 embedding、42 次聊天请求**，embedding tokens 为 922，聊天已知 tokens 为 106692。共同首次检索各只实际发送一次；固定模式与 Agent 的逻辑 embedding 归属相加不能当作新增实际请求。

D 保存的聊天聚合 `total_tokens=null` 继续保留，已知小计仍为 106692；E 没有将未知字段填成 0 或改写首次用量。本轮新增真实请求为 0。

本轮只形成评价与说明文档，没有改业务代码。按项目“文档、注释等不影响行为的修改不跑测试”的规则，**没有运行测试**；没有重复 A/B 的语法解析，没有计算或核对哈希。评价所需的阅读直接使用本批次已保存材料，完成后只回读本页内容。

## 5. 你怎样学习：约 25 分钟

只需理解 JSON 的对象、数组与字段关系。阅读已保存文件即可，不需启动服务、重跑批次或发模型请求。

1. **4 分钟：区分三个指标。** 先读本页第 2 节，再对照 [D 的机器观察](/D:/course/paper-research-assistant/docs/v1/d10/d10-D-development-run-guide.md)。用自己的话解释 `answered`、必要内容覆盖、严格完整支持分别在判断什么。
2. **5 分钟：读一题完整有据的答案。** 打开 [D5-001.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-001.json)。沿 `pair.modes.agent.result` 找 `answer.claims`、`citation_ids`、`context.shown_evidence` 与 `answer.evidence_sources`。指出哪一句分别支持 NQ RAG 初始化和“小规模”原因。
3. **5 分钟：理解机制题为何需要补查。** 打开 [D2-002.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-002.json)，看 Agent 的动作和最终引用，再对照 [逐题评价](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md)。说明补查如何让 Sequence / Token 的关键关系完整出现，而不只回答相关事实。
4. **5 分钟：看一个“有数字但归属未证实”的例子。** 打开 [D3-004.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D3-004.json)。将题目中的 Section 4.2 / HotpotQA 与实际引用文字分开，解释为什么三连败规则有据，整题仍不计严格完整支持。
5. **6 分钟：做下面六题并核对答案。** 最后用 [D5-005.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-005.json)说明合理拒答和补查增益可以得出不同判断。这是建议学习路线，不是用户已经完成学习的记录。

## 6. 练习与参考答案

### 题 1：Agent 已经 `answered` 17/17，为什么严格完整支持只有 15/17？

**参考答案：**`answered` 说明程序发布了答案，不会自动证明所有内容有据。Agent 回应了全部 17 道可答题的必要内容，但 D3-004 的实验归属未由实际引用独立证明，D6-003 Claim 2 的生成者表述有歧义。因此这两题不计严格 `complete_supported_answer`，得到 15/17。这个数字是 AI 对本批次的观察，人审仍 pending。

### 题 2：一条 Claim 引用两段，一段只支持部分内容，是否必须将整条判 `partial`？

**参考答案：**不一定。应先分别看每个实际引用支持什么，再看该 Claim 自己的引用并集能否完整支持整条陈述。并集足够时可判 `supported`；并集仍缺关键关系或限定时才是 `partial`。不能使用该 Claim 没引用的其他展示片段，更不能用未展示 PDF 或标注答案来补齐。

### 题 3：D3-004 固定模式的 Claim 是 `supported`，为什么整题仍不计完整支持？

**参考答案：**固定模式的 Claim 只说 Reflexion runs 的连续三次失败停止规则，引用直接支持这条较窄表述。但题目还限定 Section 4.2 / HotpotQA，实际引用没有独立证明规则属于该章节和实验。因此该 Claim 可以 `supported`，整题却仍缺来源归属支持。把题面中的限定复制到评价理由，不能替答案补证。

### 题 4：D2-002 Agent 本轮可以怎样说明改进，不能怎样说明？

**参考答案：**可以依据实际动作说它执行了补查，并依据最终展示与真正引用说 4 条 Claim 均有据、机制问题完整覆盖。不能只凭补查动作、引用 ID 合法或程序 `answered` 就判修复成功，也不能把这一开发题的成功扩大成所有机制题都已经解决。E 给出了该题当前批次的具体改进证据，F 据此冻结，不需要再次重跑来证明同一事实。

### 题 5：D5-005 Agent 最终合理拒答，是否说明它的补查有用？

**参考答案：**不能。拒答合理性与补查增益分别判断。该题始终限定选定 RAG 论文，补查新增的预处理、图标签和参考文献片段没有停止规则；最终不猜阈值、理由限于本轮展示，因此拒答合理。相较固定模式多一次 embedding 和一次聊天，却没有答案增益，应记录成本观察，不能用新增 3 个 chunk 宣称改善了答案。

### 题 6：E 为什么不回写 JSON 的 `not_reviewed`，也不运行测试或哈希？

**参考答案：**JSON 保存 D 的首次运行状态，E 的 AI 事后观察另存 `dev_comparison.md`，这样读者能区分程序记录和后来评价；没有用户人工确认，就保持人审 pending。E 只阅读保存输出并写评价文档，不修改业务行为，项目明确规定这类文档修改不跑测试。已有调用与验证仍适用，额外测试或哈希不能补足语义依据，因此本次新增真实 API、测试、哈希均为 0。

## 7. E 完成后的接续

本页记录 E 的已完成评价与学习建议。详细 Claim、来源、覆盖、拒答和补查判断以 [dev_comparison.md](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md)为准；原始首次记录保持 D 批次内容。F 冻结当前批次与 `d10-source-scoped-agent-v1` 提示，保留 D3-004、D6-003 及无增益补查观察，不继续改代码。G 仍待执行，实际阶段状态见 [D10 总计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。
