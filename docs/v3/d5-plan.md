# D5：阅读反馈与停止规则改进计划（第一轮）

制定日期：2026-11-02（Asia/Shanghai）。

状态：**A／B／C／D 已完成；E 的表题提取修复已实施，指定本地方法通过；F 已于 2026-11-02 完成 21 道历史错题各一次真实当前 Agent 问答与评价：16 道通过、5 道部分通过、0 道未通过、0 道未执行，Q93／Q99 排除且成绩未更新。** 第 11 节保留 D 的实际记录，第 13～14 节保留 E/F 的固定范围与评价口径，第 15 节记录实际配置、逐题比较、取证／停止观察和用量；文末第 16 节为当前提示词，第 10／12 节均为已完成阶段的历史提示。本阶段承接已经收尾的 [D4](d4-plan.md)，不重新执行旧阶段任务，也不把这批历史错题的 16 道通过外推为总体准确率、提示句因果或“其他问题已由表题修复解决”。

## 1. 目标与当前依据

本轮围绕一个具体问题改进：**模型仍缺少原问题所需的材料，已有可用目录或候选线索，却把局部无新增或“说明缺口”当作结束条件。**

第一轮只统一当前自主提示的停止边界、明确 `read_context` 的读取范围，并解释实际阅读结果。继续使用现有混合检索、父子块、表格目录、原文组装、稳定引用和 LangChain／LangGraph 主循环。先让已有能力得到正确使用，不把本轮扩大为检索架构迁移。

### 1.1 当前实际流程

```text
用户问题、所选论文版本与近期对话
→ 前置问题理解与可选查询建议
→ 当前 create_agent 自主循环
  → search：混合召回、RRF、可选重排，再组装实际原文
  → read_context：读取已知 chunk，或目录 parent 对应的子块
  → run_javascript：对已有数值做可选计算
  → 根据原文及工具反馈决定下一步
→ 模型输出完整正文
→ 引用及来源范围检查
→ 页面与导出
```

当前 `agent_graph.py` 的 `validate_final` 与 `langchain_agent.py` 的结束分支负责正文形式、引用和来源范围，不证明原问题的全部必要信息已经覆盖。正常自主路径没有必经 `prepare_answer` 或独立整题充分性判定。

搜索后已经可能取得真实正文并自动补读父内容，不能把“没有调用 `read_context`”直接判作没有阅读或回答不完整。当前正文 parent 按章节范围和 token 预算分组，不一定等于整个章节；表格 parent 保存其解析结构单元及子块关系。

### 1.2 已有失败与边界案例

以 [D4 第 19～19.1 节](d4-plan.md#19-第五部分实际实施记录)与 [issues.md](issues.md) 的最新记录为依据，不混用旧准备协议的故障结论。

| 案例 | 当前记录 | 对本轮的意义 |
|---|---|---|
| Q93：数据来源覆盖 | 最新为部分通过，取得部分来源后仍缺后续材料就结束 | 观察检索方向、后续阅读与必要并列项是否继续覆盖 |
| Q100：绝对结果覆盖 | D 时为部分通过，知道必要表格未取得，当前 parent 阅读没有新增后仍结束；F 修复表题目录后已实际读取 Table 3 并单次通过 | 保留 D 的停止观察；F 另行核对目录恢复不等于内容通过 |
| Q92：确实缺少报告的信息 | 最新为通过，正确说明未见所问指标，未用其他数值冒充 | 保留合理的资料不足回答，避免把所有缺口都改成强制阅读 |
| Q99：比较条件与额外推论 | 最新仍部分通过，既有未取全，也有已知条件没有贯穿概括 | 继续保留问题；本轮不顺带开启生成风格、逐句审核或条件专项修复 |

Q93／Q99／Q100 在 D4 E 均于第 2 轮主动结束，仍有 118 轮，未因额度耗尽、网络重试或异常综合而结束。因此本轮不增加轮数、请求时限或上下文容量。

题号、正确来源、表号、参考答案及具体数值仅用于开发后评价，不能写入业务提示、工具说明或阅读反馈。

## 2. RAGFlow 参考：具体借用什么

参考用户指定的本地 `E:/project/ragflow` 当前 Go 实现，区分程序行为、提示要求与本项目的适配建议。

| 本轮位置 | RAGFlow 实际做法 | 本项目的适配 |
|---|---|---|
| 停止规则 | 普通 Agent 提示要求定位后深读、无结果时改换表达，所需步骤完成且证据回答问题后停止；新的阅读不再改变答案只是辅助信号 | 统一“必要信息尚未取得但有可用线索时继续”与“确实无法补齐时说明限制”的边界，不把一次无新增写成全局停止条件 |
| 阅读反馈 | `list_chunks` 返回锚点、块位置、读取数量与邻域参数；邻域读取返回文档总块数；目标无正文时说明结果含义和恢复方向 | 利用已有返回／展示／新增／未展示字段，补充本次读取范围及结果含义，不新增邻域参数或覆盖率统计 |
| 工具说明 | 明确定位片段与正文阅读的区别，说明仅锚点和邻域读取各自的边界 | 明确单 chunk 与单 parent 的边界，说明目录可直接定位表格；搜索已经提供原文时不强制再读一次 |

参考入口：

- [agentic_rag.yaml](/E:/project/ragflow/conf/agentic_rag.yaml:40)：普通工具循环的检索、深读与停止要求。
- [tool_list_chunks.go](/E:/project/ragflow/internal/agentic_rag/tool_list_chunks.go:40)：阅读工具的参数、范围及返回说明；同文件 `chunksXMLNoText` 说明无正文结果。
- [helper.go](/E:/project/ragflow/internal/agentic_rag/helper.go:721)：深读结果格式；启用重复正文省略时，用 `repeat_note` 说明此前已提供的内容。
- [retrieval_model.go](/E:/project/ragflow/internal/agentic_rag/retrieval_model.go:38)：本轮工具调用／返回的最低检索要求，不是整题完整性验证。

**“已知可达的必要缺口应继续补读”是结合本项目案例形成的适配要求，不宣称 RAGFlow 已有自动保证整题完整的关卡。** 不迁移其最低调用强制、编译 claim 旁路、相关性判定模型、重复正文省略机制或整套工具组合。

## 3. 实施与真实复测总览

A～C 属于一次连续的小范围实施，不为每个部分建立新模式、独立测试批次或额外模型调用。

A～C 与 D 均已完成；D 只观察同一实现的真实效果，未修改业务逻辑或重跑对应代码未变的本地方法。后续同类规划将把必要真实问答测试一并写入实施安排，题目与规模按实际改动确定。

| 部分 | 工作内容 | 交付结果 | 当前状态 |
|---|---|---|---|
| A：当前提示与工具说明 | 统一停止规则，说明 chunk／parent 阅读边界 | 当前自主提示和实际工具描述表达一致 | 已实施 |
| B：阅读结果解释 | 根据实际返回及展示情况补充 `read_context` 反馈 | 模型能区分重复已见、未展示与目标不可用，知道本次只覆盖当前目标 | 已实施 |
| C：本地验证与记录 | 扩充少量现有断言，只运行一个相关现有方法，回写实际结果 | 证明反馈进入当前图的模型消息，现有引用与工具流转保持；效果仍待真实观察 | 已实施；指定方法通过 |
| D：真实三题复测与评价 | Q93→Q99→Q100 各一次当前图问答，同题比较 D4 输出并记录实际取证与内容 | 判断这三道旧题本轮是否改善，不将交付、引用定位或工具次数当作内容通过 | 已完成；Q93 单次通过，Q99／Q100 部分通过；第 11 节 |
| E：表题提取修复 | 修复正常比较符号使 caption 清空的问题，完成一个现有本地方法 | 恢复真实表号／表题进入模型目录 | 已实施；指定方法 29.860s 通过；第 13／15 节 |
| F：历史错题回归与观察 | 排除 Q93／Q99，21 道去重旧题各一次真实问答，含已修复回归题 | 分别评价当前内容及较最近基线的改善／保持／回退 | 已完成；16 通过／5 部分／0 未执行；第 14／15 节 |

A～C 的修改位置如下；后续 E/F 的范围见第 13～14 节：

| 文件 | 本轮职责 |
|---|---|
| [agent_current.py](../../paper_assistant/agent_current.py) | 当前 `AUTONOMOUS_SYSTEM_PROMPT` 及其版本 |
| [agent_actions.py](../../paper_assistant/agent_actions.py) | `read_context_tool_definition` 的工具描述 |
| [agent_state.py](../../paper_assistant/agent_state.py) | `execute_read` 的实际反馈，沿用 `_reply` 和已有状态 |
| [check_d9_e_runtime.py](../../scripts/check_d9_e_runtime.py) | 指定现有 runtime 方法中的少量行为断言 |

这是一份职责安排，不是强制文件锁。仅在当前调用链确有必要时调整直接调用方，并说明原因；不因此整理其他模块。

A～C 不修改分块、目录生成、入库、SQLite／Qdrant、BM25／向量／RRF／rerank、正常搜索后的原文组装或父子关系；不新增 `number_neighbors`、MQE、HyDE、独立审核模型、强制准备 JSON、全局可答标志或自动补查调度器。页面、导出、引用解析、普通书目号处理、模型／索引配置、轮数／超时／重试与异常综合沿用现行行为。后续 E 仅修复运行时目录 caption 提取，按第 13 节执行。

## 4. A：当前提示与阅读工具说明

### 4.1 统一正常循环的停止边界

在 `agent_current.py` 中整合现有相关要求，不连续叠加几段含义重复的规则。围绕原始问题所需的事实、关系、必要条件和并列项说明：

1. 当前材料已经支持所问内容时，可以正常直接回答，不要求额外调用工具。
2. 尚缺必要信息，且已展示目录、已知候选或实际原文提供了相关后续线索时，应选择有意义的下一次搜索或阅读，不把“尚未取得”当成“论文未报告”。
3. 一次局部搜索／阅读无新增，只说明当前查询或当前读取目标没有补入新原文；需要结合已有材料判断是否换方向，不能自动扩大成整节／整篇无答案。
4. 继续取证仍无法补齐、相关目标按实际结果不可用，或现有预算已经结束时，可以依据真实材料回答支持部分并说明具体限制；不要求穷尽全文、遍历所有目录、重复失败请求或跑满轮次。
5. 已有引用数量、片段相关性、调用过工具或定位合法，均不自动证明所问内容完整。

停止选择继续由当前模型／工具循环执行。程序不解析答案寻找表号、不根据固定关键词拦截最终答案，也不新增独立语义判定器。保持对合理资料不足的回答能力，不能把未知指标编出来，不能用其他指标替代缺失项。

本轮只调整正常自主提示的相关语义。异常综合本来已经无工具，不要求它继续搜索或阅读；`PROSE_FINAL_SYSTEM_PROMPT`／`PROSE_FINAL_PROMPT_VERSION`、旧 `agent_prompt.py`／`context.py` 中仍在使用的历史协议保持。

### 4.2 提示版本

A 实施前 `AUTONOMOUS_PROMPT_VERSION` 为 `v3.1-native-tool-loop-prose-citation-v1`，现已更新为 **`v3.2-native-tool-loop-reading-stop-v1`**，实际记录见第 9 节。继续使用已有导入转发，不增加版本登记文件或快照。工具参数 schema 不变，不另升动作 schema 版本。

### 4.3 明确 `read_context` 描述

在 `agent_actions.py` 的现有工具描述中说明：

- `chunk_id` 指向已知候选或实际证据中的一个块；只读该块，没有自动前后邻域。
- `parent_id` 必须来自已展示的阅读目录；读取这个 parent 保存的子块。
- 一个正文 parent 可能只是章节的一部分，读取它不等于读取完整章节。表格有独立目录入口时，可直接使用相应 parent，不需要先搜索命中其子块。
- 读取目录或候选位置本身不授予引用；只有实际进入上下文的原文沿现有规则可引用。

保持 `ReadContextAction` 的字段、二选一目标规则及 `missing_information` 现有要求，不新增必填字段、邻域参数或额外读取模式。`agent_tools.py` 已从该定义构造真实 LangChain 工具，直接复用，不复制另一份描述。

## 5. B：按实际结果解释阅读反馈

### 5.1 复用现有观察与模型消息

`AgentEvidenceState.execute_read` 已记录目标、`returned_ids`、`shown_ids`、`new_shown_ids`、`not_shown_ids`、候选位置和实际可见正文。优先在现有观察中补充简短 `message`，沿 `invoke_read → _reply → LangChain ToolMessage` 进入下一次真实模型请求，同时保留既有 `context_reads` 和工具记录。

不能只把说明写进日志而模型收不到，也不为传递一个说明新增反馈对象层、全局状态或消息类型。`status`、引用身份、原文正文、来源限制和现有错误代码保持。

### 5.2 按已有事实区分情况

| 实际情况 | 反馈应表达的含义 |
|---|---|
| 有新增可见正文 | 说明取得了当前 chunk／parent 范围的内容；是否足以回答仍由模型结合原问判断 |
| 无新增，且目标正文已在当前可见上下文 | 说明正文此前已提供，仍可使用；本次只覆盖当前目标，其他相关位置需要结合现有目录选择 |
| 目标存在，但存在未展示正文 | 依据 `shown_ids`／`not_shown_ids` 及现有省略信息说明当前未完整可见；不能一律说“已经提供”，不臆造未展示原因 |
| 目标或来源范围不可用 | 沿已有错误和实际范围说明目标不可用，保留已有原文；不把本次目标不可用解释成论文没有报告所问内容 |

**`no_new_shown_evidence` 只表示没有新增展示，不能单凭这个状态判断“目标正文已全部提供”。** 需要结合现有展示字段，避免把容量、省略或来源范围情况误写成重复阅读。

下面是“当前 parent 的目标正文已经可见、没有新增”时的说明示意，不是所有无新增情况统一套用的固定文本：

```text
本次读取范围仅为该 parent 保存的子块，这些正文已在当前上下文中，因此没有新增。
这不代表同章节的其他正文或表格已经读取。
若仍缺原问题的必要信息，请结合现有阅读目录选择其他相关目标。
```

单 chunk 读取按其真实范围说明，不称为整节或整表。没有相关后续线索时，不凭反馈编造 next_parent、表格位置或应该得到的结果。不新增全局覆盖率、完成度分数、整题 `answerable` 或自动穷举目录。

### 5.3 第一轮与邻域读取的关系

本轮不改 `evidence_reading.py` 的父子读取和目录生成，也不新增按锚点前后 N 个块读取。Q100 现有表格入口已经可达，先观察当前目录和工具能否被正确使用。

若后续仍有具体案例证明现有读取方式不便取得已定位内容的前后文，再单独规划邻域读取。该能力解决阅读范围问题，不能代替停止判断；不因本轮效果未改善就自动增加它。

## 6. C：一个现有本地方法与结果回写

### 6.1 默认验证范围

**写本规划不运行测试。未来实施 A／B 后，默认只调整并运行一个现有方法：**

`scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

该方法已有当前图入口、父块／表格阅读、稳定引用、容量、失败、消息及资源场景。优先复用并扩充现有场景中的少量断言：

- 实际 `read_context` 返回的范围说明出现在后续模型请求的对应工具消息中，日志和模型可见内容一致。
- 在已有父块阅读场景中，必要时增加一次同目标读取，确认已见内容的无新增反馈、原文与稳定 ref 保持；已有表格入口仍能继续读取并交付引用。
- 复用已有容量和目标不可用场景，按实际受影响路径确认未展示／不可用结果不会被误说为“所有正文已提供”或“论文未报告”。不为凑分支再复制整套场景。

断言关注调用、消息传递、实际字段和引用行为，不新增整段提示快照、关键词清单扫描或镜像实现的测试。mock 中安排了后续阅读，不代表真实模型一定会选择后续阅读。

保持真实聊天、embedding、重排、MinerU 和 judge 请求为 0。模型适配器、网络层、页面与导出没有对应改动时，复用 D4 已通过结果，不重新运行其方法。指定方法失败时只修复本轮直接问题并重跑受影响方法；仅有具体跨模块影响证据才扩大到直接相关的现有方法。遵守 [AGENTS.md](../../AGENTS.md)，不按模块、目录或全量运行，不做全仓语法／导入扫描。

### 6.2 回写与停止

完成 A／B 与必要本地验证后，在第 9 节记录实际改动、提示版本、方法结果与剩余问题，更新本规划及总览索引中的真实状态。该部分现已完成，第 10 节保留为历史提示；D 已按当时的第 12 节执行，结果见第 11 节。当前 E/F 使用文末第 16 节。

A～C 的交付状态为 **“第一轮已实施，本地验证通过”**；D 的真实效果已另行记录在第 11 节。Q93／Q99 不因代码或 mock 通过而关闭；Q100 的本题缺口由 F 的单次通过关闭，但 D4／D5 D 历史成绩保留。A～C 自身不自动新增真实批次；后续 D 已按第 8 节执行，未顺带修其他问题、提交或推送。

## 7. A～C 工程完成口径

当当前自主提示与工具说明统一表达读取及停止边界、阅读反馈沿实际图消息进入模型、现有原文／引用／错误合同保持，且第 6 节必要方法通过时，本轮工程实施完成。

本轮只能说明提示、反馈与调用链已改。不能宣称程序已证明整题充分、真实提前结束已经修复、回答准确率提升或成本下降。当前 `validate_final` 继续执行原有引用和来源检查，不改造成语义完整性审核。

本轮不新增审计、哈希、manifest、快照、保护层、独立验证报告或通用测试平台。

## 8. D：真实复测三道部分通过的旧题

日期：2026-11-02（Asia/Shanghai）。状态：**已完成。** 三题各一次当前 Agent 问答均正常交付并完成事后评价，结果见第 11 节。用户指定测试之前部分正确的题，因此固定为 **Q93→Q99→Q100**，不执行原先列作边界观察的 Q92，不扩展新题或整批十题。

### 8.1 目标与起点

观察 A／B 修改后，当前 Agent 是否取得原问题需要的材料、如何处理局部无新增、何时停止，以及最终内容是否完整且有据。三题的 D4 E 基线都是部分通过；本轮只作同题观察，不运行固定 RAG 或另一套消融。

第 9 节已记录现有本地方法 **Ran 1 test in 31.056s，OK**。对应业务实现未继续变化，直接复用该结果，不为真实测试准备重新运行本地方法、全仓语法检查或模型连通性探测。

### 8.2 固定原问、题号和论文版本

从 [D4 E 的 input.json](../../artifacts/v3/d4-e-old-qa-20261031/input.json)复制三题的 `id`、`question_id`、`question`、`source_paper`、`selected_versions`，保持字符串原样；新批次只重排 `order` 并生成自己的会话／提交 ID。仍保留 D3-Q 题号，明确属于旧题复测。

| 顺序 | 旧题 | 论文 | 原始问题 | 官方 question_id |
|---|---|---|---|---|
| 1 | D3-Q93 | R29 | What data sources do they use for creating their dataset? | `af5730d82535464cedfa707a03415ac2e7a21295` |
| 2 | D3-Q99 | R30 | Which is more useful, visual or textual features? | `23e2971c962bb6486bc0a66ff04242170dd22a1d` |
| 3 | D3-Q100 | R30 | What is their system's absolute accuracy? | `fc1679c714eab822431bbe96f0e9cf4079cd8b8d` |

复用以下两个原 ready 版本，不重新下载、解析、入库或索引：

| 论文 | paper_id | parse_revision |
|---|---|---|
| R29／1910.14599v1 | `local_b19a4645dc9a4be2bcf862c8aa4c7209` | `r_0cc2a70ae303ce19` |
| R30／1901.01010v1 | `local_d5ee5a495df14748b2404aa549766cde` | `r_8bf7ad71d160973e` |

Q99 与 Q100 虽使用同一论文，也必须各自开始新会话和证据注册表，不共享前题答案、工具历史或正文状态。

### 8.3 当前配置与正常调用范围

沿用 A～C 后的当前图路径与模型配置，开始时从现有配置加载并记录实际值，不照抄 D4 输入中的旧提示版本。

| 项目 | 本轮预期配置 |
|---|---|
| 聊天与上下文 | `deepseek-flash`；1,048,576 上下文；temperature 0.2；输出上限 4,096 |
| 提示与图 | `v3.2-native-tool-loop-reading-stop-v1`；`d4-create-agent-evidence-v1`；正文提示继续为现有 `v4.0-direct-prose-final-v1` |
| Agent 与网络 | 120 个模型轮次；无独立取证配额；普通请求默认 300 秒、异常综合 90 秒；每次逻辑 invoke 最多一次网络重试；沿用现有纠错和恢复规则 |
| 检索 | 当前 `qwen3.7-text-embedding`、`qwen3-rerank` 与现有索引 profile；保留混合检索、父子块和表格目录 |

如果实际值存在差异，记录实际配置并在评价中说明比较限制，不在三题之间调配置或为了对齐旧记录偷偷改模型、提示、索引和预算。

每题一次完整调用当前页面使用的入口：

```python
report = d9_runtime.run_question(
    item["question"],
    [(v["paper_id"], v["parse_revision"]) for v in item["selected_versions"]],
    mode="agent", project_root=ROOT, library_mode=True,
    conversation_history=[],
    conversation_id=item["conversation_id"],
    submission_id=item["submission_id"],
)
```

业务输入只包含原问题、固定论文版本和正常运行参数。旧答案、旧评价、QASPER 参考答案、可回答性标签、gold evidence、预期数值／表号／chunk 及指定工具均不注入前置理解、模型消息、查询或阅读参数。QASPER `full_text` 不能替代真实入库检索。

本阶段真实请求仅包括三题正常流程内的前置问题理解、聊天／工具循环、查询 embedding、重排，以及现有策略内网络重试、纠错和必要异常收尾。允许正常自选搜索、阅读、JS 或直接回答，不强制出现无新增反馈、读表或跑满轮数；不追加独立 judge、连通性、计费、MinerU、固定证据或 fixed_rag 请求。

### 8.4 窄运行入口、普通产物与接续

复用 [tmp/d4_e_old_qa_run.py](../../tmp/d4_e_old_qa_run.py) 的正常入口、顺序执行、尝试保存和现有统计方式，必要时仅新增 **`tmp/d5_d_partial_qa_run.py`**。新脚本只适配三题来源、当前配置与反馈统计，不运行或导入执行旧脚本 main，不建立通用批跑平台。

执行者完成该窄入口后，从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 tmp/d5_d_partial_qa_run.py
```

本次 D 已创建并执行这个窄入口，普通产物为：

- 目录：`artifacts/v3/d5-d-partial-qa-20261102/`。
- `input.json`：三道原问、原版本、新批次 ID 和实际配置／提示版本。
- `results.json`：逐题尝试状态、原生完整日志路径、用量、事后评价和简要同题比较。
- 会话／提交 ID：`d5-d-partial-qa-20261102-q93`、`-q99`、`-q100`。
- `task=D5-D`，`stage=d5-d-partial-qa`。完整 JSON／Markdown 继续由 runtime 保存至 `archive/run_logs/d9/`。

沿旧窄入口在请求前保存 `attempted`。同批已尝试的题只整理已有日志，不重复提交；续跑仅接续尚未尝试题，不新增预约、哈希、manifest 或全局去重层。失败、中断、缺引用、内容仍不全均保留本次结果，不补跑、不追问、不替换题。

固定版本不可用时记录受影响题未执行，不重入库；其他独立版本仍可继续。共享配置、资源或服务故障阻断后续正常问答时，保留已完成结果与未执行原因后停止，不反复探测。三题之间不改业务代码、提示、配置或预算，也不自动修复后再重跑。

### 8.5 逐题评价与 D4 同题比较

三题尝试后，由执行对话结合实际最终正文、模型真正见到的原文、必要的固定版本原文及 QASPER 各份参考进行内容评价，不额外调用判题 API。明确这是执行对话的评价；用户未逐题复核时，不写成人工准确率。

| 维度 | 本轮需要说明的事实 |
|---|---|
| 运行与交付 | 是否交付正文，正常自行结束还是出现异常／纠错／恢复／综合；运行失败与内容问题分开 |
| 实际取证 | 搜索、阅读实际取得了哪些必要原文；新增／重复／未展示反馈是否自然出现，模型收到什么并如何继续 |
| 停止选择 | 最终答案是否仍缺必要信息；有缺口时是否仍有明确可用线索，或确实无法补齐；不以轮次更多作为改善 |
| 引用 | 本题 `[ID:n]` 是否映射真实可见原文，原文是否支持对应事实及条件；`valid` 不代替语义支持 |
| 核心内容 | 每题记为通过、部分通过、未通过或未执行，说明依据和残留问题 |

以下观察点仅用于生成后评价：

| 旧题 | D4 E 基线与本轮重点 |
|---|---|
| Q93 | 基线部分通过，来源和轮次覆盖不全；看本轮是否取得并准确组织原问题所需的数据来源与构造关系，是否仍只答一部分就停止 |
| Q99 | 基线部分通过，部分条件已知但开头概括过强，另有无据默认选择建议；看细分比较证据、条件例外是否贯穿首段／正文／结尾，附加判断是否有据。仅观察，不顺带修生成策略 |
| Q100 | 基线部分通过，绝对结果覆盖不足，可达表未取得；看各数据集／子集结果和条件是否齐全，未取得与全文未报告是否分清 |

主要基线为 [D4 E results.json](../../artifacts/v3/d4-e-old-qa-20261031/results.json)及对应原生日志，不重新运行旧实现，不覆盖 D4 的七通过／三部分结论。允许搜索直接取得充分正文而无需另读；若无新增反馈没有自然触发，如实记录，不能靠额外强制调用补覆盖。

本轮是三道已见问题的复测，不是整体准确率、独立因果实验或新题泛化评测。单次改善可能包含模型采样变化；三题仍有问题也如实保留，不为得到通过而重试。

### 8.6 实际用量、结果回写与结束条件

沿现有记录汇总模型轮次、聊天 HTTP／SDK 尝试、tokens、报告耗时、搜索／阅读／JS 次数、查询 embedding、重排、网络重试、纠错、恢复／综合及引用来源。保留 `context_reads[].message` 和对应 action_steps 工具观察，支持核对反馈是否真正进入模型；直接使用原生日志，不新增独立追踪服务。

报告耗时与各服务耗时可能重叠，不简单相加作为墙钟耗时。金额或用量缺失标为未知并保留已知小计，不填零或为统计补请求。新增入库、解析与索引 embedding 为 0，正常查询 embedding 按实际计入。

将实际入口、每题一次尝试及结果、逐题比较、取证／停止观察、用量和普通产物链接写入第 11 节；按新证据更新 `issues.md` 的最新同题状态并保留历史，更新本规划及总览状态。仅写本轮通过或仍有缺口，不将一次通过扩写成普遍修复。

三题各完成一次尝试并评价后，D 可标记完成；若共享故障导致未执行完，记录已完成题、未执行题和停止原因，不能写成完整三题已完成。结束后不继续修代码、加题、补跑、执行其他对照或提交推送。

## 9. 实际实施记录（第一轮）

**状态：A～C 已实施，指定本地方法通过；A～C 完成时未运行真实问答。** 本节只记录提示、`read_context` 工具描述、阅读反馈及指定现有本地方法的工程改动与本地验证；后续 D 三题的真实结果见第 11 节，不改变本节对 A～C 的验证口径。

| 事项 | 实际记录 |
|---|---|
| A：当前提示与工具描述 | `agent_current.py` 的 `AUTONOMOUS_SYSTEM_PROMPT` 将原有完整性与资料不足要求整合为一段停止边界：所问已支持时直接回答；仍有必要信息且目录、候选或原文给出相关线索时，继续有意义的搜索或阅读；一次局部无新增只表示当前查询或目标未补入新原文，不推成整节／整篇未报告；确实无法补齐、目标按实际结果不可用或预算结束时，说明支持部分和具体限制；不强制读全文、遍历目录、额外读一次或跑满轮次。同时说明 `read_context` 的单 chunk／单 parent 范围、正文 parent 不一定覆盖整节、表格可从目录按 parent 读取，以及目录位置不授予引用。`agent_actions.py` 的 `read_context_tool_definition` 同步上述范围说明；`ReadContextAction` 字段、二选一目标和 `missing_information` 规则未改。 |
| B：阅读反馈与实际消息 | `agent_state.py` 的 `execute_read` 在现有观察中增加简短 `message`，区分取得新正文、目标正文已在当前上下文、仍有未展示正文、目标不可用及来源范围不可用；沿 `invoke_read → _reply → ToolMessage` 进入后续模型请求。既有 `returned_ids`／`shown_ids`／`new_shown_ids`／`not_shown_ids`、候选、`status`、错误码、原文正文和稳定 `ref` 保留；未新增反馈框架、覆盖率或全局完成标志。 |
| 实际修改文件／必要调用方 | [agent_current.py](../../paper_assistant/agent_current.py)、[agent_actions.py](../../paper_assistant/agent_actions.py)、[agent_state.py](../../paper_assistant/agent_state.py)；[check_d9_e_runtime.py](../../scripts/check_d9_e_runtime.py) 仅扩充指定方法。`agent_tools.py` 继续消费实际工具定义，未复制描述；`evidence_reading.py`、检索、分块、索引、图路由、最终引用校验、页面与导出未改。 |
| 当前提示版本 | `AUTONOMOUS_PROMPT_VERSION = "v3.2-native-tool-loop-reading-stop-v1"`，经 `agent_prompt.py` 现有导入转发记录。`PROSE_FINAL_PROMPT_VERSION` 仍为 `v4.0-direct-prose-final-v1`；异常综合仍无工具。 |
| C：指定方法与结果 | 运行 `.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：**Ran 1 test in 31.056s，OK**。在已有父块场景增加一次同目标读取，确认 `no_new_shown_evidence` 的反馈进入最后一次模型请求，10 个原文与 ref 1～10 保持；表格读取的反馈同样进入后续请求；另以现有父块构造受限展示窗口并调用实际 `execute_read`，确认未展示正文不会被说成全部已提供；不可用 chunk 场景确认目标不可用且不表示论文未报告。未新增提示快照、关键词扫描或镜像实现测试。 |
| 真实服务请求 | **0**。聊天、embedding、重排、MinerU、judge、连通性与计费均未调用；验证使用本地 mock。 |
| 真实内容效果 | A～C 完成时未复测。D 三题见第 11 节：Q93 单次通过，Q99／Q100 当时部分通过；F 中 Q100 已因表题目录恢复并实际读表而通过，Q99 仍部分通过。本地 mock 通过本身不能说明真实停止行为改善。 |
| 剩余问题与下一步 | D 已按第 8 节执行并完成评价，见第 11 节；Q93 的 Round 2 续文归属、Q99 首段条件概括仍需后续观察；Q100 的 Table 3 可达未读已在 F 中取得并通过。当前全上下文主路径较少触发未展示分支，A～C 仅以有限上下文路径验证其反馈语义；未开启邻域读取或其他能力。 |

## 10. 给 DeepSeek 的第一轮执行提示词（历史，A～C 已完成）

以下保留 A～C 实施时的原提示，**不再执行**；其中“第 8 节不执行”“第 10 节文末”等表述属于当时范围。当前三题真实复测使用第 12 节，不重跑第一轮实现或本地方法。

```text
执行 docs/v3/d5-plan.md 第一轮 A～C：统一当前自主提示的停止边界，明确 read_context 工具范围，补充实际阅读结果解释，并完成一个相关现有本地方法和实施记录。不要运行真实问答或顺带重构检索。

在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。先读取 docs/v3/d5-plan.md 全文、d4-plan.md 第1和19～19.1节、issues.md 第1.7及1.12～1.14节，再看当前实际代码。D4 已完成，历史提示词不执行。保留工作区现有修改，不重做备份，不自动提交或推送。

A：按 D5 第4节整理 paper_assistant/agent_current.py 的 AUTONOMOUS_SYSTEM_PROMPT，整合已有完整性与资料不足要求，不堆叠重复段落。必要信息仍缺且目录、候选或原文有明确后续线索时，继续有意义的搜索或阅读；局部无新增不能推成论文未报告。所问已充分支持则直接回答，确实无法补齐或现有预算结束时按真实材料说明限制，不强制读全文、遍历目录、额外读一次或跑满轮数。保持自然语言直接正文与模型自主工具循环，不增加 prepare_answer JSON、独立 judge、关键词拦截、全局 answerable 或自动补查关卡。提示中不写 Q93/Q100 等题号、正确来源、表号、参考答案或具体数值。AUTONOMOUS_PROMPT_VERSION 更新为 v3.2-native-tool-loop-reading-stop-v1，沿现有导入转发记录。PROSE_FINAL 提示及版本、旧 agent_prompt.py/context.py 的有效协议保持，异常综合仍无工具。

同在 A 中修改 agent_actions.py 的 read_context_tool_definition 描述：chunk 只读指定块，parent 只读目录中该 parent 保存的子块，一个正文 parent 不一定覆盖整节，表格可从目录直接按 parent 读取。目录位置不是可引用原文。ReadContextAction 字段、二选一目标及 missing_information 规则不改，不新增 number_neighbors 或工具模式。agent_tools.py 已消费该定义，复用实际封装，不复制另一套工具描述。

B：按 D5 第5节，在 agent_state.py 的 execute_read 现有观察中增加简短、事实准确的 message，沿 invoke_read/_reply 和实际 ToolMessage 进入后续模型请求，不只写日志。复用 returned_ids/shown_ids/new_shown_ids/not_shown_ids、候选和现有省略信息，保持 status、错误码、正文和稳定 ref。区分新增正文、目标已在当前上下文、正文未展示、目标或来源不可用。no_new_shown_evidence 本身不证明全部正文已提供，未展示时不要一律写成重复已见，不臆造原因或后续位置。已完整可见的重复 parent 阅读可说明“本次只覆盖该 parent，其他相关位置请结合现有目录判断”。单 chunk 按真实范围说明。不要新增反馈框架、覆盖率、全局完成标志或目录穷举器。

本轮保留混合检索、重排、分块、父子块、表格目录、自动原文组装和稳定引用，不修改 evidence_reading.py 的读取能力。也不改模型/索引配置、轮数/超时/重试、图路由、最终引用校验、页面或导出。文件范围按实际职责决定，只有必要的直接调用方才可调整并说明原因，不顺带清理其他代码。

C：只在现有 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records 中复用现有父块/表格、容量和失败场景，加入少量与改动相关的行为断言，证明反馈进入后续模型请求，重复读取的原文和稳定引用保持，未展示/不可用不被误说成已全部提供。必要时在已有场景加入一次同目标读取，不复制整套场景，不新增整段提示快照、关键词扫描器或镜像实现测试。只运行：
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records

指定方法失败只修复本轮直接问题并重跑受影响方法，只有具体跨模块影响证据才扩大到直接相关的现有方法；未变代码的通过结果复用。不跑模块/目录/全量，不扫描全仓语法或导入。所有验证保持本地 mock，真实聊天、embedding、重排、MinerU、judge、连通性和计费请求为0。不执行第8节真实复测，也不运行 D4 或其他旧批次脚本。

完成后在 D5 第9节填写实际改动、提示版本、方法和结果、剩余问题，更新真实实施状态及总览索引对应说明，保留第10节为文末提示词。代码和本地方法完成可写“第一轮已实施，本地验证通过，真实效果待观察”；未完成如实记录。不能把 mock 通过写成真实停止行为改善，不关闭 Q93/Q99/Q100、不覆盖历史结果、不继续开启邻域读取或其他能力。不新增审计、哈希、manifest、快照、保护层或独立验证报告，不自动提交推送。
```

## 11. D 实际测试与评价记录（2026-11-02）

**状态：D 已完成。** Q93→Q99→Q100 各执行一次当前 `create_agent` Agent 问答，三次均正常交付并完成执行对话评价；未补跑、未换题、未在题间改业务代码／提示／模型／索引／预算。单次结果为 **Q93 通过（仍有 Round 2 轮次归属残留），Q99 部分通过，Q100 部分通过**。这不是人工准确率、全批通过率或对某一提示句的因果结论。A～C 的本地验证仍为第 9 节的 31.056s 结果，未重跑。

### 11.1 实际配置、入口与产物

| 项目 | 本次实际生效值 |
|---|---|
| 聊天与生成 | `deepseek-flash`，`https://api.deepseek.com`，1,048,576 上下文，请求超时 300 秒；temperature 0.2，输出上限 4,096 |
| 网络重试 | 每次逻辑 invoke 最多 1 次；本批实际网络重试 0、纠错 0、恢复／综合收尾 0 |
| 提示与图 | `v3.2-native-tool-loop-reading-stop-v1`；`PROSE_FINAL_PROMPT_VERSION=v4.0-direct-prose-final-v1`；图 `d4-create-agent-evidence-v1`；运行器 `d9-native-tool-loop-runtime-v2` |
| Agent 预算 | 120 个模型轮次；无独立取证配额；异常综合 90 秒；本批三题均未耗尽轮次 |
| 检索 | `qwen3.7-text-embedding`（1024 维）、`qwen3-rerank`（30 秒）、profile `ep_cbf0f6caa97b962a`；复用原 ready 版本与索引，未新增入库、解析或索引 embedding |
| JavaScript | `mini-racer-0.12.4`，5 秒、64MiB；本批未调用 |

与第 8.3 节预期一致。与 D4 E 基线相比，除提示版本由 `v3.1-native-tool-loop-prose-citation-v1` 变为 `v3.2-native-tool-loop-reading-stop-v1` 外，模型、上下文、temperature、输出上限、embedding／rerank、索引 profile、120 轮和超时设置相同；因此同题比较包含提示版本差异和单次采样波动，不能单独归因于某一句提示。

运行入口为 [tmp/d5_d_partial_qa_run.py](../../tmp/d5_d_partial_qa_run.py)，命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tmp/d5_d_partial_qa_run.py
```

三题都先写 `attempted` 再提交；本次没有续跑。普通产物为 [input.json](../../artifacts/v3/d5-d-partial-qa-20261102/input.json) 与 [results.json](../../artifacts/v3/d5-d-partial-qa-20261102/results.json)；完整原生日志：

- Q93：[agent_20261102_120015_545363_550d7bd281da.json](../../archive/run_logs/d9/agent_20261102_120015_545363_550d7bd281da.json)、[Markdown](../../archive/run_logs/d9/agent_20261102_120015_545363_550d7bd281da.md)
- Q99：[agent_20261102_120041_877673_057064747df6.json](../../archive/run_logs/d9/agent_20261102_120041_877673_057064747df6.json)、[Markdown](../../archive/run_logs/d9/agent_20261102_120041_877673_057064747df6.md)
- Q100：[agent_20261102_120118_628526_ce69768e75dc.json](../../archive/run_logs/d9/agent_20261102_120118_628526_ce69768e75dc.json)、[Markdown](../../archive/run_logs/d9/agent_20261102_120118_628526_ce69768e75dc.md)

业务输入仅含原问、固定版本和正常参数；旧答案、旧评价、QASPER 参考、可答标签、gold、预期来源／表号／数值／chunk 与指定工具均未注入。评价时才使用固定版本原文与 [QASPER dev 原参考](../../eval/qasper/raw/qasper-dev-v0.3.json)。

### 11.2 逐题结果与同题比较

| 旧题 | 本轮交付与用量 | 本轮核心 | D4 E 基线 | 主要变化 |
|---|---|---|---|---|
| Q93 | answered；4 次 LLM（1 前置 + 3 循环）；0 搜／6 读；7 块；11 引用／6 来源 | **通过**（Round 2 轮次归属残留） | 部分通过；1 搜／1 读；2 轮；6 块；1030 字符 | 从只覆盖 Round 1 扩到 Round 1／3 的来源和 MTurk／ParlAI 构造关系；仍未读 Round 2 同节续文 |
| Q99 | answered；3 次 LLM（1 前置 + 2 循环）；2 搜／0 读；6 块；12 引用／4 来源 | **部分通过** | 部分通过；2 搜／0 读；2 轮；6 块；3164 字符 | 去掉无据的“文本更稳妥”默认建议，保留数据集条件；首段仍有无条件“best results”概括 |
| Q100 | answered；3 次 LLM（1 前置 + 2 循环）；1 搜／1 读；6 块；7 引用／5 来源 | **部分通过** | 部分通过；1 搜／1 读；2 轮；6 块；1030 字符 | 新增可读的 parent 范围 message，答案更明确区分可见材料与 Table 3；绝对结果覆盖未改善 |

**Q93。** 回答按 Round 1／2／3 组织：Round 1 给出 Wikipedia（250–600 字符）来自 HotpotQA 训练集，以及 ground-truth／TF-IDF 检索两种上下文；Round 2 给出 RoBERTa 的训练数据（SNLI、MNLI、FEVER 的 NLI 版本和 A1）；Round 3 给出 Wikipedia、Common Crawl News、Story Cloze／CBT fiction、MASC、WikiHow 和 RTE5；另说明 MTurk 工人通过 ParlAI 写 hypotheses、模型误判后由人工核验、训练／开发／测试集的构造关系。QASPER 两份参考中的 Wikipedia／HotpotQA、MASC、RTE5（另一份还含 WikiHow）均已出现，构造关系比基线完整，故本次核心记通过。残留是：读取 parent10 只取得被截断的 Round 2 前半段，目录中同节的 parent12 续文未读；回答因此只说该轮 context sources 未见于已取材料，没有补出“again constructed from Wikipedia via HotpotQA”。它没有把缺口说成论文未报告，但轮次归属仍不完整。

**Q99。** 正文和结尾保留条件：Wikipedia 上 visual-only 比 text-only 高 2.9%，arXiv 上为 competitive；joint model 在 Wikipedia 和 3 个 arXiv 子集中的 2 个胜过 text-only，并非所有子集都最好；结尾也明确增益不统一。问题在首段仍写“the best results come from combining them”，没有先写“取决于数据集”；原文在 cs.lg 上 BILSTM 最高，因此该无条件开头与正文／原文冲突。另有一处轻微误述：可见的 p7_c3 已明确写出 cs.lg 上 BILSTM 最高，回答却把“未胜过 text-only 的子集”说成只在结果表中、未写出 cs.lg。实用建议已从 D4 的“只能选一种时文本更稳妥”改为“visual 在 Wikipedia 略优、arXiv 相当”，不再是无据的默认排序；但首段条件仍未贯穿，核心仍记部分通过。第二次搜索返回 `no_new_shown_evidence` 后直接回答，没有继续读细分表，精确子集数值仍缺。

**Q100。** 回答正确给出 Wikipedia JOINT 59.4%、十次 test 均值、相对 BILSTM 高 5.3%、相对 INCEPTION 高 2.4%，并给出 arXiv 的相对比较；明确说 Table 3 不在已取材料中、不能从当前证据给出 arXiv 绝对值，没有把“未取得”写成“论文未报告”。但原问题要求的 cs.ai／cs.cl／cs.lg 绝对结果 93.4／77.1／79.9 仍缺；首句“one explicit absolute accuracy figure”也可能被读成全文只有一个绝对值，后文才限定为可见材料，措辞不够精确。读取 parent19 返回 `no_new_shown_evidence`，message 说明“该 parent 保存的子块正文已在当前上下文中……本次只覆盖该 parent……不代表同章节其他正文或表格已经读取”，该 message 已进入实际 `ToolMessage`；目录中存在 Table 3 的 parent22，模型没有继续读取即结束。属于可达材料未取得，不是服务故障或轮次耗尽，核心仍部分通过。

### 11.3 取证、反馈与停止观察

- **Q93：** 没有自然触发无新增反馈。6 次读取均为 `success`；每次的成功 message 都说明只覆盖该 parent，parent10 的 message 已进入下一次请求。模型在该提示后仍选择结束，目录中的 parent12（Round 2 续文）和 parent11（同节表格）未读；3 个循环轮次后停止，未耗尽 120 轮。
- **Q99：** 第一次搜索取得 6 个块；第二次搜索返回 `no_new_shown_evidence`，模型收到后直接回答，没有读表或继续搜索。无 `read_context`，因此没有阅读反馈分支；未耗尽轮次。
- **Q100：** 读取 parent19 返回 `no_new_shown_evidence`，message 进入实际 `ToolMessage` 并出现在下一次模型请求；模型没有把它当作“论文未报告”，但也没有沿目录读取 Table 3。1 个搜索轮次、1 个阅读轮次后停止，未耗尽 120 轮。
- 三题均为 `answered/answered`，无网络重试、纠错、恢复、综合收尾或预算截断；没有失败、缺引用或未执行题。

### 11.4 用量与引用

| 题目 | LLM／HTTP／SDK 尝试 | tokens | 报告耗时（秒） | 搜索 | 阅读 | JS | 查询 embedding | 重排 | 引用次数／来源 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q93 | 4／4／4 | 37,486 | 26.125 | 0 | 6 | 0 | 0 | 0 | 11／6 |
| Q99 | 3／3／3 | 19,598 | 36.610 | 2 | 0 | 0 | 2 | 2 | 12／4 |
| Q100 | 3／3／3 | 19,363 | 24.250 | 1 | 1 | 0 | 1 | 1 | 7／5 |
| 合计 | 10／10／10 | 76,447 | 86.985（逐题相加） | 3 | 7 | 0 | 3 | 3 | 30／15 |

- 批跑按起止时间约 87.3 秒；上表 86.985 秒是逐题报告 elapsed 的合计，不把聊天、embedding、重排耗时再简单相加为服务总耗时。金额未从现有账本得到，标为未知；没有为统计追加请求。
- 三题 `citation_status` 均为 `valid`，共 30 次引用／15 次逐题来源计数（不是全批去重来源数）；引用均映射实际展示块，但 `valid` 不等于语义完整，Q93 的 Round 2、Q100 的 arXiv 绝对值仍不能由已展示块补出。
- 对话轮次为 4／3／3 次 LLM 调用（含 1 次前置理解），自主循环步骤为 3／2／2；无表格 evidence、无 JS 调用。新增入库、解析、索引 embedding 为 0；3 次查询 embedding 已计入上表。

### 11.5 剩余问题与产物状态

- Q93 的来源覆盖已明显补齐，但 Round 2 同节续文仍未读；该题本次单次通过，问题记录保留并继续观察，不据此关闭或声称普遍修复。
- Q99 的正文条件更完整、默认建议更有据，但首段仍把“结合”写成无条件最佳；后续若修改，应针对比较条件在首段／正文／结尾的一致性，不增加逐句审核模型。
- Q100 的 no-new message 已真实到达模型，但模型仍停在没有读取可达 Table 3 的位置；后续若观察，应继续区分“可达未读”和“全文未报告”，不强制每题读表或增加表格扫描器。
- 本轮只说明三道已见题的单次结果，不覆盖 D4 的七通过／三部分历史，不外推总体准确率、泛化效果或提示句因果。
- 本批只发三题流程内的聊天、查询 embedding 和重排请求；未另发连通性、计费、MinerU、judge、固定证据或 fixed_rag 请求，新增入库／解析／索引 embedding 为 0。未修业务代码、未加题、未补跑、未开启邻域读取，也未提交或推送。

## 12. 给 DeepSeek 的真实三题复测提示词（历史，D 已完成）

以下保留 D 实际执行时的原提示，**不再执行**，其中“第 12 节文末”等表述属于当时范围。当前 E/F 使用文末第 16 节，Q93／Q99 不重跑。

```text
执行 docs/v3/d5-plan.md 第8节 D：真实复测此前部分通过的 D3-Q93、D3-Q99、D3-Q100，顺序固定，每题各一次完整当前 Agent 问答；生成后逐题评价，与 D4 E 同题比较，回写第11节。不要运行 Q92、其他旧题或新题，也不要修代码后重跑。

在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 D5 第1～3、8～9、11～12节，D4 第19～19.1节及 issues.md 第1.12～1.14节。A～C 已实施，现有 runtime 方法已通过（31.056s），代码未继续变化则直接复用，不重跑本地方法或全仓语法/导入检查。D5 第10节及 D4 历史提示不执行。保留工作区修改，不重做备份、不自动提交推送。本次是正常真实三题测试，允许其流程内聊天、查询 embedding、重排及既有策略内重试、纠错和必要收尾，不额外发连通性、计费、MinerU、judge、固定证据或 fixed_rag 请求。

从 artifacts/v3/d4-e-old-qa-20261031/input.json 直接复制三题的 id/question_id/question/source_paper/selected_versions，保留原始字符串和 D3-Q 题号，只按 Q93→Q99→Q100 重排 order 并设置本批新会话/提交ID。固定 R29：local_b19a4645dc9a4be2bcf862c8aa4c7209 / r_0cc2a70ae303ce19；固定 R30：local_d5ee5a495df14748b2404aa549766cde / r_8bf7ad71d160973e。复用原 ready 版本，不下载、解析、入库、重建索引或换版。Q99/Q100 同论文也使用独立新会话、注册表和空 conversation_history，不共享前题材料。

沿当前 d9_runtime.run_question(question, pairs, mode="agent", library_mode=True, conversation_history=[], project_root=ROOT, conversation_id=本题新ID, submission_id=本题新ID) 执行，实际走当前 create_agent 图。业务输入只有原问、所选版本和正常运行参数，不注入旧答案、旧评价、官方参考、可答标签、gold、预期来源/表号/数值/chunk 或指定工具；QASPER full_text 不替代真实入库检索。模型自己选择搜索、阅读、JS 和停止，不强制触发无新增、读表或用满轮次。

保持当前 deepseek-flash、1048576 上下文、temperature 0.2、4096 输出、v3.2-native-tool-loop-reading-stop-v1、现有正文提示/图、embedding/rerank/profile、120模型轮次、普通默认300秒/综合90秒及每次逻辑invoke最多一次网络重试。开始时从现有配置记录实际生效值，存在差异就记录并说明比较限制，不偷偷改配置；三题之间不改代码、提示、模型、索引或预算。

复用 tmp/d4_e_old_qa_run.py 的窄批跑方式，必要时只新建 tmp/d5_d_partial_qa_run.py，适配三题来源、当前版本/配置和实际统计，不运行旧main，不新建通用测试平台。普通目录 artifacts/v3/d5-d-partial-qa-20261102/，input.json/results.json，task=D5-D，stage=d5-d-partial-qa；会话/提交ID分别为 d5-d-partial-qa-20261102-q93、-q99、-q100。完整 JSON/Markdown 仍由 runtime 保存 archive/run_logs/d9/。完成窄入口后运行：
.\.venv\Scripts\python.exe -X utf8 tmp/d5_d_partial_qa_run.py

请求前保存 attempted；本批已有尝试只整理原生日志，续跑仅接未尝试题。失败、中断、缺引用或内容不足均保留，不补跑、不追问、不替换题。固定版本不可用记受影响题未执行，不重入库；共享配置/资源/服务故障阻断后续则保存完成部分及原因后停止，不反复探测。不新增预约、哈希、manifest、快照、审计、保护层或独立验证报告。

三题生成后，结合实际最终正文、真正进入模型的原文、必要固定版本原文及 QASPER 各份参考作执行对话评价，不另调判题API。运行交付、实际取证、停止选择、引用支持与核心内容分开，核心记通过/部分通过/未通过/未执行。Q93 看所需来源范围与构造关系是否补全；Q99 看比较条件是否贯穿首段正文结尾、附加选择建议是否有据；Q100 看各数据集/子集绝对结果及条件是否齐全、可达材料未读与全文未报告是否分清。这些只用于事后评价，不能灌入被测输入。模型直接搜索取得完整证据也可通过，不以阅读次数、answered或valid判内容正确。未自然触发无新增反馈就如实记录，不加调用补覆盖。

主要基线用 artifacts/v3/d4-e-old-qa-20261031/results.json 及原生日志，不重跑旧版本、不覆盖旧七通过三部分结果。本轮只说明三道已见题的单次结果，不能外推总体准确率、泛化效果或单独归因于某句提示；用户未复核时不要写成人工准确率。用现有账本记录模型轮次、HTTP/SDK、tokens、报告耗时、搜索/阅读/JS、查询embedding、重排、重试、纠错、恢复/综合及引用来源，并保留 context_reads.message 和实际工具观察。耗时不简单相加，未知金额/统计如实标未知，不填零或为统计追加请求；新增入库/解析/索引embedding为0。

将实际配置、入口和产物链接、逐题结果/同题比较、取证与停止观察、用量和剩余问题填入 D5 第11节；按本次实际结果更新 issues.md 同题最新状态并保留历史，更新 D5 和总览状态，保留第12节为文末提示词。三题全部尝试且评价后才写 D 完成；未执行完如实记完成部分和停止原因，不虚报。完成后停止，不自动修问题、增加题目、重跑、开启邻域读取或提交推送。
```

## 13. E：Q100 表题目录缺失的最小修复

制定日期：2026-11-02（Asia/Shanghai）。状态：**已实施；指定本地方法通过。** 本轮接续已完成的 D，只修有直接证据的表题提取问题，不调整停止提示；随后执行第 14 节历史错题复测。

### 13.1 失败链路与实际证据

Q100 的最新运行没有读取表格，但不能把原因全部归为模型不愿继续。核对 D 的原始模型消息与 SQLite 保存的 parent 后，发现：

- R30 的 `parent22` 已保存 Table 3 的完整表格及原文，首行以 `Table 3: Experimental results.` 开头。
- 该首行含统计检验条件 `p < 0.05`。`evidence_reading.py` 的 `_table_caption` 因 `"<" not in first` 条件，把正常表题整行排除。
- 模型真正收到的目录条目为 `content_type="table"`、`section_path=["INCEPTION"]`、`caption=""`，没有显示它是 Table 3。
- 因此需要区分“数据库里有可调用的表格 parent”和“模型收到清楚的表号／表题”。本轮修复后再看停止行为，不预设修复后一定读表。

证据入口：[Q100 最新完整 JSON](../../archive/run_logs/d9/agent_20261102_120118_628526_ce69768e75dc.json)、[evidence_reading.py](../../paper_assistant/evidence_reading.py)。问题位于运行时目录构造，原始表格已存在，不需要重新解析、分块、入库或索引。

### 13.2 修复策略与代码范围

优先在现有 `_table_caption` 内采用直接修正：继续使用 `_TABLE_CAPTION` 判断首行是否以真实表号开头，移除“任何 `<` 都让整条 caption 为空”的过宽排除。现有表号前缀判断已经可以排除以 `<table>`／`<tr>` 开头的纯 HTML 表体，不为此引入 HTML 解析器或另一套内容提取流程。

修复后的要求：

1. 普通表题中的 `p < 0.05`、`n <= 100` 等比较表达按原文保留，不能删掉符号、截断条件或只剩表号。
2. 没有表号前缀的 HTML 首行不能被当作表题。不扩大成任意片段或整张表的扫描。
3. `reading_directory` 沿当前调用链发送真实 caption；页码、parent 身份、表体、child IDs、原文和稳定引用保持。
4. 不把 Q100 的题号、目标表号、数据集或正确数值写进业务分支，不强制模型读指定表；修复对所有符合条件的表题生效。

预计业务修改仅涉及 `paper_assistant/evidence_reading.py`，本地断言在现有 `scripts/check_d9_e_runtime.py` 中调整；必要直接调用方按实际依赖处理。本轮不修 `section_path` 生成、不改 PDF 解析器、父子块、邻域读取、混合检索、模型配置或提示词；当前自主提示版本仍为 `v3.2-native-tool-loop-reading-stop-v1`。

### 13.3 必要本地验证

在现有 `RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` 的表格 fixture 中，让表题包含正常 `<`／`<=` 比较条件，沿实际目录构造与图入口检查模型收到的 caption 保留完整表号、标题和条件，并继续能按 parent 读正文及交付引用。针对纯 HTML 首行的非表题情况，复用已有场景，必要时只增加一个小断言，不新建整组测试或 HTML 清洗框架。

只运行这个现有方法：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

E 修改了被该方法覆盖的业务路径，因此此处需要重新运行一次；A～C／D 的旧通过记录保留，不重复运行其余对应代码未变的方法。失败只修本次直接问题并重跑受影响方法，具体跨模块证据才扩大范围。该检查保持本地 mock，真实服务请求为 0，不跑模块、目录、全量或全仓语法／导入扫描。

**实际结果（2026-11-02）：** `_table_caption` 只移除了 `"<" not in first` 的过宽排除，仍由 `_TABLE_CAPTION.match(first)` 要求 `Table N`／`表 N` 前缀；未新增 HTML 解析、表体扫描或 Q100 专用分支。表格 fixture 的 caption 改为 `Table 2: Recovered measurements (p < 0.05; n <= 100)`，断言实际决策消息收到完整 caption，并继续按 parent 读取表格、交付引用；另加一个 `_table_caption({"text": "<tr>..."}) == ""` 的小断言。指定方法 `Ran 1 test in 29.860s`，`OK`。该结果只说明目录信息恢复与调用链保持，不说明 Q100 内容通过。

E 完成只说明目录信息恢复与调用链保持；Q100 是否读到缺失表格、最终是否完整，由下面 F 的正常真实问答判断。

## 14. F：历史错题去重后的复测，排除 Q93／Q99

状态：**已完成。** 2026-11-02 在 E 的本地方法通过后，按固定名单各执行一次真实问答；21 题全部 answered，16 通过、5 部分通过、0 未通过、0 未执行。用户要求重跑此前错题，故既包含仍部分通过的题，也包含后来已修复的历史错题，后者作为回归观察，不把当前状态追改为错误。

### 14.1 题目范围与去重口径

依据 v3 各批 `results.json` 的逐题总体／核心评价和交付记录，收集曾评为部分通过、未通过或未交付的题。仅 `focus=partial`、回答稍长，或已废弃可选短答字段有风险而主答总体通过的，不另扩成错题。按原问题和版本／官方 question_id 对同题复测去重；历史同题不同批次不是多道题。

固定为 **21 道、19 个原论文解析版本**，Q100 先运行，然后按下表顺序完成其余题。Q93／Q99 及其不同阶段同题记录均排除；不增加新题、普通通过题或 v1／v2 的另一套评测。D2-Q15 与后续 D3-Q15 是同一官方问题，本批只运行一次。

| 顺序 | 历史题号 | 原问题（执行时从来源复制，不手工重录） | 输入来源 | 历史问题与最近基线 |
|---|---|---|---|---|
| 1 | D3-Q100 | What is their system's absolute accuracy? | S10 | D5 D 仍缺绝对结果；本轮先修目录表题再观察 |
| 2 | D1-06 | 论文讨论部分指出，系统在食材组合与风味化合物方面存在什么局限？西方菜谱和东亚菜谱在搭配上有什么相反倾向，这可能怎样影响研究结果？ | S1 | 曾缺跨块必要引用；定向修复后通过，检查回退 |
| 3 | D1-N03 | What non-annotated datasets are considered? | S2 | 无据外推全文不存在其他数据来源；最新部分通过 |
| 4 | D1-N05 | How big is slot filing dataset? | S2 | 把语料名称与用途误判为矛盾；最新部分通过 |
| 5 | D1-N07 | How are resources adapted to properties of Chinese text? | S2 | 资源适配必要项不全；D2 两次观察后仍有缺口 |
| 6 | D1-N10 | 请把刚才对目标函数的解释改成面向没有机器学习背景读者的说明，不写公式，仍说明食材和国家信息怎样一起学习，以及它在食材替换中的用途。 | S2 | 通俗化追问及阶段归属风险；最新部分通过 |
| 7 | D2-Q01 | Why is supporting fact supervision necessary for DMN? | S3 | 因果问被升级为必要性证明、旧短答不一致；最新部分通过 |
| 8 | D2-Q12 | what language pairs are explored? | S4 | 曾漏具体语言方向；局部修正后通过，检查回退 |
| 9 | D2-Q13 | What experiments are proposed to test that upper layers produce context-specific embeddings? | S4 | 曾漏必要分析项；局部修正后通过，检查回退 |
| 10 | D2-Q15 | What is the performance of BERT on the task? | S4 | 曾缺绝对指标；D3 同题读表后通过，检查回退 |
| 11 | D3-Q23 | What is the model performance on target language reading comprehension? | S5 | 曾缺目标语言主结果；正文复测后通过，检查回退 |
| 12 | D3-Q25 | How much does their model outperform existing models? | S5 | 曾最终格式失败未交付；正文复测后通过，检查回退 |
| 13 | D3-Q29 | Which component is the least impactful? | S5 | 曾不比较／算术出错；可选计算复测后通过，保留比较口径 |
| 14 | D3-Q37 | What are the results from these proposed strategies? | S6 | 缺所问精确结果；最新部分通过 |
| 15 | D3-Q44 | How do they match words before reordering them? | S7 | 已读 parse tree 信息未利用，错误声称缺材料；最新部分通过 |
| 16 | D3-Q50 | Which 7 Indian languages do they experiment with? | S7 | 曾误判七语言集合及引用问题；最新核心通过，仍有附加评论 |
| 17 | D3-Q57 | By how much more does PARENT correlate with human judgements in comparison to other text generation metrics? | S8 | 缺 how much 所需相关系数与差值；最新部分通过 |
| 18 | D3-Q66 | What is the architecture of the model? | S9 | 架构说明缺必要网络结构；最新部分通过 |
| 19 | D3-Q69 | How do they calculate variance from the model outputs? | S9 | 历史引用未交付及归一化尺度遗漏；最新部分通过 |
| 20 | D3-Q71 | Which model do they use for end-to-end speech recognition? | S9 | 未明确实际语音识别模型结构；最新部分通过 |
| 21 | D3-Q79 | How are similarities and differences between the texts from violent and non-violent religious groups analyzed? | S9 | 遗漏比较所需归一化／聚合步骤；最新部分通过 |

输入来源对应如下。每题的原始 `selected_versions` 是固定版本依据，不能根据论文标题自行换版本；D1 来源中额外的 code／title 可作批次元数据，传给运行入口时仍只取 paper_id／parse_revision。

| 来源 | 原 input.json |
|---|---|
| S1 | [d1-agent-ten-20261026/input.json](../../artifacts/v3/d1-agent-ten-20261026/input.json) |
| S2 | [d1-new-ten-20261026/input.json](../../artifacts/v3/d1-new-ten-20261026/input.json) |
| S3 | [d2-qa-new-ten-20261027/input.json](../../artifacts/v3/d2-qa-new-ten-20261027/input.json) |
| S4 | [d2-qa-dev-next-ten-20261027/input.json](../../artifacts/v3/d2-qa-dev-next-ten-20261027/input.json) |
| S5 | [d3-qa-new-ten-20261028/input.json](../../artifacts/v3/d3-qa-new-ten-20261028/input.json) |
| S6 | [d3-qa-next-ten-20261028/input.json](../../artifacts/v3/d3-qa-next-ten-20261028/input.json) |
| S7 | [d3-qa-q41-q50-20261028/input.json](../../artifacts/v3/d3-qa-q41-q50-20261028/input.json) |
| S8 | [d3-qa-q51-q60-20261028/input.json](../../artifacts/v3/d3-qa-q51-q60-20261028/input.json) |
| S9 | [d3-qa-q61-q80-20261028/input.json](../../artifacts/v3/d3-qa-q61-q80-20261028/input.json) |
| S10 | [d3-qa-q81-q100-20261028/input.json](../../artifacts/v3/d3-qa-q81-q100-20261028/input.json) |

D1-N03／N05／N07 的官方 ID 存在原行的 `source.question_id`，应保留该来源结构或正确提取；自建问题与追问没有官方 ID 时如实留空，不编造。来源混合 QASPER train／dev、自建题和追问，保留逐题原来源，不把整批统一写成官方 dev 验收集。

### 14.2 唯一追问题：保留原始前序对话

**D1-N10 是 `followup_of:D1-N09`。** 它的原问包含“刚才”，不能像独立问题一样传空历史，也不能改成一个新独立问题。

从原 [D1-N10 完整记录](../../archive/run_logs/d9/agent_20261026_075324_400898_2f0a17b6625f.json) 的 `conversation_history` 复制当时的一轮 N09 历史，作为该题固定的正常前序背景。`results.json` 的 `conversation_history_used` 是数量，不是可直接传入的历史列表。不要为了生成历史重新调用 N09，不把 N10 旧答案、旧评价或官方参考放进历史。

前序模型结论继续只帮助理解指代与表达要求，不自动成为论文证据；原文与引用仍按当前流程取得。其余 20 题使用空历史，各题都用本批独立新会话、提交 ID 和注册表，不互相继承状态。

### 14.3 最近基线与同题判断

本批既比较旧错误，也比较最近一次真实状态，不能只挑最差旧答作为基线：

- D1-06 用 `d1-term-citation-fix-20261026`；D1-N07 用 `d2-evidence-history-fix-20261027-rerun`；D1-N03／N05／N10 用原批对应记录。
- D2-Q12／Q13 用 `d2-clarification-sufficiency-rerun-20261027`；D2-Q15 用 `d3-table-reading-q15-20261028` 中 D3-Q15；D2-Q01 用原批记录。
- D3-Q23／Q25 用 `d3-prose-compute-rerun-20261028`；Q29 用 `d3-final-calculation-q29-20261028`；Q50／Q69 用 `d3-stable-citation-q50-q69-20261028`，Q69 引用未交付的旧观察也保留。
- Q37／Q44／Q57／Q66／Q71／Q79 用各自原批；Q100 用 D5 第 11 节及 `d5-d-partial-qa-20261102` 的最新记录，D4／D3 仅作更早历史。

各基线均使用已保存结果，不重新运行旧实现。已通过的历史错题按当前自然语言和显式 ID 合同检查回退，不要求恢复旧 direct_answer、claims 或 prepare_answer。

### 14.4 真实执行与批次保存

E 的业务修复和指定本地方法通过后，直接按固定名单各运行一次当前 `d9_runtime.run_question(..., mode="agent", library_mode=True)`。独立题传空历史；仅 N10 按第 14.2 节传固定历史。保留原问、原版本和正常参数，不注入旧该题答案、评价、gold、预期来源／数值／表号／chunk 或工具调用顺序。

沿用 D 阶段的 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4096 输出、120 模型轮次、普通默认 300 秒／综合 90 秒及现有每 invoke 网络重试规则；embedding、重排和索引 profile 沿当前实际配置。记录实际值，题间不改业务、提示、模型、预算、索引或评价口径。21 次完整问答可能包含多次聊天／查询 embedding／重排请求，不把它记成总共 21 个 HTTP 请求。

固定原 ready 版本；由正常运行入口进行就绪检查。不可用的版本记受影响题未执行，不擅自重解析、重入库或换版；其他独立题可继续。共享服务／配置故障阻断后续时保存已完成结果和未执行原因后停止，不追加探测。

复用 `tmp/d5_d_partial_qa_run.py` 的正常调用与逐题尝试保存方式，必要时只新增 `tmp/d5_f_history_wrong_qa_run.py`，适配多来源题目、N10 固定历史、混合来源元数据和最新基线。普通目录为 `artifacts/v3/d5-f-history-wrong-qa-20261102/`，保存 `input.json`／`results.json`；`task=D5-F`、`stage=d5-f-history-wrong-qa`。会话／提交 ID 为 `d5-f-history-wrong-qa-20261102-` 加小写完整历史题号，例如 `...-d3-q100`、`...-d1-n10`。

```powershell
.\.venv\Scripts\python.exe -X utf8 tmp/d5_f_history_wrong_qa_run.py
```

本次 F 已创建并执行 `tmp/d5_f_history_wrong_qa_run.py`，按固定名单各运行一次；请求前保存 `attempted`，已尝试题只整理原生日志，未启动续跑。每题一次；运行失败、缺引用、内容部分或模型没读表均保留，不补跑、不追问、不替换题，也未在本批中途修复后重来。

真实请求仅为 21 题正常前置理解、聊天／工具循环、查询 embedding、重排及既有策略内网络重试、纠错／必要收尾。无额外 judge、固定证据、fixed_rag、连通性、计费、MinerU 或单独“验证 caption”的模型请求；不强制读表、用 JS、固定次数阅读或穷尽目录。

### 14.5 评价重点与交付

参照第 8.5～8.6 节，分别评价运行交付、实际取证、停止选择、引用支持和核心内容，逐题记通过／部分通过／未通过／未执行，并与最近基线比较“改善／保持／回退”。修复范围只有表题提取，观察范围是 21 道历史错题，不预设这一小修会解决其他架构、计算或生成问题。

- Q100 核对真正进入模型的目录是否恢复表号／表题，是否取得必要结果；标题恢复但仍没读取要如实记录，不能把元数据通过当内容通过。
- 其他表格／数值题核对指标、数据集、单位、表头与数据行、绝对结果和相对差值；允许搜索直接取得充分正文，不以是否显式阅读判成败。
- Q29 按原问及明确声明的比较口径评价，计算需要正确，不以隐藏参考的唯一聚合口径替代题意；Q69 关注归一化尺度及引用交付，不强制调用 JS。
- N10 同时评价追问承接、无公式与通俗表达，以及表示学习／替换候选／概率评估的阶段归属；不再以旧可选短答字段为当前必须输出。
- 对参考可答性或版本有分歧的题（如 Q44），依据实际固定版本原文说明；实际已经展示的内容才可判为“已给而未用”，不能把完整论文里存在的事实误说成模型已收到。

由执行对话结合原生日志、实际可见原文及必要固定版本／参考作事后评价，不另调 judge；用户未复核时不称人工准确率。完整日志继续由 runtime 写 `archive/run_logs/d9/`，用量、消息／工具反馈与评价留在普通 results 和本规划，不另建验证报告。

在第 15 节写逐题同题比较、目录变化、调用与用量、产物链接及残留问题，按新事实更新 issues.md 与总览，保留所有旧结论。可以统计本批题数，但它是历史错题集合，不外推总体准确率、泛化或全部改善均由 caption 修复造成。

21 题各完成一次尝试且评价后，F 才可写完成；有未执行题就如实记录具体原因及完成部分，不虚报完整批次。结束后不自动修其他问题、重跑、加题或提交推送。Q93／Q99 本轮不运行，也不以本批结果更新它们的成绩。

## 15. E／F 实际记录（2026-11-02）

**状态：E 已实施，指定本地方法通过；F 的 21 题已全部尝试并完成评价：16 通过、5 部分通过、0 未通过、0 未执行。**

### 15.1 E：表题目录修复与本地方法

业务修改只有 [evidence_reading.py](../../paper_assistant/evidence_reading.py) 的 `_table_caption`：移除 `"<" not in first` 这一过宽排除，保留原有 `_TABLE_CAPTION.match(first)` 的 `Table N`／`表 N` 前缀要求。正常表题中的 `p < 0.05`、`n <= 100` 因此完整保留；以 `<tr>`／`<table>` 开头、没有表号前缀的 HTML 首行仍不会被当作表题。没有新增 HTML 解析器、整表扫描、Q100 专用分支，也没有改动解析、分块、parent／child、索引、引用、图或提示；自主提示仍是 `v3.2-native-tool-loop-reading-stop-v1`。

[check_d9_e_runtime.py](../../scripts/check_d9_e_runtime.py) 的现有表格 fixture 改为 `Table 2: Recovered measurements (p < 0.05; n <= 100)`，实际决策消息断言完整 caption，继续按 parent 读表并交付引用；另加纯 HTML 首行返回空的小断言。只运行指定方法：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

实际 `Ran 1 test in 29.860s`、`OK`；本地 mock，真实服务请求 0。该结果只证明目录 caption 与读表／引用链保持，不能单独证明 Q100 内容通过。

### 15.2 F：实际配置与产物

使用当前 `deepseek-flash`、1,048,576 上下文、temperature 0.2、4,096 输出、120 模型轮次、普通 300 秒／综合 90 秒、每 invoke 最多一次网络重试；查询 embedding 为 `qwen3.7-text-embedding`（1,024 维、cosine），重排为 `qwen3-rerank`，profile 和 ready 版本沿用当前实际配置。21 题共 **19 个原论文解析版本**，没有下载、解析、入库或重建索引；新增入库／索引 embedding 为 0。N10 从原日志复制一轮 N09 `conversation_history`，其余 20 题空历史；每题独立新会话／提交 ID。请求前写入 `attempted`，21 题一次跑完，没有续跑或补跑。

普通产物：[input.json](../../artifacts/v3/d5-f-history-wrong-qa-20261102/input.json)、[results.json](../../artifacts/v3/d5-f-history-wrong-qa-20261102/results.json)、[运行器](../../tmp/d5_f_history_wrong_qa_run.py)。完整 JSON／Markdown 在 `archive/run_logs/d9/`，逐题 run ID 见下表。Q93／Q99 未运行，成绩未更新。

### 15.3 逐题结果与同题比较

| # | 题 | 核心 | 变化 | LLM | 搜／读 | 引用／来源 | tokens | 秒 |
|---|---|---|---|---|---|---|---|---|
| 1 | D3-Q100 | 通过 | 改善 | 3 | 1/1 | 12/4 | 21,864 | 31.391 |
| 2 | D1-06 | 通过 | 保持 | 3 | 1/1 | 10/4 | 21,435 | 33.984 |
| 3 | D1-N03 | 部分通过 | 保持 | 3 | 0/2 | 6/3 | 16,357 | 20.547 |
| 4 | D1-N05 | 通过 | 改善 | 3 | 1/1 | 6/3 | 17,821 | 36.750 |
| 5 | D1-N07 | 通过 | 改善 | 4 | 2/3 | 16/12 | 48,591 | 51.031 |
| 6 | D1-N10 | 通过 | 改善 | 2 | 0/0 | 7/2 | 12,768 | 19.844 |
| 7 | D2-Q01 | 通过 | 改善 | 4 | 2/1 | 13/8 | 45,455 | 48.406 |
| 8 | D2-Q12 | 部分通过 | 回退 | 3 | 1/1 | 15/3 | 21,970 | 31.422 |
| 9 | D2-Q13 | 部分通过 | 回退 | 3 | 0/2 | 9/5 | 17,436 | 19.500 |
| 10 | D2-Q15 | 通过 | 保持 | 3 | 1/1 | 12/7 | 25,754 | 41.453 |
| 11 | D3-Q23 | 通过 | 保持 | 3 | 1/1 | 7/5 | 22,676 | 33.344 |
| 12 | D3-Q25 | 部分通过 | 回退 | 3 | 1/1 | 13/4 | 22,784 | 34.062 |
| 13 | D3-Q29 | 通过 | 保持 | 4 | 0/2 | 8/3 | 30,983 | 24.937 |
| 14 | D3-Q37 | 通过 | 改善 | 4 | 0/3 | 16/4 | 27,390 | 22.547 |
| 15 | D3-Q44 | 通过 | 改善 | 6 | 2/5 | 11/5 | 79,921 | 55.015 |
| 16 | D3-Q50 | 通过 | 保持 | 3 | 0/2 | 6/2 | 14,839 | 17.281 |
| 17 | D3-Q57 | 通过 | 改善 | 4 | 1/1 | 13/6 | 54,747 | 38.953 |
| 18 | D3-Q66 | 通过 | 改善 | 3 | 0/4 | 24/8 | 27,911 | 23.125 |
| 19 | D3-Q69 | 通过 | 改善 | 3 | 0/2 | 8/4 | 17,042 | 22.406 |
| 20 | D3-Q71 | 部分通过 | 保持 | 3 | 2/0 | 1/1 | 16,209 | 42.250 |
| 21 | D3-Q79 | 通过 | 改善 | 3 | 1/1 | 14/5 | 19,047 | 34.547 |

**Q100（通过／改善）。** 首个实际决策消息的 `reading_directory` 已含 parent22 的完整 caption：`Table 3: Experimental results... one-tailed Wilcoxon signed-rank test; p < 0.05`；随后 `read_context(parent22)` success，返回 p6_c1／p6_c2 的 Table 3 表头与数据行。回答给出 Wikipedia 59.4±0.47、cs.ai 93.4±1.07、cs.cl 77.1±3.10、cs.lg 79.9±2.54，并指出 cs.lg 上 BILSTM 81.1% 更高、arXiv 类别不平衡和 Wikipedia 59.4% 的 headline 含义。相对 D5 D 的“缺三个 arXiv 值”为改善；目录恢复和实际读表同时发生，仍需保留单次采样限制。

**D1-06（通过／保持）。** 读取 Discussion，正确说明食材组合未被表征、烹饪方法未纳入、数据数量／质量限制；西方倾向共享风味化合物、东亚倾向避免共享，作者只说“might get different results”。10 次引用／4 来源，跨块引用完整，未把未读 Table 4 当已见内容。

**D1-N03（部分通过／保持）。** 列出 E2E 51k annotated 与 Wikipedia 约 51K noisy MR–abstract pairs，Wikipedia 字段、规模和 100 篇抽查正确；但把“唯一非人工标注”只归到 Wikipedia。原论文 §4 的 E2E 训练集还分为 10K paired／32K unpaired，官方参考也把 E2E NLG challenge Dataset 与 Wikipedia Company Dataset 并列，因此复数 non-annotated datasets 未答全。基线有无据全文外推，本轮避免了该外推但核心缺口换到 E2E 未配对数据，整体仍是部分通过。

**D1-N05（通过／改善）。** 给出 Train 1,737、Dev 497、Test 559（合计 2,793）句和四类标签计数；读取 parent 返回 `no_new_shown_evidence` 后直接使用已展示表，不重复读。去掉了基线把语料名称与用途误判为矛盾的无据分析，明确“image edit request corpus”与 intent/slot 语料相容。

**D1-N07（通过／改善）。** 读取 Arguments、Relations、Senses，覆盖论证标签歧义、Hypophora／连续问句、主语宾语省略仍标 EntRel、删除 AltLexC、加入 Expansion.Progression 及隐式连接词插入；官方核心“removing AltLexC / adding Progression”已出现。仍明确说具体中文例子和精确替换约定不在所取段落，未编造；但比基线多读了 Section 3.2／3.3 并补齐三维适配。

**D1-N10（通过／改善）。** 仅用一轮 N09 历史，0 搜／0 读；用“特征卡片”解释三类预测、国家与食材共同学习和“酱油−日本+法国”的替换用途，不写公式，并说明权重／共享参数不可见。正文比基线短、阶段归属清楚。残留是“Table 4 由专业厨师从前 10 个建议挑选”这一句超出本次引用块，虽注明表未展开，仍属轻微外细节。

**D2-Q01（通过／改善）。** 先纠正“监督对 DMN 必要”的前提，再给出原 DMN 依赖监督的两条原因：单 GRU 只能看前文、远距离支持句在词级难以交互；并说明 DMN+ 用 input fusion／attention 去除该要求。官方的两条 extractive 理由均出现，且不再以 `Unanswerable` 收尾；因此相对基线改善。

**D2-Q12（部分通过／回退）。** Europarl 的 Fr-En-Es／De-En-Fr／Ro-En-De 及 Fr→Es、De→Fr、Ro→De 已给出；但把 supervised parent 方向写成 En→Es／En→Fr／En→De，缺 Fr-En／Ro-En／De-En 等反方向。MultiUN 已识别为 En＋Ar／Es／Ru 四语言，却只给 Es→Ar、Es→Ru，并说其余语言被截断，漏掉三个非英语语言之间的六个互译 zero-shot 方向，也未列 Ar-En／En-Ru 等父方向。基线已通过并给出这些方向，故本轮为回退。

**D2-Q13（部分通过／回退）。** 正确说明 self-similarity 与 intra-sentence similarity，并说明 Future Work 没有另提实验；但官方三项指标中的 maximum explainable variance 完全缺失，且把“没有另提实验”扩成对原问的否定。基线已覆盖三项分析，本轮为回退。

**D2-Q15（通过／保持）。** 给出 NUBES-PHI（Table 5）detection 0.952／0.979／0.965、classification relaxed 0.938／0.963／0.950、strict 0.925／0.950／0.937；MEDDOCAN（Table 8）detection 0.973／0.972／0.972、classification 0.968／0.967／0.967；并保留 0.979 recall、相对 CRF／spaCy 差值和数据缩减说明。与最近 D3-Q15 基线同为通过。

**D3-Q23（通过／保持）。** 给出 En→Zh 63.3／78.8、En→Kr 49.2／69.3，同语言 81.2／88.6、81.2／88.7、69.41／89.3，以及 Zh→Kr、Kr→Zh 和 translated 设置；明确 Table 1 行未取得，没有扩成全文不存在。与最近基线同为通过。

**D3-Q25（部分通过／回退）。** 给出 Pubmed Table 3 的 full model 44.81／19.74／31.48／20.83、concat 44.85／19.70／31.43／20.83，以及相对 SummaRuNNer／LexRank／Discourse-aware 的差值，并说明 ROUGE-L 落后与显著性 caveat；但明确说 arXiv Table 2 未取得，跨数据集“how much”只完成 Pubmed 一半。基线已同时给 arXiv／Pubmed，故为回退。

**D3-Q29（通过／保持）。** 读取 Table 3，列出 skip connection／undirected／no renormalization／no master node／neighbors-only 的逐数据集差值与均值，选 master-node skip connection 为 least impactful（mean Δ≈+0.02），并声明这是表格算术、论文本身未排名。按三数据集平均符号变化口径自洽；若按最大绝对差则是 undirected 0.33 < skip 0.38，答案已给表值，未把官方口径当唯一，故仍记通过但保留口径限制。

**D3-Q37（通过／改善）。** 读取 Figure 2 所在 parent，取得 A2C 32、KG-A2C 34、A2C-chained 11.8、KG-A2C-chained 41.8、A2C-Explore 40、KG-A2C-Explore 44，并说明 40 分 bottleneck、A2C-chained 低于 A2C、KG-A2C-chained 更快收敛。基线缺四个精确 reward，本轮补齐。

**D3-Q44（通过／改善）。** 明确没有独立词对齐：源句按双语词典逐词翻译，再用 CFILT-preorder 的 generic／Hindi-tuned 规则在英文 parse tree 上重排，并给出 NP+transitive verb 交换例子。此前“已读 p3_c3 的 parse tree 却称未说明”的错误已消除；对“论文未明确声明 negative”保留了推断边界。

**D3-Q50（通过／保持）。** 读取 Table 1，给出 Hindi、English、Kannada、Telugu、Assamese、Bengali、Malayalam，指出正文列表漏 Assamese、Table 1 才完整；区分六个 Indian languages 与作为第七类的 English。与基线同为核心通过，仍保留“English 不是 Indian language”的附加分类评论。

**D3-Q57（通过／改善）。** 读取 Table 2，给出 PARENT*-W 0.913 对 RG-F 0.758 的 0.155 绝对差、PARENT-W 0.838 对 RG-F 的 0.080 差，以及相对 BLEU／ROUGE／METEOR／CIDEr 等的差值；说明 Systems／Hyperparams 两种设置、显著性只部分成立、WebNLG 不能直接外推。基线缺“how much”数值，本轮补齐。

**D3-Q66（通过／改善）。** 读取 Model Overview、Feature Adaptation、DAS、CNN Encoder，说明共享 one-layer CNN（词嵌入→卷积→max-over-time pooling→文档向量）＋softmax 分类器，再叠加 source classification、symmetric-KL 特征适配、熵最小化和 epoch-ensemble bootstrapping。基线缺实际基础架构，本轮补齐 §4.1 结构。

**D3-Q69（通过／改善）。** 从 asymptotic variance 讲起，保留 √n 参数与损失差归一化，给出 ∇ℓᵀ I_q⁻¹ ∇ℓ、Fisher Information Ratio、trace 代理、预训练估计、概率加权梯度平方和 top-K beam；明确不是从模型输出直接算样本方差。基线最终漏 √n，本轮已修正。

**D3-Q71（部分通过／保持）。** 两次搜索只取得 problem formulation 的一般 RNN 句，没有读取已存在的 Experiment／§3 目录，因此未取得 p3_c3 的 spectrogram→两层 2D convolution→七层 bidirectional recurrent→FC softmax 结构；回答只说 RNN 并称具体架构不可见。基线同样部分通过，本轮未改善。

**D3-Q79（通过／改善）。** 说明比较沿内容（word frequency＋NMF topic）与情绪（Depechemood POS、逐词聚合、逐文章情感归一化、100 篇 Reuters 基线）两条线进行，并给出主题相似／差异和“same emotion, different words”的结论。基线遗漏归一化／聚合步骤，本轮明确逐词聚合与逐文章情感归一化；跨语料词频按总词数归一化仍未明说，作为方法细节残留。

### 15.4 取证、停止与引用观察

21 题全部 `answered`，没有 `run_failed`、缺引用或未执行；0 次网络重试、0 次纠错、0 次恢复／综合收尾，120 轮均未耗尽。17 次搜索、35 次 parent 读取、2 次 JS（Q29、Q57），没有强制读表或固定工具顺序。

Q100 是唯一直接验证表题目录修复的题：实际模型消息收到完整 caption，并成功读取 parent22 的 Table 3 两行；这不是把 caption 通过当成问答通过，回答内容也补齐了四个绝对值。Q37 读取 Figure 2、Q66 读取 §4.1、Q44 读取并利用 p3_c3，均对应各自历史缺口；Q71 仍 0 读、Q25／Q12／Q13 均在 `no_new` 或已见证据后停止，未继续读可达表／段，分别形成本轮 5 个部分通过中的 4 个（另一个是 D1-N03 的 E2E 未配对数据）。

所有逐题 `citation_status` 为 `valid`；共 227 次引用出现／98 次逐题去重来源计数。引用支持与内容正确分开：Q100、Q57、Q69 等的关键数值有表／公式块支持；Q71 的 1 次引用只支持一般 RNN 句，不能支持实验架构；D3-Q79 的跨语料词频归一化仍未被引用明确覆盖。

### 15.5 实际用量

| 项目 | 实际值 |
|---|---|
| 完整问答 | 21 题，21/21 answered |
| 聊天／SDK／HTTP 尝试 | 70 次（每题 2～6 次，不是 21 个 HTTP 请求） |
| tokens | 583,000 |
| 逐题报告耗时合计 | 682.795 秒 |
| 批跑墙钟 | 688.097 秒 |
| 查询 embedding／重排 | 17／17 |
| 搜索／parent 读取／JS | 17／35／2 |
| 网络重试／纠错／恢复／综合 | 0／0／0／0 |
| 引用出现／逐题来源计数 | 227／98 |
| 新增入库／解析／索引 embedding | 0 |

金额或未记录的服务小计保持未知，没有为统计追加请求。只用 21 题正常流程内的聊天、查询 embedding、重排及既有策略内重试；未另发 judge、fixed_rag、固定证据、MinerU、连通性、计费或额外验证模型请求。

### 15.6 剩余问题与边界

- **5 道部分通过：** D1-N03（漏 E2E unpaired splits）、D2-Q12（MultiUN 六互译方向及部分父方向缺失）、D2-Q13（maximum explainable variance 缺失）、D3-Q25（只给 Pubmed，缺 arXiv）、D3-Q71（只给一般 RNN，未读实验架构）。其中 Q12／Q13／Q25 相对最近基线为回退，需在后续单独定位；本批未修这些问题。
- **通过题仍有残留：** D3-Q29 的平均符号变化口径与最大绝对差口径不同；D1-N10 的 Table 4 厨师句超出本次引用块；D3-Q79 未明说跨语料词频归一化；D1-N07 的精确论证替换约定仍未取得；D3-Q50 仍保留“English 不是 Indian language”的附加评论。它们不改变本轮核心通过，但不能写成完全解决。
- **E 的因果边界：** 修复范围只有 `_table_caption`。11 道改善中只有 Q100 直接对应表题修复；Q37／Q44／Q57／Q66／Q69 等改善来自各自的搜索／阅读／选择变化，不能归因于本次小修。3 道回退也不是表题修复造成。
- 本批是历史错题集合，16/21 通过只描述这批题的单次结果，不外推总体准确率、泛化或人工准确率；Q93／Q99 未运行，成绩未更新；没有自动修其他问题、加题、补跑或提交推送。

第 16 节保留为文末当前提示词。

## 16. 给 DeepSeek 的表题修复与历史错题复测提示词

复制下方内容给能访问本项目并执行本地命令的 DeepSeek 环境。执行 E 后直接接续 F，不重做 A～D。

```text
执行 docs/v3/d5-plan.md 第13～15节 E/F：先修 Q100 暴露的通用表题提取问题，运行一个相关现有本地方法，再真实复测第14节固定21道历史错题各一次。排除 D3-Q93、D3-Q99 及其同题记录，完成后逐题评价并回写。不要修其他错题后重跑。

在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 D5 第13～16节及第9、11节记录，按实际相关代码处理。A～D 已完成，第10／12节为历史提示不执行。保留已有工作区修改，不重做备份，不自动提交推送。

E：检查 paper_assistant/evidence_reading.py 的 _table_caption。Q100 的原 parent22 文本确有 Table 3 表题，但首行含 p < 0.05，被 '<' not in first 整行排除，模型目录 caption 为空。继续使用现有表号前缀判断，优先移除这一过宽排除，让正常表题和 <、<= 比较条件完整保留；以 <table>/<tr> 开头的纯HTML仍不应成为表题。不扫描整表、不新增HTML解析框架，不删除比较符号或截断条件。不硬编码Q100/表号/正确数值，不改变源文本、解析、分块、parent/child、索引、图、引用或提示。自主提示版本保持 v3.2-native-tool-loop-reading-stop-v1；不修 section_path、邻域读取或其他无关问题。

在 scripts/check_d9_e_runtime.py 的现有 RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records 中，复用表格fixture，让表题包含 p < 0.05 和 n <= 100，验证实际模型消息收到完整caption，按parent读表与引用仍通；纯HTML非表题情况必要时加一个小断言，不新造测试组。只运行：
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
这是E改变路径后的必要重测，其余未变代码的结果复用。失败仅修本次直接原因并重跑受影响方法，具体跨模块证据才扩大；不跑模块/目录/全量，不扫描全仓语法/导入。本地方法真实服务请求为0。

F：E及上述方法完成后，按第14.1节固定名单顺序（Q100先，其余按表）各执行一次完整当前Agent问答，共21题、19个原版本。名单是历史总体/核心部分通过、未通过或未交付的原题去重，后来已通过的也保留回归；不扩普通通过题/新题，不运行93和99。逐行从S1～S10原input复制原问、官方ID/来源和selected_versions，不手工改写或换版本；D2-Q15与D3-Q15只一次。D1-N03/N05/N07的官方ID在source.question_id，其他自建题/追问可为空，混合来源不统一写dev验收。

D1-N10 必须从 archive/run_logs/d9/agent_20261026_075324_400898_2f0a17b6625f.json 的 conversation_history 复制原N09一轮历史，不把 conversation_history_used 数量当列表，不重跑N09，不加入N10旧答案或评价。历史只帮助理解，不作为自动核实的论文证据。其余20题空历史，全部新会话/提交ID/注册表，不共享本批前题结果。

复用 tmp/d5_d_partial_qa_run.py 窄入口方式，必要时只新增 tmp/d5_f_history_wrong_qa_run.py，适配多来源、N10历史、混合元数据和第14.3节最近基线，不执行旧main或造通用平台。每题调用当前 d9_runtime.run_question(question, pairs, mode='agent', library_mode=True, project_root=ROOT, conversation_history=该题规定历史, conversation_id=本题新ID, submission_id=本题新ID)。目录 artifacts/v3/d5-f-history-wrong-qa-20261102/，普通 input.json/results.json，task=D5-F，stage=d5-f-history-wrong-qa；ID前缀d5-f-history-wrong-qa-20261102-加小写完整题号。完整JSON/Markdown仍由runtime保存archive/run_logs/d9/。完成窄入口后运行：
.\.venv\Scripts\python.exe -X utf8 tmp/d5_f_history_wrong_qa_run.py

使用当前deepseek-flash、1048576上下文、temperature 0.2、4096输出、120模型轮次、普通默认300秒/综合90秒、现有每invoke网络重试和纠错/恢复、embedding/rerank/profile，记录实际配置。题间不改代码、提示、配置、版本、预算或评判口径。正常流程内聊天、查询embedding、重排及既有重试/纠错/必要收尾属于本批范围；不追加judge、fixed_rag、固定证据、MinerU、连通性、计费或额外验证模型请求。21次完整问答不是21个HTTP请求，全部实际用量如实记录。

业务输入只有原问、固定版本、规定的正常历史和运行参数，不注入旧该题答案、评价、参考、gold、预期来源/表号/数值/chunk或工具顺序，QASPER full_text不替代真实入库检索。本批实际按此执行：除 N10 的一轮 N09 历史外无旧答案或评价，无 gold／预期引用／表号／数值；模型自行选择搜索、阅读、JS 或停止。模型自行选择搜索/阅读/JS/停止，不强制读表或指定次数。请求前保存attempted；同批已尝试只整理原生日志，续跑仅接未尝试题。失败、缺引用、仍部分通过不补跑、不追问、不换题。原版本不可用记未执行不重入库，其他独立题继续；共享故障阻断则保留实际进度后停止，不反复探测。

按第14.3节最近基线事后逐题评价，分别说明运行、取证/停止、引用支持、内容，通过/部分/未通过/未执行，以及改善/保持/回退。Q100先核对模型实际目录恢复了表题，再看是否取得必要结果；不把目录通过当问答通过。Q29允许题意支持且声明清楚的比较口径，核对实际计算，不迎合隐藏参考；Q69检查归一化尺度及引用；N10检查通俗化与阶段归属。实际模型看到的证据与全文存在的事实分清。只用执行对话和既有原文/参考评价，不额外请求judge，用户未复核不称人工准确率。

在D5第15节记录E修改/本地方法新结果、21题逐题比较、实际配置/用量、原生日志与普通产物、未执行原因和残留；按本轮事实更新issues与总览，保留旧成绩和第16节文末提示。修复范围只有表题，不能声称其他题改善都由本次小修导致；本批历史错题比例不外推总体准确率。21题全部尝试且评价后才标F完成，未完如实记录。不要更新93/99成绩、不自动修其他问题、加题、补跑或提交推送，不新增哈希、审计、manifest、快照、保护层或独立验证报告。
```
