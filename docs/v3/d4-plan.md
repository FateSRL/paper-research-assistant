# D4：LangChain／LangGraph 迁移总览与实施计划

制定日期：2026-10-31；更新日期：2026-11-01（Asia/Shanghai）。

状态：**A／B／C／D／E 已完成并收尾（2026-11-01）。** C 的两处异常路径见第 13 节；D 的无效响应回填、入口／提示拆分及消费者小修见第 16 节；E 的提示清理、指定方法与十道旧题真实观察见第 19 节，收尾评价与内容问题移交见第 19.1 节。Q93／Q99／Q100 仍部分通过，继续在 [issues.md](issues.md)开放；当前架构与近期进展已同步 [总览](plan.md)。第 5／8／11／14／17／20 节为历史执行提示，不自动重跑。此次收尾只更新文档，没有新增代码修改、测试或服务请求。

## 1. 目标与迁移起点

本轮采用用户选择的三项组合：**LangChain 工具接口＋LangChain 模型接口＋`create_agent` 主循环**。`create_agent` 底层运行在 LangGraph 上；通过其状态和扩展接口承接项目规则，不另外平行实现一套自定义 StateGraph 主循环。

目标是减少项目自行维护的通用 Agent 编排代码，让工具、证据状态和运行入口的职责清楚。框架迁移不预设提高回答准确率或速度，也不顺带修复 D3 的具体语义错题。

迁移前版本已提交并推送到[原仓库](https://github.com/FateSRL/paper-research-assistant)及[迁移前备份仓库](https://github.com/FateSRL/paper-research-assistant-backup)。本地只配置原仓库 `origin`，备份通过地址直接推送，没有留下第二个远程。该备份是迁移起点，不表示后续迁移和文档改动已自动推送；不因阶段收尾重做备份、标签、冻结文件、哈希或提交推送。

### 1.1 当前有效行为

运行策略承接 [D3 第 33.8 节](d3-plan.md#338-实施与三题真实复测结果)，当前图与提示以实际代码及第 19 节 E 记录为准；D3 更早的五步、强制事实准备和小修复额度等说明属于历史。

- 页面自主问答入口为 `d9_runtime.run_question(..., mode="agent", library_mode=True)`；前置问题理解后进入原生工具循环。
- 当前工具为 `search`、`read_context`、`run_javascript`。模型自主选择继续取证或直接回答，自主路径没有必经 `prepare_answer` JSON，也没有正常答案的固定二次改写。
- 交互默认 120 个模型循环轮次，可配置正整数，没有独立五次取证限制；保留每次模型调用最多一次网络重试、普通请求默认 300 秒、异常综合 90 秒等现有策略。框架执行步数不能直接冒充模型轮数或工具次数。
- 业务模型为 `deepseek-flash`，上下文 1,048,576、temperature 0.2、输出上限 4,096；embedding、重排和索引 profile 沿现有配置。
- 每次问答共用一个 `EvidenceRegistry`，搜索、阅读、重排与最终正文沿用稳定 `ref`；编号可以不连续。只规范化显式带 `ID` 的格式，普通书目号 `[5]` 不转换。
- 实际原文、论文／解析版本范围、目录与候选位置的区别、容量裁剪后的可引用范围，以及当前结果与统计口径继续保留。

迁移起点的 D3 三题复测已正常交付，但 Q93 当轮核心来源错误、Q99 条件泛化、Q100 可达表未读。D4 E 最新三题均部分通过：Q93 本次未再无据否定现有语料，来源覆盖仍不足；Q99 条件与额外建议依据不足，Q100 可达表未取得。历史评价保留，当前状态见第 19.1 节与 [issues 1.12～1.14](issues.md)，不把迁移完成当作内容修复，也不把正确答案写入业务提示。

### 1.2 参考入口

| 来源 | 本阶段用途 |
|---|---|
| [D3 第 33 节](d3-plan.md#33-对齐-ragflow-的统一工具循环与宽松运行限制复测-q93q99q1002026-10-28) | 现行循环、恢复、限制与结果消费的依据；不重新执行旧提示词 |
| [agent.py](../../paper_assistant/agent.py)、[agent_graph.py](../../paper_assistant/agent_graph.py) | 公开入口、当前图组装／收尾与旧入口的职责划分 |
| [agent_state.py](../../paper_assistant/agent_state.py)、[agent_tools.py](../../paper_assistant/agent_tools.py) | 本题共享证据状态与实际 LangChain 工具 |
| [langchain_agent.py](../../paper_assistant/langchain_agent.py)、[langchain_model.py](../../paper_assistant/langchain_model.py)、[agent_current.py](../../paper_assistant/agent_current.py) | 实际图调度、现有模型客户端适配及当前提示／消息 |
| [agent_actions.py](../../paper_assistant/agent_actions.py) | 三个工具的名字、字段、参数解析和现有约束 |
| [prose.py](../../paper_assistant/prose.py)、[evidence_reading.py](../../paper_assistant/evidence_reading.py) | 现有证据注册表、原文读取和父子内容关系 |
| [LangChain Tools 官方文档](https://docs.langchain.com/oss/python/langchain/tools) | 标准工具封装、参数 schema 与运行上下文 |
| [LangChain Agents 官方文档](https://docs.langchain.com/oss/python/langchain/agents)、[LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview) | 后续主循环迁移及两者关系 |

## 2. 五部分迁移总览

五部分属于同一次连续迁移，不为每个组件建立平行业务模式或各跑一轮完整模型测试。

| 部分 | 工作内容 | 完成后的结果 | 当前状态 |
|---|---|---|---|
| **A：问答状态与工具** | 整理本轮证据状态，接入三个 LangChain 工具，并让当前自主循环实际使用 | 工具与状态从主控职责中分清；模型调用和循环调度仍沿当前实现 | **已完成**；第 4.1 节 JS 参数差异已在 B 收尾 |
| **B：模型接口** | 将现有 DeepSeek 调用适配为 LangChain 模型接口，接续超时、重试、用途和实际调用统计 | 为 `create_agent` 提供可用模型；避免框架与底层客户端各重试一遍 | **已完成**，见第 7 节 |
| **C：Agent 主循环** | 使用 `create_agent` 接管模型／工具循环，接入上下文、引用纠正、恢复与一次异常综合 | 现有自主取证和直接正文交付通过框架运行，运行策略按实际模型调用计数 | **已完成**；原两处问题在第 13 节修复，残留分支已在 D 收尾 |
| **D：入口与代码整理** | 先补无效响应的工具回填，再分清图入口、旧协议及页面／导出消费者，整理已迁移代码 | 残留分支处理完整；当前图路径和有效旧入口职责清楚，现有结果继续可消费 | **已完成**，见第 16 节 |
| **E：提示小修、必要验证与旧题观察** | 清理当前自主提示的一句旧引用字段指令，运行一个相关现有方法，复用其余有效验证；真实复测十道固定旧题 | 说明工程行为是否保持、引用是否交付及真实内容的变化；不宣称框架天然提高准确率 | **已完成并收尾**，见第 19／19.1 节；内容问题移交 issues |

MinerU 入库、SQLite、Qdrant、现有 embedding、BM25／RRF／重排、父子块、原文来源及引用解析继续复用。本轮不把它们整体替换为另一套 RAG 管道，不新增聊天持久化、独立判题模型、知识图谱或部署服务。

## 3. 第一部分 A：问答状态与三个工具接入

### 3.1 本部分目标与边界

将 `agent.py` 中自主路径的证据状态及搜索、阅读、计算执行职责整理出来，形成真正可调用的 LangChain 工具。当前原生工具循环要实际通过这些工具执行，不能只新增未接入的工具对象或示例脚本，也不能把整个 `answer_question_agent` 包成一个大工具冒充迁移完成。

本部分结束后，`d9_runtime` 仍使用当前 `RecordedLLM` 与手写自主循环。LangChain 模型适配属于 B，`create_agent` 替换循环属于 C；不提前接入、不设置新模式开关，也不要求用户手动选择新旧工具实现。

### 3.2 当前代码中的职责

当前 `answer_question_agent` 初始化本题注册表、来源范围和运行结果；内部 `run_autonomous` 还持有检索结果、查询去重、已知候选和显式阅读内容，再由 `merge_current` 组织实际可见原文。`execute_search`、`execute_read` 和 `execute_javascript` 分别完成实际工具工作；主循环负责派发并按 `tool_call_id` 回填观察。

本部分抽取这些实际职责，底层仍调用既有检索、阅读、JS 和来源处理能力。确实共用的底层函数继续共用，不把整个文件机械搬走，也不复制一套新旧执行实现。

### 3.3 一次问答的状态与依赖

使用简单的问答状态对象统一持有工具之间需要共享的业务状态，具体数据结构按现有代码选择，不建立通用状态框架。

| 内容 | 归属与生命周期 |
|---|---|
| 当前证据 context、同一份 `EvidenceRegistry`、已展示原文与候选位置 | 本次问答共享；注册表不随 context 深拷贝，也不按工具调用重新创建 |
| 检索结果、查询／召回去重、显式读取块、目标块和可读目录范围 | 由该问答的工具更新；只保留当前执行实际需要的数据 |
| 原始消息历史、当前轮次及循环控制 | 本部分继续由当前循环持有；需要交给工具的轮次由程序传入，不变成模型参数 |
| store、searcher、来源范围配置、现有记录／预算对象等运行依赖 | 沿用调用方的创建和关闭责任，通过必要的运行上下文传递；不放进模型可见参数，不做持久化序列化 |

后续 C 再接 LangGraph 的消息／状态接口。本部分不创建 checkpoint 数据库、会话恢复协议、状态迁移版本或全局缓存；不同问答不共享注册表和可见证据。

### 3.4 三个 LangChain 工具

使用官方 `@tool`／`StructuredTool`／`BaseTool` 的标准接口选择一种直接实现，工具名字和业务字段沿当前合同。工具对象按本次问答绑定状态与依赖；无需额外设计通用工具发现或插件注册系统。

| 工具 | 模型参数沿用 | 继续执行的业务 |
|---|---|---|
| `search` | `query`、`selected_versions`、`missing_information` | 原选定版本内检索、同查询去重、合并与原文展示，更新候选、稳定 ref 和现有检索用量 |
| `read_context` | `parent_id` 或 `chunk_id`；定向 chunk 阅读所需的 `missing_information` 沿原规则 | 只读取已知 chunk 或已展示目录中的父内容，保留范围资格、父子关系与新增原文观察 |
| `run_javascript` | `code` | 继续调用现有 JS 运行时，返回 stdout／执行错误并保留实际调用记录；计算输出不自动成为论文来源 |

保留当前工具描述和字段语义；程序依赖、注册表、循环轮次等不能成为要求模型填写的参数。复用现有 schema、Pydantic 约束与业务范围检查，避免另写一套重复的参数校验器。模型输入结构由一个明确入口处理，不机械叠加新旧两套解析。

三工具继续普通工具返回，不设置 `return_direct=True`，不让搜索或计算结果直接取代最终答案。工具错误仍形成当前模型可读观察，保留实际失败记录，已有原文不因工具失败清空。

### 3.5 接回当前自主路径

1. 当前入口在一次问答中创建状态和工具集合，并沿现有方式初始化阅读目录与原文 context。
2. `RecordedLLM` 仍返回原生 `tool_calls`。当前循环按原顺序调用相应 LangChain 工具，同一响应中的多个工具继续顺序执行，避免引入并发后改变证据编号分配和观察顺序。
3. 工具更新同一份问答状态，产生现有 observation。主循环继续记录 `parsed_action`、`tool_observation`、用途和实际次数，按真实 `tool_call_id` 回填消息。
4. 原文及 ref 仍由当前 `build_react_messages`／证据视图提供；完整诊断记录与模型可见返回沿原边界处理，不把全部 context、重复原文或内部依赖直接倾倒进工具消息。
5. 模型无工具正文、显式 ID 规范化、来源绑定、恢复与综合继续走当前路径。本部分不增加前置准备、不修改充分性策略或轮数／超时／重试策略。

允许为了这条实际调用链修改直接调用方；必要改动由依赖决定，不以文件数量或目标行数作为验收标准。当前提示词的整体清理和历史路径拆分留到后续，不在 A 中顺带大改。

### 3.6 预计文件安排与依赖

| 位置 | 本部分用途 |
|---|---|
| `paper_assistant/agent_state.py`（拟新增） | 本次问答证据状态及必要运行上下文；结构保持简单 |
| `paper_assistant/agent_tools.py`（拟新增） | 三工具的实际执行与 LangChain 封装，调用既有业务模块 |
| `paper_assistant/agent.py` | 创建共享状态／工具，接回实际自主路径，移走已抽取职责 |
| `paper_assistant/agent_actions.py` | 按实际需要复用或整理工具 schema／解析；旧入口仍使用的动作协议保留 |
| `requirements.txt` | 增加本次实际使用且与后续 `create_agent` 配套的 LangChain 依赖，固定兼容版本，不批量升级其他包 |
| `scripts/check_d9_e_runtime.py` | 仅在指定现有方法内适配调用边界与必要断言 |

文件名是预期职责分配，不是强制文件锁；已有模块能清楚承载同一职责时可以复用。安装依赖只用于实际工具接入和本地运行；不安装无用途的模型集成包、部署／追踪服务或整套示例环境。实际采用的包及版本写入第 4 节，不预填未经采用的版本。

### 3.7 必要本地验证

**本轮写规划不运行测试。未来执行 A 时，默认只同步并运行一个现有方法：**

`scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`

该方法已有真实业务入口＋本地 mock 的搜索／阅读／JS、工具失败后继续、稳定引用／非连续编号、容量范围、调用记录及资源关闭场景。复用这些场景，必要时加入少量断言，确认实际入口确实通过新 LangChain 工具执行，且本轮共享状态与结果合同保持；不再复制一组适配器场景或测试框架内部实现。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

方法失败则修复后只重跑受影响方法；仅有具体跨模块影响证据时才扩大到直接相关方法。LLM、页面及其他对应代码未变的通过结果复用，不因为文件抽取重跑。禁止按模块／目录／全量运行，不额外做全仓语法／导入扫描、历史输出重放、注册表遍历、压力实验或独立检查器。

A 不运行 QASPER 真实问答，也不发聊天、embedding、重排、入库、judge、计费或连通性请求。真实旧题观察留在 E 的后续具体安排，不提前使用 Q93／Q99／Q100 做探测或调提示。

### 3.8 完成口径

当当前自主入口实际通过三个 LangChain 工具工作、状态与稳定 ref 在本题内共用、现有记录／结果合同保持，且第 3.7 节必要方法通过时，A 完成。

交付说明应明确：**工具与业务状态已接入，模型接口和主循环仍未迁移。** 不能把导入了依赖、创建了未使用工具，或测试只调用独立示例，写成完整 LangChain／LangGraph 迁移完成。不会因 A 的本地方法通过就宣称真实准确率改善。

不新增哈希、审计、manifest、快照、保护层、独立验证报告或通用管理框架。A 完成后只更新第 4 节并停止，不自动实施 B～E、不自动提交或推送仓库。

## 4. 第一部分实际实施记录

**状态：A 已完成工具与业务状态接入；B～E 未实施。**

**实际改动：**

- 新增 [agent_state.py](../../paper_assistant/agent_state.py)：`AgentEvidenceState` 持有本题 `context`、同一 `EvidenceRegistry`、搜索轮次/查询去重、已知候选、显式读取行、目标块、可读目录 parent、保存的完整子块及来源资格结果；`merge_current`、`execute_search`、`execute_read`、`execute_javascript` 从 `agent.py` 主函数移入该对象。工具执行更新同一状态，`store/searcher/预算/client` 仍由原调用方管理，不进入模型参数，也没有新增 checkpoint、持久化或通用状态框架。
- 新增 [agent_tools.py](../../paper_assistant/agent_tools.py)：用 LangChain 官方 `StructuredTool` 封装 `search`、`read_context`、`run_javascript`，直接复用现有工具名、描述、`SearchAction`／`ReadContextAction` schema 和 `run_javascript` 的 `code` 参数；工具共享受本题状态，不新增参数校验器或返回直通回答。
- [agent.py](../../paper_assistant/agent.py)：当前自主循环创建一次 `AgentEvidenceState` 和三个工具；同一响应内按原顺序调用 `tool.invoke(arguments)`，不再保留旧工具分派和执行闭包。`tool_call_id`、`parsed_action`、`tool_observation`、取证次数、`tool_history` 和结果合同继续沿用。工具异常形成可读观察，原文不因失败清空；每轮仍经 `RecordedLLM` 和当前循环，不引入并发。
- 最终阶段 `run_javascript` 也通过同一 LangChain 工具对象执行；`fit_agent_request` 接受实际传入的工具定义用于容量计算，旧 `native_search` 参数保留给历史调用。
- 结果新增 `tool_protocol="langchain-core-1.7.3"` 与 `tool_state_version="agent-evidence-state-v1"`，用于本次工程记录；模型、提示词、检索/阅读/计算策略和预算未改。
- [requirements.txt](../../requirements.txt) 增加 `langchain-core==1.7.3`。本轮未安装 `langchain` 模型集成、`langgraph`、部署或追踪服务；其正常传递依赖随 `langchain-core` 安装。B/C 接入 `create_agent` 时再按实际需要增加模型与图依赖。

**指定本地验证：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

**Ran 1 test in 25.871s，OK。** 复用原 mock 场景并增加：
- 实际调用 `build_agent_tools` 创建本题工具，自主入口确实经 `StructuredTool.invoke` 执行搜索/阅读/JS；
- 同一 `EvidenceRegistry` 下稳定且非连续的 `ref`、目录/父块范围、原文展示、工具错误观察、重复搜索、容量裁剪、结果保存及资源关闭保持；
- 结果记录 `tool_protocol`／`tool_state_version`，原有 `tool_call_id`、`parsed_action`、`tool_observation`、取证次数和旧 fixed_rag 路径继续可用。

全部为本地 mock；**真实聊天、embedding、重排、MinerU 入库和 QASPER 问答请求均为 0**，未做服务探测、judge、计费查询或旧题重放。

**已知限制：**A 只完成工具与本题业务状态。当前仍使用 `RecordedLLM`、前置问题理解和手写自主循环；未实现 LangChain 模型接口、`create_agent` 主循环、页面入口迁移或真实旧题观察。不能把本次本地方法通过写成完整 LangChain／LangGraph 迁移完成，也不据此声称回答准确率或稳定性提高。B～E 尚未开始。

### 4.1 本次结果评估与一处收尾（2026-10-31）

**A 的主体目标已达到，可以继续规划 B。** 实际自主入口创建 `AgentEvidenceState` 和工具集合，循环调用 `StructuredTool.invoke`；不是只有依赖或闲置示例。原文与注册表在本题内共享，工具执行已经移出原大函数，模型调用与调度仍沿当前路径，符合 A 的阶段边界。上面的指定方法结果为执行方记录的 `Ran 1 test in 25.871s，OK`；本次结合代码阅读复用该记录，没有重新运行或将其当作真实问答准确率。

发现一处正常计算以外的参数合同差异：[agent_state.py](../../paper_assistant/agent_state.py) 的 `invoke_javascript` 从输入取出 `code` 后重建 `{"code": code}`，会丢掉额外字段。当前工具采用字典 JSON schema，已安装的 `langchain-core` 对此类字典输入直接转交，后续仍依赖项目解析；例如带 `extra` 的输入会在进入原 `RunJavaScriptAction` 前失去该字段，而原解析使用 `extra="forbid"`，应返回参数错误。

这是小范围的参数转交回归，不影响合法 `code` 的正常计算，不需要推倒 A 或暂停 B 的规划。B 实施开头把原始参数整体交给既有 JS 解析，复用其错误处理，不新建字段白名单、参数校验器或全局规则；在 B 本来要运行的现有运行方法中补一个必要断言即可，不另开一轮 A 测试或真实模型实验。

本次没有发现需要改写检索／引用机制或扩大迁移范围的阻碍；没有运行测试或真实请求。A 的历史通过记录保留，参数差异在实际修正前不写成已修复。

后续 B 已按第 6.2 节修正该参数转交差异，并在第 6.7 节运行方法中验证；第 4 节其余 A 记录保留为历史。

## 5. 给 DeepSeek 的第一部分执行提示词（历史，A 主体已实施）

下方保留 A 的原执行提示词，不再次执行。下一部分使用文末第 8 节。

```text
实施 docs/v3/d4-plan.md 第一部分 A：整理一次问答的证据状态，将 search、read_context、run_javascript 接为实际使用的 LangChain 工具；完成指定的一个现有本地测试方法并回写结果，不增加多余校验、哈希或真实模型请求。

在 D:/course/paper-research-assistant 工作，读取 AGENTS.md、docs/v3/d4-plan.md 第 1～4 节，以及 docs/v3/d3-plan.md 第 33.8 节。遵守 AGENTS.md 的用户四问，只完成 A 的实际调用链，复用现有能力，不扩展无关工作；D3 旧提示只作历史，不执行任何旧批次。保留已有修改，不重做备份、不改远程配置、不自动提交或推送。

总路线是 LangChain 工具＋模型接口＋create_agent，后者底层运行于 LangGraph。本次只做 A，不提前适配模型或替换主循环。当前 RecordedLLM、前置问题理解及手写自主循环继续使用；不要新增业务模式开关，不要把整个 answer_question_agent 包成一个工具，也不要只增加未接入的示例工具。

按第 3.2～3.6 节，结合实际代码抽出本题证据状态及三个工具执行职责，预期用 agent_state.py、agent_tools.py 承载，并接回 agent.py。一次问答共用同一个 EvidenceRegistry、已知候选和原文状态；注册表不随 context 深拷贝或按工具重新创建。不同问答隔离；store/searcher/现有记录与预算等依赖由原调用方管理，不放进模型参数，不新增 checkpoint、数据库、状态持久化或通用状态框架。确实共用的底层函数直接共用，不复制两套实现，不机械搬整个大函数。

使用 LangChain 官方标准工具接口，复用现有名字、描述、schema 与业务参数。search 保持 query/selected_versions/missing_information；read_context 保持已知 chunk 或已展示目录 parent 及原 missing_information 规则；run_javascript 只接受 code，继续用当前 JS 运行时。保留原范围检查和实际错误观察，不另建重复校验器，不暴露内部依赖、当前轮次或注册表为模型必填字段。工具不直接结束回答，不增加新工具或改变检索、阅读和计算策略。

当前自主循环必须实际调用新工具集合，按原顺序执行同轮多个调用，不引入并发。工具共享状态并沿用原 ref，观察和 parsed_action/tool_observation/tool_call_id、实际调用次数与用量继续归本题；模型可见消息与内部诊断沿原边界组织，原文/ref 继续通过现有证据视图提供。避免只加装饰器却保留原主函数内全部状态和执行职责。必要直接调用方可随真实依赖调整；其余历史路径和固定 RAG 仍保持可用，不大改页面和提示词。

沿用当前 deepseek-flash、上下文与输出配置、默认120轮、普通300秒／综合90秒、每次invoke最多一次网络重试及既有纠错／恢复／收尾策略。本次不改模型、凭据、embedding、rerank、索引或入库，不恢复 prepare_answer 强制JSON、固定二次改写或普通[n]自动转换。原文可见范围、论文版本和非连续ref映射继续有效。只添加本次实际需要且与后续 create_agent 配套的 LangChain 依赖，固定兼容版本，不批量升级其他包或安装部署／追踪服务。

按第 3.7 节默认仅同步并运行 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records。复用原本地mock场景，只作接入所需调整和必要断言，确认实际工具执行、共享证据/编号、错误观察及记录/结果合同；不要另建同构测试、独立适配器演示或新验证器。失败修复后仅重跑受影响方法；只有具体跨模块影响才扩大，不跑整模块、目录、全量、全仓语法/导入扫描或旧输出重放。LLM/页面等对应代码未变的通过结果直接复用。

本次真实聊天、embedding、rerank、MinerU入库和QASPER问答请求均为0；不做服务探测、judge、计费查询、gold注入或指定错题补跑。不要新增或手工计算哈希，也不新增审计、manifest、快照、保护层、独立报告和无关重构。

完成后在 d4-plan.md 第 4 节简要写实际改动/依赖版本、指定方法结果、实际调用为0及已知问题，更新 A 的实际状态，保留第 5 节为文末提示词。明确 A 只完成工具与业务状态，B～E尚未实施，不声称已完成整个框架迁移或提高问答准确率。若阻断，说明具体原因和已完成部分。A完成即停止，不自动继续后续部分或提交推送。
```

## 6. 第二部分 B：LangChain 模型接口与现有调用记录衔接

状态：**B 已实施**；第 4.1 节参数转交差异已修正，模型接口已接回当前自主循环，`create_agent` 主循环仍待 C。实际记录见第 7 节。

### 6.1 目标与技术选择

提供一个符合 LangChain `BaseChatModel` 合同的同步聊天模型适配器，实际用于当前自主循环，为 C 的 `create_agent` 提供模型。选择复用当前 `langchain-core==1.7.3` 和 `RecordedLLM`，不另换 `ChatDeepSeek`／`ChatOpenAI` 客户端或复制一套网络层。

现有 `RecordedLLM.invoke` 已负责真实请求、用途、网络重试、超时、脱敏响应、attempts 和累计统计。新模型只负责消息／工具／响应接口转换，并委托同一个已有客户端完成一次逻辑调用；前置问题理解仍沿原客户端，与后续模型适配器共用本题预算和账本。

依据为 [LangChain Models](https://docs.langchain.com/oss/python/langchain/models)、[Messages](https://docs.langchain.com/oss/python/langchain/messages)，以及当前已安装 `langchain-core` 的 `BaseChatModel`、`AIMessage` 和工具转换实现。使用项目已安装版本的实际接口，不照搬其他版本示例或提前升级整套依赖。

### 6.2 开始实施前的单点收尾

修正 `AgentEvidenceState.invoke_javascript`：将原参数字典整体传给已有 JS 参数解析，保留它对额外字段和非法 `code` 的原有处理，不先过滤为只有 `code` 的字典。合法调用继续沿原 JS 运行时与记录逻辑。

这是恢复迁移前已有合同，不新增校验层。只在第 6.7 节的运行方法中复用现有工具场景补必要断言，不先单独再跑 A 方法，也不扩展为字段组合或安全审计测试。

### 6.3 模型适配器职责

建议新增 `paper_assistant/langchain_model.py`，以轻量的 `RecordedChatModel` 承载；已有模块更适合时可按实际职责调整，不设文件数量或代码行数目标。

1. **标准模型接口。** 基于现有 `BaseChatModel` 实现同步生成所需的 `_generate`、模型类型标识和 `bind_tools`。使用框架的标准 `invoke` 返回 `AIMessage`；不能只定义一个同名 `invoke`、继续返回旧字典，伪装成可供 `create_agent` 使用的模型。
2. **复用原客户端。** 适配器持有调用方已有的 `RecordedLLM` 引用，不再打开 HTTP 客户端、不另读凭据、不拥有资源关闭责任。模型标识可以记录，客户端、预算和凭据不进入模型可序列化配置或业务消息。
3. **消息转换。** 支持当前实际使用的 system/user/assistant/tool 与对应 LangChain 消息，保留原文文本、消息顺序、工具名及 `tool_call_id`。输入仍是当前消息内容，不增加 system 指令、摘要、事实准备或新的回答要求。
4. **工具绑定。** `bind_tools` 接受 A 的工具对象或现有工具定义，使用当前工具转换能力得到请求 schema，传递实际 `tool_choice`。绑定本身不调用模型。容量拟合使用的定义与实际请求工具一致；异常综合使用不带工具的同一模型，不能残留普通轮次绑定的工具。
5. **响应转换。** 用 `ChatResult`／`ChatGeneration`／`AIMessage` 承载正文、工具调用和元数据。保留原始工具 `id/name/arguments` 及无效调用信息；解析失败的参数不能悄悄消失，正文为空、截断等现有 `invalid_output` 也不能变成成功。
6. **旧循环所需返回值。** 当前循环仍消费响应字典。用一个小的桥接函数从本次 `AIMessage` 的记录元数据取回该次原始响应，继续供现有纠错、发布和日志使用；本次结果跟随对应消息，不依赖全局／共享的“最后响应”。不为此建立第二套结果协议或多份独立账本。

`AIMessage` 所需的空字符串表示与原响应的 `None`、标准化后的 tool_calls 与原始 arguments 等差异，要通过该次记录保留真实状态，不凭转换后的非空／结构化外观判定请求成功。原始响应与请求统计只转交，不为补齐字段额外发请求。

本部分只实现现有同步文本／工具调用所需接口，不新增流式、异步、模型路由、结构化答案输出、自动压缩、缓存或追踪服务；不启用 LangChain 的 `with_retry`、fallback 或模型缓存来改变真实调用次数。

### 6.4 超时、重试与统计只有一个执行责任方

| 项目 | 本部分要求 |
|---|---|
| 请求发送与网络重试 | 仍由同一 `RecordedLLM.invoke` 处理；一次 LangChain 模型调用对应一次既有逻辑 invoke，网络失败最多按现有策略重试一次 |
| SDK 隐式重试 | 保持当前关闭状态；适配器／Runnable 不再叠加重试 |
| 用途 | 普通回答、纠错和异常综合分别保留实际 `purpose`，不把 repair/synthesis 改记为 answer |
| 超时 | 普通调用沿实际配置默认 300 秒，综合通过单次参数使用 90 秒；绑定工具或消息转换不丢掉超时参数 |
| 本题账本 | 前置理解、正常循环、纠错和综合共享原 `ChatBudget`；不重复 reserve、不重置 records，不把一次请求计两次 |
| 返回用量 | 已有 attempts、HTTP 次数、usage、finish_reason、耗时和累计统计继续可消费；缺失仍为未知，不补零、不追加查询 |
| 错误 | 原 `LLMCallError` 的状态、代码和尝试记录继续传给当前处理路径，鉴权／配置错误不伪装成功或自动更换模型 |

LangChain 标准 usage 字段可从本次已知数据映射，但其缺省值不能覆盖项目账本的未知状态；项目统计继续以真实已有请求记录为依据。

### 6.5 接回当前实际调用链

1. 一次问答沿现有入口创建 `RecordedLLM` 和共享预算；前置问题理解照常执行。自主路径创建一次引用该客户端的模型适配器。
2. 当前循环继续构建并拟合消息。普通轮次通过绑定 A 三工具的 LangChain 模型调用，纠错沿同一模型接口；消息返回后取回对应原始响应，当前循环继续派发 A 的工具。
3. 一次无工具综合通过同一适配器的不带工具入口调用，保留 90 秒和实际用途；复用已有有效正文时仍为零新增请求。
4. `result.action_steps`、SDK 尝试关联、稳定 ref、引用处理及结果保存继续沿原消费者。记录实际使用的模型接口，不把手写循环提前标成 `create_agent` 或 LangGraph 图循环。
5. 前置问题理解、fixed_rag、固定证据和历史调用者继续使用其现有客户端接口；只有实际共享改动所必需的调用方适配才纳入。B 不全局替换所有 `.invoke`，不改页面布局或旧记录格式。

当前 120 轮策略、原生工具顺序执行、直接正文、来源范围、容量拟合及恢复规则不变。实现接口时遇到目前并未使用的模型能力，不提前补成通用适配框架。

### 6.6 预计涉及位置

| 位置 | 工作 |
|---|---|
| `paper_assistant/langchain_model.py`（拟新增） | 标准聊天模型、工具绑定、消息转换和该次原始响应桥接 |
| `paper_assistant/agent.py` | 当前自主循环及其纠错／综合实际经新模型接口调用，仍保留当前调度 |
| `paper_assistant/agent_state.py` | 仅收尾第 4.1 节 JS 原参数转交，不扩大工具改造 |
| `paper_assistant/llm_client.py`、`d9_runtime.py` | 原则上复用；若共享客户端／调用关联确需小调整，只改直接依赖，不另建网络层 |
| `scripts/check_llm.py`、`scripts/check_d9_e_runtime.py` | 只在第 6.7 节两个现有方法内调整必要场景和断言 |

现有 `langchain-core` 已含所需基础接口，默认不增加模型集成包或 `langgraph`。后续 C 需要 `langchain/create_agent` 时再处理实际依赖，不在 B 安装部署或追踪组件。

### 6.7 仅两个现有本地方法

未来 B 实施完成后，默认只同步并运行：

1. `scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts`：复用原可重试 HTTP、同预算两个 invoke、300／90 秒、连续失败及 401 场景，让关键调用实际经过模型适配器，确认每次最多一次重试、用途和用量没有在框架层丢失或重复。保留原断言，不另外再建一组相同网络样本。
2. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：复用现有工具→正文、工具消息、纠错与综合、本轮引用、空／截断／错误响应和资源生命周期场景，确认模型适配器真实用于当前入口、A 工具仍实际执行、响应和调用记录保持。第 6.2 节单点收尾的断言并入该方法，避免再跑一遍 A。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

本次仅写 B 计划，不执行上述命令。未来失败修复后只重跑受影响方法；只有具体跨模块影响时才扩大到相关现有方法。页面、其他 LLM 方法及未受影响场景复用已有通过记录，不跑模块／目录／全量、独立消息重放、语法扫描或连通性探测。

B 的真实聊天、embedding、rerank、MinerU 和 QASPER 问答请求均为 0。没有真实旧题对比就不宣称速度或准确率提高，也不把本地 mock 当作新模型行为观察。

### 6.8 完成口径

当 JS 参数差异已按原合同收尾、当前自主模型调用实际经过标准 LangChain 模型接口、三个工具与该次消息／响应记录可衔接，且第 6.7 节两个必要方法通过，B 完成。

交付明确区分：**A 的工具／状态和 B 的模型接口已接入，主循环仍是手写实现，C 的 `create_agent` 尚未实施。** 不新增一次试用模型请求来“证明接入”，不创建哈希、审计、manifest、快照、保护层或独立验证报告。

B 完成后只回写第 7 节与状态，保留第 8 节为文末提示词并停止，不自动实施 C～E、运行真实旧题或提交推送。

## 7. 第二部分实际实施记录

**状态：B 已完成；A 的 JS 参数转交差异已收尾；C～E 未实施。**

**实际改动：**

- [agent_state.py](../../paper_assistant/agent_state.py) 的 `invoke_javascript` 现在把原参数字典整体序列化后交给既有 `RunJavaScriptAction` 解析，不再先取 `code` 再重建参数；额外字段、非法 `code` 和原错误处理保持，合法调用仍走原 JS 运行时与记录。指定运行方法新增 `extra` 字段被拒绝的断言。
- 新增 [langchain_model.py](../../paper_assistant/langchain_model.py)：`RecordedChatModel(BaseChatModel)` 持有调用方同一个 `RecordedLLM`，实现同步 `_generate`、`_llm_type`、`_identifying_params` 和 `bind_tools`；标准 `invoke`/`bind_tools(...).invoke` 返回 `AIMessage`，不另开 HTTP 客户端、不读取凭据、不复制重试。
- 消息转换保留当前 `system/user/assistant/tool` 文本、顺序、`tool_call_id`、工具名及原始 `arguments`；当前字典消息通过 `additional_kwargs` 原样回传给 `RecordedLLM`，不改变原文。`bind_tools` 用现有 `convert_to_openai_tool` 转换 A 的工具定义，绑定本身不发请求；无工具综合不残留工具。
- `AIMessage` 由 `ChatResult`/`ChatGeneration` 承载；原始 `status`、`output_issue`、`finish_reason`、`usage`、`attempts` 和工具调用通过该消息的 `additional_kwargs` 由 `recorded_response` 小桥接函数取回，不用全局“最后响应”。无效工具 arguments 不进入标准化 tool_calls 后丢弃，仍保留原始记录；空响应／截断状态不被改写为 success。
- [agent.py](../../paper_assistant/agent.py)：自主路径创建一次模型适配器；普通轮次经 `bind_tools(...).invoke`，纠错经同一模型接口并保留 `repair`，一次无工具综合使用同一适配器、`purpose=synthesis` 和 90 秒；最终正文的 `run_javascript` 也走同一模型与工具。`RecordedLLM` 仍是唯一请求／重试／账本责任方；前置理解、fixed_rag、固定证据和历史调用者继续原接口。
- 结果新增 `model_protocol="langchain-core-1.7.3/BaseChatModel"`、`model_adapter_version="recorded-chat-model-v1"`。依赖未新增包，沿用已安装 `langchain-core==1.7.3`；未安装 `langchain`／`langgraph`／部署或追踪服务。

**指定本地验证：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

**Ran 2 tests in 24.169s，OK。** `check_llm` 的 300／90 秒、两个共享预算 invoke、每次最多一次网络重试、连续失败、401、usage 与 attempts 均实际经过适配器；`check_d9_e_runtime` 的普通工具轮次、纠错、无工具综合、最终正文、JS 额外字段拒绝、A 工具执行、稳定 ref、容量、保存／下载和资源关闭保持。保留原断言；未新建适配器测试或真实请求。

**真实请求：聊天、embedding、rerank、MinerU 入库、QASPER 问答、judge、计费和连通性请求均为 0。** 本地 mock 只证明接口与记录行为，不代表真实问答质量。

**已知限制：**C 的 `create_agent` 主循环仍未实施；当前仍由手写循环调度 A 的工具和 B 的模型接口。`AIMessage.usage_metadata` 未额外派生，原始 usage/attempts 继续由桥接和 `RecordedLLM` 账本保留；B 只支持当前同步文本／工具调用，不支持流式、异步、自动重试包装、缓存或追踪。不声称完整 LangChain／LangGraph 迁移完成或回答准确率提高。

### 7.1 B 结果评估与 C 的衔接要求（2026-10-31）

**B 的阶段目标已达到，可以继续 C 的规划；未发现需要先返工的当前调用链问题。** `RecordedChatModel` 实际继承 `BaseChatModel`，没有把标准 `invoke` 改回旧字典；普通轮次绑定 A 工具，纠错与无工具综合实际经过适配器，网络与预算仍委托同一 `RecordedLLM`。JS 已转交完整原参数，原额外字段处理得到恢复。

两个指定方法的实施记录为 `Ran 2 tests in 24.169s，OK`，代码中关键调用已通过适配器执行；本次复用记录，没有重跑。真实服务请求为 0，能够说明接口与原记录衔接，不证明真实回答质量提高。

`usage_metadata` 未额外派生不影响当前项目账本，原始 usage／attempts 仍可取得，不需要为了字段齐全增加统计请求。当前 B 的消息保真主要依靠旧循环的字典桥接；C 将直接使用图中的 `AIMessage`／`ToolMessage`，因此要补足原生图消息的往返：包括原始工具 arguments、无效工具调用，以及 `status/output_issue` 对继续／结束的影响。这是 C 接管调度时的实际衔接工作，不把尚未使用的图路由当作 B 当前运行故障，也不能认为装好模型接口就已完成 C。

## 8. 给 DeepSeek 的第二部分执行提示词（历史，B 已实施）

下方保留 B 的原提示词，不再次执行；下一部分使用文末第 11 节，无需插件。

```text
实施 docs/v3/d4-plan.md 第二部分 B：先按第 4.1／6.2 节收尾 JS 原参数转交差异，再将现有 RecordedLLM 适配成 LangChain 标准聊天模型并接回当前自主循环；完成指定的两个现有本地方法和记录，不增加多余校验、哈希或真实服务请求。

在 D:/course/paper-research-assistant 工作，先读 AGENTS.md、d4-plan.md 第 1～4 节和第 6～7 节，必要时参考 d3-plan.md 第 33.8 节。A 主体已经实施，保留当前工作区修改，不重跑 A 原提示或 D3 旧批次。第 5 节是历史，当前只执行第 6 节 B；不重做备份、不改远程、不自动提交或推送。

先修 AgentEvidenceState.invoke_javascript：原始参数整体交给已有 JS 解析，避免先取 code 再丢掉额外字段。复用原 RunJavaScriptAction 和错误处理，不新增白名单／校验器、字段组合实验或独立 A 测试。该项与 B 一起在指定现有运行方法中验证，不修改其他工具策略。

依照已安装 langchain-core==1.7.3 的实际 BaseChatModel 接口实现轻量模型适配器，建议放 langchain_model.py。使用标准 invoke 返回 AIMessage，补足同步 _generate、模型类型标识和 bind_tools；不要只继承名字却重写成旧字典返回。持有同一个已有 RecordedLLM，所有真实请求仍委托其 invoke；不新开HTTP客户端、不另读凭据、不复制网络层或重试逻辑。框架消息和模型配置中不序列化客户端、预算和密钥。

转换当前实际使用的 system/user/assistant/tool 消息，保持原文、顺序、tool_call_id、工具名和原始arguments。bind_tools接收A的实际工具／定义，沿现有转换生成请求schema，绑定不发请求，容量拟合与实际工具一致。响应用ChatResult/ChatGeneration/AIMessage承载，保留当前原始响应及status/output_issue/finish_reason/usage/attempts等记录。无效工具参数不能被标准化后丢弃，空响应／截断等invalid_output不能伪装success；该次原始结果跟随对应消息，用一个小桥接函数供当前字典消费者取回，不依赖全局最后响应或另建账本。

当前自主普通轮次、纠错和一次无工具综合必须实际经过新模型接口，仍由现有手写循环调度A的三个工具。普通调用沿原工具绑定，综合用不带工具的同一适配器及90秒；已有正文恢复仍零请求。RecordedLLM负责唯一一次逻辑invoke和原每调用一次网络重试，SDK隐式重试仍关闭，不启用LangChain with_retry/fallback/缓存/自动压缩。保留purpose与300／90秒、共享ChatBudget、records及真实HTTP/usage/耗时；不重复reserve、清空预算、修复改记answer或把未知用量补零。

保持deepseek-flash及其上下文/输出/temperature、默认120轮和现有充分性／引用／恢复规则。前置问题理解继续原接口，与适配器共用原客户端和预算；fixed_rag、固定证据和历史调用者不全局替换。保留稳定ref、普通[n]不转换、实际原文与版本范围、A状态及工具顺序，不增加prepare_answer、固定二次生成、并发、流式、异步或新业务模式。B不接create_agent、不改页面、不安装无关模型集成／图／追踪服务，复用已有langchain-core；只有实际直接依赖需要时才小改llm_client或d9_runtime。

完成改动后，默认仅同步并运行 scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts 和 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records，按第6.7节复用本地mock，确认实际适配器调用、消息/工具回填、普通/综合超时、每调用网络重试、真实统计和已有引用结果保持。JS收尾断言并入运行方法，不额外再跑A。失败修复后只重跑受影响方法；只有具体跨模块影响才扩大，不跑模块／目录／全量、全仓语法／导入扫描、历史重放或独立测试框架。对应代码未变的已有通过结果复用。

真实聊天、embedding、rerank、MinerU、QASPER问答、judge、计费和连通性请求均为0。不新增或手工计算哈希，不新增审计、manifest、快照、保护层、独立报告或无关重构。不要用真实服务试调用或错误题补跑代替本地接口验证。

在d4-plan.md第7节记实际JS修正、模型接口与调用路径、依赖变化、两个方法结果、真实请求为0和已知问题，更新总览实际状态并保留第8节文末提示词。明确A/B接入程度，C的create_agent主循环仍未实施；不声称完整迁移或问答质量提高。阻断就说明具体原因和完成部分，不虚报测试。B完成即停止，不自动进入C～E、测试真实旧题、提交或推送。
```

## 9. 第三部分 C：由 create_agent 接管自主主循环

状态：**C 主体及第 12 节两处收尾已完成，实际修复见第 13 节。** 当前自主入口已调用 `create_agent` 图；最新发现的无效响应分支由第 15 节 D 第一项处理。第 10／10.1 节保留原实施与问题记录，E 尚未执行。

### 9.1 本部分目标与依赖

一次问答创建并调用一个 `create_agent`，让其实际承担模型与工具循环。当前自主路径不再用原 `for number in range(...)` 调度研究过程，也不能把整套旧循环包装成图中的一个节点，或每次只让框架执行一轮再由外层循环手动派发。

仅增加与现有 `langchain-core==1.7.3` 兼容的 `langchain` 及实际需要的 LangGraph 依赖，固定采用的版本；不预填未经采用的版本，不批量升级无关依赖，不安装部署、追踪或示例服务。若版本约束确需调整同一生态内的包，按直接依赖处理并记录原因，不借机更换业务模型或网络客户端。

依据为 [Agents](https://docs.langchain.com/oss/python/langchain/agents)、[Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)、[Runtime](https://docs.langchain.com/oss/python/langchain/runtime) 和所选版本的实际工具执行实现。`before_model`／`wrap_model_call`、`after_model`、`wrap_tool_call` 等只接入项目已有职责，不堆叠通用审核、限流或安全中间件。

### 9.2 图状态、业务状态与消息来源

- 图的 `messages` 成为当前内部对话的唯一正式历史。移走旧自主循环的独立 history，不同时维护两份需要反复猜测同步的消息列表。
- A 的 `AgentEvidenceState` 与同一 `EvidenceRegistry` 继续保留本题证据身份、可见原文和工具状态；通过本次运行上下文或本题工具绑定传递，不作为模型参数，也不深拷贝到图状态生成另一份注册表。
- 图状态只补充循环确实需要的轮次、待纠正错误、已提供原文标识及已接受正文等字段；不建立通用状态机框架、数据库 checkpoint、长期记忆或跨题缓存。
- 当前用户对话理解／检索建议仍由入口原前置调用产生，不新增前置阶段；旧用户回答不自动变成图中已核实论文证据。

### 9.3 原文进入正式消息，容量裁剪同步落地

在每次正常模型调用前复用现有证据视图、提示与容量拟合逻辑，按实际新增原文构建含 ref 的载荷，写入图的正式消息历史。下一轮必须仍能取得之前真正提供过的原文，不能只在一次临时 request 中注入原文、随后却把它标为已提供而从正式历史丢失。

保留当前按完整消息组／完整原文块裁剪的行为。裁剪结果同步到图中实际使用的消息和当前 `allowed_refs`，保持工具调用与 `ToolMessage` 配对，不把已移除正文的旧号继续当作可引用证据；不再加一个模型摘要或压缩调用。

每个模型轮次保存实际拟合后的请求与当次证据范围，交付引用依据该次真实请求和证据快照处理。图执行事件或最终 messages 的外观不能替代“该次实际看到了什么”。候选位置和目录仍只用于定位，普通 `[n]` 不转换。

### 9.4 模型响应与图路由

复用 B 的模型适配器，必要补足以下原生消息衔接，而非另建模型实现：

1. 框架产生的 `AIMessage`／`ToolMessage` 在下一轮转回原客户端时，保留正文、工具名、`tool_call_id` 和原始 arguments。有效工具调用可用于框架派发，无效 JSON 调用仍保留原记录并返回原有参数错误观察，不能从图中静默消失。
2. 在模型响应后的接入点读取对应 `recorded_response`，沿用现有 `status/output_issue`、正文规范化和引用处理。空答、截断、旧动作 JSON 或可修正显式引用错误继续在剩余轮次内反馈，不能因为 `message.tool_calls` 为空就被框架直接当作成功终态。
3. 合法工具调用交给框架工具执行；未知工具或参数错误产生现有可读观察与对应消息。每个真实调用 ID 仍有正确的工具返回关系，不伪造成功取证。
4. 只有通过现有正文／引用处理的最终回答才登记为本轮已接受正文并结束。该登记同时保存当次证据快照，后续结果交付消费它，不直接取“最后一条非空 assistant”。

使用所选版本支持的状态更新／中间件跳转完成继续、工具和结束路由。原错误纠正属于同一个图内循环，不在外层再次启动研究；不引入语义 judge、缺引用补引、按长度判短答或强制准备 JSON。

### 9.5 工具顺序、实际记录与资源线程

A 的三个工具继续由框架实际调用。每次工具前后只接入原观察、`parsed_action`、`tool_observation`、取证／JS 次数和用途记录，不再由主循环额外执行相同工具。正常 `search/read_context` 尝试与模型轮次、网络重试分开计数。

当前 A 的状态和注册表由同题多个工具更新；C 保持同一响应中工具按原始顺序执行。按所选版本实际设置图及工具内部的串行执行，必要时使用 `max_concurrency=1`，不能只限制图节点却保留内部工具并发，也不靠提示模型每次只发一个调用来替代实现。

图节点和工具可能在框架工作线程执行。当前 [storage.py](../../paper_assistant/storage.py) 的 SQLite 连接默认绑定创建线程；即便并发数为 1，也不代表仍在该线程。为图路径明确适配只读连接的跨线程串行使用及直接资源调用方，保留 SQLite 的 `mode=ro` 和资源关闭责任，不全局放开写连接的线程约束、不新增连接池或另一套存储。所需调整限于实际图调用链，图退出后原调用方仍正常关闭资源。

这属于当前框架接入的必要兼容，而非新增并发能力或审计保护层。直接相关的既有资源以实际调用行为为准适配；不得用吞掉线程错误、空结果或假成功维持表面通过。

### 9.6 模型轮数、网络预算与一次收尾

业务默认上限仍为 120 个模型循环轮次，可配置正整数；纠错占正常轮次，单次 invoke 的网络重试不另算模型轮次。同一轮多个工具不额外消耗多个模型轮次。前置理解与异常综合的统计继续沿原口径，不把图节点数、hook 次数或工具线程任务数混成问答轮数。

LangGraph 的递归／执行步上限需要容纳实际模型、工具和中间件节点，不能把业务 120 直接当作图的 `recursion_limit=120`，也不能让框架默认小上限提前终止正常可用额度。仍以业务模型轮次控制正常收尾，不新增整题 tokens／时长配额；本地用较小显式轮数覆盖上限，不为证明默认值真的运行 120 轮。

保留现有异常处理：优先复用本轮已接受正文，零新增模型请求；没有可复用正文时，用当前真实原文、ref 和已完成计算做一次无工具综合，单次 90 秒，仍经 B 的同一模型／账本。图外可以保留这一处异常收口，但不能在外层重新循环、重置预算或反复调用 `create_agent` 重启研究。

鉴权、配置和原本不可重试的终止错误继续如实失败，不借图的 retry policy 再试；正常已完成答案不固定再综合，综合失败不再启动第二套收尾。只保留现有每 invoke 最多一次网络重试，业务模型、普通 300 秒、用途和累计记录不变。

### 9.7 入口、消费者与代码组织

建议新增 `paper_assistant/langchain_agent.py` 承载图创建及必要接入点，`agent.py` 的当前自主分支调用该实现，复用已有业务模块。名称与拆分可按真实职责调整，不把原大文件整体搬进新文件，也不维护两套自主循环供页面切换。

本部分必须沿现有问答入口实际运行图，并继续提供 `action_steps`、消息／响应记录、取证与模型轮次、引用／来源及终态字段，正常正文与导出结果保持同源。标明实际 `create_agent`／依赖／循环版本，不把新增字段当作接入已完成的唯一证据。

D 留给入口与历史提示的进一步整理，但 C 不能因此留下当前入口未接入或结果消费已断裂的问题。必要消费者小调整随实际影响完成，仍使用的 fixed_rag、固定证据与历史调用者保持原入口；不改页面布局、聊天持久化、检索／入库或题目策略。

### 9.8 预计文件与必要本地方法

| 位置 | C 的职责 |
|---|---|
| `paper_assistant/langchain_agent.py`（拟新增）、`agent.py` | 实际图创建、消息与路由接入、当前自主分支替换及单次异常收口 |
| `agent_state.py`、`agent_tools.py` | 复用 A，按图调用需要衔接状态、观察与顺序执行 |
| `langchain_model.py` | 图原生消息的保真往返、无效调用与原响应状态衔接，继续委托原客户端 |
| `storage.py`、直接资源打开调用方 | 必要的图路径只读跨线程兼容与原生命周期 |
| `requirements.txt` | 固定实际兼容的框架依赖，其他包不批量升级 |
| 现有运行／LLM 测试方法 | 复用原本地场景覆盖实际图、消息、预算和来源交付 |

未来实施 C 后默认只同步并运行两个现有方法：

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`：真实执行 `create_agent` 图与 A/B 接口，保留原工具→正文、多工具顺序、错误纠正、稳定／非连续 ref、原文保留与容量裁剪、超过五轮、较小上限收尾、恢复／一次综合、保存与资源关闭场景；确认已替换当前手写调度，不能 mock 成旧循环而绕过图运行。
2. `scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts`：因 C 必须衔接原生图消息，复用 B 场景及必要消息断言，确认普通与工具消息往返、无效 arguments 不丢失、300／90 秒、每 invoke 一次重试、用途及原 attempts／usage 保持。底层请求仍全部 mock，不重复搭建一组相同 HTTP 样本。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts
```

**仅当页面／导出消费者代码或其消费合同实际变化时**，再运行 `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`；未变则复用已有记录，不为凑数跑第三项。失败修复后只重跑对应方法，只有具体跨模块影响证据才扩大，不跑模块／目录／全量、语法扫描、旧结果重放、压力实验或独立验证器。

C 实施后已运行上述两个方法；真实聊天、embedding、rerank、MinerU、QASPER、judge、计费与连通性请求均为 0，真实旧题观察留到 E。框架实际图的离线方法通过仍不能替代真实回答效果。

### 9.9 完成口径

当前自主问答真实由 `create_agent` 图调度 A 工具和 B 模型，原手写自主研究循环已被替换，正式消息原文／稳定 ref、错误继续、模型轮数、单次综合和原结果消费者保持，且必要方法通过，C 才完成。

只回写第 10 节与实际状态，保留第 11 节为文末提示词。未完成时说明具体缺口，不以仅创建图、外包旧循环或改版本标签宣称完成。不生成哈希、审计、manifest、快照、保护层或独立报告，不自动开始 D／E、真实旧题、提交或推送。

## 10. 第三部分实际实施记录

**状态：C 已完成当前自主入口的图接入；D／E 未实施。**

**实际依赖：**沿用 `langchain-core==1.7.3`，新增并固定 `langchain==1.4.7`、`langgraph==1.2.19` 及正常传递依赖（`langgraph-checkpoint==4.3.1`、`langgraph-prebuilt==1.1.1`、`langgraph-sdk==0.4.11`）；未批量升级其他包，未安装部署／追踪服务。

**图与接入：**

- 新增 [langchain_agent.py](../../paper_assistant/langchain_agent.py)：`create_agent` 实际创建并运行图，`EvidenceMiddleware` 使用 `before_model`、`after_model`、`wrap_model_call`、`wrap_tool_call`。`d9_runtime` 的当前自主入口已经过 `agent.py` 调用该图；原 `for number in range(...)` 研究循环已移除，不是把旧循环包成一个节点，也不是外层逐轮调用图。
- 图 `messages` 是唯一正式内部历史。每轮 `before_model` 用现有 `build_react_messages` 生成含稳定 ref 的证据载荷，写入正式图消息；后续轮保留。每次模型前复用 `fit_agent_request` 按完整消息组／原文块裁剪，裁剪结果通过 `RemoveMessage(REMOVE_ALL_MESSAGES)` 写回图消息，并同步 `allowed_refs`／`allowed_citation_ids`；没有摘要／压缩模型。
- `after_model` 从对应 `AIMessage` 的 `recorded_response` 读取该次原始状态；空答、截断、旧 action JSON、工具参数错误和可修正引用错误在剩余模型轮次内继续，只有经原正文／引用处理的完整正文才登记 `accepted_text`／`accepted_context` 并结束。图外仅保留一次无工具 90 秒综合，复用 B 模型和同一账本；图内不重启研究、不重置预算。
- A 的三工具由框架工具节点实际执行；`wrap_tool_call` 仅接入原 `parsed_action`、`tool_observation`、`tool_call_id`、`evidence_calls_used`、JS 记录和错误纠正，没有第二次执行。`max_concurrency=1` 用于图及工具批次的串行；同响应多工具按框架原始顺序执行。无效工具 arguments 和未知工具仍形成现有可读观察。
- 模型轮次按 `before_model` 的实际调用计数，默认 120／可配置正整数；网络重试不另算模型轮次，同轮多工具不另算。图 `recursion_limit` 按业务轮次留足余量，没有直接把 120 当图步数上限。
- [storage.py](../../paper_assistant/storage.py) 增加仅只读的 `enable_thread_sharing()`：保留 `mode=ro`、原连接所有权和关闭责任，以 `check_same_thread=False` 加串行锁适配图工作线程；`d9_runtime` 仅自主图路径启用。写连接、连接池和全局线程约束未改。
- [d9_runtime.py](../../paper_assistant/d9_runtime.py) 的已验证正文清理恢复识别新 `loop_version`；结果继续提供 `action_steps`、真实消息／响应、模型轮次、取证／JS、引用／来源和终态。`fixed_rag`、固定证据和历史入口保持原用法。
- 结果版本为 `loop_version=graph_version="d4-create-agent-evidence-v1"`；A/B 的工具与模型字段保留。页面布局、导出合同和聊天持久化未改。

**指定本地验证：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts
```

**Ran 2 tests in 28.460s，OK。** 运行方法确认 `run_evidence_graph`、`RecordedChatModel._generate`、`build_agent_tools` 实际被调用；覆盖正式图消息原文保留、容量裁剪、同轮工具顺序、错误继续、稳定／非连续 ref、超过五轮、较小轮数一次综合、只读资源跨线程关闭、保存／下载和原 fixed_rag 场景。LLM 方法覆盖 300／90 秒、共享预算、每 invoke 一次网络重试、连续失败、401、消息／工具往返和 usage／attempts。未新增测试框架或真实请求。

**真实请求：聊天、embedding、rerank、MinerU 入库、QASPER 问答、judge、计费和连通性请求均为 0。** 本地图执行只证明接入与记录行为，不证明真实问答质量或稳定性提高。

**已知限制：**D 的入口／历史协议整理和 E 的真实旧题观察未实施；固定证据、fixed_rag 和部分历史消费者仍走原路径。图接入当前聚焦同步文本／工具调用，未增加流式、异步、checkpoint 持久化或自动摘要。不能把本次本地方法通过写成完整迁移完成；也不声称回答准确率提升。

### 10.1 C 结果评估：先收尾两处异常路径（2026-10-31）

C 的图接入主体成立，原实施方记录的两个本地方法通过结果保留；本次基于代码阅读发现两处遗漏，不将此前通过记录改写成覆盖了所有异常情况，也不重复运行原方法来制造新的通过结论。

1. **混合工具调用漏执行。** `EvidenceMiddleware.after_model` 在一条响应同时存在合法调用和不可解析参数调用时，只为非法项写入错误 `ToolMessage`，随后直接 `jump_to="model"`。同批合法调用尚未执行、没有对应返回；原始 assistant 消息仍保留这些调用，下一次模型请求会带未配对的工具历史，可能被接口拒绝。
2. **模型最终抛错时缺步骤记录。** `action_steps` 条目在 `after_model` 中创建；网络重试耗尽、鉴权等异常使 `handler` 抛出时，不会进入该 hook。外层虽记录 `interrupted_failure`，底层账本也保留实际请求／费用，但该轮缺少 action step 的请求、错误和 `sdk_attempt_numbers` 关联。

这两处是图派发和记录职责的遗漏，不需要增加模型审查、校验层或请求额度。D 的入口／代码整理暂缓，先完成第 12 节局部修复。当前仅报告并规划，没有修改业务代码、补跑测试或发起真实请求。

## 11. 给 DeepSeek 的第三部分执行提示词（历史，主体已实施）

下方保留 C 原迁移提示词，不重新执行；当前修复使用文末第 14 节，无需插件。

```text
实施 docs/v3/d4-plan.md 第三部分 C：使用 create_agent 实际替换当前自主模型／工具主循环，复用 A 的状态与工具、B 的模型接口，保留原文／ref、错误纠正、现有轮次和一次异常综合；完成指定本地方法与结果回写，不增加多余校验、哈希或真实服务请求。

在 D:/course/paper-research-assistant 工作，先读 AGENTS.md、d4-plan.md 第1～2、7～7.1、9～10节，以及实际 A/B 代码；必要时参考 d3-plan.md 第33.8节。A/B已实施，不再执行第5／8节历史提示或D3旧批次；保留当前工作区修改。只做C及实际直接调用方，不重做备份、不改远程、不自动提交推送或实施D/E。

按第9.1节引入并固定兼容当前core的langchain及实际LangGraph依赖，不批量升级其他包或安装部署／追踪服务。一次问答真正运行create_agent，由框架负责模型和工具循环；替换当前自主研究for循环，不能把旧循环整体包成一个图节点，不能在外层逐轮invoke图后手动派发工具，也不创建平行自主模式。

按第9.2～9.3节，以图messages为唯一正式内部历史，A的AgentEvidenceState和EvidenceRegistry仍每题一份，通过运行上下文或本题工具绑定传递，不深拷贝注册表或放入模型参数。每轮新增原文/ref必须进入正式图消息，后续确实保留；复用现有证据视图与容量拟合，裁剪同步落到实际图消息、allowed_refs和配对工具消息。不能只临时override一次request却把原文标记已提供后丢失；不增加摘要／压缩模型。保存当次真实拟合请求和证据范围。

按第9.4节补足B模型的原生图消息往返，保留原始工具name/id/arguments和对应ToolMessage。无效arguments及未知工具返回现有可读观察，不能从标准化工具列表中静默消失。after_model等实际接入点读取对应recorded_response，沿原status/output_issue、正文与引用处理路由：空答、截断、旧动作JSON、可修正引用错误在剩余轮次内继续，不因无标准tool_calls就自动成功。通过现有处理的完整正文连同证据快照登记后结束，不新增judge、缺引用审核、字数判定或prepare_answer关卡。

框架实际执行A的工具，工具前后接入原parsed_action/tool_observation/tool_call_id和次数，不再执行第二遍工具。按第9.5节让同批工具保持原始顺序，图及工具内部都实际串行，不能只提示模型一次调用一个工具。适配框架工作线程与当前SQLite连接创建线程的差异：即便max_concurrency=1也不等于同线程；只对图路径的只读连接做必要跨线程串行兼容，保留mode=ro、原资源所有权和关闭责任，不全局放开写连接、不新增连接池、不吞错误或伪造空成功。必要直接资源调用方随实际图运行修正，不扩展存储改造。

按第9.6节用实际模型循环轮次控制原默认120／可配置上限，纠错算轮次、invoke网络重试不另算，同轮多工具与模型次数分开。LangGraph节点步数／递归上限要容纳实际图，不能把120直接设成recursion_limit=120而提前耗尽。用小显式上限做原本地场景，不实际跑满120。保持deepseek-flash、原上下文/输出/temperature、普通300秒、现有每invoke一次网络重试、共享账本与真实purpose；不叠加框架retry/fallback/缓存或新增整题token／时长门槛。

保留已有正文恢复零请求；没有本轮已接受正文才做一次无工具90秒综合，基于本轮实际原文/ref和已完成计算，仍经B模型与同一账本。图外允许这一处异常收口，不允许重启研究图、循环综合或重置预算；鉴权／配置与原不可重试错误如实停止，正常答案不固定再改写，导出失败不再调模型。

当前d9_runtime自主入口必须实际接入图，保留原action_steps、实际消息/响应/SDK尝试、模型轮次、取证/JS、引用/来源及终态供页面和导出使用，更新实际循环／依赖版本。可新增langchain_agent.py承载图与必要接入点，复用原模块，不把整个agent.py搬过去。fixed_rag、固定证据和历史入口保持原用法；D的全面整理后续做，但C不能留下当前入口未接图或消费已断。普通[n]不转换、源版本/可见范围不变，不修改检索、入库、题意或充分性策略。

改动完成后，默认仅同步并运行 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records 和 scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts，按第9.8节复用原mock场景，实际执行图而非mock成旧循环；覆盖原文正式保留/裁剪、工具与消息顺序、错误继续、稳定ref、轮次/一次收尾、线程资源、网络重试及记录。只有页面/导出消费者代码或消费合同实际变化，才增加 scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；未变复用。失败修复只重跑受影响方法，仅具体跨模块证据才扩大，不跑模块/目录/全量、语法扫描、历史重放、压力或独立验证器。

本轮真实聊天、embedding、rerank、MinerU、QASPER问答、judge、计费与连通性请求均为0，不用真实服务试调用或错题补跑替代本地图接口验证。不新增或手工计算哈希，不增加审计、manifest、快照、保护层、独立报告和无关重构。

完成后在d4-plan.md第10节记实际框架版本、图接入/消息/工具/资源改动、轮次与收尾、必要方法结果、真实请求0和已知问题，更新实际状态，保留第11节为文末提示词。明确C的实际接入程度和D/E未实施；阻断如实说明，不虚报或宣称问答质量提高。C完成即停止，不自动继续D/E、运行真实旧题、提交或推送。
```

## 12. C 收尾：混合工具调用与模型失败步骤记录修复

日期：2026-10-31（Asia/Shanghai）。状态：**两处问题已修复，记录见第 13 节。** 只处理第 10.1 节两个已定位问题，不重做 A／B／C 的迁移，不推进 D／E。

### 12.1 依据与处理目标

| 问题 | 当前触发位置 | 修复后应达到的行为 |
|---|---|---|
| 一条响应中既有合法调用，又有 arguments 无法解析为参数对象的调用 | [langchain_agent.py](../../paper_assistant/langchain_agent.py) 的 `after_model` 混合分支 | 合法项仍实际执行，非法项取得既有参数错误观察；本批每个调用 ID 都有一次对应结果后，再进入下一轮模型 |
| 模型逻辑调用最终抛错，`after_model` 不执行 | 同文件 `wrap_model_call` 与 `after_model` 的记录分工 | 调用开始即有本轮 action step，成功或失败都补齐该条记录；原预算账本与请求次数保持 |

只恢复原有执行和记录合同。模型、提示词、检索／阅读／JS 规则、论文范围、稳定 ref、120 轮、300／90 秒及原网络重试／一次综合均不调整。

### 12.2 同批工具处理

一条模型响应视为一个工具批次，原始调用列表及其顺序、ID 和 arguments 继续保留。修正 `after_model` 的提前跳转，让框架执行尚未完成的合法调用；无法解析的项沿现有参数错误观察回填，不执行其业务工具。

处理要求：

- 合法调用继续通过 A 的实际工具执行，不因为同批另一项出错而跳过；已执行项也不因修复路由再执行一次。
- 每个非法项使用自己的原调用 ID 返回现有 `invalid_arguments` 观察。保留非法原始参数，不把它猜配成合法参数、不新增参数修复模型。
- 同批调用的结果沿原始调用顺序组织，全部回填后才继续模型；保持下一轮 assistant／tool 消息对应关系。可按已安装框架的路由或工具接入点实现，不限定某一条未经实际接口确认的跳转写法。
- 延续当前串行工具执行和同题证据注册表。合法工具产生的原文／ref 正常进入正式图历史，错误项不新增论文来源。
- 沿用本批 `tool_calls`、`parsed_action`、`tool_observation`、纠错与实际工具次数的记录，不把非法项记成成功取证。若现有统计将指定工具的参数错误算作一次尝试，按同一口径保留，不引入新的计数规则。

复用本批已有信息完成派发，不新增全局配对检查器、批次管理框架、重放队列或第四个业务工具。单项错误不会重开整题，也不会额外发一轮模型来代替当前尚未执行的合法调用。全合法／全非法及未知工具的现有语义继续保留。

### 12.3 模型调用步骤的建立与结束

将当前步骤条目的创建移到实际逻辑模型调用开始处，优先由 `wrap_model_call` 在调用 `handler` 前建立；`before_model` 继续准备拟合消息、证据范围和本轮用途。因轮数上限等原因根本没有调用模型时，不凭空创建请求步骤。

条目继续使用现有 `action_steps` 字段：`phase`、`purpose`、`repair_kind`、`autonomous_step`、实际消息、允许的 ref／chunk、`response`、`error` 和 `sdk_attempt_numbers`。`after_model` 在成功返回后更新同一条记录，不再追加一条重复步骤；工具结果也挂回该轮条目。

`handler` 抛出 `LLMCallError` 时，在现有异常出口记入原状态、代码和尝试信息，`response` 保持未成功取得响应的真实状态；在 `finally` 等统一出口把该次预算记录切片对应的 SDK 尝试编号写回。错误随后沿原路径抛出，原鉴权停止或一次无工具综合继续处理，不吞错、不伪造 `AIMessage` 成功，也不再发请求。

一次逻辑调用及其内部网络重试仍只占一个 action step；HTTP 尝试分别由原账本记录。原始费用和累计统计不重算、不补零，不重复 reserve、不重置预算。没有发起 HTTP 的本地调用失败按实际尝试记录为空说明，不伪造 SDK 编号或网络失败。

### 12.4 改动位置

默认集中修改 `paper_assistant/langchain_agent.py` 的混合派发与模型记录接入，以及第 12.5 节指定方法。只有实际框架路由必须衔接时，才小改 `langchain_model.py` 或直接调用方；不扩大到存储、页面、导出、依赖升级或历史协议清理。

保留实际图调度，不能为修混合调用恢复外层手写模型循环。既有版本字段若随实际修复更新，同步直接消费者和断言即可，不增加新的验证标记或记录体系。

### 12.5 默认只运行一个现有方法

修复后仅运行以下现有方法（本次已按此执行）：

`scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`

在该方法里复用当前本地 mock 和真实图入口：

| 场景 | 最少需要观察的结果 |
|---|---|
| 一条响应包含合法 search 和参数 JSON 损坏的另一个调用，随后模型正常回答 | 合法搜索实际执行一次、非法项不执行业务；下一次请求保留原始调用，每个 ID 只有一次对应工具结果，无缺配／重配；已取得原文与 ref 正常可用 |
| 原有连续两次 503 后进入一次综合的场景 | 不另造相同网络样本；失败的正常轮次也有 action step、原错误及两个尝试编号，综合独立记录，HTTP 数和累计费用口径不增加 |
| 原有 401 终止场景 | 不另发样本；失败条目含请求、错误与一次 SDK 尝试，没有额外网络重试、综合或伪造正文 |

保留现有全合法工具、单项错误、引用、容量、轮数和资源场景，不删除原断言换取通过。只补上述定位问题需要的场景／断言，不做参数排列组合、框架内部实现测试或另建验证器。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

底层 LLM／适配器和页面对应代码未变时，直接复用 C 的已通过记录，不再跑其方法。只有实际修改 `langchain_model.py` 的消息转换或工具绑定时，才增加已用过的 `scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts`；失败修复后只重跑受影响方法。只有具体跨模块影响才扩大，不跑模块／目录／全量、语法扫描、历史重放或压力实验。

全部为本地 mock，真实聊天、embedding、rerank、MinerU、QASPER、judge、计费和连通性请求均为 0；不通过真实模型制造错误，也不补跑 Q93／Q99／Q100。

### 12.6 完成口径

同批合法调用不漏执行、各调用结果只回填一次，且最终抛错的模型轮次具备完整既有步骤记录，原工具／HTTP 次数与预算口径保持，指定必要方法通过后，本次 C 收尾完成。

结果写入第 13 节，保留第 14 节为文末提示词；历史第 10 节通过记录保留，不覆盖成新成绩。未完成就说明实际缺口，不预填修复成功或语义效果。收尾完成后停止，D／E 仍待后续安排，不自动提交或推送。

不新增校验层、哈希、审计、manifest、快照、保护层、独立报告或无关重构。

## 13. C 两处问题实际修复记录

**状态：两处问题已修复；D／E 未实施。**

**实际改动：**

- 混合工具调用：模型适配器对无法解析为参数对象的调用保留原 name/id/原始 arguments，并以内部 sentinel 参数使其进入图的工具派发；[langchain_agent.py](../../paper_assistant/langchain_agent.py) 的 `wrap_tool_call` 在调用业务工具前识别 sentinel，按原 `tool_call_id` 返回既有 `invalid_arguments` 观察，不执行业务工具。`after_model` 移除了混合批次的提前 `jump_to="model"`，合法项仍由框架工具节点按原批次顺序执行；每个 ID 只执行／回填一次，原始 assistant 调用与 tool 结果保持配对。全合法、全非法、未知工具及原有计数口径保留。
- 模型失败步骤：action step 改由 `wrap_model_call` 在 `handler(request)` 前创建，复用 `before_model` 的拟合消息、allowed refs／chunk、轮次、purpose 和 repair 信息；`after_model` 只更新同一条，不再追加。`handler` 抛错时记录原 `status`／`code`／`attempts`，`response` 保持 `None`，`finally` 用本次 `budget.records` 切片写回 `sdk_attempt_numbers`；异常继续沿原路径传播，不吞错、不重调、不伪造成功响应。
- 仅为派发衔接小改 [langchain_model.py](../../paper_assistant/langchain_model.py) 的 `response_to_ai_message`，使坏参数调用可按原 ID 被图处理；网络、预算、超时、鉴权、提示词、轮次、来源范围和稳定 ref 未改。

**指定本地验证：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts
```

**Ran 2 tests in 29.587s，OK。** 运行方法在原 mock 中新增合法 `search`＋坏 JSON 同批场景，确认合法搜索实际执行一次、坏参数不执行业务、下一次请求保留两个原始调用 ID 且各只有一个工具结果，稳定 `ref` 正常；并断言 503 两次失败轮次有 action step、原错误与两次 SDK 尝试编号，401 失败轮次有一条步骤／一次尝试且无综合。工具 embedding 数、HTTP 次数、引用、容量、轮次和资源断言保持。LLM 方法因适配器消息转换实际改动而重跑，覆盖 300／90 秒、共享预算、每 invoke 一次重试、连续失败、401 和工具消息往返。

**真实请求：聊天、embedding、rerank、MinerU、QASPER、judge、计费和连通性请求均为 0。** 本地 mock 只证明派发、记录和边界行为，不证明真实回答质量。

**已知限制：**D／E 未实施；sentinel 仅用于本次图内坏参数派发，未成为模型可见参数或新业务协议。历史第 10 节通过记录未改写。

### 13.1 最新修正评价与转入 D 的小修（2026-10-31）

原两项修复有效：合法／坏参数混合批次不再提前跳回模型，内部错误标记只用于图内派发，原始 arguments 仍保留；失败模型轮次在调用前建步骤、异常与 finally 补齐错误及尝试关联。指定方法新增断言检查了原请求的调用 ID／工具结果对应，以及已有 503／401 的失败步骤。第 13 节记录为 `Ran 2 tests in 29.587s，OK`，本轮阅读复用记录，未重跑。

仍有一个相邻分支：`RecordedLLM` 会把 `finish_reason="length"` 等情况记为 `invalid_output`，同时保留已返回的工具调用。若其中 arguments 已能解析为对象，`after_model` 既不进入 `success + valid_calls`，也不进入 `raw_calls + not valid_calls`，随后追加纠正消息直接跳模型，原工具调用仍缺少返回。它与已修复的“成功响应里混有坏参数”触发条件不同。

用户决定将此项纳入 D，不再另开一次 C 收尾批次。D 开头对整条无效响应的工具调用补齐错误观察后再纠正，不执行被判无效输出中的业务调用；不新增校验层或调整额度。当前只是代码阅读结论，未以真实模型复现，尚未修复。

## 14. 给 DeepSeek 的 C 收尾修复提示词（历史，两项已修复）

下方保留原两项修复提示词，不再次执行；当前工作使用文末第 17 节 D 提示词，无需插件。

```text
实施 docs/v3/d4-plan.md 第12节 C 收尾，只修复两个已定位问题：混合合法／非法工具调用时合法项被跳过，以及模型最终抛错时缺少action_steps。复用现有图、工具和账本，完成指定必要本地方法并回写结果，不增加多余校验、哈希或真实服务请求。

在 D:/course/paper-research-assistant 工作，读取 AGENTS.md、d4-plan.md 第10～10.1、12～13节和相关实际代码。A/B及C主体已实施，保留当前工作区修改，不重新执行第5／8／11节历史提示或D3旧批次。只做本次C收尾，不推进D/E、不重做备份、不改远程、不自动提交或推送。

按第12.2节修EvidenceMiddleware.after_model的提前跳转。一条响应里有合法调用和arguments无法解析的调用时，合法项仍由框架实际执行，非法项以自己的原call_id返回既有invalid_arguments观察；保持同批原始顺序，全部回填后才进入下一轮模型。每个调用只执行／回填一次，原始name/id/arguments不丢失、不猜成合法参数，不留下未配对的assistant/tool历史。使用已安装版本实际支持的路由／工具接入点，复用A工具和同题ref，不恢复外层手写模型循环、不新增第四个工具、全局配对校验器、批次框架或重放队列。全合法、全非法、未知工具及原统计口径继续保留。

按第12.3节把action step建立放到实际逻辑模型调用开始，优先在wrap_model_call调用handler前建立。复用before_model已拟合请求、证据范围、轮次和实际用途；没有调用模型就不虚建步骤。after_model更新同一条而非再append，工具观察仍归本轮。handler抛LLMCallError时记原status/code/attempts并继续原异常路径，在finally等统一出口关联本次budget.records切片对应的sdk_attempt_numbers。失败条目response保持真实未取得响应状态，不伪造成功AIMessage、不吞错或重调模型。一个逻辑调用及内部网络重试只记一个step，原HTTP尝试、累计费用和预算不重算、不补零、不重复reserve。

默认只改langchain_agent.py及指定现有运行方法，只有实际路由衔接需要才小改模型适配器／直接调用方。保持deepseek-flash、提示词、120轮、300／90秒、每invoke最多一次原网络重试、原鉴权终止、已有正文恢复和一次无工具综合。来源范围、普通[n]不转换、稳定ref、工具串行、只读资源及结果合同不变，不改检索／入库／页面／依赖或整理历史协议。

修复后默认只同步并运行 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records。复用真实图入口与原本地mock，在原方法内增加一个合法search＋坏JSON调用的必要场景，确认合法项实际执行一次、非法项不执行业务，下一次真实mock请求中各原调用ID都有一次对应工具结果且ref正常。网络问题复用已有503两次后一次综合和401停止场景，只补失败步骤/错误/尝试关联断言，不再复制网络样本；保留原HTTP次数、费用、引用、容量、轮次和资源断言。

LLM／适配器与页面对应代码未变的通过结果复用。只有实际修改langchain_model.py消息转换或绑定时才增加原 scripts.check_llm.LLMChecks.test_retryable_http_error_retries_once_and_preserves_both_attempts。失败修复只重跑受影响方法，仅具体跨模块影响才扩大，不跑模块／目录／全量、语法扫描、历史重放、压力或独立验证器，不新建测试框架或参数排列组合。

本轮真实聊天、embedding、rerank、MinerU、QASPER、judge、计费和连通性请求均为0，不用真实模型造错误或补跑错题。不新增或手工计算哈希，不新增审计、manifest、快照、保护层、独立报告和无关重构。

完成后在d4-plan.md第13节简要记录两处实际修复、指定方法实际结果、工具／HTTP次数是否保持、真实请求0及已知问题，更新总览与C收尾状态，保留第14节为文末提示词，不覆盖第10节历史通过记录。阻断如实写完成部分和原因，不虚报修复或问答质量提高。完成本次收尾即停止，不自动进入D/E、运行真实旧题、提交或推送。
```

## 15. 第四部分 D：无效响应小修、入口与历史代码整理

日期：2026-10-31（Asia/Shanghai）。状态：**D 已完成，记录见第 16 节。** 先完成第 13.1 节小修，再整理已经迁移的入口、提示和消费者；不重做 C 的图接入，也不提前执行 E 的真实旧题观察。

### 15.1 本部分目标与当前依据

当前页面的 `d9_runtime.run_question(..., mode="agent", library_mode=True)` 已经调用图，A 工具、B 模型与 C 的执行机制继续复用。D 的目标是补齐已定位分支，让当前图路径容易识别，并分清仍在使用的旧动作／准备协议；不能把“入口整理”写成又建立一个新 Agent 模式。

当前 `agent.py` 仍同时承载图路径的组装与收尾、旧动作解析和历史分支；`agent_prompt.py` 同时包含当前原生工具提示与旧事实准备协议，当前 `AUTONOMOUS_SYSTEM_PROMPT` 还通过旧文本的 `split/replace` 组装。页面与导出已能消费通用 `loop_version`，按真实需要整理，不为框架名称增加新的操作选项或界面。

### 15.2 D1：先补整条无效响应中的工具回填

在 `EvidenceMiddleware.after_model` 中明确处理 `response.status != "success"` 且仍有原始工具调用的分支，位于正常工具派发／最终正文判定之前。以 `finish_reason="length"`、`output_issue="truncated"` 且工具 arguments 已完整可解析为必要案例。

1. 保留本轮原始响应、调用列表、ID、顺序和 arguments。整条响应已经无效，本分支不执行任何业务工具，不把可解析参数当作成功输出继续派发。
2. 为本轮每个原调用 ID 返回一次现有结构的错误观察，`error.code` 对应真实 `output_issue`（例如 `truncated`）；参数本来合法时，不误报 JSON 参数非法。原始响应记录仍为 `invalid_output`，不改写成工具成功。
3. 全部错误结果写入正式图消息，形成完整 assistant／tool 对应，再进入原纠正路由。额度已用尽时沿原上限收尾，消息及记录也保持完整；不新增模型调用、重试额度或第四个工具。
4. 这些调用未实际执行，不新增检索、阅读、JS、embedding 或论文来源；模型轮次及本轮失败记录沿既有口径。成功响应下已修复的混合批次仍正常执行合法项，不因本小修改变。

复用现有错误回填与记录代码，避免再复制一套大分支；不增加全局消息配对扫描、输出审核、参数猜配或工具回放机制。

### 15.3 D2：分清当前图入口与有效旧入口

保留 `d9_runtime.run_question` 与 `answer_question_agent` 等现有公开调用合同，页面当前入口继续直接走已接入的图路径。把当前自主路径组装／一次异常收口与旧动作分支分清，使当前入口不必穿过大量历史动作条件才能读懂。

可将当前图运行入口独立到职责明确的模块，或把旧动作执行部分移入 legacy 模块；选择能复用实际公共逻辑的直接方案，不同时做两种拆分。真正共用的消息拟合、引用发布和记录能力在已有合适模块复用，避免循环导入、整文件搬家或新建一个装下所有内容的 common 模块。

fixed_rag、固定证据与确有调用的历史入口继续保留原语义。只移走已被框架替代且当前不再执行的自主调度残余；不能因为名字含 prepare/facts 就删除仍服务其他入口的函数，也不为所有历史符号建立通用兼容路由。

本部分不更改公共默认模式、前置问题理解、论文选择、预算、检索与引用规则；不新增页面新旧框架开关，也不重新运行模型来比较两套入口。

### 15.4 D3：分开当前提示与旧准备协议

让当前图的普通提示、异常综合提示、稳定 ref 约定和 `build_react_messages` 具有明确归属。当前自主提示不再依靠查找旧 JSON 提示中的字符串边界来截取、替换后组装。

沿用当前实际生效的文本和输出合同，尽量原样提取；可以共享清楚的论文事实／来源规则，但把旧动作 JSON、facts、prepare_answer 等特有内容留在其实际使用的旧路径。仍被调用的旧构造函数可保留公开名称或必要导入转发，不制造无用途的新接口。

这是代码组织调整，不顺带改充分性、读表策略、答案风格或针对错题调提示。原有来源／上下文处理继续保留，不借拆文件删除其必要检查。只移动文件而提示文本未变时，不伪称新提示效果；只有实际行为变更才按既有版本字段如实记录。

### 15.5 D4：整理现有页面、导出与运行记录消费

检查直接相关的现有消费位置，必要时小改 `app.py`、`agent_export.py`、`d9_runtime.py`：

- 当前图记录继续展示实际模型轮数、工具、纠错、失败步骤及一次综合，不把图节点数当模型轮数，也不因没有旧准备阶段误判失败。
- `response=None` 的失败步骤按已有 error／SDK 尝试呈现；不显示成成功正文或丢掉前一轮有效答案。正常回答、恢复与综合均消费现有同一份答案和来源结构。
- JSON、Markdown、页面引用与下载继续使用相同的 `answer.text`、引用位置及来源映射。旧 claims／历史记录按既有结构继续可读，不要求迁移旧日志或重编号。
- 已能正确消费的代码直接复用；不为“统一框架”强制改所有页面函数，不新做图节点看板、运行报告、聊天持久化或界面布局。

把 D1 的功能修复与 D2～D4 的组织调整分清，保留能定位实际改动的说明，不用修改结果标签掩盖行为缺口。

### 15.6 预计涉及位置

| 位置 | 本部分工作 |
|---|---|
| `langchain_agent.py` | D1 无效响应带调用的错误回填；继续由现有图调度 |
| `agent.py` 及必要的当前／旧路径模块 | 当前公开入口、图组装与旧动作分支的职责整理 |
| `agent_prompt.py` 及必要的旧提示模块 | 独立当前提示与旧准备协议，直接调用方随实际导入调整 |
| `d9_runtime.py`、`app.py`、`agent_export.py` | 只做实际需要的入口／记录／页面／导出衔接 |
| `scripts/check_d9_e_runtime.py` | 必要 D1 场景及入口拆分后的现有断言／mock 位置 |

模块名字与文件数量按职责决定，不预设拆成多少个文件，不为代码行数目标搬运代码；不改存储线程适配、模型网络层、依赖版本或入库索引。必要直接调用方随真实依赖调整，不扩大为全仓格式化或命名重构。

### 15.7 必要验证与复用

D 实施后已运行以下方法：

`scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`

在该方法中补一个本地 mock：响应标为 `length/truncated`，同时带有参数完整的工具调用；确认该轮业务工具没有执行、实际模型请求及错误记录保持，下一次纠正请求中每个原调用 ID 都有一次错误结果且原 arguments 保留，随后可按正常循环继续。不要只断言最终 answered，而遗漏本轮工具是否误执行或消息是否完整。

复用原有正常图入口、已修复混合批次、503／401 失败记录、当前与旧路径、稳定／非连续 ref、容量裁剪、正文／来源和资源场景；按拆分后的真实调用位置调整现有 mock，不能把图执行 mock 成旧循环，不能删除有效旧路径断言换取通过。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

**仅当页面／导出消费者代码或消费合同实际修改时**，再同步运行 `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations`，覆盖正文／错误／引用与下载同源、旧记录消费；若不需要改消费者则复用通过记录。LLM／模型适配器未改，复用第 13 节结果，不因移动导入重跑网络方法。

失败修复后仅重跑受影响方法；只有具体跨模块影响证据才扩大，不跑模块／目录／全量、全仓语法／导入扫描、历史重放、提示词快照或压力实验。无需另建模拟框架、消息校验器或验证报告。

D 的真实聊天、embedding、rerank、MinerU、QASPER、judge、计费与连通性请求均为 0；不补跑旧题或发模型请求证明拆分有效。E 的题目、实际调用范围和评价安排留到后续，不提前开始。

### 15.8 完成口径与记录

D1 已补齐无效响应的工具错误结果，当前图入口与有效旧路径、当前提示与旧协议的归属清楚，页面／导出／记录继续消费同源结果，且实际相关方法通过时，D 完成。不要把“文件拆出来了”代替实际入口可用，也不要求消灭所有旧路径或把整个项目改成框架默认 RAG。

结果写入第 16 节，保留第 17 节为文末提示词；历史成绩不覆盖。未完成就写明具体问题，不预填修复／拆分成功，不声称问答准确率提升。完成 D 后停止，不自动执行 E、提交或推送。

不新增哈希、审计、manifest、快照、保护层、独立报告或无关重构。

## 16. 第四部分实际实施记录

**状态：D 已完成；E 未实施。**

**D1 无效响应回填：** [langchain_agent.py](../../paper_assistant/langchain_agent.py) 的 `after_model` 新增 `status != "success"` 且仍有原始 `tool_calls` 的分支。整条响应判为无效时不执行任何业务工具；按原始调用顺序为每个原 `call_id` 写入一次 `tool_error` 观察，`error.code` 使用真实 `output_issue`（`truncated`），保留原始 `response`、arguments 和失败步骤。全部错误结果进入正式图消息后再走原纠正／上限收尾；未增加工具、embedding、JS、论文来源或额度。

**D2 入口整理：** 新增 [agent_graph.py](../../paper_assistant/agent_graph.py)，承载当前图的组装、一次无工具综合和异常收口；`agent.py` 的自主分支只组装 `GraphRunContext` 并调用该入口。旧动作／准备分支继续留在 `agent.py`／`agent_prompt.py`，`fixed_rag`、固定证据和历史入口语义未改；`d9_runtime.run_question`、`answer_question_agent` 公开合同保持。

**D3 提示拆分：** 新增 [agent_current.py](../../paper_assistant/agent_current.py)，独立保存当前自主提示、一次综合提示、稳定 ref 规则和 `build_react_messages`；文本按现有生效值原样提取。当前自主提示不再从旧 JSON 提示文本 `split/replace` 组装。`agent_prompt.py` 保留旧动作／facts 提示，并通过导入转发当前名称，避免旧调用断裂；未改充分性、读表、答案风格或来源处理。

**D4 消费者：** [app.py](../../app.py) 增加图轮次中逐调用工具观察及失败步骤错误的展示；[agent_export.py](../../paper_assistant/agent_export.py) 的图步骤导出补充 `response`、`error`、`sdk_attempt_numbers`。正文、引用、来源、下载和旧 claims 记录继续同源；未改布局、聊天持久化或旧日志。

**指定方法：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

**最终运行：Ran 1 test in 29.927s，OK。** 原方法新增 `length/truncated` 且带完整工具参数的 mock 场景，确认该轮业务工具未执行、错误码为 `truncated`、下一请求保留原 arguments 且每个原调用 ID 有且仅有一个错误工具结果，随后正常纠正。原有正常图／混合批次、503／401、稳定 ref、容量、旧路径、结果保存和资源关闭断言保留。

因页面／导出消费者实际修改，另运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations
```

**Ran 1 test in 22.613s，OK。** 覆盖正文／引用／来源与下载同源、旧记录消费及页面终态显示。LLM／模型适配器未改，第 13 节通过结果复用。

**真实请求：聊天、embedding、rerank、MinerU、QASPER、judge、计费和连通性请求均为 0。**

**已知限制：** E 的真实旧题观察未执行；历史日志不迁移，旧 action／prepare 入口仍保留原协议；本次仅证明入口整理、D1 回填和本地消费行为，不声称问答质量提升。

## 17. 给 DeepSeek 的第四部分执行提示词

复制下方内容交给能访问本项目并运行本地命令的 DeepSeek 执行环境；无需插件。

```text
实施 docs/v3/d4-plan.md 第15节 D：先修复整条invalid_output响应带可解析工具调用时缺少工具回填的问题，再整理已迁移的当前图入口、旧动作／准备协议与必要页面／导出消费者。完成指定本地方法和记录，不增加多余校验、哈希或真实服务请求。

在 D:/course/paper-research-assistant 工作，读取 AGENTS.md、d4-plan.md 第1～2、13～13.1、15～16节及相关实际代码。A/B/C主体和原两处C修复已完成，不再执行第5／8／11／14节历史提示或D3旧批次；保留当前工作区修改。只做D，不重做备份、不改远程、不自动提交推送或执行E。

首先按第15.2节在after_model明确处理response.status非success且有原始tool_calls的分支。以finish_reason=length、output_issue=truncated、arguments已经完整可解析为必要案例；整条响应无效，该轮不执行业务工具。按每个原call_id及原顺序回填一次对应输出错误的ToolMessage/观察，保留raw response、原始arguments和失败步骤，全部回填后再走原纠正／上限收尾。错误码反映原output_issue，不把合法参数说成JSON非法，不把此轮记为成功取证，不增加工具／embedding／JS或论文来源。复用现有错误结构，不增配对扫描器、参数猜配、模型修复调用或新额度；原成功响应的混合批次保持修复后的正常行为。

再按第15.3节分清当前图入口与旧动作路径。现有页面入口已经用图，本次不重新迁移主循环或创建框架开关。保留d9_runtime.run_question和answer_question_agent等公开合同，可将当前图运行组装或旧动作部分抽到职责清楚的模块，选择一条直接方案；公共能力复用现有模块，避免循环导入、整文件搬家、两套自主循环或common大杂烩。fixed_rag、固定证据和确有调用的旧入口保留原语义，不因名字含prepare/facts就删掉；只处理真实调用关系需要的导入/转发，不建通用兼容框架。

按第15.4节独立当前图普通提示、一次综合提示、稳定ref规则和消息构造，当前自主提示不再依靠旧JSON提示的split/replace边界组装。尽量原样提取实际文本与协议，旧动作JSON/facts/prepare特有内容归其仍在用的旧路径；不借拆分调充分性、读表策略、答案风格或错题提示，不删除已有来源/上下文处理。仅移动文本不能冒充新提示效果或伪造版本。

按第15.5节只适配必要的d9_runtime/app/agent_export等消费者，已经正确的直接复用。当前图轮次、工具、纠错、失败步骤response=None及error/SDK尝试、恢复和一次综合正确呈现，正常正文/引用/来源在页面、JSON、Markdown、下载同源，历史claims记录继续可读；不迁移旧日志、不重新编号、不改布局或新增图看板／报告／聊天持久化。

保持deepseek-flash及原上下文/temperature/输出、120轮、300／90秒、每invoke一次网络重试、共享账本、图内串行、来源范围、普通[n]不转换和稳定ref。保留前置问题理解和正常直接正文；不改模型网络层、存储线程适配、依赖、入库索引或检索策略，不恢复prepare_answer关卡或固定二次生成。

改动完成后默认仅同步并运行 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records。原方法内补一个truncated响应带完整工具参数的本地mock，断言该轮工具未执行、错误记录真实、下轮每个原ID有一次输出错误结果且arguments保留，再正常纠正；复用原正常图/混合批次、503/401、稳定ref、裁剪、旧路径、结果与资源场景，不删原断言或mock成旧循环。按拆分后的真实位置调整必要mock，不另造测试框架。

只有页面/导出消费者代码或消费合同实际变动，才再运行 scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations；未变复用通过记录。LLM/模型适配器未改，复用第13节通过结果，不因移动导入重跑。失败修复只重跑受影响方法，只有具体跨模块影响才扩大，不跑模块/目录/全量、全仓语法/导入扫描、历史重放、提示快照、压力或独立验证器。

真实聊天、embedding、rerank、MinerU、QASPER问答、judge、计费和连通性请求均为0；E后续再安排，不补跑错题或发真实调用证明拆分有效。不新增或手工计算哈希，不增加审计、manifest、快照、保护层、独立报告和无关重构。

完成后在d4-plan.md第16节简要写D1实际修复、入口/提示/消费者拆分或复用、实际方法结果、真实请求0和已知问题，更新实际状态并保留第17节为文末提示词。历史第10／13节成绩保留，不虚报拆分、修复或准确率。阻断如实说明完成部分和原因。D完成即停止，不自动开始E、提交或推送。
```

## 18. 第五部分 E：清理引用提示残留，并真实观察十道旧题

日期：2026-10-31（Asia/Shanghai）。状态：**E 已完成，记录见第 19 节。** 本部分承接 A～D 的当前图入口，完成一处已定位的提示小修、一个相关现有方法与十道旧题各一次真实运行。第 17 节是已经结束的 D 提示词，后续执行使用第 20 节。

### 18.1 当前依据与本轮目标

D 的无效响应回填、图入口／提示拆分及页面／导出消费已完成，第 16 节记录运行时、页面两个方法通过。本次评价另发现 [agent_current.py](../../paper_assistant/agent_current.py) 的当前 `AUTONOMOUS_SYSTEM_PROMPT` 末尾仍含旧指令：

> Keep citations in citation_ids, not in claim text.

它沿用 [context.py](../../paper_assistant/context.py) 的旧答案组织规则，与当前“直接输出完整自然语言正文，在论文事实后写 `[ID:n]`”的合同矛盾。当前自主正文没有供模型填写的 `claims`／`citation_ids` JSON。本轮只清理这一句，不把框架迁移变成充分性、检索或错题专项优化。

E 同时观察：实际页面入口能否通过已接入的图完成问答、正文是否按当前约定交付引用、此前通过的题是否保持核心正确，以及 Q93／Q99／Q100 的已有内容缺口是否仍然存在。运行成功、引用交付和核心内容分别评价，不预填修复或准确率提升。

### 18.2 E1：只清理当前自主提示的旧引用指令

在 `agent_current.py` 的 `AUTONOMOUS_SYSTEM_PROMPT` 中删除上面这句旧指令，沿用该提示已经明确的“论文事实后使用 `[ID:n]`”要求，不再叠加一段重复规则。当前自主提示版本由 `v3.0-native-tool-loop-v1` 更新为 `v3.1-native-tool-loop-prose-citation-v1`，让现有运行记录反映本次文本变更；通过既有导入转发读取同一版本，不另造版本映射。

`PROSE_FINAL_SYSTEM_PROMPT`、`PROSE_FINAL_PROMPT_VERSION`、稳定 ref 规则及其他业务提示保持。旧 facts／claims 入口仍需要字段规则，保留 `context.py`、`agent_prompt.py` 中为它们服务的原指令；不全局删除 `citation_ids`／claim 规则，不恢复强制准备 JSON 或正常答案的固定二次生成。

不顺带改读表策略、资料充分性、检索排序、答案风格、错误恢复、工具 schema、引用解析、普通 `[n]` 处理或预算。Q93／Q99／Q100 的旧答案、诊断、正确来源和数值不能写进业务提示。

### 18.3 E2：一个现有方法，其余通过结果复用

当前自主提示实际改变后，仅运行一次现有方法：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

它确认当前消息构造、真实图入口与直接正文交付仍能走通，沿用原有工具回填、失败记录、稳定 ref、裁剪、旧路径及资源断言。只在现有断言确实绑定旧提示版本时同步预期，不新增逐字提示快照、提示扫描器、引用配对校验器或镜像实现的测试。

页面／导出、模型适配器和网络层本轮不改，直接复用第 16 节及第 13 节相应通过结果，不重跑页面方法或 LLM 方法。指定方法失败时只修复本次改动直接引起的问题并重跑该方法；只有具体跨模块影响证据才扩大。无关缺陷如实报告，不顺带改造。不得运行模块、目录、全量回归或全仓语法／导入扫描。

该方法保持本地 mock，真实服务请求为 0；真实效果由下面十道正常问答观察，不为提示小修再加独立模型实验。

### 18.4 E3：固定十道旧题与原入库版本

输入复用 [D3-Q81～Q100 的 input.json](../../artifacts/v3/d3-qa-q81-q100-20261028/input.json)，保留选中行的原始 `id`、`question_id`、`question` 和 `selected_versions`。**这是旧题复测，沿用 D3-Q 题号，不续排为新题。** 题目原文直接复制，不手工重新录入或清理空白，Q88 原问的尾部空格也保留。

固定五篇原 ready 版本如下，十题均不新增入库、下载、OCR、解析、索引 embedding 或重建索引：

| 论文 | 固定 `paper_id` | 固定 `parse_revision` |
|---|---|---|
| R26／1908.10084v1 | `local_8f4ce726f1fa4cfbbad9b631c80e2bce` | `r_bbebee450c4ae496` |
| R27／2002.01320v1 | `local_e6a6a3f91b36494e90744de7194f9271` | `r_82704cc6d815ba76` |
| R28／2002.03407v1 | `local_586658a88c3f4908912205b2ed8c8bd7` | `r_36f57978209ee9a1` |
| R29／1910.14599v1 | `local_b19a4645dc9a4be2bcf862c8aa4c7209` | `r_0cc2a70ae303ce19` |
| R30／1901.01010v1 | `local_d5ee5a495df14748b2404aa549766cde` | `r_8bf7ad71d160973e` |

十题顺序固定为 **Q81→Q83→Q85→Q88→Q91→Q92→Q93→Q96→Q99→Q100**。七道此前核心通过的题中包含正确表达资料不足的边界题，另三道用于观察已知内容缺口；每篇两题，兼顾机制、指标、列表、质量评价、人员身份、资料不足与条件／表格结果。

下表的观察重点只用于生成后的评价，不能进入业务消息、问题理解、检索参数或工具指令。

| 旧题 | 论文 | 原始问题（实际输入直接复制旧 input） | 官方 `question_id` | 生成后观察重点 |
|---|---|---|---|---|
| D3-Q81 | R26 | How are the siamese networks trained? | `2e89ebd2e4008c67bb2413699589ee55f59c4f36` | 训练机制、目标和所用数据有据，保留题目需要的解释 |
| D3-Q83 | R26 | What metrics are used for the STS tasks? | `a29c071065d26e5ee3c3bcd877e7f215c59d1d33` | 评价指标与相似度函数分清，指标口径准确 |
| D3-Q85 | R27 | Which languages are part of the corpus? | `bc84c5a58c57038910f7720d7a784560054d3e1a` | 主语料语言列表完整，源语／目标语与其他测试集分清 |
| D3-Q88 | R27 | How is the quality of the data empirically evaluated? | `29923a824c98b3ba85ced964a0e6a2af35758abe` | 数据质检的对象、手段及必要结果对应，不能以模型指标替代 |
| D3-Q91 | R28 | Who were the human evaluators used? | `31735ec3d83c40b79d11df5c34154849aeb3fb47` | 评价者身份有据，区别于参考摘要作者，不编造背景 |
| D3-Q92 | R28 | What is the interannotator agreement for the human evaluation? | `fb2b536dc8e442dffab408db992b971e86548158` | 资料不足时说明可见范围，不用偏好比例冒充一致性数值 |
| D3-Q93 | R29 | What data sources do they use for creating their dataset? | `af5730d82535464cedfa707a03415ac2e7a21295` | 正文正常交付；数据来源与用途／轮次覆盖，不作无据的整体否定 |
| D3-Q96 | R29 | Do they compare human-level performance to model performance for their dataset? | `a69a59b6c0ab27bcee1a780d6867df21e30aec08` | 区别人类基线、人工核验比例和模型间比较，资料范围表达准确 |
| D3-Q99 | R30 | Which is more useful, visual or textual features? | `23e2971c962bb6486bc0a66ff04242170dd22a1d` | 首段、正文、结尾都保留数据集／子集条件和例外，不无条件概括联合模型最优 |
| D3-Q100 | R30 | What is their system's absolute accuracy? | `fc1679c714eab822431bbe96f0e9cf4079cd8b8d` | 各数据集／子集的绝对结果及条件是否覆盖；可达表未读与全文未报告分清 |

### 18.5 每题一次真实当前图问答

E1 与指定本地方法完成后，再按固定顺序各执行一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`。每题使用独立新会话、本题注册表和本批新提交 ID，同论文题之间也不共享答案、工具历史或证据状态。实际调用当前图路径，不运行旧批次 main、旧动作模式、fixed_rag 或固定证据实验。

被测模型继续为 `deepseek-flash`，上下文 1,048,576、temperature 0.2、输出上限 4,096；沿用当前 embedding、rerank 与索引 profile。保持 120 个模型轮次、普通请求默认 300 秒、异常综合 90 秒、每次逻辑 invoke 最多一次网络重试及现有账本／恢复规则；不因本批测试添加全题小额度、额外业务重试或框架第二层重试。记录实际生效配置与版本，不把旧 input 中五步、准备 JSON 或旧提示版本抄作本轮配置。

只传原问、固定版本和普通完整回答要求。旧答案、旧评价、官方参考、可回答性标签、gold evidence、预期来源／数值／表号／chunk、指定工具和强制引用范例均不注入业务输入；QASPER `full_text` 不替代真实入库检索。模型自己选择搜索、阅读、计算、回答和停止，不强制读表、跑满轮次或触发异常综合。

本批授权的真实请求仅包括十题正常流程内的前置问题理解、模型／检索工具调用、查询 embedding、重排，以及原策略内的纠错、网络重试与必要异常收尾。一次完整运行可能有多次请求，全部如实计入。没有自然触发的分支沿用已有本地证据，不为覆盖额外发请求；不调用独立 judge、连通性、计费、MinerU 或探测 API。

题目失败、中断、内容不足、缺引用或模型未用某工具，都保留本次结果，不补跑、不追问、不替换题。十题之间不改代码、提示、模型或预算。固定版本不可用时记录受影响题未执行，不重入库；其他独立版本可继续。共享资源／配置故障阻断后续正常问答时，保存完成部分后停止，不额外探测或反复尝试。

### 18.6 普通产物与接续

使用 `artifacts/v3/d4-e-old-qa-20261031/` 的普通 `input.json`／`results.json`，`stage=d4-e-old-qa`，会话／提交 ID 为 `d4-e-old-qa-20261031-q81`、`-q83`、`-q85`、`-q88`、`-q91`、`-q92`、`-q93`、`-q96`、`-q99`、`-q100`。完整 JSON／Markdown 继续由 runtime 写入 `archive/run_logs/d9/`，旧产物保留。

复用 [tmp/d3_react_q93_q99_q100_run.py](../../tmp/d3_react_q93_q99_q100_run.py) 的正常调用、顺序执行、尝试状态及原生日志汇总方式；需要时仅新增 `tmp/d4_e_old_qa_run.py` 窄入口，替换本批十题、stage、目录、ID 和实际配置／统计。工具与纠错统计读取当前 `action_steps[].tool_calls` 和现有账本，不能把图节点数当模型轮数或照抄旧准备阶段计数。不运行旧脚本 main，不新建通用测试平台。

沿用现有“请求前保存尝试状态”的方式。续跑时，已有本批尝试只整理现有日志，接续尚未尝试题，不覆盖本批旧尝试或重新提交失败题；不新增预约协议、哈希、manifest 或全局去重层。

### 18.7 事后评价与结束条件

十题生成后，由执行对话结合实际最终正文、该题展示原文与必要的固定版本原文、QASPER 各份参考作人工式评价，不再请求判题模型。参考意见冲突时依据实际原文说明，不把单份 `unanswerable` 标签直接当裁决。

- **运行／交付：**终态、正文是否实际发布、是否正常直接结束，或出现纠错／恢复／综合。`answered` 不自动代表内容正确。
- **引用：**是否实际写出 `[ID:n]`、映射是否对应本题真实原文、引用是否支持相应事实。普通书目 `[n]` 仍原样保留，不能转成证据引用；定位 `valid` 或空检查不算语义通过。
- **核心内容：**按所问判为通过、部分通过、未通过或未执行，并简述依据。正确说明资料不足可以通过；正常交付但来源、条件或数据错误仍记内容问题。

逐题同题比较：七道此前通过题以 D3 第 31.6 节及该批原生日志为旧记录；Q93／Q99／Q100 以 D3 第 33.8 节最新真实复测为主要基线，保留它们已交付但内容仍有缺口的结论，不再把 Q93 旧准备 JSON 失败当作最新状态。不覆盖或重算历史二十题成绩。

本次只清理一处格式指令，未实施 Q93／Q99／Q100 的内容专项修复；它们仍错就如实记录。七道旧通过题的历史流程与当前流程不同，三个近期错题也存在模型采样变化，本批不作为框架或这一句提示对准确率／速度的独立因果实验，不据十题推断总体准确率。未出现的新工程缺陷不凭猜测增加防护。

复用现有统计记录实际模型轮次、HTTP／SDK 尝试、tokens、报告耗时、搜索／阅读／JS、查询 embedding、重排、网络重试、纠错、恢复／综合、引用出现及来源去重。入库与索引 embedding 为 0；费用或某项统计缺失如实标注，不记成零、不为统计补请求。

完成提示小修、一个指定方法及十题各一次尝试，或明确共享故障导致停止后，把实际修改、方法结果、逐题内容／引用／交付评价、用量与普通产物链接写入第 19 节，更新实际状态并保留第 20 节为文末提示词。未执行完不能写 E 完成。结果中的问题先报告，不自动修复、加测试、重跑旧题或开启新题；不自动提交或推送。

本部分不新增审计、哈希、快照、manifest、保护层、独立验证报告或无关重构。

## 19. 第五部分实际实施记录

**状态：E 已完成；本轮迁移于 2026-11-01 收尾，评价与问题移交见第 19.1 节。**

**提示修改：** [agent_current.py](../../paper_assistant/agent_current.py) 的 `AUTONOMOUS_SYSTEM_PROMPT` 删除末尾旧句 `Keep citations in citation_ids, not in claim text.`，保留已有的“论文事实后写 `[ID:n]`”与稳定 ref 规则。`AUTONOMOUS_PROMPT_VERSION` 更新为 `v3.1-native-tool-loop-prose-citation-v1`，通过原导入转发记录；`PROSE_FINAL_SYSTEM_PROMPT`、`PROSE_FINAL_PROMPT_VERSION`、旧 facts／claims 协议、检索与预算均未改。

**指定方法：**

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

**Ran 1 test in 28.313s，OK。** 现有图入口、消息构造、工具回填、稳定 ref、裁剪、错误记录及旧路径断言保持；未新增提示快照或扫描器。页面／导出、LLM／适配器与网络层未改，第 16／13 节结果复用。

**十题真实复测：**从旧 input 直接复制 Q81、Q83、Q85、Q88、Q91、Q92、Q93、Q96、Q99、Q100 的原问、`question_id` 和固定 `selected_versions`，按固定顺序各运行一次当前 `d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])`。十题均 `completed/answered`；**内容 7 题通过、3 题部分通过、0 题未执行/运行失败**。Q88 原问尾空格保留。

| 题号 | 交付/核心 | 主要观察 | 引/源 | 轮次/工具 | 聊天次/tokens/秒 |
|---|---|---|---:|---|---:|
| D3-Q81 | 通过 | 共享权重、池化、三目标及 NLI/triplet 训练设置有据 | 12/5 | 2；1搜/1读 | 3/22,389/29.719 |
| D3-Q83 | 通过 | Spearman 对 gold、cosine 作为相似度而非指标，ρ×100 口径正确 | 8/3 | 2；1搜/1读 | 3/20,759/23.172 |
| D3-Q85 | 通过 | 11 种源语言完整、均译入 English；Tatoeba 五语另列 | 7/4 | 2；1搜/1读 | 3/22,900/32.813 |
| D3-Q88 | 通过 | 五项翻译质检、split disjointness、Tatoeba 检查齐全，未以模型指标替代质检 | 11/4 | 2；2搜/0读 | 3/38,215/35.172 |
| D3-Q91 | 通过 | 作者机构 20 人、每人 20 次标注；未编造身份背景 | 4/1 | 2；1搜/1读 | 3/28,991/28.844 |
| D3-Q92 | 通过（正确不足） | 正确说明正文未报告 agreement，不以选择比例冒充 | 2/1 | 2；1搜/1读 | 3/28,190/27.281 |
| D3-Q93 | **部分通过** | Round 1 Wikipedia/HotpotQA 来源有据，且明确 Rounds 2/3 未见；仍漏 MTurk/ParlAI、人工 hypotheses/核验及其余来源，未再作“未使用现有语料”的无据否定 | 6/5 | 2；1搜/1读 | 3/21,131/28.406 |
| D3-Q96 | 通过（范围适当不足） | 明确未见人类 accuracy 基线，区分模型 accuracy、采集期 error rate 与人工核验比例 | 12/7 | 3；3搜/1读 | 4/58,143/49.187 |
| D3-Q99 | **部分通过** | 正文保留互补性、Wikipedia 2.9% 与 arXiv 竞争及部分例外；开头仍偏概括，细分表未取得；收尾评价另确认“单选文本更稳妥”的建议缺少所引证据支持 | 18/6 | 2；2搜/0读 | 3/19,106/36.047 |
| D3-Q100 | **部分通过** | Wikipedia JOINT 59.4% 与 10 次 test 均值正确；仍漏 arXiv 93.4/77.1/79.9，Table 3 未读，属可达材料未取得而非全文未报告 | 5/2 | 2；1搜/1读 | 3/18,636/25.781 |

**引用与内容：**十题均 `answer_format=prose_citations_v1`，`citation_checks` 最终 `valid`；正文实际写出 `[ID:n]`，共 85 次引用出现、逐题去重来源合计 38、全批按 paper/version/chunk 去重 34。引用定位通过不等于语义支持；Q93 的 6/5 支持 Round1 与表材料，不支持完整来源清单；Q99 的条件例外部分有据，但首段概括过强，额外的文本默认选择建议也不能由所引比较直接推出；Q100 的 5/2 支持 Wikipedia 与相对比较，不能证明全文只有该绝对 accuracy。

**用量：**问答 **31 次聊天 HTTP／31 次 SDK 尝试／278,460 tokens／报告耗时 316.422 秒**；查询 embedding **14 次/362 tokens/77.799811 秒请求耗时**；重排 **14 次/127,540 报告 tokens/19.136904 秒**；模型轮次 **21**，搜索 **14**、阅读 **8**、取证 **22**；网络重试、纠错、恢复、综合、JS 均为 **0**；正文合计 **18,430 字符**。入库与索引 embedding **0**。费用金额未返回，缺失不记零；报告耗时不互斥，不合并为墙钟耗时。

**产物：**[input.json](../../artifacts/v3/d4-e-old-qa-20261031/input.json)、[results.json](../../artifacts/v3/d4-e-old-qa-20261031/results.json)，窄入口 [d4_e_old_qa_run.py](../../tmp/d4_e_old_qa_run.py)。逐题完整 JSON/Markdown 在 `archive/run_logs/d9/`，路径见 results。真实请求只包括十题正常前置规划、模型/检索工具、查询 embedding、重排及原策略内统计；无 judge、fixed_rag、固定证据、连通性、计费、MinerU 或额外探测请求。

**已知限制：**Q93、Q99、Q100 的既有内容缺口仍在；本次只清理一句旧提示并做一次旧题观察，不是内容专项修复。七道旧通过题与三道近期错题的历史流程、模型采样不同，不能把十题结果单独归因于提示清理或框架迁移，也不据此推断总体准确率或速度提升。历史第 10／13 节成绩保留。

### 19.1 阶段收尾评价与问题移交（2026-11-01）

**本轮 LangChain／LangGraph 迁移按 A～E 已完成并收尾。** 当前实际图、标准工具／模型接口、直接正文、必要异常回填与记录、入口／提示拆分及页面／导出衔接均已落实。E 指定方法通过，十题全部交付，七道旧通过题保持通过；本批没有发现需要继续阻断迁移收尾的新工程问题。当前提示的旧 `citation_ids` 句子已删除，不再列为待修。

剩余内容问题按最新同题结果移交 [issues.md](issues.md)，不继续挂成框架迁移未完成：

| 事项 | 当前状态 | 移交位置 |
|---|---|---|
| Q93 来源覆盖 | 部分通过；Round 1 正确、旧无据否定本次未再出现，后续来源与采集／人工构造关系仍不全 | issues 1.12 |
| Q99 条件与额外推论 | 部分通过；中段／结尾已有例外，开头仍过强；“单选文本更稳妥”建议缺少所引证据支持，细分表未取得 | issues 1.13 |
| Q100 绝对结果 | 部分通过；Wikipedia 正确，arXiv 三子集数值缺失，Table 3 可达但未取得 | issues 1.14 |

三题均在第 2 轮主动停止，日志仍有 118 轮，未出现额度耗尽、重试、纠错、恢复或综合。因此后续责任集中在取证完整性、无新增结果后的继续方向、停止判断及答案条件一致性。正确表达确实缺失的资料仍可通过（如 Q92），不能把所有不足都改为强制阅读。Q99 既有未取全，也有已知例外未贯穿概括和附加建议依据不足的问题。

本次补记只更新问题与状态：七通过／三部分的总评、原始答案、运行日志与历史成绩不改；未触发的异常／JS 分支复用现有本地证据，不追加真实覆盖。旧 Q69 等未在 E 重测的内容残留继续按原记录保留。后续内容改进另行确定，本次不实施修复、补跑、开启新题、提交或推送。

## 20. 给 DeepSeek 的第五部分执行提示词（历史，E 已完成）

复制下方内容交给能访问本项目并执行本地命令的 DeepSeek 环境；无需插件。

```text
执行 docs/v3/d4-plan.md 第18节 E：清理当前自主提示的一句旧引用字段指令，运行一个相关现有方法，再真实复测十道固定旧题各一次，并回写第19节。不要增加多余校验、哈希或额外测试请求。

在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 d4-plan.md 第1～2、16、18～19节，及实际相关代码；A/B/C/D已完成，第5／8／11／14／17节为历史提示，不再执行。保留当前工作区修改，不重做备份、不改远程、不自动提交推送。本次只做E。

先按第18.2节，在 paper_assistant/agent_current.py 的 AUTONOMOUS_SYSTEM_PROMPT 删除末尾“Keep citations in citation_ids, not in claim text.”，继续沿用已有的正文事实后写[ID:n]规则，不叠加重复规则。将 AUTONOMOUS_PROMPT_VERSION 更新为 v3.1-native-tool-loop-prose-citation-v1，通过原有导入转发记录实际版本。旧facts/claims入口仍需要字段指令，保留context.py、agent_prompt.py的原协议；PROSE_FINAL提示和版本、稳定ref规则及其他提示保持。不改充分性、读表、检索、风格、引用解析、普通[n]处理、工具、恢复或预算，不把错题答案和诊断写入业务提示。

修改后只运行 scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records 一次；只有原断言确实绑定旧提示版本才同步预期，不新增提示快照、扫描器或镜像实现的测试。复用原有效断言，真实服务请求为0。页面/导出、LLM/模型适配和网络层未改，复用第16／13节结果，不重跑对应方法。失败只修复本次直接问题并重跑受影响方法，具体跨模块证据才扩大；不跑模块/目录/全量或全仓语法/导入扫描。

随后从 artifacts/v3/d3-qa-q81-q100-20261028/input.json 直接复制 D3-Q81、Q83、Q85、Q88、Q91、Q92、Q93、Q96、Q99、Q100，顺序固定，保留原id/question_id/question/selected_versions，不手工重写或strip原问，Q88尾空格保留。题号仍为D3-Q，属于旧题复测。五篇原ready版本固定见第18.4节，不下载、OCR、解析、索引、重入库或换版，不另做ready/题单校验器或预检请求。

每题各一次完整真实 d9_runtime.run_question(..., mode="agent", library_mode=True, conversation_history=[])，调用当前create_agent图路径，独立新会话/注册表/本批提交ID，同论文也不共享前题答案和历史。保持deepseek-flash、1048576上下文、temperature 0.2、4096输出、当前embedding/rerank/profile、120模型轮次、普通300秒/综合90秒、每逻辑invoke最多一次网络重试及现有账本/恢复规则。记录实际配置与版本，不复制旧input的五步、准备JSON或旧提示配置；十题之间不改代码、提示、模型或预算。

业务输入只有原问、固定版本和普通完整回答要求。旧答案、评价、官方参考、unanswerable/gold、预期来源/数值/表号/chunk、指定工具及强制引用范例均不进入业务消息、问题理解或检索；不以QASPER full_text代替真实入库检索。工具与停止由模型决定，不强制读表、用JS、跑满轮数或触发异常。真实请求只包括十题正常前置规划、模型与检索工具、查询embedding、重排，以及现有策略内纠错/网络重试/必要收尾，全部计入；不发judge、fixed_rag、固定证据、连通性、计费、MinerU或额外探测请求。

普通目录 artifacts/v3/d4-e-old-qa-20261031/，input.json/results.json，stage=d4-e-old-qa；会话/提交ID为 d4-e-old-qa-20261031-q81、-q83、-q85、-q88、-q91、-q92、-q93、-q96、-q99、-q100。原生完整JSON/Markdown由runtime保存archive/run_logs/d9/，保留历史。复用tmp/d3_react_q93_q99_q100_run.py的顺序执行、尝试状态、正常调用和日志汇总方式，必要时仅新增tmp/d4_e_old_qa_run.py窄入口，替换十题、目录、ID、配置与当前图统计；不运行旧main、不造通用测试框架。请求前保存尝试；已有本批尝试只整理，接续未尝试题，失败/中断/缺引用/内容不足不补跑、不追问、不替换题。固定版本不可用则受影响题记未执行，不重入库；共享故障阻断后续时记录完成部分并停止，不反复探测。

生成后按第18.7节结合实际正文、展示原文/必要固定版本原文和QASPER各份参考评价，不再请求判题模型。运行交付、引用交付/支持与核心内容分别评价，valid/answered/空检查不当作语义通过。七道旧通过题用D3第31.6节及该批原生日志比较；Q93/Q99/Q100用D3第33.8节最新三题复测比较，不覆盖历史。重点观察Q93来源覆盖及无据否定、Q99各处结论的条件例外、Q100各子集绝对结果和可达表未读；这些只能用于事后评价，不能注入业务。未做内容专项修复，仍有缺口就如实记录，不宣称清一句提示或框架迁移必然提升准确率/速度，不从十题推断总体准确率。

沿现有账本记录实际模型轮次、HTTP/SDK、tokens、报告耗时、工具/JS、查询embedding、重排、网络重试、纠错、恢复/综合、引用/来源，图节点数不当模型轮数。入库/索引embedding为0，费用或统计缺失如实说明，不填零或追加查询。不新增审计、哈希、manifest、快照、保护层或独立验证报告。

完成后把实际提示修改/版本、方法结果、十题逐题评价、用量与普通产物链接填入d4-plan.md第19节，更新真实状态，保留第20节为文末提示词。未完成就写实际进度与具体原因；不虚报测试或修复。问题先报告，不自动修复、补跑或开启新题，不自动提交推送。
```
