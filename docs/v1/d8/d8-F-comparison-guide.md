# D8 F：四题首次真实成对实验与人工复核

执行日期：2026-10-05。F 已完成四道开发题、八份模式的真实首次运行，完整轨迹/供应商用量、机器核对、独立 AI 初审和人审包已保存。用户随后确认“我的审核和AI相同”，八模式总体结论已补记为用户确认 AI 审核结论；A–F 完成记录范围，G 汇总待做，D7 暂缓，验收仍留 D11。

## 1. 实际看到了什么

本批次为 `d8_f_dev4_20261005`。三篇 1188 个 chunk 的 ready 配对、实际公开配置与 A 策略一致；真实前确认 Qdrant 可独占打开并关闭，使用新批次，E 的零费用 prepared 批次保持原样。原问题和完整版本进入问答，case_id、期望答案、标注引文和可答标签只用于事后评分。

| 题目 | 固定 RAG 首次状态 | Agent 首次状态 | AI 初审（用户已确认总体判断） |
|---|---|---|---|
| D2-001：RAG 两种记忆组件 | answered | answered，直接回答 | 两模式都完整有据；Agent 多写三条机制说明，未增加原题覆盖 |
| D2-002：Sequence / Token 使用文档的差异 | insufficient_evidence | answered，补查一次 | 固定模式本轮证据不足；Agent 新增两条展示依据，完整回答两种机制 |
| D2-003：ReAct 摘要点名哪些基准 | insufficient_evidence | answered，没有补查 | Agent 引用页4正文，却声称摘要点名，未满足来源限制；不能算完整支持的答案 |
| D5-006：本地界面上线排期 | insufficient_evidence | insufficient_evidence，没有补查 | 两模式都合理不足，未虚构排期；这是明显范围外负题 |

程序可答完成数为固定 `1/3`、Agent `3/3`；用户确认的 AI 原问题与引用支持判断为固定 `1/3`、Agent `2/3`。D2-003 展示了程序定位检查的边界：两个事实名和任务类型可由正文部分支持，但不能由正文证明“摘要点名”。当前总体确认已记录，独立逐结论/逐引用人审评分未提供，QA accuracy 仍未测量。

AI 逐条检查共 16 条发布结论：14 条由实际引用并集支持，D2-003 两条仅部分支持且违反范围。逐引用是另一个层次：RAG 两题的19次引用中15次完整、4次部分支持，同条其他引用补足；ReAct 两次正文引用部分支持但不能证明摘要归因。21/21 引用定位合法不能写成21/21语义正确。

## 2. 请求、证据与耗时

| 账本 | embedding 次数 / tokens | 聊天 SDK/HTTP 次数 / tokens |
|---|---:|---:|
| 实际本批次 | 5 / 201 | 9 / 22188 |
| 固定模式单独运行的逻辑代价 | 4 / 165 | 4 / 8544 |
| Agent 单独运行的逻辑代价 | 5 / 201 | 5 / 13644 |

四次首轮检索共用，加一次 D2-002 补查。两模式逻辑 embedding 合计9/366包含重复归属的首轮，不能拿它代替实际5/201。所有 usage 完整，网络重试、格式/引用修复均为0，没有额外调用项目模型做 judge；不从 tokens 推算人民币费用。

可答分母是3题、4段标注引文。初轮 Returned / Shown 全部标注命中 `1/3`，逐引文 `1/4`；Agent 最终全部命中仍 `1/3`，逐引文升到 `2/4`。补轮及合并仅 D2-002 适用，分母1题/2引文：全部 `0/1`、逐引文 `1/2`。未精确命中 Token 的标注原句，AI仍可用实际另一段引用确认语义支持，因此这两个指标需要分开看。

共享首轮实耗与两模式自身实耗见 [成对报告](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/comparison_report.md)。各模式从120秒减同一首轮耗时，初始化、判断/补查/回查/关闭扣自身额度，不扣另一模式等待。组件和不是两次独立实测墙钟时间；同步 embedding 剩余 deadline 和严格120秒中止仍未验证。

本次真实观察到直接回答、一次有新增展示的补查及直接资料不足；未观察到相同查询停止、无新增展示停止、无收益补查、故障/修复或预算终止。对应控制分支仍由 D/E 离线记录证明，不强迫模型复跑来覆盖分支。

## 3. 去哪里检验

| 要核对什么 | 文件 |
|---|---|
| 结论、代价和限制 | [成对报告](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/comparison_report.md) / 同名 JSON |
| 冻结样本、公开配置、源码/data/eval SHA | [manifest](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/manifest.json) |
| 实际共享首轮快照 | [首轮快照](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/first_retrieval_snapshots.json) |
| 逐题完整消息、动作、修复、引用及费用 | 同目录下 `D2-001.json`、`D2-002.json`、`D2-003.json`、`D5-006.json`；另有八份不可覆盖模式历史 |
| 机器评分与实际账本 | [summary](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/summary.json) |
| 独立记录核对 | [139项审计](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/f_machine_audit.md) |
| 独立 AI 逐结论/引用评价 | [AI汇总](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/ai_semantic_review.md)、[RAG两题](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/ai_review_rag_cases.md)、[ReAct两题](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/ai_review_react_cases.md) |
| 当前用户审核确认 | [确认说明](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review_confirmation.md)、[逐模式确认记录](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review.json) |
| 首次生成人审材料（历史pending状态） | [人审包](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review.md)、[原模板](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review_template.json) |
| 完成范围与保护核对 | [F完成记录](/D:/course/paper-research-assistant/artifacts/d8/task_f.json)、[首次保护报告](/D:/course/paper-research-assistant/artifacts/d8/task_f_integrity.json)、[本次确认保护报告](/D:/course/paper-research-assistant/artifacts/d8/task_f_human_confirmation_integrity.json) |

CLI 实际执行一次并退出0；没有再次付费尝试已运行题。八份历史 JSON/Markdown 与首次 case 记录保留。原机器汇总和输出不继承后续 AI 标签，AI另存；题目的 `human_verified` 也不继承给答案。

## 4. 本次已记录的审核与学习要点

用户已在本次聊天明确表示“我的审核和AI相同”，据此记录四题八模式的总体结论确认，方式为 `user_confirmation_of_ai_review`，无需重复填写原pending模板。本次确认包含 D2-002 补查后完整回答、D2-003 来源限制失败及两种模式对 D5-006 的合理拒答。

用户未另交独立逐结论/逐引用评分、实名或具体阅读时间，记录仅标注确认依据与记录时间。AI报告、机器汇总、首次输出及原人审包/模板保留生成时的历史状态；这些文件中的 `pending` 应结合当前确认记录阅读。全量答案人审及冻结验收仍另行开展。

后续学习仍可用这四题区分：题目是否完整回答、实际引用是否支持答案、来源是否满足“摘要”等限定、资料不足理由是否合理。D2-002 可比较两种机制与新增依据，D2-003 可比较摘要限制与页4正文引用。再用5次实际 embedding和9次逻辑归属解释为什么账本不能直接相加。检查这些记录不需要重跑问答。

## 5. 后续安排

这是四题开发冒烟。Agent 同时改变查询、证据选择和可能的聊天次数，不能把 D2-002 的观察归因于“改写单独有效”，不能证明优于固定 top-10/20，也不能外推全量人审准确率。D2-003 的来源限制失败留给后续开发修复，新版本保留本次首次结果。

当前 manifest 只规划四题，已经全部尝试，`remaining_case_ids=[]`。其 `--resume` 不能新增其余16题。后续完整20题需新建完整批次；也可单列16题，但要明确独立批次身份，不能把它拼称这个四题 manifest 的同一冻结实验。源码/配置/策略改变时同样建立新版本及新批次。

G 汇总与 D9–D11 交接待执行；D9 按需要接页面 Agent 模式并补时限/故障组合及旧六题 AI 缺口，D10 冻结正式配置，D11 执行冻结验收。全量答案人审、旧六题 AI 评价和 D7 交付事项保持原待办。
