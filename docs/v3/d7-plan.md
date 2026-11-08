# D7 稳定性回归与新 50 题问答对照

日期：2026-11-05（Asia/Shanghai）。

D7 用 D6 第二批的 N50-019、N50-034 验证当前库模式 Agent 的交付和时限行为。先在本地重放故障并验证修复，再用两道原题各做一次真实问答回归。D6 原始运行和评分作为对应版本的基线，两道已知案例的复测结果单独记录。

第 1～8 节保留已完成的定向回归。第 9 节安排新 50 道官方题的独立对照，第 10 节是本批执行提示词。

## 1. 基线与本轮目标

| 回归题 | D6 末次响应 | 末次调用耗时 | 整题耗时 | D6 运行状态 | D6 内容评分 |
|---|---|---:|---:|---|---|
| N50-019 | 正文只有 `The` | 626.828 秒 | 635.937 秒 | `answered` | 未通过 |
| N50-034 | 正文停在 `The authors` | 909.797 秒 | 934.828 秒 | `answered` | 部分正确 |

两题末次响应均为 HTTP 200、`finish_reason=stop`，末次调用均只发出一次 HTTP 请求，记录的请求超时参数为 300 秒。两题均使用了 2 轮 Agent 模型决策，未触发 120 轮上限。保存的响应已包含不完整正文，日志尚不足以定位服务端为何提前结束文本或长时间等待。[N50-019 原生记录](../../artifacts/v3/d6-qa-paired-new50-b2-20261103/native_reports/N50-019_agent_20261103_091939_615429_66ee1f980e91.json)、[N50-034 原生记录](../../artifacts/v3/d6-qa-paired-new50-b2-20261103/native_reports/N50-034_agent_20261103_100541_299285_4b478f08323c.json)

D7 执行前，当前库模式 Agent 的 `total_timeout=None`；本轮修复后改为 120 秒整题预算，见第 7 节。调用层将 `stop` 且非空的文本作为成功响应，最终验收主要检查输出类型、引用和来源范围。D7 验收三个行为。

1. 明显残片进入有限修复或 `invalid_output`，可交付正文才进入 `answered`。
2. 前置理解、检索、重排、读取、生成、重试和收尾共享整题截止时间。慢调用到期时能够结束用户等待，迟到结果不能提交为成功。
3. 模型轮数达到现有上限后停止探索，有剩余时间时沿用已取得的证据收尾。

当前两道异常题均在第 2 轮发生长等待。本轮真实回归固定原有轮数上限，使用离线小上限验证边界，以免将减少轮数和截止时间的效果混在一起。[现行策略](../../paper_assistant/d9_runtime.py)、[最终验收与收尾](../../paper_assistant/agent_graph.py)、[问题记录](issues.md#118-不完整正文仍被标为已回答)

## 2. 冻结原题、论文版本与运行条件

从 `eval/qasper/d6-new50-b2-v1/sample.json` 按 `case_id` 和 `question_id` 取原始 `question`，用 `papers.json` 核对实际论文与解析配对。两题均使用已有 ready 版本。

| case_id | 官方 question_id | 原题 | PDF 版本 | 本地 paper_id | parse_revision |
|---|---|---|---|---|---|
| N50-019 | `d53299fac8c94bd0179968eb868506124af407d1` | What is the performance of classifiers? | `2002.02070v1` | `local_e4ef7d4c7d3140b99fbb9726205e25cd` | `r_f73a9ea0a1657f47` |
| N50-034 | `206739417251064b910ae9e5ff096e867ee10fb8` | What argumentation phenomena encounter in actual data are now accounted for by this work? | `1601.02403v1` | `local_404cb18a683547deacea55a76763bc23` | `r_b19bf144f8af3edc` |

两题各只选本篇的完整 `(local_paper_id, parse_revision)` 配对。正式入口为 `d9_runtime.run_question`，参数固定为 `mode="agent"`、`library_mode=True`、`top_k=5`、`max_chars=8000`、`conversation_history=[]`、`answer_instructions="Please answer in English."` 和 `max_iterations=120`。每题使用独立的新会话和提交 ID。

生成、检索和索引条件以 D6 第二批输入为准。聊天使用 `deepseek-flash`、temperature 0.2、输出上限 4096、模型上下文 1,048,576。embedding 使用 `qwen3.7-text-embedding`、1024 维、cosine 和 profile `ep_cbf0f6caa97b962a`，重排配置为 `qwen3-rerank`。是否实际调用搜索或重排由 Agent 自行决定。运行前离线核对已配置的模型、索引与版本配对。发生变化时先记录差异及可比性。[D6 冻结输入](../../artifacts/v3/d6-qa-paired-new50-b2-20261103/input.json)、[题目与评分](../../eval/qasper/d6-new50-b2-v1/sample.json)、[论文版本](../../eval/qasper/d6-new50-b2-v1/papers.json)

业务模型只接收原题、所选论文和当前流程自然取得的信息。原答案、评分、目标数值和人工标注的证据位置留在评测侧。

## 3. 复测前置修复与验收边界

### 3.1 最终正文验收

在现有 Agent 最终验收入口补齐交付判定，覆盖常规工具循环最终输出和无工具综合。复用现有引用检查和发布流程。正常发布发生在正文与引用均通过后。

判定依据是通用的正文完成条件和当前答复结构。使用保存的单词输出和断尾响应检查真实缺口，也检查完整短答、合理的资料不足说明和正常带引用正文。保留内容评测中“部分正确”与运行层“已交付”的区别。可交付文本允许明确交代没有取得哪些证据。

检测到正文异常且还有时间时，沿用已有修复或无工具综合入口，最多给这类异常一次收尾机会。收尾使用当前证据并再次经过同一最终验收。仍不完整时返回 `invalid_output`，截止后使用 `budget_exceeded`。运行错误代码、原始响应和已知用量留在现有记录中。以运行内容判定异常，题号和论文 ID 只用于选择回归输入。

### 3.2 整题时限与轮数

D7 验证采用 **120 秒整题预算**，取项目普通 `ChatPolicy` 已有的 120 秒默认值作为试验起点。每次准备开始新的探索前检查剩余时间，**剩余 20 秒内转入收尾**。整题预算从问答入口开始，前置理解、后续工具、模型调用、重试和综合使用同一个单调时钟截止点。已开始的操作也受该截止点约束，阶段超时取当前剩余时间与阶段上限中的较小值。

优先复用 `ChatBudget`、剩余时间传递和业务提交前检查。截止点需要实际约束正在等待的慢调用。离线验收须覆盖本地真实阻塞或持续收到数据的长等待，确认到期返回、取消边界及迟到结果处理。只用假时钟可以验证阶段和提交判定。通过同步线程等待超时只能证明页面停止等待，记录必须说明后台任务和请求是否也已结束。[预算与请求参数](../../paper_assistant/llm_client.py)、[提交边界](../../paper_assistant/deadline.py)、[页面后台调用](../../app.py)、[HTTPX 超时语义](https://www.python-httpx.org/advanced/timeouts/)

实际实施按当前调用链选择能够取消的最小边界。正常路径、重试和收尾共用同一截止点。到期后终止后续付费调用和成功发布。保留 120 轮真实回归设置，离线用较小的 `max_iterations` 验证达到轮数后停止探索，以及剩余时间充足和已耗尽时的收尾行为。

## 4. 离线复现与进入真实回归的条件

离线检查使用现有日志、假客户端或本地可控慢响应。复用已有运行器和测试夹具，所有离线情形使用本地数据。

| 情形 | 输入与操作 | 通过条件 |
|---|---|---|
| 两道异常正文 | 从原生日志读取末次 `chat_attempts[-1]`，保留 `stop` 和原始正文。通过假客户端送入正式库模式 Agent 的最终验收路径 | 两段残片均被识别。修复成功时仅发布完整修复答复。修复失败时返回 `invalid_output`。常规输出和兜底综合都经过同一验收 |
| 合法短答与正常引用 | 使用已有正常夹具，覆盖直接简答、资料不足说明及带合法引用的正文 | 正常文本可以发布。引用范围与保存的原文仍一致 |
| 真实阻塞与迟到返回 | 在本地配置秒级测试预算，让请求等待超过截止点。另以已有预算夹具模拟到期后收到成功响应 | 调用链在试验截止附近实际进入 `budget_exceeded`。记录实际取消边界。后续请求停止，迟到成功不改变终态。可得的原始错误和用量仍保留 |
| 达到模型轮数上限 | 以假模型持续请求工具，离线传入小轮数上限。分别验证有剩余时间和时间耗尽 | 探索轮数受限。有预算时最多一次已有收尾，无剩余时间时以超时终态结束 |

优先使用覆盖实际改动的 1～3 个现有测试方法。预算提交可用 `scripts.check_llm.LLMChecks.test_late_success_is_budget_exceeded_and_still_records_usage`，到期后阻止重试可用 `scripts.check_llm.LLMChecks.test_deadline_expiring_after_failure_prevents_retry`。库模式回归可复用 `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` 中已有的真实入口假客户端夹具。仅在现有夹具不能覆盖本次残片或阻塞回归时，增加对应的最小故障用例。秒级真实钟检查需在执行前固定预算和本地容差，并分别记录业务终态时间与导出耗时。

只有正文验收、到期行为和轮数边界均已验证，且两道题的版本与运行条件核对完成，才进入下一节。离线证据若只能确认到期后禁止发布，应将实际中断仍待验证写入结果，先完成该前置缺口。

## 5. 真实问答回归

按 **N50-019 → N50-034** 的顺序，各提交一次修复版 Agent，合计 **2 次完整问答尝试**。这 2 次包括流程自然发生的聊天、查询 embedding、rerank 和预算内的既有重试或收尾。沿用已有论文和索引。两次运行各用空历史及新 ID，保留原生记录和页面同源的最终结果。

提交前写入尝试状态，返回后先保存原生报告及历史路径，再抽取统计。单题发生异常时按实际终态保存。若共享服务不可用，记录已经尝试的题与未执行的题。复测额度为每题一次，内容部分正确或执行失败均保留为结果。基线直接引用 D6，真实请求范围仅为这两道 Agent 回归题。

记录每题末次响应的 HTTP 状态、`finish_reason`、是否触发完整性检查与修复、模型轮数、读／搜次数、请求用量、总耗时、截止阶段和实际发布的正文。展示耗时采用本次执行的实际配置与计时边界。

## 6. 评价口径

- **离线机制验收。** 原样异常响应是否被拦截，合法短答是否仍可交付，实际慢调用能否到期结束，以及轮数达到上限后能否按剩余预算收尾。
- **真实回归交付。** 分别报告正常交付、受控超时或无效输出、其他执行失败及未执行。受控终止单列为运行行为，答案内容按实际交付评价。
- **真实内容检查。** 对照原始问题、实际 PDF、已展示原文及 D6 冻结 rubric。N50-019 核对分类器性能的指标、数值与比较基准，保留正文概括和表格数值之间的差异。N50-034 记录答复是否覆盖原问所指的现象，D6 中原问与 rubric 范围的争议继续单列。本轮交付验收独立于该争议。
- **成本与延迟。** 逐题对照原运行，使用本次和基线各自的实际用量。未知部分保留未知。两题是已知回归案例，评价限于本次运行和本地故障复现。

若真实复测生成了正常正文，记录这次正常交付。异常处理生效的证据来自离线重放，或实际复测中再次触发并被正确处理的异常。单次真题耗时用于该题回查，跨题稳定性需另有对应证据。

## 7. 执行记录与产物

执行日期：2026-11-05（Asia/Shanghai）。本轮已完成；真实请求仅为 N50-019、N50-034 各一次 Agent 问答，共 2 次完整尝试，无自动重跑。

### 7.1 实际改动

- `paper_assistant/deadline.py` 新增 `FINALIZE_RESERVE_SECONDS = 20.0`。
- `paper_assistant/d9_runtime.py` 的库模式 Agent 预算改为 `INTERACTIVE_AGENT_POLICY.total_timeout=120.0`，并在报告中写入 `question_budget_seconds`、`finalize_reserve_seconds`、`deadline_enforcement` 和 `budget_implementation_version`。既有 `max_iterations=120` 保持不变。
- `paper_assistant/agent_graph.py` 新增 `final_text_issue()` 并在 `validate_final()` 写入 `final_text_check`。明显空输出、断尾、孤立引用或不完整名词短语在一次现有综合后仍不合格时返回 `invalid_output`；正常短答、资料不足说明、数字答案和带终止标点的正文仍可交付。收尾综合的 `timeout_seconds` 取 `min(90, budget.remaining_seconds())`，入口检查剩余时间。
- `paper_assistant/langchain_agent.py` 在 `before_model` 和 `wrap_tool_call` 检查剩余 20 秒：不再开始新探索或付费工具调用，直接进入既有收尾；残片在 `after_model` 触发一次无工具综合，不另开修复循环。
- 测试补充了残片、正常短答、截止收尾、超期和小轮数的离线用例；`check_d9_e_runtime` 的旧策略断言按 Agent 120 秒更新。未改检索、分块、引用合同或其他问答入口。

### 7.2 离线验证

| 验证方法 | 结果 | 覆盖 |
|---|---|---|
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 通过（24.812 秒） | 正式入口假客户端：`The`／`The authors` 残片各最多一次综合；第二次仍残片时 `invalid_output`；`No.` 等完整短答可发布；20 秒内转入综合；121 秒超期返回 `budget_exceeded`；`max_iterations=1` 时停止探索并在剩余预算内收尾；既有引用和资源释放检查 |
| `scripts.check_llm.LLMChecks.test_real_local_blocking_request_is_cancelled_at_budget_deadline` | 通过（4.295 秒） | 本地 HTTP 服务真实阻塞 2 秒，预算 0.6 秒；HTTPX 在 0.6 秒请求超时，实测约 0.719 秒进入 `budget_exceeded/deadline_exceeded`；只发出 1 次 HTTP 请求，无迟到发布 |
| `scripts.check_llm.LLMChecks.test_late_success_is_budget_exceeded_and_still_records_usage` | 通过 | 截止后返回的成功响应仍记录 usage，但不成为成功终态 |
| `scripts.check_llm.LLMChecks.test_deadline_expiring_after_failure_prevents_retry` | 通过 | 失败后预算耗尽时不再重试 |

离线验证全部使用本地假客户端或本地 HTTP 服务，未发起真实模型、embedding 或 rerank 请求。真实阻塞验证的取消边界是同步 OpenAI/HTTPX 请求的读超时与连接关闭；没有 Future 或未纳管后台 worker。运行时在 `ExitStack` 中关闭聊天客户端、检索 store／searcher。操作系统层面的强制线程终止未声明为已实现。

### 7.3 真实问答回归

按 N50-019 → N50-034 顺序各调用一次 `d9_runtime.run_question`。固定参数为 `mode="agent"`、`library_mode=True`、`top_k=5`、`max_chars=8000`、`conversation_history=[]`、`max_iterations=120`、`answer_instructions="Please answer in English."`；每题使用独立新 `submission_id` 和 `conversation_id`，仅选择本题的 `(local_paper_id, parse_revision)`。

| case_id | 提交与完成（UTC） | 整题耗时 | 最终正文 | chat 尝试／tokens | 取证 | 模型轮数 | 终态 | 内容复核 |
|---|---|---:|---:|---|---:|---:|---|---|
| N50-019 | 06:36:26.345–06:36:38.720 | 12.359 秒 | 1,263 字符，4 条有效引用 | 3 次 HTTP／13,715 | embedding 0，rerank 0，context read 2 | 2 | `answered` | 完整；表 2 数值已核对 |
| N50-034 | 06:36:38.731–06:37:17.827 | 39.093 秒 | 5,636 字符，22 条有效引用 | 4 次 HTTP／72,660 | embedding 2，rerank 2，search 2，context read 3 | 3 | `answered` | 按冻结 rubric 复核为完整；原问范围争议单列 |

N50-019 的末次响应为 HTTP 200、`finish_reason=stop`、调用约 2.735 秒（记录的请求超时参数随剩余预算为 110.438 秒），无修复、无 synthesis，`final_text_check=valid`。回答给出 Table 2 的四个分类器全部 macro/micro 指标：KNN macro P/R/F1 为 0.6133/0.6086/0.5808，RF 为 0.5968/0.5947/0.5733，SVM 为 0.6080/0.605/0.5801，MLP 为 0.6094/0.6059/0.5795；micro-F1 分别为 0.6762/0.6687/0.6712/0.6778。回答明确指出 KNN 在三个 macro 指标最好、MLP 的 micro-F1 高于 KNN，并说明表格数值差距小、可见文本未给出划分细节。上述数值与 PDF Table 2 及 D6 固定 RAG 已核对值一致。D6 的 `fail` 标签保留为历史基线。

N50-034 的末次响应为 HTTP 200、`finish_reason=stop`、调用约 7.469 秒（记录超时参数 88.688 秒），无修复、无 synthesis，`final_text_check=valid`。回答先给出限定短答，随后分列 modified Toulmin／logos 维度纳入的现象，以及未完整建模或未解决的现象：rhetorical questions、figurative language、narratives、fallacies in general；并报告 pathos 标注一致性 α_U 0.30、ethos 被忽略、narrative 缺少统一理论。按 D6 冻结 rubric 的三条核心要求，该正文为完整。D6 的 `partial` 标签保留。

原问与冻结 rubric 的范围争议单独记录：原问是预设“已有现象被 accounted for”的 QASPER unanswerable 题；D6 rubric 要求必须指出未解决现象，而 D6 Agent 正文只列纳入模型的现象并截断。D7 新回答同时给出 accounted 与 not fully accounted 两侧，并对原问措辞作限定；因此本轮交付验收独立通过，但该原问／rubric 的口径差异不因这次回答而消失，也不回改 D6 的 `partial`。

两题均远低于 120 秒整题预算，未触发 `budget_exceeded`、`invalid_output` 或轮数上限；两题均无 repair、无网络重试、无 synthesis。与 D6 相比，N50-019 从 635.937 秒、正文 `The` 变为 12.359 秒、1,263 字符；N50-034 从 934.828 秒、正文截断于 `The authors` 变为 39.093 秒、5,636 字符。单次结果只说明这两题的本次行为，不据此重算 D6 的总体准确率或跨题稳定性。

原生日志：[N50-019](../../artifacts/v3/d7-ending-regression-20261105/native_reports/N50-019_20261105_063626_356570_9ed0bdf614cc.json)、[N50-034](../../artifacts/v3/d7-ending-regression-20261105/native_reports/N50-034_20261105_063638_735468_4f38aded2bdd.json)。冻结输入与逐题状态：[input.json](../../artifacts/v3/d7-ending-regression-20261105/input.json)、[results.json](../../artifacts/v3/d7-ending-regression-20261105/results.json)。每题一次尝试的提交记录保存在同目录 `attempts/`，未自动补跑。

### 7.4 问题状态回填

- 第 1.18 节（不完整正文仍被标为已回答）：当前 `library_mode=True` Agent 交付路径已按 D7 验证修复；两份原异常和正常短答均有离线重放，两题真实回归均发布完整正文。服务端为何提前返回 `stop` 或截断的根因仍未定位，D6 原记录保留。
- 第 1.19 节（首次失败与耗时长尾）：当前库模式 Agent 已有 120 秒整题截止和 20 秒收尾保留；D7 两题均在 12.359／39.093 秒完成。D6 其余长尾题（如 N50-040）未在本轮重跑，根因仍未定位，不能据此宣称长尾问题全部关闭。
- 第 1.20 节 N50-034 范围争议：D7 已按原问、PDF 和冻结 rubric 复核新回答；D6 的 `partial` 与 034 原问／rubric 争议继续保留，不因新回答修改历史评分。

D6 原运行及评分保持对应版本的历史记录；本轮产物不使用 D6 分数重算总体指标。

## 8. 两道已知故障回归的历史执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。按 docs/v3/d7-plan.md 执行异常结尾与长等待的定向回归，最后回填第7节并保留本提示词。

本轮范围是当前 library_mode=True 的 Agent 交付验收、整题截止和已有轮数边界。真实题仅 N50-019 与 N50-034，各一次。两题是 D6 已知故障回归。以 D6 已保存的输出和运行记录作为基线。评分校准与独立新题评测分别属于其他工作。

基线与固定输入
1. 从 eval/qasper/d6-new50-b2-v1/sample.json 与 papers.json 读两题原始 question、question_id、实际 local_paper_id、parse_revision 和 PDF 版本。用 D7 第2节核对。只使用已 ready 的固定论文版本。
2. 从 artifacts/v3/d6-qa-paired-new50-b2-20261103/results.json 定位两份原生报告。保留 chat_attempts[-1] 的 stop 和原始正文。019 的最终响应只有 The，034 的最终响应停在 The authors。两题均为2轮，末次调用分别耗时626.828与909.797秒。用已有记录复现基线。
3. 核对当前 d9_runtime、ChatBudget、RecordedLLM、Agent 图的最终验收与无工具综合路径。当前问题由真实异常响应及超期行为判定，题号只用于选择复测输入。

复测前置修复
1. 在现有最终验收和发布边界处理明显残片，让正常终答与综合共用检查。保留正常短答、资料不足说明和引用校验。异常正文在剩余预算内最多一次已有修复/收尾，仍失败时用 invalid_output。
2. D7 试验预算为整题120秒，剩余20秒内进入收尾。前置理解、聊天、检索、重排、重试和综合共享一个截止点，按剩余时间约束实际等待。复用现有预算和业务提交检查，并用实际可取消边界结束超期等待。到期后返回 budget_exceeded，迟到结果不能重新发布为 answered。记录本地取消和资源释放的实际范围。仅 Future.result 超时或返回后的假时钟检查属于等待/提交验证，实际阻塞必须单独验证。
3. 真题 max_iterations=120。离线小上限检查到达轮数后终止探索，剩余预算内才允许既有收尾。按已确认的两个故障做最小必要修改，保留入库、检索、分块、引用和其他问答入口的现有合同。

离线验证
使用本地假客户端重放两份异常响应，并覆盖正常短答与带引用正文。用秒级预算模拟真实阻塞，记录到期时间、实际取消边界、迟到结果和后续请求次数。验证小轮数上限及无剩余预算时的终态。按 D7 第4节从现有相关方法选择1～3个，复用已经通过且代码未改的验证。只有缺少这次故障覆盖时才补最小用例。离线不发真实模型或 embedding/rerank 请求，所有离线前置验收通过后进入真实回归。

真实回归
按 N50-019、N50-034 顺序，各调用一次正式 d9_runtime.run_question。mode=agent，library_mode=True，top_k=5，max_chars=8000，conversation_history=[]，max_iterations=120，answer_instructions="Please answer in English."。selected_versions 只传本题实际 local_paper_id/parse_revision。每题使用独立新 conversation_id 和 submission_id。生成模型、embedding、rerank、索引与 D6 第二批保持可比，执行前离线核对实际值并记录差异。
真实调用共2次完整问答尝试，包含正常流程里的模型、查询 embedding、rerank 和预算内重试/修复。模型只接收原题与当前论文，gold、旧答案、评分和人工证据位置留在评测侧。按每题一次保留执行结果。服务故障时记录已尝试与未执行项。

评价与产物
先存 attempted 和原生报告，再统计正文完整性、终态、截止阶段、模型轮数、取证次数、修复、用量和耗时。异常检测以离线重放或真实触发为证。将正常交付、受控终止和内容完整性分开记录。019 核对实际表格的分类器指标，034 单列原问与冻结 rubric 的范围争议。原评分作为历史基线。
保存 artifacts/v3/d7-ending-regression-<实际执行日>/input.json、results.json，并引用已有 archive/run_logs/d9 中的原生记录。回填 D7 第7节实际改动、验证和两题结果，按验证范围更新相关问题状态。完成后结束本轮。
```

## 9. 新 50 题独立问答对照规划（2026-11-05）

### 9.1 本批目标与对照范围

在新题上比较**按完整请求容量工作的固定 RAG**与**完成 D7 正文验收和整题预算调整的 Agent**。两组使用相同原题、选定论文版本、检索组件及生成模型，分别保留各自的正常产品流程。比较内容完整性、证据支持、实际交付和资源消耗。

D6 第二批首次执行的时间为北京时间 2026-11-03 17:07:57～18:41:44，落在 DeepSeek 官方记录的 API 部分中断时段。后续重试补齐了明确失败项，初次返回的部分结果仍来自该时段。本批在开始前固定服务状态记录、故障处理和配对分母，以便分别评价问答内容和运行交付。[DeepSeek 官方事故记录](https://status.deepseek.com/incidents/7202016104287?from=history&month=2026-11)、[D6 首次执行与重试](d6-plan.md#17112-阶段-b首次-100-次21-次失败与重试)

D6 两批是历史对照，D7 第 7 节是两道已知故障的同题回归。新批次的主结果仅使用本节 50 道题。D7 当前的有限预算和正文检查作为待评测版本的一部分。持续保活场景下的硬中断按独立的本地故障用例评价，本批的真实问答记录按实际到期行为解释。

### 9.2 已选题目与配比

本批使用本地 QASPER dev v0.3 的 **50 道官方原题**，编号 **V50-001～050**。涉及 11 篇论文，6 篇各选 5 道、5 篇各选 4 道。题目来自 [QASPER 原始数据](../../eval/qasper/raw/qasper-dev-v0.3.json)。

选题时读取当前 `eval/qasper/*/sample.json` 及 `artifacts/v2`、`artifacts/v3` 下的 `input.json`，共 69 份历史文件。本批的 50 个官方 question_id 与 11 个 arXiv ID 均未在这些记录中出现。按 arXiv 来源和规范化题名核对当前 SQLite，11 篇均未入库。新题含义限于本项目已检查的历史记录。

| 主类型 | 代码 | D6 第二批初选 | 本批初选 |
|---|---|---:|---:|
| 事实与设置 | F | 9 | 14 |
| 方法、机制与多项说明 | M | 21 | 19 |
| 结果、比较与统计数值 | R | 13 | 10 |
| 官方标注资料不足 | U | 7 | 7 |
| 合计 | — | 50 | 50 |

本批仍为单篇、单轮的官方问题。保留原句、拼写及 question_id，执行时从官方 JSON 取原始字符串，包括表格中不易展示的尾部空格。题型按原题内容划分，允许与前批配比有偏差。

- 7 道题的全部官方标注均为资料不足。题号为 V50-026、031、035、039、042、046、047。其余 43 道至少有一份可回答标注。
- 14 道题的官方 evidence 选中或提及表格。是否依赖表格，按实际 PDF 和必要答案要点核定。
- V50-034 有可回答与资料不足标注冲突，V50-048 有 Yes／No 冲突。最终答题标签和分母在准备阶段核定。

### 9.3 论文与候选 PDF

| 编号 | 论文 | arXiv ID | 原始 qas 序号 | PDF 候选 |
|---|---|---|---|---|
| V01 | UTCNN: a Deep Learning Model of Stance Classificationon on Social Media Text | `1611.03599` | 1、2、3、4、6 | [候选 v1](https://arxiv.org/pdf/1611.03599v1) |
| V02 | Translation Artifacts in Cross-lingual Transfer Learning | `2004.04721` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/2004.04721v1) |
| V03 | Artificial Error Generation with Machine Translation and Syntactic Patterns | `1707.05236` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1707.05236v1) |
| V04 | Automatic Judgment Prediction via Legal Reading Comprehension | `1809.06537` | 1、2、4、5、6 | [候选 v1](https://arxiv.org/pdf/1809.06537v1) |
| V05 | Deep Learning the EEG Manifold for Phonological Categorization from Active Thoughts | `1904.04358` | 1、2、3、4、6 | [候选 v1](https://arxiv.org/pdf/1904.04358v1) |
| V06 | Open Event Extraction from Online Text using a Generative Adversarial Network | `1908.09246` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1908.09246v1) |
| V07 | VAIS ASR: Building a conversational speech recognition system using language model combination | `1910.05603` | 1、2、3、4 | [候选 v1](https://arxiv.org/pdf/1910.05603v1) |
| V08 | Knowledge Graph Representation with Jointly Structural and Textual Encoding | `1611.08661` | 1、2、3、4 | [候选 v1](https://arxiv.org/pdf/1611.08661v1) |
| V09 | Grammatical Error Correction and Style Transfer via Zero-shot Monolingual Translation | `1903.11283` | 1、2、3、4 | [候选 v1](https://arxiv.org/pdf/1903.11283v1) |
| V10 | Contextual Joint Factor Acoustic Embeddings | `1910.07601` | 1、2、3、4 | [候选 v1](https://arxiv.org/pdf/1910.07601v1) |
| V11 | Analysis of Wikipedia-based Corpora for Question Answering | `1801.02073` | 1、2、3、4 | [候选 v1](https://arxiv.org/pdf/1801.02073v1) |

qas 序号从 1 开始。v1 是待核对的候选版本，实际选用的 PDF 版本和本地解析配对在入库阶段确认。

### 9.4 五十道官方原题

从 `raw[arxiv_id]["qas"]` 按 question_id 精确取题，并核对原始序号。类型用于评测分组，完整参考取该条目的全部官方 answers。

| 编号 | 论文 | qas 序号 | 类型 | 官方原题 | question_id |
|---|---|---:|---|---|---|
| V50-001 | V01 | 1 | F | What topic is covered in the Chinese Facebook data? | `37a79be0148e1751ffb2daabe4c8ec6680036106` |
| V50-002 | V01 | 2 | F | How many layers does the UTCNN model have? | `518dae6f936882152c162058895db4eca815e649` |
| V50-003 | V01 | 3 | F | What topics are included in the debate data? | `e44a6bf67ce3fde0c6608b150030e44d87eb25e3` |
| V50-004 | V01 | 4 | R | What is the size of the Chinese data? | `6a31db1aca57a818f36bba9002561724655372a7` |
| V50-005 | V01 | 6 | M | What are the baselines? | `d3093062aebff475b4deab90815004051e802aa6` |
| V50-006 | V02 | 1 | M | What are examples of these artificats? | `73906462bd3415f23d6378590a5ba28709b17605` |
| V50-007 | V02 | 2 | F | What are the languages they use in their experiment? | `5bc1dc6ebcb88fd0310b21d2a74939e35a4c1a11` |
| V50-008 | V02 | 3 | M | Does the professional translation or the machine translation introduce the artifacts? | `88bf368491f9613767f696f84b4bb1f5a7d7cb48` |
| V50-009 | V02 | 4 | M | Do they recommend translating the premise and hypothesis together? | `0737954caf66f2b4c898b356d2a3c43748b9706b` |
| V50-010 | V02 | 5 | R | Is the improvement over state-of-the-art statistically significant? | `664b3eadc12c8dde309e8bbd59e9af961a433cde` |
| V50-011 | V03 | 1 | M | What was the baseline used? | `7b4992e2d26577246a16ac0d1efc995ab4695d24` |
| V50-012 | V03 | 2 | R | What are their results on both datasets? | `ab9b0bde6113ffef8eb1c39919d21e5913a05081` |
| V50-013 | V03 | 3 | M | What textual patterns are extracted? | `9a9d225f9ac35ed35ea02f554f6056af3b42471d` |
| V50-014 | V03 | 4 | F | Which annotated corpus did they use? | `ea56148a8356a1918bedcf0a99ae667c27792cfe` |
| V50-015 | V03 | 5 | F | Which languages are explored in this paper? | `cd32a38e0f33b137ab590e1677e8fb073724df7f` |
| V50-016 | V04 | 1 | R | what are their results on the constructed dataset? | `aa2948209cc33b071dbf294822e72bb136678345` |
| V50-017 | V04 | 2 | F | what evaluation metrics are reported? | `d9412dda3279729e95fcb35cbed09e61577a896e` |
| V50-018 | V04 | 4 | M | what are the state-of-the-art models? | `e3c9e4bc7bb93461856e1f4354f33010bc7d28d5` |
| V50-019 | V04 | 5 | R | what is the size of the real-world civil case dataset? | `06cc8fcafc0880cf69a2514bb7341642b9833041` |
| V50-020 | V04 | 6 | F | what datasets are used in the experiment? | `d650101712e36594bd77b45930a990402a455222` |
| V50-021 | V05 | 1 | M | How do they demonstrate that this type of EEG has discriminative information about the intended articulatory movements responsible for speech? | `7ae38f51243cb80b16a1df14872b72a1f8a2048f` |
| V50-022 | V05 | 2 | M | What are the five different binary classification tasks? | `deb89bca0925657e0f91ab5daca78b9e548de2bd` |
| V50-023 | V05 | 3 | M | How was the spatial aspect of the EEG signal computed? | `9c33b340aefbc1f15b6eb6fb3e23ee615ce5b570` |
| V50-024 | V05 | 4 | F | What data was presented to the subjects to elicit event-related responses? | `e6583c60b13b87fc37af75ffc975e7e316d4f4e0` |
| V50-025 | V05 | 6 | R | How many subjects does the EEG data come from? | `f9f59c171531c452bd2767dc332dc74cadee5120` |
| V50-026 | V06 | 1 | U | Do they report results only on English data? | `f3c204723da53c7c8ef4dc1018ffbee545e81056` |
| V50-027 | V06 | 2 | R | What baseline approaches does this approach out-perform? | `0602a974a879e6eae223cdf048410b5a0111665e` |
| V50-028 | V06 | 3 | F | What datasets are used? | `56b034c303983b2e276ed6518d6b080f7b8abe6a` |
| V50-029 | V06 | 4 | M | What alternative to Gibbs sampling is used? | `15e481e668114e4afe0c78eefb716ffe1646b494` |
| V50-030 | V06 | 5 | M | How does this model overcome the assumption that all words in a document are generated from a single event? | `3d7a982c718ea6bc7e770d8c5da564fbb9d11951` |
| V50-031 | V07 | 1 | U | What is the performance reported for the best models in the VLSP 2018 and VLSP 2019 challenges? | `ceb4bac1f6c506b5dab37607354530faee02ccac` |
| V50-032 | V07 | 2 | F | Is the model tested against any baseline? | `91bc8c0bc1634045177065536dd311f89134630b` |
| V50-033 | V07 | 3 | M | What is the language model combination technique used in the paper? | `fe1dcd6ef1f8618bbceee418f07cafe63a8efe08` |
| V50-034 | V07 | 4 | M | What are the deep learning architectures used in the task? | `53f74250948015c394e7b8438a2041fdeb330911` |
| V50-035 | V08 | 1 | U | How large are the textual descriptions of entities? | `2e37e681942e28b5b05639baaff4cd5129adb5fb` |
| V50-036 | V08 | 2 | M | What neural models are used to encode the text? | `b49598b05358117ab1471b8ebd0b042d2f04b2a4` |
| V50-037 | V08 | 3 | M | What baselines are used for comparison? | `932b39fd6c47c6a880621a62e6a978491d881d60` |
| V50-038 | V08 | 4 | F | What datasets are used to evaluate this paper? | `b36f867fcda5ad62c46d23513369337352aa01d2` |
| V50-039 | V09 | 1 | U | How do they measure style transfer success? | `a66a275a817f980c36e0b67d2e00bd823f63abf8` |
| V50-040 | V09 | 2 | F | Do they introduce errors in the data or does the data already contain them? | `b6f466e0fdcb310ecd212fd90396d9d13e0c0504` |
| V50-041 | V09 | 3 | R | What error types is their model more reliable for? | `62ea141d0fb342dfb97c69b49d1c978665b93b3c` |
| V50-042 | V09 | 4 | U | How does their parallel data differ in terms of style? | `a32c792a0cef03218bf66322245677fc2d5e5a31` |
| V50-043 | V10 | 1 | R | Which approach out of two proposed in the paper performed better in experiments? | `c6a0b9b5dabcefda0233320dd1548518a0ae758e` |
| V50-044 | V10 | 2 | M | What classification baselines are used for comparison? | `1e185a3b8cac1da939427b55bf1ba7e768c5dae4` |
| V50-045 | V10 | 3 | F | What TIMIT datasets are used for testing? | `26e2d4d0e482e6963a76760323b8e1c26b6eee91` |
| V50-046 | V10 | 4 | U | How does this approach compares to the state-of-the-art results on these tasks? | `b80a3fbeb49a8968e149955bdcf199556478eeff` |
| V50-047 | V11 | 1 | U | Can their indexing-based method be applied to create other QA datasets in other domains, and not just Wikipedia? | `c34e80fbbfda0f1786d3b00e06cef5ada78a3f3c` |
| V50-048 | V11 | 2 | M | Do they employ their indexing-based method to create a sample of a QA Wikipedia dataset? | `a9337636b52de375c852682a2561af2c1db5ec63` |
| V50-049 | V11 | 3 | R | How many question types do they find in the datasets analyzed? | `45a5961a4e1d1c22874c4918e5c98bd3c0a670b3` |
| V50-050 | V11 | 4 | M | How do they analyze contextual similaries across datasets? | `30e21f5bc1d2f80f422c56d62abca9cd3f2cd4a1` |

### 9.5 论文准备和评分冻结

1. 按 V01～V11 取得具体版本的原始 PDF。核对题名、原文段落、关键表图与官方标注对应关系。v1 不匹配时核定其他明确版本并记录依据。
2. 通过当前正式入口完成必要的解析、分块、文档 embedding 和入库。匹配且 ready 的资源可以直接复用。新论文的获取、解析和文档向量用量归入准备阶段，分别记录。
3. 对每题绑定本篇唯一的 `(local_paper_id, parse_revision)`。冻结实际 PDF 版本、索引 profile、原题和模型配置。业务入口使用本地论文 ID。证据映射只标注必要事实所在的 PDF 位置与现有原文块。解析确有缺失时，按证据覆盖缺口记录。
4. 阅读实际 PDF 和全部官方参考，冻结 `d7-new50-content-v1` 的每题必要要点、允许范围、条件、单位、同义表达及可答性。官方标签与实际 PDF 有差异时，在生成前记录裁定。确认题目、版本和评分依据后进入正式运行。
5. 在 `eval/qasper/d7-new50-v1/` 保存 `sample.json` 和 `papers.json`。评测侧保留参考答案、标签与人工证据位置。业务输入仅包含原题、选定论文及普通语言要求。

准备时重点核对下列边界。表中为待确认事项，实际裁定以固定 PDF 为依据。

| 题目 | 需确认的范围 |
|---|---|
| V50-007、008、010 | 区分完整语言集合与特定实验的语言子集。V50-008 是询问翻译来源的选择题，官方 Yes 无法直接给出所问来源。V50-010 核对显著性的实验和比较对象 |
| V50-012、019、020 | 表中结果应带数据集及指标。案件总数与具体实验划分分别核对，保留可接受的规模口径 |
| V50-021、023、025 | 区分 t-SNE 图所支持的观察、EEG 处理网络结构和受试者数量 |
| V50-026、031、035、039、042、046、047 | 核对实际 PDF 是否提供所问信息。实验涉及的语言、作者系统与挑战赛最佳系统、实体描述规模、风格迁移评价等各按原问范围判断 |
| V50-032、034、045 | 区分官方 No 与资料不足。V50-034 的 DNN 描述与详细架构范围按正文核对。V50-045 需要区分总体测试集和具体实验分块 |
| V50-048、050 | 核定论文是否实际用索引方法构造了示例数据集，处理 Yes／No 冲突。上下文相似性分析按原文列出的比较维度判定 |

有多个合理范围时，在冻结时为两组写明同一接受规则。确实无法裁定的题标记为评分争议，保留原题及提交状态。评分标准在本批输出生成前冻结。

### 9.6 两组配置与调用数量

| 项目 | 固定 RAG | 当前 Agent |
|---|---|---|
| 正式入口 | `d9_runtime.run_question(..., mode="fixed_rag")` | `d9_runtime.run_question(..., mode="agent")` |
| 问答流程 | 正常前置理解、一次混合检索、既有父块补读、生成和必要纠错 | 正常前置理解、当前模型／工具循环、按需搜索与读取、D7 正文验收 |
| 容量 | 当前 library fixed 的 `full_request` | 当前 Agent 的 `full_request` |
| 时间策略 | 库模式固定 RAG 的既有 policy，记录实际单次请求和整题设置 | D7 整题预算 120 秒，剩余 20 秒进入收尾，实际采用当前 `deadline_enforcement` |
| 轮数 | 固定流程 | `max_iterations=120` |
| 共同输入 | `library_mode=True`、`top_k=5`、`max_chars=8000`、本题唯一论文配对、空历史 | 相同 |
| 语言要求 | `answer_instructions="Please answer in English."` | 相同 |

执行前离线记录生成模型、temperature、输出上限、实际模型容量、embedding／rerank 模型、索引 profile、提示与运行策略版本。以当前 `deepseek-flash`、temperature 0.2、输出 4096、`qwen3.7-text-embedding` 和 `qwen3-rerank` 为起点，两组使用相同的模型与检索组件。本批从冻结配置到完成保持同一版本，固定 RAG 和 Agent 保留各自的现有时间与调用策略。对照结果按两条完整流程解释。

按 V50 编号升序逐题串行，奇数题先固定 RAG，偶数题先 Agent。同题相邻执行，两组分别建立新 conversation_id 和 submission_id。共享论文索引，各自进行正常问答与取证。

**50 道题 × 2 组 × 每组每题 1 次，共 100 次正式问答提交。** 范围包含流程所需的前置理解、生成、查询 embedding、rerank、工具调用与现有策略内重试或修复。论文准备成本另计。本批真实问答额度为每题每组一次。

### 9.7 服务状态与中断处理

正式开跑前读取 [DeepSeek 公共状态页](https://status.deepseek.com/) 和相关历史事件，记录核对时间、Flash API 状态及相关事故窗口。以已配置的服务与模型对应关系为准。状态核对通过公共记录和已有运行信息完成，正式的首条真实模型请求属于 100 次问答之一。

- 公告中存在影响本批模型的进行中事故时，延后开跑。运行中收到相关事故公告、终态 HTTP 503，或确认共享服务不可用时，暂停两组的新提交，保存原生结果与用量并核对服务状态。
- 相关服务恢复后按固定顺序续跑未尝试的提交。经历暂停的配对记录实际两组执行时间。官方受影响窗口与任一组运行重合，或配对跨越一次已确认的中断暂停时，将该对单列为环境受扰。
- 每个提交保留最初尝试、既有策略内重试、最终返回和用量。单题的预算耗尽、输出无效或来源异常保留具体终态。上游 HTTP 错误、断连和读取超时分别记录。外部事故归因以实际状态、原始错误和时间窗口为依据。
- 批次完成后核对相关服务历史记录，补记延迟公布的事故窗口。受扰标记只依据冻结规则和日志，独立于题目得分。

最终记录覆盖 50 题的 100 个计划位置，明确尝试、交付、失败、环境受扰和未执行。正式内容对照缺项时报告实际分母，保留当次完整记录。需另行恢复受扰配对时，以双方同题为单位安排单独复测批次。

### 9.8 交付、内容与成本的评价

先核对交付，再按生成前冻结的 rubric 对真实正文做同一口径盲评。使用本地已有答案、PDF 与原文证据直接核对。记录以下三个层次。

| 层次 | 判定与统计 |
|---|---|
| **实际交付** | 按每组计划 50 题记录尝试、可交付答案、受控超时、无效输出、其他失败和未执行。HTTP 200、`stop`、`answered` 与实际正文分开核对。明显残片单列交付异常，合理的有限回答或资料不足说明可以进入内容评价 |
| **同题内容对照** | 主对照采用两组都正常交付、都可评价且属于正常服务范围的同一题交集。报告实际配对数、完整／部分正确／未通过及配对四格。任一侧缺测或环境受扰时，该题两组一同移出主配对分母，并保留排除原因和已取得的答案 |
| **计划规模下的结果** | 另列每组完整且正常交付题数／50、完整或部分正确且正常交付题数／50，以及缺测与失败数。该口径反映实际流程交付与内容的共同表现，和条件化的同题内容比较分别展示 |

内容评分须覆盖必要事实、条件、范围、单位及证据支持。真实但错误的回答、可答题的错误拒答、已读原文仍漏关键要点，按内容评价处理。引用定位通过和关键结论获得支持分别记录。附加无据事实与数值矛盾也单列。判分规则保持双向一致，并保留生成前确认的同义范围。

用量按服务分别汇总 Chat、query embedding、rerank 请求和已知 tokens，包含失败与策略内重试。以逐题 `known_total_tokens` 保留用量不完整任务的已知部分。记录每题耗时中位数、均值及最大值，以及 Agent 的搜索、阅读、计算、修复和收尾。论文准备与问答成本分别列出。

报告先给 50 题主表和实际有效配对分母，再用原生证据解释分歧题，区分首轮定位、实际送入模型的原文、Agent 新增阅读、生成漏答和交付故障。D6 与 D7 历史结果可在背景中并列。本批结论对应已冻结的版本、单篇单轮题集和实际服务条件。

### 9.9 产物、必要验证与执行状态

阶段 A 产生 `eval/qasper/d7-new50-v1/sample.json` 和 `papers.json`。阶段 B、C 使用 `artifacts/v3/d7-qa-paired-new50-20261105/input.json`、`results.json` 及现有盲评结构，引用正常生成的原生 JSON／Markdown。保存原始终态后再提取评分、环境标签和用量。

优先复用现有论文入库、正式问答入口及已用的批次记录方式。确需修改评测编排时，只针对实际改动选择 1～3 个现有离线方法。已有通过结果可以复用。本批实际完成了 50 道原题、11 篇 v1 论文入库、50 题绑定和 100 次正式问答；执行结果如下。

实际执行后在本节回填论文版本、最终题型与标签、服务窗口、计划与交付数、同题配对结果、分歧案例和用量。原生记录与历史成绩保留各自批次。

#### 9.9.1 实际论文版本与配比

11 篇均使用候选 v1 PDF，题名、正文与关键表图核对后走正式入库流程；没有图片题，也没有换用其他版本。实际绑定如下（chunks 为当前 parse_revision 的分块数）。

| arXiv | PDF | local_paper_id | parse_revision | chunks | pages |
|---|---|---|---|---:|---:|
| 1611.03599 | v1 | `local_8c399b45711c4e5596ce6da888bc32d5` | `r_bf1e4f792caca9c4` | 40 | 11 |
| 2004.04721 | v1 | `local_f7311efd38284053bbb64a63b309536f` | `r_493843bb09f1058a` | 58 | 11 |
| 1707.05236 | v1 | `local_23090aede61842d5bd60252bc5f28fcd` | `r_97201b87f308f5b0` | 19 | 6 |
| 1809.06537 | v1 | `local_81aacbe9528c4bbb81c48a24c837dd0c` | `r_e5096b3f4fa354e2` | 38 | 10 |
| 1904.04358 | v1 | `local_0bf2d3025f44405c92ed2edbf8b74a7a` | `r_4ec6ea2f63daedd5` | 24 | 5 |
| 1908.09246 | v1 | `local_e32087e9068948bab1e969ff4f01acdc` | `r_c8b53ca2bce576dd` | 43 | 10 |
| 1910.05603 | v1 | `local_8e23aa91b0e04c3594bae7489b565746` | `r_304cf532d70fad44` | 20 | 3 |
| 1611.08661 | v1 | `local_6d102cd5b45f4346b578f1c0157cf162` | `r_d39f0f3242652520` | 38 | 8 |
| 1903.11283 | v1 | `local_c36148f80bcc4cfd87777c82e3468322` | `r_e8fab0e5e4098d5f` | 45 | 11 |
| 1910.07601 | v1 | `local_d6c193649afc44cdbca480c900aaaa36` | `r_00c5d4657632e373` | 30 | 8 |
| 1801.02073 | v1 | `local_dd10ee7083024b03a5ad5a543348bd32` | `r_f97dfdd0edfc280c` | 24 | 5 |

最终配比为 F14/M20/R10/U6（初选 F14/M19/R10/U7）。V50-039 依 PDF 从官方 U 改判 M；V50-034 的可答性冲突和 V50-048 的 Yes/No 冲突已按原文裁定。最终可答 44 题、不可答 6 题（V50-026/031/035/042/046/047），有正向证据 43 题。`sample.json` 与 `papers.json` 的绑定、`d7-new50-content-v1` 均在生成前冻结；Gold、评分与人工证据位置未进入模型输入。

#### 9.9.2 服务窗口与完成度

- 批次窗口：2026-11-05 15:23:45–15:55:09（Asia/Shanghai），wall 1884.055 s。
- 开跑前 15:20 核对 `status.deepseek.com/history.atom`：无进行中事故；最近一条为 11-03 18:48:02 已解决的网页/API 部分中断。跑后 16:00:28 复核，事故列表未更新，无新增窗口。
- 100 个计划位置全部尝试且全部完成：fixed_rag 50/50、agent 50/50；失败 0、未执行 0、交付异常 0。100 条终态均为 `answered`，无 HTTP 503/其他 HTTP 错误，无网络重试、无引用修复；没有暂停或环境受扰配对。
- finish_reason：`stop` 200 次、`tool_calls` 55 次；agent 50 条最终正文检查均为 `valid`，fixed_rag 50 条均为 `fixed_citations_valid`。100 条正文均为非空、未截断的正常交付。
- 实际配置：`deepseek`/`deepseek-flash`，temperature 0.2，max_tokens 4096，context 1,048,576；embedding `qwen3.7-text-embedding`（1024 维、cosine，profile `ep_cbf0f6caa97b962a`，collection `paper_chunks_ep_cbf0f6caa97b962a`），rerank `qwen3-rerank`；两组 `library_mode=True`、`top_k=5`、`max_chars=8000`、空历史、英文作答指令。fixed_rag 走 full_request（`input_budget_tokens=1017118`，无整题 wall timeout，按单请求 timeout）；agent 使用 `shared_question_deadline_with_httpx_timeouts`（120 秒整题、20 秒收尾）和 `max_iterations=120`。

#### 9.9.3 同题配对内容结果

先交付核对，再统一盲评并解盲。主配对只取两组都正常交付且可评价的题；本批 **有效配对 49 题**。V50-009（“是否推荐把 premise 和 hypothesis 放在一起翻译”）的官方答案为 No，但 PDF 第 9 页明确建议“if translating from English, doing so at the document level”，即支持一起/文档级翻译；该冲突在生成前未识别，评分阶段不能再改冻结 rubric，故两组合同题移出主表，保留原答案并单列原因。

| fixed_rag \ agent | 完整 | 部分 | 未通过 |
|---|---:|---:|---:|
| 完整 | 38 | 0 | 1 |
| 部分 | 1 | 2 | 0 |
| 未通过 | 5 | 0 | 2 |

- 两组同题完整：38/49（77.6%）；两组同题部分：2/49；不一致 7 对。
- fixed_rag：完整 39/49（79.6%），完整或部分 42/49（85.7%）。
- agent：完整 44/49（89.8%），完整或部分 46/49（93.9%）。
- 按计划 50 题口径：fixed_rag 完整且正常交付 39/50、完整或部分且正常交付 42/50；agent 分别为 44/50、46/50。每组另有 1 题（V50-009）为评分争议，不计入上述完整/部分/未通过。
- 内容未通过共 10 条：错误拒答 7 条（V50-002 两组、V50-010 fixed、V50-015 fixed、V50-018 fixed、V50-032 fixed、V50-050 fixed）；另 3 条为 V50-010 agent（以无显著性检验作答）、V50-026 agent（无据断言仅英语）、V50-040 fixed（误称数据自带错误）。另有 5 条部分正确但漏关键要点（V50-006 fixed 漏否定词；V50-007 两组漏语言名；V50-023 两组漏四层 2D CNN）。
- 引用：742 次引用、167 个唯一 chunk，全部可解析到当前论文版本，缺失 0；按答案支持度粗分为支持 83、部分支持 5、不支撑 10、不适用 2。10 条未通过答案另列额外/无据主张，5 条部分答案单列漏项。

#### 9.9.4 分歧案例

- **agent 独有完整 6 题**：V50-006、V50-015、V50-018、V50-032、V50-040、V50-050。V50-015/018/032/040/050 的 fixed_rag 均在一次取证后给出错误拒答或错误断言；agent 各用 2 次工具（1 次 search、1 次 read_context）补读到 English learner writing、对比模型表、baseline 说明、introduced errors、Table 1 overlap 指标后作答。V50-006 fixed_rag 只举 lexical overlap，漏 negation-word artifact；agent 补读后给出两类。
- **fixed_rag 独有完整 1 题**：V50-026。fixed_rag 依据 FSD/Twitter/Google 三数据集回答“并非仅英语”；agent 反而无据断言 all English，属内容过度推断，不是交付问题。
- **两组都未通过 2 题**：V50-002（UTCNN 八层；两组都称无法确定，agent 4 次工具仍未从图 2/架构描述得到 eight layers）与 V50-010（两组都称没有显著性检验；论文报告 5 seeds 均值与标准差但未给 p 值，按冻结 rubric 的 Yes 判未通过）。
- **两组都部分 2 题**：V50-007（只给 15/10/6 语言数，未列语言名）与 V50-023（解释 covariance matrix，但漏 four-layered 2D CNN）。
- **评分争议 1 题**：V50-009，见上；这是本批唯一被移出主配对的题。

#### 9.9.5 用量与成本

| 项目 | fixed_rag | agent |
|---|---:|---:|
| Chat 请求 | 100 | 155 |
| Chat prompt / completion tokens | 643,116 / 23,406 | 1,055,836 / 39,973 |
| Chat known_total_tokens | 666,522 | 1,095,809 |
| query embedding 请求 / tokens | 50 / 1,341 | 36 / 942 |
| rerank 请求 / tokens | 50 / 352,474 | 36 / 238,460 |
| 工具调用 | 0 | 118（search 36、read_context 82） |
| 逐题耗时中位数 / 均值 / 最大（s） | 18.438 / 17.920 / 27.922 | 20.445 / 19.362 / 26.891 |
| 逐题耗时合计（s） | 895.987 | 968.124 |

- 合计 Chat 255 次请求、1,762,331 known tokens；embedding 86 次、2,283 tokens；rerank 86 次、590,934 tokens；wall 1884.055 s，逐题合计 1864.111 s，编排开销约 19.944 s。
- Agent 50 题均有工具轨迹：1 次 1 题、2 次 41 题、3 次 1 题、4 次 6 题、8 次 1 题，均值 2.36，最大 8；无工具错误。所有 `known_total_tokens` 完整，无未知 Chat 用量。
- 准备成本另列，不并入上表：11 篇 PDF 入库，41 次文档 embedding、98,721 tokens、入库 630.201 s；11 次 MinerU 解析，MinerU token 用量未提供，保持未知。
- 未取得单价，不能给出货币金额；以上为可计量的请求、token 与耗时。

#### 9.9.6 产物与验证

- 输入与结果：[`input.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/input.json)、[`results.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/results.json)；逐题原生记录在 [`native_reports/`](../../artifacts/v3/d7-qa-paired-new50-20261105/native_reports/)，History 仍在 `archive/run_logs/d9/`。
- 盲评链：[`blind_review.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/blind_review.json)、[`blind_map.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/blind_map.json)、[`judgments.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/judgments.json)、[`unblinded_scores.json`](../../artifacts/v3/d7-qa-paired-new50-20261105/unblinded_scores.json)。
- 验证：100 条任务、100 个唯一 `submission_id`/`conversation_id`；题目升序、同题相邻、奇数 fixed_rag 先/偶数 agent 先；100 条原生记录齐全。未修改 D9 运行时、检索/引用契约或其他问答入口；本次只有评测编排与文档产物，没有跑测试套件（无源码行为改动）。D6 旧分数和 D7 两题回归仍按各自批次保留，未混入本批主表。

## 10. 给 DeepSeek 的新 50 题执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守当前 AGENTS.md。执行 docs/v3/d7-plan.md 第9节的新50题对照，最后回填第9.9节的实际结果。第1～8节是已完成的两题回归及历史提示词。

本批目标是比较完整请求容量的库模式固定RAG与完成D7正文验收和时间预算调整的当前Agent。冻结版本和评分后，两组各运行同一批50道新官方原题一次，共100次正式问答。按实际流程质量、交付和成本评价。

阶段A准备与冻结
1. 按第9.3～9.4节的arxiv_id、原始qas序号和question_id，从eval/qasper/raw/qasper-dev-v0.3.json精确读取V50-001～050的原始question和全部官方answers，保留原始文字。初选F14/M19/R10/U7，最终配比按PDF裁定。
2. 对V01～V11核对具体版本的原PDF，先检查候选v1的题名、正文和关键表图。确认实际版本后走当前正式入库流程。已有匹配且ready的资源直接复用。新论文必要的解析、分块和文档embedding成本单列。
3. 每题绑定唯一的local_paper_id与parse_revision，与papers中的实际配对核对。保存eval/qasper/d7-new50-v1/sample.json与papers.json。准备好11篇版本和50题绑定后冻结运行输入。
4. 在生成前按实际PDF和全部参考冻结d7-new50-content-v1，核定必要要点、单位、比较基准、允许的语义等价范围和最终可答性。重点看第9.5节的争议，尤其V50-034的可答性、V50-048的Yes/No冲突以及7道官方资料不足题。不可消除的争议在生成前标记。Gold、正确数值和人工证据位置留在评测侧。

阶段B运行
1. 正式运行前用公共状态页核对所用DeepSeek API服务，并记录实际时间及相关事故窗口。公共状态核对走只读页面。处于影响本批的事故时延后开跑，运行中收到相关事故公告、终态HTTP 503或确认共享服务不可用时暂停双方，保存当前结果。恢复后按原顺序续跑未尝试的提交。
2. 调用正式d9_runtime.run_question。query用官方原题，selected_versions只含本题完整本地配对。两组library_mode=True、top_k=5、max_chars=8000、conversation_history=[]、answer_instructions="Please answer in English."。固定RAG使用当前library full_request，Agent使用D7正文验收、120秒预算、20秒收尾和max_iterations=120。分别记录两条正式路径实际policy和deadline_enforcement。
3. 两组使用相同实际生成模型、temperature、输出上限和模型上下文设置，相同embedding/rerank与索引profile。执行前离线记录这些值与runtime、prompt、容量和交付策略版本，在本批内固定。
4. V50升序逐题串行，奇数题fixed_rag先、偶数题agent先。每个mode独立新conversation_id和submission_id。同题相邻执行，各自完成正常前置理解与取证。100次问答包括流程内的聊天、query embedding、rerank、现有重试和修复。每个计划位置只提交一次。
5. 提交前记录attempted与实际输入。返回即先保存原生结果和历史路径，再抽统计。记录每次起止时间、实际终态、HTTP错误、finish_reason、异常正文、重试、用量和共享事故。官方故障窗口重合或配对跨越已确认中断时按第9.7节标记环境受扰。批次后复核服务历史。发生失败时记录已尝试和未执行，按本批调用范围继续。
6. 复用既有批次与正式入口。确需调整评测脚本时，仅验证实际改动涉及的1～3个现有离线方法。离线阶段使用已有记录和假客户端。已有工程验证按代码版本复用。

阶段C评分与汇报
先核对实际正文交付，再统一盲评并解盲。用冻结rubric、PDF及实际原文评价完整/部分正确/未通过、引用支持和附加错误。可答题的错误拒答属于内容问题，明显空正文、半截输出和失败终态单列交付问题。
主配对内容表只用两组都正常交付、可评价、处于正常服务范围的同一题交集。报告有效配对数和剔除原因，任何一侧缺测时两组同题一起移出这个分母。另列每组计划50、尝试、失败、未执行、完整且交付/50、完整或部分且交付/50。把环境受扰标签和内容评分分开保留。
汇总Chat、embedding、rerank实际请求和已知tokens、耗时及工具轨迹。失败、重试和未知用量按实际记录处理。使用known_total_tokens汇总已知部分，准备成本另列。用已有轨迹解释分歧，区分定位、实际原文、Agent补读、漏答与交付故障。
保存artifacts/v3/d7-qa-paired-new50-<实际执行日>/input.json与results.json，沿用现有盲评与原生报告结构。回填D7第9.9节实际论文版本、配比、服务窗口、运行完成度、配对成绩、案例和成本。新题主表只使用本批，D6旧分数和D7两题回归保留为历史证据。
```
