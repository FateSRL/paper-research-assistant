# D1：当前 Agent 的十题完整流程开发观察

安排日期：2026-10-26（Asia/Shanghai）。状态：待执行，0/10。本轮只建立 v3 文档与本安排，不发真实请求。总架构及遗留问题见 [v3 总规划](plan.md)，上一批结果见 [v2／2.17 第 9 节](../v2/2.17-ragflow-agent-original-history-plan.md#9-实施结果2026-10-26)。

## 1. 本阶段目的

2.17 已证明固定原文可以通过成功准备的消息历史传到最终生成，也观察到最终补足准备遗漏；该题核心答案此前已覆盖，新机制增加了输入成本，并出现有据但不必要的背景扩写。本阶段保留该实现，先用十题完整 Agent 流程扩大观察，再决定是否需要局部修正。

本批要观察的是检索、阅读、准备、最终表达与引用的完整衔接，以及原问覆盖、事实忠实性和实际成本。它是已有开发案例的当前版本观察，不是新的留出验收，不用十题通过率声称一般准确率，不比较固定 RAG 或提前编译知识路径。

## 2. 运行条件与范围

- 实际调用页面对应入口 `d9_runtime.run_question(..., mode="agent", library_mode=True)`，保留前置理解与规划、模型自主选择工具、临时事实准备、原文历史重放、最终生成与现有引用发布。
- 运行前在普通 `input.json` 中确定下方十题顺序、问题原文、版本配对及实际公开配置。沿用当前聊天模型、embedding、rerank、temperature、输出上限、超时及修复／重试策略；不在批次中换模型、改提示或切论文版本。
- 当前交互条件沿用 DeepSeek 配置、temperature 0.2、输出上限 4096、单次超时 30 秒，网络重试与共享修复各最多一次；五次自主决策、五次共用 search／read_context 和 8192 token 证据窗口保持。具体模型名、索引配置与真实用量写入既有记录。
- 输出使用普通完整回答与原有引用要求，按问题语言作答；不要求 QA 最短答案、固定 Yes／No／Unanswerable 字段或 `direct_answer`，不运行 Answer F1／Evidence F1 或评委模型。
- 每题只运行一个逻辑问答；自然产生的多次聊天、查询 embedding、重排及受限重试／修复属于该题实际成本。十题不等于十次模型请求。
- 复用下列已有论文版本，由现有入口正常确认 ready。若不可用，记录具体缺项并暂停相关题，不自动下载、重新解析、入库、重建向量或悄悄换版。

### 2.1 论文版本配对

| 代号 | 论文 | paper_id | parse_revision | 绑定依据 |
|---|---|---|---|---|
| M | MonaLog | `local_5da940b5dc2a4dff8a7b5358de12b728` | `r_ffe2ec817e72a72e` | 2.17 实际固定证据运行使用的 MinerU API 版本 |
| N | Location-Relative Attention Mechanisms For Robust Long-Form Speech Synthesis | `local_2cc8d921ea84427fa519dae6f1c39b8e` | `r_2e39e24cc58dc759` | 既有 question-intent-three ready 绑定 |
| A | Shallow Discourse Annotation for Chinese TED Talks | `local_903ae31ca7a448f382affa3b1274bc7e` | `r_d10f45f1749c1be9` | 同上 |
| D | Dynamic Memory Networks for Visual and Textual Question Answering | `local_e1d98edb937e40be9c967348d0c734b9` | `r_d7354c46c4404390` | 既有 answer-focus／fresh-five 题目绑定 |
| C | A neural network system for transformation of regional cuisine style | `local_de839747a9344083b2f8d3ab154bf9f9` | `r_e35b37ccaac0c60a` | 同上 |

现有 [QASPER 三题 papers.json](../../eval/qasper/question-intent-three-20261025/papers.json)中的 MonaLog 仍是较早版本，不能直接照表覆盖 M 的新绑定；本批明确使用 2.17 的 `r_ffe2ec817e72a72e`。其他输入仍按上表配对，不能只传 paper_id 让程序自行猜版本。

## 3. 十题与执行顺序

D1-01 至 D1-09 各使用独立新会话；D1-10 复用 D1-09 的会话与本批实际产生的回答历史。以下“观察重点”只用于事后阅读结果，不进入模型问题、取证参数或提示。

| 编号 | 版本代号 | 输入问题（按此原文运行） | 来源／观察重点 |
|---|---|---|---|
| D1-01 | M | How do they select monotonicity facts? | QASPER `45893f31ef07f0cca5783bd39c4e60630d6b93b3`；完整取证下的来源、条件、符号与原文传递 |
| D1-02 | N | How they compare varioius mechanisms in terms of naturalness? | QASPER `e4024db40f4b8c1ce593f53b28718e52d5007cd2`，保留原题拼写；方法／条件及结论强度 |
| D1-03 | A | Which inter-annotator metric do they use? | QASPER `269b05b74d5215b09c16e95a91ae50caedd9e2aa`；并列指标覆盖及术语 |
| D1-04 | D | 根据表1，ODMN和DMN+在bAbI-10k的平均错误率及DAQUAR-ALL的准确率各是多少？从ODMN到DMN+，两项分别变化多少个百分点？ | fresh-five 的 s7；表格归属、数值与指标方向 |
| D1-05 | C | 这篇菜谱转换论文中，地域风格识别与食材替换分别采用什么输入表示和模型？扩展 word2vec 用于哪个阶段？ | answer-focus 的 s6；方法阶段和主体归属 |
| D1-06 | C | 论文讨论部分指出，系统在食材组合与风味化合物方面存在什么局限？西方菜谱和东亚菜谱在搭配上有什么相反倾向，这可能怎样影响研究结果？ | answer-focus 的 s3；跨页续文、限定和附加解释 |
| D1-07 | D＋C | 比较《Dynamic Memory Networks for Visual and Textual Question Answering》的 DMN+ 文本输入模块与《A neural network system for transformation of regional cuisine style》的配料 word2vec：二者怎样组织上下文，是否保留输入的顺序信息，为什么采取这样的设计？ | answer-focus 的 s4；双论文证据和设计解释 |
| D1-08 | D | DMN+在VQA test-std上的All准确率，其95%置信区间上下界分别是多少？ | fresh-five 的 s11；必要事实缺失时的取证与缺口表达 |
| D1-09 | C | 菜谱转换论文为什么不直接选择“让目标国家分类概率最高”的替换食材？它提出的扩展word2vec替换方法如何选择候选食材？ | fresh-five 的 s9；原问约束、候选选择与机制依据，同时作为下一题的前序会话 |
| D1-10 | C，与 D1-09 同会话 | 请把刚才的解释说得更容易理解一些，仍然围绕候选食材是怎么选择的。 | 本批追问；使用真实上轮历史，观察指代、简化表达及范围保留 |

题目来源：[QASPER 三题 sample](../../eval/qasper/question-intent-three-20261025/sample.json)、[answer-focus questions](../../artifacts/v2/comparison/answer-focus-stage-context-20261024/questions.json)、[fresh-five questions](../../artifacts/v2/comparison/fresh-five-question-quality-20261024/questions.json)。这些文件可能包含参考字段；运行输入只取问题和本节明确的版本，参考答案、证据标注、正确页码／chunk 和历史评价仅用于事后比较，不整体传给模型。

D1-01 是完整自主取证下的同题观察，不是重跑 2.17 固定证据两阶段实验；后者只作已有对照，不追加一次相同固定运行。D1-10 不额外生成“前序回答”，也不使用旧参考答案伪造会话：通过现有 `select_conversation_history` 组织 D1-09 的真实报告。若 D1-09 没有产生可用历史，D1-10 记为未执行，不以独立首问或虚构历史替代。

## 4. 执行方法与记录

优先直接复用当前 runtime 和已有 JSON／Markdown 保存。现成双模式 comparison runner 会运行固定 RAG，QASPER runner 会附加短答规则和评分，因此不能原样启动它们再删除不需要的结果；本批只执行上表的 Agent 运行。

若需要顺序编排脚本，只增加调度这十题和连接第 9／10 题所必需的窄入口，调用现有 runtime、会话历史整理和保存函数，不建设通用回放／评测框架，不改变生产流程或增加测试层。

建议批次目录：`artifacts/v3/d1-agent-ten-20261026/`；已存在时使用新后缀，不覆盖旧结果。正常逐题日志继续由 `save_agent_run` 保存到既有 `archive/run_logs/d9/`，批次使用普通输入和结果索引链接到这些记录：

- `input.json`：十题、顺序、版本、会话关系、实际公开配置与普通完整回答要求，不含 gold 或诊断提示。
- `results.json`：已尝试／完成／未执行的题目及原因、运行记录路径、实际用量和简短内容评价。无额外哈希、manifest 或证据快照。
- 逐题原生 JSON／Markdown：保留实际前置理解、工具调用和观察、准备、最终请求、原始响应、引用、失败和账本，不另抄一套相同日志或生成独立审计报告。

代码和已有测试未变时，复用 2.17 已通过的两个指定离线结果，不先重跑全目录、全量回归或同一组测试。本批不修改模型提示、解析器、索引、来源映射、UI 或其他模式，不发索引 embedding、解析、入库或评委请求。

## 5. 评价口径

以本轮完整回答及其实际获得的原文判断，每题在现有结果中记录：

1. 核心所问是否回答完整，必要并列项、关系、适用条件和模态是否保留；正确但不必要的背景另记聚焦问题，不因篇幅长直接判事实错误。
2. 主体／方法阶段／论文归属、公式、数值及结论强度是否受到原文支持；引用可定位与语义支持分开判断。
3. 缺少事实时是否明确当前证据边界，是否无据推断“不存在”；追问是否正确继承本轮对象和要求，旧回答没有变成新证据。
4. 实际经历哪些搜索／阅读、是否触发不足后补证、哪些材料最终可见；未自然出现的分支记为未覆盖，不用强制动作凑覆盖率。
5. 前置理解、取证、准备、最终及修复／重试的真实请求、token 和耗时；2.17 固定证据耗时不与本批完整 Agent 直接相减后声称提速或退化。

内容可记为通过、部分通过或失败，运行失败单独记录。说明评价为 AI 辅助原文对照，不冒充独立人工准确率；准备数量、引用数量、发布成功或词面 F1 不单独决定内容结论。缓存差异及输入长度会影响成本，token 不直接按同一比例换算费用。

## 6. 错误处理与停止条件

- 逐题一次，保存全部实际输出；不为获得更好答案重新生成，不边跑边改提示后把不同版本混成同一批。
- 内容错误先记录，十题结束后按解析、检索、展示、准备或最终表达定位，再决定局部修复。后续修复独立记录，只复测失败题及有证据受影响的题，不默认整批重跑。
- 出现索引不可用、模型配置错误、原文历史缺失等影响后续执行的运行故障时暂停排障，记录已发生调用；未完成题保持未执行，不虚报零成本或自动重开整个批次。
- 完成上表十题及已有结果的简要评价后结束；若中途故障或第 9／10 题依赖无法满足，则保留实际完成数／10 和原因。任务完成不要求调到 10/10 内容通过。

完成后在本文追加本批实际状态、结果路径、主要失败类型与成本，更新 [总规划](plan.md)中的 D1 状态和对应遗留项。不要另建验证报告、哈希、审计、检查清单或额外模型审核流程。

## 7. 给 DeepSeek 的执行提示词

以下是后续执行 D1 时使用的普通文本，不依赖任何插件。本轮文档整理不执行这些调用。

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/plan.md 和 docs/v3/d1-plan.md，按 D1 安排执行本次十题完整 Agent 开发观察。本次执行包含表中十个逻辑问答及其正常聊天、查询embedding、重排与原有受限重试/修复，不包含其他真实调用。只运行mode="agent", library_mode=True，不运行fixed_rag、固定证据两阶段实验或评委。

按D1表格原文和明确版本顺序执行；MonaLog使用2.17的r_ffe2ec817e72a72e，不能从旧QASPER绑定换回旧版。第1至9题独立会话，第10题只承接本批第9题真实产生的历史，复用select_conversation_history，不额外生成前序或伪造历史。第9题没有可用历史则第10题保留未执行。参考答案、页码/chunk标注和文档观察重点不进入模型输入。沿用当前模型、提示、配置和额度，输出普通完整回答与引用，不附加QA最短答案、direct_answer或F1要求。

优先复用d9_runtime.run_question及正常保存；需要编排时只补顺序执行和追问衔接的窄入口，不重建runner或改生产逻辑。运行前用普通input.json确定本批题目、版本和配置，不生成哈希或manifest。已有测试代码未变时直接复用2.17两个指定方法的通过结果，不重复跑测试，不做全量回归。不下载、解析、入库、重建索引、改映射或补其他题。

每题只运行一次，保留完整请求、取证、准备、最终、引用、失败与实际用量。内容错误不立即改提示重跑；运行故障影响后续时暂停并记录已尝试范围。保存到artifacts/v3/d1-agent-ten-20261026/或新的后缀目录，引用现有正常JSON/Markdown日志，在results.json中简要评价覆盖、忠实性、引用支持、聚焦、追问和成本。评价注明AI辅助原文对照，不称独立人工准确率。

十题结束或明确故障停止后，更新D1与v3总规划的实际状态、结果路径和必要问题结论。不要新增哈希、正文指纹、证据快照、审计、校验清单、独立验证报告、语义校验器、审核模型或无关重构；不因内容低分补跑或为了覆盖分支强迫工具动作。
```
