# D3：补齐表格定位入口与 Q15 单题复测

制定日期：2026-10-28（Asia/Shanghai）。状态：**已完成**表格阅读目录入口、Q15 单题复测、Q21～Q30、计算工具／自然语言最终回答、Q23／Q25／Q29 复测，以及 Q31～Q40 新十题；实现与结果见第 7.1、10、13、16、17.7 节。D2 历史计划与结果保留。

本阶段承接 [D2 两处修正及三题复测](d2-plan.md#1571-实际实施与结果2026-10-27)。只补齐已入库表格的定位入口，复用现有 `read_context`，完成相关离线验证后真实复测 Q15 一次。D2 历史计划与结果保留，不再向 D2 追加本阶段任务。

遵守 [AGENTS.md](../../AGENTS.md) 和 [Stop That Shit](C:/Users/ggy/.codex/plugins/cache/stop-that-shit/stop-that-shit/0.2.4/skills/stop-that-shit/SKILL.md)：只处理已有证据支持的具体缺口，不增加无用校验、哈希、审计或无关重构。

## 1. 本阶段目的与顺序

执行顺序：**补齐表格目录 → 两个指定离线方法 → Q15 各阶段完整运行一次 → 记录结果后结束。**

本次不继续修改探索／准备的充分性规则。D2 的 Q12、Q13 已通过；Q15 的正文也确实支持召回率和相对表现等部分答案，不能只凭“没读表格”判为无据回答。本次先解决可以直接定位的材料入口缺口，再评价主要性能数值是否补齐。

不新建公式阅读器。现有公式能够作为正文类父块的内容保留，本次不把表格目录的问题类推成公式全部不可读，也不迁移 RAGFlow 的整个检索框架。

## 2. 已确认的事实与修正边界

| 已有事实 | 证据 | 本次含义 |
|---|---|---|
| Q15 已从前置澄清进入正常问答，但主要绝对 F1 仍缺 | [D2 三题结果](../../artifacts/v3/d2-clarification-sufficiency-rerun-20261027/results.json)、[Q15 原记录](../../archive/run_logs/d9/agent_20261027_134354_854343_3d12a0aae212.md:192) | 旧记录作基线，不重新处理澄清流程，不把所有 P／R／F1 列一律设为必答 |
| 正文确实提供了部分性能证据 | [已发送正文](../../archive/run_logs/d9/agent_20261027_134354_854343_3d12a0aae212.md:368)含 0.979 recall、相对 F1 差异等 | 评价区分“有证据支持”和“核心内容是否覆盖”，不能因未读表格否定已经支持的结论 |
| 两张表已经解析和保存 | [表5父块](../../data/chunks/local_6ea12bf2b36844b39f032c65c04fbab8/r_6f647351b0a8f7af/parents.jsonl:25)、[表8父块](../../data/chunks/local_6ea12bf2b36844b39f032c65c04fbab8/r_6f647351b0a8f7af/parents.jsonl:33)；BERT 行分别见 [chunks 第35行](../../data/chunks/local_6ea12bf2b36844b39f032c65c04fbab8/r_6f647351b0a8f7af/chunks.jsonl:35)与[第49行](../../data/chunks/local_6ea12bf2b36844b39f032c65c04fbab8/r_6f647351b0a8f7af/chunks.jsonl:49) | 不需要重新 OCR、解析、分块或入库；这些具体定位仅供开发回查，不能写成 Q15 专用业务规则 |
| 目录只列 body parent | [reading_directory](../../paper_assistant/evidence_reading.py:37)筛选 `content_type == "body"` | 独立 table parent 未获得目录定位入口。本轮只读结果叙述，不是已经给出表格准确定位后模型没有读取 |
| 现有父块阅读已经能读取保存的子块 | [parent_children](../../paper_assistant/evidence_reading.py:28)、[execute_read](../../paper_assistant/agent.py:663) | 将表格纳入实际发送的目录后，复用 `accessible_parents → read_context(parent_id) → 原文历史 → 准备 → 最终` 即可 |

另一个需要保留的实际细节：表8当前继承的 `section_path` 是 `5. Conclusions and Future Work`，而保存的表题明确为 `Table 8: Results of Experiment B: MEDDOCAN`。因此目录不能仅增加一个无类型的 parent ID；应同时让模型看到表格类型与已有表题。本次保留保存的章节位置，不重做章节识别。

## 3. 参考 RAGFlow 的具体做法

参考用户本地 `E:/project/ragflow` 的 Go Agentic RAG 当前路径，不修改该仓库。

| 来源 | 采用的行为 | 本项目适配 |
|---|---|---|
| [原始 chunk 读取条件](E:/project/ragflow/internal/agentic_rag/grep_service.go:213) | 读取原始内容时，没有按 body 类型排除表格 | 让已有 table parent 与 body parent 一起进入当前版本的阅读目录 |
| [list_chunks](E:/project/ragflow/internal/agentic_rag/tool_list_chunks.go:40) | 定位后读取真实 chunk 原文，按需要取得上下文 | 保留本项目父块／子块结构，以 `read_context(parent_id)` 读取表格真实子块，不增加另一套工具或邻居窗口参数 |
| [原文输出](E:/project/ragflow/internal/agentic_rag/helper.go:755) | 保存的原始文本进入模型请求，带真实来源身份 | 沿用当前表题、表头及表行的原有文本／HTML，不生成表格摘要来替代原文，仍只引用实际发送的子块 |

RAGFlow 的锚点邻居读取与本项目的父块阅读不是同一接口；本次采用其“不按正文类型漏掉可读表格”的行为，接到已有接口即可。不引入 `decision_judge`、compiled claims 直接回答、视觉回看或第二个阅读 Agent。

## 4. 最小改动

### 4.1 表格进入阅读目录，并携带可识别的表题

主要修改 [evidence_reading.py](../../paper_assistant/evidence_reading.py:37)：

- 在现有所选 `paper_id / parse_revision` 范围内，目录同时包含 **body 与 table** parent，保持保存的文档顺序及已有 `section_path / parent_id / pdf_pages`。
- 目录条目补充 `content_type`；表格条目使用 `caption` 承载已保存的表题。优先复用已有表题内容；当前 API 版本的表题已在 `parent.text` 的开头，可直接取得原有表题行。没有表题时留空，不让模型编造标题，不把数据行或整张表塞进目录。
- 表题只帮助定位，例如辨认 Table 5／Table 8 及其结果对象；不能在生成阶段把目录表题当成表格数值证据。
- 不改变已保存的 parent／child 身份、顺序和内容，也不新建表格索引或入库元数据迁移。公式当前并入 body parent 的路径沿用。

### 4.2 接到现有实际阅读流程

[agent.py](../../paper_assistant/agent.py:414)已将实际请求中目录条目的 parent IDs 加入 `accessible_parents`，再由 `read_context` 读取该 parent 的真实子块。实施时沿用这条链路：

1. 实际探索消息能看到表格类型、表题、页码和 parent ID。
2. 模型自行选择是否读取。读取后，现有合并及消息历史保留表格原文；准备和最终请求继续承接这些材料。
3. 目录中的 parent ID 不加入引用白名单。只有实际发送的表格子块按现有规则获得引用权限。
4. 保留当前版本／来源范围检查，不按任意传入的 parent ID 读取其他论文或版本。

若实际目录构建、序列化或读取消费处需要直接适配，仅修改这些必要调用点。现有 `read_context(parent_id)` 已能读取时，不重写执行器。

必要时将 [目录字段说明](../../paper_assistant/agent_prompt.py:292)同步为“章节／表格定位信息”，说明 `content_type`、表题及定位不等于证据；只做接口说明适配，不修改 v2.20 的充分性判据，不强制每题读表、不增加取证次数。若提示正文确有变化，更新实际受影响的既有提示版本字段即可。

## 5. 实施后的指定离线验证

本次写规划不跑测试。后续实现后只调整并点选以下两个现有方法，全部使用本地通用材料／mock：

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：在既有结构化材料场景中补表格 parent／真实表头和表行子块，搜索只返回正文。确认实际目录提供表格位置，mock 模型从目录取得 parent ID 后能通过原生 `read_context` 取得表格；表格正文进入准备和最终请求，最终引用支持对应表行，目录本身不获引用权限。保留原来的正文阅读与所选版本范围行为，不新增独立检查器。
2. `scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question`：补目录中的 table 条目，确认表格类型、已有表题和页码在实际消息里保留；仅有目录时不泄露表行、不扩大引用范围，真正读取的表头／行按现有原文路径保留。已有 body 目录和原问、原文历史衔接继续正常。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question
```

mock 验证材料可达和消息衔接，真实模型是否选择读取由下一节观察。只有方法失败或有具体跨模块影响时才扩大到直接相关方法；未改且已通过的其他结果复用，不跑整个模块／目录／全量回归，不发真实模型或 embedding 请求作离线验证。

## 6. 离线通过后仅复测 Q15 一次

### 6.1 固定输入及已有版本

从 [D2 三题复测 input.json](../../artifacts/v3/d2-clarification-sufficiency-rerun-20261027/input.json)的 `questions` 数组按 `id="D2-Q15"` 取得原题和版本，不从评价文本生成新问题。

| 项目 | 固定值 |
|---|---|
| 原题 | `What is the performance of BERT on the task?` |
| QASPER question_id | `66c96c297c2cffdf5013bab5e95b59101cb38655` |
| 论文 | Sensitive Data Detection and Classification in Spanish Clinical Text: Experiments with BERT；QASPER paper_id `2003.03106` |
| 本地 paper_id | `local_6ea12bf2b36844b39f032c65c04fbab8` |
| parse_revision | `r_6f647351b0a8f7af` |
| 版本状态 | 复用已有 MinerU API ready 版本，不重新下载、解析、分块或入库 |

只向业务入口传原题、实际版本配对及普通完整回答要求。问题诊断、官方参考、表格位置、预期 chunk、数值和观察重点只用于开发回查与事后评价，不能作为业务输入、前置规划或工具指令。

### 6.2 执行及保存

- 只运行一次 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，独立新会话；保留原题号 Q15，使用本批新的会话／提交 ID，例如 `d3-table-reading-q15-20261028-q15`。
- 复用当前模型、1048576 上下文、temperature 0.2、4096 输出、30 秒单次超时、五步／五次取证及现有共享重试／修复配置，记录实际公开配置。三类旧证据截断继续取消，不为拿到表格增加额度、硬编码工具动作或改变问题。
- 真实前置规划、聊天、查询 embedding、可选重排、阅读、准备、最终及原额度内重试／修复属于这一题完整复测。不额外发连通性、固定证据、双模式评分或 judge 请求。
- 单独使用 `artifacts/v3/d3-table-reading-q15-20261028/`，保存普通 `input.json/results.json`；逐题原生 JSON／Markdown 仍由 runtime 写入 `archive/run_logs/d9/`。复用 `tmp/d2_clarification_sufficiency_three_run.py` 的窄调度方式，必要时只新增 Q15 的入口 `tmp/d3_table_reading_q15_run.py`，不直接运行旧三题／十题 main，不建设通用评测框架。
- 请求前保存尝试状态；已有本批尝试则直接整理，不重复调用。内容仍不完整、运行失败或进程中断均不自动重开，不追加追问、不在同一轮继续调规则后补跑。既有版本不可用或共享服务故障时记录实际阶段、用量和原因，不自动重入库或换版本。

### 6.3 评价口径

先区分两件事：

1. **入口是否补齐。** 表格条目是否进入实际发送的目录，包含真实类型、表题、页码和定位；若模型选择阅读，工具是否成功提供对应表头／表行，准备及最终是否保留。没有选择读表本身不证明入口修复失败，也不自动构成答案错误。
2. **答案是否覆盖原问。** 生成后结合实际原文与 QASPER 参考检查 BERT 在 NUBES-PHI／MEDDOCAN 下的主要性能及设置归属，重点看此前缺失的主要绝对 F1。相对比较和 0.979 recall 是有效证据，应保留其价值；不要求照抄整张表或补齐用户未问的每个 precision／recall 列，也不只凭状态为 answered 或引用定位 valid 判通过。

若表格未读到，沿现有动作和消息记录区分“目录没有送达、目录送达但未选择、读取失败、已读后准备遗漏、最终遗漏”。这是对实际记录的简短评价，不新增分类 schema、审核模型或诊断系统。引用和数据集／检测／分类设置需对应，不将 baseline 数值归给 BERT。

内容记通过／部分通过／内容未交付，运行失败单列；与 D2 最新 Q15 原记录逐项比较，记录聊天／查询 embedding／重排／重试／修复、tokens、耗时及日志路径。单题结果不外推准确率、稳定性或提速，不覆盖 D2 历史成绩。

## 7. 交付与结束条件

本阶段交付为最小表格目录改动、两个指定离线方法，以及 Q15 一次真实复测的结果。完成或明确故障停止后，在本节简要补记实际改动、验证、内容评价、用量和产物链接；不另建验证报告。

### 7.1 实际实施与结果（2026-10-28）

**实现：**[evidence_reading.py](../../paper_assistant/evidence_reading.py:44) 的 `reading_directory` 在所选版本内同时保留保存顺序的 body 与 table parent，条目保留 `section_path / parent_id / pdf_pages`，新增 `content_type`；table 条目从保存的 `parent.text` 首行取真实表题放入 `caption`，首行不是表题时留空，不生成摘要、不放入数据行。Q15 实际目录 32 条（22 body／10 table），Table 5 与 Table 8 均带表题和页码；Table 8 保存的 `section_path` 仍为 `5. Conclusions and Future Work`，凭表题识别，未重做章节识别。[agent_prompt.py](../../paper_assistant/agent_prompt.py:292) 仅同步目录字段说明（类型、表题、定位不等于证据），`AUTONOMOUS_PROMPT_VERSION` 更新为 `v2.21-table-reading-directory-v1`。未改 schema、存储、父／子块、`read_context`、充分性规则、模型或预算。

**离线：**两个指定方法通过，最后合并运行 2 tests OK，28.480 秒，mock，无真实模型／embedding 请求：`test_actual_cores_citations_closed_resources_and_stage_records` 在既有结构化场景加通用 table parent，搜索只返回正文，验证实际目录可定位表格、原生 `read_context(parent_id)` 取得真实表头／表行、准备与最终承接原文，最终引用支持表行且目录 parent ID 不获引用权限；`test_model_messages_show_only_selected_content_and_data_question` 验证目录 body／table 字段、type／caption／页码保留，仅目录不泄露表行、不扩大引用范围，已显示的表行按原路径保留，既有正文路径继续工作。

**Q15 真实复测：**各阶段只运行一次，`mode="agent"`、`library_mode=True`、空会话历史；实际配置为 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证，旧证据截断未恢复。run_id `20261028_021608_088510_6976db5be1ed`，1/1 completed、answered，0 重试、0 修复；4 次聊天请求、62,768 tokens、报告耗时 41.531 秒，查询 embedding 1 次、重排 1 次；9 条主张、7 个 evidence sources，citation_checks valid；2 个自主步骤、1 次取证调用、1 轮搜索，展示 9 块、10,302 字符，`max_chars=None`、无 `max_tokens`。

**入口与内容评价：**入口已补齐。实际发送的目录含 Table 5／8 的类型、表题和页码且未夹带表行；模型未调用 `read_context`，选择一次搜索后直接获得表5／表8的 BERT 行子块（`p6_c3`、`p8_c3`），自动父块续读补充表头，表格原文实际进入准备与最终消息。内容记 **通过**：直接回答补齐 NUBES-PHI（Experiment A）与 MEDDOCAN（Experiment B）的 BERT 绝对 detection／classification precision、recall、F1（例如 NUBES-PHI detection 0.952／0.979／0.965、strict classification 0.925／0.950／0.937；MEDDOCAN detection 0.973／0.972／0.972、classification 0.968／0.967／0.967），数据集、实验和列归属正确，引用表行支持数值；正文 0.979 recall 与相对比较等既有有效证据保留，此前 D2 缺少的主要绝对 F1 已补齐。

**与 D2 基线对比：**D2-Q15 原记录为 6 次聊天、143,028 tokens、4 个自主步骤、3 次取证调用、13 块／17,260 字符、40.578 秒，内容部分通过且缺绝对 F1；本次为 4 次聊天、62,768 tokens、2 个自主步骤、1 次取证调用、9 块／10,302 字符、41.531 秒，内容通过。两次 embedding／重排各 1 次，重试／修复各 0；单题步骤与用量变化不作为准确率或速度结论，D2 基线保留。不因未调用 `read_context` 判错。

**产物：**[input.json](../../artifacts/v3/d3-table-reading-q15-20261028/input.json)、[results.json](../../artifacts/v3/d3-table-reading-q15-20261028/results.json)；逐题原生 [JSON](../../archive/run_logs/d9/agent_20261028_021608_088510_6976db5be1ed.json)／[Markdown](../../archive/run_logs/d9/agent_20261028_021608_088510_6976db5be1ed.md)。本次到此结束，未改充分性、公式／OCR、入库、分块、短答或其他题目。

保留 D2 已取消的前置澄清及现有“取证 → 准备 → 最终生成”。不并入公式解析、OCR、重新入库、表格分块重做、邻居窗口新工具、充分性规则调整、短答字段整改或其他性能优化；不引入裁判、额外模型、哈希／正文指纹、manifest、快照、审计和无关保护层。

不重跑 Q12／Q13、旧十题或自动开始新十题。此次单题结束后，后续新题测试另行安排；不为取得一次通过而反复重跑 Q15。文末保留下一节 DeepSeek 提示词。

## 8. 给 DeepSeek 的执行提示词

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d3-plan.md，以及 docs/v3/d2-plan.md 第15.7.1节。执行D3：补齐已入库表格的定位／阅读入口，完成两个指定离线方法，再真实复测Q15一次。D2两处修正已经完成，不执行D1／D2历史提示，不重跑Q12／Q13或旧十题，保留工作区已有修改。

先看实际代码和已有D3记录。此次具体缺口是 paper_assistant/evidence_reading.py 的 reading_directory 只列body parent；Q15的表5／表8早已解析入库，但上次没有进入阅读目录。本次只补这一入口，不继续改探索／准备的充分性规则。Q15正文已有0.979 recall和相对性能等有效证据，不能把未读表格直接等同于无据回答，也不把整套P／R／F1全列设成每道性能题的必答条件。

参考本地 E:/project/ragflow/internal/agentic_rag/grep_service.go:213 的原始chunk读取条件，以及tool_list_chunks.go:40和helper.go:755的定位后读原文行为：不要因body类型筛选漏掉可读表格。接入本项目时复用当前父块／子块和read_context，不迁移RAGFlow框架，不新增邻居参数或公式阅读器。

主要改reading_directory：在所选paper_id／parse_revision内同时列body和table，保留保存顺序和section_path／parent_id／pdf_pages；补content_type，表格条目用caption承载已保存表题。当前API版本表题已在parent.text开头，直接取得真实表题行；没有表题留空，不编造、不生成摘要、不把数据行或整张表塞入目录。表8当前保存的section_path可能是Conclusions，仍应凭它真实的Table 8表题识别，不为此重做章节识别或解析。公式已有body parent路径保持现状，不假设公式也被排除。

复用agent.py现有目录→accessible_parents→read_context(parent_id)→真实子块→原文历史→准备→最终链路。只有实际发送的表格子块获得引用权限，目录parent ID／caption不作答案证据。沿用既有版本和来源范围检查；read_context已支持读取时不重写执行器，不改schema或存储。必要时只适配实际目录字段的序列化及目录说明，保持充分性规则、模型和预算现状，不强制读取表格。若实际提示正文有变化，更新真正受影响的既有版本字段即可。

实现后只调整并点选两个既有方法：scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records，以及 scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question。前者用现有结构化fixture补通用表格，搜索只给正文，验证实际目录可定位表格、原生read_context能取得真实表头／行、准备和最终承接原文与引用；后者验证实际目录字段保留、仅目录不泄露表行或放宽引用、已有正文路径继续工作。使用本地材料与mock，不为离线验证发真实模型或embedding请求。只在必要时扩展这两个方法，不新建检查器；仅失败或具体跨模块影响才扩大直接相关方法，不跑模块／目录／全量回归，未改且已通过的结果复用。

离线通过后，只真实运行Q15一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])。原题／question_id和selected_versions从artifacts/v3/d2-clarification-sufficiency-rerun-20261027/input.json的questions按id=D2-Q15取得，原题为What is the performance of BERT on the task?，本地版本为local_6ea12bf2b36844b39f032c65c04fbab8／r_6f647351b0a8f7af，复用已有MinerU API ready结果，不下载、解析、分块或重新入库。真实请求仅为这一题正常前置规划、聊天、查询embedding、可选重排、阅读、准备、最终及原额度内重试／修复；不发额外连通性、固定证据、双模式或judge请求。

只传原题、版本配对和普通完整回答要求；官方参考、诊断、表5／表8的具体定位、期望数值、chunk或观察重点不进入模型消息、规划或检索参数。模型自行决定动作，不加额度、不强制工具、不改为最短答案／F1协议。保持当前模型、1048576上下文、temperature 0.2、4096输出、30秒单次超时、五步／五次取证和既有共享修复，旧8192证据窗口／8000字符／累计八块截断保持取消。实际公开配置照实记录，不静默换参数。

使用artifacts/v3/d3-table-reading-q15-20261028/普通input.json/results.json，原生JSON／Markdown继续由runtime写入archive/run_logs/d9/。复用tmp/d2_clarification_sufficiency_three_run.py的窄调度逻辑，必要时只新增tmp/d3_table_reading_q15_run.py，不运行旧多题main。使用本批新的会话／提交ID，例如d3-table-reading-q15-20261028-q15；先保存尝试状态再请求。已有本批尝试不重跑；失败、中断或内容未改善均保留，不追加追问、替代题或改提示后补抽样。已有版本不可用或服务故障就记录原因和实际用量，不自动重建索引。

生成后按D3第6.3节评价，分别看目录／读取入口是否修好和内容是否覆盖原问。主要检查此前缺少的绝对F1及其数据集／检测／分类归属，引用必须支持实际值；承认正文相对性能的有效性，不要求抄全P／R／F1表。没有读表不单独判错，若有缺口则沿实际消息区分入口、选择、阅读、准备或最终哪个环节未取得／保留材料。不以answered、引用valid或工具次数代替内容通过，不据单题声称准确率或稳定提速。

完成局部实现、两个离线方法及Q15一次真实复测后，在D3第7节简要补记改动、验证、内容结果、用量和产物路径，保留D2基线，不另建验证报告。此次到此结束，不顺带改充分性、公式／OCR、入库、分块、短答、其他题或新十题；不新增审核模型、裁判、哈希、manifest、快照、审计、无用校验或无关重构。保持D3最后一节为本提示词。
```

## 9. D3 新十题 QA 测试规划（2026-10-28）

### 9.1 目的、来源与范围

用户已安排继续测试，本批在 D3 现有实现上运行十道新题，**只测试，不修改业务代码或提示词**。第 8 节保留为已完成修正任务的历史提示；本批使用第 11 节最新执行提示词，不重做表格目录修正，不重跑 Q15。

十题全部来自本地 [QASPER 官方 dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json)，五篇不同于上一批的论文、每篇两题。延续此前题号，记为 **D3-Q21～D3-Q30**。选题时已与现有 `artifacts/v3/*/input.json` 及 QASPER 样本索引对照，十题的 question_id 和原问均未重复；执行时直接按本节固定题号读取，不另建排重或题单校验程序。本批是公开 dev 的定向开发观察，不是隐藏 test 或随机抽样成绩。

观察重点是新题中的数值与设置归属、必要并列项、公式／文字说明衔接，以及材料充分时是否正常停止。D3-Q15 的核心数值已通过，但其指标列名与数值行分处不同块，最终主要引用行块；本批顺带观察结论依赖跨块表头时是否保留必要来源。此观察不作为开跑前必须再修的事项，也不要求所有表格结论一律引用整张表。

新论文允许通过现有入口入库；已有相同 PDF／API 解析方案的 ready 版本直接复用。不为了测试而改入库、检索、公式、表格分块或充分性判断，不强制出现阅读动作或超容量裁剪。

### 9.2 五篇论文及固定 PDF 来源

已核对以下 arXiv 论文题名与公开版本，按表中版本下载，不自动跟随最新版。R1～R4 使用 v1，R5 使用包含实验和消融的 v2。本地 paper_id／parse_revision 以实际导入返回为准，不提前编造。

| 代号 | QASPER paper_id | 论文 | 固定 PDF |
|---|---|---|---|
| R1 | `1911.02855` | Dice Loss for Data-imbalanced NLP Tasks | [arXiv v1](https://arxiv.org/pdf/1911.02855v1) |
| R2 | `1909.09587` | Zero-shot Reading Comprehension by Cross-lingual Transfer Learning with Multi-lingual Language Representation Model | [arXiv v1](https://arxiv.org/pdf/1909.09587v1) |
| R3 | `1909.08089` | Extractive Summarization of Long Documents by Combining Global and Local Context | [arXiv v1](https://arxiv.org/pdf/1909.08089v1) |
| R4 | `1909.03582` | Clickbait? Sensational Headline Generation with Auto-tuned Reinforcement Learning | [arXiv v1](https://arxiv.org/pdf/1909.03582v1) |
| R5 | `1908.06267` | Message Passing Attention Networks for Document Understanding | [arXiv v2](https://arxiv.org/pdf/1908.06267v2) |

论文来源链接用于准备 PDF；问答仍必须从本项目实际入库材料检索，不将 QASPER 的 `full_text` 或 gold evidence 当作已检索正文喂给模型。若固定 PDF 与官方参考存在内容／版本差异，事后按实际原文评价并说明，不为匹配参考中途换版或补跑。

### 9.3 十题与固定执行顺序

下表的观察重点只用于事后评价，不进入前置规划、模型消息、检索参数或工具调用。英文题目保留原拼写及语法；实际执行从官方 JSON 按 question_id 提取原始 `question`，不复制或润色展示文本。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q21 | R1 | What are method's improvements of F1 for NER task for English and Chinese datasets? | `b5bc34e1e381dbf972d0b594fe8c66ff75305d71` | 语言／数据集下的并列提升；区分绝对 F1、提升点数和比较基线 |
| D3-Q22 | R1 | How are weights dynamically adjusted? | `20e38438471266ce021817c6364f6a46d01564f2` | 动态权重的机制与所需公式含义；主体、变量及条件忠实，不扩成未问的完整推导 |
| D3-Q23 | R2 | What is the model performance on target language reading comprehension? | `37be0d479480211291e068d0d3823ad0c13321d3` | 目标语言、实验设置和性能数值对应，不只说表现良好 |
| D3-Q24 | R2 | What source-target language pairs were used in this work? | `a3d9b101765048f4b61cbd3eaa2439582ebb5c77` | 源／目标方向及必要并列项，区分训练方向与评价场景 |
| D3-Q25 | R3 | How much does their model outperform existing models? | `de5b6c25e35b3a6c5e40e350fc5e52c160b33490` | 不同数据集、指标和基线下的比较，提升范围有据 |
| D3-Q26 | R3 | What do they mean by global and local context? | `b66c9a4021b6c8529cac1a2b54dacd8ec79afa5f` | 两个概念与文中具体含义完整对应，不以通用术语解释代替论文事实 |
| D3-Q27 | R4 | What is this method improvement over the best performing state-of-the-art? | `ae7c93646aa5f3206cd759904965b4d484d12f83` | 比较对象、指标和增益，不能把单个维度的优势推广到所有结果 |
| D3-Q28 | R4 | What is future work planed? | `b0d66760829f111b8fad0bd81ca331ddd943ef41` | 明确回答作者的未来计划，与已经完成的工作分开；不改官方拼写 |
| D3-Q29 | R5 | Which component is the least impactful? | `2858620e0498db2f2224bfbed5263432f0570832` | 消融证据与适用数据集；结论需条件化时正常限定，不预设统一排名 |
| D3-Q30 | R5 | What is the message passing framework? | `bc67b91dd73acded2d52fd4fee732b7a9722ea8b` | 框架的必要阶段及关系，公式与解释有据，不过度展开整套模型 |

Q24 官方原题末尾有一个空格，以 JSON 原字串为准。十题均为独立新会话，不通过同论文上一题的答案、工具历史或准备事实为下一题预填证据。

### 9.4 必要入库与现有结果复用

通过已完成的 `import_runtime.import_pdf` 默认 MinerU API 入口准备第 9.2 节五篇论文，沿用 VLM／全文 OCR／公式和表格识别配置及现有分块、SQLite、embedding、Qdrant 流程。必要的 PDF 下载、官方解析和索引 embedding 属于后续执行本批所需的准备工作；本次写规划不发起这些请求。

- 有相同固定 PDF 和 API 解析方案的 ready 版本则直接复用；已有相同方案解析 bundle 时复用现有导入能力，不重复上传，不用旧 Standard 版本冒充本批 API 版本。
- 使用实际 ready 返回的 `paper_id / parse_revision` 将 R1～R5 各自绑定到两题，记录公开来源及解析配置。继续使用当前索引 profile，不修改模型或重建现有索引来准备本批。
- 单篇准备失败时保存该篇两题未执行及原因，其他独立论文可继续；共享服务故障阻断后续时保留已有结果和实际用量后停止。缺配置按现有失败结果说明，不加额外连通性请求，不静默回退本地解析。

本批没有业务代码修改，不跑离线测试、语法扫描或全量回归；D3 已通过的两个方法直接复用。不为执行本批增加 manifest、哈希、快照、额外 ready 校验器或重复的题目／版本检查层，沿用入库及问答入口已有检查。

### 9.5 执行、参数与普通产物

每题按固定顺序只调用一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，输出普通完整回答及引用。模型自主选择搜索、阅读与准备；不因未调用 `read_context`、没有耗尽额度或未出现超容量路径而补跑。

保持 D3 当前配置及实际提示版本：`deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证及既有共享重试／修复。保留表格目录、已读原文历史、取消前置澄清和 v2.20 充分性行为，固定 8192 证据窗口、8000 字符、累计八块及旧页面聊天／整题超时限制不恢复。实际配置与提示版本照实保存，不静默换参数。

本批目录为 `artifacts/v3/d3-qa-new-ten-20261028/`，仅使用普通 `input.json/results.json`；逐题完整 JSON／Markdown 继续由现有 runtime 保存至 `archive/run_logs/d9/`。

- `input.json` 保存官方来源、固定版本、实际入库配对、十题无 gold 输入及公开配置；准备和问答成本分开，索引 embedding 与查询 embedding 分开。
- `results.json` 汇总每题实际状态、停止原因、原生日志路径、真实用量与简短评价，不再复制一套完整工具正文。
- 复用 `tmp/prepare_d2_dev_five.py`、`tmp/d2_qa_dev_next_ten_run.py`、`tmp/d3_table_reading_q15_run.py` 中现有准备和顺序调度方式；需要时只新增本批窄入口，如 `tmp/d3_qa_new_ten_run.py`，将论文清单、题号、stage、目录及会话／提交前缀改为本批，不运行旧 main、不建设通用评测框架。
- 十题会话／提交 ID 使用 `d3-qa-new-ten-20261028-q21` 至 `q30`。先保存尝试状态再请求；已有本批尝试只接续未尝试题，失败／中断或回答不完整不自动重开，不追加追问、替代题或改提示后补抽样。

本批真实调用仅包括必要入库，以及十题正常前置规划、Agent、准备、最终、查询 embedding、可选重排和原额度内重试／修复。不运行 fixed_rag、QASPER 双模式评分、审核模型、固定证据实验或额外模型连通性测试，也不要求最短答案或新增 F1 短答协议。

### 9.6 内容评价与停止位置

生成后，按实际提供的原文与官方参考逐题作 AI 辅助评价，记通过／部分通过／内容未交付，运行失败单列。运行完成、引用定位 valid 或事实数量不替代内容判断。

重点保留以下与现有问题直接相关的观察，不建立新的判定器：

- 所问核心对象、并列项、关系和必要条件是否答全；数值与数据集、指标、实验、比较对象对应。提升点数、绝对值与相对比例不能混用，未报告数值不编造。
- 需要表格时，沿已有目录、工具及实际消息查看材料是否取得并保留。搜索直接给出原文即可作答，不强迫再读一次；表题和目录只定位，不代替表行。结论需要跨块列头和数据行共同支持时，应保留必要来源；单块已经完整支持时不要求多挂引用。
- 公式／机制问题按原问需要解释，保留变量、主体及条件，不以熟悉的公式替换原文，不为每题补全未问的整段推导。普通问题不升级为形式证明，明确询问未来工作的题则正常回答未来计划。
- 核心缺口仍在、有具体方向且额度可用时，是否继续取证；材料足够时正常停止。若仍不完整，区分未取得、已取得后遗漏、准备或最终漏表达，给出原记录依据，不因工具次数较少直接判提前收尾。
- `direct_answer` 若自发出现，观察它与主答一致性，不用其字段代替主答评价，不在本批修短答协议。附加分析、全文排除或矛盾判断仍须有原文依据。

十题各一次，或明确共享故障停止后结束。在第 10 节简要记录五篇准备、十题评价、重复出现的具体问题、成本和产物路径。只说明这十道公开 dev 原题的实际结果，不重算旧批次，不据不同题目声称准确率提升或稳定提速；不自动继续修复、加步数或开始另一批。

## 10. 新十题实际结果

### 10.1 五篇准备（2026-10-28）

五篇按第 9.2 节固定版本下载 PDF，并通过现有 `import_runtime.import_pdf` 默认 `mineru-api` 入口入库；解析配置为 MinerU API `vlm`、全文 OCR、`enable_formula=true`、`enable_table=true`，沿用当前索引 profile `ep_cbf0f6caa97b962a`。未改解析、分块或索引代码；本次无同 PDF／同 API 方案可复用，五篇均新建 API bundle。全部 `ready`，实际配对如下：

| 代号 | 实际 paper_id / parse_revision | chunks | API batch |
|---|---|---|---|
| R1 1911.02855v1 | `local_575eedb5adbe4b9280e4ba44c3f79fb2` / `r_b34d29cc2d46509c` | 45 | `d55f63fc-7a0e-4369-ba3b-79a2605af34b` |
| R2 1909.09587v1 | `local_7ae5be87fd2a43aaa38f84c9dad1fd70` / `r_a9023725da88cf1a` | 35 | `b08276e7-d5c6-445a-8fe0-c9d7162591a5` |
| R3 1909.08089v1 | `local_0f9f9bf444a043b89195a40ff08f923c` / `r_189ff4e8823117cd` | 45 | `e26bc5f1-a758-4fc7-b0d9-c14b2a54582b` |
| R4 1909.03582v1 | `local_a557504b72314b5f8bec1843355740f0` / `r_cf7b538a251a4239` | 40 | `5ba68dad-73ac-4da8-b004-1d52208f8e34` |
| R5 1908.06267v2 | `local_c478c4244d854f1ca16394c147d25534` / `r_b1ddfb5d02f59522` | 39 | `a9471206-b73d-43c5-a66d-d713facc3a66` |

入库合计 204 chunks、22 次索引 embedding 请求、221.919 秒；与问答成本分开记录。十题按第 9.3 节固定顺序执行，原问从官方 dev JSON 按 question_id 取得，Q24 末尾空格保留；无 gold／观察重点进入模型消息。

### 10.2 逐题结果与内容评价

十题各一次独立新会话，`mode="agent"`、`library_mode=True`、空历史；实际配置保持 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证。结果：**9 completed（9 answered）、1 run_failed（Q25 invalid_output）；内容 7 通过、2 部分通过、1 运行失败**。

| 题号 | 结果 | 内容评价 |
|---|---|---|
| D3-Q21 | 通过 | 给出 English CoNLL2003 +0.29、OntoNotes5.0 +0.96，Chinese MSRA +0.97、OntoNotes4.0 +2.36，并明确相对 BERT-MRC baseline；另给绝对 F1 93.33／92.07／96.72／84.47。 |
| D3-Q22 | 通过 | 说明 weight 与 (1−p) 成正比、将 p 变为 (1−p)p 以压低 easy examples，并给单例 DSC 公式与导数直觉；未展开未显示的 Eq.12，属原问外。 |
| D3-Q23 | 部分通过 | 给出跨语言迁移的定性结论及 testing on English 的 53.8 vs 44.1，但主要 target-language（Chinese／Korean）Table 1／2 的 EM／F1 未取得；body 已明确指向 Table 1／2，仍有 3 次取证额度却以 `Unanswerable` 收尾，且 direct_answer 与 claims 已有数值不一致。 |
| D3-Q24 | 通过 | 列出未翻译 En／Zh／Kr 及 translated En-Fr、En-Zh、En-Jp、En-Kr、Zh-En、Zh-Fr、Zh-Jp、Zh-Kr，并说明测试语言为 English／Chinese／Korean；与官方参考一致。 |
| D3-Q25 | 运行失败 | `prepared_final_decision` 先返回 `invalid_action_schema`（reason 放在 action 顶层），共享修复后返回 `invalid_json`；无 answer／claims／引用，保留失败记录，未重跑。 |
| D3-Q26 | 通过 | global context 指 whole document 的表示，local context 指当前 topic／section 内句子的表示；并给模型组合方式与消融背景，未以通用术语替代论文定义。 |
| D3-Q27 | 通过 | 给出相对 Pointer-Gen baseline 的 absolute 18.2%（60.8% vs 42.6%），并明确不是对最强 RL baseline 的相对百分比；Table 3 行块支持数值。 |
| D3-Q28 | 通过 | 按原问列出三项未来工作：改进 sensationalism scorer、探索 RL／MLE 动态平衡在 textGAN 的应用、进一步研究生成 sensational headlines 的伦理问题。 |
| D3-Q29 | 部分通过 | 已读 Table 3 的列头／数据行，也指出 undirected edges 的影响随数据集而异，但结论称论文没有明确 least-impact 排名，未比较差值或指出 undirected 为 least impactful（官方参考为 max abs 0.33）；仍有 3 次取证额度并以 `no_reliable_evidence_direction` 收尾，属已取得材料后未完成比较。 |
| D3-Q30 | 通过 | 把 MP framework 说明为递归邻域聚合：AGGREGATE／COMBINE／READOUT、T 步迭代与 permutation-invariant 读出，并给形式化变量；未扩成整套 MPAD。 |

表格跨块观察：Q24、Q27 的引用表块含列头和数据行；Q29 也已取得 Table 3 的列头／行块，但准备／最终未完成“least impactful”比较；Q23 未读已定位的 Table 1／2。Q21、Q22 的数值／公式主要由正文块支持，未强制引整表。

### 10.3 成本与产物

问答合计 43 次聊天请求、663,125 tokens、报告耗时 281.515 秒；查询 embedding 14 次、重排 14 次；0 网络重试、1 修复；57 条主张、38 个 evidence sources；22 个自主步骤、19 次取证调用、14 轮搜索，累计展示 86 块／98,121 字符。入库成本另计：22 次索引 embedding、221.919 秒。`results.json` 保留逐题状态、停止原因、原生日志路径、真实用量与简短评价；本批只说明这十道公开 dev 原题的实际结果，不重算旧成绩，不声称准确率或稳定速度提升。

**产物：**[input.json](../../artifacts/v3/d3-qa-new-ten-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-new-ten-20261028/results.json)；逐题原生 JSON／Markdown 在 `archive/run_logs/d9/`，路径见 results。D3-Q15、D2 历史和第 7.1 节保留。本批结束后不自动修复上述问题或继续下一批。

## 11. 给 DeepSeek 的新十题执行提示词

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d3-plan.md 第7.1、9～10节，执行D3-Q21～D3-Q30十道新QASPER官方dev原题。本任务只测试D3当前版本，不修改业务代码、提示词或预算。第8节是已完成的历史修正任务，不重做目录修正，不重跑Q15、Q12／Q13或旧十题。遵守Stop That Shit的范围要求，不添加冗余校验。

本批固定使用第9.2节五篇论文及PDF版本：R1 1911.02855v1、R2 1909.09587v1、R3 1909.08089v1、R4 1909.03582v1、R5 1908.06267v2，每篇两题。允许现在入库，必要PDF下载、MinerU官方API全文解析及索引embedding属于本批准备工作；已有相同PDF／API方案的ready结果就直接复用，已有同方案bundle也通过原有入口复用，不重复上传，不用历史Standard版本冒充。沿用import_runtime.import_pdf默认API入口的VLM／全文OCR／公式／表格配置和当前索引profile，不改解析或索引代码。实际paper_id／parse_revision用ready返回绑定R1～R5，不拿QASPER paper_id代替、不预造版本。单篇失败保留该篇两题未执行并说明，其他独立论文可继续；共享故障阻断后续时记录已有结果和用量后结束，不自动换版或重建索引。

按第9.3节固定顺序和question_id，从eval/qasper/raw/qasper-dev-v0.3.json读取原始question。十题题号D3-Q21～Q30，保留原英文、拼写、语法及Q24末尾空格，不生成或润色题目。只把原问、实际版本配对和普通完整回答要求传给业务入口。开发观察、Q15诊断、参考答案、gold evidence、预期公式／数值／chunk及工具动作不进入模型消息、前置规划或检索参数，不以QASPER full_text绕过真实入库检索。选题排重已在规划时完成，不另建排重流程或题单校验程序。

每题仅一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，十题独立新会话，同论文两题也不共享先前回答或工具历史。模型自主选择搜索、阅读和准备，不强制read_context、耗尽额度或超容量路径。保留D3当前模型／提示与配置：deepseek-flash、1048576上下文、temperature 0.2、4096输出、30秒单次超时、五步／五次取证和原有共享重试／修复。保留表格目录、已读正文历史及已取消的前置澄清；不恢复8192固定证据窗口、8000字符、累计八块或旧页面请求／整题时限。实际公开配置及版本写入普通input.json，不静默换模型或参数。

使用artifacts/v3/d3-qa-new-ten-20261028/普通input.json/results.json，逐题原生JSON／Markdown继续由runtime写入archive/run_logs/d9/，不复制另一套正文日志。input记录论文固定来源、API配置、实际入库配对和十题无gold输入；results记录真实状态、停止原因、日志路径、用量与简短评价。入库成本与问答成本分开，索引embedding与查询embedding分开。复用现有五篇准备和顺序问答调度逻辑，需要时只建tmp/d3_qa_new_ten_run.py等本批窄入口，修改本批论文、题号、目录、stage和会话／提交前缀，不能启动旧main去跑旧批次，不建设通用框架。

会话／提交ID使用d3-qa-new-ten-20261028-q21至q30。先保存尝试状态再调用；已有本批尝试不重跑，只接续从未尝试题。内容不完整、失败或中断均保留，不追加追问／替代题，不在测试中改提示后补抽样。真实调用只包括必要入库和十题正常前置规划、聊天、取证、准备、最终、查询embedding、可选重排及原额度内重试／修复，不额外运行连通性、fixed_rag、双模式评分、固定证据或judge实验，不新增最短答案或F1协议。

生成后按第9.6节用实际原文和官方参考逐题评价，先看核心覆盖、数字／实验设置和引用归属。特别观察表格列头与数据行跨块时的必要引用，以及正文／公式解释是否忠实；不要求每条都引用整表或抄完整P／R／F1。搜索已给足原文时可直接准备，没用read_context不单独判错；核心仍缺、有方向及额度却收尾时记录具体依据。普通问题不升级成证明或未来提案，Q28明确问未来工作则按原问回答。自发direct_answer只看与主答一致性，不替代claims评分。版本差异按实际入库原文说明，不中途换版补跑，不将缺失加强成全文不存在。

这是无业务代码变更的观察批次，D3已通过的离线结果直接复用，不再跑离线测试、语法扫描或全量回归，不新增题单／ready验证器、哈希、manifest、快照、审计或审核模型；沿用现有入库和问答入口已有检查即可。十题各一次或明确共享故障停止后，在D3第10节简要补记五篇准备、逐题内容评价、仍有的具体问题、成本与普通产物链接，保留D3-Q15和D2历史，不另建验证报告，不重算旧成绩或声称准确率／稳定速度提升。完成这批后结束，不自动修问题、加额度或继续下一批，保持D3文末为本提示词。
```

## 12. 后续修正计划：计算工具与自然语言最终回答

制定日期：2026-10-28。状态：**已实施并完成三题复测**；实际改动、离线验证与 Q23／Q25／Q29 结果见第 13 节。第 1～11 节保留为历史。

本阶段采用已经讨论的两项方案：**增加 RAGFlow 式 `run_javascript` 计算工具；Agent 最终只生成自然语言正文和 `[ID:n]` 引用标记**。准备阶段仍使用结构化事实，相关充分性表述与正文消费处一并适配。此处不是只去掉外层 `action`、仍让模型填写 `claims` 的折中方案。

### 12.1 三个问题与本次处理范围

| 问题 | 已确认的原因或现象 | 本次处理 |
|---|---|---|
| Q25 最终未交付 | 最终 JSON 把 `reason` 放在 action 顶层，修复后又多出结束括号；两次均正常结束，不是输出长度或超时截断 | 最终正文退出 `AnswerAction / AnswerDraft` 的 JSON 生成与解析链路，程序负责状态、引用解析及保存 |
| Q29 已有完整数值却没有完成比较 | Table 3 已送达，准备也提取了数值，但模型以作者没有明确写出最小影响排名为由收尾 | 增加可选计算工具；明确“原始事实忠实提取”不等于“只能回答作者直接写过的结论”，允许依据已读数值作可说明的比较 |
| Q23 未取得目标语言主结果 | 实际目录已给出 Table 1／2，模型读取结果叙述后判充分，缺主要 EM／F1；这次与旧 Q15 的目录缺失不同 | 记录并在同题复测继续观察；不再改目录、不增加必须读表或逐题完整性判定器 |

Q29 的准备指令边界可能影响了判断，但不能据此证明唯一根因。计算工具和表述调整提供完成比较的能力，也不保证模型每次都会调用或判断正确。Q25 改为正文后仍须评价内容：旧运行还缺主要结果比较，不能只因成功输出便判通过。

### 12.2 采用的 RAGFlow 行为与必要适配

参考用户本地 `E:/project/ragflow` 的当前 Go Agentic RAG，不修改该仓库。

| RAGFlow 来源 | 直接采用 | 本项目的必要适配 |
|---|---|---|
| [run_javascript](E:/project/ragflow/internal/agentic_rag/tool_run_javascript.go:38) | 主模型可选调用；参数 `code`；对已持有的数据做算术、排序、计数、聚合；`console.log` 返回结果；每次独立执行 | Go 的 goja 无法直接放入本项目 Python，采用嵌入式 JS 运行时承接相同工具接口 |
| [最终正文规则](E:/project/ragflow/conf/agentic_rag.yaml:47) | 一条自然语言回答，论文事实后带 `[ID:n]`；程序转成界面引用 | 接到现有准备成功后的最终生成请求，保留本次运行中实际送达的原文及工具历史 |
| [稳定引用句柄](E:/project/ragflow/internal/agentic_rag/evidence_registry.go:27) | 同一运行内来源首次展示时分配编号，再次出现仍用原编号 | 直接用已有 `paper_id / parse_revision / chunk_id` 身份维护小型映射；**不复制其正文哈希去重实现，不增加新哈希** |
| [数值规则](E:/project/ragflow/conf/agentic_rag.yaml:50) | 保留原始精度，中间计算不提前舍入，区分单位和差值／比例 | 适用于准备充分性说明、工具描述与最终正文，不新增计算审核模型 |

不迁移 `decision_judge`、compiled claims 直接回答路径、额外模型或第二个 Agent；论文问答仍经过现有准备阶段。不复制 RAGFlow 的大步数或时限配置。

### 12.3 增加可选计算工具，接入现有自主循环

实施前已确认当前 Python 为 3.14.4，依赖清单中没有 JS 运行时。计划仅增加 **`mini-racer`** 依赖，模块名为 `py_mini_racer`；其[官方文档](https://bpcreech.com/PyMiniRacer/#compatibility)说明支持 Python 3.10～3.14 和 Windows，并提供同步执行超时。实施时固定实际使用的兼容版本，不升级其他依赖。V8 支持的语法按实际运行时说明，不额外仿造 ES5.1 语法扫描器。

主要接入 [agent_actions.py](../../paper_assistant/agent_actions.py)、[agent.py](../../paper_assistant/agent.py) 和 [agent_prompt.py](../../paper_assistant/agent_prompt.py)，执行器可放在一个职责单一的小模块：

1. 工具名 `run_javascript`，原生 function calling 参数为 `{"code":"完整 JavaScript"}`，输出来自 `console.log`。沿用主模型已有的工具调用、`tool_call_id`、观察记录和历史重放方式，不另起模型请求或计算服务。
2. 工具只处理模型已经取得的数值或列表，支持差值、相对比例、排序、计数和聚合；不能替代搜索／阅读，也不能把常量结论打印一次当成计算。使用 JS 内建功能，不注入文件、网络、数据库、环境变量、Python 对象或 Node 接口。
3. 每次创建并关闭独立运行时。保留执行所必需的终止边界：输入 64 KiB、stdout 1 MiB，二者沿用 RAGFlow；本项目无统一整题截止时限，故单次 JS 执行设 5 秒上限，并使用运行时自身的堆内存上限。直接使用运行时能力，不建设通用沙箱平台或多层代码审核器。stdout 达上限时终止并返回工具错误，不将截断结果当成完整计算。
4. 成功结果和语法／执行／超时错误均写入现有工具观察，后续请求能看到；失败后由模型在剩余额度内决定如何继续。不静默换用 Python `eval/exec`、系统 shell 或另一个模型，不自动扩大额度重试。
5. 每轮带工具请求沿用现有自主步数计算方式；计算调用不计入搜索／阅读共用的五次**取证**额度，也不带来额外自主步骤。工具可用性应分别由其用途和剩余步骤决定，不能因取证额度耗尽就连计算一起屏蔽；现有终止阶段仍只收尾。无须另设计算调用总额度。
6. 计算输入、输出和错误保存在现有 action/tool 记录中，与新增工具定义一起进入完整请求容量管理。计算结果是由已读材料得到的中间结果，不是新论文来源，不分配引用句柄；最终引用应指向提供输入数据及必要条件的真实原文。

### 12.4 对齐准备与最终阶段的充分性边界

保留现有 `prepare_answer`、`facts / answerable / missing_information` 和事实短引句机制。只修改与此次问题有关的规则：

- `facts` 继续忠实保存原始事实、数值、指标、实验条件和引用；模型算出的排名或差值不能冒充作者原话，不能伪造对应短引句。
- `answerable` 判断现有原文是否提供回答所需的输入与关系。若比较对象、基线、指标、单位和必要数值已齐，能够通过简单计算回答，不应仅因作者没有写出同一句比较或排名而判无答案。可以在准备前调用计算工具；简单计算也可由最终模型完成，工具不是每题必经关卡。
- 最终正文允许明确写“根据表中数值计算／比较”，保留比较范围与条件，引用输入来源。对于没有唯一通用排名的情况，说明实际比较口径；不偷偷把某一个数据集的结论推广到全部数据集，不把不同实验设置当作同一消融。
- 若输入缺列头、基线、必要对象或数值，仍应按现有流程搜索／阅读；若输入已齐而只差运算，不能仅用“没有新的检索方向”作为拒答理由。相关 gap 决策可使用计算工具，现有准备返回机制随之适配。
- `missing_information` 只记录原问确实缺少的材料及必要限定；“作者没有逐字给出这项排名”本身不是缺失证据。未读内容不能加强成整篇论文不存在。

这些规则在探索、准备和最终正文中保持一致。不给 Q29 写专用比较公式、预置答案或固定 chunk，也不为 Q23 增加必须读指定表格的规则。

### 12.5 最终生成改为自然语言正文和引用标记

目标流程为：**搜索／阅读／可选计算 → 准备事实 → 最终自然语言正文＋引用 → 程序保存和展示**。

1. 探索决策、工具参数和准备结果按现有需要保持结构化。**最终请求使用 `require_json=False`，不提供工具，不再要求模型返回 `action / answer / status / claims / basis / reason / direct_answer / evidence_quotes`。** 论文问题继续先准备；已有纯对话／一般知识分支如触及最终输出，也统一交给正文生成，不借此新增论文直接回答捷径。
2. 复用准备成功请求与响应向最终请求重放的机制，继续传入本次实际保留的原文、工具调用／结果、准备事实与必要对话。替换最终规则，并清理在该请求中仍有效的“必须输出 JSON／AnswerAction”等冲突指令，不能只在旧 JSON 提示后追加一句“请输出正文”。准备响应本身仍可作为结构化历史保留。
3. 来源在首次真实展示正文时取得 `ref=n`，消息中明确给出对应 `[ID:n]`。后续搜索重排、重复读取或新增材料不改变旧编号；准备里的 `citation_ids` 仍可使用已有 chunk ID，不为此重做准备协议。
4. 映射仅来源于实际展示的原文；候选位置、阅读目录、parent ID 和计算结果不能获得引用权限。完整请求裁剪后，只有该次请求仍实际保留的有效原文允许引用；移除正文的编号不复用给其他来源。沿用已有身份和来源范围管理，不增加哈希映射。
5. 程序保存 `answer.text`（保留模型原始正文和标记）、`answer.citations`（按正文顺序记录引用出现位置及其 ref／真实 chunk 身份）、`answer.evidence_sources`（程序提供的原文与元数据）。内部字段由程序生成，运行状态继续由 runtime 设置。**不把整篇正文包装成一条假 `claim` 来满足旧 schema，不再让另一个模型把正文拆回 claims。**
6. 引用标记统一解析一次，解析结果供展示、导出和计数复用；仅确认编号映射、当前已读范围和所选版本，复用现有来源加载与记录。新链路不增加正文／PDF 哈希、重复 PDF 扫描或多层引用校验。已有其他链路的检查不借本次整体重构。
7. 未知或当前不可引用的标记不能静默绑定其他来源；需要修复时沿用现有共享的一次修复额度，修复仍返回正文，不能重新掉回 JSON 修复。空输出、截断及请求失败沿用已有失败处理。普通正文含括号、公式、代码或表格都不作 JSON 解析，不因没有 claims、没有 reason 而拒绝交付。
8. 引用定位通过不证明语义正确。是否覆盖原问、计算是否合理、论文事实是否有必要引用，继续由现有内容评价观察；不增加审核模型、逐句语义验证器或全篇引用强制覆盖关卡。证据不足的范围直接写入正文。

### 12.6 正文消费处一起适配

这不是只改一条提示词。当前多个实际调用点依赖 `claims`，须完成以下直接适配：

| 消费处 | 必要行为 |
|---|---|
| [agent.py](../../paper_assistant/agent.py)、最终提示与记录 | 新 Agent 终态使用正文数据；工具调用与准备仍按各自协议解析，已有失败／用量记录继续保存 |
| [app.py](../../app.py:389) | 展示保存的自然语言及 Markdown，引用标记可查看对应真实来源；保留原有段落、列表、公式和表格，不强制切成“结论 1／2” |
| [agent_export.py](../../paper_assistant/agent_export.py:104)、实际 CLI／下载调用点 | Markdown 与 JSON 导出完整正文和来源，导出不重新生成答案；正文中的引用与页面对应 |
| [conversation.py](../../paper_assistant/conversation.py:10) | 多轮历史提取新正文及对应来源 ID，原文追问仍可定位；不再因没有 claims 把上一轮答案变空。本次不顺带修改三轮／4000 字符的历史额度 |
| [evaluation.py](../../paper_assistant/evaluation.py:69)、[agent_evaluation.py](../../paper_assistant/agent_evaluation.py:156)及本批结果汇总 | 新输出按实际正文与引用出现次数评价；同一引用重复出现需分别计数，来源去重数另计。缺少 claims 不再等于没有答案；无可靠对应项的旧指标标为不适用，不伪造 claim 数 |

`fixed_rag` 和历史已保存的 claims 报告保持可读。消费处优先读新正文，旧记录继续读既有 claims；只在真实兼容入口分支，不建立通用格式迁移层，不批量重写历史产物。本次不把固定 RAG 的生成协议一并改掉。

保留 D2／D3 已完成的原文历史、表格目录和完整请求容量管理；不恢复固定 8192 证据窗口、8000 字符、累计八块或旧页面三请求／整题 120 秒限制。未知模型容量的 8192 回退仍仅用于容量未知场景，不能覆盖当前已配置的 1,048,576。输出长度、单次请求超时、取证额度与上下文容量继续分别管理。

### 12.7 实施后的指定离线验证

**本次只写规划，不执行以下测试或真实调用。** 后续完成实现后，调整并点选以下三个现有方法，使用本地材料及 mock 模型，不发真实聊天／embedding 请求：

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：覆盖实际 `run_javascript` 数值运算、独立运行时及超时错误，模型工具结果进入准备与最终历史；最终只给正文也能交付，身份映射在重排和再次读取后稳定，计算不增加取证次数，旧范围和终止机制继续有效。mock 中验证错误句柄使用现有修复额度，最终正文不经过 JSON 解析；使用通用数据，不放 Q29 的答案。
2. `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`：同一现有方法中覆盖新 Agent 正文显示、引用来源与保存后下载，并检查新正文可进入已有历史提取；旧 claims／fixed_rag 仍能展示。页面重绘和导出不触发模型请求。
3. `scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately`：同一正文多次引用同一来源，按引用出现次数计数，去重来源数与先前修复拦截分开；旧记录口径继续可用，不能用空 claims 把新正文计成空答案。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately
```

实际修改触及上述消费链，因此这些是有依据的跨模块验证；不按模块／目录运行，不为凑数新增测试。仅在失败或另有具体影响时扩大到直接相关的方法；未改且已通过的检查复用。不要另建验证报告、审计器、manifest、哈希或快照。

### 12.8 离线通过后复测 Q23／Q25／Q29，各一次

从 [新十题 input.json](../../artifacts/v3/d3-qa-new-ten-20261028/input.json)按原题号取问题与实际版本，复用第 10.1 节已 ready 的 API 版本；不重新下载、解析或索引。下面仅列开发评价重点，**不能注入业务消息或查询**。

| 原题号 | 原题与 question_id | 版本 | 生成后评价重点 |
|---|---|---|---|
| D3-Q23 | What is the model performance on target language reading comprehension?；`37be0d479480211291e068d0d3823ad0c13321d3` | R2：`local_7ae5be87fd2a43aaa38f84c9dad1fd70 / r_a9023725da88cf1a` | 主要目标语言数值是否取得并回答；目录可达不等于已读，英语测试分数不能替代 Chinese／Korean 的主要结果 |
| D3-Q25 | How much does their model outperform existing models?；`de5b6c25e35b3a6c5e40e350fc5e52c160b33490` | R3：`local_0f9f9bf444a043b89195a40ff08f923c / r_189ff4e8823117cd` | 首先是否成功交付正文及引用，其次是否真正回答主要性能增益与比较基线；不能只因去掉 JSON 后能输出就判内容通过 |
| D3-Q29 | Which component is the least impactful?；`2858620e0498db2f2224bfbed5263432f0570832` | R5：`local_c478c4244d854f1ca16394c147d25534 / r_b1ddfb5d02f59522` | 已读消融数值是否转化成有口径、有来源的比较结论；区分结构组件与迭代次数，记录是否自然调用计算工具，不强迫调用 |

每题通过 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])` 完整执行一次，三题独立新会话。使用新实现及其实际提示版本；保留 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次请求 30 秒、五步和五次取证，以及原有共享重试／修复额度。新增计算执行边界按第 12.3 节，与模型请求超时分开。

只传原问、所选实际版本与正常完整回答要求，不传参考答案、期望组件、差值算法、表号、chunk、工具脚本或动作顺序；不以 QASPER full_text 替代检索。模型自行决定取证、计算与准备。未使用计算工具、未耗尽额度、回答不完整或运行失败，均不因此补跑。

本轮目录 `artifacts/v3/d3-prose-compute-rerun-20261028/`，普通 `input.json/results.json`；会话／提交 ID 使用 `d3-prose-compute-20261028-q23/q25/q29`。复用现有顺序运行入口，只需本轮窄调度，不建设新评测框架。沿用现有尝试状态，已有本轮尝试不重复，只接续未尝试题。完整原生日志继续保存到 `archive/run_logs/d9/`，结果只保存路径与简短评价，不复制第二套工具正文。

生成后再用实际入库原文与官方参考作内容评价，分别记录通过／部分通过／未完成及运行失败。三题旧结果作同题基线，不重算历史十题，不用三题样本声称总体准确率提高。记录模型聊天、计算次数及耗时、搜索／阅读、查询 embedding、重排、共享重试／修复与真实 token 用量；计算不算模型请求或新证据来源。共享服务故障时保留实际结果及用量，不反复连通性探测。

完成这三题及第 13 节结果记录后结束，不自动修 Q23、不追加新十题、不加预算、不引入 judge 或 fixed_rag 对比。正常复测属于后续执行此计划的任务范围，本次文档修改不发任何付费请求。

## 13. 本轮实施与三题复测结果（2026-10-28）

### 13.1 实际改动

- 新增 [js_runtime.py](../../paper_assistant/js_runtime.py)：当前 `.venv` Python 3.11.5、`mini-racer==0.12.4`（V8 12.6.228.18），独立 `MiniRacer`、输入 64 KiB、stdout 1 MiB、5 秒、64 MiB 硬内存上限；只捕获 `console.log`，不注入文件、网络、数据库、环境、Python 对象或 Node 模块；超限返回 `javascript_stdout_limit` 错误，不回退 shell／`eval/exec`。
- [agent_actions.py](../../paper_assistant/agent_actions.py) 增加 `run_javascript` 原生工具定义与参数校验；[agent.py](../../paper_assistant/agent.py) 在现有自主循环中执行并把结果写入既有 `tool_call_id` 观察／历史。计算调用不增加 `evidence_calls_used`，仍按现有轮次消耗自主步骤；取证额度耗尽时仍可单独调用计算，终止阶段不提供工具。
- 最终生成改为正文：[agent_prompt.py](../../paper_assistant/agent_prompt.py) 新增自然语言最终系统提示和正文修复提示，`require_json=False`、不提供工具；`AUTONOMOUS_PROMPT_VERSION`／`PROSE_FINAL_PROMPT_VERSION` 分别更新为 `v2.22-compute-prose-final-v1`／`v3.0-prose-citations-v1`。最终请求重放准备消息与响应，但最终 payload 只含问题、版本、来源和缺口，不再含 `action_contracts`／`allowed_actions`。
- [citations.py](../../paper_assistant/citations.py)、[prose.py](../../paper_assistant/prose.py) 与 [source_scope.py](../../paper_assistant/source_scope.py) 统一解析一次 `[ID:n]`，按实际保留原文建立稳定 ref；程序生成 `answer.text`、`answer.citations`（含出现位置）、`answer.evidence_refs`、`answer.evidence_sources`，不再生成 claims。未知／不可用 ref 使用现有一次修复额度，修复仍为正文。
- 消费处：[app.py](../../app.py) 展示正文和引用来源；[agent_export.py](../../paper_assistant/agent_export.py)、[answer_export.py](../../paper_assistant/answer_export.py) 保存／导出正文和有序引用；[conversation.py](../../paper_assistant/conversation.py) 提取新正文与 citation_ids；[evaluation.py](../../paper_assistant/evaluation.py)、[agent_evaluation.py](../../paper_assistant/agent_evaluation.py) 按正文引用出现次数计分、去重来源另计，旧 claims 指标对新正文标为不适用。`requirements.txt` 只固定 `mini-racer==0.12.4`，未升级其他依赖。

### 13.2 指定离线验证

三个指定现有方法合并运行 **3 tests OK、36.482 秒**，全部本地材料／mock，无真实聊天或 embedding 请求：

- `test_actual_cores_citations_closed_resources_and_stage_records`：实际本地 JS 数值运算、独立运行时、5 秒超时、1 MiB 输出上限；计算历史进入准备与最终；最终正文不经过 JSON 解析；未知 ref 用共享一次修复后交付；目录／父块引用范围和结构化旧路径继续有效。
- `test_two_modes_five_terminal_states_and_full_citations`：新 Agent 正文在页面显示、引用来源可展开、下载／Markdown 保存和会话历史提取；旧 claims 与 `fixed_rag` 仍可读；页面重绘不触发模型请求。
- `test_published_duplicate_citations_and_prior_intercepts_are_counted_separately`：同一来源多次引用按 3 次出现计数、去重来源 2 个，旧 claims 的 2/2 口径继续可用；新正文不伪造 claim 数。

### 13.3 三题真实复测

每题完整执行一次，`mode="agent"`、`library_mode=True`、空历史；实际配置为 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证；最终提示 `v3.0-prose-citations-v1`，JS `mini-racer-0.12.4`。三题均 1/1 completed、answered；内容 **2 通过、1 部分通过、0 运行失败**。

| 题号 | 结果 | 正文与内容评价 |
|---|---|---|
| D3-Q23 | 通过 | 正文已交付，12 个引用出现／6 个来源；从 Table 2 取得目标语言主结果（En→Zh 63.3／78.8、En→Kr 49.2／69.3，同语言与翻译设置及 Zh→Kr／Kr→Zh），并说明 Table 1 具体行未展示。未调用计算工具，非必需。 |
| D3-Q25 | 通过 | 正文已交付，19 个引用出现／7 个来源；真正回答主要性能比较：给出 arXiv／Pubmed 的 attentive／concat 与 SummaRuNNer、Cheng & Lapata、LexRank、Discourse-aware 的 ROUGE／METEOR 差值，并保留 ROUGE-L 落后等限定。模型成功调用 `run_javascript` 一次（385 字符、0.096 秒）；一次 `invalid_json` format 修复后最终正文正常。 |
| D3-Q29 | 部分通过 | 正文已交付，9 个引用出现／4 个来源；已读 Table 3 并形成有口径的比较，但算术有误：按表中数值 no-master-node-skip 的平均绝对变化约 0.23、undirected 约 0.27，正文写 0.19／0.30；且以平均绝对变化选 no-master-node-skip，未说明与官方参考按最大绝对差 0.33 指向 undirected 的口径差异。未调用计算工具；问题在比较口径与算术，不在引用定位。 |

同题旧结果比较：Q23 由部分通过变为取得目标语言主结果；Q25 由运行失败变为正文成功交付并回答主要比较；Q29 仍为部分通过，但已从无正文交付变为有正文、已读表和可评价的比较。只记录这三道公开 dev 原题，不重算旧十题，不声称总体准确率或稳定速度提升。

### 13.4 成本与产物

三题问答合计 18 次聊天请求、492,289 tokens、报告耗时 129.986 秒；查询 embedding 4 次、重排 4 次；0 网络重试、1 修复；11 个自主步骤、9 次取证调用、4 轮搜索；40 个引用出现／17 个去重来源；正文合计 6,032 字符；JS 调用 1 次、计算耗时 0.096 秒（不计模型请求或论文来源）。本轮未重新入库、下载、OCR、解析或索引。

**产物：**[input.json](../../artifacts/v3/d3-prose-compute-rerun-20261028/input.json)、[results.json](../../artifacts/v3/d3-prose-compute-rerun-20261028/results.json)；逐题原生 [Q23 JSON](../../archive/run_logs/d9/agent_20261028_043607_712761_596b17a06619.json)／[Q25 JSON](../../archive/run_logs/d9/agent_20261028_043732_004549_c8e76c05c570.json)／[Q29 JSON](../../archive/run_logs/d9/agent_20261028_043823_200977_657aaed5b9b1.json)，完整 Markdown 同目录。第 10 节十题历史、第 7.1 节 Q15 和 D2 记录保留。

## 14. 给 DeepSeek 的本轮实施与三题复测提示词

```text
请在 D:/course/paper-research-assistant 读取 AGENTS.md、docs/v3/d3-plan.md 第10、12～13节，实施第12节方案并完成其中指定的三题复测。本轮执行依据是第12节；第8、11节是已经完成的历史任务，不重新跑旧十题。参考 E:/project/ragflow 的实际 Go Agentic RAG，能沿用的行为直接沿用，必要时适配本项目 Python。遵守 Stop That Shit，只做本轮及其必要消费处改动，不添加冗余校验、哈希、快照、manifest、审计或额外模型。

第一项：增加可选原生工具 run_javascript，参数 code，console.log 为结果。参考 ragflow/internal/agentic_rag/tool_run_javascript.go，主模型只对已经取得的数据做算术、排序、计数或聚合，不用工具打印常量结论，不将计算当检索或新论文证据。采用 mini-racer（Python 模块 py_mini_racer），在当前 Windows/Python 环境安装并固定实际兼容版本，不升级无关依赖，不把 Go 的 goja 或 Node 直接塞进 Python。每次独立运行时，使用其自身执行和内存限制；输入64KiB、stdout 1MiB、单次执行5秒，达到输出上限返回错误而非完整成功结果。不暴露文件、网络、数据库、环境、Python桥接或Node模块。不要新增语法黑名单扫描器、通用沙箱平台，不能回退系统shell或Python eval/exec。沿用已有tool_call_id、工具观察、历史和错误返回。计算按现有轮次消耗自主步骤，不计五次搜索／阅读取证额度，不新增自主步骤或单独计算总额度；工具可用性分开控制，现有终止阶段只收尾。依赖或实际执行受阻时如实记录，不静默把计算工具做成空壳。

第二项：Agent最终只生成自然语言正文＋[ID:n]，参照ragflow/conf/agentic_rag.yaml的最终正文规则。最终require_json=False，不提供工具，不再要求action/answer/status/claims/basis/reason/direct_answer/evidence_quotes。探索决策、工具参数和prepare_answer继续按各自需要结构化；论文问答必须保留准备阶段，不引入compiled claims直接回答、decision_judge或额外模型。继续重放准备请求和响应、实际已读原文及工具调用／结果；清理最终请求中仍有效的JSON／AnswerAction冲突指令，不能只在旧JSON提示末尾加一句输出正文。

引用在真实正文首次展示时分配稳定ref，重排／重复读取不换号。用已有paper_id/parse_revision/chunk_id建立运行内映射，不照搬RAGFlow ServeText中的正文哈希去重。候选位置、目录、parent和计算结果不获引用权限；只有当前实际请求仍保留的原文可引用，删掉正文后旧编号不分给别的来源。准备citation_ids仍用已有chunk ID。程序保存answer.text原文、answer.citations有序出现位置与真实来源身份、answer.evidence_sources及原有runtime状态，不让模型生成这些内部字段，不把正文伪装成一条claim，也不另调模型拆claims。引用标记只统一解析和映射一次供消费者复用，沿用已有来源与范围信息；不新增正文/PDF哈希或重复PDF扫描。未知／失效标记沿用现有共享一次修复，修复也输出正文，不掉回JSON；空输出、截断和请求故障沿用原有处理，不扩修复额度。不要增加逐句语义验证、全文引用覆盖判定器或审核模型。

同步调整充分性表述：facts仍忠实提取原文与短引句，算出的比较不冒充作者原话。回答所需基线、对象、指标、单位和数值齐全时，可通过计算给出结果，不能只因作者没写出逐字排名就判缺证据；探索可先调用计算工具，简单运算也允许最终模型完成，不要求每题调用。最终说明“根据数值计算／比较”的范围和口径，引用实际输入来源；缺真正输入才继续搜索／阅读，输入齐而只缺运算不能以没有新检索方向拒答。探索、准备、gap决策、最终规则保持这一边界一致，必要gap阶段可调用计算。不给Q29写专用脚本、预设答案或固定chunk，不给Q23添加必须读表的规则。

完成所有实际消费者适配：app.py的新正文／Markdown和引用展示、agent_export.py及实际CLI/下载保存、conversation.py的历史正文与引用追问、evaluation.py/agent_evaluation.py及本轮汇总的正文评价和引用出现次数。同一来源多次引用分别计数，去重来源数另计；无对应项的旧claim指标标不适用，不伪造claim数。旧claims报告与fixed_rag仍可读，只在必要入口兼容，不迁移历史文件、不改fixed_rag生成协议。保留三轮/4000字符历史额度，本次只避免新正文因无claims而丢失，不顺带改历史策略。

保留已完成的原文历史、表格目录、模型完整请求容量管理和已有来源范围行为，不恢复8192固定证据窗口、8000字符、累计八块或旧页面三次请求／整题120秒上限。未知模型容量8192回退可保留，不能覆盖已配置1048576；上下文、输出、超时和执行额度分开。模型维持deepseek-flash、temperature 0.2、4096输出、单次30秒、五步／五次取证及原共享重试／修复，不以加预算解决问题。

实现后按第12.7节只点选三个现有方法：scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records；scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately。调整这些方法覆盖真实本地JS执行、原文和计算历史衔接、自然语言最终交付、稳定引用／原额度修复、页面／下载／历史和新旧引用计数。mock用通用数据，不嵌入复测答案；离线不发真实聊天或embedding。只有失败或有具体跨模块影响才扩大到直接相关方法，不跑整模块／目录／全量；已通过且未变的结果复用，不另建验证报告或检查框架。

离线通过后，从artifacts/v3/d3-qa-new-ten-20261028/input.json按原题号取D3-Q23、Q25、Q29，保留原问及实际paper_id/parse_revision，复用第10.1节R2/R3/R5 ready版本，不重新下载/OCR/解析/索引。三题各一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话，工具使用完全由模型决定。不注入参考答案、官方gold、开发观察、预期比较口径、组件名、表号、chunk、代码或动作顺序，不用QASPER full_text绕过检索。真实调用仅包括三题正常流程、查询embedding/重排和原额度内重试修复；不发额外连通性、judge、fixed_rag或固定证据实验请求。

使用artifacts/v3/d3-prose-compute-rerun-20261028/的普通input.json/results.json，会话/提交ID为d3-prose-compute-20261028-q23、-q25、-q29；沿用现有尝试状态与顺序入口，已有本轮尝试不重跑，只接续未尝试题。完整JSON/Markdown由现有runtime保存到archive/run_logs/d9/，汇总只链接原生日志。内容部分通过、失败、未调用计算工具或未耗尽额度均不补跑，不追加追问，不在批次中改提示再抽样。

生成后按实际原文与官方参考评价，开发预期仅此时使用：Q23看是否取得目标语言的核心数值；Q25分开评价“正文成功交付”和“真正回答主要性能比较”；Q29看已取得的消融数值是否形成有口径、有来源的比较。不能把HTTP成功、引用定位通过或去掉JSON后能输出当成内容通过。记录实际模型/提示/JS运行时版本、三题结果、工具使用与计算耗时、模型tokens、搜索/阅读、查询embedding、重排、共享重试/修复和成本；计算不算新模型请求或论文来源。与旧三题同题比较即可，不重算旧十题或声称总体准确率提高。

在D3第13节简要写实际改动、指定离线结果、三题评价和普通产物链接，保留全部历史，不另建报告。无法完成的部分如实记录，不宣称完成。完成本轮后结束，不自动修Q23、开始新十题、增加预算或加入其他流程，保持本轮提示词位于文末。
```

## 15. 对齐 RAGFlow 的可选计算策略与 Q29 单题复测

制定日期：2026-10-28。用户要求本轮直接实施并复测，历史计划和结果保留。本节取代第 12 节“最终阶段不提供计算工具”的限制，其他范围不扩大。

1. 采用本地 RAGFlow [run_javascript 的可选策略](E:/project/ragflow/internal/agentic_rag/tool_run_javascript.go:38)及[保留数值精度规则](E:/project/ragflow/conf/agentic_rag.yaml:50)：不强制每次算术调用工具，不预设 Q29 的组件、比较口径或计算脚本；去掉本项目额外的“将简单算术留给最终回答”引导。
2. 最终正文生成也可原生调用已有 `run_javascript`，工具结果继续进入同一消息历史，再由模型输出正文和引用。只开放计算，不重开搜索／阅读；复用已有执行器和错误观察，不新增模型、审核器、哈希或数值扫描器。
3. 最终计算轮次消耗原有剩余自主步骤，不计取证次数；到达五步上限后只收尾，引用／格式修复沿用现有共享一次额度，不提供额外工具。工具定义、调用和结果计入完整请求容量。准备事实仍按原流程，最终格式保持自然语言。
4. 离线仅调整并运行现有 `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`，覆盖最终计算、结果重放、计算错误返回和步数触顶收尾，复用其既有来源与修复场景；不运行整个模块／目录或重复其他已通过检查。
5. 离线通过后，从上一批 input 中取 D3-Q29 原问、原版本，独立新会话完整运行一次。复用 R5 的 ready 版本，不重新入库；模型、五步／五次取证、输出及超时配置保持原值。未调用工具、回答错误或失败均不补跑，参考答案只用于生成后评价。

本轮普通产物为 `artifacts/v3/d3-final-calculation-q29-20261028/input.json/results.json`；会话／提交 ID 为 `d3-final-calculation-20261028-q29`。完整原生日志仍保存到 `archive/run_logs/d9/`。结果应区分算术正确性、比较口径及引用，不因平均值与最大值口径不同就直接判错。只记录本题真实调用和用量，不额外生成验证报告或提示词交接任务。

## 16. 最终阶段可选计算实施与 Q29 结果（2026-10-28）

本轮已完成第 15 节计划。计算工具仍为可选；未加入强制算术调用、数值审核模型、哈希或新校验层。

### 16.1 实际改动与离线验证

- [agent.py](../../paper_assistant/agent.py) 的最终正文请求在仍有自主步骤时，只提供 `run_javascript`，`tool_choice="auto"`；原生调用、输出／错误加入同一次最终消息历史后继续生成。探索和最终复用同一个计算执行函数，不提供新的搜索／阅读入口。
- 每轮最终计算消耗一个原有剩余自主步骤，不增加取证次数；耗尽五步后不再提供工具，只收尾。引用／格式修复仍共享一次额度且不提供工具。工具定义与结果继续进入完整请求容量管理。
- [agent_prompt.py](../../paper_assistant/agent_prompt.py) 去掉“将简单算术留给最终回答”的额外引导，保留 RAGFlow 的可选使用、已有输入、保留精度与不得打印常量结论的规则。提示版本更新为 `v2.23-optional-final-calculation-v1`／`v3.1-optional-final-calculation-v1`。准备协议、最终自然语言格式和所选版本范围不变。
- 只调整并执行指定现有方法 `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`，**1 test OK，21.837 秒**。新增该方法内的最终计算成功、错误回传、剩余步数耗尽收尾场景；其原有引用修复、来源、导出和固定模式场景一并通过。全部使用本地材料／mock，不发离线真实请求；未重复运行其他方法。

### 16.2 Q29 一次真实复测

复用 R5 的 `local_c478c4244d854f1ca16394c147d25534 / r_b1ddfb5d02f59522`，原问仍为 `Which component is the least impactful?`，空历史、独立新会话、`mode="agent"`、`library_mode=True`。保持原模型和请求／取证参数，没有重新入库或向业务输入注入参考答案、比较口径或代码。

结果：**completed／answered，按明确的平均绝对变化口径核心通过，算术错误未重现**。

- 模型先搜索并读取消融正文，准备后在 **`prepared_final_decision`** 自主调用 `run_javascript` 一次，然后生成自然语言正文。工具耗时 **0.026363 秒**、stdout **685 字符**，执行成功；最后一次请求保留这次调用及实际结果。
- 工具与正文对应的变化量：去掉 master-node skip connection 的绝对差为 `0.14 / 0.38 / 0.18`，均值 **0.2333**；undirected 的绝对差为 `0.28 / 0.19 / 0.33`，均值 **0.2667**。正文分别写约 **0.23／0.27**，上轮 **0.19／0.30** 的错误没有重现。
- 正文按平均绝对变化选择 master-node skip connection，并区分了结构组件变化与 3MP 等迭代次数变化。官方参考按最大绝对变化选择 undirected（0.33 小于 0.38）；原问未规定聚合方式，因此记录为**比较口径不同，不据隐藏参考口径直接判算错**。
- 仍有轻微范围表达问题：开头和结尾将“当前材料未见明确排名”说成“论文没有明确排名”。本轮只记录，不继续改提示或补跑。

实际用量：**5 次聊天、100,365 tokens、报告耗时 26.141 秒**；查询 embedding **1 次**、重排 **1 次**，网络重试／修复 **0／0**；自主步骤 **3／5**、取证 **2／5**，计算不计取证；**11 个引用出现、4 个来源**，引用定位 valid。一次同题复测只说明本次行为，不能据此证明可选策略必然使用工具或稳定消除算术错误。

产物：[input.json](../../artifacts/v3/d3-final-calculation-q29-20261028/input.json)、[results.json](../../artifacts/v3/d3-final-calculation-q29-20261028/results.json)；原生 [Q29 JSON](../../archive/run_logs/d9/agent_20261028_045927_770618_1af006b9541f.json)／[Q29 Markdown](../../archive/run_logs/d9/agent_20261028_045927_770618_1af006b9541f.md)。窄入口为 `tmp/d3_final_calculation_q29_run.py`，复用上一批的输入与运行辅助函数，没有启动旧三题 main。单题已结束，没有追加付费请求或重算历史成绩。

## 17. 下一批新十题 QA 测试规划：D3-Q31～D3-Q40（2026-10-28）

状态：**已完成五篇准备与 Q31～Q40 十题复测**；实际准备、逐题评价、用量和产物见第 17.7 节。第 1～16 节全部保留为历史；第 18 节提示词位于文末。

### 17.1 目的与范围

固定选择本地 [QASPER 官方 dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json) 中五篇论文、每篇两道官方原题，编号 **D3-Q31～D3-Q40**。五篇论文未出现在已有 `artifacts/v3/*/input.json` 的历史批次中；所选十题的 question_id 和原问已与这些批次及 `eval/qasper/*/sample.json` 对照，无重复。论文代号续用 **R6～R10**，不与第 9 节 R1～R5 混用。

本批观察新论文上的核心覆盖、并列项、实验结果归属、是非判断及指标定义，并记录自然语言交付、引用和可选计算的实际表现。它是公开 dev 的定向开发观察，不是随机抽样或隐藏 test 成绩。只测试现有实现，不修改业务代码、业务提示词、解析／检索策略或预算；不把旧题复测并入这十道新题。

本次仅追加规划，不下载／入库论文、不发聊天、embedding 或重排请求。执行本批时，必要的新论文准备与十题正常问答属于本批范围。

### 17.2 五篇论文及固定 PDF 版本

以下题名、arXiv ID 和公开版本已核对，执行时固定使用表中版本，不自动跟随最新版。QASPER paper_id 用于定位官方题目，实际问答必须绑定导入返回的本地 `paper_id / parse_revision`，不预造本地身份。

| 代号 | QASPER paper_id | 论文／所选 PDF 题名 | 固定 PDF |
|---|---|---|---|
| R6 | `1704.06194` | Improved Neural Relation Detection for Knowledge Base Question Answering | [arXiv v1](https://arxiv.org/pdf/1704.06194v1) |
| R7 | `1609.00425` | Identifying Dogmatism in Social Media: Signals and Models | [arXiv v1](https://arxiv.org/pdf/1609.00425v1) |
| R8 | `2004.03354` | Inexpensive Domain Adaptation of Pretrained Language Models: Case Studies on Biomedical NER and Covid-19 QA | [arXiv v2](https://arxiv.org/pdf/2004.03354v2) |
| R9 | `2002.08795` | How To Avoid Being Eaten By a Grue: Exploration Strategies for Text-Adventure Agents | [arXiv v1](https://arxiv.org/pdf/2002.08795v1) |
| R10 | `1912.08960` | Going Beneath the Surface: Evaluating Image Captioning for Grammaticality, Truthfulness and Diversity | [arXiv v1](https://arxiv.org/pdf/1912.08960v1) |

R8 的 QASPER 元数据仍使用旧题名 `Inexpensive Domain Adaptation of Pretrained Language Models: A Case Study on Biomedical Named Entity Recognition`，但保存的正文已经包含 Covid-19 QA 实验。已核对 [v1 正文](https://arxiv.org/pdf/2004.03354v1) 仅有早期 NER 内容，[v2 正文](https://arxiv.org/pdf/2004.03354v2) 已包含相应新增实验，因此本批固定 v2，并分别记录数据集题名与实际 PDF 题名；不因题名不同将它误认成另一篇论文，也不在运行中换版追参考。

### 17.3 十题与固定执行顺序

下表只列官方原题、身份和事后观察重点。执行时从官方 JSON 按 `paper_id + question_id` 读取原始 `question`，保留大小写、拼写、语法及空白，不从表格重写或翻译。观察重点不传入前置规划、模型消息、检索参数或工具指令。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q31 | R6 | On which benchmarks they achieve the state of the art? | `9ee07edc371e014df686ced4fb0c3a7b9ce3d5dc` | 所问基准是否完整列出，任务与实验范围对应；不把局部结果扩大为所有基准领先 |
| D3-Q32 | R6 | What is te core component for KBQA? | `c0e341c4d2253eb42c8840381b082aae274eddad` | 对应本文所说的核心组件及作用，区分一般 KBQA 目标与本文具体实现；保留原题 te 拼写 |
| D3-Q33 | R7 | what are the topics pulled from Reddit? | `b6ae8e10c6a0d34c834f18f66ab730b670fb528c` | 采样主题及数据来源范围完整，区分标注语料与后续大规模应用语料 |
| D3-Q34 | R7 | What predictive model do they build? | `a87a009c242d57c51fc94fe312af5e02070f898b` | 回答具体模型和必要特征设置，不以泛称机器学习模型代替论文方法 |
| D3-Q35 | R8 | Which eight NER tasks did they evaluate on? | `1d3e914d0890fc09311a70de0b20974bf7f0c9fe` | 八项任务是否齐全；同一数据集的不同实体任务不能错误合并或重复计数 |
| D3-Q36 | R8 | What in-domain text did they use? | `16535db1d73a9373ffe9d6eedaa2369cefd91ac4` | 语料与不同实验用途对应；按所选版本实际正文评价，不只依赖旧题名限定范围 |
| D3-Q37 | R9 | What are the results from these proposed strategies? | `c5abe97625b9e1c8de8208e15d59c704a597b88c` | 主要策略、结果数值和评价指标对应，区分得分、瓶颈现象与比较结论 |
| D3-Q38 | R9 | What are the two new strategies? | `88ab7811662157680144ed3fdd00939e36552672` | 两种策略及核心差别均有交代，名称与机制对应，不把基线误列为新策略 |
| D3-Q39 | R10 | Are the images from a specific domain? | `50e80cfa84200717921840fddcf3b051a9216ad8` | 给出明确判断及其实际材料依据；领域范围说明与图像来源对应，不扩成全文排除结论 |
| D3-Q40 | R10 | How is diversity measured? | `509af1f11bd6f3db59284258e18fdfebe86cae47` | 按本文解释指标及必要分子／分母、统计对象和条件，不套用通用多样性指标 |

十题全部使用独立新会话。同论文第二题不带入第一题的答案、工具历史或准备事实；官方参考、gold evidence 和 `full_text` 不作为业务输入或检索替代材料。

### 17.4 允许的新论文入库与复用

执行时可下载上述固定 PDF 到 `eval/qasper/pdfs/`，通过现有 `import_runtime.import_pdf` 默认 `parser="mineru-api"` 入口入库，沿用当前 VLM／全文 OCR／公式／表格配置、分块、SQLite 和向量索引流程。必要下载、官方解析、索引 embedding 属于本批准备；不另外发连通性测试请求。

- 相同固定 PDF、相同 API 解析方案已有 ready 结果时直接复用；已有相同方案解析 bundle 时使用现有导入复用能力，不重复上传。不用不同版本或旧 Standard 解析结果冒充本批版本。
- 以实际 ready 返回绑定 R6～R10 各自两题，保存公开来源、固定 PDF 版本、实际题名、解析配置及本地版本配对；保持当前索引 profile，不为本批重建其他论文索引。
- 单篇准备失败时，保留对应两题未执行及原因，其他独立论文可继续；共享服务故障阻断后续时保存已有结果和实际用量后停止。不自动换解析器、换论文或换版本。

本批无业务行为修改，不跑离线测试、语法扫描或全量回归；第 13、16 节已通过且对应代码未变的验证直接复用。不为题单、来源或 ready 状态增加新的校验器、manifest、哈希或审计文件。

### 17.5 执行方式、现有配置与产物

按 Q31→Q40 固定顺序，每题只运行一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`。只传官方原问、实际所选版本配对及普通完整回答要求。模型自主选择搜索、`read_context`、准备与可选 `run_javascript`；最终输出沿用自然语言正文和真实引用。

保持第 16 节当前实现和参数：`deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次请求 30 秒、五步／五次取证，以及既有网络重试一次／共享修复一次额度。当前提示版本为 `v2.23-optional-final-calculation-v1`／`v3.1-optional-final-calculation-v1`，执行时照实保存实际版本；embedding／重排继续沿用现有 profile。计算保持可选，最终阶段仅可使用原有剩余自主步数计算，不重开搜索／阅读，不增加取证额度。保留表格目录、已读原文历史和完整请求容量管理，不恢复旧证据截断或旧整题超时限制。

本批使用新目录 `artifacts/v3/d3-qa-next-ten-20261028/`，与 Q21～Q30 的 `d3-qa-new-ten-20261028/` 分开：

- `input.json` 保存官方来源、固定题号／question_id／原问、五篇实际版本配对、公开配置及提示／JS 运行时版本，不保存 gold 为业务输入。
- `results.json` 保存各题尝试状态、停止原因、原生日志路径、实际用量及简短内容评价；入库成本与问答成本、索引 embedding 与查询 embedding 分开记录。
- 完整逐题 JSON／Markdown 由现有 runtime 写入 `archive/run_logs/d9/`，汇总只链接原生日志，不另复制一套完整请求历史。
- 会话／提交 ID 使用 `d3-qa-next-ten-20261028-q31` 至 `d3-qa-next-ten-20261028-q40`。先保存尝试状态再请求；本批已有尝试不重复运行，只接续未尝试题。失败、中断、部分回答或未调用计算工具均不自动重开，不追加追问或替代题。

准备可复用 `tmp/d3_prepare_new_five.py` 的方式，顺序调度及自然语言统计可复用 `tmp/d3_prose_compute_run.py`、`tmp/d3_final_calculation_q29_run.py` 的现有能力；必要时仅新增本批窄入口，如 `tmp/d3_prepare_next_five.py`、`tmp/d3_qa_next_ten_run.py`。替换为本批固定清单、stage、目录和 ID，不运行旧 main，不把 Q23／Q25／Q29 或 Q21～Q30 重新提交。新正文按 `answer.text / citations / evidence_sources` 评价，不沿用旧十题把缺失 claims 记为零的口径。

真实调用仅包括必要入库、十题正常前置规划／Agent／准备／最终、查询 embedding、可选重排和原额度内重试／修复。不运行 fixed_rag、双模式评分、独立 judge、固定证据实验或额外模型请求，不在批次中修改提示后补跑。

### 17.6 事后评价与记录口径

回答生成后结合实际展示原文与官方各份参考作 AI 辅助内容评价，记通过／部分通过／内容未交付，运行失败和未执行单列。HTTP 成功、answered 或引用定位 valid 均不直接等于内容通过；原问存在歧义或参考标注不一致时，以实际版本原文说明判断依据，不只按某一条隐藏口径判错。

- 按第 17.3 节原问检查核心对象、必要并列项和范围。枚举题不能只列示例；是非题需有实际依据；方法和指标定义需保留必要主体、变量或条件，不额外要求未问的完整推导。
- 数值须与策略／数据集／指标／设置对应，区分原文报告值和自行计算的结果。发生比较时记录实际口径和算术是否正确；不强制调用 JS，也不因没有调用而单独扣分。JS 输出不作为论文来源，引用应指向实际输入原文。
- 观察材料取得后是否贯穿准备和最终、必要表头与行块是否共同支持结论。搜索已提供完整原文即可作答，不要求重复阅读；目录和表题只定位。局部未读到不能强化为整篇论文没有报告。
- 缺核心内容时沿现有记录区分未取得材料、取得后未利用、准备遗漏或最终遗漏；若有具体取证方向和剩余额度却收尾，记录原记录依据。材料充分时正常停止，不因工具次数少或未触发容量裁剪补跑。
- 按新自然语言格式记录引用出现次数及按真实来源身份去重的来源数；同来源重复引用分别计出现次数。无 claims 的旧指标标不适用，不伪造主张数或用零作为失败依据。

逐题保存实际模型／提示／JS 运行时版本、状态／停止原因、聊天请求与 tokens、耗时、搜索／阅读、查询 embedding、重排、网络重试／共享修复、计算调用及本地计算耗时；费用沿用现有用量与可用计费信息，缺失项如实标明。JS 本地执行本身不算独立模型请求，承接工具结果的聊天继续计入实际聊天用量，不为统计另发请求。

只汇总本批十道公开 dev 原题的结果和重复出现的具体问题，不重算历史批次，不据不同题目宣称准确率提高、稳定消除算术错误或稳定提速。

### 17.7 执行结果（2026-10-28）

**五篇准备：**五篇固定 PDF 均无现成同方案 ready 版本，已下载到 `eval/qasper/pdfs/` 并通过现有 `import_runtime.import_pdf` 默认 `mineru-api` 入口入库；沿用 VLM／全文 OCR／公式／表格识别和当前索引 profile，未改解析、分块或索引代码。全部 `ready`：

| 代号 | QASPER paper_id | 实际 paper_id / parse_revision | chunks | API batch |
|---|---|---|---|---|
| R6 | 1704.06194 | `local_b58f7bd4e2e24437a5db38d3221b64b6` / `r_da0cfdd5b85019c7` | 42 | `0053866c-8bef-4dab-98d2-cabbb0de9368` |
| R7 | 1609.00425 | `local_12f0a83a48ad49769c29b7d5b4013f77` / `r_b6627f0a7134f66f` | 33 | `3892e780-6778-4fc4-8d0a-fa15646e54dc` |
| R8 | 2004.03354 | `local_08e9c60d291f4f8e864566661b8b448f` / `r_2a53c3828557a0c7` | 41 | `8086466f-2b66-4153-9fa6-fa2dae733220` |
| R9 | 2002.08795 | `local_6da29ab4fab34c76bf0cd7c85e49f9c1` / `r_5c9e4f5fc27b27c5` | 19 | `9d23faa9-8277-41f3-bfa9-4e726ccf884b` |
| R10 | 1912.08960 | `local_7c2d091cf1744d558f8b3882d7442ea7` / `r_e077672b02ee2c89` | 30 | `7c44725b-1e39-4967-8653-164303163d36` |

R8 数据集题名仍为旧 NER 题名，实际 PDF v2 题名为 “Inexpensive Domain Adaptation of Pretrained Language Models: Case Studies on Biomedical NER and Covid-19 QA”；本批按规划使用含新增实验的 v2，input 同时保存 `dataset_title` 与 `pdf_title`。入库合计 165 chunks、19 次索引 embedding、196.658 秒；与问答成本分开记录。

**逐题结果：**十题各一次，`mode="agent"`、`library_mode=True`、空历史；实际配置 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证；提示 `v2.23-optional-final-calculation-v1`／`v3.1-optional-final-calculation-v1`，JS `mini-racer-0.12.4`（V8 12.6.228.18）。结果：**10/10 completed、answered；内容 9 通过、1 部分通过、0 运行失败／未执行**。本批没有模型调用 `run_javascript`。

| 题号 | 结果 | 内容评价 |
|---|---|---|
| D3-Q31 | 通过 | 回答 SimpleQuestions 与 WebQSP，并区分 SimpleQuestions 超过先前 SOTA、WebQSP 与 STAGG 的 63.9 相当而非超过；保留单／多检测器设置。 |
| D3-Q32 | 通过 | 明确 relation detection 是 KBQA 核心组件，并说明实体链接、关系检测和约束检测在本文系统中的位置与作用；未停在一股 KBQA 定义。 |
| D3-Q33 | 通过 | 列出训练抽样 politics、business、science、AskReddit 及额外 Reddit frontpage 帖子；区分标注样本与更广泛讨论示例。 |
| D3-Q34 | 通过 | 回答统计预测分类器及 logistic regression 模型，说明 BOW／SENT／LING 及组合特征、TF-IDF、L2 惩罚和两类标注设置。 |
| D3-Q35 | 通过 | 完整列出八项 NER 任务：BC5CDR-disease、NCBI-disease、BC5CDR-chem、BC4CHEMD、BC2GM、JNLPBA、LINNAEUS、Species-800，对应 Table 2 的 (1)–(8)。 |
| D3-Q36 | 通过 | 回答 PubMed+PMC（BioBERTv1.0 数据）与 CORD-19，并区分 CORD-19 only 与 CORD-19+PubMed+PMC；同时说明 QA 评估集。 |
| D3-Q37 | 部分通过 | 给出两种策略相对 A2C／KG-A2C 的定性结果、score 40 瓶颈和可通过性，但没有取得 Figure 2／结果表中的精确 reward（A2C-chained 11.8、KG-A2C-chained 41.8、A2C-Explore 40、KG-A2C-Explore 44）。正文只说可见证据没有精确最终分数，未说全篇未报告；仍有 3 次取证额度，属选择／取得结果表环节遗漏。 |
| D3-Q38 | 通过 | 明确两种新策略 KG-A2C-chained（bottleneck 检测／policy freezing／backtracking）与 KG-A2C-Explore（Go-Explore 结合知识图谱 cell 表示），并交代机制差别与评估表现。 |
| D3-Q39 | 通过 | 明确回答 Yes：图像来自 ShapeWorld 合成的抽象彩色形状域，并说明 Existential-OneShape、Spatial-TwoShapes 等变体；没有扩成全文排除自然图像。 |
| D3-Q40 | 通过 | 说明 diversity 为 observed number / optimal number 的 ratio，optimal 由 ShapeWorld 生成 caption 代理，并解释 language construction 的句级抽象；保留计数范围未说明的限定。 |

**成本：**问答合计 41 次聊天请求、584,483 tokens、报告耗时 188.421 秒；查询 embedding 13 次、重排 13 次；0 网络重试、0 修复；21 个自主步骤、14 次取证调用、13 轮搜索；81 个引用出现／50 个去重来源，正文合计 13,831 字符；无 JS 调用（0 秒）。逐题引用出现／去重来源：Q31 8/5、Q32 5/5、Q33 5/4、Q34 9/4、Q35 17/8、Q36 6/6、Q37 10/5、Q38 11/6、Q39 4/4、Q40 6/3；逐题聊天／tokens／耗时及搜索／阅读、embedding／重排详见 results.json。入库 19 次索引 embedding、196.658 秒另计。本批未重新下载、OCR、解析或索引其他论文；未取得单独计费金额，仅记录实际请求与 tokens。

**产物：**[input.json](../../artifacts/v3/d3-qa-next-ten-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-next-ten-20261028/results.json)；逐题原生 JSON／Markdown 在 `archive/run_logs/d9/`，路径见 results。第 10 节 Q21～Q30、第 13 节 Q23／Q25／Q29、第 16 节 Q29 及更早历史全部保留。本批结束，不自动修 Q37 或开始下一批。

## 18. 给 DeepSeek 的 Q31～Q40 新十题执行提示词

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d3-plan.md 第13、16、17节，执行第17节固定的D3-Q31～D3-Q40十道新QASPER官方dev原题。第1～16节的旧任务和提示全部作为历史，不执行旧main，不重跑Q15、Q21～Q30或Q23／Q25／Q29。保留工作区已有修改。本批只测试当前业务实现，不修改业务代码、业务提示词、解析／检索策略或预算。

十题全部从eval/qasper/raw/qasper-dev-v0.3.json按第17.3节的paper_id和question_id读取原始question，题号续排Q31～Q40，不自行生成、翻译或润色问题，保留原始大小写、拼写、语法及空白。题单已与历史批次和样本索引对照，不另建排重／题单校验程序。只把原问、实际本地版本配对和普通完整回答要求交给业务入口；第17.3节观察重点、官方答案、gold evidence、预期数值／组件／表号／chunk、计算代码与工具动作不得注入模型消息、前置规划或检索参数，不用QASPER full_text绕过真实入库检索。

用户已允许入库新论文。本批固定R6 1704.06194v1、R7 1609.00425v1、R8 2004.03354v2、R9 2002.08795v1、R10 1912.08960v1，每篇两题，来源见第17.2节。R8的数据集题名仍是旧NER题名，固定PDF v2题名是Case Studies on Biomedical NER and Covid-19 QA；这是同一论文的版本差异，按规划使用含新增实验的v2，不误用v1或自动下载最新版。必要PDF下载、MinerU官方API解析和索引embedding属于本批准备。相同固定PDF／API方案已有ready结果就复用，已有同方案bundle沿用现有导入复用能力，不重复上传，不用旧Standard或不同版本替代。

入库沿用import_runtime.import_pdf默认mineru-api入口及当前VLM／全文OCR／公式／表格配置、分块和索引profile，不修改入库代码、不重建其他论文索引。实际paper_id／parse_revision取ready返回绑定R6～R10，记录数据集与实际PDF题名、来源和配置，不预造本地ID。单篇准备失败时记录对应两题未执行，其他独立论文可继续；共享服务故障阻断后续时保存已有结果和用量后停止，不自动换论文、换版、换解析器，不发额外连通性请求。

沿用第16节当前自然语言正文及引用格式、表格目录、原文历史、完整请求容量管理和最终阶段可选run_javascript。模型保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次30秒、五步／五次取证及既有网络重试一次／共享修复一次，embedding和重排沿用当前profile，保存实际提示与JS运行时版本。计算工具由模型自行决定，最终只可消耗原有剩余自主步骤计算，不重开搜索／阅读，不增加额度，不写逐题专用规则或脚本。不恢复8192固定证据窗口、8000字符、累计八块及旧整题超时限制。

按Q31→Q40顺序，各一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，每题独立新会话，不向同论文第二题传第一题历史。使用artifacts/v3/d3-qa-next-ten-20261028/的普通input.json/results.json，会话／提交ID为d3-qa-next-ten-20261028-q31至-q40，stage及论文清单均改为本批。先保存尝试状态再请求；已有本批尝试只整理、不重跑，仅接续未尝试题。回答不完整、失败、中断、未调用read_context／计算工具或未耗尽额度均不自动重开，不追加追问、替代题或中途改提示补抽样。

可复用tmp/d3_prepare_new_five.py的准备方式及tmp/d3_prose_compute_run.py、tmp/d3_final_calculation_q29_run.py的顺序运行与自然语言统计能力；必要时只新增本批窄入口tmp/d3_prepare_next_five.py、tmp/d3_qa_next_ten_run.py，不运行旧main、不建设通用评测框架。input保存无gold题单、实际版本和公开配置；results汇总状态、停止原因、实际用量及评价。逐题完整JSON／Markdown由现有runtime保存到archive/run_logs/d9/，汇总只链接原生日志。只进行必要入库与十题正常流程及原额度内重试／修复，不额外跑fixed_rag、双模式评分、judge、固定证据实验或模型测试。

生成后按第17.6节结合实际展示原文和官方各份参考逐题评价。检查核心覆盖、必要并列项、结果与设置归属、判断依据及指标定义；区分内容通过、部分通过、内容未交付、运行失败和未执行。参考歧义／标注不一致或版本差异按实际正文说明，不能只看answered、HTTP成功或引用定位valid判通过，局部未读到不能说成整篇未报告。若发生计算，分开评价算术与比较口径，引用实际输入来源，不把JS结果当论文证据，不强制每题调用工具。材料充分时允许正常收尾，缺口仍在时根据实际日志说明取证／准备／最终哪里遗漏。

使用answer.text、answer.citations、answer.evidence_sources评价自然语言交付；同来源多次引用计不同出现次数，去重来源数另计，没有claims的旧指标标不适用，不记作零或伪造主张数。逐题记录真实聊天请求／tokens／耗时、搜索／阅读、查询embedding、重排、网络重试／共享修复、JS调用与计算耗时和实际可得费用；本地计算不算独立模型请求，但承接工具结果的聊天计入真实聊天用量。入库成本与问答成本、索引embedding与查询embedding分开；无计费信息如实注明，不为统计发请求。

本批无业务行为修改，不跑离线测试、语法扫描或全量回归；第13、16节已通过且对应代码未变的验证直接复用。遵守AGENTS.md与Stop That Shit的范围要求，不增加审核器、哈希、manifest、快照、审计、额外校验层或无关重构。完成十题各一次或明确共享故障停止后，在第17.7节简要写准备、逐题评价、用量和产物链接，不另建验证报告，不重算旧批次，不据不同新题宣称准确率或稳定性提升。到此结束，不自动修复、加预算或开始下一批，保持第18节本提示词位于文末。
```

## 19. 保持现有版本继续测试：D3-Q41～D3-Q50（2026-10-28）

状态：**已执行结束，结果见第 19.7 节**。上一批 Q31～Q40 十题全部交付，内容 9 通过、1 部分通过。用户决定继续观察新题，暂不围绕 Q37 的单次遗漏修改业务实现或提示词。本批继续从官方 QA 数据集选十题，可入库新论文；最后的第 20 节交接提示词写给**另一个 GPT 对话中的执行助手**，被测系统仍沿用当前 `deepseek-flash` 配置。

### 19.1 来源、编号与观察目的

题目固定来自本地 [QASPER 官方 dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json)，五篇论文各两题，续排 **D3-Q41～D3-Q50**，论文代号续排 **R11～R15**。已与已有 `artifacts/v3/*/input.json` 和 `eval/qasper/*/sample.json` 对照，十题 question_id 与原问无重复，五篇论文也未用于此前 v3 批次。

本批覆盖性能比较、数量与并列项、方法机制、指标定义及证据不足判断。观察同类数值遗漏是否在不同论文上再次出现，同时保留普通题型，不把十题变成 Q37 的定向重演。固定现有代码、业务提示、检索／解析方案和预算，按原问正常作答；不增加必须读表、必须计算、必须耗尽额度等规则。

这是公开 dev 的定向开发观察，成绩只描述本批。规划阶段未下载 PDF 或执行付费请求；后续按用户授权完成的实际入库与问答见第 19.7 节。

### 19.2 五篇新论文与固定来源

以下公开题名和 arXiv 版本已核对，执行时固定版本，不自动跟随最新版。实际本地 `paper_id / parse_revision` 以 ready 返回为准，不拿 QASPER paper_id 代替。

| 代号 | QASPER paper_id | 所选 PDF 题名 | 固定 PDF |
|---|---|---|---|
| R11 | `1802.06024` | Towards an Engine for Lifelong Interactive Knowledge Learning in Human-Machine Conversations | [arXiv v1](https://arxiv.org/pdf/1802.06024v1) |
| R12 | `1811.00383` | Addressing word-order Divergence in Multilingual Neural Machine Translation for extremely Low Resource Languages | [arXiv v1](https://arxiv.org/pdf/1811.00383v1) |
| R13 | `1708.01464` | Massively Multilingual Neural Grapheme-to-Phoneme Conversion | [arXiv v1](https://arxiv.org/pdf/1708.01464v1) |
| R14 | `1605.06083` | Stereotyping and Bias in the Flickr30K Dataset | [arXiv v1](https://arxiv.org/pdf/1605.06083v1) |
| R15 | `2002.01664` | Identification of Indian Languages using Ghost-VLAD pooling | [arXiv v1](https://arxiv.org/pdf/2002.01664v1) |

R11 的 QASPER 元数据题名为 `Towards a Continuous Knowledge Learning Engine for Chatbots`，所选 PDF v1 使用表中题名；两者对应同一 arXiv ID 和 LiLi 方法。输入准备分别保存 `dataset_title` 和 `pdf_title`，不因题名差异换论文。版本与参考存在差异时，事后根据实际入库原文说明，不在运行中换版或补跑。

### 19.3 十题与固定执行顺序

执行时按表中 `QASPER paper_id + question_id` 从官方 JSON 读取原始 `question`，保留大小写、拼写、语法和空白。观察重点仅供生成后的评价，不进入业务消息、前置规划、检索参数或工具指令。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q41 | R11 | How much better than the baseline is LiLi? | `286078813136943dfafb5155ee15d2429e7601d9` | 比较对象、知识库、关系类型和指标对应；若计算提升，说明采用的口径，不把绝对差当相对百分比 |
| D3-Q42 | R11 | Do they report results only on English data? | `cb196725edc9cdb2c54b72364f3bbf7c76471490` | 是否有直接依据支持语言及 only 的排他性；不能仅凭论文语言或熟悉的数据集名称断定 |
| D3-Q43 | R12 | On how many language pairs do they show that preordering assisting language sentences helps translation quality? | `37861be6aecd9242c4fdccdfcd06e48f3f1f8f81` | 数量与实际语言方向相符，区分 parent task 与 child tasks，不重复或漏算 |
| D3-Q44 | R12 | How do they match words before reordering them? | `a313e98994fc039a82aa2447c411dda92c65a470` | 分清词匹配、词序调整及系统／规则的实际作用，不因原问含混编造独立对齐流程 |
| D3-Q45 | R13 | how is model compactness measured? | `113d791df6fcfc9cecfb7b1bebaf32cc2e4402ab` | 回答文中实际衡量方式、单位和比较对象，不擅自替换为参数量或运行内存 |
| D3-Q46 | R13 | what evaluation metrics were used? | `55c8f7acbfd4f5cde634aaecd775b3bb32e9ffa3` | 必要指标列全，区分各自定义与评价粒度，不混用名称相近的指标 |
| D3-Q47 | R14 | What is the size of the dataset? | `7561a968470a8936d10e1ba722d2f38b5a9a4d38` | 区分图像数、每图描述数和总量；保留原文的约数／超过等限定 |
| D3-Q48 | R14 | What biases are found in the dataset? | `26c2e1eb12143d985e4fb50543cf0d1eb4395e67` | 所列偏差对应本文材料，区分已观察实例、背景论述和待进一步验证的推断 |
| D3-Q49 | R15 | What is the GhostVLAD approach? | `4bc2784be43d599000cb71d31928908250d4cef3` | 方法与基础模型的关系、额外机制及其参与阶段说明准确，不混淆分配与最终聚合 |
| D3-Q50 | R15 | Which 7 Indian languages do they experiment with? | `75df70ce7aa714ec4c6456d0c51f82a16227f2cb` | 按实际材料完整列出七种语言；正文列举与表格不一致时核对来源，不凭常识补项 |

十题全部独立新会话，同论文第二题不承接第一题的正文、工具历史或准备事实。题单不携带参考答案、gold evidence、预期数值、表号或 chunk；QASPER 的 `full_text` 不替代实际 PDF 入库与检索。

### 19.4 新论文准备与现有结果复用

用户已允许必要的新论文入库。执行时固定 PDF 保存至 `eval/qasper/pdfs/`，沿用 `import_runtime.import_pdf` 默认 `mineru-api` 入口、当前 VLM／全文 OCR／公式／表格配置、分块及索引 profile。下载、官方解析和索引 embedding 属于执行本批的准备范围。

相同固定 PDF／API 方案已有 ready 版本直接复用，已有同方案 bundle 则通过现有导入能力复用；不用不同版本或旧 Standard 结果替代，不重建其他论文索引。五篇各自绑定实际 ready 返回的本地配对，保存来源、版本及公开配置。单篇失败记录对应两题未执行，其他独立论文可继续；共享故障阻断后续时保留结果和用量后停止，不自动换题、换版或换解析器。

本批不改业务行为，不跑离线测试、语法扫描或全量回归。第 13、16 节已通过且对应代码未变的结果直接复用，不为本轮新增校验器、哈希、manifest 或审计文件。

### 19.5 固定执行方式、配置与普通产物

按 Q41→Q50 顺序，每题仅一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，只传官方原问、实际版本配对及普通完整回答要求。搜索、阅读、准备、计算与停止由模型在当前流程内自行决定。交接给 GPT 执行不代表将被测业务模型切换为 GPT。

配置保持第 17.7 节实际值：`deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次请求 30 秒、五步／五次取证、既有网络重试一次／共享修复一次；embedding 与重排沿用现有 profile。提示版本保持当前 `v2.23-optional-final-calculation-v1`／`v3.1-optional-final-calculation-v1`，实际运行版本照实保存。保留自然语言正文、稳定引用、表格目录、原文历史和完整请求容量管理；最终可选计算只使用剩余自主步骤，不额外开放搜索／阅读或增加预算。

本批目录固定为 `artifacts/v3/d3-qa-q41-q50-20261028/`，stage 为 `d3-qa-q41-q50`，会话／提交 ID 为 `d3-qa-q41-q50-20261028-q41` 至 `d3-qa-q41-q50-20261028-q50`。

- `input.json`：官方来源、十题身份及无 gold 原问、五篇固定来源与实际版本配对、公开配置和提示／JS 运行时版本。
- `results.json`：各题尝试状态、实际停止原因、原生日志路径、用量及生成后简短评价。入库与问答成本、索引与查询 embedding 分开记录。
- 完整逐题 JSON／Markdown 继续由 runtime 写入 `archive/run_logs/d9/`，汇总只链接原生日志，不另复制请求历史。

复用上一批 `tmp/d3_prepare_next_five.py`、`tmp/d3_build_next_ten_input.py`、`tmp/d3_qa_next_ten_run.py` 的准备、无 gold 题单构建、顺序执行和自然语言统计方式。必要时只新增本批窄入口，例如 `tmp/d3_prepare_q41_q50.py`、`tmp/d3_build_q41_q50_input.py`、`tmp/d3_qa_q41_q50_run.py`，替换清单、stage、目录及 ID；不运行旧 main，不覆盖旧批次文件，不建设通用评测框架。

请求前保存尝试状态，已有本批尝试只整理，不重复运行；只接续未尝试题。内容不完整、运行失败、中断、正确说明证据不足、未调用工具或未耗尽额度均不自动补跑，不追加追问或替代题，不在批次中修改提示。真实调用仅含必要入库、十题正常问答及原额度内重试／修复，不额外发连通性、judge、fixed_rag、双模式或固定证据实验请求。

### 19.6 事后评价：区分正常不足与核心遗漏

生成后按第 17.6 节已有口径，用实际入库原文、实际展示材料和官方各份参考评价；运行状态与内容评价分开。**正确说明证据不足可以判内容通过，不以十题全部 answered 为目标。**核心遗漏和明确错误如实记录，不能因引用定位 valid 或 HTTP 成功判通过。

本批参考标注存在需要保留的实际差异：Q41 的两份参考一份给出比较、一份标为不可回答；Q42 两份均标为不可回答；Q44 对可回答性也有分歧。这些信息只供事后评价，不写入业务输入，不要求模型照着标签拒答或作答。根据实际原文判断是否能回答原问，不能把只找到相关方法名称等同于已解答所有细节，也不能把未发现语言说明强化为“只用某种语言”。

数值与并列项按原问检查；必要比较分清原文值与自行计算、基线和聚合口径。Q41 的 baseline 未在原问中指名，允许依据原文明确所选比较对象，不强制唯一隐藏基线；发生计算时记录算术是否正确，不强迫调用 JS。参考只列某个偏差或某个数值时，不据此否定其他确有原文支持的回答。

若再次出现 Q37 类遗漏，依据现有日志记录：核心数值是否已入库、目录是否送达、模型是否识别缺口、是否选择读取、准备／最终是否利用。只作普通文字评价，不建设新诊断系统；个别遗漏不在本批触发改提示、修复或补跑。无关超参数、未问的预处理和泛化限制说明可记为简洁性问题，不扩成每题新的必答项。

沿用正文和引用统计，引用出现次数与真实来源去重数分开，无 claims 的旧指标标不适用。逐题记录聊天／tokens／报告耗时、搜索／阅读、查询 embedding、重排、网络重试／共享修复及 JS 调用／本地耗时；计费缺失如实说明，工具后续聊天仍计实际聊天用量。没有计算调用不能据此证明计算能力稳定，没有重试也不外推总体稳定性。

### 19.7 执行结果（2026-10-28）

**五篇准备：**本批无已有尝试，五个固定 v1 PDF 均下载到 `eval/qasper/pdfs/`，经默认 `import_runtime.import_pdf` 的 `mineru-api` 入口全部 ready；本次五篇均为新 API 批次，未替换版本或重建其他论文索引。

| 代号 | QASPER / 固定版本 | 实际 paper_id / parse_revision | chunks | API batch |
|---|---|---|---|---|
| R11 | `1802.06024v1` | `local_cf2f76f1e8bb4b7f836128e695c745c4` / `r_714475564edf686b` | 50 | `f79f79f2-1d56-4039-babc-57d073e08575` |
| R12 | `1811.00383v1` | `local_48e93b3918f24403b17f3719e389484e` / `r_1118c58940125f20` | 24 | `f416c577-0deb-4c4b-8507-49da8438d8ff` |
| R13 | `1708.01464v1` | `local_667e8d185ebe42ed806cb9c60d442735` / `r_699b733ac4f79d1f` | 33 | `818bfd36-9081-44cd-b6fc-3152b82ecae2` |
| R14 | `1605.06083v1` | `local_2b938863a100443f993370ba32ac1256` / `r_df460336ee2a1cee` | 19 | `47f66130-6a61-4b95-bddf-b7278ed47d8f` |
| R15 | `2002.01664v1` | `local_599a9a07261e4e3bb80dd801c2d440fd` / `r_4a1440d302194feb` | 24 | `ab871116-d048-4fb8-b7ee-beb05bb477e2` |

R11 分别保留 `dataset_title` = Towards a Continuous Knowledge Learning Engine for Chatbots、`pdf_title` = Towards an Engine for Lifelong Interactive Knowledge Learning in Human-Machine Conversations。实际解析记录为 `mineru-api 3.4.4`、cloud/hybrid、model_version=vlm、全文 OCR、公式/表格开启，沿用当前分块和索引 profile。入库合计 **150 chunks、5 个 API 批次、17 次索引 embedding / 39,406 tokens、208.651 秒导入报告耗时**；embedding 请求本地耗时 11.769 秒包含于导入时间，PDF 下载耗时未单独记录。

**执行与配置：**Q41→Q50 各一次完整独立新会话，`mode="agent"`、`library_mode=True`、空历史；stage、目录及会话/提交 ID 均按第 19.5 节。保持 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步/五次取证、网络重试一次/共享修复一次；embedding `qwen3.7-text-embedding` 1024 维、重排 `qwen3-rerank` 及当前 profile。提示 `v2.23-optional-final-calculation-v1` / `v3.1-optional-final-calculation-v1`，JS `mini-racer-0.12.4` / V8 12.6.228.18。未改业务代码、业务提示词、策略或预算，未跑离线测试、语法扫描或回归，复用第 13、16 节已有适用验证。

**结果：10/10 completed / answered，0 运行失败/未执行；内容 9 通过、1 部分通过。**内容评价由本 GPT 对话在生成后对照实际 v1 原文、实际展示材料与官方各份参考完成，没有额外 judge 请求。引用交付另计：9 题绑定来源、Q50 原生引用缺失。

| 题号 | 事后评价 | 原生日志 |
|---|---|---|
| D3-Q41 | 通过：明确多基线、两 KB、F1/MCC 和 overall 绝对差，并列出关系类型反例；自主 JS 一次，口径和算术正确。官方参考可回答性分歧不影响实际 Table 6 可比事实。 | [JSON](../../archive/run_logs/d9/agent_20261028_055532_090267_502dc80ce880.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055532_090267_502dc80ce880.md) |
| D3-Q42 | 通过：明确语言排他性证据不足，未凭 KB 名称推断 English-only；运行 answered 不等于内容必须肯定作答。 | [JSON](../../archive/run_logs/d9/agent_20261028_055557_950832_b8b858c98cbd.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055557_950832_b8b858c98cbd.md) |
| D3-Q43 | 通过：五个 Bengali/Gujarati/Marathi/Malayalam/Tamil→Hindi child 方向，未把 English parent 重计；BLEU 对应正确。 | [JSON](../../archive/run_logs/d9/agent_20261028_055616_211946_11b1cce47877.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055616_211946_11b1cce47877.md) |
| D3-Q44 | 部分通过：词典逐词翻译、CFILT generic/Hindi-tuned 及换序例子正确；但已展示的 p3_c3 明写 parse tree，准备与最终仍称该依据未提供。 | [JSON](../../archive/run_logs/d9/agent_20261028_055634_869206_4a4ecc2970ee.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055634_869206_4a4ecc2970ee.md) |
| D3-Q45 | 通过：按模型 MB 大小比较 LangID-High 15.4 MB / 合计 wFST 197.5 MB，未误换参数量或运行内存。 | [JSON](../../archive/run_logs/d9/agent_20261028_055650_122031_2a55a1eaf91b.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055650_122031_2a55a1eaf91b.md) |
| D3-Q46 | 通过：PER、WER、WER 100 列全，定义与多语言等权平均正确。 | [JSON](../../archive/run_logs/d9/agent_20261028_055705_661759_227b0469977f.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055705_661759_227b0469977f.md) |
| D3-Q47 | 通过：超过 30,000 张、每图 5 条，未捏造精确总量；“不能确定总数”应限于精确值，仍可推得超过 150,000 条的下界。 | [JSON](../../archive/run_logs/d9/agent_20261028_055720_381528_c2bf7e043871.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055720_381528_c2bf7e043871.md) |
| D3-Q48 | 通过：两类偏差与六类不当推断、性别/族裔等实例有原文支持，保留 SEB 未验证限定；未覆盖 §3.1 种族标记统计，不把所有实例/数值增为必答。末句无定量率应限于六类推断。 | [JSON](../../archive/run_logs/d9/agent_20261028_055731_649576_66f9ec179c36.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055731_649576_66f9ec179c36.md) |
| D3-Q49 | 通过：NetVLAD 扩展、K+G、ghost 吸收噪声、参与 V 计算但排除最终拼接准确；没有把 NetVLAD 的 hard→soft 错归为 Ghost 独有新增。 | [JSON](../../archive/run_logs/d9/agent_20261028_055756_817922_0e155166dc7b.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055756_817922_0e155166dc7b.md) |
| D3-Q50 | 内容通过、引用交付缺失：按 Table 1 列全 Hindi、English、Kannada、Telugu、Assamese、Bengali、Malayalam，并指出正文漏项；“权威名单无法确定”过度保守。正文 [1] 等 7 次普通标记未绑定原生来源。 | [JSON](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.md) |

**具体问题：**本批未重现 Q37 那种被问及的核心数值没有取得而只定性作答：Q41 取得 Table 6 并计算，Q43 取得 Table 2，Q50 取得七语言表。Q44 则出现另一环节的遗漏：原文已展示，准备时误判缺口并传到最终；只记录，不修复或补跑。Q48 未取得 §3.1 的种族标记统计，不把局部未读到泛化为全文没有，也不据单条官方参考否定其他有依据的偏差实例。Q50 虽列全七项，正文只有普通数字标记，原生 `citations/evidence_refs/evidence_sources` 全空、`evidence_status=none`；其 `citation_checks=valid` 是空检查，不能算引用交付成功。Q41 一份参考的 WordNet unknown 对 Single 的 F1 差写为 0.1，实际 v1 为 0.0139，按原文判断。

**实际用量：**问答 **41 次聊天请求、550,833 tokens、175.360 秒报告耗时**（原生日志起止本地耗时合计 175.371 秒）；15 次搜索、2 次本地阅读、21 个自主步骤、17 次取证；查询 embedding **15 次 / 395 tokens / 31.360 秒**，重排 **15 次 / 报告 100,672 tokens / 5.556 秒**，网络重试/共享修复 **0/0**。Q41 在 `prepared_final_decision` 自主 JS **1 次，0.098150 秒**，消耗原有剩余步数；其后聊天已含在 41 次/总 tokens 内，未新增搜索阅读。正文共 15,509 字符；原生引用 **80 次出现 / 逐题去重来源之和 44 / 全批去重来源 39**，`evidence_sources` 逐题计数之和 44。逐题引用出现/来源：Q41 11/7、Q42 8/8、Q43 8/5、Q44 10/4、Q45 2/2、Q46 10/5、Q47 2/1、Q48 17/7、Q49 12/5、Q50 0/0；无 `claims` 的旧指标标为不适用。各类耗时不是互斥分项，不重复相加；索引 embedding 与查询 embedding 分开记录。原生结果未提供单独计费金额，费用记缺失而非零，未为统计追加请求。

**产物：**[input.json](../../artifacts/v3/d3-qa-q41-q50-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-q41-q50-20261028/results.json)，完整逐题 JSON/Markdown 使用上表原生日志，不另复制历史。窄入口为 `tmp/d3_prepare_q41_q50.py`、`tmp/d3_build_q41_q50_input.py`、`tmp/d3_qa_q41_q50_run.py`，准备状态 `tmp/d3_q41_q50_prepare.json`；未启动旧 main 或覆盖旧产物。本批到此结束，不修复、不加预算、不重跑、不开始下一批，也不据不同新题宣称总体准确率提高。

## 20. 给另一个 GPT 对话的 Q41～Q50 执行提示词

复制下方代码块内容作为新对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 执行第19节D3-Q41～D3-Q50测试，仅完成必要入库、窄调度与结果记录，保持业务代码、业务提示词和预算不变。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，先读取其 stop-that-shit 技能说明并遵守 Stop Ladder。change 模式的范围仅为本提示词已授权的测试准备、执行和结果回写；按 AGENTS.md 的用户四问控制工作范围，不顺带增加业务修复、提示词调整、审计、哈希、保护层或无关重构。

你是接手本项目测试工作的 GPT 助手。请在 D:/course/paper-research-assistant 工作，先读取 AGENTS.md、docs/v3/d3-plan.md 第16、17.7、19节，然后实际执行第19节的D3-Q41～D3-Q50十道新QASPER官方dev原题，不要只复述规划。第1～18节的旧执行提示作为历史，不执行旧main或重跑旧题，保留工作区已有修改。

用户已决定继续观察新题，暂不围绕Q37修复或调整业务提示。此次由GPT对话负责执行与事后评价，被测系统仍保持deepseek-flash，不把业务模型切成GPT。只测试当前实现，不修改业务代码、业务提示词、解析／检索策略或预算，不增加逐题专用规则。

题单以第19.3节为准，从eval/qasper/raw/qasper-dev-v0.3.json按QASPER paper_id和question_id提取原始question，保持Q41～Q50连续编号、原始大小写／拼写／语法／空白，不自行生成或翻译题目。只把原问、实际本地版本配对和普通完整回答要求传给业务入口。开发观察、官方参考、可回答性标签、gold evidence、预期基线／数值／表号／chunk和工具动作不能进入模型消息、前置规划或检索参数，不用QASPER full_text替代真实入库检索。题单排重已在规划中完成，不另建校验程序。

用户允许必要新论文入库。本批固定R11 1802.06024v1、R12 1811.00383v1、R13 1708.01464v1、R14 1605.06083v1、R15 2002.01664v1，每篇两题，PDF链接见第19.2节。R11的数据集题名是Towards a Continuous Knowledge Learning Engine for Chatbots，实际PDF v1题名是Towards an Engine for Lifelong Interactive Knowledge Learning in Human-Machine Conversations，分别保存dataset_title和pdf_title，不误换论文。必要PDF下载、MinerU官方API解析和索引embedding属于本批准备；相同固定PDF／API方案已有ready或bundle则通过现有能力复用，不重复上传，不用不同版本或旧Standard结果替代。

入库沿用import_runtime.import_pdf默认mineru-api入口和当前VLM／全文OCR／公式／表格配置、分块及索引profile，实际paper_id／parse_revision以ready返回绑定R11～R15，不预造ID、不重建其他论文索引。单篇准备失败时记录对应两题未执行，其他独立论文可继续；共享故障阻断后续时保存已有结果和用量后停止，不自动换题、换版本、换解析器或额外发连通性请求。

保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次请求30秒、五步／五次取证及既有网络重试一次／共享修复一次，embedding和重排使用现有profile。沿用当前自然语言正文、稳定引用、表格目录、原文历史、完整请求容量管理和可选run_javascript，保存实际配置及提示／JS版本。工具与停止均由模型在现有流程内决定，不强制读表、计算或耗尽额度；最终计算只消耗原有剩余自主步数，不重开搜索／阅读，不恢复旧证据截断或旧整题超时限制。

按Q41→Q50顺序，每题一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话，同论文第二题不承接第一题历史。使用artifacts/v3/d3-qa-q41-q50-20261028/的普通input.json/results.json，stage为d3-qa-q41-q50，会话／提交ID为d3-qa-q41-q50-20261028-q41至-q50。先保存尝试状态再请求；已有本批尝试不重复运行，只整理并接续未尝试题。失败、中断、部分回答、正确说明证据不足或未调用工具都不自动补跑，不追加追问、替代题或中途改提示。

复用tmp/d3_prepare_next_five.py、tmp/d3_build_next_ten_input.py、tmp/d3_qa_next_ten_run.py的准备、输入构建、顺序执行与自然语言统计方式；必要时只新增本批窄入口tmp/d3_prepare_q41_q50.py、tmp/d3_build_q41_q50_input.py、tmp/d3_qa_q41_q50_run.py，改成本批清单、stage、目录与ID，不运行旧main或覆盖旧产物。input记录无gold原问、来源、实际配对及公开配置，results记录状态／停止原因／用量与事后评价；逐题完整JSON／Markdown由现有runtime保存到archive/run_logs/d9/，汇总只链接原生日志。真实请求仅限必要入库、十题正常流程和原额度内重试／修复，不额外跑judge、fixed_rag、双模式或固定证据实验。

回答生成后按第19.6节结合实际原文与官方各份参考评价，运行状态和内容评价分开。正确说明证据不足可以通过，不以全部answered为目标；参考可回答性分歧按实际材料说明，不能只照某一条标签。检查数值／基线／关系类型／语言方向／必要并列项和机制定义；计算如发生，分开检查口径与算术。缺口仍在时依据日志说明材料未取得、取得后未利用或准备／最终遗漏，不因工具次数少直接判错，不把局部未读到说成全文没有。Q37类遗漏只记录，不在本批调规则或补跑。

按answer.text／citations／evidence_sources记录自然语言交付；引用出现次数与真实来源去重数分开，无claims的旧指标标不适用。记录聊天请求／tokens／报告耗时、搜索／阅读、查询embedding、重排、网络重试／共享修复、JS调用与本地耗时及可得费用；入库与问答、索引与查询embedding分开。计算后的聊天计入实际用量，费用缺失如实说明，不为统计发额外请求。本批不改业务行为，不跑离线测试、语法扫描或全量回归，复用已通过且对应代码未变的结果，不增加审核器、哈希、manifest、快照、审计或通用评测框架。

完成十题各一次或明确共享故障停止后，在d3-plan.md第19.7节简要补记五篇准备、逐题评价、实际配置、用量及产物链接，不另建验证报告，保持第20节提示词位于文末。最终向用户概括本批表现、具体问题是否重复和实际用量，不重算旧批次或据不同新题宣称总体准确率提升。到此结束，不自动修复、加预算、重跑旧题或开始下一批。
```

## 21. 对齐 RAGFlow 的引用格式兼容修复与离线验证（2026-10-28）

状态：**已实施并完成限定离线验证，结果见第 21.7 节**。本轮只修 Q50 暴露的引用格式交付缺口，优先移植本地 RAGFlow 已有行为。第 1～20 节及 Q41～Q50 原始成绩保留，后续执行以第 22 节给另一个 GPT 对话的提示词为准。

### 21.1 已确认的问题与本轮边界

[Q50 原生日志](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json)中，实际最终来源包含 ref 1～6，模型已取得七语言表；最终正文却使用普通 `[1]` 等标记，而非约定的 `[ID:1]`。本题标记顺序为 **1、2、4、1、5、5、3**，共 **7 次出现、5 个去重来源**。当前 [prose.py](../../paper_assistant/prose.py:8) 只匹配严格 `[ID:n]`，所以原生 `citations / evidence_refs / evidence_sources` 全空、`evidence_status=none`；[引用检查](../../paper_assistant/citations.py:195)在零匹配下返回 `valid`，未触发修复。

本轮目标是让这类已有来源编号的格式变体正常绑定原文，保留正文、来源身份和现有修复机制。不改变问答内容、充分性、取证选择或模型提示；不处理 Q44 的理解遗漏，也不为 Q50 重写七语言答案。修复后判断的是引用交付，不重新评价旧题准确率。

执行顺序：**移植格式兼容 → 三个指定现有离线方法 → Q50 保存输出离线重放 → 在本节记录后结束**。本次写规划不改业务代码、不跑测试；后续实施与验证均不发真实聊天、embedding 或重排请求。

### 21.2 采用 RAGFlow 的具体行为

参考仓库 `E:/project/ragflow` 只读，不修改。

| 参考实现 | 已有行为 | 本项目采用方式 |
|---|---|---|
| [CitationMarkerPattern](E:/project/ragflow/internal/service/citation.go:38) | 同时匹配 `[ID:n]`、`[ID: n]` 与普通 `[n]`，支持已有数字字符范围 | 将该匹配与数字规范化行为直接移植到 Python 的现有 prose 模块，生成标准 `[ID:n]` |
| [buildAgenticReference](E:/project/ragflow/internal/service/agentic_reference.go:42) | 在来源扫描、关联和发布前统一规范化引用格式 | 最终输出先规范化，再由现有验证／发布链路消费同一份正文 |
| [Agentic 严格扫描器](E:/project/ragflow/internal/agentic_rag/citations.go:139) | 仍按标准 `[ID:n]` 关联实际展示的来源 | 保留本项目现有严格解析、来源检查和一次共享修复，规范化后复用 |

RAGFlow 的 Agentic 严格扫描器本身也不识别普通 `[n]`，不能只复制该正则并声称已解决；本次采用其通用格式兼容及“先规范化再消费”的组合方式。Python 与 Go 的正则／数字转换语法按语言适配，保持可追溯的来源注释；不迁移 RAGFlow 的整个引用管线。

本项目 ref **从 1 开始**，沿用本次实际来源映射，不照搬 RAGFlow 从 0 开始的输出编号或重新压缩编号。同来源的多次出现分别计数，来源身份仍按既有方式去重。未知编号、未展示来源继续由现有检查返回错误并使用共享修复，不照搬静默忽略越界编号的分支。

### 21.3 最小改动与消费者衔接

1. **[prose.py](../../paper_assistant/prose.py)：增加统一的本地规范化函数。**按 RAGFlow 的 `CitationMarkerPattern` 识别本轮相关格式，输出标准 `[ID:n]`，保留编号含义、出现顺序和次数。例如 `[5]`、`[ID: 5]` 均变成 `[ID:5]`；已规范的标记再次处理不变，无标记正文不变。不把未知编号删掉或改成其他来源，不给原本没有标记的句子自动配证据。此次不扩展到没有本轮需求的合并引用、网页链接、裸 chunk ID 等其他协议。
2. **[agent.py](../../paper_assistant/agent.py:689)：在最终正文进入验证前调用一次规范化。**将同一份规范化正文传入 `validate_prose_citations`，验证通过后交给 `publish_prose`。首轮与现有格式／引用修复后的输出都经过此入口；计算工具请求沿用现有分支，只有生成最终正文时才处理。`action_steps.response.content` 和聊天记录继续保存模型原始响应，`answer.text` 保存实际交付的规范化正文；引用 `position` 必须根据后者重新解析，不能复用原文位置。
3. **[citations.py](../../paper_assistant/citations.py:195)：复用现有来源检查。**在规范化正文上生成 `citations / evidence_refs / evidence_sources`，保留当前实际请求的 refs、`allowed_citation_ids`、所选版本与实际原文范围。通常不需要改该检查器；仅在必要调用点适配，不新增第二套引用解析、来源扫描或校验层。合法格式变体不消耗修复额度，未知 `[99]` 规范化后应和未知 `[ID:99]` 一样走已有一次修复。

[页面](../../app.py:406)、[Agent 导出](../../paper_assistant/agent_export.py:123)、[普通导出](../../paper_assistant/answer_export.py:81)、[历史](../../paper_assistant/conversation.py:34)和现有评价已经消费正文及原生引用结构。它们直接使用上述统一输出；实施时仅在确有必要的消费者处适配，不分别新增格式转换。保留旧 claims 报告和 fixed_rag 路径，不改历史文件。

`citation_checks=valid` 只表示已识别引用的定位检查结果，引用交付仍看实际 `citations / evidence_sources`。本次让 Q50 的七处标记进入原有检查，不把所有零引用回答一律判错：正常说明证据不足、无论文事实的分析文字继续允许无引用；现有零分母统计保持不适用，不能当作 100% 引用交付成功。不新建逐句语义覆盖判定器，也不让模型额外审核引用。

本轮不改业务提示或提示版本，不调模型、上下文、输出长度、超时、步骤／取证或重试／修复额度；不重做入库、解析、分块、检索或引用 UI。

### 21.4 三个指定现有离线测试方法

后续实施时只在下列既有方法内补必要场景，用通用本地材料／mock，不嵌入 Q50 的论文事实或参考答案，不为本轮另建测试框架。

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：在现有最终正文与引用修复场景中覆盖 `[n]`、`[ID: n]`、标准格式及混合重复引用；确认原始模型响应保留，发布正文规范化，引用编号／出现顺序／字符位置对应发布正文，实际来源身份正确。合法变体无新增模型请求、无修复；未知编号走既有一次共享修复，不重置额度。复用该方法现有未展示来源、无证据说明和资源关闭场景，确认无标记正文不被补引。可在同一方法中直接验证规范化的幂等性及 RAGFlow 已支持的数字转换。
2. `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`：沿用现有 prose fixture 与页面、下载、Markdown 导出和历史检查，使用上述统一链路产出的正文与原生引用；确认页面能显示正确引用出现数／来源数、展开真实原文，保存／导出及历史保留相同来源身份。保留旧 claims 与 fixed_rag 检查；已规范化的输出能直接消费时，不增加页面转换逻辑。
3. `scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately`：在现有自然语言记录场景确认重复出现分别计数、去重来源另计、旧 claims 指标不适用；零引用记录不能因空 `valid` 形成 100% 比例；此前失败检查与实际发布的引用计数仍分开。复用既有评价函数，不添加本轮专用评分字段。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately
```

只有方法失败或发现具体跨模块影响才扩大到直接相关方法；不运行整个模块／目录／全量回归。已通过且对应代码未变的结果复用，不因改了记录文字重新运行。以上是后续实施的验证安排，本次文档修改不执行该命令。

### 21.5 Q50 原始输出的离线重放

三个指定方法通过后，用一次普通离线检查重放 [Q50 已保存 JSON](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json)，不调用 `run_question` 或任何真实模型：

- 读取最后一次 `final_prose` 请求的原始 `response.content`、该请求真实提供的 `sources / allowed_refs` 和保存的 context，复用本地 SQLite／已入库原文。使用实际最终请求的编号映射，不重新给来源排序编号，不以官方参考补全材料。
- 将旧正文送入本次统一规范化与现有引用验证路径，检查发布正文对应的标记序列 **1、2、4、1、5、5、3**，得到 **7 次引用、5 个去重来源**，每次引用均对应当前保存来源；第 5 号确实指向七语言表。
- 原问、语言名单及其余文字不重写；只改变引用标记形式。旧结果中的过度保守结论保持原样，本次不借引用修复润色答案。
- 只在内存生成离线结果并在第 21.7 节简要记数值和原日志路径，不覆盖原始 JSON／Markdown、`artifacts/v3/d3-qa-q41-q50-20261028/results.json` 或第 19.7 节成绩，不另保存一套运行报告。

该检查证明保存输出在新解析链路下能正确关联来源，不证明模型下一次必然输出同样文本，也不计为 Q50 新一次真实复测。当前本地材料不可用时如实记录具体阻断，不自动重新入库或向模型补请求。

### 21.6 验收与结束条件

普通编号和空白变体可在现有入口规范化，发布正文与原生引用一致；Q50 离线重放从 0/0 恢复为 7 次引用／5 个来源；未知编号和未展示来源仍使用原检查，合法变体不增加模型请求，正常无引用回答不受影响；三个指定方法通过。

完成上述改动、指定验证及第 21.7 节补记后结束。不真实重跑 Q50、Q44 或旧十题，不新增模型、embedding、重排请求，不自动开始 Q51～Q60，不另建验证报告或进行无关重构。不能完成的项目如实记录，不提前宣称完成。

### 21.7 实施与验证结果（2026-10-28）

已完成本节限定实现与离线验证。

- [prose.py](../../paper_assistant/prose.py) 移植只读参考仓库 RAGFlow `internal/service/citation.go` 的 `CitationMarkerPattern` 及 Arabic-Indic / Eastern Arabic-Indic 数字转换，保留来源注释；统一将 `[n]`、`[ID: n]` 和标准标记规范为 `[ID:n]`。只转换标记内数字，保留编号、顺序、重复次数及从 1 开始的来源映射；标准文本幂等，无标记正文不变，未知编号留给原检查处理。未增加合并引用、网页或裸 chunk 协议。
- [agent.py](../../paper_assistant/agent.py) 按 RAGFlow `internal/service/agentic_reference.go:buildAgenticReference` 的顺序，在 `request_prose_final` 得到最终正文后、`validate_prose_citations` 前统一规范化，首轮和既有修复输出均经过该入口。`action_steps.response.content`、聊天记录仍保留模型原始文本；同一份规范化正文用于验证和发布，引用位置据此重新计算。计算分支、来源白名单及已有验证器保持原样；页面、导出、历史和评价无需业务适配。

仅在三个指定现有方法中补通用本地 fixture/mock 场景并运行指定命令：

| 方法 | 实际结果 |
|---|---|
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 通过；覆盖混合/重复/数字变体、幂等、原始响应与交付正文、位置及真实来源、合法变体零修复、普通/标准未知 99 的一次修复、修复再次失败及准备阶段已用共享额度、正常无引用，保留原计算/资源关闭等场景。 |
| `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations` | 通过；规范化后的通用 prose fixture 显示 4 处/2 来源及原文，JSON 下载、Markdown 和会话历史使用同一正文/来源身份，保留旧 claims 和 fixed_rag 场景。 |
| `scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately` | 通过；重复出现与去重来源分计，旧 claims 保留，prose 不虚构 claims；空 valid 检查为 0/0、ratio=None，未记 100%。 |

实际输出：**Ran 3 tests in 24.909s，OK**。未扩大到其他方法、模块或全量；之后仅补文档，不重复执行已通过验证。

**Q50 保存输出离线重放：通过。**三个方法通过后，读取[原生日志](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json)最后一次 `final_prose` 的原始 `response.content`、该次真实 `sources/allowed_refs`（1～6）与保存 context，使用只读本地 `papers.sqlite3` 和已入库原文，通过新规范化与现有 `validate_prose_citations`。恢复序列 **1、2、4、1、5、5、3**，**7 次引用、5 个去重 `evidence_refs/evidence_sources`**，状态 valid；规范化正文的引用位置为 **54、60、66、242、308、371、504**。ref 5 对应 `local_599a9a07261e4e3bb80dd801c2d440fd_r_4a1440d302194feb_p3_c3`，本地原文确为包含七种语言的 Table 1。正文除标记形式外完全不变，过度保守结论亦未重写。

本次仅在内存检查保存输出，未生成运行报告、覆盖原生 JSON/Markdown、旧 results 或第 19.7 节成绩；这是**离线解析验证，不是新的模型复测**。未调用 `run_question`，真实聊天/embedding/重排请求均为 0；业务提示及版本、模型配置、取证/步骤/输出/超时、网络重试和共享修复额度未变。未处理 Q44、未补跑旧题或开始下一批，本轮结束。

## 22. 给另一个 GPT 对话的引用格式修复执行提示词

复制下方代码块内容作为新对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 按d3-plan.md第21节移植RAGFlow引用格式兼容，完成三个指定离线方法和Q50保存输出的离线重放，不发真实模型请求。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能说明，按Stop Ladder及AGENTS.md用户四问控制范围。请在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第19.7和21节，实际完成本轮实现与离线验证，不只复述规划。第1～20节旧执行提示作为历史，不运行旧main、不重跑旧题，保留工作区已有修改。本提示词交给GPT执行，被测业务模型配置保持不变。

具体问题：Q50已取得七语言表，最终模型却写普通[1]等标记；prose.py只匹配[ID:n]，导致citations/evidence_refs/evidence_sources为空，空检查仍valid。修复格式交付，不修改Q44的理解问题、Q50的过度保守结论、充分性或业务提示词，不重新生成答案。

本地E:/project/ragflow只读参考，能复用就直接移植。采用internal/service/citation.go:38的CitationMarkerPattern及已有数字转换行为，兼容[ID:n]、[ID: n]和[n]；采用internal/service/agentic_reference.go:42的先规范化再解析／关联／发布顺序。注意internal/agentic_rag/citations.go:139仍是严格[ID:n]扫描器，只抄这个不能解决普通[n]。按Python语法适配现有prose模块，保留来源注释，不迁移整个框架或其他引用协议。

在paper_assistant/prose.py加入统一本地规范化，将相关格式变为标准[ID:n]，保持编号含义、顺序和次数；标准文本再次规范化不变，无标记正文不变。沿用本项目从1开始的稳定ref，不复制RAGFlow从0开始的发布编号或重新压缩映射。未知编号不能删除、改号或随意配来源；不为原本没有标记的句子自动找证据，不扩展合并引用、网页链接或裸chunk等未要求协议。

在agent.py现有request_prose_final取得最终正文后、validate_prose_citations之前规范化，首轮及既有修复输出均走这个统一入口。action_steps.response.content和聊天记录保留模型原始响应，answer.text使用实际规范化交付正文；解析和发布必须使用同一份文本，position依据该文本重新计算。计算工具分支保持原样。继续由citations.py现有检查生成原生citations/evidence_refs/evidence_sources，保留当前实际请求refs、所选版本、已展示原文与白名单检查。合法格式变体不占修复额度，未知[99]与未知[ID:99]一样沿用现有一次共享修复，不加请求预算。

页面、Markdown/JSON下载、导出、历史及评价继续消费同一份正文与原生引用。只有确有必要才适配消费者，不在各处另加解析器；旧claims报告和fixed_rag仍可读。citation_checks valid只表示已识别引用的检查结果，是否交付看实际引用和来源；正常无证据说明或纯分析允许零引用，零分母不记100%，不建立逐句语义审核、全篇引用判定器、额外模型、哈希、manifest或审计层。业务提示及提示版本、模型、取证／步骤／输出／超时和共享重试修复额度均不变。

实现后只调整并运行第21.4节三个现有方法：scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records；scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately。用通用本地fixture/mock覆盖格式兼容、原始响应与规范化正文、位置/重复引用/真实来源、未知编号一次修复、正常无引用、页面/导出/历史及空检查统计。不嵌入Q50答案，不另建框架，不跑整模块／目录／全量；只有失败或具体跨模块影响才扩大，已通过且对应代码未变的结果复用。离线不得发聊天、embedding或重排请求。

三个方法通过后按第21.5节仅离线重放archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json的原始最终输出：使用该次最终请求真实sources/allowed_refs、保存context及本地已入库材料，经过新规范化和现有验证路径。预期ref序列1、2、4、1、5、5、3，共7次引用、5个去重来源，ref5对应七语言表；正文除标记形式外不重写。不要调用run_question，不用官方参考填材料，不覆写原生日志、旧results或第19.7节成绩。离线结果只在内存检查并在第21.7节简要记录，不另建运行报告；本地材料不可用时如实记录阻断，不重入库或请求模型。

在d3-plan.md第21.7节简要写实际改动、三个方法的实际结果、Q50离线7/5来源恢复情况和原日志链接；未完成的如实说明，保持第22节本提示词位于文末。完成后向用户说明改动与实际验证，明确这是已有输出的离线解析验证，不是新的模型复测。到此结束，不真实重跑Q50/Q44或旧十题，不追加付费调用、不开始Q51～Q60、不顺带修其他问题。
```

## 23. 下一批十题真实测试：D3-Q51～D3-Q60（2026-10-28）

状态：**已执行结束，结果见第 23.6 节**。承接第 21.7 节已经完成的引用格式兼容修复，在当前版本继续测试十道新 QASPER 官方 dev 原题。用户明确要求不增加冗余测试和校验：本批只做必要论文准备、十题各一次完整真实问答及事后评价，不再安排离线回归或 Q50 重放。最后的第 24 节提示词交给另一个 GPT 对话执行，并包含 Stop That Shit 插件调用。

### 23.1 来源与固定论文

题目来自本地 [QASPER 官方 dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json)，编号续排 **D3-Q51～D3-Q60**，五篇论文各两题，代号 **R16～R20**。选题时已对照历史 `artifacts/v3/*/input.json` 与 `eval/qasper/*/sample.json`，所选 question_id 和原问未重复，五篇论文未用于此前 v3 批次；执行时直接使用固定题单，不重复建设排重或题单校验流程。

以下 arXiv 题名和公开 v1 版本已核对；固定使用表中 PDF，不自动跟随最新版。允许必要的新论文入库，实际本地 `paper_id / parse_revision` 以现有入口 ready 返回为准。

| 代号 | QASPER paper_id | 论文 | 固定 PDF |
|---|---|---|---|
| R16 | `1603.09631` | Data Collection for Interactive Learning through the Dialog | [arXiv v1](https://arxiv.org/pdf/1603.09631v1) |
| R17 | `1808.09111` | Unsupervised Learning of Syntactic Structure with Invertible Neural Projections | [arXiv v1](https://arxiv.org/pdf/1808.09111v1) |
| R18 | `2002.11910` | Integrating Boundary Assembling into a DNN Framework for Named Entity Recognition in Chinese Social Media Text | [arXiv v1](https://arxiv.org/pdf/2002.11910v1) |
| R19 | `1906.01081` | Handling Divergent Reference Texts when Evaluating Table-to-Text Generation | [arXiv v1](https://arxiv.org/pdf/1906.01081v1) |
| R20 | `1802.07862` | Multimodal Named Entity Recognition for Short Social Media Posts | [arXiv v1](https://arxiv.org/pdf/1802.07862v1) |

### 23.2 十题与执行顺序

执行时按 `QASPER paper_id + question_id` 从官方 JSON 取原始 `question`，保留大小写、拼写、语法和空白。表中观察重点只用于事后评价，不进入模型消息、前置规划、检索参数或工具指令。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q51 | R16 | How was this data collected? | `455d4ef8611f62b1361be4f6387b222858bb5e56` | 采集方式、任务来源及必要参与者条件对应，不以通用数据收集流程代替论文事实 |
| D3-Q52 | R16 | What is the average length of dialog? | `bc16ce6e9c61ae13d46970ebe6c4728a47f8f425` | 平均值的单位及分母正确，区分 turns、句子或词数；直接报告值与推算值分开 |
| D3-Q53 | R17 | What datasets do they evaluate on? | `6424e442b34a576f904d9649d63acf1e4fdefdfc` | 数据集与任务、子集对应；根据实际实验说明作答，不把参考分歧直接当模型错误 |
| D3-Q54 | R17 | What is the invertibility condition? | `887c6727e9f25ade61b4853a869fe712fe0b703d` | 条件、变量及逆映射关系忠实于正文／公式，不增加未问的形式证明 |
| D3-Q55 | R18 | What are previous state of the art results? | `9da1e124d28b488b0d94998d32aa2fa8a5ebec51` | 先前方法、指标及任务类别对应，区分旧结果与本文提升，不混淆不同列 |
| D3-Q56 | R18 | What boundary assembling method is used? | `d78f7f84a76a07b777d4092cb58161528ca3803c` | 搜索方向、边界合并条件与用途完整，不把边界组装等同于整套识别模型 |
| D3-Q57 | R19 | By how much more does PARENT correlate with human judgements in comparison to other text generation metrics? | `ffa7f91d6406da11ddf415ef094aaf28f3c3872d` | 数据集、指标／比较对象及相关系数对应；若计算差值，不与相对百分比混用 |
| D3-Q58 | R19 | How many people participated in their evaluation study of table-to-text models? | `bf3b27a4f4be1f9ae31319877fd0c75c03126fd5` | 区分独立参与人数、判断数量与任务数量；没有明确人数依据时正常说明不足 |
| D3-Q59 | R20 | Does their NER model learn NER from both text and images? | `adbf33c6144b2f5c40d0c6a328a92687a476f371` | 明确判断并说明两种模态在本文模型中的作用，不把多模态泛化为所有输入均同等有效 |
| D3-Q60 | R20 | How large is their MNER SnapCaptions dataset? | `1591068b747c94f45b948e12edafe74b5e721047` | 数量与统计对象对应，区分图文对、实体标注和数据划分，保留原文数量精度 |

十题全部独立新会话，同论文第二题不承接第一题的答案、工具历史或准备事实。官方参考、gold evidence、预期数值／公式／表号／chunk 不作为业务输入，QASPER `full_text` 不替代实际入库检索。

### 23.3 必要准备与真实运行

五篇 PDF 经现有 `import_runtime.import_pdf` 默认 `mineru-api` 入口准备，沿用当前解析配置、分块和索引 profile。相同固定 PDF／API 方案已有 ready 或 bundle 时直接通过现有能力复用；缺少时允许下载、官方 API 解析和索引 embedding。不重建其他论文索引，不增加连通性测试或独立 ready 校验器。单篇失败记录对应两题未执行，其他论文可继续；共享故障阻断后续时保存已有结果后停止，不自动换题或换版。

按 Q51→Q60，每题只调用一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`。这是**十题新的真实模型运行**，包含各题正常的前置规划、检索／阅读、准备、最终生成及原额度内重试／修复；不是保存输出重放，也不是每题只发一次 HTTP 请求。模型自主选择工具与停止，不注入工具动作或强制生成某种引用格式。

保持当前 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证，以及既有网络重试一次／共享修复一次；embedding／重排沿用当前 profile，照实保存配置和提示／JS 版本。保留第 21 节引用兼容、自然语言正文、实际来源映射、原文历史和可选计算。执行助手是 GPT，不切换被测业务模型。

本批不改业务实现、提示词或预算。第 21.7 节三个方法及 Q50 离线重放已经通过，代码未变则直接复用；**不重跑这些验证，不增加新的离线测试、语法扫描、全量回归、额外模型／embedding 探测、judge、fixed_rag 或固定证据实验**。引用交付在本批正常结果中观察即可，不为触发兼容分支额外重跑。

### 23.4 产物与尝试状态

普通产物目录为 `artifacts/v3/d3-qa-q51-q60-20261028/`，stage 为 `d3-qa-q51-q60`，会话／提交 ID 为 `d3-qa-q51-q60-20261028-q51` 至 `d3-qa-q51-q60-20261028-q60`。`input.json` 保存无 gold 原问、来源／实际版本配对和公开配置；`results.json` 保存实际状态、停止原因、原生日志路径、用量与简短评价。完整逐题 JSON／Markdown 沿用 runtime 的 `archive/run_logs/d9/`，不复制一套历史或新增验证报告。

复用 `tmp/d3_prepare_q41_q50.py`、`tmp/d3_build_q41_q50_input.py`、`tmp/d3_qa_q41_q50_run.py` 的现有方式，必要时只新增本批窄入口，替换固定题单、论文、stage、目录和 ID；不运行旧 main 或覆盖旧产物，不建设通用评测框架。沿用现有尝试状态，请求前保存；已尝试题只整理，接续未尝试题。失败、中断、内容不足或未调用某工具均不自动补跑，不追加追问或替代题。

### 23.5 事后评价与结束条件

十题生成后按实际展示原文与官方各份参考评价，分开记录运行状态、核心内容和引用交付，不用 answered 或 citation_checks valid 替代内容判断。Q53、Q58 的官方参考存在可回答性分歧，依据实际版本原文说明；正确说明证据不足可以通过，不强求十题都肯定作答。

重点看所问对象、必要条件／并列项、数值与设置归属，以及准备／最终是否利用已有材料。若发生计算，区分口径和算术；未调用计算不单独判错。普通编号若出现，利用原生日志中已有的原始输出、交付正文及 `citations / evidence_sources` 观察是否正常绑定；引用出现次数与去重来源分计，零引用不能只凭空 valid 判交付通过。无需新增格式校验脚本或第二套来源检查。

沿用现有统计记录聊天请求、tokens、报告耗时、查询 embedding、重排、网络重试／修复和 JS 调用；必要入库与问答成本、索引与查询 embedding 分开，费用缺失如实注明，不为统计追加请求。只说明本批结果及具体问题是否重复，不重算旧批次或据不同新题声称准确率提高。

完成十题各一次或明确共享故障停止后，在第 23.6 节补记并结束。问题只记录，不在批次中修复、改提示、加预算或补抽样，也不自动开始下一批。

### 23.6 执行结果（2026-10-28）

**五篇准备：**五个固定 v1 PDF 经默认 `import_runtime.import_pdf` 的 `mineru-api` 入口全部 ready，沿用当前 VLM/全文 OCR/公式/表格配置、分块及索引 profile；本次均为新 API 批次，未更换版本、解析器或重建其他论文索引。

| 代号 | 固定版本 | 实际 paper_id / parse_revision | chunks | API batch |
|---|---|---|---|---|
| R16 | `1603.09631v1` | `local_acffc244283745a8a86b85e3f29902db` / `r_97bc0915a0967ec9` | 25 | `fe5758a4-3abd-4100-84fc-3ff409d1d96a` |
| R17 | `1808.09111v1` | `local_57dac2a4b538465e9eaafbbdd9441ee9` / `r_ce8f65599aea2c14` | 48 | `3270053c-b705-40bc-9588-e85eea550d62` |
| R18 | `2002.11910v1` | `local_88ef531d2aea4576afedcef58bf92b7f` / `r_db78f2ba617760a2` | 17 | `84b15a7e-745d-4a7d-92f6-3c79eadf56c3` |
| R19 | `1906.01081v1` | `local_a0e5236e8b2d4acb9afbdc38c3fd0cfa` / `r_f638e4c89eb81dc9` | 51 | `5529dc5f-6abd-4013-b3c0-42af40ab886e` |
| R20 | `1802.07862v1` | `local_9e038bfb958946b7ad891c6eb6c45ae6` / `r_876dc67efa78d975` | 33 | `20fb1f09-0cd0-4297-ad23-a1f66d1c1452` |

入库合计 **174 chunks、5 个 MinerU API 批次、20 次索引 embedding / 43,887 tokens、260.193 秒导入报告耗时**；索引 embedding 请求耗时 14.918 秒已包含于导入，PDF 下载耗时未单列。准备时保存 R18 尝试状态出现一次本地 Windows `os.replace` 拒绝访问，发生在 R18 下载/入库之前；接续读取已保存状态、跳过 ready 的 R16/R17，只准备 R18～R20，没有重复上传/embedding，也未改保存或业务代码。

**配置与执行：**Q51→Q60 各一次完整真实 Agent 运行，空历史、独立会话，`library_mode=True`，stage、目录和会话/提交 ID 均按第 23.4 节。实际仍为 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步/五次取证、网络重试一次/共享修复一次；embedding `qwen3.7-text-embedding` 1024 维、重排 `qwen3-rerank`，沿用原 profile。提示 `v2.23-optional-final-calculation-v1` / `v3.1-optional-final-calculation-v1`，JS `mini-racer-0.12.4` / V8 12.6.228.18。未改业务代码、提示或预算；复用第 21.7 节已通过结果，未跑旧 main、旧题、离线测试、语法扫描、额外 ready 校验或付费探测。

**逐题：10/10 completed / answered，0 运行失败/未执行；核心内容 9 通过、1 部分通过；10/10 原生引用及来源非空且绑定。**Q57 停止原因为 `no_reliable_evidence_direction`，其他九题为 `answered`。以下内容评价由本 GPT 对话在生成后结合实际 v1 原文、展示材料和官方各份参考完成，没有额外 judge。引用列为出现次数/逐题去重来源数，不能用 valid 代替核心内容评价。

| 题号 | 核心内容评价 | 引用/来源 | 原生日志 |
|---|---|---|---|
| D3-Q51 | 通过：CrowdFlower、Simple Questions 训练题、三阶段对话、英语国家参与者及专家标注对应实际采集流程。 | 11/5 | [JSON](../../archive/run_logs/d9/agent_20261028_064447_077744_3a2ec8eeda50.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064447_077744_3a2ec8eeda50.md) |
| D3-Q52 | 通过：8533 turns / 1900 dialogs ≈ 4.49 turns/dialog，分组均值亦正确；明确为推算，自主 JS 一次，口径和算术正确。 | 2/2 | [JSON](../../archive/run_logs/d9/agent_20261028_064518_403557_992124f864b0.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064518_403557_992124f864b0.md) |
| D3-Q53 | 通过：WSJ/Penn Treebank，区分 POS induction/依存解析设置与词向量训练数据；官方可回答性分歧按实际 §4 原文处理。 | 9/7 | [JSON](../../archive/run_logs/d9/agent_20261028_064551_819113_5b92f21d872b.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064551_819113_5b92f21d872b.md) |
| D3-Q54 | 通过：dim(x)=dim(e) 与 f_phi 逆映射存在两项条件完整，推断可处理性的前提保留；附带说明偏长。 | 9/8 | [JSON](../../archive/run_logs/d9/agent_20261028_064625_888396_cf0edcf04987.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064625_888396_cf0edcf04987.md) |
| D3-Q55 | 通过：三种先前方法的 P/R/F1 列正确，overall 58.23/58.99/59.11 与本文 61.06 分开；不照抄一份参考中错误的 55.97 recall（实际 54.97）。 | 10/4 | [JSON](../../archive/run_logs/d9/agent_20261028_064652_544876_0b36d7803971.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064652_544876_0b36d7803971.md) |
| D3-Q56 | 通过：BIES、backward greedy search、相邻两个 noun 合并边界及实体候选用途完整，未等同整套 NER 模型。 | 9/4 | [JSON](../../archive/run_logs/d9/agent_20261028_064714_597761_ed2a8f56e486.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064714_597761_ed2a8f56e486.md) |
| D3-Q57 | 部分通过：定性比较正确，缺少原问要求的相关系数/差值；表已入库且目录送达，但两次搜索后未读表便以无线索结束，重现 Q37 类遗漏。 | 11/6 | [JSON](../../archive/run_logs/d9/agent_20261028_064735_024987_5502c700bd0e.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064735_024987_5502c700bd0e.md) |
| D3-Q58 | 通过：约 500 位不同 workers，未混淆 1100 tables、8800 judgments 与人数；实际原文支持可回答，不随另一份不可答标签拒答。 | 4/2 | [JSON](../../archive/run_logs/d9/agent_20261028_064759_955470_25c30bb6370a.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064759_955470_25c30bb6370a.md) |
| D3-Q59 | 通过：明确 text+image，解释 word/character/visual 与 modality attention，保留无关视觉上下文可被衰减的条件。 | 9/5 | [JSON](../../archive/run_logs/d9/agent_20261028_064813_433410_aa9fc81e96cb.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064813_433410_aa9fc81e96cb.md) |
| D3-Q60 | 通过：10K 图像-caption 配对与专家实体标注、70/15/15 划分区分正确；额外“精确整数无法确定”过度保守，未影响核心规模交付。 | 4/2 | [JSON](../../archive/run_logs/d9/agent_20261028_064830_375393_18360ce065d7.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_064830_375393_18360ce065d7.md) |

**问题与引用观察：**Q57 是选择/取得核心结果表环节遗漏。实际 Table 2 的调参 PARENT*-W / RG-F 平均相关系数为 0.913/0.758（差 0.155），未调参 PARENT-W 为 0.838（同基线差 0.080）；Table 4 的 PARENT-C / CIDErD 为 0.846/0.829（差 0.017）。允许明确其他比较口径，但本次没有任何核心数值。表格 chunk 已入库，首个实际决策请求已包含 `parent15`（Table 2）和 `parent23`（Table 4）的阅读目录/表题；模型取得的正文未含表格数值，准备阶段识别缺口后仍称没有 scoped 线索，未读表便收尾（自主步骤 3/5、取证 2/5）。判部分通过依据实际可读材料，不因工具次数少；最终“paper reports ... qualitatively”也不应扩大为全文没有数值。只记录，不修复、改提示或补跑。

十题原始最终输出与 `answer.text` 均相同且已使用标准 `[ID:n]`，实际 `citations/evidence_sources` 均非空；本批未自然触发普通 `[n]` 兼容分支，因此不声称这十题重新证明该分支的真实运行稳定性。Q60 留有额外精度不足的保守限定，部分回答附带原问未需的背景，但核心内容按所问对象评价。

**实际用量：**问答 **43 次聊天请求、601,897 tokens、235.766 秒报告耗时**（原生日志本地起止耗时合计 235.780 秒）；13 次搜索、3 次本地阅读、23 个自主步骤、16 次取证。查询 embedding **13 次 / 364 tokens / 50.699 秒**，重排 **13 次 / 报告 86,992 tokens / 5.286 秒**，网络重试/共享修复 **0/0**。Q52 自主 JS **1 次，0.186576 秒**，其后聊天已含在上述 43 次和总 tokens 内，无追加预算。正文共 **13,630 字符**，引用 **78 次出现 / 逐题去重来源之和 45 / 全批去重来源 43**，`evidence_sources` 逐题计数之和 45；无 `claims` 的旧指标不适用。各类耗时不是互斥分项，不重复相加；索引与查询 embedding、入库与问答分开记录。原生结果没有单独计费金额，费用记缺失而非零，未为统计发额外请求。逐题全部请求、tokens、搜索/阅读、重试/修复及 JS 统计见 results。

**产物：**[input.json](../../artifacts/v3/d3-qa-q51-q60-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-q51-q60-20261028/results.json)；完整记录使用上表 runtime 原生 JSON/Markdown。窄入口 `tmp/d3_prepare_q51_q60.py`、`tmp/d3_build_q51_q60_input.py`、`tmp/d3_qa_q51_q60_run.py`，准备状态 `tmp/d3_q51_q60_prepare.json`。未覆盖历史产物、重算旧成绩或新增验证报告。本批结束，不修复、加预算、补跑或开始下一批；不同新题的结果不用于宣称总体准确率提高。

## 24. 给另一个 GPT 对话的 Q51～Q60 测试提示词

复制下方代码块内容作为新对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 执行d3-plan.md第23节Q51～Q60十题真实测试，只做必要论文准备、十题各一次完整运行与结果回写，不加冗余测试或校验。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能并遵守Stop Ladder及AGENTS.md用户四问。请在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第21.7和23节，实际执行本批。第1～22节旧提示只作历史，不运行旧main或重跑旧题，保留工作区已有修改。

本批是Q51～Q60十道新的真实模型问答，不是离线重放。按第23.2节固定paper_id/question_id，从eval/qasper/raw/qasper-dev-v0.3.json提取官方原始question，保留大小写、拼写、语法和空白，不自行出题或润色。题单已在规划中排重，不再写排重、题单校验或预检脚本。只把原问、实际本地版本配对和普通完整回答要求传给业务入口，观察重点、参考答案、可回答性标签、gold evidence、预期数值／公式／表号／chunk及工具动作均不注入业务消息，不用QASPER full_text替代检索。

用户允许必要新论文入库。固定R16 1603.09631v1、R17 1808.09111v1、R18 2002.11910v1、R19 1906.01081v1、R20 1802.07862v1，来源见第23.1节，每篇两题。相同固定PDF／API方案已有ready或bundle就用现有能力复用；缺少时下载PDF，通过import_runtime.import_pdf默认mineru-api入口解析和索引，沿用当前配置及profile，实际paper_id/parse_revision用ready返回，不预造ID、不重建其他论文索引。单篇失败记录两题未执行，其他独立论文可继续；共享故障阻断后续时保存已有结果停止，不换题、换版或换解析器，不增加连通性请求。

保持当前业务代码、业务提示与预算。被测模型仍为deepseek-flash，GPT只是执行助手；使用1048576上下文、temperature 0.2、4096输出、单次30秒、五步／五次取证及既有网络重试一次／共享修复一次，embedding与重排沿用当前profile，保存实际配置及提示／JS版本。沿用第21节引用格式兼容、自然语言正文、实际来源映射、原文历史和可选计算，不强制读表、调用计算、耗尽额度或输出某种引用格式。

按Q51→Q60，各一次完整d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话，同论文第二题不带第一题历史。真实调用仅包括必要入库、十题正常流程及原额度内重试／修复。使用artifacts/v3/d3-qa-q51-q60-20261028/的普通input.json/results.json，stage=d3-qa-q51-q60，会话／提交ID为d3-qa-q51-q60-20261028-q51至-q60；完整原生日志由runtime保存到archive/run_logs/d9/。沿用尝试状态，请求前保存；已尝试只整理，接续未尝试题，不因失败、中断、不完整或未调用工具补跑，不追加追问或替代题。

复用tmp/d3_prepare_q41_q50.py、tmp/d3_build_q41_q50_input.py、tmp/d3_qa_q41_q50_run.py的准备、输入构建、顺序执行与统计方式，必要时只新增本批窄入口并替换清单、stage、目录及ID，不运行旧main或覆盖历史。第21.7节三个现有方法和Q50离线重放已通过，代码未变就复用，不重跑、不加新离线测试、语法扫描、全量回归、额外ready校验、固定证据实验、judge、fixed_rag或模型／embedding探测。十题正常结果已经承担本批观察，不为验证引用兼容另跑Q50或强制触发分支。

生成后按第23.5节结合实际原文与官方各份参考评价，分开记录运行状态、核心内容和引用交付。参考分歧按实际材料说明，正确表达证据不足可通过，不以十题全部肯定作答为目标。关注数值／基线／单位／统计对象、必要条件和并列项；计算如发生，区分口径与算术。已有材料遗漏或过度保守只根据日志记录，不中途修复、改提示或补抽样。引用使用原生日志中已有的原始输出、answer.text、citations/evidence_sources判断是否绑定，不只看空valid；出现次数和去重来源分计，无claims的旧指标不适用，不另建格式扫描器或来源校验器。

沿用现有统计记录实际请求、tokens、报告耗时、搜索／阅读、查询embedding、重排、重试／修复及JS调用，入库与问答、索引与查询embedding分开，费用缺失如实说明，不为统计追加请求。不新增审计、哈希、manifest、保护层、通用框架或独立验证报告。

十题各一次或明确共享故障停止后，在d3-plan.md第23.6节简要补记五篇准备、逐题评价、实际用量和普通产物链接，保持第24节提示词位于文末。最后向用户概括本批实际表现和具体问题，不重算旧成绩或宣称总体准确率提高。完成后结束，不自动修复、加预算、重跑旧题或开始下一批。
```

## 25. 下一批二十题真实测试：D3-Q61～D3-Q80（2026-10-28）

状态：**已执行结束，结果见第25.6节**。用户要求继续二十题测试，并明确不要多余校验。本批沿用当前实现和配置，选择五篇新论文、每篇四道官方原题，以减少论文准备次数；二十题全部独立新会话，各一次完整真实问答。第 1～24 节及历史成绩保留，文末第 26 节为给另一个 GPT 对话的执行提示词。

### 25.1 来源与五篇固定论文

题目来自本地 [QASPER 官方 dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json)，续排 **D3-Q61～D3-Q80**，论文代号 **R21～R25**。选题时已对照历史 `artifacts/v3/*/input.json` 及 `eval/qasper/*/sample.json`，所选 question_id 和原问无重复，五篇论文未用于此前 v3 批次。执行直接使用固定题单，不另写排重、题单校验或预检程序。

以下公开题名和 v1 版本已核对，固定使用表中 PDF；允许必要的新论文入库。本地 `paper_id / parse_revision` 取现有导入入口实际 ready 返回，不提前编造。

| 代号 | QASPER paper_id | 论文 | 固定 PDF |
|---|---|---|---|
| R21 | `1809.01541` | Copenhagen at CoNLL--SIGMORPHON 2018: Multilingual Inflection in Context with Explicit Morphosyntactic Decoding | [arXiv v1](https://arxiv.org/pdf/1809.01541v1) |
| R22 | `1809.00530` | Adaptive Semi-supervised Learning for Cross-domain Sentiment Classification | [arXiv v1](https://arxiv.org/pdf/1809.00530v1) |
| R23 | `1612.03226` | Active Learning for Speech Recognition: the Power of Gradients | [arXiv v1](https://arxiv.org/pdf/1612.03226v1) |
| R24 | `1909.02027` | An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction | [arXiv v1](https://arxiv.org/pdf/1909.02027v1) |
| R25 | `1912.03804` | Women in ISIS Propaganda: A Natural Language Processing Analysis of Topics and Emotions in a Comparison with Mainstream Religious Group | [arXiv v1](https://arxiv.org/pdf/1912.03804v1) |

### 25.2 二十题与固定顺序

从官方 JSON 按 `QASPER paper_id + question_id` 提取原始 `question`，保留大小写、拼写、语法和空白。表中观察重点只用于生成后评价，不进入前置规划、业务消息、检索参数或工具指令。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q61 | R21 | How do they perform multilingual training? | `5cb610d3d5d7d447b4cd5736d6a7d8262140af58` | 语言切换、训练单位和参数共享等必要机制有据，不套用通用多语言训练说明 |
| D3-Q62 | R21 | What languages are evaluated? | `c32adef59efcb9d1a5b10e1d7c999a825c9e6d9a` | 评价语言列全，区分训练组合、任务语言与实际报告范围 |
| D3-Q63 | R21 | Does the model have attention? | `b9d168da5321a7d7b812c52bb102a05210fe45bd` | 明确判断及注意力的具体作用位置，不能仅凭 encoder-decoder 名称推断 |
| D3-Q64 | R21 | What is MSD prediction? | `32a3c248b928d4066ce00bbb0053534ee62596e7` | 缩写、预测对象及辅助任务作用对应，不把少数标签示例当完整定义 |
| D3-Q65 | R22 | How many labels do the datasets have? | `6aa2a1e2e3666f2b2a1f282d4cbdd1ca325eb9de` | 分清类别数与已标注样本数的歧义，数量须对应各数据集及使用口径 |
| D3-Q66 | R22 | What is the architecture of the model? | `b46c0015a122ee5fb95c2a45691cb97f80de1bb6` | 基础网络、分类器与训练目标区分清楚，不以优化方法替代网络结构 |
| D3-Q67 | R22 | What are the baseline methods? | `5b7a4994bfdbf8882f391adf1cd2218dbc2255a0` | 必要基线列全并区分其作用，不把本文变体混作所有外部基线 |
| D3-Q68 | R22 | What are the source and target domains? | `9176d2ba1c638cdec334971c4c7f1bb959495a8e` | 域名称与实验分组、源到目标方向对应，不将历史数据集介绍都当本轮实验 |
| D3-Q69 | R23 | How do they calculate variance from the model outputs? | `f94b53db307685d572aefad52cd55f53d23769c2` | 区分估计量方差、Fisher 信息和 EGL 的关系，依实际公式解释，不套用输出样本方差公式 |
| D3-Q70 | R23 | How much data samples do they start with before obtaining the initial model labels? | `aa7d327ef98f9f9847b447d4def04889b4508d7a` | 区分初始有标注训练集与未标注候选池，小时数和实例数不可混用 |
| D3-Q71 | R23 | Which model do they use for end-to-end speech recognition? | `b8d7d055ddb94f5826a9aad7479b4a92a9c8a2f0` | 给出具体模型及必要结构，不将样本选择算法误作识别模型 |
| D3-Q72 | R23 | Which dataset do they use? | `551457ed34ca7fc0878c85bc664b135c21059b58` | 数据来源、标注状态及训练／选择／评估用途对应，不编造原文未给的公开数据集名称 |
| D3-Q73 | R24 | How was the dataset annotated? | `2c7e94a65f5f532aa31d3e538dcab0468a43b264` | 区分意图设计、样本收集和人工标注流程，说明必要任务与角色 |
| D3-Q74 | R24 | Which classifiers are evaluated? | `149da739b1c19a157880d9d4827f0b692006aa2c` | 分类器必要并列项完整，区分基础模型、商业系统和 out-of-scope 检测方案 |
| D3-Q75 | R24 | What is the size of this dataset? | `27de1d499348e17fec324d0ef00361a490659988` | 总样本、in-scope／out-of-scope、意图数和域数对应，不混用不同数据划分或变体 |
| D3-Q76 | R24 | Where does the data come from? | `cfcdd73e712caf552ba44d0aa264d8dace65a589` | 不同样本来源和众包任务对应，不将提示素材来源等同于直接收集的样本来源 |
| D3-Q77 | R25 | What conclusions do the authors draw from their finding that the emotional appeal of ISIS and Catholic materials are similar? | `f318a2851d7061f05a5b32b94251f943480fbd15` | 准确归属作者结论及研究范围，区分情绪得分相似与具体用词差异，不扩大到群体等同判断 |
| D3-Q78 | R25 | How id Depechemood trained? | `6bbbb9933aab97ce2342200447c6322527427061` | 区分作者复用的词典与其构建方法，矩阵／评分来源和转换关系忠实，保留原题 id 拼写 |
| D3-Q79 | R25 | How are similarities and differences between the texts from violent and non-violent religious groups analyzed? | `2007bfb8f66e88a235c3a8d8c0a3b3dd88734706` | 主题／情绪分析、归一化及比较对象对应，不将统计比较扩大为因果解释 |
| D3-Q80 | R25 | How are prominent topics idenified in Dabiq and Rumiyah? | `d859cc37799a508bbbe4270ed291ca6394afce2c` | 主题模型、选择依据与实际采用方法分清，保留原题 idenified 拼写 |

同论文四题均独立新会话，不传递前题答案、工具历史或准备事实。官方参考、gold evidence、预期数值／公式／表号／chunk 不作为业务输入，QASPER `full_text` 不替代真实入库检索。

### 25.3 必要准备与二十题真实运行

五篇固定 PDF 经现有 `import_runtime.import_pdf` 默认 `mineru-api` 入口准备，沿用当前 VLM／全文 OCR／公式／表格配置、分块和索引 profile。相同 PDF／API 方案已有 ready 或 bundle 则通过现有能力复用；缺少时允许必要下载、官方 API 解析和索引 embedding，不重建其他论文索引。单篇失败记录对应四题未执行，其他独立论文可继续；共享故障阻断后续时保存已有结果后停止，不自动换题、换版或换解析器。

按 Q61→Q80，各一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，实际执行正常前置规划、检索／阅读、准备、最终与原额度内重试／修复。这是二十题新的真实模型运行，不是离线重放；每题一次运行包含正常流程所需的多次 HTTP 请求。模型自主决定工具和停止，不强制读表、计算、耗尽额度或生成某种引用格式。

保持 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次请求 30 秒、五步／五次取证、既有网络重试一次／共享修复一次；embedding／重排沿用当前 profile，保存实际配置及提示／JS 版本。保留第 21 节引用兼容和现有自然语言／来源／历史／容量管理。执行助手是 GPT，不切换被测业务模型，不改业务代码、提示词或预算。

本批没有业务行为修改，复用第 21.7 节已通过且对应代码未变的验证；**不重跑离线测试或 Q50 重放，不跑语法扫描／全量回归，不新增 ready 校验、连通性探测、独立 judge、fixed_rag、固定证据实验、格式扫描器或来源校验层**。二十题正常结果用于本批观察，不为复现旧问题另加实验。

### 25.4 普通产物与接续

目录固定为 `artifacts/v3/d3-qa-q61-q80-20261028/`，stage 为 `d3-qa-q61-q80`，会话／提交 ID 为 `d3-qa-q61-q80-20261028-q61` 至 `d3-qa-q61-q80-20261028-q80`。`input.json` 保存无 gold 原问、来源／实际版本配对和公开配置；`results.json` 保存实际状态、停止原因、原生日志路径、用量和简短评价。完整逐题 JSON／Markdown 继续由 runtime 写入 `archive/run_logs/d9/`，不复制历史，不另建验证报告。

复用 `tmp/d3_prepare_q51_q60.py`、`tmp/d3_build_q51_q60_input.py`、`tmp/d3_qa_q51_q60_run.py` 的现有方式，必要时仅新增本批窄入口并替换清单、stage、目录和 ID；注意本批是五篇各四题、共二十题，不能沿用旧入口的每篇两题或十题终点。不运行旧 main 或覆盖旧产物，不建设通用框架。沿用现有尝试状态，请求前保存；已尝试题只整理，接续未尝试题，失败／中断／内容不足均不自动补跑，不追加追问或替代题。

### 25.5 事后评价与结束条件

生成后结合实际版本原文、展示材料及官方各份参考评价，运行状态、核心内容和引用交付分开记录。正确说明证据不足可以通过，不强求全部 answered 或肯定作答；参考分歧或明显笔误按实际原文说明。Q62 参考存在可回答性分歧；Q65 的 labels、Q70 的初始数据范围及 Q69 的 variance 均可能有解读差异，应保留模型采用的口径，不用隐藏参考强制唯一解释。

观察必要并列项、主体／条件、数字／单位／数据集／实验设置及公式含义是否对应。若计算，分别评价输入、口径和算术；不要求每题调用 JS。Q37／Q57 类问题若重复，只依据日志说明目录和材料是否可达、模型是否识别缺口及何处遗漏，不中途改提示、修复或补跑。

引用直接看原生日志已有的原始输出、交付正文、`citations / evidence_sources`，出现次数与去重来源分计，零引用不因空 valid 判交付成功；无 claims 的旧指标不适用。沿用现有请求／tokens／报告耗时、搜索／阅读、查询 embedding、重排、重试／修复及 JS 统计，入库与问答、索引与查询 embedding 分开，计费缺失如实注明，不为统计追加请求。

这是五篇论文二十道公开 dev 原题的定向观察，不据此推断总体准确率、稳定性或不同批次的速度变化。二十题各一次或明确共享故障停止后，补记第 25.6 节并结束；不自动修复、加预算、重跑旧题或开始下一批。

### 25.6 执行结果（2026-10-28）

**五篇准备：**五个固定v1 PDF经默认`import_runtime.import_pdf` / `mineru-api`全部ready，本次为五个新API批次；沿用当前VLM/全文OCR/公式/表格配置、分块和索引profile，未换版本或重建其他论文索引。

| 代号 | 固定版本 | 实际 paper_id / parse_revision | chunks | API batch |
|---|---|---|---|---|
| R21 | `1809.01541v1` | `local_0ef5ad5decec4a3f94af3f7ee5bf9a20` / `r_eca9a99724a80c7d` | 29 | `7d09bde1-9c31-4fed-b98f-c77c6da0e000` |
| R22 | `1809.00530v1` | `local_5612dda0dc514a9ab1cd97170ba30d07` / `r_aa1f06de4501c4b5` | 78 | `34898ace-c2d6-46d5-ac0d-3047151708a6` |
| R23 | `1612.03226v1` | `local_8e13f9a853d545078f7d3bb22d7904c1` / `r_9531dc8dea728049` | 22 | `9b89edbc-1b36-4384-885a-e2a1559564ab` |
| R24 | `1909.02027v1` | `local_ce93acf022934a55acd85ec96e71b46a` / `r_5b1d09c2da7bb2de` | 28 | `ab2cb376-0409-4c8c-a105-579f4fae0628` |
| R25 | `1912.03804v1` | `local_02bb467b34a0473199041669a8b4ba69` / `r_5c460c159818e835` | 39 | `f45e2919-47e4-4512-a90d-0b592d174c99` |

入库合计 **196 chunks、21次索引embedding / 53,657 tokens、237.748秒导入报告耗时**；索引embedding请求耗时16.030秒包含于导入，PDF下载耗时未单列。实际配对和公开配置保存在input，未预造ID或增加ready校验。

**配置与执行：**Q61→Q80二十题各一次完整真实运行，独立会话、空历史、`mode="agent"`、`library_mode=True`，stage、目录及提交/会话ID按第25.4节。仍为`deepseek-flash`、1,048,576上下文、temperature 0.2、4,096输出、单次30秒、五步/五次取证、网络重试一次/共享修复一次；embedding `qwen3.7-text-embedding` 1024维、重排`qwen3-rerank`和当前profile。提示`v2.23-optional-final-calculation-v1` / `v3.1-optional-final-calculation-v1`，JS `mini-racer-0.12.4` / V8 12.6.228.18。未改业务代码、提示、模型或预算；复用第21.7节已有验证，没有旧main、旧题重跑、离线测试、扫描、额外探测或judge。

**结果：20/20 completed / answered，0运行失败/未执行；核心内容17通过、3部分通过（Q66/Q71/Q79）。**Q71、Q72以`no_reliable_evidence_direction`停止，其余为`answered`；Q72内容不足判断正确，不能仅按停止原因扣分。二十题原生引用及来源均非空、定位valid；引用交付单独评价为**19通过、1部分（Q69编号语义碰撞）**，不等同20题引用语义均正确。评价由本GPT对话生成后结合实际v1原文、展示材料与官方各份参考完成。

| 题号 | 核心内容/引用交付评价 | 原生引用/来源 | 原生日志 |
|---|---|---|---|
| D3-Q61 | 通过：按minibatch随机切换语言，共享MSD辅助解码器；随机二至三语言组、不传语言ID和单语finetuning对应原文。 | 8/4 | [JSON](../../archive/run_logs/d9/agent_20261028_070827_754761_a1c2f2cc8d58.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_070827_754761_a1c2f2cc8d58.md) |
| D3-Q62 | 通过：DE/EN/ES/FI/FR/RU/SV七语言代码完整；未展开全称而称不能给名称过度保守，参考不可答标签不覆盖实际表格依据。 | 6/6 | [JSON](../../archive/run_logs/d9/agent_20261028_070850_336685_4e216e0a4753.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_070850_336685_4e216e0a4753.md) |
| D3-Q63 | 通过：明确attention，说明字符LSTM解码、encoder states及本文图示；未仅凭encoder-decoder名称推断。 | 6/5 | [JSON](../../archive/run_logs/d9/agent_20261028_070909_800028_a3013f18c5f3.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_070909_800028_a3013f18c5f3.md) |
| D3-Q64 | 通过：MSD缩写、目标tag、逐component生成、辅助损失与仅Track1条件完整；另有两次unknown_tool，最终在原额度内完成。 | 11/5 | [JSON](../../archive/run_logs/d9/agent_20261028_070929_018756_a23265851ad7.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_070929_018756_a23265851ad7.md) |
| D3-Q65 | 通过：明确labels按类别数解读，新数据三分类、旧Amazon二分类；不强制参考的已标注实例数口径。 | 6/5 | [JSON](../../archive/run_logs/d9/agent_20261028_071001_367674_b6b7b08d6979.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071001_367674_b6b7b08d6979.md) |
| D3-Q66 | 部分：CNN encoder+softmax与训练目标正确，但未读已知§4.1，遗漏词嵌入→单层卷积→max-over-time pooling的实际架构。 | 12/6 | [JSON](../../archive/run_logs/d9/agent_20261028_071016_444946_6c732d555a18.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071016_444946_6c732d555a18.md) |
| D3-Q67 | 通过：Naive/mSDA/NaiveNN/AuxNN/ADAN/MMD六基线完整，与DAS等本文变体分开。 | 11/3 | [JSON](../../archive/run_logs/d9/agent_20261028_071036_064073_38432f9e70da.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071036_064073_38432f9e70da.md) |
| D3-Q68 | 通过：新小规模、large-scale与旧Amazon域池分组正确，source有标签/target无标签及set1方向明确；未强制枚举全部任务矩阵。 | 8/6 | [JSON](../../archive/run_logs/d9/agent_20261028_071053_961403_5b8df49794a8.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071053_961403_5b8df49794a8.md) |
| D3-Q69 | 内容通过、引用部分：Fisher渐近方差、trace代理、概率加权梯度平方/top-K关系正确；三个文献编号与当前句柄发生语义碰撞。 | 14/8 | [JSON](../../archive/run_logs/d9/agent_20261028_071111_291498_0f4fd1b9baff.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071111_291498_0f4fd1b9baff.md) |
| D3-Q70 | 通过：初始base-model集190小时约100K，与1700小时约1.1M未标注池分开，口径明确。 | 4/2 | [JSON](../../archive/run_logs/d9/agent_20261028_071136_044793_84a53738e736.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071136_044793_84a53738e736.md) |
| D3-Q71 | 部分：只给一般RNN而称实验模型不能确定；漏读§3明确的两层2D卷积+七层双向recurrent+softmax/CTC。 | 4/4 | [JSON](../../archive/run_logs/d9/agent_20261028_071152_773945_c06b3536fc0c.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071152_773945_c06b3536fc0c.md) |
| D3-Q72 | 通过：有标注训练/未标注选择池/验证/测试规模和用途正确，未编造未具名数据的公开语料库名称；正确不足可通过。 | 4/1 | [JSON](../../archive/run_logs/d9/agent_20261028_071214_033813_b58b316c8458.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071214_033813_b58b316c8458.md) |
| D3-Q73 | 通过：scoping众包、人工归并intent、rephrase/scenario及OOS专家核查对应，区分采集与标注。 | 11/4 | [JSON](../../archive/run_logs/d9/agent_20261028_071231_409835_d1fd63f2aa30.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071231_409835_d1fd63f2aa30.md) |
| D3-Q74 | 通过：SVM/MLP/FastText/CNN/BERT/DialogFlow/Rasa名单完整，区分classifier与OOS方案。 | 6/5 | [JSON](../../archive/run_logs/d9/agent_20261028_071254_104991_940678f316df.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071254_104991_940678f316df.md) |
| D3-Q75 | 通过：23700总量、22500 in-scope/150 intents/10 domains、1200 OOS正确，full与变体分开。 | 5/3 | [JSON](../../archive/run_logs/d9/agent_20261028_071311_855044_41a4e38b750f.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071311_855044_41a4e38b750f.md) |
| D3-Q76 | 通过：众包来源及OOS worker mistakes/scoping/scenario说明正确，Quora/Wikipedia只是prompt题材；未取得in-scope详细流程作为范围限制记录。 | 7/3 | [JSON](../../archive/run_logs/d9/agent_20261028_071329_231588_751a22dca85a.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071329_231588_751a22dca85a.md) |
| D3-Q77 | 通过：两选定女性材料语料inspired高/afraid低而具体词不同，作者结论与用途归属准确，不扩大到群体等同。 | 8/3 | [JSON](../../archive/run_logs/d9/agent_20261028_071348_315363_133bf09955ef.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071348_315363_133bf09955ef.md) |
| D3-Q78 | 通过：约23.5K Rappler新闻众包情绪评分和矩阵构词典、八类0–1分，与本文POS匹配复用分开；未照抄参考矩阵笔误。 | 8/3 | [JSON](../../archive/run_logs/d9/agent_20261028_071410_646139_c5d87d07823f.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071410_646139_c5d87d07823f.md) |
| D3-Q79 | 部分：比较对象、词频/NMF/Depechemood正确，但遗漏按语料词数归一化、逐文章情绪聚合与归一化。 | 13/7 | [JSON](../../archive/run_logs/d9/agent_20261028_071432_499600_adbdc2d4963f.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071432_499600_adbdc2d4963f.md) |
| D3-Q80 | 通过：区分试用LDA与最终NMF，按coherence选10主题并人工命名，未把词频辅助当主题模型。 | 7/4 | [JSON](../../archive/run_logs/d9/agent_20261028_071458_771961_6a5dda9b5b4e.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_071458_771961_6a5dda9b5b4e.md) |

**具体问题：**Q66的`p5_c3/parent10`（CNN Encoder Implementation）、Q71的`p3_c3/parent7`（Experiments）及Q79的`p11_c4/parent19`、`p12_c2/parent20`（Content/Emotion Analysis）均已入库，相关目录已在实际决策请求中送达。Q66准备时识别§4.1未读但以高层目标收尾；Q71两次搜索后声称无具体阅读线索，未读实验正文；Q79准备时认为比较方法已覆盖，未取得归一化段。它们是选择/取得/准备覆盖的遗漏，与Q37/Q57同类材料利用问题有关；不因工具次数少本身判错，也不把局部未读到说成全文没有。未中途修复、补抽样或加预算。

Q69自然触发普通编号兼容：原始最终响应在文献提及处写`[8]`、`[5]`、`[4]`，实际交付规范化为当前`[ID:8]`、`[ID:5]`、`[ID:4]`，保留14次原生引用/8来源且未占修复额度。但ref5实际为`p3_c5`、正文仅“(b) CER on dev set”，不支持beam-search文献；ref8为引言、ref4为摘要，也不是所提论文书目条目的身份。因此格式识别成功与来源支持正确须分开，本次记录为**文献编号/当前句柄语义碰撞**。其余十九题原始最终输出与`answer.text`相同，使用标准标记。没有另建格式扫描器、语义审核器或来源校验层。

Q64两次将`prepare_answer`当native工具调用，返回`invalid_arguments/unknown_tool`，之后改用正常准备动作并完成；原有步骤/取证共4/5、3/5，未触发网络重试或共享修复。它解释了总取证33次与30次搜索+1次本地阅读的差额。Q62全称未展开及部分未问细节的保守限定、Q76未取得in-scope详细流程等另在results记录；Q65/Q70保留明确、合理的歧义解读，不以隐藏参考强制唯一口径。Q69的渐近方差表述应保留Eq.(3)的sqrt(n)缩放语境；没有数值计算。

**实际用量：**问答 **84次聊天请求、1,139,145 tokens、411.204秒报告耗时**；30次搜索、1次本地阅读、2次无效`prepare_answer`工具调用、44个自主步骤、33次取证。查询embedding **30次 / 793 tokens / 69.133秒**，重排 **30次 / 报告188,105 tokens / 12.372秒**，网络重试/共享修复 **0/0**；JS **0次、0秒**。正文合计 **31,577字符**；原生引用 **159次出现 / 逐题去重来源之和87 / 全批去重来源64**，`evidence_sources`逐题计数之和87（包含Q69形式绑定但语义碰撞的来源）。无claims旧指标不适用。各类耗时不互斥，不重复相加；入库/问答及索引/查询embedding分开。计费金额未提供，记缺失而非零，未为统计追加请求；逐题详细统计见results。

**产物：**[input.json](../../artifacts/v3/d3-qa-q61-q80-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-q61-q80-20261028/results.json)，完整逐题JSON/Markdown使用上表runtime原生日志。窄入口为`tmp/d3_prepare_q61_q80.py`、`tmp/d3_build_q61_q80_input.py`、`tmp/d3_qa_q61_q80_run.py`，准备状态`tmp/d3_q61_q80_prepare.json`。未覆盖历史或新增验证报告；本批结束，不自动修复、加预算、重跑或开始下一批，不据本批不同新题宣称总体准确率/稳定性提升。

## 26. 给另一个 GPT 对话的 Q61～Q80 测试提示词

复制下方代码块内容作为新对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 执行d3-plan.md第25节Q61～Q80二十题真实测试，只做必要论文准备、每题一次完整运行和结果回写，不增加额外测试或校验。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能，遵守Stop Ladder和AGENTS.md用户四问。请在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第21.7、23.6和25节，实际执行本批；第1～24节旧提示仅作历史，不运行旧main或重跑旧题，保留工作区已有修改。

本批五篇论文各四题，共二十题，固定题号D3-Q61～D3-Q80。按第25.2节paper_id/question_id，从eval/qasper/raw/qasper-dev-v0.3.json提取官方原始question，保持大小写／拼写／语法／空白，不自行出题或润色。题单已在规划中对照历史，不另做排重、题单校验或预检程序。只传原问、实际本地版本配对和普通完整回答要求；观察重点、官方参考、可回答性标签、gold evidence、预期数值／公式／表号／chunk及工具动作不注入业务消息或检索参数，不用QASPER full_text替代真实入库检索。

用户允许必要新论文入库。固定R21 1809.01541v1、R22 1809.00530v1、R23 1612.03226v1、R24 1909.02027v1、R25 1912.03804v1，PDF来源见第25.1节。相同固定PDF／API方案已有ready或bundle则通过现有能力复用；缺少时下载并用import_runtime.import_pdf默认mineru-api入口解析／索引，保持当前配置和profile，实际paper_id/parse_revision取ready返回，不预造ID、不重建其他论文索引。单篇失败记录对应四题未执行，其他论文可继续；共享故障阻断后续时保存结果后停止，不换题、换版或换解析器，不另发连通性请求。

二十题各一次完整真实d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，按Q61→Q80顺序、独立新会话。同论文四题之间不传前题答案、工具历史或准备事实。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次请求30秒、五步／五次取证及既有网络重试一次／共享修复一次，embedding与重排沿用当前profile，记录实际配置和提示／JS版本。GPT负责执行，被测业务模型不切换；不改业务代码、业务提示或预算，工具与停止由模型在现有流程内决定，不强制读表、计算、耗尽额度或输出特定引用格式。

使用artifacts/v3/d3-qa-q61-q80-20261028/的普通input.json/results.json，stage=d3-qa-q61-q80，会话／提交ID为d3-qa-q61-q80-20261028-q61至-q80；完整JSON／Markdown由runtime写入archive/run_logs/d9/。复用tmp/d3_prepare_q51_q60.py、tmp/d3_build_q51_q60_input.py、tmp/d3_qa_q51_q60_run.py的现有方式，必要时只加本批窄入口，替换五篇四题清单、stage、目录和ID，确保终点为Q80，不沿用旧的每篇两题或十题终点，不运行旧main或覆盖历史。沿用尝试状态，请求前保存，已有尝试只整理、接续未尝试题；失败、中断、内容不足或未用某工具均不补跑，不追加追问或替代题。

本轮真实调用只包括必要入库、二十题正常流程及原额度内重试／修复。第21.7节已通过且对应代码未变的验证直接复用，不重跑离线测试、Q50重放、语法扫描或全量回归；不增加排重／ready校验器、模型／embedding探测、judge、fixed_rag、固定证据实验、独立格式扫描或来源校验。沿用已有引用兼容与检查即可，正常二十题已经承担本批观察，不为触发某分支多加请求。不新增审计、哈希、manifest、保护层、通用框架或独立验证报告。

生成后按第25.5节结合实际原文和官方各份参考作内容评价，运行状态、核心覆盖和引用交付分开。可回答性分歧、题意歧义或参考笔误按实际证据说明，不用隐藏参考口径强制判错，正确说明不足可以通过。关注并列项、数字／单位／数据集／设置、条件及公式关系；若计算，区分输入、口径和算术。重复出现Q37/Q57类遗漏时只根据已有日志指出环节，不中途修复、改提示、加预算或补抽样。引用直接用原始输出、answer.text和citations/evidence_sources观察，出现次数与去重来源分计，不把空valid当交付成功，无claims的旧指标不适用。

沿用现有统计记录实际请求、tokens、报告耗时、搜索／阅读、查询embedding、重排、重试／修复和JS；必要入库与问答、索引与查询embedding分开，计费缺失如实说明，不为统计追加请求。完成二十题各一次或明确共享故障停止后，在d3-plan.md第25.6节简要补记五篇准备、二十题逐题评价、实际用量及普通产物链接，保持第26节提示词位于文末。最终向用户概括本批实际表现和具体问题，不重算历史成绩或宣称总体准确率提高。到此结束，不自动修复、重跑旧题或开始下一批。
```

## 27. 取消普通编号转换，并真实复测 Q50／Q69（2026-10-28）

状态：**已实施并完成三个指定方法及两题真实复测，结果见第27.6节**。用户已选择按 RAGFlow Agentic 的明确句柄约定处理引用，依靠模型遵守已有提示规范，普通 `[5]` 不再自动转成系统引用。本轮实施该最小改动，并将此前的 **Q50、Q69 各完整真实复测一次**。第 1～26 节及历史结果保留；本节取代第 21 节将所有普通 `[n]` 转换成 `[ID:n]` 的行为，后续执行使用文末第 28 节 GPT 提示词。

### 27.1 两个案例与本轮取舍

- **Q50 引用未交付：**[旧记录](../../archive/run_logs/d9/agent_20261028_055815_041591_16ee9ed6abd3.json)列对七种语言，但模型只写普通 `[1]` 等标记，原生引用／来源为 0。第 21 节曾通过自动转换使保存输出离线关联到来源；该历史结果保留，本轮不再将“自动恢复 7 次／5 来源”作为验收目标。
- **Q69 编号含义被改写：**[旧记录](../../archive/run_logs/d9/agent_20261028_071111_291498_0f4fd1b9baff.json)同时有当前证据 `[ID:n]` 和原论文书目 `[8]／[5]／[4]`。程序把后三者变成系统句柄，导致无关图注等被绑定为来源。应取消这类自动转换，保留书目编号原意。

按用户决定，系统仅将明确的 `[ID:n]` 作为本次证据引用，保留目前支持的带 ID 空白／数字格式规范化。普通 `[5]` 原样保存；**不新增缺引用检测、强制补引、额外模型修复或语义审核**。若 Q50 再次只输出普通编号，就如实记录引用未交付，不猜配来源、不补跑。这是本轮明确选择的处理边界，不预设两题一定引用通过。

### 27.2 参考实现与最小改动

参考本地 RAGFlow [Agentic 严格句柄扫描](E:/project/ragflow/internal/agentic_rag/citations.go:139)、[原有提示规范](E:/project/ragflow/conf/agentic_rag.yaml:48)及[先规范化再关联的入口](E:/project/ragflow/internal/service/agentic_reference.go:42)。该路径以 `[ID:n]` 和实际段落 `ref` 关联来源；通用 `CitationMarkerPattern` 接受普通 `[n]` 的行为不再用于本项目最终回答转换。参考仓库只读。

1. **[prose.py](../../paper_assistant/prose.py)：**将 `COMPAT_MARKER` 中可选的 `ID:` 前缀改为必需，保留现有 `[ID:n]`、`[ID: n]` 和标记内数字转换；普通 `[5]`、`[99]`、普通数字字符标记保持原样。同步来源注释／函数说明，明确本轮采用 Agentic 的显式句柄边界。不额外扩展括号、ref 别名或其他引用协议。
2. **现有调用与消费者：**继续在 `request_prose_final` 的同一入口规范化、验证并发布；原始响应保留，`answer.text`、引用位置和真实来源仍对应同一交付正文。普通编号不进入 `citations / evidence_refs / evidence_sources`，也不因与当前 ref 恰好同号而获来源权限。页面／导出／历史／评价直接消费现有结构，无必要不改业务代码。
3. **提示及预算：**保留已有要求使用 `[ID:n]` 的业务提示，不追加“必须补齐引用”等指令，不修改提示版本或预算。未知显式 `[ID:99]` 仍走现有一次共享修复；普通 `[99]` 不再被当成未知系统引用，不触发新修复。正常无引用回答沿用原有行为，空 valid 不代表引用已交付。

本轮只收紧这一处转换及必要测试预期，不改证据注册／编号、来源检查、充分性、检索／阅读策略或工具协议，不处理 Q64、Q66、Q71、Q79 等其他问题。不新增校验器、判定器、审计、哈希或保护层，也不为本轮手工重算 PDF／正文哈希。

### 27.3 仅同步并运行三个已有测试方法

三个方法中目前均有依赖“普通 `[n]` 自动转换”的既有 fixture 或预期，需要一起同步。只在原方法内使用通用本地材料／mock，覆盖本次行为变化；不另建测试文件或评测框架，不嵌入两题参考答案。

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：调整现有格式兼容场景，验证混合正文中普通书目 `[1]` 保留、明确 `[ID: 2]` 正常绑定，原始响应与交付正文／引用位置一致；纯普通编号原样交付但无原生引用、无新增请求或修复。保留显式未知 `[ID:99]` 的一次共享修复和耗尽场景，将旧 `[99]` 应触发修复的预期改为普通文本语义，不删除该行为覆盖。幂等、数字转换和正常无标记场景复用，不重复扩大检查。
2. `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`：将既有 prose fixture 中需要成为系统引用的标记改为明确带 ID 的形式，普通书目编号保留为正文；确认页面、下载、导出和历史仍消费同一份正文／来源，书目号不增加来源计数。复用既有旧 claims 与 fixed_rag 场景，不改 UI 或另加页面测试流程。
3. `scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately`：同步现有 fixture，让需要统计的三次引用均为显式句柄，普通书目编号不增加系统引用；重复出现／去重来源分计、零引用 ratio=None、旧 claims 与已有失败统计保持原行为。不新增评分 schema 或语义评分器。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately
```

方法失败或发现具体跨模块影响才扩大到直接相关方法；不运行整个模块／目录／全量回归。已通过且对应代码未变的验证复用，不因结果补记重复执行。离线测试不发真实模型、embedding 或重排请求，也不另做 Q50／Q69 历史输出重放；后面的两题真实复测直接承担本轮运行观察。

### 27.4 原题原版本，各一次完整真实复测

从下列历史 input 按题号取得原始问题和版本配对，不根据评价文本重新生成题目，不重新下载、OCR、解析、索引或入库。

| 题号 | 输入来源及官方原问 | 固定本地版本 |
|---|---|---|
| D3-Q50 | [旧 input](../../artifacts/v3/d3-qa-q41-q50-20261028/input.json)；`Which 7 Indian languages do they experiment with?`；question_id `75df70ce7aa714ec4c6456d0c51f82a16227f2cb`，QASPER `2002.01664` | `local_599a9a07261e4e3bb80dd801c2d440fd / r_4a1440d302194feb` |
| D3-Q69 | [旧 input](../../artifacts/v3/d3-qa-q61-q80-20261028/input.json)；`How do they calculate variance from the model outputs?`；question_id `f94b53db307685d572aefad52cd55f53d23769c2`，QASPER `1612.03226` | `local_8e13f9a853d545078f7d3bb22d7904c1 / r_9531dc8dea728049` |

三个指定方法通过后，按 Q50→Q69，各一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，独立新会话。这是两题新的真实模型运行，正常前置规划、检索／阅读、准备／最终、查询 embedding／可选重排及原额度内重试／修复均在本轮范围内；不是固定旧输出的重放。只传原问、实际版本配对与普通完整回答要求，不传旧答案、诊断、参考、预期编号／chunk、书目冲突说明或强制引用格式。

保持 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、单次 30 秒、五步／五次取证及原网络重试一次／共享修复一次，embedding／重排沿用当前 profile；保存实际配置与提示／JS 版本。模型自主决定检索、阅读、计算、准备及最终形式，不为触发某分支强制输出 `[5]` 或 `[ID:n]`。

目录为 `artifacts/v3/d3-explicit-citation-q50-q69-20261028/`，stage 为 `d3-explicit-citation-q50-q69`，会话／提交 ID 分别为 `d3-explicit-citation-20261028-q50`、`d3-explicit-citation-20261028-q69`。仅用普通 `input.json / results.json`，完整逐题日志由 runtime 保存至 `archive/run_logs/d9/`。复用现有顺序调度和尝试状态，必要时只加一个本轮窄入口，例如 `tmp/d3_explicit_citation_q50_q69_run.py`；不运行旧批次 main。已有本轮尝试只整理，接续未尝试题，失败／中断／缺引用均不自动补跑，不追加追问或额外模型请求。已有版本不可用或共享故障时如实记录，不重入库。

### 27.5 两题评价与停止条件

- **Q50：**分别评价七语言内容是否覆盖、是否主动使用明确系统句柄及实际来源是否绑定。若再次只有普通编号，记录内容情况和引用未交付；不恢复自动猜配、不新增格式修复、不为通过补跑。
- **Q69：**看方差／Fisher／EGL 的核心解释及尺度条件是否准确；区分原论文书目编号与本次证据句柄。普通书目号保留、明确系统引用指向实际支持原文，才算本题引用交付通过。若模型主动把书目号写成 `[ID:n]` 而选错来源，如实记为模型引用偏差，不用新审核器兜底。

新一轮检索顺序和编号可能变化，**不要求复现旧 ref=5、旧 7/5 或旧 14/8 计数**，只按本轮实际映射评价。没有自然出现普通编号时，记录该分支未在真实输出触发，不据两题成功外推稳定性。模型是否遵守格式与程序是否保留普通编号，是两个分别记录的观察。

沿用现有统计记录真实请求／tokens／报告耗时、搜索／阅读、查询 embedding、重排、网络重试／共享修复、JS 及引用出现／来源去重数；费用缺失如实注明。引用定位 valid 不代替语义判断，空检查不算交付通过。仅同题比较旧运行，不重算原十题／二十题成绩，不覆盖历史，不额外生成报告或计费／连通性请求。

完成最小改动、三个指定方法及两题各一次复测后，在第 27.6 节补记并结束；明确故障阻断时记录实际完成部分，不反复重启。不顺带处理其他问题、加预算或开始新题批次。

### 27.6 实施与真实复测结果（2026-10-28）

**实际改动：**[prose.py](../../paper_assistant/prose.py) 将 `COMPAT_MARKER` 的 `ID:` 从可选改为必需；保留 `[ID:n]`、`[ID: n]` 和标记内两类阿拉伯数字转换，普通 `[5]`、`[99]` 及普通数字字符编号保持原样。注释改为 RAGFlow Agentic 显式句柄边界，沿用先规范化再验证/发布及当前从1开始的编号。`agent.py`、来源检查、提示/版本、模型/预算均未改；没有缺引用检测、强制补引或新增修复请求。

**三个指定现有方法：全部通过，Ran 3 tests in 36.889s，OK。**

| 方法 | 实际覆盖/结果 |
|---|---|
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 通过。混合书目号与显式句柄；普通 `[1]/[99]/[۲]` 原样、零引用且不增加请求/修复；ID空白/数字变体、幂等、原始响应/交付正文/位置、显式未知99的一次修复与共享额度耗尽。旧普通99场景保留为普通文本语义。 |
| `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations` | 通过。4处显式引用/2来源，普通书目 `[1]/[99]` 保留且不增来源，页面、JSON下载、Markdown、历史一致；旧claims/fixed_rag保留。 |
| `scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately` | 通过。三处显式引用/两来源分计，普通书目号不增加系统引用；零引用ratio=None，旧claims和失败统计不变。 |

仅运行以上三方法；离线没有真实聊天、embedding或重排请求，未扩大方法/模块/全量，未另做历史输出重放或手工哈希。之后未改对应代码，结果直接复用。

**两题真实运行：**三个方法通过后，从指定历史input取得原问、question_id及固定版本；按Q50→Q69各一次独立完整 `mode="agent"`、`library_mode=True`、空历史运行，均 **completed/answered，stop_reason=answered**。复用现有R15/R23 ready配对，下载/OCR/解析/索引/入库均0。实际配置仍为 `deepseek-flash`、1,048,576上下文、temperature 0.2、4,096输出、单次30秒、五步/五次取证、原网络重试一次/共享修复一次；embedding `qwen3.7-text-embedding` 1024维和重排 `qwen3-rerank` 沿用原profile。提示 `v2.23-optional-final-calculation-v1` / `v3.1-optional-final-calculation-v1`，JS `mini-racer-0.12.4` / V8 12.6.228.18。未强制输出格式、编号或工具动作。

| 题号 | 核心内容 | 模型格式与实际引用支持 | 原生日志 |
|---|---|---|---|
| Q50 | 部分通过。表中七种语言全部列对，但仍把正文漏列Assamese当作冲突，开头/结尾断言无法确定准确集合。准备阶段还误称表中没有Malayalam；最终虽列全，错误不足结论仍延续。 | 主动使用显式ID，原始响应=交付正文；**5次引用/5来源**。本次ref5确为七语言Table 1，其他来源身份与各自正文/摘要/引言/结论对应，引用已交付。最终无普通编号，本题未自然触发普通号保留分支。 | [JSON](../../archive/run_logs/d9/agent_20261028_075939_643132_2c4f951a1637.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_075939_643132_2c4f951a1637.md) |
| Q69 | 通过。Fisher渐近方差、参数/损失的sqrt(n)尺度、trace代理、概率加权梯度平方、top-K beam/backprop关系有已展示原文支持。 | **未遵守显式句柄格式，引用未交付：0次/0来源**。原始最终输出全部是普通数字号，既有书目 `[6]/[8]/[5]/[4]`，也有用于当前证据的 `[3]/[1]/[10]/[9]`；程序均原样保留，未猜配当前来源。`citations/evidence_refs/evidence_sources` 全空、`evidence_status=none`，valid是空检查，不能算交付通过；没有追加修复。 | [JSON](../../archive/run_logs/d9/agent_20261028_080006_882812_989ce11abf89.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_080006_882812_989ce11abf89.md) |

**同题观察：**旧Q50只有普通号/0来源，本次主动显式ID/5来源，但过度保守结论仍在。旧Q69把书目号自动绑定到无关来源，本次没有自动改义，却因模型也把系统引用写成普通号而没有原生引用。程序边界与模型遵守格式分别记录；本次不要求旧编号或计数、不恢复猜配、不补跑、不以两题外推稳定性，也不重算旧成绩。

**实际用量：**问答 **8次聊天、96,257 tokens、70.313秒报告耗时**；Q50为4次/43,361 tokens/27.047秒，Q69为4次/52,896 tokens/43.266秒。3次搜索、1次本地阅读、4个自主步骤、4次取证；查询embedding **3次/72 tokens/15.960秒**，重排 **3次/报告13,863 tokens/1.471秒**；网络重试/共享修复 **0/0**，JS **0次/0秒**。原生引用共 **5次出现/5个去重来源**，两题均为prose、无claims旧指标不适用。入库及索引embedding均0，各类耗时不互斥，不重复相加；单独计费金额缺失，未为统计发请求。

**产物：**[input.json](../../artifacts/v3/d3-explicit-citation-q50-q69-20261028/input.json)、[results.json](../../artifacts/v3/d3-explicit-citation-q50-q69-20261028/results.json)；窄入口 `tmp/d3_explicit_citation_q50_q69_run.py`，未运行旧main或覆盖历史。完整日志用上表runtime原生JSON/Markdown，没有另建验证报告/扫描器/审核器/哈希/快照。本轮结束，不顺带修其他问题、加预算或开始新题。

## 28. 给另一个 GPT 对话的显式引用修正与两题复测提示词

复制下方代码块内容作为新对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 按d3-plan.md第27节取消普通[n]自动转换，完成三个指定现有测试，再真实复测Q50和Q69各一次；不加校验层、哈希或模型修复请求。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能并遵守Stop Ladder及AGENTS.md用户四问。请在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第21.7、25.6和27节，实际完成本轮改动与两题真实复测。第1～26节旧提示作为历史，不运行旧main、不覆盖历史，保留工作区已有修改。

用户已决定按RAGFlow Agentic明确句柄约定、依靠模型遵守原提示：只认[ID:n]系统引用，普通[5]原样保留。RAGFlow参考E:/project/ragflow/internal/agentic_rag/citations.go:139、conf/agentic_rag.yaml:48和internal/service/agentic_reference.go:42，仓库只读。不要再套用通用CitationMarkerPattern将所有[n]转成系统句柄。Q50缺ID可能仍未交付引用，用户接受如实记录，不新增缺引用检测、强制补引、额外修复请求或语义审核。

最小修改paper_assistant/prose.py：COMPAT_MARKER的ID前缀由可选改为必需，保留现有[ID:n]、[ID: n]和标记内数字转换；[5]、[99]等普通编号保持原样，不因同号就绑定当前来源。不扩展其他格式协议，更新必要说明即可。沿用agent.py现有统一规范化→验证→发布顺序，原始响应保留，正文和引用位置对应同一交付文本；来源编号、白名单和检查不变。显式未知[ID:99]仍按原一次共享额度修复，普通[99]不再触发系统引用错误。不改业务提示／版本、模型或预算，不顺带修Q64/Q66/Q71/Q79。

同步第27.3节三个既有方法的旧fixture／预期：scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records；scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；scripts.check_agent_evaluation.AgentEvaluationChecks.test_published_duplicate_citations_and_prior_intercepts_are_counted_separately。用通用本地mock覆盖普通书目与明确系统句柄混用、纯普通编号零引用且无额外请求、带ID变体正常规范化、显式未知编号原一次修复，以及现有页面／导出／历史／统计。旧[99]触发修复的预期改为普通文本语义，不删行为覆盖。只运行这三个现有方法；只有失败或具体跨模块影响才扩大，不跑整模块／目录／全量，不为凑数加测试。已通过且代码未变的验证复用，离线不发真实请求，不另做历史输出重放或新增扫描／校验／哈希／快照／审计。

三个方法通过后，从artifacts/v3/d3-qa-q41-q50-20261028/input.json取D3-Q50，从artifacts/v3/d3-qa-q61-q80-20261028/input.json取D3-Q69，保留原问、question_id及selected_versions。固定版本见第27.4节：Q50 local_599a9a07261e4e3bb80dd801c2d440fd/r_4a1440d302194feb；Q69 local_8e13f9a853d545078f7d3bb22d7904c1/r_9531dc8dea728049。复用ready版本，不下载／OCR／解析／索引或入库。只传原问、实际版本及普通完整回答要求，不传旧答案、诊断、参考、预期编号／chunk或强制格式，不用QASPER full_text替代检索。

按Q50→Q69各一次完整真实d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话；不是旧输出离线重放。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次30秒、五步／五次取证及原网络重试一次／共享修复一次，embedding／重排沿用现有profile，保存实际配置及提示／JS版本。工具及最终形式由模型自行决定，原额度内正常流程属于本轮范围，不发额外judge、fixed_rag、固定证据、连通性或计费请求。

使用artifacts/v3/d3-explicit-citation-q50-q69-20261028/的普通input.json/results.json，stage=d3-explicit-citation-q50-q69，会话／提交ID为d3-explicit-citation-20261028-q50和-q69；完整原生日志仍由runtime写入archive/run_logs/d9/。沿用顺序调度和尝试状态，必要时只新增tmp/d3_explicit_citation_q50_q69_run.py这类窄入口。请求前保存尝试，已有本轮尝试只整理，接续未尝试题；失败、中断、缺引用或部分回答都不补跑、不追加追问。版本不可用或共享故障时如实记录，不自动重新入库。

生成后按第27.5节分开评价核心内容、模型是否遵守格式和实际引用支持。Q50若仍全是普通编号，记录引用未交付，不恢复猜配、不增加修复或补跑。Q69原书目号应保留，系统引用应对应实际支持材料；模型主动用错误ID的语义偏差另记，不加审核器。新的检索编号／来源数可以变化，不要求旧ref5或7/5、14/8计数；未自然出现某种格式就说明未触发，不强制制造。citation_checks valid不是语义保证，空检查不是引用交付通过。

在d3-plan.md第27.6节简要补记实际改动、三个方法结果、两题内容／引用评价、用量及产物链接，保留历史和第28节文末位置。不重算旧批次成绩、不另建验证报告、不新增或手工重算PDF／正文哈希。完成后向用户说明真实完成情况，到此结束，不顺带修其他问题、加预算、重跑或开始新题。
```

## 29. 迁移 RAGFlow Agentic 引用链路，并真实复测 Q50／Q69（2026-10-28）

状态：**已完成，实际修改、两个指定方法及两题各一次真实复测见第29.7节。**按第30节 GPT 提示词执行。按链路实际需要修改相关调用方，不以改动行数或文件数限制实施。第1～28节及历史结果保留；本节接续第27节显式句柄边界，取代其“不改注册／编号／提示、不扩展带ID格式”的本轮限制，普通 `[n]` 不转换的决定继续有效。

### 29.1 依据与目标

现有 [source_refs](../../paper_assistant/prose.py:24) 在最终作答时按 `shown_evidence` 当前顺序生成数字 `ref`；自主检索／阅读和 `prepare_answer` 主要使用 `chunk_id`。本轮目标是让模型从首次阅读原文到准备事实、最终作答，始终使用同一个证据句柄，不在最终阶段重新编号。

第27.6节最新真实结果是：Q50主动写显式ID，交付5次引用／5来源，但内容仍有错误的不足结论；Q69内容通过，最终全部使用普通数字号，交付0引用／0来源。记录分别见 [Q50](../../archive/run_logs/d9/agent_20261028_075939_643132_2c4f951a1637.json) 和 [Q69](../../archive/run_logs/d9/agent_20261028_080006_882812_989ce11abf89.json)。当前缺少贯穿取证过程的数字身份是可改进点，不能据此预先断言它是模型漏写ID的唯一原因，也不预设迁移后两题一定通过。

直接参考本地 RAGFlow Agentic 的以下实现，参考仓库只读：

- [EvidenceRegistry](E:/project/ragflow/internal/agentic_rag/evidence_registry.go:38)：同一运行内按首次展示顺序登记，同一原文块重复展示保持编号。
- [检索返回](E:/project/ragflow/internal/agentic_rag/helper.go:583)与[阅读返回](E:/project/ragflow/internal/agentic_rag/helper.go:728)：原文旁直接附带 `ref`。
- [提示约定](E:/project/ragflow/conf/agentic_rag.yaml:48)：最终 `[ID:n]` 的 n 来自工具返回的 ref。
- [规范化入口](E:/project/ragflow/internal/service/agentic_reference.go:52)、[格式规范化](E:/project/ragflow/internal/service/citation.go:350)及[严格扫描／解析](E:/project/ragflow/internal/agentic_rag/citations.go:139)：先规范格式，再识别明确句柄并查运行内映射。

移植上述机制并适配项目的 Python、JSON 和既有来源检查；不迁移 RAGFlow 的整套检索框架、强制深读策略或其他问答协议。

### 29.2 注册表的生命周期与存储

**一次提问生成一条回答，使用一张内存注册表。**同一聊天的下一问另建，不同论文在同一次问答内共用本轮编号空间；不是每篇论文一张永久编号表，也不是整个聊天共用一张表。

注册表绑定本次 Agent 调用，采用现有 `(paper_id, parse_revision, chunk_id)` 来源身份，维护身份→ref与ref→身份映射；保留项目从1开始的编号。注册表对象通过本轮调用／显式参数共享，不能随 context 的 `deepcopy` 被复制成多份独立计数器。上下文和请求只携带普通可序列化的 ref 字段。

问答完成后运行对象即可释放。既有原生请求记录保存各阶段展示的 ref，最终 `answer.text / citations / evidence_refs / evidence_sources` 保存已交付正文与来源关系，继续随现有 JSON／Markdown 运行记录落盘，不另建注册表数据库、全库固定引用号或缓存服务。当前页面聊天依赖 `session_state`，新页面会话没有从磁盘恢复聊天的入口；本轮不增加聊天持久化或恢复功能。

### 29.3 贯通实施

1. **注册与展示出口。**新增或在合适模块实现职责明确的 `EvidenceRegistry`，在本轮 Agent 入口创建并传入实际原文展示链路；与已有负责来源限定的 `source_registry` 区分。只有实际提供的原文才形成可引用证据，标题、阅读目录、parent、候选位置及前置检索规划用的主题材料不因登记功能获得引用权限。重复搜索、展开同块、调整排序都沿用已分配 ref；新原文领取新号，旧号不回收给其他原文。
2. **搜索／阅读统一输出。**贯通 [agent.py](../../paper_assistant/agent.py)、[context.py](../../paper_assistant/context.py:414)、[agent_prompt.py](../../paper_assistant/agent_prompt.py:733) 及 [evidence_reading.py](../../paper_assistant/evidence_reading.py) 的必要调用。保留现有 JSON 表达，在 `evidence_sections` 的实际正文／摘要／表格块旁增加同一个 `ref`，原有 `chunk_id` 继续承担读取与定位身份；工具观察若指向已展示原文，也使用该 ref。上下文合并、排序、重复取证、增量原文回放及修复都携带一致编号。新增字段参与现有消息容量计算，不绕过 `fit_agent_request`；最终保留的原文决定当前引用权限，登记过不等于当前仍可引用。
3. **准备动作使用同一ref。**将本轮自主 Agent 的模型侧 `prepare_answer` 来源协议明确为 `citation_refs: [9]`，摘录使用 `evidence_quotes: [{"ref": 9, "quote": "连续原文"}]`。在现有动作解析入口结合本轮映射转换为内部 `Claim.citation_ids` 和 `EvidenceQuote.chunk_id`，继续使用已有处理与原文摘录关系；未知或本次不可引用的 ref 接入现有动作／引用错误及共享修复流程，不猜测来源。必要修改 [agent_actions.py](../../paper_assistant/agent_actions.py:77)、提示合同及调用方，并同步受影响的动作／提示版本。保留原始模型响应；回放、准备后的模型可见事实和修复提示继续用同一 ref，避免把内部转换结果重新变成另一套模型引用协议。旧记录的内部 chunk_id 结构及 fixed_rag／旧 claims 消费协议保留，不要求重写历史或全局更换 Claim 模型。
4. **最终作答直接复用映射。**[prose.py](../../paper_assistant/prose.py:24) 的 `source_refs` 不再现场 `enumerate` 分配编号，改为从同一注册表取得当前实际可引用原文的 ref。`sources`、`allowed_refs`、准备历史、可选JS后的最终请求以及已有修复请求使用相同映射。保留 [citations.py](../../paper_assistant/citations.py:208) 已有 `by_ref` 查找，必要适配其他按位置生成或解释编号的入口；不把来源列表第n项当作ref=n。裁剪后允许编号不连续；被移出本次有效原文范围的段落不能仅凭旧号获得引用权限，同块以后真正重新展示时仍恢复原号。
5. **提示与格式规范化同步。**取证阶段就解释 ref 的意义，准备动作沿用 ref，最终事实按 RAGFlow 约定使用 `[ID:n]`。业务提示增加通用区分示例：原文书目 `[5]` 与当前段落 `ref=9` 是两套编号，引用该段应写 `[ID:9]`；示例不包含两题答案或定位。规范化支持明确带ID的 `[ID: 9]`、`(ID:9)`、`【ID：9】`、`(**ID:9**)` 及 `[ID:9, ID:10]` 等 RAGFlow 已有形式，保留当前标记内数字规范化，然后严格扫描 `[ID:n]` 并查映射。普通 `[5]`／`[99]`／`[1,2]` 原样保留；不引入 `ref5` 别名或通用可选ID正则。组合句柄按各个ref解析，不照搬0起点或用 `len(sources)` 判断有效范围；未知显式号保留给已有错误处理，不静默删去，不增加缺引用检测、强制补引、语义审核或模型请求。
6. **消费者一致交付。**正文规范化后再生成引用位置，原始模型输出保留；页面、导出、保存记录和评价消费同一份 `citations / evidence_refs / evidence_sources`。必要修改 [app.py](../../app.py) 和 [agent_export.py](../../paper_assistant/agent_export.py)，特别是已有证据展示区按列表重新编号的地方应显示本次登记ref，避免与答案句柄冲突。可见的普通书目号不被页面／导出重新识别成系统来源；出现次数与去重来源仍分开。旧记录缺少新增字段时沿用原有展示，不根据新注册规则重算旧答案。

按上述调用链完成必要数据、提示、解析、容量拟合和消费者修改，不增加独立校验层。模型、检索／阅读策略、停止／充分性判断及调用预算保持原配置；不顺带处理 Q50 内容保守、Q37／Q57 选读遗漏或其他题的问题。

### 29.4 两个现有方法承担本地验证

只同步并运行以下两个现有方法，使用通用本地 fixture／mock，在原方法内覆盖新增行为，不另建测试套件或嵌入两题参考答案：

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：在已有自主搜索、结构化阅读、表格、容量与prose场景里覆盖首次登记、重复命中／展开／重排编号稳定、不同问答隔离；准备ref与摘录转换、最终sources和修复映射一致；裁剪后的非连续ref仍正确关联、不可见证据不获权限；新增带ID格式、普通书目共存与纯普通号零引用，保留未知显式号原有共享修复及原始输出／交付正文／位置／保存记录的对应关系。调整旧“不支持ID括号和合并句柄”的预期为本轮明确支持范围，不扩大到普通编号或ref别名。
2. `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`：将既有prose fixture使用非连续ref，例如3和9，确认答案引用与原文展开、证据显示、JSON下载／Markdown／历史记录对应同一来源；普通书目号保留，重复引用与去重来源不混计，旧claims及fixed_rag的现有消费仍可用。需要同步的测试辅助函数只负责构造这两个方法使用的新协议数据，不加入运行时兼容或自动补引功能。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations
```

以上两个方法在实现后的最终代码状态运行；若失败，修正后仅重跑受影响方法。只有失败或具体跨模块影响证据才扩大到直接相关的已有方法，不跑整个模块／目录或全量回归。不另跑注册表扫描、独立语法扫描、评价整套、旧输出重放或连通性检查；已通过且对应代码未变的其他结果直接复用。本地验证不发真实聊天、embedding或重排请求，既有测试内部所需来源数据继续沿用，不额外手工计算哈希。

### 29.5 Q50／Q69 各一次完整真实复测

两个指定方法通过后，提取以下历史input中的原题和版本配对，顺序 Q50→Q69；题号不变，不追加新题号。

| 题号 | 输入与官方原问 | 固定本地版本 |
|---|---|---|
| D3-Q50 | [原input](../../artifacts/v3/d3-qa-q41-q50-20261028/input.json)；`Which 7 Indian languages do they experiment with?`；question_id `75df70ce7aa714ec4c6456d0c51f82a16227f2cb`，QASPER `2002.01664` | `local_599a9a07261e4e3bb80dd801c2d440fd / r_4a1440d302194feb` |
| D3-Q69 | [原input](../../artifacts/v3/d3-qa-q61-q80-20261028/input.json)；`How do they calculate variance from the model outputs?`；question_id `f94b53db307685d572aefad52cd55f53d23769c2`，QASPER `1612.03226` | `local_8e13f9a853d545078f7d3bb22d7904c1 / r_9531dc8dea728049` |

两题分别执行一次新的 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，使用独立新会话和独立注册表。保持原问、question_id和selected_versions；只向业务流程传原问、实际版本及普通完整回答要求。新的通用引用协议由业务提示生效，不在题目、检索参数或answer_instructions中另塞旧答案、诊断、参考、预期编号／chunk、书目冲突说明或强制工具动作，不用QASPER全文替代真实检索。

业务模型保持 `deepseek-flash`，1,048,576上下文、temperature 0.2、4,096输出、单次30秒、五步／五次取证及原网络重试一次／共享修复一次；embedding和重排沿用当前profile。记录实际配置及实施后的提示／动作／JS版本，不能把第27节旧提示版本原样写成本次实际版本。GPT负责实施与执行，不替换被测业务模型。正常前置规划、检索／阅读、准备／最终、查询embedding、可选重排／JS及原额度内重试／修复属于这两次完整运行，不额外发judge、fixed_rag、固定证据、计费或探测请求。

复用已ready的两个固定版本，下载／OCR／解析／索引／入库均不发起；版本不可用或共享故障时如实记录，不自动重入库。目录使用 `artifacts/v3/d3-stable-citation-q50-q69-20261028/`，stage=`d3-stable-citation-q50-q69`，会话／提交ID分别为 `d3-stable-citation-20261028-q50` 与 `d3-stable-citation-20261028-q69`。保存普通 `input.json / results.json`，完整JSON／Markdown仍由runtime写入 `archive/run_logs/d9/`。

复用 [现有两题调度入口](../../tmp/d3_explicit_citation_q50_q69_run.py) 的顺序运行和尝试状态方式，必要时新增 `tmp/d3_stable_citation_q50_q69_run.py` 并替换stage／目录／ID；不运行旧main或覆盖旧结果。请求前保存尝试，已有本轮尝试只整理、接续未尝试题。失败、中断、内容部分通过或缺引用都不补跑、不追加追问；不在两题之间改代码、改提示或加预算以取得通过。

### 29.6 评价与完成口径

先区分程序机制与真实模型表现：本地方法覆盖登记／传递／解析行为；两题的新模型请求观察模型是否实际沿用句柄、是否交付正确内容及对应来源。不得用保存输出离线重放代替真实复测，也不把运行状态answered当作内容和引用都通过。

- **链路观察：**直接对照现有原生请求里的原文ref、准备响应和最终sources／引用，记录本轮实际沿用情况。没有自然触发重排、裁剪、格式变体或普通书目时说明未触发，相关机制以本地场景为依据，不为触发而增加请求或另建扫描器。
- **Q50：**评价七语言覆盖、证据读取与错误不足结论是否仍在；内容和引用交付分别判定。即使使用显式ID、列全七项，仍错误声称无法确定准确集合时，内容不能直接算完全通过。
- **Q69：**评价方差／Fisher／EGL解释及原文的尺度、条件是否准确；书目普通号应保持书目含义，系统句柄应指向实际支持段落。模型仍只写普通号时如实记引用未交付；模型主动选错显式号时记录来源支持偏差，不靠新审核器或修复流程兜底。

按本轮实际登记表判断，不要求复现任何旧ref、引用次数或来源数量。`citation_checks=valid`不是语义通过，空检查不是引用交付成功；两题结果不外推总体稳定性，不重算第27节或旧批次成绩。沿用已有统计，记录实际请求、tokens、报告耗时、搜索／阅读、embedding／重排、网络重试／共享修复、JS以及引用出现／来源去重数；缺失费用保持缺失，不为统计追加调用。

完成迁移、两个方法和两题各一次运行后，将实际改动、验证、内容／引用评价、用量及产物链接补到第29.7节，保留第30节为文末可复制提示词。阻断时写清已完成部分与实际故障；不新增审计、哈希、manifest、快照、保护层或独立验证报告，不另加测试批次。

### 29.7 实施与真实复测结果

**实际改动（2026-10-28）：**按只读 RAGFlow 的 EvidenceRegistry／helper／Agentic提示及先规范化再关联机制适配。[prose.py](../../paper_assistant/prose.py) 增加提问内内存注册表，以paper/version/chunk登记1起点ref；实例由Agent本轮闭包与显式参数共享，不进入context deepcopy。搜索／阅读、原文合并排序／增量回放／准备／最终／既有修复沿用同号；登记快照与实际映射随原生日志保存。[context.py](../../paper_assistant/context.py) 的实际原文旁携带ref；目录和候选不授引用权。[agent.py](../../paper_assistant/agent.py) 工具观察携带shown_refs，容量拟合删除同块在回放及最终sources中的原文副本并同步权限，允许裁剪后非连续号、重新展示恢复旧号；最终sources不再enumerate。

[agent_actions.py](../../paper_assistant/agent_actions.py) 将自主prepare_answer的citation_refs和quote.ref通过本轮登记与当前可见集合转换成内部Claim/EvidenceQuote；回放模型侧事实仍用ref，原始响应保留。fixed_rag／旧Claim协议保留。[agent_prompt.py](../../paper_assistant/agent_prompt.py) 贯穿原文ref→准备ref→最终[ID:n]及书目[5]/段落ref9的通用区分；不含两题答案。显式ID的空格、括号、全角括号/冒号、星号及合并形式统一规范化，数字转换保留；普通[5]/[99]/[1,2]不动，未知显式号不删，沿原共享修复。[citations.py](../../paper_assistant/citations.py) 继续原by_ref及白名单/版本/原文检查，来源带实际ref；[app.py](../../app.py) 原文面板使用登记ref（旧记录无ref保留原展示），[agent_export.py](../../paper_assistant/agent_export.py) 标出实际来源ref。正文、引用位置、下载与历史继续同源；未增加缺引用检测、语义审核、哈希、注册数据库或额外请求。

**两个指定现有方法均通过。**运行方法 `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` 最终单方法 **Ran 1 test in 26.919s，OK**；页面方法 `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations` 已在仅含这两个方法的运行中通过，之后页面及其引用/导出消费者代码未变，复用该通过结果。失败修正仅重跑受影响的运行方法；未扩大到其他方法/模块、语法扫描或历史重放。通用mock覆盖重排/重复命中稳定号、问答隔离、准备ref/摘录转换、不可见/未知ref、裁剪回放副本及非连续权限、重新展示恢复号、显式变体/普通编号、原始响应和位置、原共享修复、JS沿用与fixed_rag旧协议；页面用3/9验证展开、证据显示、JSON/Markdown/历史和重复引用。离线无真实聊天、embedding或重排请求。

**两题真实运行：**从指定历史input保留原问、question_id与固定版本，按Q50→Q69各一次独立完整Agent运行、空历史／独立注册表，均 **completed/answered，stop_reason=answered**。复用ready；下载/OCR/解析/索引/入库均0。两题间未改代码、提示或预算，未补跑或追问。

| 题号 | 内容评价 | 格式与来源支持 | 原生日志 |
|---|---|---|---|
| Q50 | **核心七项通过。**Hindi、English、Kannada、Telugu、Assamese、Bengali、Malayalam，与本地Table 1及官方两份参考一致；本次明确承诺七项，没有重复“无法确定集合”或Malayalam遗漏。仍强调正文漏列Assamese，并附加“English非Indian language”的不必要分类评论，该评论不由所引原文证实。 | **7次引用/4来源**，准备citation_refs/quote.ref及最终ID一致；ref1数据集正文、ref5七语言表、ref4摘要、ref2引言。实际原文展示顺序4,6,2,1,5,3，最终sources=1,2,3,4,5,6，编号没有随原文展示位置重排。集合有表直接支持；附加评论不能因valid即算获支持。 | [JSON](../../archive/run_logs/d9/agent_20261028_090631_722758_e665fc72688b.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_090631_722758_e665fc72688b.md) |
| Q69 | **部分通过。**Fisher逆矩阵、期望方差/Fisher Information Ratio、trace代理、预训练估计、概率加权梯度平方、top-K beam/backprop和旧EGL不平方均覆盖。但最终损失差方差省略√n归一化，不能不加尺度直接当作未归一化损失差的方差；原文ref1 Eq.3和准备第2事实已有√n，属“材料取得且准备正确，最终组织遗漏”，不是算术错误。参数估计的√n保留。 | **14次引用/5来源**；书目[6]/[8]/[5]/[4]保持普通文本，系统ID对应本轮实际材料，没有旧普通号猜配。ref2分布/Fisher、ref1 Eq.3、ref5方差/trace、ref6 Eq.4/beam、ref4动机；来源对应，valid不保证尺度完整。search后同响应的read_context重新展示四块，refs 2,1,5,6不变；最终sources=2,1,5,6,3,4,7，阅读重排没有重新编号。 | [JSON](../../archive/run_logs/d9/agent_20261028_090658_819359_3a3cc5dc718a.json) / [Markdown](../../archive/run_logs/d9/agent_20261028_090658_819359_3a3cc5dc718a.md) |

两题原始最终响应均等于规范化交付正文，主动使用标准显式ID；Q69自然触发书目/系统句柄共存及同块阅读重排。真实运行没有触发容量裁剪、格式变体、未知ref修复或JS，不为触发加请求。没有以空valid替代交付，也不以两题外推整体稳定性或重算历史成绩。

**实际配置：**deepseek-flash，1,048,576上下文、temperature 0.2、4,096输出、单次30秒、五步/五次取证、网络重试一次/共享修复一次；embedding qwen3.7-text-embedding 1024维、重排qwen3-rerank沿现有profile。实施后动作 `v2.16-stable-evidence-refs-v1`、自主提示 `v2.24-stable-evidence-refs-v1`、最终提示 `v3.2-stable-evidence-refs-v1`；JS mini-racer-0.12.4 / V8 12.6.228.18。预算及其他业务问答策略不变。

**实际用量：**聊天 **8次/92,765 tokens/55.406秒报告耗时**（Q50：4次/43,034/26.891秒；Q69：4次/49,731/28.515秒）。2次搜索、1次本地阅读、4个自主步骤、3次取证；查询embedding **2次/48 tokens/8.987349秒**，检索报告总耗时10.997196秒；重排 **2次/报告9,207 tokens/0.918049秒**。网络重试/共享修复 **0/0**，JS **0次/0秒**；入库/索引embedding均0。原生引用 **21次出现/9个去重来源**，无claims旧指标不适用。耗时不互斥，不叠加为墙钟总耗时；独立计费金额缺失，未追加统计请求。

**产物：**[input.json](../../artifacts/v3/d3-stable-citation-q50-q69-20261028/input.json)、[results.json](../../artifacts/v3/d3-stable-citation-q50-q69-20261028/results.json)，窄入口 [d3_stable_citation_q50_q69_run.py](../../tmp/d3_stable_citation_q50_q69_run.py)。完整正文/请求只保留runtime原生JSON/Markdown，汇总链接原日志，旧产物及第27.6节未覆盖。本轮结束，未顺带修内容缺口或开始其他题。

## 30. 给另一个 GPT 对话的引用链路迁移与两题真实复测提示词

复制下方代码块内容作为另一个GPT对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 按d3-plan.md第29节迁移RAGFlow Agentic引用链路，完成两个指定现有测试方法，并真实复测Q50、Q69各一次；不要增加多余校验、哈希或模型请求。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能，遵守Stop Ladder和AGENTS.md用户四问。在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第27.6节及第29节，实际完成本轮实现与两题复测。第1～28节保留为历史，不执行其中旧提示或main，不覆盖工作区已有修改。用户要求按引用链路需要完整修改，不以改动少为目标，也不顺带改其他问答问题。

参考仓库E:/project/ragflow只读。直接移植internal/agentic_rag/evidence_registry.go的运行内稳定登记、helper.go的原文旁ref、conf/agentic_rag.yaml的[ID:n]提示约定，以及internal/service/agentic_reference.go、citation.go和internal/agentic_rag/citations.go的先规范化再扫描／查映射机制，适配Python和现有JSON。保留本项目1起点，不照搬通用CitationMarkerPattern的普通[n]识别，不引入ref5别名、servedText哈希去重或整套RAGFlow检索框架。

每次提问使用一张内存注册表，以已有paper_id/parse_revision/chunk_id登记；搜索再次命中、阅读展开、重排、准备、最终及已有修复都沿用同号，新块分配新号，旧号不复用。注册表实例在本轮共享，不随context deepcopy分裂；evidence_sections等模型实际读到的原文旁加ref，目录／候选／前置规划材料不因此获得引用权限。JSON即可，不必为XML外壳重做工具。原文新增、合并、回放和容量拟合一起贯通，拟合后实际保留原文决定本次引用权限；裁剪后的ref允许不连续，不用列表位置或len(sources)推断编号有效性，同块重新真正展示时保持原号。

按第29.3节将自主Agent的模型侧prepare_answer改用citation_refs:[n]和evidence_quotes:[{ref:n,quote:连续原文}]，在现有动作解析入口查本轮映射转换为内部Claim.citation_ids/EvidenceQuote.chunk_id，继续现有处理，未知／不可见ref沿用既有错误与共享修复。回放保留原始模型响应，面向模型的准备事实及修复仍用ref。必要同步agent_actions、agent_prompt及调用方与实际动作／提示版本，不全局替换旧Claim模型或fixed_rag协议。source_refs改读本轮注册表，最终sources、allowed_refs、可选JS后请求与修复保持一致，不最终重新enumerate。保留citations.py已有by_ref解析及当前来源权限，不新增另一层审查。

业务提示贯穿取证、准备和最终：最终[ID:n]中的n等于原文旁ref；通用示例明确论文书目[5]与段落ref=9不同，引用该段用[ID:9]，不加入两题答案。规范化覆盖第29.3节明确带ID的空格／括号／全角／星号及[ID:9, ID:10]合并形式，保留现有数字转换；普通[5]/[99]/[1,2]原样，不猜配、不静默删除未知显式号。保留原始响应，从规范化后的同一正文计算位置并发布。页面、原文展开、证据编号、导出、历史和评价使用同一来源映射，必要修掉展示区自行按列表重编号；旧记录保持可消费。最终引用映射沿现有结果和运行记录保存，不新建注册表数据库、全库引用号、聊天恢复或会话持久化功能。

本地只调整并运行scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records和scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations两个现有方法，按第29.4节覆盖登记传递、搜索／阅读／重排稳定、问答隔离、准备ref及摘录转换、非连续号与可见权限、ID变体／普通书目、原有修复以及页面／保存／导出。使用通用本地mock，不嵌入两题答案；失败修复后仅重跑受影响方法，只有具体跨模块影响才扩大。对应代码未变的其他通过结果复用，不跑整模块／目录／全量，不另跑扫描器、语法检查、历史重放或模型／embedding／重排探测。

两方法通过后，从artifacts/v3/d3-qa-q41-q50-20261028/input.json取D3-Q50，从artifacts/v3/d3-qa-q61-q80-20261028/input.json取D3-Q69，原问、question_id和selected_versions保持不变。固定版本为Q50 local_599a9a07261e4e3bb80dd801c2d440fd/r_4a1440d302194feb，Q69 local_8e13f9a853d545078f7d3bb22d7904c1/r_9531dc8dea728049。复用ready版本，不下载／OCR／解析／索引／入库。只传原问、实际版本及普通完整回答要求，不向题目或检索／answer_instructions注入旧答案、诊断、gold、预期编号／chunk、书目冲突说明或强制工具动作；新通用引用协议由业务提示生效。

按Q50→Q69各一次完整真实d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话／注册表，不是旧输出离线重放。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次30秒、五步／五次取证及原网络重试一次／共享修复一次；embedding和重排沿当前profile。记录实际配置和实施后的提示／动作／JS版本，GPT执行而业务模型不切换。原额度内正常规划、取证、准备、最终、可选JS及重试／修复属于完整运行，不额外发judge、fixed_rag、固定证据、计费或连通性请求。

本轮目录artifacts/v3/d3-stable-citation-q50-q69-20261028/，stage=d3-stable-citation-q50-q69，会话／提交ID为d3-stable-citation-20261028-q50和-q69，使用普通input.json/results.json。完整JSON／Markdown继续由runtime写archive/run_logs/d9/。复用tmp/d3_explicit_citation_q50_q69_run.py的顺序调度和尝试状态，必要时新增tmp/d3_stable_citation_q50_q69_run.py，替换新stage／目录／ID，不运行旧main。请求前保存尝试，已有本轮尝试只整理、接续未尝试题。失败、中断、部分通过或缺引用不补跑、不追加追问，两题之间不改代码／提示／预算；固定版本不可用或共享故障时记录实际状态，不自动重入库。

生成后按第29.6节分别评价内容、模型格式和实际来源支持，直接对照现有原生请求的ref、准备响应与最终sources／引用，不新增检查程序。Q50列全但仍作错误不足结论要单独记内容部分通过；Q69区分书目号与系统句柄，检查核心解释的原文支持。模型继续漏ID就如实记引用未交付，不加缺引用检测、强制补引、额外修复或语义审核。不要求旧ref或旧引用计数，未自然触发的场景如实说明，valid及空检查不算语义／交付通过，不以两题外推稳定性或重算旧成绩。

在d3-plan.md第29.7节补记实际修改、两个方法结果、两题内容／引用评价、实际用量和产物链接，保留第30节为文末提示词。不新增审计、哈希、manifest、快照、保护层、独立验证报告或其他测试批次，不手工重算PDF／正文哈希。向用户简要交付实际完成情况；存在阻断就说明已完成部分与具体原因，不虚报实施或真实测试。
```

## 31. 稳定引用机制后的新二十题：D3-Q81～D3-Q100（2026-10-28）

状态：**已执行；五篇ready，二十题各一次真实尝试完成，实际结果见第31.6节。**本批沿用第29.7节稳定证据句柄链路。第1～30节及历史成绩保留，执行使用文末第32节给另一个GPT对话的提示词。

### 31.1 题目来源与五篇固定论文

来源为本地 [QASPER官方dev v0.3](../../eval/qasper/raw/qasper-dev-v0.3.json)，续排 **D3-Q81～D3-Q100**，本批论文代号 **R26～R30**。选题时已对照前面D3输入及既有sample题单，选定的二十个question_id未重复；执行直接使用本节固定题单，不另建排重、题单校验或预检程序。

以下题名及固定v1已核对arXiv公开版本。允许必要的新论文入库；已有同一固定PDF／解析方案的ready版本或bundle时通过现有能力复用。本地 `paper_id / parse_revision` 取实际ready返回，不预造编号，不以论文代号替代本地身份。

| 代号 | QASPER paper_id | 论文 | 固定PDF |
|---|---|---|---|
| R26 | `1908.10084` | Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks | [arXiv v1](https://arxiv.org/pdf/1908.10084v1) |
| R27 | `2002.01320` | CoVoST: A Diverse Multilingual Speech-To-Text Translation Corpus | [arXiv v1](https://arxiv.org/pdf/2002.01320v1) |
| R28 | `2002.03407` | Abstractive Summarization for Low Resource Data using Domain Transfer and Data Synthesis | [arXiv v1](https://arxiv.org/pdf/2002.03407v1) |
| R29 | `1910.14599` | Adversarial NLI: A New Benchmark for Natural Language Understanding | [arXiv v1](https://arxiv.org/pdf/1910.14599v1) |
| R30 | `1901.01010` | A Joint Model for Multimodal Document Quality Assessment | [arXiv v1](https://arxiv.org/pdf/1901.01010v1) |

### 31.2 二十题与固定顺序

执行按 `QASPER paper_id + question_id` 从官方JSON取得原始 `question`，保留大小写、拼写、语法和空白，表格只用于阅读。尤其Q88、Q90的原始字符串含尾部空格，提取时不trim。表中观察重点只用于生成后评价，不进入前置规划、业务消息、检索参数或工具指令。

| 题号 | 论文 | 官方原题 | question_id | 事后观察重点 |
|---|---|---|---|---|
| D3-Q81 | R26 | How are the siamese networks trained? | `2e89ebd2e4008c67bb2413699589ee55f59c4f36` | 训练数据、网络共享及训练目标的必要关系有原文支持，不拿检索相似度替代训练过程 |
| D3-Q82 | R26 | What transfer learning tasks are evaluated? | `4944cd597b836b62616a4e37c045ce48de8c82ca` | 实际迁移任务列全，与STS及训练任务区分，不凭熟悉的评测套件补项 |
| D3-Q83 | R26 | What metrics are used for the STS tasks? | `a29c071065d26e5ee3c3bcd877e7f215c59d1d33` | 指标名称、比较对象及不同设置的口径对应，不将相似度函数直接等同评价指标 |
| D3-Q84 | R26 | How much time takes its training? | `7f207549c75f5c4388efc15ed28822672b845663` | 训练耗时与检索／推理耗时分开，保留硬件、模型及训练设置条件；未给时不猜 |
| D3-Q85 | R27 | Which languages are part of the corpus? | `bc84c5a58c57038910f7720d7a784560054d3e1a` | 语言列表与翻译方向完整对应，不混用源语言数和包含目标语的总数 |
| D3-Q86 | R27 | How was the dataset collected? | `f8f4e4a50d2b3fbd193327e79ea32d8d057e1414` | 区分原始语音／转写来源、译文收集与质量控制，不用单一来源代替整个流程 |
| D3-Q87 | R27 | What is the architecture of their model? | `cee8cfaf26e49d98e7d34fa1b414f8f31d6502ad` | 实验模型的编码／解码及任务设置有据，区分语音识别、文本翻译与语音翻译组件 |
| D3-Q88 | R27 | How is the quality of the data empirically evaluated? | `29923a824c98b3ba85ced964a0e6a2af35758abe` | 评价手段、对象与结果支持关系对应，不只复述数据收集或模型训练过程 |
| D3-Q89 | R28 | What is the recent abstractive summarization method in this paper? | `c21b87c97d1afac85ece2450ee76d01c946de668` | 基础摘要方法与本文域迁移／数据合成策略分清，不误把辅助策略当作基础模型 |
| D3-Q90 | R28 | Is the student reflection data very different from the newspaper data? | `b5608076d91450b0d295ad14c3e3a90d7e168d0e` | 差异判断对应原文实际维度与依据，不泛化成无证据的领域常识或绝对结论 |
| D3-Q91 | R28 | Who were the human evaluators used? | `31735ec3d83c40b79d11df5c34154849aeb3fb47` | 评价者角色和已报告背景准确，区分摘要作者、数据提供者与评价者；缺失身份不编造 |
| D3-Q92 | R28 | What is the interannotator agreement for the human evaluation? | `fb2b536dc8e442dffab408db992b971e86548158` | 一致性指标、数值和评价任务对应；若未报告，说明本轮材料范围，不能以其他质量分数替代 |
| D3-Q93 | R29 | What data sources do they use for creating their dataset? | `af5730d82535464cedfa707a03415ac2e7a21295` | 来源与收集轮次／用途对应，不把训练用旧NLI数据都当新数据的原始材料 |
| D3-Q94 | R29 | Do they use active learning to create their dataset? | `ee2c9bc24d70daa0c87e38e0558e09ab97feb4f2` | 明确判断并解释实际人机迭代机制，术语与流程关系按原文，不因题目暗示就肯定 |
| D3-Q95 | R29 | What are the weaknesses found by non-expert annotators of current state-of-the-art NLI models? | `b3d01ac226ee979e188a4141877a6d2a5482de98` | 弱点类别、必要实例及分析范围有据，不只泛称模型鲁棒性不足或扩充通用错误清单 |
| D3-Q96 | R29 | Do they compare human-level performance to model performance for their dataset? | `a69a59b6c0ab27bcee1a780d6867df21e30aec08` | 有无比较与实际比较结果对应，数据轮次／划分、模型和指标条件不能遗漏 |
| D3-Q97 | R30 | Where do they get their ground truth quality judgments? | `71a0c4f19be4ce1b1bae58a6e8f2a586e125d074` | 各文档数据来源及质量标签形成方式分开，不混为同一种人工评分 |
| D3-Q98 | R30 | How large is their data set? | `07b70b2b799b9efa630e8737df8b1dd1284f032c` | 区分文档类型、总量／子集／划分与计数单位，保留预处理后范围 |
| D3-Q99 | R30 | Which is more useful, visual or textual features? | `23e2971c962bb6486bc0a66ff04242170dd22a1d` | 结论对应不同数据集和实验条件，区分单模态比较与联合模型效果，不作无条件排序 |
| D3-Q100 | R30 | What is their system's absolute accuracy? | `fc1679c714eab822431bbe96f0e9cf4079cd8b8d` | 绝对结果与相对提升分开，模型／数据集／指标及数值对应，不能把其他指标冒充accuracy |

同论文四题均独立新会话／注册表，不传前题答案、工具历史或准备事实。官方参考、可回答性标签、gold evidence及预期数值／公式／表号／chunk不作为业务输入，QASPER `full_text` 不替代PDF入库后的真实检索。

### 31.3 必要准备与二十题真实运行

五篇固定PDF沿用 `import_runtime.import_pdf` 默认 `mineru-api` 官方API入口，保持现有VLM／全文OCR／公式／表格、分块与索引profile。相同固定材料已有ready或bundle就通过原能力复用；缺少时允许必要下载、API解析及索引embedding，不重建其他论文索引。单篇失败记录其四题未执行，其他独立论文可以继续；共享故障阻断后续时保存结果后停止，不自动换题、换版或换解析器，不额外发探测请求。

按Q81→Q100，各一次完整真实 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`。保留正常前置规划、检索／阅读、准备、最终、可选JS和原额度内重试／修复；每题一次运行可以包含正常流程所需的多次HTTP请求。模型自主决定工具和停止，不强制读取特定表格、执行计算、耗尽额度或生成指定编号。

保持 `deepseek-flash`、1,048,576上下文、temperature 0.2、4,096输出、单次30秒、五步／五次取证、网络重试一次／共享修复一次；embedding和重排沿当前profile。沿用第29.7节稳定句柄实现，基线动作／自主提示／最终提示为 `v2.16-stable-evidence-refs-v1`／`v2.24-stable-evidence-refs-v1`／`v3.2-stable-evidence-refs-v1`，记录运行时实际配置和提示／动作／JS版本。GPT负责执行，不切换被测业务模型，不改业务代码、提示或预算，不回退普通 `[n]` 自动转换。

本批没有业务行为修改，**复用第29.7节已通过且对应代码未变的结果，不重跑离线方法、Q50／Q69、语法扫描或全量回归**。现有正常入库与问答流程已包含其所需处理，不另加ready校验器、连通性测试、独立judge、fixed_rag、固定证据实验、引用扫描器或来源审核。不给本批新增哈希、手工哈希计算、审计、manifest、快照或保护层。

### 31.4 普通产物与接续

目录 `artifacts/v3/d3-qa-q81-q100-20261028/`，stage=`d3-qa-q81-q100`，会话／提交ID为 `d3-qa-q81-q100-20261028-q81` 至 `d3-qa-q81-q100-20261028-q100`。普通 `input.json` 保存原问／question_id、来源及实际ready版本、公开配置；普通 `results.json` 保存每题实际状态、停止原因、日志路径、用量和生成后评价。完整逐题JSON／Markdown继续由runtime写入 `archive/run_logs/d9/`，不复制一套完整日志或另建验证报告。

复用 `tmp/d3_prepare_q61_q80.py`、`tmp/d3_build_q61_q80_input.py`、`tmp/d3_qa_q61_q80_run.py` 的方式，必要时只新增对应本批的准备、输入和顺序执行入口（如 `tmp/d3_prepare_q81_q100.py`、`tmp/d3_build_q81_q100_input.py`、`tmp/d3_qa_q81_q100_run.py`），替换五篇四题清单、起止序号、stage、目录和ID。保留顺序和尝试状态，请求前保存，已尝试题只整理、接续未尝试题；不执行旧main或覆盖旧输入／结果，不建设通用批次框架。失败、中断、内容不足、未用工具或缺引用均不补跑，不追加追问或替代题。

### 31.5 生成后评价与结束条件

二十题生成后结合实际版本原文、已展示材料和官方各份参考评价，运行完成、核心内容、模型句柄格式与实际来源支持分开。可回答性分歧、题意歧义和参考笔误依据原文说明；正确、范围适当的证据不足回答可以通过，不为符合隐藏参考强求肯定结论或固定措辞。

按第31.2节观察必要并列项、数字／单位、任务与模型／数据集／指标、主体及条件是否完整。若准备事实已有正确内容而最终遗漏，定位为最终组织问题；若未读取实际可达原文，只根据本轮日志说明环节。训练时间与推理时间、绝对数值与相对提升等不能混用。用户未问的分类评论、重复结论或无依据的延伸单独注明，不以主答案正确掩盖这些偏差，也不中途修提示、加预算或补跑。

引用直接使用原生日志中的原始输出、`answer.text`、ref及 `citations / evidence_sources` 评价，观察稳定句柄在普通新题中的实际使用，出现次数与去重来源分计。书目普通号保持原意；未知号、错来源或漏ID按真实结果记录，不猜配、不强制补引。`valid`不能证明语义正确，空检查不能算引用交付成功；没有自然触发阅读重排、裁剪、格式变体或普通书目时如实说明，不增加实验来凑覆盖。无claims的旧指标不适用。

沿用已有请求／tokens／报告耗时、搜索／阅读、embedding／重排、网络重试／共享修复、JS和引用统计；入库与问答、索引与查询embedding分开，费用缺失保持缺失，不为统计发请求。本批是公开dev新题的定向观察，不拿不同题目批次的差异直接证明机制导致准确率或速度提升。

二十题各一次完成或明确共享故障停止后，将实际准备、逐题内容／引用评价、用量和产物链接补到第31.6节，保留第32节为文末提示词。到此结束，不自动修业务、加预算、重跑旧题或开始下一批。

### 31.6 本批实际结果

**实际执行（2026-10-28）：**五篇均ready；Q81→Q100按固定顺序各尝试一次、独立空历史/注册表。**19题answered，Q93为invalid_output未交付；核心内容17题通过（含范围适当的不足回答）、Q99/Q100部分通过、Q93未交付。**这是本批内容评价，不是用answered冒充正确，也不与不同新题批次推断机制提升。业务代码、提示、预算未改；第29.7节验证复用，未跑离线测试/扫描/重放、judge或其他模式。

**论文准备：**R26/R27/R29/R30各下载固定v1并通过默认MinerU官方API新增一个解析/索引版本；R28由现有能力复用ready（28块、0新embedding，返回batch_id/parse_source为空，未补查或重上传）。保持VLM、hybrid/medium、全页OCR、公式/表格开启、image_analysis=false及现有分块/索引profile。实际返回绑定如下：

| 论文 | 实际paper_id / parse_revision | chunks | 新索引embedding | 结果 |
|---|---|---:|---:|---|

| R26 1908.10084v1 | `local_8f4ce726f1fa4cfbbad9b631c80e2bce` / `r_bbebee450c4ae496` | 42 | 5 | 新增API版本ready |

| R27 2002.01320v1 | `local_e6a6a3f91b36494e90744de7194f9271` / `r_82704cc6d815ba76` | 45 | 5 | 新增API版本ready |

| R28 2002.03407v1 | `local_586658a88c3f4908912205b2ed8c8bd7` / `r_36f57978209ee9a1` | 28 | 0 | 复用ready |

| R29 1910.14599v1 | `local_b19a4645dc9a4be2bcf862c8aa4c7209` / `r_0cc2a70ae303ce19` | 43 | 5 | 新增API版本ready |

| R30 1901.01010v1 | `local_d5ee5a495df14748b2404aa549766cde` / `r_8bf7ad71d160973e` | 45 | 5 | 新增API版本ready |

准备共203块（新增175、复用28）；4个新API batch_id及实际parser/profile见普通input。入库报告耗时 **230.077592秒**；索引embedding **20次/49,923 tokens/16.361227秒请求耗时**，与问答查询embedding分开。MinerU HTTP总请求数、下载独立耗时及计费金额未由runtime完整提供，不手工推算、不补发统计请求。

**逐题评价：**以下“引/源”为本题引用出现次数/本题真实来源去重数。19个已发布正文均主动使用标准显式ID，原始最终响应与answer.text相同；准备ref、实际来源及来源定位沿本轮映射，具体内容支持仍单独评价，valid不是语义保证。Q93未到最终正文/引用检查，0/0不算通过。完整评价、状态和用量在results，完整请求/原文只链接runtime原生日志。

| 题号 | 核心评价与具体观察 | 引/源 | 聊天次/tokens/报告秒 | 原生日志 |
|---|---|---:|---|---|

| Q81 | **通过**：共享权重、池化及三目标、NLI训练齐全；末尾“公式仅渲染不能引用”不必要，ref1实际已有公式。 | 12/6 | 4/72,258/24.750 | [JSON](../../archive/run_logs/d9/agent_20261028_114955_836702_5795ba0cab01.json) / [MD](../../archive/run_logs/d9/agent_20261028_114955_836702_5795ba0cab01.md) |

| Q82 | **通过**：七项SentEval任务齐全且与其他适配区分；额外结果/AFS/Wikipedia展开及不足评论偏多。 | 17/7 | 4/83,192/26.109 | [JSON](../../archive/run_logs/d9/agent_20261028_115020_742749_2d99963f621d.json) / [MD](../../archive/run_logs/d9/agent_20261028_115020_742749_2d99963f621d.md) |

| Q83 | **通过**：Spearman、cosine对gold及ρ×100正确，指标与相似度函数分清。 | 5/3 | 4/46,858/20.766 | [JSON](../../archive/run_logs/d9/agent_20261028_115047_135257_b6a902c5a19c.json) / [MD](../../archive/run_logs/d9/agent_20261028_115047_135257_b6a902c5a19c.md) |

| Q84 | **通过**：微调少于20分钟；没有把65小时/5秒推理搜索当训练时间。 | 5/4 | 4/53,146/21.282 | [JSON](../../archive/run_logs/d9/agent_20261028_115108_078659_253f4d5434ee.json) / [MD](../../archive/run_logs/d9/agent_20261028_115108_078659_253f4d5434ee.md) |

| Q85 | **通过**：11种源语言完整，明确译入English；另列Tatoeba五语，未混计。 | 4/3 | 4/55,149/21.484 | [JSON](../../archive/run_logs/d9/agent_20261028_115129_529653_767014ef969f.json) / [MD](../../archive/run_logs/d9/agent_20261028_115129_529653_767014ef969f.md) |

| Q86 | **通过**：众包语音/验证、转写去重、专业翻译与质检分清；回答长但原文支持。 | 18/5 | 4/52,520/27.890 | [JSON](../../archive/run_logs/d9/agent_20261028_115151_194885_d7dc962fc8f3.json) / [MD](../../archive/run_logs/d9/agent_20261028_115151_194885_d7dc962fc8f3.md) |

| Q87 | **通过**：ST/ASR沿Bérard并3层decoder；MT为3+3层Transformer、dropout0.3。 | 6/4 | 5/78,581/24.156 | [JSON](../../archive/run_logs/d9/agent_20261028_115219_236460_598bb5b50963.json) / [MD](../../archive/run_logs/d9/agent_20261028_115219_236460_598bb5b50963.md) |

| Q88 | **通过**：BLEU/同文/perplexity/字符比例/LASER五检查与人工返译完整；数据质检和模型指标分开。 | 16/8 | 4/114,454/26.812 | [JSON](../../archive/run_logs/d9/agent_20261028_115243_568884_385cf423aab4.json) / [MD](../../archive/run_logs/d9/agent_20261028_115243_568884_385cf423aab4.md) |

| Q89 | **通过**：明确PG-net基础模型，迁移和模板合成另分；未问的合成细节展开较多。 | 9/4 | 4/61,939/29.454 | [JSON](../../archive/run_logs/d9/agent_20261028_115401_831899_1da992275fcc.json) / [MD](../../archive/run_logs/d9/agent_20261028_115401_831899_1da992275fcc.md) |

| Q90 | **通过**：Yes；结构、重复、碎片/语法与规模差异有据，ROUGE补充数字正确。 | 7/6 | 4/91,634/30.391 | [JSON](../../archive/run_logs/d9/agent_20261028_115431_475889_96eb30db2da7.json) / [MD](../../archive/run_logs/d9/agent_20261028_115431_475889_96eb30db2da7.md) |

| Q91 | **通过**：作者机构20人、每人20标注；与参考摘要的TA/专家作者区分。 | 5/2 | 4/73,045/21.125 | [JSON](../../archive/run_logs/d9/agent_20261028_115502_133191_eae9bf8b580a.json) / [MD](../../archive/run_logs/d9/agent_20261028_115502_133191_eae9bf8b580a.md) |

| Q92 | **通过（正确不足）**：正确不足：未见agreement，不把偏好比例当kappa；两份官方均unanswerable。 | 6/4 | 5/122,571/28.954 | [JSON](../../archive/run_logs/d9/agent_20261028_115523_446315_d98ec612b767.json) / [MD](../../archive/run_logs/d9/agent_20261028_115523_446315_d98ec612b767.md) |

| Q93 | **未交付（运行失败）**：未交付：准备citation_refs连续写chunk_id字符串，原一次共享修复后仍invalid_action_schema。 | 0/0 | 4/48,888/21.844 | [JSON](../../archive/run_logs/d9/agent_20261028_115552_637541_e9fc9b3d1eda.json) / [MD](../../archive/run_logs/d9/agent_20261028_115552_637541_e9fc9b3d1eda.md) |

| Q94 | **通过（术语分歧）**：人机对抗迭代/三轮机制正确；官方Yes/No冲突，保留active learning命名分歧。 | 6/6 | 4/56,213/21.500 | [JSON](../../archive/run_logs/d9/agent_20261028_115614_641873_ae73e5c30ee7.json) / [MD](../../archive/run_logs/d9/agent_20261028_115614_641873_ae73e5c30ee7.md) |

| Q95 | **通过**：六类推理弱点、500例/轮dev范围及跨轮数字有据；未只泛谈鲁棒性。 | 15/9 | 4/67,068/31.766 | [JSON](../../archive/run_logs/d9/agent_20261028_115636_293268_49572eecb69b.json) / [MD](../../archive/run_logs/d9/agent_20261028_115636_293268_49572eecb69b.md) |

| Q96 | **通过（范围适当不足）**：范围适当不足：已见材料无人类accuracy基线，不把人工核验率当人类表现；模型数据展开无助核心。 | 6/5 | 5/92,993/31.125 | [JSON](../../archive/run_logs/d9/agent_20261028_115708_281652_1134346a5a43.json) / [MD](../../archive/run_logs/d9/agent_20261028_115708_281652_1134346a5a43.md) |

| Q97 | **通过（核心来源）**：两类标签来源正确；arXiv会议续行AAAI与负标/可能未投稿说明本地可达但未读，核心来源不受影响。 | 10/4 | 4/47,567/21.093 | [JSON](../../archive/run_logs/d9/agent_20261028_115739_663311_651ec0a3811f.json) / [MD](../../archive/run_logs/d9/agent_20261028_115739_663311_651ec0a3811f.md) |

| Q98 | **通过（参考笔误）**：两数据集/三子集规模及JS求和正确；官方2,794篇arXiv为笔误，实为Wikipedia test数。 | 6/5 | 7/153,998/21.094 | [JSON](../../archive/run_logs/d9/agent_20261028_115800_848899_13ac7dc04d9f.json) / [MD](../../archive/run_logs/d9/agent_20261028_115800_848899_13ac7dc04d9f.md) |

| Q99 | **部分通过**：互补性与Wikipedia比较正确，但总结“联合最好”未保留cs.lg例外；准备已有限定，最终泛化。 | 10/5 | 4/47,211/18.422 | [JSON](../../archive/run_logs/d9/agent_20261028_115822_065718_64923a450974.json) / [MD](../../archive/run_logs/d9/agent_20261028_115822_065718_64923a450974.md) |

| Q100 | **部分通过**：只给Wikipedia 59.4%；漏arXiv 93.4/77.1/79.9%，可达表3未读而停止。 | 4/2 | 4/49,432/14.281 | [JSON](../../archive/run_logs/d9/agent_20261028_115840_596044_a9677ef4dfcd.json) / [MD](../../archive/run_logs/d9/agent_20261028_115840_596044_a9677ef4dfcd.md) |

**具体缺口与参考分歧：**Q81有一份参考标unanswerable，另一份和实际训练原文明确可回答，按材料通过。Q82按正文明确七项transfer口径，不以某份较宽泛参考强加STS。Q94两份Yes/No冲突，按实际HAMLET机制评价。Q98表1中2,794是Wikipedia test数；实际表2的arXiv cs.ai/cs.cl/cs.lg共4,092/2,638/5,048篇，模型在原第五步可选JS得到11,778总量及10,599/589/590划分和，输入/口径/算术均正确，明确是计算值；未重开取证。

Q93是**模型准备动作字段类型失败**：quote.ref=4正确，但citation_refs用了chunk_id字符串，原一次共享修复后仍同错，停止于action_repair；没有恢复猜配或额外修复。Q99是**条件在最终总结中泛化**：准备保留“胜text-only于Wikipedia和两个arXiv子集”，最终开头/结尾却概括联合最好；实际cs.lg是BILSTM 81.1%高于JOINT 79.9%，正文中段的限定不能消除总结偏差。Q100是**材料可达却未取得**：一次搜索只有叙述性结果，准备answerable=true、最终留不足；本地表3 p6_c1/c2具备三项arXiv绝对accuracy，目录有page6 table入口parent22但caption为空，未自然read_context。该问题重现“可读表未取便停止”的遗漏，不能说全文没给。Q97同有次要续行未读；Q81及多题存在未问细节/不足评论。只记录环节，不改规则或补跑。

Q99/Q100沿原文写2.9%、5.3%、2.4%等higher，这些数值按表实际是**准确率百分点差**，不是相对增幅；绝对accuracy与比较差值分开评价。Q96部分表格续行本身不带模型名，完整主语需结合已见同表上下文，不能单凭引用定位通过就认定单块能独立证明所有关系。

**链路与停止观察：**Q87、Q98各自然本地阅读一次；Q98在先缺表后自主读取、二次准备补全，并在剩余原步数内最终计算，stop_reason=step_limit_answered。Q92/Q96为no_reliable_evidence_direction后交付不足说明，其他正常题answered；没有按工具次数多少判错。重复检索、原文按论文顺序展示与最终sources沿提问内ref，19个发布答案均有实际来源；未观察到容量裁剪或需规范化的ID格式变体，未为普通书目/其他分支制造实验。旧无claims指标不适用。

**一次本地调度中断：**Q88已完成并保存后，保存Q89请求前attempt状态的os.replace遭WinError 5，Q89请求尚未发出。之后沿同一窄入口接续，Q81～Q88全部SKIP completed，从Q89首次运行到Q100。没有重复任何已尝试题、改变业务或增加写入保护层；此本地中断与网络重试/模型修复分计。

**实际配置：**deepseek-flash，1,048,576上下文、temperature 0.2、4,096输出、单次请求30秒、五步/五次取证、网络重试一次/共享修复一次。embedding为qwen3.7-text-embedding 1024维、重排qwen3-rerank，沿当前profile。动作 `v2.16-stable-evidence-refs-v1`、自主提示 `v2.24-stable-evidence-refs-v1`、最终提示 `v3.2-stable-evidence-refs-v1`；JS mini-racer-0.12.4 / V8 12.6.228.18。input保留官方原问/ID与ready配对，Q88一个、Q90两个尾部空格原样保留；观察重点和参考未进入业务输入。

**问答实际用量：**聊天 **86次/1,468,717 tokens/484.298秒报告耗时**；29次搜索、2次本地阅读，46个自主步骤、31次取证；查询embedding **29次/797 tokens/101.060725秒**（检索总报告125.279278秒）；重排 **29次/报告264,593 tokens/10.826104秒**。网络重试 **0**，共享修复 **1**（Q93）；JS **1次/0.119179秒**（Q98，计算后的最终聊天已计入86次）。**167处引用；每题来源去重数加总92，按paper/version/chunk对全批去重为76个实际来源**，两种口径不混用。费用金额缺失，不记零；各项耗时不互斥，不加成墙钟总耗时，也未为统计发请求。

**普通产物：**[input.json](../../artifacts/v3/d3-qa-q81-q100-20261028/input.json)、[results.json](../../artifacts/v3/d3-qa-q81-q100-20261028/results.json)。本批窄入口为 [准备](../../tmp/d3_prepare_q81_q100.py)、[输入](../../tmp/d3_build_q81_q100_input.py)、[顺序运行](../../tmp/d3_qa_q81_q100_run.py)，准备状态沿既有方式保存在tmp。stage/目录/会话及提交ID均为本批Q81～Q100，旧main和历史输入/结果未运行或覆盖；未新增独立报告、审计、哈希、manifest或保护层。二十题各一次已结束，不自动修复、加预算、重跑或启动下一批。

## 32. 给另一个 GPT 对话的 Q81～Q100 二十题测试提示词

复制下方代码块内容作为另一个GPT对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 执行d3-plan.md第31节Q81～Q100二十道新QA原题，各一次完整真实运行；只做必要论文准备、结果评价和回写，不增加多余校验、哈希或测试请求。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能，遵守Stop Ladder和AGENTS.md用户四问。在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第29.7节及第31节，实际执行本批。第1～30节旧提示仅作历史，不运行旧main或重跑旧题，保留工作区已有修改。

固定题单D3-Q81～D3-Q100，五篇各四题，论文R26～R30及question_id见第31.1／31.2节。按QASPER paper_id+question_id从eval/qasper/raw/qasper-dev-v0.3.json提取question，保持原始大小写／拼写／语法／空白，不自己出题、润色或trim；Q88／Q90有尾部空格。规划已对照历史题单，不另写排重、题单校验或预检程序。只向业务流程传原问、实际版本配对与普通完整回答要求，观察重点、官方参考、可回答性标签、gold evidence、预期数值／公式／表号／chunk和指定工具动作都不注入前置规划、模型消息或检索参数，不用QASPER full_text代替真实入库检索。

用户允许必要论文入库。固定R26 1908.10084v1、R27 2002.01320v1、R28 2002.03407v1、R29 1910.14599v1、R30 1901.01010v1，PDF链接见第31.1节。相同固定材料已有ready或bundle则用现有能力复用；缺少时才下载并走import_runtime.import_pdf默认mineru-api官方API入口解析／索引，沿当前VLM／OCR／公式／表格和索引profile，actual paper_id/parse_revision取ready返回。不重建其他论文索引，不预造ID，不额外探测模型／embedding／API。单篇失败记录对应四题未执行、继续其他独立论文；共享故障阻断后保存并停止，不换题、换版、换解析器。

二十题按Q81→Q100各一次完整真实d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，每题独立新会话／注册表，同论文不传前题答案、工具历史或准备事实。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、单次30秒、五步／五次取证、原网络重试一次／共享修复一次，embedding和重排沿当前profile。沿用第29.7节稳定引用链路，记录实际提示／动作／JS版本；GPT执行而业务模型不切换。不改业务代码、提示或预算，不恢复普通[n]自动转换。模型自主决定检索、阅读、JS和停止，不强制读表、算数、耗尽额度或输出某个编号。

使用artifacts/v3/d3-qa-q81-q100-20261028/下普通input.json/results.json，stage=d3-qa-q81-q100，会话／提交ID为d3-qa-q81-q100-20261028-q81至-q100，完整JSON／Markdown由runtime写archive/run_logs/d9/。复用tmp/d3_prepare_q61_q80.py、tmp/d3_build_q61_q80_input.py、tmp/d3_qa_q61_q80_run.py的准备／输入／顺序执行方式，必要时只新增本批窄入口，替换五篇四题、起止序号、stage、目录和ID，不运行旧main或覆盖旧产物，不建通用框架。沿用尝试状态，请求前保存；已尝试题只整理、接续未尝试题。失败、中断、部分回答、缺引用或没用工具均不补跑，不追加追问或替代题。

本轮没有业务行为修改，复用第29.7节已通过且对应代码未变的验证，不重跑离线方法、Q50／Q69、语法扫描或全量回归。真实调用只包括必要入库及二十题正常流程和原额度内重试／修复；不发独立judge、fixed_rag、固定证据、连通性、计费或额外模型请求，不增加ready／题单／引用／来源校验器、缺引用补引或语义审核。不要新增或手工计算哈希，也不新增审计、manifest、快照、保护层和独立验证报告。

生成后按第31.5节结合实际原文及官方各份参考评价，运行状态、核心内容、模型格式和实际来源支持分开。数字／单位／对象／条件／并列项要对应，训练与推理耗时、绝对结果与相对提升不混用；题意／参考分歧按证据说明，正确不足可以通过，不以隐藏参考强迫唯一口径。准备正确而最终遗漏、材料可达却没读及不必要评论分别据本轮日志定位，不中途修业务、改提示或加预算。

引用用原始响应、answer.text、已有ref和citations/evidence_sources直接观察；普通书目号保留，出现次数与去重来源分计，valid和空检查不当交付／语义通过。未自然触发某种重排／裁剪／格式分支就说明未触发，不为凑覆盖加请求，不要求旧编号／数量。无claims的旧指标不适用，不据不同新题批次直接宣称准确率或速度提升。沿用实际请求／tokens／报告耗时、工具、embedding／重排、重试／修复、JS及引用统计，入库和问答分开；缺失费用不记零、不追加查询。

在d3-plan.md第31.6节补记实际论文准备、逐题内容／引用评价、实际用量和产物链接，保留第32节为文末可复制提示词。二十题各一次或明确故障停止后结束，向用户简要说明实际完成情况，不自动修复、加预算、重跑旧题或开始下一批。
```

## 33. 对齐 RAGFlow 的统一工具循环与宽松运行限制，复测 Q93／Q99／Q100（2026-10-28）

状态：**已实施；指定方法通过，Q93/Q99/Q100各一次真实复测已完成，结果见第33.8节。**统一工具循环、取消自主强制准备JSON与旧小限制，仅复测三道指定题。第1～32节及历史结果保留；本节取代此前交互Agent“五步／五次取证、整题共享一次修复／网络重试、单次30秒”的执行要求，执行使用文末第34节GPT提示词。

### 33.1 依据与本轮目标

第31.6节的三道未通过完整交付标准的题，分别反映不同环节：

- **Q93未交付：**[旧记录](../../archive/run_logs/d9/agent_20261028_115552_637541_e9fc9b3d1eda.json)在第2个自主步骤、仅1次取证后，把chunk_id字符串写入要求整数的 `citation_refs`，一次共享修复后仍错，`answer=null`。本题没有耗尽五步，直接失败点是强制 `prepare_answer` 结构与修复终止门槛。
- **Q99部分通过：**[旧记录](../../archive/run_logs/d9/agent_20261028_115822_065718_64923a450974.json)准备保留了联合模型只在部分数据集优于文本模型的条件，最终首尾却概括为联合最好；实际cs.lg上BILSTM 81.1%高于JOINT 79.9%。观察统一正文路径能否保留例外，不预设去掉准备必然解决。
- **Q100部分通过：**[旧记录](../../archive/run_logs/d9/agent_20261028_115840_596044_a9677ef4dfcd.json)仅交付Wikipedia 59.4%，遗漏已入库表中的三项arXiv绝对accuracy。一次搜索后停止，没有继续阅读。放宽额度给予模型继续取证的空间，但不强制其读取特定表格，也不声称旧遗漏由五步用完造成。

参考仓库 `E:/project/ragflow` 只读。迁移依据为 [120轮默认值](E:/project/ragflow/internal/agentic_rag/agent.go:127)、[正常工具循环](E:/project/ragflow/internal/agentic_rag/agent.go:475)、[最后正文采集](E:/project/ragflow/internal/agentic_rag/agent.go:615)、[工具错误作为观察返回](E:/project/ragflow/internal/agentic_rag/helper.go:81)、[每次模型调用重试](E:/project/ragflow/internal/agentic_rag/agent.go:150)以及[恢复与综合收尾](E:/project/ragflow/internal/agentic_rag/agent.go:551)。不要求每题先提交事实JSON；正常答案不固定多一次改写；异常时尽量利用本轮已有结果。

### 33.2 新交互Agent策略

下表针对当前 `mode="agent", library_mode=True` 的自主问答路径。共享组件作必要适配，旧fixed_rag／历史记录及其他调用者的既有默认行为保持可消费，不重写旧成绩。

| 项目 | 本轮实施值／行为 |
|---|---|
| 自主循环 | 默认 **120轮**，可配置正整数；120是默认运行上限，不再把参数合法范围写死为1～5。模型可以提前回答，不要求跑满 |
| 工具额度 | 删除独立五次search/read_context门槛，搜索／阅读／JS及可恢复错误由同一循环管理；一条响应可含多个工具调用，统计实际次数，不把120轮误报成固定120次工具 |
| 正常回答 | 使用原生tool_calls；模型不请求工具时直接交最终自然语言正文，经现有引用解析发布。自主路径不再强制解析 `prepare_answer / facts / citation_refs / evidence_quotes / answerable` |
| 可恢复纠错 | 工具参数／不可用工具／可修正输出或引用错误反馈给模型，在统一循环内纠正，不设整题“仅一次修复、再错即终止”的独立小额度；纠错仍占正常循环，实际用途与错误均记录 |
| 网络重试 | 改为 **每次逻辑模型调用最多重试1次**，重试只针对现有可重试网络／HTTP错误；整题总重试数保留统计，不作为后续调用失去重试资格的依据。保留SDK隐式重试关闭的现有方式 |
| 单次模型超时 | 本轮默认 **300秒，可配置**，同步实际生效的 `LLM_TIMEOUT` 与交互policy；不能policy改大、底层配置仍30秒，因 `min(policy, settings, remaining)` 导致实际继续30秒。300秒是本项目本轮选定值，不声称是参考仓库所有模型请求的统一默认 |
| 整题总预算 | 沿用当前交互路径 `max_attempts=None / total_timeout=None`，不新增整题tokens配额；120轮承担主循环上限。RAGFlow另有15分钟／默认50万tokens，并非无限制，但本轮不把这些新增到当前流程 |
| 异常综合 | 无可复用最终正文时，基于本轮已取得证据进行一次不带工具的综合，单次逻辑调用使用 **90秒**超时并沿每调用一次网络重试；实际用量归入本题。正常已交付时不额外综合，不增加按字数判短答、独立judge或第二套收尾循环 |

模型保持 `deepseek-flash`、1,048,576上下文、temperature 0.2、4,096输出；embedding／重排和索引profile沿当前配置。来源身份、论文／解析版本范围、实际保留原文及ref映射、普通 `[n]` 不转换等现有约束继续有效。网络调用连续失败、鉴权／配置错误不会通过把同一请求无意义重复120遍来处理：按现有错误分类记录，能恢复本轮已有效正文则恢复，否则在可调用条件下收尾；真实阻断如实交付失败状态。

### 33.3 统一主循环、正常交付与异常收尾

1. **统一原生工具循环。**修改 [agent.py](../../paper_assistant/agent.py)、[agent_prompt.py](../../paper_assistant/agent_prompt.py)、[agent_actions.py](../../paper_assistant/agent_actions.py) 的自主路径和必要调用方：模型可以继续搜索／阅读／计算，或直接交最终正文。移除自主路径强制 `AgentAction / prepare_answer` 解析、`pending_preparation / gap_evidence_decision / finalize_prepared` 依赖及“先准备后才能回答论文事实”的提示；旧模式确实仍使用的协议按其现有调用保留，不为新路径建立第二套事实表或兼容猜配层。现有原问、多轮指代及检索规划职责继续沿用，不另增前置阶段。
2. **正文就是正常最终结果。**自主调用允许原生工具及自然语言输出，不固定要求JSON。不带工具且完整返回的正文使用本轮已展示原文及稳定ref，直接走既有规范化、引用关联和发布；重复引用位置、来源列表、原始响应与交付正文仍同源。不把过程消息拼成多份答案，不固定再调用模型润色一遍。空输出、截断或可修正的显式引用错误使用现有错误信息回到循环，在剩余轮次内修正；普通书目号或无句柄正文继续既有语义，不新增缺引用强制补引。
3. **工具错误作为模型可读观察。**原生工具的字段错误、不可用工具或当前可恢复执行失败返回说明，允许修参数、换工具或利用已有原文回答；恢复不改变论文选择与来源权限。保留实际失败记录和真实调用统计，不把失败工具包装成成功取证。不新增全局错误次数关卡或错误评分器。
4. **复用本轮已有最终正文。**循环异常结束时，优先使用本轮已形成、绑定相应证据快照并已通过现有引用处理的最终正文，零新增模型请求。不复用输入历史的答案、工具调用消息、旧prepare JSON或“我继续查一下”叙述。RAGFlow的本轮非空assistant文本恢复条件较宽，这里利用已有正文状态／类型，不新增语义审核器来猜是否可用。
5. **没有正文才综合。**达到循环上限或研究阶段异常、又没有可复用正文时，给模型原问题与本轮实际取得且可引用的原文／ref，要求不再调用工具，直接答能够支持的内容并说明具体缺口。保持本轮来源映射、统计与请求记录，不重开新问答、不伪装为新的首次运行、不重置累计用量，也不新增脱离用户停止语义的后台任务。综合本身仍失败或来源不合法时记录真实终态，不能宣称保证answered；本地导出失败不重新调用模型掩盖写入故障。
6. **继续使用稳定证据链路。**保留提问内注册表、合并／阅读／排序／容量拟合后的ref及可见权限，正常工具循环、恢复和综合都沿同一来源身份；收尾不能把已移出当前有效证据范围的旧号重新当可引用证据。旧的 `[ID:n]` 格式规范化及普通 `[n]` 保留规则继续使用，不新增引用扫描或语义核验层。

### 33.4 必要配置与消费者适配

同步 [d9_runtime.py](../../paper_assistant/d9_runtime.py:184) 的五步入口、[agent.py](../../paper_assistant/agent.py:1006) 的1～5参数检查与D8冻结预算检查，以及 [llm_client.py](../../paper_assistant/llm_client.py:53) 的policy合法值、reserve／invoke实际重试计数：不能只把一个5改成120，其他硬限制仍拦住新策略。新策略在交互Agent生效，移除该路径对小阶段／一次纠错的依赖；旧调用者默认预算不因共享代码适配被无意放宽。

网络重试额度在每次invoke内部计算，整题预算继续汇总所有HTTP尝试、用途、失败、tokens和耗时。纠正与收尾用途如实记录，不通过把repair伪装成普通answer绕过额度检查；新路径取消对应小额度即可。单次超时同步配置入口、`.env.example` 和实际生效的 `LLM_TIMEOUT`，只改相应配置键，模型和凭据等其余配置保持原值；收尾请求的90秒与普通300秒可在同一现有客户端／预算下按用途取值，不建立额外客户端池或预算管理框架。

提示词清理过时的五步／五次取证、强制准备JSON、准备后禁止继续取证等互相竞争的要求，保留原问题、事实范围、必要条件和ref约定；正常循环提示允许自主继续或直接回答，收尾提示才要求停止工具。同步实际受影响的提示／动作／运行版本并记录，不伪造未实施版本号。不专门注入三题诊断、表号、数值或“务必读表”指令，也不顺带修表caption、重分块或改检索／充分性策略。

必要适配 [app.py](../../app.py)、[agent_export.py](../../paper_assistant/agent_export.py) 及现有统计消费者，使“无prepare阶段”不会被误显示为失败，页面和导出按实际轮次上限／工具计数、直接正文／恢复／综合呈现。本轮输出仍沿用现有prose与来源字段，旧记录可读；不增加聊天持久化／恢复界面或另建验证报告。

### 33.5 两个指定现有测试，页面仅在实际改动时增加一项

默认仅同步并运行以下两个方法，在原方法内使用通用本地mock覆盖变化；相关共享fixture按新自主协议调整，旧fixed_rag／历史消费覆盖保留，不以删除行为断言换取通过。

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：正常“工具→直接正文”且没有强制准备／额外改写；超过5轮及5次取证仍可继续，默认120配置生效；工具错误后继续、输出／引用纠错不受一次共享额度终止；已有正文恢复不增请求，无正文综合及综合失败如实记录；稳定ref／非连续号、容量权限、JS、原始正文／引用位置、资源关闭、JSON／Markdown／历史消费保持。用较小显式上限覆盖触顶收尾，不为了验证120而真的循环120次。
2. `scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts`：在新交互策略下，同一整题budget的两个独立invoke各首次失败、各重试成功，整题累计重试2次但每次最多1；同一invoke连续两次失败不继续发隐藏请求，失败／成功attempt与usage均保留；普通较长超时及收尾90秒实际传入，不仍受30秒配置夹住。保持旧默认调用者的既有语义，不做真实服务探测。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts
```

**仅当页面消费者代码或其结果消费合同实际改变时**，再同步运行 `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`，验证直接正文／恢复记录与3／9非连续句柄的展开、下载／导出一致；页面未变则复用第29.7节通过结果，不为凑数执行第三项。

只在失败或发现具体跨模块影响时扩大到直接相关的已有方法；修复后仅重跑对应代码已变或失败的方法。对应代码未变的通过结果直接复用。不跑整模块／目录／全量，不另做语法扫描、旧输出重放、注册表遍历、预算压力实验、独立judge或连通性校验。本地测试不发真实聊天、embedding或重排请求，不新增或手工重算哈希。

### 33.6 三道原题原版本，各一次完整真实复测

指定本地方法通过后，从 [上一批input](../../artifacts/v3/d3-qa-q81-q100-20261028/input.json) 按题号提取原问、question_id及selected_versions，题号保留，不新编Q101等编号。复用两个ready版本，不下载／OCR／解析／索引／入库。

| 题号 | 官方原问与question_id | 固定本地版本 |
|---|---|---|
| D3-Q93 | `What data sources do they use for creating their dataset?`；`af5730d82535464cedfa707a03415ac2e7a21295`；R29／QASPER `1910.14599` | `local_b19a4645dc9a4be2bcf862c8aa4c7209 / r_0cc2a70ae303ce19` |
| D3-Q99 | `Which is more useful, visual or textual features?`；`23e2971c962bb6486bc0a66ff04242170dd22a1d`；R30／QASPER `1901.01010` | `local_d5ee5a495df14748b2404aa549766cde / r_8bf7ad71d160973e` |
| D3-Q100 | `What is their system's absolute accuracy?`；`fc1679c714eab822431bbe96f0e9cf4079cd8b8d`；R30／QASPER `1901.01010` | 同Q99 |

按Q93→Q99→Q100各一次新的完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`，独立新会话／注册表，使用本节新策略；同论文两题之间不传历史。只向正常业务流程传原问、实际版本及普通完整回答要求，不传旧答案、诊断、官方参考、gold evidence、预期数值／表号／chunk、指定工具或强制格式。新的通用工具循环／ref约定由业务提示生效，不为这三题单独写修复提示，不用QASPER全文代替真实检索。

目录为 `artifacts/v3/d3-react-rerun-q93-q99-q100-20261028/`，stage=`d3-react-rerun-q93-q99-q100`，会话／提交ID为 `d3-react-rerun-20261028-q93`、`d3-react-rerun-20261028-q99`、`d3-react-rerun-20261028-q100`。保存普通 `input.json / results.json`；完整JSON／Markdown仍由runtime写入 `archive/run_logs/d9/`。记录实际新循环／重试／超时配置、提示／动作／运行／JS版本，不能把上一批五步／30秒或旧提示版本写成本次实际策略。

复用 `tmp/d3_stable_citation_q50_q69_run.py` 或 `tmp/d3_qa_q81_q100_run.py` 的顺序调度与尝试状态，必要时新增本轮窄入口（如 `tmp/d3_react_q93_q99_q100_run.py`），替换三题、stage／目录／ID及新策略统计，不运行旧main或覆盖历史。请求前保存尝试，已尝试题只整理、接续未尝试题；失败、中断、部分通过或缺引用都不补跑，不追加追问。三题之间不改代码、提示或预算；固定版本不可用或共享故障阻断后如实记录，不自动重入库。

一次完整运行包括正常规划、原生取证／JS、纠错／重试及必要异常收尾，均记入该题实际调用；这不等于每题仅一次HTTP请求，也不等于失败后重开整题。除这三题及正常流程外，不另发模型／embedding探测、fixed_rag、固定证据、judge、计费请求或额外样本。

### 33.7 评价与完成口径

- **Q93：**首先看是否交付正常正文、是否已消除必经准备JSON导致的失败；再评价数据来源、轮次／用途等必要覆盖和实际引用。只有“没报schema错”不能算内容通过；即使仍有缺口也按所问核心与已取得证据评价。
- **Q99：**最终主结论、中段和结尾都应保留数据集／子集条件，不将有例外的联合模型概括为所有情况最好；引用定位正确不证明这种泛化成立。数字比较区分准确率百分点差与相对增幅。
- **Q100：**分别评价Wikipedia与arXiv三个子集的绝对结果及模型／指标／条件对应；仅给Wikipedia、仍未取得可达表时记录部分通过，不把“当前没读到”当“全文没报告”。不为通过强迫读表或事后补跑。

直接对照原生日志记录正常直接回答、实际工具／纠错／网络重试、触顶／异常收尾及ref沿用情况，不要求三题必须超过5轮或触发某错误；未自然出现的分支由本地方法承担，不为凑覆盖增加请求。answered、运行恢复、核心正确、模型格式与实际来源支持分别记录；空valid不是引用交付通过，不预设三题一定改善，也不把变化单独归因于轮数变大。

沿现有统计记录实际HTTP尝试／tokens／报告耗时、模型循环轮数、搜索／阅读／JS、每调用网络重试与全题累计、纠错及恢复／综合调用、引用出现与来源去重。费用缺失如实说明，不追加统计请求；不重算旧二十题成绩，不生成独立审计、验证报告、manifest、哈希、快照或保护层。

实施完成、必要方法通过并三题各一次复测结束后，将实际改动／配置、方法结果、三题内容／引用评价、用量和产物链接补到第33.8节，保留第34节为文末提示词。故障阻断则明确完成部分和实际原因，不虚报实现或真实测试，不自动开始新题。

### 33.8 实施与三题真实复测结果

**实际实施（2026-10-28）：**参考只读RAGFlow `agentic_rag/agent.go`／helper的原生工具循环、错误观察、每调用重试及恢复/综合顺序，完成本项目适配。业务模型、输出容量、embedding/重排及索引profile保持原配置；没有改三题专用提示、表caption、分块或检索策略。

[agent.py](../../paper_assistant/agent.py) 自主路径改为一张本轮证据注册表上的统一工具/prose循环。取消必经prepare_answer、事实/摘录JSON、pending/gap准备状态及固定二次作答；正常无工具完整正文直接经现有规范化→引用关联→发布。search/read_context/JS可同轮多个调用，移除独立五次取证门槛；字段/未知工具/可恢复执行或输出/引用错误返回当前循环纠正，实际repair用途入账。保留版本范围、实际原文/容量权限、稳定ref、普通[n]不转换及显式ID变体，未增加缺引用补引或语义判定器。旧Action/Claim与fixed_rag两阶段协议仍由旧入口使用。[agent_prompt.py](../../paper_assistant/agent_prompt.py)、[agent_actions.py](../../paper_assistant/agent_actions.py) 同步正常原生工具/直接正文合同，移除自主强制准备提示，普通最终正文不固定再生成一次。

**异常路径：**仅恢复本轮已经通过引用处理并绑定相应证据context的最终正文，零新模型请求；历史答案、带工具的过程文本及旧action/facts JSON不作恢复候选。没有该正文时，达到循环上限/研究异常仅做一次无工具综合，基于本轮当前有效原文/ref及已完成计算；90秒、同一client/budget，失败如实结束，不再进入第二综合循环。401/403等鉴权/配置或不可继续调用状态不通过循环反复刷LLM请求；本地清理已有效正文可直接恢复，本地导出不重调模型。

**实际策略与配置：**[d9_runtime.py](../../paper_assistant/d9_runtime.py) 交互Agent默认120轮，`AGENT_MAX_ITERATIONS`/显式max_iterations可设正整数，agent不再1～5拒绝；移除该路径D8冻结小预算门槛。交互Agent policy为temperature0.2、输出4096、request_timeout由实际`LLM_TIMEOUT`同步（本轮300秒）、max_attempts=None、total_timeout=None、max_repairs=None、每invoke最多一次网络重试。共享[llm_client.py](../../paper_assistant/llm_client.py) 按本次invoke计重试、全题统计累计；SDK隐式重试仍关闭，旧默认调用者保留3次请求/一次整题网络重试/一次修复/30秒等默认值，较大显式配置不再被ChatPolicy三次硬上限拒绝。综合用途为synthesis，实际timeout90秒；修正仍记repair，不伪装answer。`.env`仅同步LLM_TIMEOUT=300并添加AGENT_MAX_ITERATIONS=120，`.env.example`与[config.py](../../paper_assistant/config.py)对应；模型和凭据未改动或输出。没有新增整题15分钟/tokens小上限或脱离停止语义的后台任务。

模型仍deepseek-flash、1,048,576上下文；embedding qwen3.7-text-embedding 1024维、重排qwen3-rerank沿现有profile。实施版本：runtime `d9-native-tool-loop-runtime-v2`，Agent `d14-native-tool-loop-agent-v1` / loop `react-native-tools-v1`，工具合同 `v3-native-evidence-tools-v1`，正常循环提示 `v3.0-native-tool-loop-v1`，无工具综合提示 `v4.0-direct-prose-final-v1`，JS mini-racer-0.12.4 / V8 12.6.228.18。[app.py](../../app.py) 与[agent_export.py](../../paper_assistant/agent_export.py) 显示真实轮数、工具动作、取证次数及恢复/综合状态；正文、原文展开、JSON/Markdown/历史继续同源，旧记录无新字段仍可读，没有聊天恢复功能。

**指定本地方法：全部通过。**

| 方法 | 实际结果/覆盖 |
|---|---|
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 最终单方法 **Ran 1 test in 16.622s，OK**。直接正文不额外改写；6次取证/7轮继续、默认120与可配正整数；工具/多次输出及引用纠错、旧action JSON不作终稿；小上限一次90秒综合、综合无效/异常只结束一次、网络失败后综合与鉴权停止；已有有效正文清理恢复0请求；稳定/非连续ref、容量剔除与重展、JS、实际原文/结构化表、资源关闭/保存/下载及fixed_rag旧协议。 |
| `scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts` | 通过。同一题两个invoke分别失败一次再成功，累计重试2次；每invoke连续两次失败即停止，下一invoke仍有自己的重试资格；真实MockTransport超时300/90、purpose及usage/失败记录、旧默认语义和401一次发送。 |
| `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations` | 因页面/导出消费合同实际调整而运行，通过。120轮/工具动作/恢复/综合显示，3/9非连续句柄展开、重复引用与来源分计、下载/导出/历史及旧claims/fixed_rag消费。 |

LLM与页面方法在仅含这三个方法的一次运行中通过，之后其对应行为/消费代码未变，复用结果；失败修正及后述版本记录修正只重跑受影响运行方法。未扩大到其他方法/模块、语法扫描、历史重放或真实探测；本地全部mock，无真实聊天/embedding/重排。没有为了验证120实际跑120轮，也没有新增测试框架或报告。

**三题真实复测：**按Q93→Q99→Q100，从指定旧input保留原问/question_id和两个固定ready版本，各一次完整Agent，独立空历史/注册表。三题之间没有改代码/提示/预算；未下载/OCR/解析/索引/入库，均 **completed/answered、stop_reason=answered**，自然在3/2/2轮交付。没有强制读表/耗尽轮数，没有正常答案的固定二次生成。

| 题号 | 内容与环节评价 | 实际工具/轮数 | 引用出现/本题去重源 | 聊天/报告用量 | 原生日志 |
|---|---|---|---:|---|---|
| D3-Q93 | **运行已交付、核心未通过。**MTurk/ParlAI和人工写hypotheses/核验有据，但漏Wikipedia/HotpotQA、MASC、WikiHow、GLUE RTE/RTE5的premise来源；开头“not assembled from existing text corpora”错误否定。目录Round1/2/3可达，实际只读Dataset collection、HAMLET和Annotation details。 | 3轮；1搜/3读 | 9/5 | 4次/45,560 tokens/20.141秒 | [JSON](../../archive/run_logs/d9/agent_20261028_131331_082592_a2b3a965ea2f.json) / [MD](../../archive/run_logs/d9/agent_20261028_131331_082592_a2b3a965ea2f.md) |
| D3-Q99 | **部分通过。**互补性和中段“只胜text-only于两个arXiv子集”正确，首段仍写joint beats both，末尾仍称两种单模态都非最佳，未保留cs.lg文本模型更强的例外。两次搜索未取得细分结果表。 | 2轮；2搜/0读 | 15/6 | 3次/19,364 tokens/18.672秒 | [JSON](../../archive/run_logs/d9/agent_20261028_131351_336210_686fc536e643.json) / [MD](../../archive/run_logs/d9/agent_20261028_131351_336210_686fc536e643.md) |
| D3-Q100 | **部分通过。**Wikipedia JOINT 59.4%及10次test均值正确；漏arXiv 93.4/77.1/79.9%。读Experimental Results仅返回已见p5_c3/c4，明知Table3未见仍停止，未读可达page6表；不是论文没报告。 | 2轮；1搜/1读 | 6/3 | 3次/18,245 tokens/11.922秒 | [JSON](../../archive/run_logs/d9/agent_20261028_131410_123379_9e4392154b2e.json) / [MD](../../archive/run_logs/d9/agent_20261028_131410_123379_9e4392154b2e.md) |

**格式、来源与未触发分支：**三题均使用标准显式ID，原始最终响应=answer.text，refs沿本轮原文映射、没有准备JSON。Q93的9/5支持写作/核验流程，不支持整体否定已有语料；Q99的15/6支持有条件互补，不支持开头无条件joint beats both；Q100的6/3支持Wikipedia和比较叙述，不能证明全文只有一个绝对accuracy。valid是定位检查而非语义保证。Q99/Q100沿原文写2.9%、5.3%、2.4%等higher，按实际表数值是准确率百分点差，未明确相对增幅口径；三题没有JS/算术分支。

本次Q93消除了必经准备类型错误、取得了正常交付，但核心来源仍未覆盖且有不当否定；Q99最终条件泛化、Q100可达表未读的问题仍在。Q100有118轮剩余仍主动回答，Q93也只用3轮，不将这些缺口归因为额度耗尽。真实运行未触发超过5轮、纠错/网络重试、异常恢复/综合、容量裁剪或ID变体，相关机制只由指定本地方法证明，不为覆盖补实验，不以三题保证总体稳定或单独归因轮数。

**版本记录说明：**三题实际请求均携带正常循环提示 `v3.0-native-tool-loop-v1`，没有调用综合提示；原生日志的`final_prompt_version`误继承了`v4.0-direct-prose-final-v1`标签。三题**全部完成后**仅修正发布版本字段（正常/恢复使用实际循环版本，综合使用综合版本），并在运行方法增加相应断言、重跑通过；生成提示、模型调用和正文未改变，三题未重测。原生日志原值保留，results同时记录reported_final_prompt_version与actual_model_prompt_version，不能把该旧标签当作发生过综合调用。

**实际用量：**入库/索引embedding **0**。问答 **10次聊天HTTP/83,169 tokens/50.735秒报告耗时**，其中3次正常前置规划与7个模型循环轮次；4次搜索、4次本地阅读，共8次取证，轮数与工具次数分计。查询embedding **4次/106 tokens/9.029065秒**，检索报告总11.533759秒；重排 **4次/报告31,421 tokens/1.364525秒**。网络重试/纠错/恢复/综合均 **0**，JS **0次/0秒**。**30处引用，本题来源去重数加总14，全批按paper/version/chunk去重13来源**。无claims旧指标不适用；费用金额未返回，缺失不记零，不追加查询，各类耗时不互斥、不加成墙钟耗时。

**普通产物：**[input.json](../../artifacts/v3/d3-react-rerun-q93-q99-q100-20261028/input.json)、[results.json](../../artifacts/v3/d3-react-rerun-q93-q99-q100-20261028/results.json)，窄入口 [d3_react_q93_q99_q100_run.py](../../tmp/d3_react_q93_q99_q100_run.py)。请求前记录尝试，旧main、旧成绩和旧输入/结果未执行或覆盖；完整JSON/MD只用runtime原生日志。没有judge、额外样本、固定证据、计费/连通性请求、独立验证报告、哈希、审计、manifest或保护层。本轮到此结束，不自动修内容、补跑或开始下一批。


## 34. 给另一个 GPT 对话的统一循环实施与三道错题复测提示词

复制下方代码块内容作为另一个GPT对话的完整提示词，保留首行插件指令。

```text
$stop-that-shit change -- 按d3-plan.md第33节实现RAGFlow式统一工具循环、取消强制准备JSON与五轮等小限制，完成指定现有方法，再真实复测Q93、Q99、Q100各一次；不要增加多余校验、哈希或额外测试请求。

使用插件 [@Stop That Shit（别再造史了）](plugin://stop-that-shit@stop-that-shit)，读取其stop-that-shit技能，遵守Stop Ladder和AGENTS.md用户四问。在D:/course/paper-research-assistant工作，先读AGENTS.md、docs/v3/d3-plan.md第29.7、31.6及33节，实际实施并完成三题复测。第1～32节保留为历史，不执行旧提示或main，不覆盖已有修改和旧成绩。用户已选择完整调整流程与旧限制，不只把一个5改120。

E:/project/ragflow只读，参考internal/agentic_rag/agent.go的120轮／正常工具循环／最后正文／恢复与finalizeAnswer，helper.go工具错误返回和每次模型调用重试机制。按第33.2节：交互Agent默认120轮可配置正整数，取消独立五次取证和强制prepare_answer JSON，正常原生工具调用或直接prose；可恢复工具／输出／引用问题在循环内反馈纠正，不受整题一次共享修复失败即终止。网络是每次invoke最多重试1次，不是单次重试120次；全题次数仍累计。默认普通模型请求300秒可配置，实际LLM_TIMEOUT与policy同步，综合单次90秒；交互max_attempts/total_timeout沿None，不新增15分钟／50万tokens等整题限制。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出及现有embedding／重排profile。

贯通agent、agent_prompt、agent_actions、d9_runtime、llm_client及必要配置／调用方，移除自主路径强制facts/citation_refs/evidence_quotes/answerable、pending preparation/gap/finalize准备状态和过时提示。正常无工具完整正文直接走现有引用处理与发布，不固定二次改写。保留工具结构、论文/版本范围、实际可见原文、稳定ref、容量拟合、普通[n]不转换及当前显式ID格式规范化。旧fixed_rag、旧调用者默认预算与历史记录保持可消费，不全局重写旧协议。同步实际提示／运行版本，不伪造版本号。

同步入口5、参数1～5检查、D8冻结预算及ChatPolicy/reserve/invoke中的旧小限制，避免较大配置仍被下层拒绝；invoke内部管理本次网络重试额度，全题budget保留累计统计和真实用途，不把repair伪装answer。普通300秒和收尾90秒实际生效，配置最小值不能仍是30秒；不输出凭据或改模型/索引配置。工具错误作为可读结果继续，网络按可重试分类处理，鉴权／配置故障不重复刷请求。必要适配页面／导出轮数、直接正文和恢复显示，结果与引用来源继续同源，不加聊天恢复功能。

异常收尾按第33.3节：优先复用本轮已形成且通过现有引用处理、绑定证据快照的最终正文，零新增模型请求；不从旧历史、工具消息、prepare JSON或过程叙述猜答案，不加judge。没有正文才用本轮实际已取得原文／ref进行一次无工具综合，回答支持内容并明确缺口，实际请求归本题；不重开问答、重置累计用量或新增脱离用户停止语义的后台任务，不因本地导出失败重调模型。综合仍失败如实记录。不要额外加入按长度判短答、第二套收尾循环、语义审查或缺引用补引。

默认只同步并运行scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records和scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts两个现有方法，按第33.5节用通用本地mock覆盖直接正文、超过5轮/5取证、工具错误和多次纠错继续、小显式上限收尾、已有正文恢复/无正文综合、稳定ref与保存消费者，以及两个invoke各重试一次和实际超时/统计。不要为了验证120真的跑120轮。仅页面消费者代码或消费合同实际改变时再运行scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；未变则复用第29.7通过结果。失败修复后仅重跑受影响方法，只有具体跨模块影响才扩大，不跑整模块／目录／全量、语法扫描、历史重放或真实服务探测，不新增测试框架、检查器、哈希或独立验证报告。

方法通过后，从artifacts/v3/d3-qa-q81-q100-20261028/input.json取D3-Q93、D3-Q99、D3-Q100，保留原始question、question_id和selected_versions。Q93固定local_b19a4645dc9a4be2bcf862c8aa4c7209/r_0cc2a70ae303ce19；Q99/Q100固定local_d5ee5a495df14748b2404aa549766cde/r_8bf7ad71d160973e。复用ready，不下载/OCR/解析/索引/入库，不预造或替换版本。只传原问、实际版本和普通完整回答要求，不传旧答案、诊断、gold、预期值／表号／chunk或强制工具动作，新通用循环规则由业务提示生效，不为三题专门改提示或补表caption。

按Q93→Q99→Q100，各一次完整真实d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，独立新会话／注册表，用第33.2节新策略，不是旧输出重放。模型自主决定继续取证、计算与停止，不要求跑满120轮或触发错误。记录真实生效的策略、提示／动作／运行／JS版本，不抄旧五步／30秒信息。正常前置规划、循环、纠错／网络重试与必要收尾均属于各题一次完整运行，实际费用和请求必须计入，不另发judge、fixed_rag、固定证据、连通性、计费或额外模型／embedding请求。

目录artifacts/v3/d3-react-rerun-q93-q99-q100-20261028/，stage=d3-react-rerun-q93-q99-q100，会话／提交ID为d3-react-rerun-20261028-q93、-q99、-q100，使用普通input.json/results.json，完整JSON／Markdown由runtime写archive/run_logs/d9/。复用现有两题／二十题顺序调度和尝试状态，必要时只新增tmp/d3_react_q93_q99_q100_run.py窄入口，替换三题和本轮目录／ID／统计，不运行旧main。请求前保存尝试，已有本轮尝试只整理、接续未尝试题；失败、中断、部分通过或缺引用不补跑、不追问、不换题；三题之间不改代码、提示或预算。固定版本不可用或共享故障时记录实际完成部分，不重入库。

按第33.7节生成后评价：Q93看是否正常交付及数据来源覆盖；Q99看最终各处结论是否保留数据集差异和例外；Q100看各数据集／子集绝对结果是否完整，未读到不说全文没有。运行恢复、answered、核心正确、模型格式和来源支持分开；valid／空检查不是语义或引用交付通过。按现有原生日志说明实际工具、纠错／重试、收尾与ref，无自然触发就如实记录，不为覆盖补实验，不以三题改善保证总体稳定性或单独归因轮数。入库0，统计实际循环／HTTP／tokens／报告耗时、工具／JS、网络重试、纠错和恢复／综合、引用／来源；费用缺失不记零、不追加查询。

在d3-plan.md第33.8节补记实际修改／配置、方法结果、三题内容／引用评价、用量与产物链接，保留第34节为文末提示词。不新增审计、哈希、manifest、快照、保护层、独立报告或其他批次，不手工重算PDF／正文哈希。完成后简要交付真实情况；阻断就说明具体原因和已完成部分，不虚报或自动补跑。
```
