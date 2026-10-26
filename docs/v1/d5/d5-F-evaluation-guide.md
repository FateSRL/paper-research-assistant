# D5 任务 F：开发题集初跑、候选题与答案评价

记录日期：2026-10-04（Asia/Shanghai）。**正式十题的首次真实问答、机器统计和 AI 逐题评价已完成；六道新增题仍为候选，正式十六题初跑尚未完成。** 本轮 7 题返回答案，3 题返回不足，其中 2 道可回答题未检到所需依据。自动补检索仍是 D8 计划。

用户对六道候选的实际回复为：**“暂未复核，先保留候选”**（2026-10-04）。因此候选继续保留 `ai_reviewed`，人工状态为 `pending`，不并入正式文件。见 [人工状态记录](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_human_review.json)。

前置流程见 [E 问答 CLI 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)，任务范围见 [D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)。F 复用已实现的一轮检索和问答流程，保存第一次结果，再评价检索、引用和答案；期望要点、标准引文与可回答性只用于事后评价，不进入问答提示词。

## 1. 先看四类代表题，再继续同一批十题

| 题目 | 本次首次结果 |
|---|---|
| D2-001 · RAG | answered；参数记忆为预训练 seq2seq/BART，非参数记忆为 Wikipedia 稠密索引/神经检索器，引用 PDF 文件页 1/2 |
| D2-005 · Reflexion | answered；不更新权重，使用语言反馈和反思记忆指导后续尝试，引用页 1/2/4 |
| D2-003 · ReAct | insufficient_evidence；本轮没有摘要依据，正文中同事实不能满足摘要限定；仍是可回答题未完成 |
| D2-006 · 资料外题 | insufficient_evidence；选定论文不提供所问 API 价格，未编造价格 |

下面保留本次已经执行的批跑命令。`--live` 会调用真实 embedding 和聊天服务。四题是同批的前四题，再同批补余六题，没有重复付费。本批已完成；日常纯查看用 `Get-Content` 阅读已有文件。下方不带 `--live` 的 `--resume` 不请求模型，但会更新派生汇总，不是纯读取。

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_qa_baseline `
  --batch-id d5_f_dev10_20261004 `
  --live `
  --case-id D2-001 `
  --case-id D2-005 `
  --case-id D2-003 `
  --case-id D2-006
$LASTEXITCODE
```

检查四题记录后，继续同一批的剩余六题：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_qa_baseline `
  --batch-id d5_f_dev10_20261004 `
  --resume `
  --live
$LASTEXITCODE
```

`--resume` 先检查题集、源码、模型配置、版本和评分规则是否仍与本批一致；已尝试题即使失败也不自动重跑。准备新批时不带 `--live`，只保存配置、题序和评分规则，不请求模型。需要核对并更新派生汇总时可离线执行，它会更新 manifest/summary 并创建临时锁：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_qa_baseline `
  --batch-id d5_f_dev10_20261004 `
  --resume
```

同名批次不会被重置。以后要做不同代码或配置的回归，应使用新的批次名，保留本次原始结果。若出现 `needs_attention`，先检查该题的预占和运行记录；中断时可能已发生请求，不通过删除文件直接重跑。

## 2. 运行记录在哪里

本批目录：`D:\course\paper-research-assistant\artifacts\d5\qa_baseline\d5_f_dev10_20261004\`。

| 文件或目录 | 用途 |
|---|---|
| `manifest.initial.json` | 首次配置、题序、源码及题集绑定，不覆盖 |
| `rubric.json` | 本批冻结的机器评分规则 |
| `manifest.json` | 当前进度、已尝试题、尚未尝试题及需处理题 |
| `results/<case_id>.json` | 每题第一次 CLI 完整结果、退出码、历史记录来源与机器检查 |
| `reservations/<case_id>.json` | 请求前预占；只有预占而无结果时需要检查是否已调用 |
| `summary.json` / `summary.md` | 机器指标、各题终态、请求和用量汇总 |
| `ai_semantic_review.json` / `.md` | 每个要点、结论及结论与引用配对的 AI 支持度，人工待评 |
| `batch_verification.json` / `.md` | 174 项配置、原始输出、消息隔离、费用与评分重算核对 |

每题还保留 E 的不可覆盖历史记录，文件位置由逐题结果中的 `source_history_report` 指出。最近一次的 [answer_result.md](/D:/course/paper-research-assistant/artifacts/d5/answer_result.md) 会随问答更新，回看初跑应以批次逐题记录及其历史来源为准。

## 3. 机器、AI 和人工分别看什么

评分规则已在首次 F 付费问答前保存：[简单说明](/D:/course/paper-research-assistant/artifacts/d5/qa_evaluation_rubric.md)、[完整规则](/D:/course/paper-research-assistant/artifacts/d5/qa_evaluation_rubric.json)。这次是开发集初跑，不是冻结验收集成绩。

**机器检查**看精确标注引文有没有出现在返回候选和实际展示正文中，分别统计；只合并空白，并核对论文、PDF 哈希和文件页码。这是精确目标命中观察，不等于语义检索召回率。机器还记录 `answered` 数、可回答题错误拒答数、无答案题返回不足数、最终引用定位、被拦截的早期草稿、终态、请求次数、用量与耗时。

**AI 逐题评价**看全部期望要点是否覆盖，每条结论是否被它自己引用的本轮原文支持，问题的来源限制是否满足，不足理由是否合理。一个结论有多条引用时，也分别检查每条引用；不能用其中一条正确引用掩盖另一条无关引用。要点完整、事实都有依据且来源符合限制，才算 AI 判断的完整回答。AI 评价使用保存的输出和证据，不新增 judge API。

**人工评价**仍待实际复核。原十题的题目标注已由用户确认，不代表本次生成答案也通过人审。人工支持率填写 `N/A / 待评`，不能把程序定位通过或 AI 判断写成人工准确率。

## 4. 怎样解释失败

| 现象 | 初步归因 |
|---|---|
| 关键标注依据没有出现在本轮候选 | 检索目标未命中；另看是否存在其他同样有效的语义证据 |
| 候选有依据，但展示集合没有 | 上下文选择或正文预算省略 |
| 展示了依据，却漏答、答错或写了无依据内容 | 生成或语义支持问题 |
| 正文支持事实，但问题要求摘要 | 来源范围不符合问题限制 |
| 引用未展示、跨范围或实际来源不一致 | 引用校验问题，保留被拦截记录 |
| JSON/字段/输出形状不合要求 | 结构问题 |
| 服务、数据或运行故障 | 系统问题；不能当成正确拒答 |

**ReAct D2-003 始终是可回答题。** D4 的原 top-5 缺少题目要求的摘要依据；本次新查询以实际候选和展示结果为准。若仍缺摘要而拒答，可以是合理遵守证据限制，但仍计为可回答题未完成，不计入无答案题正确拒答，也不修改标注。若本次确实检到并展示了摘要，可正常回答。不能从评分标注偷偷补摘要或扩大 top-k。

同样，复合问题只回答了部分要点时不能算完整。第一次的错误、非零退出和不足都留在报告中，不删题、不改标注，也不无记录地重跑后覆盖首次失败。

## 5. 六道候选保留在哪里

材料入口：[候选复核包](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_review.md)、[候选 JSONL](/D:/course/paper-research-assistant/artifacts/d5/eval_candidates.jsonl)、[来源验证](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_validation.json)。

| 候选题 | 类型与新内容 |
|---|---|
| D5-001 | fact：RAG 中 CT/WQ 使用 NQ RAG 模型初始化及原因 |
| D5-002 | fact：ReAct ALFWorld 标注 3 条轨迹，取 2 条按顺序构造 6 个提示 |
| D5-003 | fact：Reflexion 的 Actor、Evaluator、Self-Reflection 三组件职责 |
| D5-004 | fact：LeetcodeHardGym 的 40 道 hard 题与 19 种语言覆盖 |
| D5-005 | unanswerable：仅选 RAG 论文，不能提供后来 Reflexion 的 HotpotQA 重试上限 |
| D5-006 | unanswerable：ReAct 论文不提供本地项目 Streamlit 界面发布日期 |

四道事实题的五段原文已与固定 PDF 指定文件页、正式段、完整 chunk 和只读 SQLite 对照；AI 看过完整页面截图。两个无答案题核对了所选论文的完整文本、版本和研究范围，标签不是因为 top-5 漏召回。候选准备 API 0 次，正式十题、PDF、分块和 SQLite 不变。它们目前仍是 AI 初审，人审字段为空。

用户以后逐题核对问题、要点、原文和页码，并明确确认后，才能合并到唯一正式 [eval/dev.jsonl](/D:/course/paper-research-assistant/eval/dev.jsonl)。原十题的确认记录保留；确认后目标分布才是 `8 fact / 3 method / 2 retrieval_paraphrase / 3 unanswerable` 共十六题。六题补跑使用新的题集绑定，保留这次十题初跑，不覆盖原批次。

## 6. 实际结果与后续步骤

| 指标 | 本次观察 |
|---|---|
| 已首次运行 / 计划正式题 | 10/10；10 个不同 run_id，首四题未重复调用 |
| 程序终态 | answered 7；insufficient_evidence 3；系统/结构/预算故障 0 |
| 可回答题程序完成 | 7/9；2 道可回答题拒答，不是正确负例 |
| 精确全部标注引文命中 | 返回 5/9，展示 5/9；单条引文均为 7/12，不是语义召回率 |
| 最终引用定位合法 | 21/21；早期结构或引用拦截 0，不能据此断言语义全部正确 |
| AI 判断的完整支持回答 | 7/9 可回答题；2 道拒答合理但仍未完成 |
| AI 判断的资料外合理拒答 | 1/1，只覆盖一个基本资料外问题 |
| AI 结论支持 | 19/19 个发布结论由其实际引用原文并集支持；21 次结论与引用配对中 19 完整支持、2 部分支持 |
| 新答案人工支持率 / 准确率 | N/A，pending |
| 实际请求 / tokens | embedding 10 次/379；聊天 SDK/HTTP 10 次/22612；总网络 20 次；重试/修复 0 |
| CLI 记录区间耗时 | 总计 98.456 秒，中位数 9.000 秒，最大 14.006 秒；不含其他批次组织时间 |
| 验证与保留 | 46 项离线边界、174 项记录核对通过，核对新增 API 0；332 项旧源码、正式输入和验收文件哈希不变 |

逐题原文依据见 [AI 评价](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/ai_semantic_review.md)，机器统计见 [初跑汇总](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/summary.md)，实际配置见 [冻结配置](/D:/course/paper-research-assistant/artifacts/d5/qa_runtime_config.json)，完整阶段记录见 [task_f.json](/D:/course/paper-research-assistant/artifacts/d5/task_f.json)。这十道开发题只初跑一次，尚未测量多次稳定性，也不是冻结验收集。

两个实际未完成案例：D2-003 的五条证据只有正文/参考文献，没有摘要；D2-002 检到了表格、分类等价和解码说明短句，没有两种方法使用文档的规则。模型均返回不足，没有直接用通用知识补答；质量统计仍计未完成。两题保留初跑，不改标签、top-k 或代码后覆盖结果。

另两题说明精确引文指标的限制：D2-004 虽未命中标注的摘要原句，但问题没有要求摘要，所引正文可以支持答案。D3-004 只命中了停止条件引文，引用实际属于 PDF 第 6 页的 4.2 HotpotQA 结果段；在题面限定下支持“同一任务连续失败三次后停止”，没有把这个条件扩展为所有 Reflexion 任务。单独转载该回答时应显式保留 HotpotQA 实验范围，不能用未展示的资料补充新事实。

| 项目 | 当前状态 |
|---|---|
| 十题正式开发集 | 保持原题及人工标注 |
| 四题代表试跑、其余六题初跑 | 已完成，全部保留首次输出与历史 |
| 机器指标与实际用量 | 已统计，与原始请求和 usage 核对一致 |
| AI 答案支持度评价 | 十题逐条已完成，新增 judge API 0 |
| 新答案人工语义评价 | pending；人工支持率 N/A |
| 六题新增标注人工复核 | 用户明确暂未复核，继续保留候选 |
| 正式十六题合并与完整初跑 | 未完成 |

六题继续保持候选，等用户实际核对后再合并并补跑；新答案的人审独立保留 pending。G 已据现有记录完成工程汇总与 [D6 交接](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md)，D5 总状态仍为“实现完成，评测/人审待补”。D6 页面直接复用固定 RAG，D8 才实现是否补检索的 Agent 决策。
