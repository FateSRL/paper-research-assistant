# D10 D：完整开发对照日志、学习路线与参考答案

执行日期：2026-10-07（Asia/Shanghai）。**D 已完成新版本 20 题、两模式共 40 份首次输出，批次和导出均为 completed，CLI 退出码 0。** E 的完整语义评价、F 冻结和 G 交接尚未执行；程序生成状态不作为问答准确率。

## 1. D 工作日志

承接 [C 的验证选择](/D:/course/paper-research-assistant/docs/v1/d10/d10-C-verification-guide.md)，使用 A/B 修改后的当前 Agent 提示，未在批次中途修改源码或策略。没有先运行额外付费四题冒烟，也没有使用精简前的 prepared 或拼接旧答案。

本次批次为 `d10_d_dev20_20261007_195707`。准备记录时间为 **19:57:12**，最终汇总时间为 **20:02:11**，均为 2026-10-07 的北京时间。正式开发集包含 17 道可答题、3 道负题；全部 20 题已尝试且保存最终题记录，剩余 0。各题均有固定 RAG / Agent 两份运行结果、机器评分及现有 JSON/Markdown 导出；本次无需续跑。

直接使用当前 `scripts.run_agent_comparison --stage d9` 入口，显式传入开发集全部 ID。D10 是实施阶段，d9 是沿用的运行策略与保存目录。Agent 实际结果记录提示版本 `d10-source-scoped-agent-v1`；没有另建 D10 runtime。

实际执行命令如下，**它们已经运行，阅读日志不需要再执行**：

```powershell
$d10ExecutionCases = @(Get-Content -LiteralPath 'eval/dev.jsonl' -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object { ($_ | ConvertFrom-Json).case_id })
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --stage d9 --batch-id d10_d_dev20_20261007_195707 --case-ids $d10ExecutionCases
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --stage d9 --batch-id d10_d_dev20_20261007_195707 --execute-prepared
```

准备阶段真实请求为 0，第二条命令执行本次已授权的真实问答。本轮没有新增测试、外置预检或源码/历史哈希审计，也没有读取验收题或修改正式题目、语料与索引。

## 2. 结果保存在哪里

| 材料 | 位置与作用 |
|---|---|
| 本批次题目、公开配置、模式和来源范围 | [manifest.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/manifest.json) |
| 已尝试、已完成与剩余题目 | [state.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/state.json) |
| 完整两模式结果、机器指标和实际用量 | [summary.json](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/summary.json) |
| runner 保存的简短完成说明 | [summary.md](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/summary.md) |
| 每题首次结果和调用前预占记录 | 同一目录的 `<case_id>.json` / `<case_id>.attempt.json`；逐题链接见下表 |
| 模式运行的 JSON/Markdown 历史 | 沿用 `archive/run_logs/d9/`；具体文件由每份模式结果的 `history_report` / `history_markdown` 字段指向 |

原始输出、费用和机器评分保持 runner 保存的内容。本页只是用户要求的独立工作日志，不另复制整批证据或生成校验包。

## 3. 实际机器观察

| 项目 | 固定 RAG | Agent |
|---|---:|---:|
| 回答 / 不足 | 15 / 5 | 17 / 3 |
| 17 道可答题的程序 answered | 15/17 | 17/17 |
| 可答题不足 | 2 | 0 |
| 3 道负题的程序不足 | 3/3 | 3/3 |
| 输出结论数 | 39 | 50 |
| 引用定位通过 | 45/45 | 52/52 |
| 补查 | 无 | 3 次 |

没有工具、格式、预算或导出失败。本批次无需网络重试和输出修复。表中的 answered、引用定位和负题不足均为程序指标；尚未逐结论评价语义支持、整题完整性或拒答合理性，不能把 17/17 写成 Agent 人工准确率。

三个实际补查题是 **D2-002、D2-003、D5-005**。D5-005 是负题，补查后仍不足，额外调用及其是否值得将在 E 的成本与拒答评价中说明。

| 题目原始记录 | 类型 | 固定 RAG | Agent | Agent 补查 |
|---|---|---|---|---|
| [D2-001](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-001.json) | 可答 | 回答 | 回答 | 无 |
| [D2-002](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-002.json) | 可答 | 不足 | 回答 | 一次 |
| [D2-003](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-003.json) | 可答 | 不足 | 回答 | 一次 |
| [D2-004](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-004.json) | 可答 | 回答 | 回答 | 无 |
| [D2-005](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-005.json) | 可答 | 回答 | 回答 | 无 |
| [D2-006](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D2-006.json) | 负题 | 不足 | 不足 | 无 |
| [D3-001](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D3-001.json) | 可答 | 回答 | 回答 | 无 |
| [D3-002](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D3-002.json) | 可答 | 回答 | 回答 | 无 |
| [D3-003](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D3-003.json) | 可答 | 回答 | 回答 | 无 |
| [D3-004](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D3-004.json) | 可答 | 回答 | 回答 | 无 |
| [D5-001](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-001.json) | 可答 | 回答 | 回答 | 无 |
| [D5-002](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-002.json) | 可答 | 回答 | 回答 | 无 |
| [D5-003](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-003.json) | 可答 | 回答 | 回答 | 无 |
| [D5-004](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-004.json) | 可答 | 回答 | 回答 | 无 |
| [D5-005](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-005.json) | 负题 | 不足 | 不足 | 一次 |
| [D5-006](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D5-006.json) | 负题 | 不足 | 不足 | 无 |
| [D6-001](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D6-001.json) | 可答 | 回答 | 回答 | 无 |
| [D6-002](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D6-002.json) | 可答 | 回答 | 回答 | 无 |
| [D6-003](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D6-003.json) | 可答 | 回答 | 回答 | 无 |
| [D6-004](/D:/course/paper-research-assistant/artifacts/d9/comparison/d10_d_dev20_20261007_195707/D6-004.json) | 可答 | 回答 | 回答 | 无 |

## 4. 调用与 tokens

| 账本口径 | Embedding 次数 / tokens | 聊天 SDK/HTTP 次数 / 已知 tokens |
|---|---:|---:|
| 实际整个批次 | 23 / 922 | 42/42 / 106692 |
| 固定模式独立运行的逻辑归属 | 20 / 833 | 19/19 / 42850 |
| Agent 独立运行的逻辑归属 | 23 / 922 | 23/23 / 63842 |

20 次共同首检索各实际发送一次，Agent 三次补查另计，因此实际 embedding 为 23；两模式逻辑归属相加为 43，不能当作实际付费次数。两模式聊天分别执行，19＋23＝42。embedding 失败 0、网络重试 0、输出修复 0；没有查询服务价格或估算金额。

原始聊天 `total_tokens` 为 `null`，`known_total_tokens` 为 106692。原因可直接见 D2-003 固定模式：0 聊天，`usage_complete=false`、`total_tokens=null`、已知小计 0，这个记录使聚合总字段继续为 null。这里保留原字段，单列已知总量，不改写首次统计或把 null 当作 0。

## 5. 两个重点结果怎样接给 E

**D2-002：**固定模式仍不足；Agent 这次实际选择并执行了补查。新回答包含“Sequence 整段使用同一文档”和“Token 可按 token 使用不同文档”，并补充长度 1 时的等价情况。相较旧记录，可以确认“未补查、只答相关事实”的动作和输出发生了变化；每条结论是否由实际引用充分支持、重复表达是否影响完整性，留 E 评价，D 不预填整题正确结论。

**D2-003：**固定模式首轮来源不足；Agent 一次摘要范围补查后发布 HotpotQA / Fever 两条结论，现有来源检查记录为 valid。D 已保存来源约束与补查轨迹；E 仍须分别评价原文支持和整题要求，不能只凭 valid 当作准确率。

全部 40 份输出的 `semantic_support_status` 仍按运行记录为 `not_reviewed`，QA accuracy 未测量，人审 pending。本轮没有复用 D8/D9 的答案补新结果，也没有进行 E 的全量语义评分。

## 6. 你怎样学习：约 25 分钟

阅读保存材料即可，不必再次执行真实命令。需要的 Python 基础是函数、字典、列表、条件判断和文件路径。

1. **4 分钟：准备和执行。** 看 [prepare_batch()](/D:/course/paper-research-assistant/scripts/run_agent_comparison.py:70)和 [main()](/D:/course/paper-research-assistant/scripts/run_agent_comparison.py:334)。区分保存计划与发起真实请求。
2. **5 分钟：理解进度。** 打开本批次 manifest/state，找 `case_ids`、`split`、`modes`、`attempted_case_ids`、`completed_case_ids` 和 `remaining_case_ids`。再看 [execute_batch()](/D:/course/paper-research-assistant/scripts/run_agent_comparison.py:165)，理解已尝试和已保存最终记录为什么不同。
3. **5 分钟：共享首轮。** 看 [FrozenFirstSearcher](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py:46)和 [aggregate_usage()](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py:31)，用本次 23 实际 / 43 逻辑 embedding 解释费用归属。
4. **5 分钟：读机器指标的边界。** 看 [agent_evaluation.py](/D:/course/paper-research-assistant/paper_assistant/agent_evaluation.py)，找出程序 answered、精确命中和引用定位各回答什么问题。用 D2-002 新旧记录说明为什么还需要 E。
5. **6 分钟：回答下面五题。** 先用自己的话解释，再看参考答案。学习安排不是用户已经学习或通过的记录。

## 7. 练习与参考答案

### 题 1：准备、execute-prepared、resume 分别做什么？

**参考答案：**默认准备保存题目、参数和初始状态，不生成论文答案。`--execute-prepared` 执行未尝试的同名 prepared 批次，会发真实请求。`--resume` 只继续已有批次中未尝试题，不重播已尝试或失败题。`--live` 则新建并立即执行；三个执行标志互斥，本轮使用先准备、后执行，没有 resume。

### 题 2：为什么实际 embedding 是 23，逻辑相加却是 43？

**参考答案：**每题共同首检索只请求一次，共 20 次；Agent 另补查 3 次，所以实际是 23。逻辑归属表示每模式独立运行需要的检索，固定模式归属 20，Agent 归属 23；共同首检索被各自归属一次，相加时重复计算了 20 次。逻辑总和不能用来算实际费用。聊天分别执行，所以其实际次数可以按两模式相加。

### 题 3：失败后可以删 attempt，再用 resume 重跑吗？

**参考答案：**不可以。`attempt.json` 在调用前保存，失败也可能消耗请求和 tokens。删除它重播会破坏首次记录。`resume` 继续未尝试题，已有 attempt 却缺最终记录时先查看失败现场，不自动重播；确需复测另建并标注新批次。失败仍属于计划分母。本轮没有失败，也没有删除或重播。

### 题 4：completed、answered、引用定位通过能否证明全部答对？

**参考答案：**不能。`completed` 表示计划题目已按流程保存结果，允许包含正常不足。`answered` 表示程序发布答案；引用定位表示原文来源匹配。它们不自动证明实际引用支持全部结论或覆盖原题。E 才按最终展示、引用、原问题评价支持、来源、完整性和拒答合理性，不能提前把机器 17/17 当语义准确率。

### 题 5：为什么 D10 使用 stage d9？为什么 tokens 为 null 却有已知总量？

**参考答案：**D10 是当前工作阶段；`stage d9` 选择已有受控入口和保存目录，用新批次区分新实验，无需复制 runtime。tokens 的 null 说明聚合字段没有完整数值，程序同时保留已知小计；本次固定 D2-003 的零聊天占位记录传播了 null，因此日志保留原 null 并单列 106692 已知 tokens。不能将一般未知用量随意填 0，也不需要为这次运行重写旧统计。

## 8. 下一步

E 使用这一批次的 40 份首次输出进行完整事后评价；判断每条结论支持、原题完整性、来源约束、拒答合理性和补查成本。需要人审时只记录用户实际确认范围。F 再根据开发证据决定必要修复与最终冻结，G 汇总交接。当前进度见 [D10 总计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。

