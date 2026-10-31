# D2：已读原文历史延续与 Agent 旧截断限制移除

制定日期：2026-10-27（Asia/Shanghai）。状态：第一阶段、首批 QA 十题、第二批 dev 十题及后续两处局部修正均已完成。首批 9 通过／1 部分通过；第二批 7 通过／2 部分通过／1 澄清；取消前置澄清与统一充分性后，Q12／Q13 通过、Q15 部分通过，见第 7.1／10／13／15.7.1 节。当前结束本轮，不自动启动其他修复或下一批。

本文件参考 [D1 第 9 节](d1-plan.md#9-d1-后续局部修正规划术语忠实性与跨块引用)的安排方式，单独规划 D2；不追加或覆盖 D1 的历史计划与结果。问题依据为 [issues.md 的 1.6／4.2](issues.md#16-适配问题的已读关键事实在后续窗口中丢失)。遵守 [AGENTS.md](../../AGENTS.md) 与 [Stop That Shit](C:/Users/ggy/.codex/plugins/cache/stop-that-shit/stop-that-shit/0.2.4/skills/stop-that-shit/SKILL.md)，执行要求同时写成普通文字，文末提示词不依赖插件。

## 1. 本阶段目的与顺序

第一阶段一起完成：保留同一次 Agent 运行的已读正文，按模型实际容量管理完整请求，取消固定 8192 token、8000 字符及累计 8 块的旧证据限制，并同步引用权限和准备／最终的可用证据定义。目标是在容量充足时，后续搜索或阅读不再抹去早先实际展示的原文。

N03／N05 的无据全文排除与矛盾判断保留为后续独立正确性修正。首批 QA 观察已结束，当前按用户安排规划第 12～14 节下一批，不在新批中修改生成职责；第 8／11 节保留为历史交接文本。

用户多轮历史、检索数量、执行步数、输出及超时默认值、回答扩写、通俗化与成本优化暂缓。D1 各批已完成结果继续作为旧记录，不重跑整个十题批次。

## 2. 实际问题与改动依据

| 问题 | 当前行为与已有证据 | 本阶段处理 |
|---|---|---|
| 已读正文跨取证步骤丢失 | [agent.py](../../paper_assistant/agent.py:592)删去旧 user 消息的正文，工具回复又排除 `visible_chunks`；后续依赖重建的当前证据窗口 | 后续请求延续本次实际展示的正文和有效工具历史，不只留下“曾展示”的 ID |
| 固定证据窗口提前淘汰原文 | [context.py](../../paper_assistant/context.py:19)为结构化材料写死 8192；N07 后续窗口使用 8021／8192 tokens，`p7_c6` 排第 9，以 `after_budget_stop` 省略 | 改为完整请求的模型容量预算，容量充足时继续保留已读正文 |
| 旧字符和累计条数限制可能先执行 | 无 token 预算时回退 8000 字符；[agent_context.py](../../paper_assistant/agent_context.py:159)在 token 选择之前执行累计切片；部分消息入口仍保留旧 5／8 条校验 | 同步移除 Agent 路径的旧字符回退、累计切片及相应旧校验，不让它们在新预算之前接管 |
| 引用和提示只认可当前窗口 | [agent_prompt.py](../../paper_assistant/agent_prompt.py:281)将证据和引用绑定当前 `evidence_sections`；早期正文移出后不再可引用 | 引用、准备及最终统一依据本次请求实际保留的有效正文 |

N07 的直接触发原因是 token 窗口及正文历史重组，当次 `count_omitted=[]`；不能把它归因于累计 8 块切片。取消 8 块是处理另一个实际存在的提前截断入口。8000 字符也不是与 token 预算并行截断，而是必须一起清理的旧分支。

N07 的 [原始记录](../../archive/run_logs/d9/agent_20261026_074957_220040_0df00fc8fb29.json)显示：结论正文进入过早期自主决策，准备和最终却已没有它。现有“成功准备请求继续传到最终”的实现应保留并接通更早正文，不能仅扩大一次窗口后宣称历史问题已解决。

## 3. 直接复用 RAGFlow 的部分与必要适配

只读参考 `E:/project/ragflow`，不修改该仓库。优先移植已有机制与策略，利用当前项目的 `tool_history`、`chunk_id`、context 和成功准备历史，不先迁移 Go／Eino 框架或建设另一套通用会话系统。

| RAGFlow 来源 | 直接采用的行为 | 当前项目必要适配 |
|---|---|---|
| [run_session.go](E:/project/ragflow/internal/agentic_rag/run_session.go:38) | 同次运行的较早消息通过 session 事件重放继续提供；新增调用不覆盖旧消息 | 在现有 Python 消息链中延续有效工具调用、结果和已展示正文，仍使用现有稳定 `chunk_id` |
| [message_fit.go](E:/project/ragflow/internal/agent/chat/message_fit.go:35)及[LLM 调用位置](E:/project/ragflow/internal/agent/component/llm.go:831) | 先组装完整消息，再按模型容量 fitting；容量足够则原样保留，采用其 97% 容量余量；未知容量回退 8192 | 加入当前输出预留和工具定义开销，在准备、最终及修复实际发送前使用同一容量规则 |
| [evidence_registry.go](E:/project/ragflow/internal/agentic_rag/evidence_registry.go:27) | 来源身份稳定，跨步骤继续关联已经提供的证据 | 直接沿用项目现有 `chunk_id` 与来源检查，不另造引用句柄、正文指纹或映射校验层 |

session 来自 Agentic RAG，`FitMessages` 来自 Canvas LLM 组件，是两处可复用实现；不能写成 RAGFlow Agentic 当前已统一执行的同一机制。

其 [tokenizer.Fit](E:/project/ragflow/internal/tokenizer/message_fit.go:35)在超限时会删除较早非 system 消息，并可能直接裁剪字符串。本项目消息含 JSON 证据和原生工具调用，超限处理需按完整消息／原文单元适配，保留工具调用与结果配对，不能直接切坏 JSON 或把已截断正文继续按完整 chunk 开放引用。这是接入现有协议需要的适配，不新增审核或校验阶段。

## 4. 第一阶段的六项改动

### 4.1 延续本次运行的正文历史

- 不再将旧消息统一缩成问题与步骤号，也不再以“正文只放最新窗口”为由丢弃所有早期工具正文。按 RAGFlow 的同次运行重放语义，后续请求能继续取得此前实际展示的原文。
- 搜索排名决定这次新增结果的顺序，不改变已经读过的来源身份。相同 `chunk_id` 复用已有正文，不在每一步把全部原文再复制一份；使用现有 ID 去重，不计算新哈希。
- 只延续本次请求所属运行、所选版本与来源范围内的材料。原生工具调用和结果继续按现有 `tool_call_id` 配对；定位候选不因进入历史就变成已读证据。

### 4.2 按实际模型容量管理完整请求

- 在现有 `LLMSettings` 和配置示例中补充上下文容量配置，例如 `LLM_CONTEXT_LENGTH`。当前 `deepseek-flash` 明确使用 `1048576` tokens，依据 [DeepSeek 官方模型说明](https://api-docs.deepseek.com/api/list-models/)。容量配置独立于输出 `max_tokens`、请求超时与执行额度，不为识别容量额外调用模型或建设模型目录服务。
- 保留 RAGFlow 的未知容量回退 8192；当前已明确配置容量的 DeepSeek 不进入该回退。删除 Agent 固定 8192 证据视图预算，不能仅把参数改成 `None`，再让旧分支恢复 8192 或 8000 字符。
- 在组装后统一计算系统提示、问题、用户历史、工具调用与结果、原文、准备响应、最终指令及工具定义等请求开销。沿用 RAGFlow 的 97% 余量，并为当前配置输出额度留足空间；输入预算不得超过 `min(floor(0.97 * 上下文容量), 上下文容量 - 输出预留)`。
- 准备、最终和格式／引用修复使用相同规则；最终追加准备响应后需要按实际最终请求重新计算，不能只沿用准备时的证据 token 数。复用可用的计数依赖，不以 embedding chunk 的 token 数代替完整聊天请求计数，也不发真实请求来做离线计数。
- 容量足够时不淘汰已读正文。确实超限时才对完整消息／原文单元释放空间，并以本次最终保留正文更新引用范围；沿用现有消息结构和来源处理，不增加正文摘要模型、证据快照或一套独立验证流程。

### 4.3 移除 Agent 的 8000 字符旧限制

同步调整 `context.py`、Agent 输入及实际消息构建中的字符回退和硬编码校验；新路径不再用 8000 字符限制正文。原有日志中的字符数可作为普通统计保留，不能继续决定原文是否可用。已有固定证据或其他入口若直接复用受影响函数，只做维持其正常调用所需的签名和调用适配，不扩展为所有模式的重构。

### 4.4 移除累计 8 块及旧累计证据条数校验

合并去重后不再执行 `retained[:8]` 等累计切片；清理关联的 5／8 条最终证据校验，让累计正文由完整请求容量决定。单次搜索仍保持当前 top 5，搜索调用结果协议与累计证据数量分开管理，不把本项扩成 top-N 参数改造。

### 4.5 引用权限对应实际发送正文

当前请求历史中实际保留的正文继续可以引用，使用既有 `chunk_id`、版本与来源信息；仅有候选定位、历史 ID 或旧模型结论而无正文的来源仍不可引用。若真实容量裁剪移除了某块，引用范围同步移除；不能永久累计“曾经见过”的全部 ID。

准备、最终、修复和现有引用发布使用同一个实际正文范围；现有 context／来源结构承载所需正文，避免模型能看到而发布层无法定位。沿用现有来源与引用检查，不新增引用生成模型、语义匹配器、校验器、哈希或正文指纹。

### 4.6 准备与最终使用全部实际保留原文

修改现有准备、最终和修复规则，将“仅最新 `evidence_sections` 有效”改成“本次请求实际保留的全部有效原文可用”。去掉早期正文已保留却仍被统一宣布不可引用的旧表述，候选定位与原文仍作明确区分。

继续保留 `facts / answerable / missing_information`、现有 Claim／EvidenceQuote、原生工具协议，以及成功准备请求向最终生成的历史重放。最终可以使用实际保留原文补足准备遗漏；准备结果不自动成为新增论文证据。只更新实际受影响的提示版本，整理冲突规则，不堆叠另一套同义警告。

## 5. 实施后指定离线验证

本节用于后续代码实施，不在本轮文档修改时执行。只调整并点选以下 3 个既有方法，使用本地材料与 mock，不运行整个脚本模块、目录或全量回归，不发真实聊天、embedding、重排或检索服务请求。

| 既有方法 | 本阶段需要覆盖的实际行为 |
|---|---|
| `scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question` | 完整准备／最终消息能使用保留的早期正文；累计正文超过旧 8000 字符和 8192 token 时，在所配容量足够的前提下仍可提供；完整请求计入历史、准备响应与输出预留；容量不足时保留正文与可引用 ID 一致，未展示定位不能引用 |
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 实际自主核心 mock 经早期搜索、后续读取、准备和最终后，早期正文仍可见且可正常发布引用；工具配对、现有保存和修复链正常；实际容量配置与未知容量回退分别生效 |
| `scripts.check_agent.AgentFlowChecks.test_ten_unique_candidates_remain_in_whole_request_context` | 旧方法 `...produce_eight_retry_first_whole_chunks` 已按新行为重命名；容量足够时十个去重候选不再被累计八块切片丢掉，方法内保护旧上限的断言已替换，不保留两套相反预算行为 |

测试材料使用通用正文，不把 N07 的正确答案或指定 chunk 写进生产提示。相关方法中固定 8192、8000 字符和八块的断言随对应行为调整，不新增一套哈希或文本匹配机制。已通过且相关代码未变的验证直接复用；只有失败或出现具体跨模块影响，才扩大到直接相关的方法，不默认增加第四个方法或全量测试。

离线方法证明消息传递、容量与发布行为，不证明真实模型一定答全。真实内容表现按下一节单独记录。

## 6. 第一阶段仅复测 D1-N07 一次

完成第一阶段实现与上述离线验证后，按本节执行一次真实完整 Agent 复测。第一次于 2026-10-27 执行，发现 `select_context` 仍注入 8192；用户随后明确要求重跑，第二次使用当前代码执行，两次均记录于第 7.1 节。第二次不是自动补跑，也不覆盖第一次记录。

| 项目 | 固定输入 |
|---|---|
| 问题 | `How are resources adapted to properties of Chinese text?` |
| 论文 | Shallow Discourse Annotation for Chinese TED Talks，沿用 D1 的 A 版本 |
| paper_id | `local_903ae31ca7a448f382affa3b1274bc7e` |
| parse_revision | `r_d10f45f1749c1be9` |
| 入口 | `mode="agent", library_mode=True`，独立新会话 |

沿用模型、ready 版本、索引、普通完整回答要求与第一阶段范围外参数，只改变本计划明确的正文历史和预算行为。模型自主选择检索与阅读，不将正确 chunk、答案、AltLexC／Progression 诊断、期望引用或工具动作塞进业务问题及模型提示；这些只作事后原文对照。

直接复用现有 runtime、单题调用及保存能力。若需要窄调度入口，只筛选本题并连接新目录，不直接启动 `tmp/d1_new_ten_run.py` 的旧十题批次，也不重建评测框架。原 D1-N07 报告直接作为旧结果，不重新执行旧流程。

建议结果目录：`artifacts/v3/d2-evidence-history-fix-20261027/`，已存在时使用新后缀，不覆盖已尝试记录。只用普通 `input.json/results.json` 和既有 `archive/run_logs/d9/` 逐次 JSON／Markdown，保存实际请求、准备、最终、引用、失败阶段与用量；不另抄一套日志或产生独立验证报告。

事后根据实际记录判断：

- 早期实际展示的正文在后续读取、准备及最终请求中是否延续；如果本次没有自然出现旧丢失路径，明确记录该路径未覆盖，不靠强制动作补一次。
- 原问所需主要适配是否完整，准备是否遗漏重要并列项；引用对应实际保留正文且支持具体结论。不能只以 `answerable=true`、引用定位 valid 或出现两个关键词判通过。
- 若原文仍未取到，区分本次未取得、取得后丢失、准备漏提取和最终漏表达；不把所有漏答归到同一个窗口问题，也不因机制已修就宣布内容通过。
- 如实记录聊天、查询 embedding、重排、重试／修复、token 与报告耗时。单题成本变化只作观察，不声称稳定提速、普遍准确率提升或严格因果关系。

单题各一次的含义是本题只执行一次完整流程；正常共享额度内重试／修复按现有行为计入该次记录。成功或保存明确阶段失败后结束，不因漏答或取证路径不同而反复抽样；配置或资源故障按实际失败记录，不自动重开整个流程。

## 7. 紧随后续阶段与本次边界

### 7.1 第二阶段：N03／N05 表达忠实性

第一阶段完成后，独立处理 [issues.md 的 1.5／4.3](issues.md#15-附加分析作无据的全文排除或矛盾判断)：N03 将当前材料未见外推成全文没有其他外部数据集，N05 将名称与用途描述直接判为不一致。

后续只调整现有准备和最终规则：`missing_information` 描述回答原问仍缺的事实；区分当前未见与论文明确否定；全文排除和矛盾判断需要相应原文支持，名称／用途的不同描述本身不构成矛盾。保留用户要求的正常解释与分析，不新增审核模型、全文否定检测、黑名单或答案后处理。

该阶段实施时再按实际改动点选必要既有方法，并仅以 D1 第 11.3 节原题、第 11.2 节 G／S 版本分别复测 N03／N05 各一次，使用原记录作旧对照，不与第一阶段 N07 混算。它不是第一阶段验收前置条件，也不在下一节第一阶段提示词中执行。

### 7.2 暂缓与沿用

- 用户多轮历史仍为现有 3 轮／4000 字符，本阶段只修同一道题内部的 Agent 正文历史。
- 单次检索仍 top 5，保留五步与五次取证、输出 4096、单次超时 30 秒及既有共享重试／修复。暂不照搬 RAGFlow 的 12 条、120 步或引入其整题成本额度；这些不是 N07 已读正文丢失的必要修复。
- 页面已取消的最多 3 次聊天／整题 120 秒继续保持取消，不重新施加，也不重复修改。
- 扩写、重复、通俗化、可选 `direct_answer` 与 token 优化暂缓；字段语义问题保留记录，后续使用 QASPER 短答评测前再处理，不把它当纯格式问题。
- 不改解析、分块、索引、入库、存储架构或 UI，不重建来源映射，不下载论文或重新 embedding 全库。不新增额外业务校验层、哈希、正文指纹、manifest、快照、审计、检查清单、评委或独立验证报告；既有必要来源／版本／引用检查直接复用，不顺带清理与本次无关的已有字段。

### 7.3 完成记录

后续实施完成后，在本文件第 8 节之前简要补记改动、实际点选方法与结果、N07 真实状态及普通结果路径，更新 [issues.md](issues.md)对应状态与 [总规划](plan.md)的 D2 入口。规则接通、离线通过和真实内容表现分开陈述，未执行的部分明确标注；D1 原答案和成绩不覆盖。

本轮仅新建本规划。未来交接执行第一阶段达到本文件要求后结束，不自动进入第二阶段、扩成新十题或继续添加保护层；本文件最后一节始终保留为给 DeepSeek 的普通执行提示词。

## 7.1 第一阶段实际实施与结果（2026-10-27）

### 实际改动

- 配置与计费：`LLMSettings.context_length` 读取可选 `LLM_CONTEXT_LENGTH`；示例值为 `deepseek-flash` 的 `1048576`。新增 `paper_assistant/message_fit.py`：已知容量使用 `min(floor(context*0.97), context-output_reservation)`，未知容量回退 `8192` 并按输出预留计输入预算；tokenizer 复用上下文既有 Qwen 计数器。
- Agent 完整上下文：`source_scope.Registry.full_context_mode` 在自主 Agent 时关闭候选的 8192 token 选择；`context_options={}`，`max_chars=None`，`merge_*`／`read_evidence_context`／`restore_conversation_evidence` 的 `max_chunks=None`；`select_context` 在 `max_chars=None` 时不再从候选自动注入 8192。固定 RAG 与固定证据仍走原路径。
- 消息历史：先前的 payload 不再压缩成 `{"question","autonomous_step"}`，工具历史保留原始 user 正文、assistant tool call 与 tool reply 的配对；当前 payload 只放**本次新增**原文（`new_evidence_ids`），`allowed_citation_ids` 仍是会话中实际保留的全部原文 ID，因此早期正文不会被重复抄写到每个请求，也不会失去引用权限。
- 请求容量：`fit_request` 先按完整消息组（保护当前请求；最终生成保护准备组）删除最早历史，再按整块删除正文；删除后同步 `shown_evidence`、`allowed_citation_ids`、`shown_chars`、`omitted_evidence`、`candidate_locations` 与所有历史 payload 的引用 ID，绝不留下“正文已删但 ID 仍可引用”的请求。
- 准备／最终／修复：准备使用完整有效原文；最终重放成功准备请求的全部消息，不再只看本次 payload；格式／动作修复以失败的完整请求为 base，保留原工具配对与原文；最终修复在准备历史上追加。
- 提示：v2.19 明确“本会话已提供的原文”均可作准备依据，最终按会话中全部有效原文引用；只有被容量裁掉或仅存在于候选定位的块不可引用。旧 5／8 块计数校验与 8000 字符 Agent 上限已移除。

### 指定离线验证

三个既有方法均通过（2026-10-27，最后运行 24.598 秒，3 tests OK）：

1. `scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question`
2. `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records`
3. `scripts.check_agent.AgentFlowChecks.test_ten_unique_candidates_remain_in_whole_request_context`（旧名 `...produce_eight_retry_first_whole_chunks`，已按新行为重命名）

覆盖：十块去重候选在容量足够时全部保留；当前请求只含新增块而允许引用 ID 累计；早期正文在后续请求／最终中可见；不同阶段使用全部有效原文；`context_fit_budget` 的已知 1M 与未知 8192 回退、完整请求 token 计数均实际计入。另新增一个强制超容量用例：10 个长正文、`context_length=8192`、输出预留 1024，输入预算 7168；请求从 11,113 tokens 裁到 6,655，删 6 块留 4 块，并断言 `allowed_citation_ids` 等于保留正文 ID、所有历史 payload 的引用 ID 同步、被删 ID 进入 `omitted_evidence` 的 `token_budget`、被删正文不再出现在请求中。

### D1-N07 两次复测（第二次为当前代码生效验证）

**第一次（2026-10-27，保留为历史尝试）**

- 输入同下；新独立会话，`mode=agent`、`library_mode=True`；正常完整回答，未使用 QA 最短答案、direct_answer 指令、F1 或 judge。
- 结果：`answered`，4 次聊天请求、43,474 tokens、40.391 秒、2 次 embedding、2 次 rerank、0 重试、0 修复，最终 6 条主张／6 个来源，引用检查 valid，准备 8 条事实、`answerable=true`。早期 `p7_c6`（删除 AltLexC／新增 Progression）保留到准备与最终，最终第 3 条主张引用该块。
- 内容边界：补出 `p7_c6`，但没有旧答案中的论元标注、Hypophora／问句序列、EntRel 省略；最终以“Section 3 未展示”收束。
- 容量旁注：context 仍带 `max_tokens=8192`，`p1_c4` 因 `token_budget` 被省略；说明当时 8192 尚未真正移除。运行后发现 `select_context` 在 `max_chars=None` 时仍从结构化候选注入 8192，随后修复。
- 记录：[input.json](../../artifacts/v3/d2-evidence-history-fix-20261027/input.json)、[results.json](../../artifacts/v3/d2-evidence-history-fix-20261027/results.json)、`archive/run_logs/d9/agent_20261027_075816_845274_a96b3b3316eb.json`／`.md`。

**第二次（用户要求重跑，当前代码）**

- 输入：同一原问、`local_903ae31ca7a448f382affa3b1274bc7e`／`r_d10f45f1749c1be9`；新独立会话 `d2-n07-rerun-20261027`，`mode=agent`、`library_mode=True`；正常完整回答，未使用 QA 最短答案、direct_answer 指令、F1 或 judge。
- 结果：`answered`，4 次聊天请求、56,508 tokens、42.907 秒、2 次 embedding、2 次 rerank、0 重试、0 修复，最终 9 条主张／7 个来源，引用检查 valid，准备 12 条事实、`answerable=true`。
- 四项验证：context 为 `max_chars=None`、`max_tokens` 不存在、`shown_evidence=10`、`shown_chars=14,870`、`omitted_evidence=[]`；最终请求本地计数 26,988 tokens，完整预算 1,017,118 tokens。说明本运行没有 8192 证据窗口、没有 8000 字符截断、没有八块上限，也没有触发容量裁剪。10 块正文全部在会话历史中，`p7_c6` 保留到准备与最终，最终第 7 条主张引用它。
- 内容：覆盖论元（`p2_c3`）、sense hierarchy（`p4_c2`）、隐式关系连接词和结论段 `p7_c6`；但仍未调用 `read_context`，第 9 条主张明确说 Section 3.2 的详细关系适配和作者实际采用的论元修改未展示。第二次检索已返回 `p2_c2`、`p2_c3`、`p4_c2`、`p4_c3`，所以“没有读”主要是模型再次提前准备，而不是没有检索到任何 Section 3 内容。
- 与第一次对比：第一次 43,474 tokens、6 条主张、8192 窗口；第二次 56,508 tokens、9 条主张、无 8192。内容覆盖增加，但仍非原问完整覆盖；单题不用于准确率或速度结论。
- 记录：[input.json](../../artifacts/v3/d2-evidence-history-fix-20261027-rerun/input.json)、[results.json](../../artifacts/v3/d2-evidence-history-fix-20261027-rerun/results.json)、`archive/run_logs/d9/agent_20261027_113311_578818_d5432118ee5c.json`／`.md`。旧 N07：[agent_20261026_074957_220040_0df00fc8fb29.md](../../archive/run_logs/d9/agent_20261026_074957_220040_0df00fc8fb29.md)。

**当前判断**

四项改动在第二次运行中实际生效：正文历史保留、8192 取消、8000 字符取消、八块取消。仍未解决的是证据充分性／探索：第二次有机会读 Section 3.2（reading directory 有 `parent10`）却没有读，导致关系细节和实际论元修改缺失。1M 完整请求预算在本第二次运行中也没有触发裁剪（26,988 远低于 1,017,118）；“超容量同步裁剪”由强制离线用例验证，不等于真实 1M 请求已经触发过裁剪。

### 本阶段未做

- 未重跑 D1 十题、旧基线 N07、fixed_rag、固定证据、judge 或额外模型实验；第二次 N07 只按用户明确要求重跑当前题；未执行后续阶段（N03／N05）及 §7.1 以外的语义审计。

## 8. 给 DeepSeek 的第一阶段执行提示词

第一阶段已完成，以下仅保留为历史交接文本，不重新执行。本次新十题按第 9～11 节安排，使用第 11 节提示词。

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d2-plan.md、docs/v3/issues.md 的 1.6／4.2，以及 docs/v3/d1-plan.md 第11～12节，只执行 D2 第一阶段：同次 Agent 运行的已读正文延续、完整请求容量管理、三类旧截断移除、引用与准备／最终规则同步。先确认本阶段实际实施和复测记录，已完成且相关代码未变的验证不重复执行，已有真实尝试不补跑。本次实现从现有工作区继续，保留用户已有修改，不重置或覆盖历史结果。

动手前按“用户让做了吗、结果需要吗、有证据吗、缺少会失败吗”约束范围。只读参考 E:/project/ragflow/internal/agentic_rag/run_session.go、evidence_registry.go、internal/agent/chat/message_fit.go、internal/tokenizer/message_fit.go 及 internal/agent/component/llm.go。优先移植现成消息延续、完整消息 fitting 和默认回退行为，只做当前 Python／JSON／原生工具协议的必要适配，不迁移整套 Go／Eino，不改 RAGFlow 仓库。

一次完成本文件第4节六项：保留此前实际展示的正文、工具调用及结果，不再删掉旧正文后仅靠最新窗口；取消 Agent 固定8192 token证据窗口、8000字符回退及累计8块切片，调整相关旧5／8条累计校验；按模型实际容量管理完整请求；引用权限对应本次实际保留正文；准备、最终和修复统一使用全部有效原文。利用现有tool_history、稳定chunk_id、context与成功准备→最终重放，避免每步把全文重复复制一份，不只累计旧ID。

在现有LLMSettings／配置示例补上下文容量，当前deepseek-flash明确使用1048576 tokens。未知容量才保留RAGFlow的8192回退；已知容量不能再被旧分支降为8K。上下文容量、输出max_tokens和取证额度分别管理。组装后计入system、问题、用户历史、工具定义、工具调用／结果、原文、准备响应、最终／修复指令及输出预留。沿用97%容量余量，并确保输入不超过容量减实际输出预留。容量足够则保留全部已读正文；真超限时按完整消息／原文单元适配，保留工具配对和JSON结构，以裁剪后的实际正文同步引用范围。不直接把Go fitter的字符串裁剪用于JSON证据，不新增审核或校验阶段。

保持facts／answerable／missing_information、Claim／EvidenceQuote、当前单次top5、五步／五次取证、4096输出、30秒单次超时及共享重试／修复。页面已取消的3次聊天／整题120秒不恢复。用户历史3轮4000字符、top-N与步数配置化、无据附加分析、direct_answer、文风、通俗化与成本优化都不混入本阶段。只调整实际受影响调用和提示版本，必要共享入口随签名适配，不做无关重构。

实施后仅调整并点选第5节列出的三个既有单独方法：scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question、scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records，以及scripts.check_agent.AgentFlowChecks.test_ten_unique_candidates_produce_eight_retry_first_whole_chunks（按新行为重命名）。把保护旧数字的断言换成正文连续性、实际容量、累计十块可保留和引用发布行为。全部本地／mock，不为离线验证发真实模型、embedding或重排请求，不跑整模块、目录或全量回归；只有失败或具体跨模块影响才扩大直接相关方法。只改文档或注释时不跑测试。

实现与指定离线验证通过后，按第6节仅运行一次D1-N07完整Agent，独立新会话，mode="agent", library_mode=True，原题为“How are resources adapted to properties of Chinese text?”，paper_id=local_903ae31ca7a448f382affa3b1274bc7e，parse_revision=r_d10f45f1749c1be9。本提示包含这一题的正常前置理解、聊天、查询embedding、可选重排及原有额度内重试／修复，不包含其他真实题目或模型实验。模型自主搜索与阅读，不把正确chunk、答案、诊断或期望引用塞进业务消息，不强制动作。不要启动旧十题runner、fixed_rag、固定证据实验或评委，不重跑旧N07。

复用现有runtime与日志保存，使用artifacts/v3/d2-evidence-history-fix-20261027/（已有则新后缀）下普通input.json/results.json及现有archive/run_logs/d9/逐次JSON／Markdown。看实际请求中的早期正文是否传到准备与最终、原问主要适配是否完整和引用是否支持，并记录真实用量。未自然出现旧路径就记录未覆盖，不为凑覆盖再跑。只运行一次或保留明确阶段失败后结束，内容未改善也不改提示后补抽样。

完成后在D2末尾提示词之前补记实际改动、离线结果、N07状态和产物路径，更新issues.md对应状态及v3总规划D2入口。区分机制接通、离线通过与真实内容表现，不覆盖D1历史，不声称普遍准确率或稳定提速。本次不执行第7.1节N03／N05后续阶段。不要新增任何额外校验器、审核模型、正文哈希／指纹、manifest、快照、审计、检查清单或独立验证报告；现有必要来源检查直接复用。完成第一阶段即结束，保持D2最后一节为本提示词。
```

## 9. 新十题 QA 完整 Agent 测试规划（2026-10-27）

### 9.1 目的与本批范围

D2 第一阶段的正文延续和三类旧限制移除，在已测范围内通过；N07 仍存在“核心缺口有补证方向、额度未耗尽，却直接准备收尾”的内容问题，已单列在 [issues.md 第 1.7 节](issues.md#17-核心缺口仍存在时提前准备与收尾)。先用新的问题观察它是否跨题出现，不继续反复跑 N07，也不先修改停止判断。

本批 QA 指当前页面对应的完整论文问答：`d9_runtime.run_question(..., mode="agent", library_mode=True)`，输出普通完整回答与引用。十题全部采用本地 QASPER train 官方原题、独立新会话；不附加最短答案、`direct_answer` 或 F1 协议，不调用评委模型。这里是开发观察，不是独立留出集准确率或新旧方案公平对照。

本轮仅把问题和测试安排写入文档，不执行十题，不创建运行结果。本批后续交给 DeepSeek 执行时，包含这十题的正常前置理解、查询 embedding、可选重排、模型自主搜索／阅读、准备、最终及原有额度内重试／修复。

### 9.2 固定条件

- 使用当前 D2 已实施代码与 v2.19 相关提示，不先修 N03／N05、`direct_answer`、文风或取证充分性，不在十题中途改生产代码、提示或参数。
- 沿用当前 `deepseek-flash`、上下文容量 `1048576`、temperature 0.2、输出上限 4096、单次超时 30 秒、五步与五次共用取证及既有共享重试／修复。旧 8192 证据窗口、8000 字符和累计八块限制保持取消；页面三次聊天／整题 120 秒限制保持取消。
- 十题按下表顺序，各使用独立新会话，不继承 D1、N07 或彼此的回答。单次检索仍 top 5，模型自主决定是否继续搜索、阅读或准备，不强制动作，也不为了覆盖分支造缺口。
- 只使用下表已有本地版本与现有 ready 索引。不下载、解析、入库、重建向量或新增模型连通性实验。已有离线方法及相关代码未变，直接复用通过记录，不先重跑测试。
- 将实际公开配置、提示版本、每题 `conversation_id` 和 `submission_id` 写入普通输入索引；不输出密钥。若当前配置与上述计划不一致，先记录差异，不静默改模型或参数后声称同一批。

### 9.3 论文与完整版本配对

沿用 D1 已运行过的本地版本，代号只用于本表与题目表，不改变检索范围。

| 代号 | 论文／QASPER paper_id | 本地 paper_id | parse_revision |
|---|---|---|---|
| D | Dynamic Memory Networks for Visual and Textual Question Answering／`1603.01417` | `local_e1d98edb937e40be9c967348d0c734b9` | `r_d7354c46c4404390` |
| S | Improving Slot Filling by Utilizing Contextual Information／`1911.01680` | `local_82440870d77e472cae9f8b4a7391512f` | `r_fda731e86209b3be` |
| A | Shallow Discourse Annotation for Chinese TED Talks／`2003.04032` | `local_903ae31ca7a448f382affa3b1274bc7e` | `r_d10f45f1749c1be9` |
| M | MonaLog: a Lightweight System for Natural Language Inference Based on Monotonicity／`1910.08772` | `local_5da940b5dc2a4dff8a7b5358de12b728` | `r_ffe2ec817e72a72e` |
| N | Location-Relative Attention Mechanisms For Robust Long-Form Speech Synthesis／`1910.10288` | `local_2cc8d921ea84427fa519dae6f1c39b8e` | `r_2e39e24cc58dc759` |

### 9.4 新十题与执行顺序

题目原文与 `question_id` 取自本地 [QASPER train](../../eval/qasper/raw/qasper-train-v0.3.json)，保留原有英文与拼写。按已有 `eval/qasper/*/sample.json` 及 `artifacts/v2`、`artifacts/v3` 的批次输入／样本／结果索引比对，以下题号和问题原文未出现；部分主题与旧题接近，因此只称开发批次中的新题，不称独立留出数据。

“事后观察重点”、官方答案、证据标注及本文件的问题诊断仅供运行后评价，不能传入模型消息、前置规划、搜索参数或工具提示。运行输入只取原题、对应完整版本和普通完整回答要求，不整体加载含参考答案的原始数据给模型。

| 编号 | 版本 | 输入问题（按此原文运行） | QASPER question_id／事后观察重点 |
|---|---|---|---|
| D2-Q01 | D | Why is supporting fact supervision necessary for DMN? | `129c03acb0963ede3915415953317556a55f34ee`；原因及必要限定，区分原 DMN 与 DMN+ |
| D2-Q02 | D | What changes they did on input module? | `141dab98d19a070f1ce7e7dc384001d49125d545`；并列改动及各自作用是否完整 |
| D2-Q03 | D | How does the model circumvent the lack of supporting facts during training? | `bfd4fc82ffdc5b2b32c37f4222e878106421ce2a`；所问机制与训练关系，不以一般模型介绍代替回答 |
| D2-Q04 | S | What are the baselines? | `cb8e2069218e30c643013c20e93ebe23525d9f55`；多个基线是否答全、系统名称归属 |
| D2-Q05 | S | What metris are used for evaluation? | `5efa19058f815494b72c44d746c157e9403f726e`；保留官方拼写，指标及适用限定 |
| D2-Q06 | A | How high is the inter-annotator agreement? | `0d7f514f04150468b2d1de9174c12c28e52c5511`；agreement／Kappa、数值及评价范围 |
| D2-Q07 | A | Do they build a model to recognize discourse relations on their dataset? | `58e65741184c81c9e7fe0ca15832df2d496beb6f`；本文实际工作、未来计划与一般用途，否定范围 |
| D2-Q08 | M | How do they combine MonaLog with BERT? | `4688534a07a3cbd8afa738eea02cc6981a4fd285`；组合方式、模型分工与训练／推断边界 |
| D2-Q09 | M | Do they beat current state-of-the-art on SICK? | `ee27e5b56e439546d710ce113c9be76e1bfa1a3d`；比较对象、实验设置及结论强度 |
| D2-Q10 | N | Does DCA or GMM-based attention perform better in experiments? | `5c4c8e91d28935e1655a582568cc9d94149da2b2`；不同条件和比较维度，不加强统计结论 |

### 9.5 执行与保存

建议本批目录为 `artifacts/v3/d2-qa-new-ten-20261027/`。未来首次执行时保存普通 `input.json/results.json`，原生逐题 JSON／Markdown 继续由现有 runtime 保存到 `archive/run_logs/d9/`。若已有本批尝试记录，只接续尚未尝试题；只有明确另开一批时才使用新后缀，不覆盖或重跑已尝试题。

直接复用现有 `d9_runtime.run_question`、正常日志保存和 `tmp/d1_agent_ten_run.py`／`tmp/d1_term_fix_run.py` 的顺序调度、用量提取思路。需要时只新增本批的窄调度入口，如 `tmp/d2_qa_ten_run.py`，将任务名称、批次目录及提交／会话前缀改为本批 D2；不能原样启动写死旧目录和 D1 标识的 runner，也不建设通用评测框架或修改生产 runtime。

十题全部为 `conversation="independent"`；会话／提交 ID 可使用 `d2-qa-new-ten-20261027-q01` 至 `q10` 等本批唯一前缀。先记录尝试状态，再执行并沿用正常日志落盘；进程中断后不得把已尝试但未完成的题当作从未运行而自动重开。

`input.json` 保存第 9.4 节原题、官方题号、版本配对、顺序和实际公开配置，不保存 gold、诊断或观察重点作为业务输入。`results.json` 仅汇总各题运行状态、停止原因、日志路径、真实请求与用量，以及简短内容评价，不再复制整份工具正文。

每题只执行一次完整流程。回答、澄清、证据不足和运行失败分别保存，不追加追问或替代题来补成绩。正常额度内重试／修复计入该次流程；配置、索引、资源等共享故障影响后续时保留已尝试范围并停止排障，未执行题记明原因，不自动重开全批。

### 9.6 评价口径：先看核心覆盖，再看停止是否合理

逐题结合实际提供的原文、最终回答及官方参考作 AI 辅助原文对照，分别记为通过／部分通过／失败，运行失败单列。官方答案不代替本地原文；存在版本或证据差异时据实说明，不为匹配参考而改写业务输入或补跑。

- 看原问的必要并列项、因果关系、条件、比较对象与数值是否答全，事实与每条引用是否匹配。运行完成、引用定位 valid、准备事实数量或最终篇幅不能替代这个判断。
- 若仍有缺口，先区分核心缺项与用户未问的可选细节。记录材料未取得、已取得后丢失、准备漏提取或最终漏表达；只有核心未覆盖且尚有可执行方向时，才记录“提前收尾”的具体依据。
- 对第 1.7 节观察，沿用已有动作／消息记录查看准备的 `answerable`、缺口文字、剩余步数与取证次数，以及已知候选或阅读目录。模型没有调用 `read_context` 本身不算错；当前证据足够时提前结束可以通过。没有自然出现多轮阅读或超容量路径就记为未覆盖，不强制工具、不塞满 1M、不另加实验。
- 无据全文排除、矛盾判断、扩写、可选字段和表达问题继续归入现有问题条目，不与核心事实缺失混成一类。未要求却输出的 `direct_answer` 只单列观察，不用它替代 claims 主答，不在本批切换短答协议。
- 统计真实聊天、查询 embedding、重排、重试／修复、tokens 与报告耗时。新十题与旧 N07／D1 的题目和路径不同，不据此声称准确率提升、等质量降本或稳定提速。

本批只需在现有结果中统计“核心覆盖不足且有提前收尾证据”的涉及题数与具体题号；同一题不因多段缺口重复计数。十题结束后据跨题表现再决定是否局部修改充分性判断，不在运行中调提示、加步数、增加模型或自动开始第二阶段。

## 10. 新十题实际结果

执行日期：2026-10-27。实际尝试 **10/10**、完成 **10/10**、运行失败 **0**；10 题均为 `answered`，10 个独立新会话，没有澄清、证据不足或未执行题。仅调用一次 `d9_runtime.run_question(..., mode="agent", library_mode=True)` 每题；没有修改代码或提示，没有重跑 N07、D1 旧批次或离线方法。

| 题号 | 状态 | 核心覆盖评价 | 备注 |
|---|---|---|---|
| D2-Q01 | completed／answered | **部分通过** | 两条核心原因（单向 GRU、远距离句词级交互）已答出，并正确保留作者推测限定；但开头和末尾将普通因果问转为严格必要性证明，direct_answer 又写 Unanswerable。属于回应重心与答案一致性问题，不是未取得原因或混淆 DMN／DMN+。 |
| D2-Q02 | completed／answered | 通过 | 覆盖 sentence reader、input fusion、bi-GRU、位置编码；额外覆盖 VQA 输入模块。Table 1 数值未给出，但问的是输入模块改动。 |
| D2-Q03 | completed／answered | 通过 | 覆盖不要求 supporting fact 标签、模型学习选择重要事实、input fusion 与 attention-based GRU。 |
| D2-Q04 | completed／answered | 通过 | Adobe internal NLU、Pytext、Rasa 三个基线及 Table 2 F1 均覆盖。 |
| D2-Q05 | completed／answered | 通过 | 给出 micro-averaged F1 on all labels，并说明它是可见的唯一评价指标。 |
| D2-Q06 | completed／answered | 通过 | 给出 0.85／0.83 及完整 agreement／Kappa 表值，并指出正文 intra/inter 术语差异。 |
| D2-Q07 | completed／answered | 通过 | 回答 No；论文是数据集／标注工作，parser 和自动识别只是未来工作。 |
| D2-Q08 | completed／answered | 通过 | 覆盖 MonaLog 生成 E/C 对、与输入句配对、扩展 SICK 训练集、fine-tune BERT、0.95 阈值重标 N。 |
| D2-Q09 | completed／answered | 通过 | 回答 No；给出 77.19、85.38、86.74、87.1 等比较，未把 hybrid 说成 SOTA。 |
| D2-Q10 | completed／answered | 通过 | 回答 no uniform winner；DCA／GMMv2b 均最快对齐且可泛化，DCA 有感受野和归一化优势，和官方“about the same”一致；自然度数值表未展示，但问的是比较结论。 |

**总计：**9 通过、1 部分通过、0 失败；67 条最终主张、40 个 evidence sources；40 次聊天请求、478,818 tokens、308.97 秒；15 次查询 embedding、15 次 rerank；0 网络重试、0 修复。40 次聊天请求与 10 题均逐题记录在 [results.json](../../artifacts/v3/d2-qa-new-ten-20261027/results.json)。10/10 题都自发输出了 `direct_answer`，仅作为附带观察记录，不用它替代 claims 主答评分。

**跨题提前收尾：**十题中**没有发现**符合“核心事实仍缺、有具体补证方向、额度未耗尽，却 `answerable=true` 并收尾”的题目。Q01 已有两条原因，缺的是用户未要求的形式证明，不应为了它继续取证；其回应偏移与短答不一致单列于 [issues.md 第 1.8／1.3 节](issues.md#18-将普通因果提问升级为形式必要性证明)。Q10 缺少自然度数值表，但用户问的比较结论已给出。二者不按核心缺口重复计数。十题全部 `answerable=true`，均用 2 个自主步骤；Q05 用 1 次取证，其余 1–2 次。

**自然未覆盖路径：**Q04、Q06、Q08、Q09 调用了 `read_context`，但结果均为 `no_new_shown_evidence`，没有成功新增正文；其余题未调用。没有自然出现多轮阅读或超容量裁剪，不另加实验。所有 context 的 `max_chars=None`、无 `max_tokens`，保留 5–10 块、最多 12,731 字符，说明本批没有 8192／8000／八块上限；1M 完整请求预算未触发裁剪。

**产物：**[input.json](../../artifacts/v3/d2-qa-new-ten-20261027/input.json)、[results.json](../../artifacts/v3/d2-qa-new-ten-20261027/results.json)；逐题原生 JSON／Markdown 保存在 `archive/run_logs/d9/`，各题路径见 results。调度器最后一次汇总写入遇到一次 Windows 文件替换权限错误，但十题逐题记录均已落盘，随后补写汇总与 `halt`，没有重跑任何题。第一次 N07、第二次 N07 与 D1 历史结果均保留，不用于重算本批成绩。本批只作开发观察，不声称准确率、稳定性或速度提升，也未开始第二阶段或修改停止判断。

## 11. 给 DeepSeek 的新十题 QA 执行提示词

首批 Q01～Q10 已完成，以下仅保留为历史交接文本，不重新执行。下一批 Q11～Q20 使用第 14 节最新提示词，包含第 12 节指定新论文的必要入库。

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d2-plan.md 第9～10节及 docs/v3/issues.md 第1.7节，执行D2-Q01～D2-Q10新十题QA完整Agent观察。本任务是测试当前版本，不修代码或提示。D2第一阶段已经完成，不再执行第8节历史交接、不重跑N07或D1旧批次，也不进入N03／N05修正规划。

先看第10节与 artifacts/v3/d2-qa-new-ten-20261027/ 的实际状态。已有尝试记录不重跑，只接续从未尝试题；若十题都已尝试，直接整理结果，不再调用模型。按第9.4节十道QASPER官方原题、原文和顺序运行，准确使用第9.3节完整paper_id／parse_revision配对；十题全部独立新会话，不继承旧回答。保留英文原题及拼写，不加正确答案、观察点、诊断、期望chunk／引用或强制工具动作到模型消息、前置规划及检索参数。

每题只执行一次 d9_runtime.run_question(..., mode="agent", library_mode=True)，输出普通完整回答与引用。本任务包含十题正常前置理解、聊天、查询embedding、可选重排以及原有额度内重试／修复。保持当前D2实现和v2.19相关提示、deepseek-flash、1048576上下文、temperature 0.2、4096输出、30秒单次超时、五步／五次共用取证及既有共享修复。三类旧证据截断和页面三次聊天／整题120秒限制保持取消。实际公开配置与提示版本写入普通input.json，不静默换模型或参数。

本批QA是完整问答开发观察，不附加最短答案、direct_answer要求或F1协议，不运行QASPER双模式评分runner、fixed_rag、固定证据实验或judge。参考答案和证据标注只在输出后对照，不能整体传给业务模型。只用现有ready版本，不下载、解析、入库、重建索引或额外测试模型连通性。相关代码未变的三个指定离线通过结果直接复用，不重跑测试、整模块或全量回归。

复用现有runtime、正常日志保存及tmp/d1_agent_ten_run.py、tmp/d1_term_fix_run.py的顺序调度和用量提取。若需入口，只增加本批窄调度，如tmp/d2_qa_ten_run.py，改对D2任务名称、批次目录、提交与会话前缀；不要直接运行写死D1目录和标识的旧runner，不重构生产代码。使用artifacts/v3/d2-qa-new-ten-20261027/下普通input.json/results.json和现有archive/run_logs/d9/逐题JSON／Markdown，不复制另一套完整正文日志，不覆盖旧批次。记录尝试状态后再执行，已有尝试不得因中断或失败自动重开。

模型自主决定搜索、阅读及准备。内容错误、澄清或缺口如实保留，不改提示后补抽样，不追加替代题；共享配置／索引／资源故障影响后续时停止并记录失败阶段、已发生用量与未执行原因。十题各一次或明确故障停止后结束，不为了凑十题完成或覆盖read_context分支强迫动作。

按第9.6节用实际原文与官方参考作AI辅助评价，分别看核心覆盖、事实忠实、逐条引用、运行状态和成本。特别记录“核心事实仍缺、有具体补证方向且额度未耗尽，却answerable=true并收尾”的实际题号；区分未取到、取到后丢失、准备遗漏和最终遗漏。未调用read_context本身不是失败，证据充分时提前结束可以通过；用户没问的细节也不强行当核心缺项。自然未出现的多轮阅读／超容量路径记未覆盖，不加额外实验。direct_answer若自发出现，只单列观察，不用它替代claims评分。

完成后只在D2第10节简要记录实际数量、逐题评价、跨题提前收尾情况、失败、用量和普通产物路径，更新issues.md对应问题与v3总规划本批入口。新旧题不同，不声称准确率或稳定速度提升，不重算旧D1／N07成绩。本轮先观察，不自动修改停止判断、加容量／步数或开始第二阶段。不要新增无用校验层、审核模型、哈希／正文指纹、manifest、快照、审计、检查清单或独立验证报告。保留D2最后一节为本提示词。
```

## 12. 第二批新十题 QA 测试规划（2026-10-27）

### 12.1 来源、目的与当前状态

首批 Q01～Q10 为 9 通过／1 部分通过，未发现 N07 式核心缺口提前收尾跨题重复。Q01 已单列为 [issues.md 第 1.8 节](issues.md#18-将普通因果提问升级为形式必要性证明)的回应重心偏移，以及第 1.3 节的短答不一致：两条原因已经答出，不是证据没取到。问答生成规则与停止机制继续保持。用户另明确要求将默认入库入口改为调用 MinerU 官方 API，本批先完成这一项业务改动，再准备论文和测试。

按用户澄清，本批全部取自 **QASPER 官方数据集**，不限已有入库论文，不使用自拟题补足。固定本地 [qasper-dev-v0.3.json](../../eval/qasper/raw/qasper-dev-v0.3.json)中的 10 道原题、5 篇新论文，每篇 2 题。`official_split=dev`，对应公开 validation 数据；本批是使用公开 dev 的开发测试，不称官方隐藏 test 成绩或独立准确率。

十道题号与原文字串均未见于已有批次输入／样本／结果索引，五篇目前未在本地论文库中。先按论文链接完成必要入库，再运行十题；不受第 9.2 节首批“只使用已有 ready 版本”的限制。本轮只写规划与提示词，不下载、入库或发起真实测试。

### 12.2 五篇论文及下载链接

以下标题与 arXiv 条目已核对。本批明确使用 v1 PDF，记录该实际来源；不假定它与 QASPER 抽取正文完全一致，事后有差异时据实说明。

| 代号 | QASPER paper_id／论文 | 来源链接 | 本地绑定 |
|---|---|---|---|
| V1 | `1912.01214`／Cross-lingual Pre-training Based Transfer for Zero-shot Neural Machine Translation | [arXiv](https://arxiv.org/abs/1912.01214)／[v1 PDF](https://arxiv.org/pdf/1912.01214v1) | 待实际入库 ready 后记录 |
| V2 | `1909.00512`／How Contextual are Contextualized Word Representations? Comparing the Geometry of BERT, ELMo, and GPT-2 Embeddings | [arXiv v1](https://arxiv.org/abs/1909.00512v1)／[v1 PDF](https://arxiv.org/pdf/1909.00512v1) | 待实际入库 ready 后记录 |
| V3 | `2003.03106`／Sensitive Data Detection and Classification in Spanish Clinical Text: Experiments with BERT | [arXiv](https://arxiv.org/abs/2003.03106)／[v1 PDF](https://arxiv.org/pdf/2003.03106v1) | 待实际入库 ready 后记录 |
| V4 | `1909.11687`／Extreme Language Model Compression with Optimal Subwords and Shared Projections | [arXiv v1](https://arxiv.org/abs/1909.11687v1)／[v1 PDF](https://arxiv.org/pdf/1909.11687v1) | 待实际入库 ready 后记录 |
| V5 | `2002.03407`／Abstractive Summarization for Low Resource Data using Domain Transfer and Data Synthesis | [arXiv v1](https://arxiv.org/abs/2002.03407v1)／[v1 PDF](https://arxiv.org/pdf/2002.03407v1) | 待实际入库 ready 后记录 |

不预先编造本地 `paper_id` 或 `parse_revision`。表中 QASPER paper_id 用于定位数据集，不能直接作为本地运行版本；同一论文的两道题绑定入库返回的同一完整本地配对。

### 12.3 十题与固定顺序

运行时按指定 `question_id` 从原始 dev 文件提取 `question`，保留官方英文、大小写、语法和末尾空白。下表只用于展示，不靠手工润色重写；Q17、Q20 原字符串末尾各有两个空格。

“事后观察重点”、官方答案、证据和本文件的问题诊断只用于输出后的评价，不进入业务模型消息、前置规划或工具参数。

| 编号 | 论文 | 官方问题原文 | question_id／事后观察重点 |
|---|---|---|---|
| D2-Q11 | V1 | which multilingual approaches do they compare with? | `b6f15fb6279b82e34a5bf4828b7b5ddabfdf1d54`；比较方法完整性与归属 |
| D2-Q12 | V1 | what language pairs are explored? | `5eda469a8a77f028d0c5f1acd296111085614537`；语料、枢轴语言与实际翻译方向，必要并列项 |
| D2-Q13 | V2 | What experiments are proposed to test that upper layers produce context-specific embeddings? | `1ec152119cf756b16191b236c85522afeed11f59`；实验设计与指标，不只复述结论 |
| D2-Q14 | V2 | How do they calculate a static embedding for each word? | `891c2001d6baaaf0da4e65b647402acac621a7d2`；具体构造方法和表示范围 |
| D2-Q15 | V3 | What is the performance of BERT on the task? | `66c96c297c2cffdf5013bab5e95b59101cb38655`；数据集、任务与评价口径下的数值归属 |
| D2-Q16 | V3 | What are the other algorithms tested? | `6b53e1f46ae4ba9b75117fc6e593abded89366be`；比较算法完整性，区分方法与实现工具 |
| D2-Q17 | V4 | Why are prior knowledge distillation techniques models are ineffective in producing student models with vocabularies different from the original teacher models? | `d087539e6a38c42f0a521ff2173ef42c0733878e`；直接解释技术约束与原因，保留条件 |
| D2-Q18 | V4 | What state-of-the-art compression techniques were used in the comparison? | `efe9bad55107a6be7704ed97ecce948a8ca7b1d2`；比较方法与设置，区分 teacher／student／baseline |
| D2-Q19 | V5 | What is the interannotator agreement for the human evaluation? | `fb2b536dc8e442dffab408db992b971e86548158`；是否报告所问数值，区分未报告与否定，不编造指标 |
| D2-Q20 | V5 | Is the student reflection data very different from the newspaper data? | `b5608076d91450b0d295ad14c3e3a90d7e168d0e`；判断与实际领域／结构差异对应，保留范围 |

### 12.4 先改默认入库入口，再准备五篇论文

**A. 唯一新增业务改动：默认直接调用官方 API**

修改 [import_runtime.import_pdf](../../paper_assistant/import_runtime.py:29)的默认入库行为，使页面上传及本批调用同一入口时直接使用 MinerU 官方精准解析 API。不能只在批次脚本中单独调用 API、页面默认仍走本地 Standard，也不能只把默认字符串改成 `mineru-api` 后继续要求普通调用方先提供 `api_bundle`。

- 复用 `load_mineru_api_settings`、`parse_pdf_via_api` 和现有 `mineru-api` 结果导入分支：普通 PDF 导入自动完成上传、等待解析、下载原始结果，再衔接既有结果适配、父子分块、SQLite 保存及当前 Qdrant profile 的 embedding 入库。
- 固定使用 `model_version="vlm"`、文件参数 `is_ocr=true`、`enable_formula=true`、`enable_table=true`，不传 `page_ranges`，整篇处理。现有 API 调用已支持这组参数，直接复用；不凭返回的 `effort` 字段新增官方未公开的高档位参数。
- 页面调用不增加必填参数或本地／云端切换控件；沿用现有进度、结果和失败展示。已有 `api_bundle` 直接复用，重复上传的同一 PDF 若已有本批 API 方案的可用 ready 版本，复用现有版本／缓存，不再次上传解析；已有本地 Standard 版本保留，不能冒充 API 结果或批量重解析历史论文。
- API Token 缺失或调用失败时，按现有导入失败方式返回真实错误，不自动回退本地解析、不继续索引或声称 ready。保留必要的本地结果格式转换，这不等于重新运行本地 GPU 文档解析。
- 改动限于入库编排、必要调用适配及现有提示文案；不改问答内核、存储架构、解析算法，不新建解析服务、通用重试框架、额外缓存／校验层或哈希机制。

**B. 入口改动后的最小离线验证**

后续实施只调整并点选以下两个既有方法，使用 mock API、离线 embedding 与本地临时材料，不调用真实 MinerU、聊天或 embedding 服务。本轮文档修改不运行它们。

1. `scripts.check_mineru_api.MinerUAPIChecks.test_config_upload_poll_and_original_bundle_without_gpu_or_index`：确认全文调用不带页码限制，VLM／OCR／公式／表格参数及原始结果包保存正确；保留原方法必要的显式页码参数行为。
2. `scripts.check_index.IndexChecks.test_successful_import_and_repeat_make_no_second_embedding_request`：通过实际默认 `import_pdf` 串起 mock API 解析、现有结果适配和索引 ready；重复同 PDF 不新增 API／embedding 请求，失败不发布 ready。必要时调整旧默认本地解析的断言，不另造一套导入测试框架。

问答代码未变的三个既有离线结果直接复用，不因本次入口改动重跑问答测试。只有指定方法失败或出现具体跨模块影响，才扩到直接相关方法；不跑整模块、目录或全量回归。

**C. 五篇新论文的必要准备**

入口改动和上述离线方法通过后，下载第 12.2 节五份 v1 PDF，经修改后的默认入口完成 **MinerU API 全文 OCR 入库**。PDF 可放在 `eval/qasper/pdfs/<arxiv_id>v1.pdf`；本批五篇统一使用上述 API 方案。若已有同一 API 解析结果或相应 ready 配对，按现有机制复用，不重新发起同一任务。真实 API 解析与索引 embedding 属于本批必要入库工作，不另加连通性或解析对比实验。

根据真实 `status=ready` 结果，在本批普通 `input.json` 的论文表中写入来源 URL、PDF 版本、解析方案、实际 `(paper_id, parse_revision)` 与当前索引 profile，再用于对应两道题。沿用现有入库状态和来源检查，不新增校验器、哈希快照、manifest 或证据映射工程，也不把 QASPER 的参考证据／full_text 直接塞进问答来代替真实 PDF 入库。

单篇下载或解析失败时记录实际失败，该篇的两题保持未执行，不换论文／题目；不受该篇影响的其他论文可继续。模型配置、embedding 服务、索引资源等共享故障阻断后续时停止，记录已发生请求及剩余未执行原因。入库成本与问答成本分开汇总，不把解析／索引 embedding 混作查询 embedding。

### 12.5 十题执行、参数与保存

入库成功后，逐题只运行一次 `d9_runtime.run_question(..., mode="agent", library_mode=True)`。十题均独立新会话，`conversation_history=[]`，输出普通完整回答与引用，不附加最短答案、`direct_answer` 或 F1 协议。

除第 12.4 节默认入库入口外，保持当前 D2 问答代码及 v2.19 相关提示、`deepseek-flash`、`1048576` 上下文、temperature 0.2、4096 输出、30 秒单次超时、五步／五次共用取证和既有共享重试／修复。三类旧证据限制与页面三次聊天／整题 120 秒继续保持取消。本批不先修 Q01、N07、N03／N05、可选字段或文风，也不在十题中途改变模型或预算。

本批目录使用 `artifacts/v3/d2-qa-dev-next-ten-20261027/`，任务标识使用 `stage="d2-qa-dev-next-ten"`；提交／会话可用 `d2-qa-dev-next-ten-20261027-q11` 至 `q20` 等唯一前缀。普通 `input.json` 同时保存五篇实际入库结果和十题无 gold 输入，`results.json` 保存状态、逐题日志路径、用量与简短评价；逐次完整正文与响应继续用 `archive/run_logs/d9/` 原生日志，不另复制一套。

复用 `tmp/d2_qa_ten_run.py` 的现有顺序调度、用量提取和保存逻辑，需要时只加本批窄入口，如 `tmp/d2_qa_dev_next_ten_run.py`。将批次路径、stage、题号与提交／会话前缀接到本批，不能直接运行仍指向首批目录的旧入口，不建设通用 runner 或修改问答 runtime；第 12.4 节入库编排的必要改动包含在任务内。

已有本批记录时只接续尚未尝试题；先记录尝试状态，再发问答请求。内容错误、澄清或证据不足也保留，不重新生成、不追加追问或替代题。只运行第 12.4 节入口改动所需的两个离线方法，其余已通过且相关代码未变的结果复用，不额外跑测试、全量回归或模型／embedding 连通性请求。

### 12.6 评价与结束条件

沿用第 9.6 节核心覆盖、忠实性、逐条引用及真实运行状态的评价方式，但本批换为 dev 新论文，不能与首批 train 题目直接作准确率或速度归因比较。运行完成与内容通过分开统计，入库失败、未执行及运行失败不藏进成功题数。

本批追加观察两个现有问题：

- **提前收尾：**核心事实确实未覆盖、已有具体补证方向且额度未耗尽时，是否仍 `answerable=true` 收尾。没有阅读动作、没有完整表格或缺少用户未问的细节，单独都不足以判失败；自然未出现多轮新增阅读或超容量路径就记未覆盖，不强制动作补实验。
- **回应重心／短答一致性：**原因、比较、是否类问题能否直接回答实际所问，而非索求用户未要求的形式证明或额外条件。合理纠正错误前提允许成立；不能仅因与官方措辞不同判错。若正文已有有据解释，短答却为 `Unanswerable`，分别记录主答覆盖与字段不一致，不用短答代替 claims 评分。

官方参考仅在运行后与实际本地原文对照。原文未报告所问值时可诚实说明缺口；既不能编造数字，也不能把“未报告”加强为“不存在”。有 PDF 版本、抽取或表格差异时记录实际原因，不为贴合 gold 而重新入库、改提示后补跑。

十题各尝试一次，或明确故障停止后结束。只记录本批是否跨题重复上述问题及相应题号，不把同题多个段落计成多题，不自动启动修复阶段、增加审核模型或继续下一批。汇总必要的下载／解析／入库成本、问答请求、查询 embedding／重排、tokens 与耗时；不新增独立验证报告、哈希、审计或检查清单。

## 13. 第二批十题实际结果

执行日期：2026-10-27。本批完成默认入库 API 编排、两个指定离线方法、五篇新论文准备和 D2-Q11～Q20 十题问答；未改问答内核、系统提示、停止规则或预算。

### 默认入库入口与离线验证

- `import_runtime.import_pdf` 默认改为 `parser="mineru-api"`；页面上传和普通导入都自动读取 `MINERU_API_TOKEN`、调用 `parse_pdf_via_api`，固定 `vlm`／`is_ocr=true`／`enable_formula=true`／`enable_table=true`、不传 `page_ranges`，整篇解析。已有 API bundle 或同 PDF 的 API parse 版本直接复用；普通调用无需先给 bundle。Token 缺失／API 失败按失败返回，不回退本地、不继续索引。
- `scripts.check_mineru_api.MinerUAPIChecks.test_config_upload_poll_and_original_bundle_without_gpu_or_index`：通过；mock 验证全文请求不带 `page_ranges`、显式页码请求仍保留。
- `scripts.check_index.IndexChecks.test_successful_import_and_repeat_make_no_second_embedding_request`：通过；mock API 走默认入口到 ready，重复同一 PDF 只 1 次 API、0 次额外 embedding，embedding 失败和 API 失败均不发布 ready；原 Standard 分支保留并显式测试。
- 两个方法均未发真实 MinerU／聊天／embedding 请求；问答三个已通过离线结果按代码未变复用。

### 五篇 API 准备

五份 PDF 下载自第 12.2 节 v1 链接，均为默认入口真实解析。解析方案：`mineru-api` 3.4.4，VLM／OCR／公式／表格／全文；五篇均 `ready`。

| 代号 | QASPER paper_id | 本地 paper_id／parse_revision | API batch_id | chunks | 索引 embedding |
|---|---|---|---|---|---|
| V1 | 1912.01214 | `local_ceffb8f4d7d9432c947c4bfed305a4f4`／`r_d2bf40c05ce555c1` | `2c6ae017-400c-45c4-9099-6f2e4ea8b456` | 38 | 4 |
| V2 | 1909.00512 | `local_69264257566f4852a58c5323a89afa3d`／`r_2f0989aa60cd781a` | `fbf1acd1-8a12-40c2-9153-a9fb98c7f4d7` | 34 | 4 |
| V3 | 2003.03106 | `local_6ea12bf2b36844b39f032c65c04fbab8`／`r_6f647351b0a8f7af` | `c39ac13e-6588-4e85-9901-485497f06b51` | 50 | 5 |
| V4 | 1909.11687 | `local_2d7ec33617ee4a4a949058fc30913e06`／`r_b31c143d1ea0a255` | `06164a27-1b54-4171-b7be-6c08a0c3f1c5` | 30 | 3 |
| V5 | 2002.03407 | `local_586658a88c3f4908912205b2ed8c8bd7`／`r_36f57978209ee9a1` | `7cb6a088-690c-40cb-a285-c9e95744a76c` | 28 | 3 |

下载 5 份、合计 1,940,601 bytes；索引 embedding 共 19 次请求；准备阶段报告耗时合计 232.155 秒。未重复上传同一 PDF，未复用旧 Standard 版本冒充 API 结果。

### 十题运行与评价

十题全部独立新会话、`conversation_history=[]`，每题只运行一次；**10/10 completed**，9 answered、1 needs_clarification、0 运行失败。运行后按官方 dev 参考作 AI 辅助评价：**7 通过、2 部分通过、1 澄清（内容未交付）、0 失败**。

| 题号 | 运行 | 核心评价 |
|---|---|---|
| D2-Q11 | answered | 通过：pivoting、MNMT、无预训练跨语言迁移及额外 MNMT 变体。 |
| D2-Q12 | answered | **部分通过／提前收尾**：给出 Europarl 三组和 MultiUN 四语言/English pivot，但没有具体八组方向及阿拉伯语、西班牙语、俄语等具体语言；准备仍 `answerable=true`，剩余 3 步，阅读目录有 Setup／Main Results。 |
| D2-Q13 | answered | **部分通过／提前收尾**：给出 self-similarity 和 intra-sentence similarity，缺 maximum explainable variance；`direct_answer=Unanswerable`；剩余 3 步，阅读目录含 4.2／4.3。 |
| D2-Q14 | answered | 通过：first principal component，及 MEV／anisotropy 限定；`read_context` 无新增正文。 |
| D2-Q15 | needs_clarification | 澄清“哪个 task/dataset/metric”，没有交付官方要求的 BERT F1 数值；单列澄清，不混入通过数，不计运行失败。 |
| D2-Q16 | answered | 通过：rule-based、CRF、spaCy、NLNDE S2／S3、BERT+CRF；`read_context` 成功新增 `p3_c9`。 |
| D2-Q17 | answered | 通过：共享 vocabulary/output space、tokenization mismatch、student embedding from scratch、维度变化；未升级为形式证明。 |
| D2-Q18 | answered | 通过：PKD 6／3 层、NoKD、BERT_BASE teacher。 |
| D2-Q19 | answered | 通过：官方两处答案均 unanswerable；模型明确说没有报告 agreement，`prep answerable=false`，无编造数值。 |
| D2-Q20 | answered | 通过：Yes；领域、结构、重复／碎片／语法、规模及 ROUGE 差异；未把“无分布距离数值”说成不存在。 |

**跨题问题：**确认 **D2-Q12、D2-Q13** 两题属于“核心仍有具体缺口、阅读目录有方向、额度未耗尽，却 `answerable=true` 收尾”；两题都只用了 2 个自主步骤。D2-Q15 是检索前澄清，不是提前收尾。D2-Q19 的 `no_reliable_evidence_direction` 与官方 unanswerable 一致，不是缺口。其余题未发现同类问题。

**容量：**十题 context 全部 `max_chars=None`、无 `max_tokens` 键；展示 0–16 块，单题最多 20,720 字符（Q19），旧 8192／8000／八块限制未生效。1M 完整请求预算未触发裁剪；没有为覆盖多轮阅读或超容量路径强行加实验。

**成本：**问答 38 次聊天请求、554,570 tokens、报告耗时合计 251.503 秒；查询 embedding／重排各 16 次；0 网络重试、0 修复；48 条主张、35 个 evidence sources。9/10 题自发输出 `direct_answer`，只单列观察。

**产物：**[input.json](../../artifacts/v3/d2-qa-dev-next-ten-20261027/input.json)、[results.json](../../artifacts/v3/d2-qa-dev-next-ten-20261027/results.json)；逐题原生 JSON／Markdown 在 `archive/run_logs/d9/`，路径见 results。首批 Q01～Q10、N07、D1 历史保留，不与本批混算；本批是公开 dev 开发观察，不声称隐藏 test 成绩、准确率或稳定速度提升。

## 14. 给 DeepSeek 的第二批十题执行提示词

以下提示依次包含：默认入库入口切换官方 API、两个相关离线方法、指定五篇论文的 API 全文 OCR 入库、D2-Q11～Q20 十题问答；不执行第 8／11 节历史任务。

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d2-plan.md 第12～13节及 docs/v3/issues.md 第1.3／1.7／1.8节，执行D2第二批任务：先把默认入库入口改为自动调用MinerU官方API，完成两个指定离线方法，再用该入口入库五篇新论文，最后运行D2-Q11～Q20十道QASPER官方dev原题。这是公开dev／validation开发测试，不是隐藏test成绩。本批不使用自拟题，也不限于已经入库的论文。

先看第13节与artifacts/v3/d2-qa-dev-next-ten-20261027/实际状态。已有同一API方案的ready准备或问答尝试记录直接复用，只接续缺少的实现／准备和从未尝试的题；不重跑首批Q01～Q10、N07、D1，也不按第8／11节历史提示再实施旧任务。保留工作区已有修改。本批唯一业务改动是默认入库API编排及必要调用适配，不改问答内核、系统提示、停止规则或预算，不先修Q01等内容问题。

按第12.4节修改import_runtime.import_pdf的默认行为：页面上传和本批普通PDF导入都自动调用官方API，不再默认本地mineru-standard。复用load_mineru_api_settings、parse_pdf_via_api及已有API结果适配／导入分支；普通调用无需先给api_bundle，已有bundle可直接复用。不能只改默认字符串，不能只在测试脚本中绕过入口调用API。固定VLM、is_ocr=true、公式和表格识别开启、不传page_ranges，整篇解析，不添加官方未公开的高档位参数。衔接现有分块、SQLite、embedding缓存与Qdrant索引，保持页面进度和返回结构；不加本地／云端选择控件。重复同PDF的API ready结果复用，不重复上传，历史Standard版本保留但不能冒充本批API结果。Token缺失／API失败按原有失败结果返回，不静默回退本地、不继续索引或声称ready。

实现后只调整并点选scripts.check_mineru_api.MinerUAPIChecks.test_config_upload_poll_and_original_bundle_without_gpu_or_index和scripts.check_index.IndexChecks.test_successful_import_and_repeat_make_no_second_embedding_request。使用mock API、离线embedding和临时材料，验证全文参数、默认入口到ready、重复导入不重复API／embedding以及失败不发布ready；不发真实请求做离线验证。问答代码未变的三个通过结果复用，不重跑问答测试、整模块或全量回归；只有失败或具体跨模块影响才扩大直接相关方法。

入口和指定离线方法完成后，按第12.2节五篇arXiv链接下载v1 PDF，统一使用修改后的默认API入口与当前索引profile完成全文OCR、正文保存及embedding入库，记录实际API配置、batch_id和入库结果。必要PDF下载、官方API解析与索引embedding属于本任务，无需为每篇另立授权或额外验证阶段。使用真实status=ready返回的本地paper_id／parse_revision绑定对应两题，不把QASPER paper_id当本地ID、不预造版本，不把数据集full_text或参考证据直接喂给问答来绕过入库。已有同一API方案的解析结果或ready配对就复用。单篇失败保留该篇两题未执行，其他独立论文可继续；共享服务／资源故障阻断后续时停止并记录实际用量与原因。

十题固定为第12.3节顺序，从eval/qasper/raw/qasper-dev-v0.3.json按指定question_id提取原始question，保留英文、大小写、语法和原有末尾空白。只把原题、实际ready版本配对和普通完整回答要求传入业务流程。观察重点、Q01/N07诊断、gold答案与证据标注只供事后评价，不能进入模型消息、前置规划、检索参数或工具提示，不强制搜索／阅读动作。

入库后每题只运行一次d9_runtime.run_question(..., mode="agent", library_mode=True)，十题独立新会话，conversation_history=[]。本任务包含十题正常前置理解、聊天、查询embedding、可选重排、准备、最终及原有额度内重试／修复。保持当前D2实现和v2.19相关提示、deepseek-flash、1048576上下文、temperature 0.2、4096输出、30秒单次超时、五步／五次共用取证及既有共享修复。固定8192证据窗口、8000字符、累计八块和页面三次聊天／整题120秒限制保持取消。

输出普通完整回答与引用，不加最短答案、direct_answer要求或F1协议，不跑fixed_rag、QASPER双模式评分、固定证据、judge或额外模型连通性实验。除上述两个入库相关方法外，相关代码未变的离线通过结果复用，不额外跑测试或全量回归。复用现有入库、问答runtime、日志保存及tmp/d2_qa_ten_run.py的窄调度逻辑，必要时新增本批入口tmp/d2_qa_dev_next_ten_run.py，改对本批路径、stage、题号和提交／会话前缀；不要运行仍指向首批目录的旧main，不新建通用框架或额外校验层。

本批使用artifacts/v3/d2-qa-dev-next-ten-20261027/下普通input.json/results.json。input保存五篇实际来源、版本、解析配置、入库返回配对与十题无gold输入；results汇总真实状态、原生日志路径、用量与简短评价。完整问答继续由现有archive/run_logs/d9/逐题JSON／Markdown保存，不复制另一套正文日志。先保存尝试状态再运行，失败／中断已有尝试不能自动当新题重开。入库与问答成本分开，索引embedding与查询embedding分开。

按第12.6节在输出后用实际原文与官方参考作AI辅助评价。看核心事实、条件和比较是否答全、引用是否支持；区分材料未取得、取得后丢失、准备遗漏与最终遗漏。观察核心缺口有具体方向且额度未耗尽却提前收尾，以及把普通因果问升级为形式证明、正文已有解释却短答Unanswerable的情况。不要因没有read_context、缺用户未问的细节或措辞不同就判失败；合理纠正错误前提可以通过。未报告值不能编造或加强成不存在。自发direct_answer单列一致性，不替代claims主答评分。

十题各尝试一次或明确故障停止后结束，不改提示后补抽样、不换题、不追加追问，不为覆盖多轮阅读或超容量而再造实验。完成后只在D2第13节简要补记API入口改动、两个指定离线结果、五篇准备／十题运行／内容结果、跨题问题、用量及产物路径，更新issues.md与v3总规划入口，保留首批／N07／D1历史。新旧题目与解析版本不同，不声称准确率或稳定速度提升。不自动开始其他修复、加步数或新一批；不新增哈希／正文指纹、manifest、快照、审计、审核模型、检查清单或独立验证报告。保持D2最后一节为本提示词。
```

## 15. 后续局部修正规划：取消前置澄清关卡，统一取证充分性判断

制定日期：2026-10-27（Asia/Shanghai）。状态：**已实施并完成两个指定离线方法及 Q12／Q13／Q15 各一次真实复测**；实现与结果见第 15.7.1 节。用户最新决定取代此前“放宽前置澄清”的建议：参考本地 RAGFlow Agentic RAG，直接取消独立的前置澄清关卡，保留多轮理解与检索规划。本批只处理这一处流程调整和探索／准备充分性规则统一；第 14 节为已完成批次的历史提示，本次实施使用第 16 节。

### 15.1 已有问题与修正目标

| 问题 | 已有证据 | 本次目标 |
|---|---|---|
| Q15 在结果检索前要求用户指定任务／数据集／指标 | [原记录](../../archive/run_logs/d9/agent_20261027_125218_490658_f71ff8c4b253.json)中，前置理解已收到所选单篇论文的标题及摘要正文块 `p1_c1`，却返回澄清。只发生 1 次聊天、0 次查询 embedding／重排，没有进入实验结果的搜索或阅读；不是论文未入库，也不是完全没有见过 chunk | 前置阶段只理解原问和规划检索，不再通过 `clarification_question` 阻断正常问答。论文中的任务、数据集、指标和结果应交给取证流程查找，多组设置可以分别回答 |
| Q12 核心语言／方向仍缺，却认定准备充分 | [原记录](../../archive/run_logs/d9/agent_20261027_125058_079375_0e65bdf59626.json)已经说明缺少 MultiUN 的具体语言及方向，仍 `answerable=true`；还有 3 步，目录存在 Setup／Main Results 线索 | 原问所问范围内的必要并列项属于核心事实，不能以“已有一些相关事实”替代覆盖；有具体方向和额度时继续取证，不把官方某个参考的固定计数写成生产规则 |
| Q13 漏掉一项相关分析，并偏移对原问的理解 | [原记录](../../archive/run_logs/d9/agent_20261027_125128_091596_d3bb34544a28.json)给出 self-similarity／intra-sentence similarity，缺 maximum explainable variance；已有正文含方差分析线索，仍 `answerable=true`。同时将实验提问理解成未来实验提案，以没有专门的 proposed 清单收束 | 按原问的通常含义和论文上下文判断；保留所问关系下的必要并列实验，不能擅自增加“未来提案”或“专门列成清单”的条件 |

三题及官方参考只用于说明问题和事后评价，不把题号、标准答案、预期语言、实验名称或 chunk 定位写入业务提示及检索参数。Q13 的 `direct_answer=Unanswerable` 保留为历史表现，本批不另改短答字段协议。

### 15.2 直接采用 RAGFlow 的部分与必要适配

以用户本地 `E:/project/ragflow` 当前 Agentic RAG 路径为准，不修改该仓库。

| 来源 | 采用的行为 | 本项目适配 |
|---|---|---|
| [Agentic 入口](E:/project/ragflow/internal/service/chat_pipeline.go:285)、[用户问题进入会话](E:/project/ragflow/internal/agentic_rag/agent.go:523) | 用户问题进入 Agent；这一路没有本项目这种独立的前置澄清判定和早退关卡 | 删除当前前置阶段的澄清输出职责及 runtime 早退；沿用当前理解／规划调用，保留原问、多轮历史、来源范围与版本配对 |
| [检索与停止规则](E:/project/ragflow/conf/agentic_rag.yaml:40) | 获取并消费证据，证据能回答原问后停止；新阅读不再改变答案可作为停止信号 | 将同一充分性口径用于探索动作和准备判断。正文已经支持回答时允许停止；有核心缺口和具体线索时继续搜索／阅读 |
| [搜索定位与深读的区别](E:/project/ragflow/conf/agentic_rag.yaml:33) | 定位信息不能代替原文证据 | 本项目搜索本来就能发送正文，已发送正文可以直接使用；只有候选位置或目录不能作证。不机械要求每次搜索后再调用一次 `read_context` |

本次不采用 RAGFlow 的 compiled claims 直接回答快路，论文回答继续走现有“搜索／阅读 → 准备 → 最终生成”。`decision_judge` 属于段落过滤，本次不接入；也不把 RAGFlow 的主循环描述成具有额外的整题完整性裁判。

### 15.3 改动一：取消前置澄清，保留理解和检索规划

主要修改 [conversation.py](../../paper_assistant/conversation.py:76)及 [d9_runtime.py](../../paper_assistant/d9_runtime.py:168)，同步处理直接依赖这些字段的构造和测试样例。

- 前置调用只做问题理解、必要指代补全和 `planned_queries` 规划，不回答论文问题，不再要求模型输出 `clarification_question`。
- 首问继续由程序保存用户原文作为作答目标，不由前置模型改写。多轮只使用已有历史补足能够确定的指代；无法可靠消解时，保留原问及实际历史进入正常流程，不猜测用户指的是哪个对象，不扩展问题。
- 删除当前澄清字段的读取／回填，以及 `standalone_question` 与 `clarification_question` 必须二选一的旧校验。保留当前 JSON、非空问题、版本配对和来源范围所需校验，不另造新字段或兜底判定器。
- 删除 runtime 根据澄清输出返回 `needs_clarification`／`clarification_required` 的早退分支，直接衔接原有正常核心。前置理解／规划仍只用已有一次调用，不增加模型轮次。
- 同篇论文含多组实验、多篇论文存在可比较对象，均可按原问检索后分别组织；不再强迫用户先选定论文中可以查得的数据集、指标或任务设置。若正常流程仍不能确定必要对象，沿现有回答／缺口协议说明具体不足，不臆造对象或事实，不增加后置澄清状态机。
- `prepare_conversation` 被普通固定流程共用的调用点及 [固定实验上下文](../../paper_assistant/fixed_evidence.py:122)按新返回结构作必要适配，固定材料流程仍保持自己的取证边界。现有页面、导出和会话历史对旧 `needs_clarification` 记录的读取展示保留；旧日志不改写，不为停产这一状态清理整个展示层。

### 15.4 改动二：探索与准备使用同一充分性规则

主要整理 [agent_prompt.py](../../paper_assistant/agent_prompt.py:150)中的 `FACT_PREPARATION_RULES` 及实际探索规则。探索提示本来就包含准备规则，应合并／替换重复或冲突段落，不把相近长警告叠加到多个位置。

共同判据如下，实施时按当前提示语言融入已有职责：

1. **对照原问判断。** 用本次请求实际保留的原文判断所问对象、关系、必要条件及并列项是否覆盖；主题相关、工具成功、新增 chunk 或 facts 数量都不代表足够。
2. **核心缺口必须继续处理。** 原问所问范围内的必要语言／方向、实验、比较对象或结果尚缺，且已有具体搜索／阅读方向及额度时，探索阶段继续取证；准备阶段返回 `answerable=false`，在已有 `missing_information` 中写明具体缺失，交给下一轮工具决策。
3. **可选补充不阻断回答。** 原问核心已经有依据，缺少未要求的额外指标、背景、精确计数或全篇清单时，可以 `answerable=true`。重点替换当前“unasked complete inventory／exact count”的宽泛措辞：它只免除原问之外的盘点，不免除原问所问范围内的必要并列项。
4. **不擅自加强提问。** 普通因果问不升级为形式必要性证明；实验提问结合论文上下文理解，不自动升级为未来实验提案，也不要求作者另列同名标题。用通用语义规则处理，不做关键词分类或逐题特判。
5. **充分时允许停止。** 当前原文已覆盖原问即可准备，不强制阅读、增加步骤或耗尽额度。一次阅读没有新增材料本身既不证明充分，也不证明必须继续；继续与否取决于核心缺口及剩余具体线索。
6. **确实无法补足时沿用现有收尾。** 已无可靠方向或已到额度，保留已支持事实和具体缺口，进入现有最终生成；不把无依据的事实改写为已知，也不为了收尾把 `answerable=false` 改为 true。

当前 [agent.py 的准备路由](../../paper_assistant/agent.py:733)已经支持 `answerable=false` 且有额度时进入 `gap_evidence_decision`，并支持无方向后的正常收尾。本次沿用该机制，不增加事实数量阈值、缺口分类 schema、额外审核模型或新的状态流转。最终阶段继续使用成功准备请求保留的原文，不改回答／引用协议；如共享规则进入固定材料提示，保留它“不能追加检索”的既有约束。

### 15.5 实施后的指定离线验证

本次写文档不跑测试。后续实施后只调整并点选两个现有方法，全部使用本地材料／mock：

1. `scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved`：把原先“首问／多轮返回澄清且零检索”的场景改成新行为。覆盖单篇性能问题不需先指定数据集或指标、原问与版本范围保留并进入正常核心；多轮指代不明不猜对象，交给正常流程说明不足；保留 `answerable=false → 补证 → 新准备 → 最终`、充分后正常最终生成及无方向／额度收尾的已有覆盖。新运行不再产出前置澄清状态，旧报告读取场景保留。
2. `scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question`：确认统一规则进入实际探索／准备消息，必要并列项与可选补充的边界一致；原问、原文、引用范围和准备到最终的衔接继续保留。只在现有方法中补必要场景，不新增独立检查器或通用测试框架。

```powershell
python -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question
```

mock 验证规则发送、接口和执行路由，不代替真实模型的内容效果评价。只有方法失败或有具体跨模块影响时才扩大到直接相关方法；未改的页面／历史展示和已有通过结果复用。不跑整模块、全量回归或额外连通性请求。

### 15.6 修改完成后只复测 Q12、Q13、Q15

用户已追加要求：两处修改和第 15.5 节指定离线方法通过后，执行三道题的真实复测。这里的“失败题”指 **Q12／Q13 的部分通过及 Q15 的澄清未交付**，不是运行异常；原批次运行失败为 0。本次写规划不发请求，后续按第 16 节执行时包含以下三题的正常真实调用。

- 固定顺序为 **D2-Q12 → D2-Q13 → D2-Q15**，每题只执行一次完整 `d9_runtime.run_question(..., mode="agent", library_mode=True)`，均为独立新会话、空会话历史。正常额度内网络重试／修复仍属于该次流程；不追加追问、换题或改提示后补跑，不重跑其余七题、首批十题、N07 或 D1。
- 从 [原批次 input.json](../../artifacts/v3/d2-qa-dev-next-ten-20261027/input.json)取三题原始 question／question_id 和对应版本配对，保留原字串。继续使用第 13 节已有 API ready 版本：Q12 用 V1、Q13 用 V2、Q15 用 V3；不重新下载、解析或入库，不换论文版本。既有配对不可用时记录该题未执行及原因，不自动重建索引。
- 只向业务入口传原题、版本配对和普通完整回答要求；本节诊断、参考答案、期待项和预期 chunk 不进入模型、检索规划或工具参数。保持当前模型、容量、输出／超时、五步／五次取证及共享重试／修复配置，不为使三题通过加额度、强制阅读或缩成最短短答。
- 单独使用 `artifacts/v3/d2-clarification-sufficiency-rerun-20261027/`，保存普通 `input.json/results.json`；逐题完整记录沿用 `archive/run_logs/d9/`。会话／提交 ID 使用本批新前缀并带原题号。复用 `tmp/d2_qa_dev_next_ten_run.py` 的窄调度方式，必要时新增只包含三题的入口，不运行旧十题 runner 的原 main、不建设新框架。已有本次复测尝试则保留并只接续未尝试题，中断或内容未改善也不自动重开同题。
- 结果记录实际状态、停止原因、日志路径、聊天／查询 embedding／重排／重试／修复、tokens 和耗时。三题正常前置规划、Agent、准备、最终及相关查询 embedding／重排属于此次复测；不另发连通性、固定证据、双模式评分或 judge 请求。

内容评价在生成之后对照实际原文与官方参考完成，与原始三题记录逐题比较：

| 题目 | 本次重点 | 不能算作修复成功的情况 |
|---|---|---|
| Q12 | 是否回答所问的具体语言及翻译方向，包括 MultiUN 对应内容；核心仍缺且有线索／额度时是否继续取证 | 只说“四种语言／以英语为枢轴”，仍遗漏所问的具体语言／方向，却判充分；不以某条官方参考的固定总数作为唯一答案形式 |
| Q13 | 是否覆盖所问的相关实验／分析，包括 maximum explainable variance；是否按论文实际实验理解原问 | 仍只给两项分析，或额外要求未来实验提案／单列清单；不把强制多搜或调用阅读本身当作通过 |
| Q15 | 是否进入正常取证并给出 BERT 性能，数据集、任务设置、指标和值归属正确 | 仅取消澄清状态却没有交付性能结果，或把不同设置的数值混用；不只凭状态为 answered 判通过 |

分别记通过／部分通过／内容未交付／运行失败，保留仍存在的具体问题，不在复测过程中继续修改实现。沿现有记录区分核心内容是否改善及取证停止是否合理，三题结果不外推为新十题准确率，不覆盖第 13 节历史成绩。

### 15.7 交付与停止位置

本批后续执行顺序为：两处局部实现 → 两个指定离线方法 → Q12／Q13／Q15 各一次真实复测 → 简要记录。真实复测遇到影响后续的共享故障时保留已尝试范围、用量与未执行原因并停止；不为凑齐或获得更好答案重复调用。

保持当前模型、上下文容量、输出／超时及五步／五次取证配置，沿用 D2 已读历史和完整请求容量管理；不恢复旧 8192 证据窗口、8000 字符或累计八块截断。解析入库、重排、短答协议、其他表达问题及对话历史容量不并入本批。除两处修改所需的直接调用适配外，不增加新阶段、新模型、哈希、审计或无关重构。

完成后在本节简要补记实际修改、两个方法结果、三题真实复测评价／用量和普通产物路径，不另建验证报告。下一节保留为最新实施提示词；历史计划与结果保留原样。

### 15.7.1 实际实施与结果（2026-10-27）

**实现：**`conversation.py` 首问不再返回或要求 `clarification_question`，只保留原问、理解和 planned_queries；多轮只采用可靠的 `standalone_question`，返回 null 时保留原问，不猜对象。`d9_runtime.py` 删除澄清字段读取和 `needs_clarification` 早退，直接进入正常核心；旧日志／会话历史读取保留。`fixed_evidence.py` 移除新上下文的空澄清字段。`agent_prompt.py` 合并探索与 `FACT_PREPARATION_RULES` 的充分性口径：原问范围内的对象、关系、条件和必要并列项属核心；未要求的全篇盘点／精确总数／额外指标不阻断；普通因果不升级形式证明，实验问不升级未来提案；充分时允许停止。`AUTONOMOUS_PROMPT_VERSION` 与 `FIXED_PREPARE_PROMPT_VERSION` 更新为 `v2.20-shared-sufficiency-v1`。

**离线：**两个指定方法通过（最后合并运行 2 tests OK，12.841 秒，mock，无真实模型／embedding）：`test_original_query_and_complete_pairs_preserved` 覆盖性能问题正常进入检索、指代不明不猜对象、`answerable=false → gap → 新准备 → 最终`、充分后生成及无方向收尾；`test_model_messages_show_only_selected_content_and_data_question` 验证共享探索／准备规则实际进入消息、必要并列项与可选补充边界，以及原问／原文／引用衔接。

**三题真实复测：**顺序 Q12→Q13→Q15，各一次、独立新会话；3/3 completed、3/3 answered、0 运行失败。内容评价：**2 通过、1 部分通过、0 失败**。

| 题号 | 结果 | 评价 |
|---|---|---|
| D2-Q12 | 通过 | 不再只说四种语言；补齐 Europarl 三组及 Fr→Es／De→Fr／Ro→De，MultiUN 明确 English pivot、Ar／Es／Ru 和六个互译零样本方向。首次准备 `answerable=false`，补证后第二轮才 true；未重复旧提前收尾。 |
| D2-Q13 | 通过 | 覆盖 self-similarity、intra-sentence similarity、maximum explainable variance，并明确是论文实际分析，不再要求未来提案或同名清单。 |
| D2-Q15 | 部分通过 | 已进入正常检索，给出 NUBES-PHI／MEDDOCAN 任务设置、0.979 detection recall、相对差异和 MEDDOCAN 0.3 F1 差距；但 BERT 完整绝对 precision／F1 表值仍未取得，最终自己说明 Tables 5／8 未展示。相对旧“澄清未交付”是改善，但性能数值仍不完整，记部分通过；它也是本轮唯一仍可归为“有具体方向、额度未尽却最终 `answerable=true`”的题。 |

**用量：**16 次聊天请求、340,810 tokens、报告耗时合计 117.172 秒；查询 embedding／重排各 4 次；0 网络重试、0 修复；29 条主张、18 个 evidence sources。三题 context 均 `max_chars=None`、无 `max_tokens`，展示 7／21／13 块；旧证据截断未恢复，1M 完整请求裁剪未触发。3/3 题都有 `direct_answer`，只单列观察。

**产物：**[input.json](../../artifacts/v3/d2-clarification-sufficiency-rerun-20261027/input.json)、[results.json](../../artifacts/v3/d2-clarification-sufficiency-rerun-20261027/results.json)；原生 JSON／Markdown 在 `archive/run_logs/d9/`，路径见 results。原第 13 节三题结果保留为基线，不覆盖、不重跑其他题；不据此外推整批准确率或速度。

## 16. 给 DeepSeek 的两处局部修正与三题复测提示词

```text
请读取 D:/course/paper-research-assistant/AGENTS.md、docs/v3/d2-plan.md 第13、15节及 docs/v3/issues.md 的已有相关记录，执行第15节两处局部修正：取消独立前置澄清关卡；统一探索和准备阶段的证据充分性判断。修改及两个指定离线方法通过后，按第15.6节只真实复测Q12、Q13、Q15，每题一次。第15节已经包含用户最新决定，取代“只放宽澄清”的旧建议。保留工作区已有修改，不执行第8／11／14节历史任务。

参考用户本地 E:/project/ragflow 的 Agentic RAG 当前实现：internal/service/chat_pipeline.go:285、internal/agentic_rag/agent.go:523 将问题交给 Agent，conf/agentic_rag.yaml:40-44 要求取证后依据原问判断是否可以停止。能沿用的行为和规则直接采用，必要适配只为接入本项目已有接口。保留当前论文回答的“搜索／阅读→准备→最终生成”，不引入 compiled claims 直接回答快路，不接入 decision_judge。

第一处主要改 paper_assistant/conversation.py 和 d9_runtime.py。保留现有一次前置理解／规划调用、planned_queries、多轮历史、版本配对和来源限制；前置阶段不再负责要求用户澄清。删除 clarification_question 的输出要求、读取回填和问题／澄清二选一校验，删除 runtime 据此返回 needs_clarification／clarification_required 的早退。首问作答目标继续由程序原样保存；多轮只补确定的指代，无法消解时保留当前原问及实际历史进入正常核心，不猜对象、不增加问题。任务、数据集、指标及多组实验交由取证查明并按设置回答；正常流程仍无法确定必要对象时沿现有缺口协议说明，不新增后置澄清状态机。直接调用方和 fixed_evidence.py 的空字段构造按需同步适配。保留已有 JSON／问题／版本／来源所需校验，不新增判定层。旧日志和页面／导出／会话历史的旧澄清记录读取展示保留，本批只停止新流程产生该状态，不清理整个展示层。

第二处主要整理 paper_assistant/agent_prompt.py 的实际探索和 FACT_PREPARATION_RULES。探索本来包含准备规则，替换冲突和重复文案，不追加多套长规则。共同按原问及实际保留的原文判断：核心对象、关系、条件和必要并列项未覆盖，有具体取证方向和额度就继续；准备发现这类缺口须 answerable=false，missing_information 直接写缺什么。主题相关、工具成功、新 chunk 或事实数量不等于充分。收窄旧的 unasked complete inventory／exact count：用户未要求的全篇盘点可省，原问所问范围内的必要语言／方向／实验／比较项不能当可选。核心已经覆盖时可以 answerable=true，未问的背景或额外指标不阻断回答。普通因果问不升级为形式证明，实验提问不自动变成未来提案或必须单列同名清单。正文已足够时允许停止，不强制 read_context 或耗尽额度；没有可靠方向或到额度时保留支持事实与具体缺口，沿现有协议收尾。

agent.py 已支持 answerable=false 后进入 gap_evidence_decision 继续补证，优先复用，不重写状态机，不加裁判、缺口 schema、词表或事实数量阈值。最终仍承接成功准备的原文请求，不改 direct_answer／引用协议；共享规则如影响固定材料流程，保留它不得追加检索的边界。Q12／Q13／Q15 及参考答案仅供理解缺陷和事后评价，不能把题号、预期答案、实验／语言清单或 chunk 定位写入生产提示、规划或检索参数。

实施后只调整并运行两个现有方法：scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved，以及 scripts.check_generation.ContextChecks.test_model_messages_show_only_selected_content_and_data_question。将前一个方法中的旧澄清早退断言改成新正常流程，覆盖性能问题进入检索、指代不明不猜对象、核心缺口后继续取证和充分后最终生成；第二个检查实际探索／准备规则及原问／原文／引用衔接。离线方法使用mock，不调用真实模型或embedding。只有失败或具体跨模块影响才扩大相关方法，不跑模块／目录／全量回归，不为凑数新增测试。更新实际受影响的既有提示版本字段即可，不增加版本管理机制。

离线通过后按Q12→Q13→Q15顺序真实复测，仅这三题，每题一次d9_runtime.run_question(..., mode="agent", library_mode=True)，独立新会话、空历史，输出普通完整回答与引用。原字串、question_id和本地paper_id／parse_revision从artifacts/v3/d2-qa-dev-next-ten-20261027/input.json对应记录取得，复用第13节V1／V2／V3已ready的API版本，不下载解析、不重新入库或换版本。本任务包含这三题正常前置规划、聊天、查询embedding、可选重排、准备、最终和原额度内重试／修复。只向业务流程传原题和版本，gold、问题诊断、预期实验／语言／数值及chunk不进入模型消息、规划或检索参数；不强制工具、不加额度、不改成最短答案／F1协议。不要重跑其余题或发额外连通性、固定证据、双模式评分及judge请求。

本次复测使用artifacts/v3/d2-clarification-sufficiency-rerun-20261027/普通input.json/results.json，原生完整日志继续保存到archive/run_logs/d9/。复用已有窄调度逻辑，必要时只建三题入口，不能直接运行旧十题main。使用本批新会话／提交前缀；已有尝试不重跑，只接续未尝试题，失败／中断也不自动当新题重开。保留原批次结果作为基线，不覆盖历史、不改提示后补抽样、不追加追问或替代题。共享故障阻断后续时记录已尝试范围、实际用量和未执行原因后停止。

生成后按第15.6节用实际原文和官方参考逐题评价：Q12具体语言／方向是否补全，Q13相关分析是否覆盖且不再升级为未来提案，Q15是否交付设置归属正确的性能数值。分别记录内容和运行结果，不以answered、引用有效或调用更多工具代替通过；内容未改善如实保留，不在这轮继续修再跑。保存停止原因、日志路径、真实请求／tokens／耗时，与旧三题逐题比较，不外推为整批准确率。

保持当前模型、容量、输出／超时和取证额度，不恢复D2已取消的旧证据截断。完成两处修改、指定离线方法与这三题各一次复测后，按第15.7节简要补记实际改动、离线结果、复测评价／用量及产物路径，保留历史结果；不生成独立验证报告、哈希、审计、审核模型或其他无关改动。完成后结束，保持D2文末为本提示词。
```
