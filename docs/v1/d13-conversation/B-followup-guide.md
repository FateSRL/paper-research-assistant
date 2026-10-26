# 连续对话 B：追问理解与两模式接入日志

执行日期：2026-10-09（Asia/Shanghai）。**B 已完成实现及针对性离线验证。** A 的会话与历史日志见 [A-conversation-guide.md](/D:/course/paper-research-assistant/docs/v1/d13-conversation/A-conversation-guide.md)；后续完成的完整回查问题展示与导出增强见 [C 日志](/D:/course/paper-research-assistant/docs/v1/d13-conversation/C-citation-export-guide.md)。

## 1. 工作日志

[conversation.py](/D:/course/paper-research-assistant/paper_assistant/conversation.py) 的 `prepare_conversation()` 接收当前问题和已固定的近期历史。无历史直接沿用原问题，不增加模型调用；有历史借用本轮 `RecordedLLM` 发起一次准备调用，生成 `standalone_question` 或 `clarification_question`，保留 `user_question`。准备只理解意图，不回答论文问题，不把历史推断补成论文事实。

[d9_runtime.py](/D:/course/paper-research-assistant/paper_assistant/d9_runtime.py) 在检索前接入准备步骤。对象含糊时返回 `needs_clarification`，保存澄清文本、已发生的聊天用量及既有运行记录，本轮不搜索、不请求 embedding 或重排、不生成论文答案。用户下一次输入结合 A 保留的原追问和澄清问题继续。准备的工具、输出格式或预算失败直接按实际错误返回，不新增准备修复循环。

固定 RAG 和 Agent 接收同一个完整问题，用于检索、来源范围判断和 `context.question`；回答及原有修复消息另外携带原问题和有限历史，支持结论编号追问、解释与表达调整。历史不进入 `allowed_citation_ids`。`source_scope.py` 的已有消息字段范围只补入 `conversation_context`，继续使用原来源判断和引用检查。

准备结果可选择用户明确追问的旧原文 ID，仅从历史中已有的相关 ID 选择；两模式从当前所选版本的实际原文块重取，并纳入本轮展示证据。恢复相关旧片段优先于检索片段，沿用初轮最多 5 条、Agent 最终最多 8 条及 8000 字符限制。最终引用继续由本轮真实原文和已有校验决定，不能直接引用历史回答。

准备、回答、Agent 补查后回答、网络重试及既有修复共用原 `ChatBudget`：最多 3 次聊天尝试、总时限 120 秒。补全后 Agent 用完三次时不发第四次请求。原有记录保存会话字段及准备消息／响应，现有 Markdown 导出增加必要的澄清展示；没有新建记录体系或新增依赖。

实际验证只运行计划中的 3 个既有方法：

- `scripts.check_d9_e_page.PageChecks.test_saved_mode_query_pairs_survive_control_changes_and_reruns`：通过，覆盖固定历史、会话切换、澄清续答、旧引用与重绘／下载不重跑。
- `scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved`：最终通过，覆盖首问兼容、两模式追问与澄清续答、原问题／完整问题一致性、固定 RAG 旧原文恢复、澄清导出及准备失败。初跑暴露既有来源消息字段未允许会话字段；补入该字段后只重跑此失败方法，0.492 秒通过。
- `scripts.check_agent.AgentFlowChecks.test_format_repair_then_retry_then_bad_citation_does_not_send_fourth_chat`：通过，覆盖准备实际计入共享三次预算、历史 ID 不自动授权和明确旧引用的原文恢复。

首轮 3 个方法运行 7.850 秒，页面和 Agent 方法已通过，其涉及路径未继续修改，直接复用结果。测试使用临时合成论文与 SDK `MockTransport`；真实模型、embedding、重排请求均为 0，没有运行全量回归或测量新准确率。没有新增哈希、审计、保护快照、通用校验层、测试脚本或独立验证报告。

## 2. 怎样学习：约 20 分钟

1. 阅读 `prepare_conversation()` 和 runtime 的 `conversation_preparation`，区分完整问题、澄清及失败三条路径。
2. 对照 `context.py` 的 `CONVERSATION_INSTRUCTION`、`restore_conversation_evidence()`，再看 RAG／Agent 接入位置，追踪历史如何帮助理解而不授权引用。
3. 阅读上面两个后端既有测试方法，观察准备调用、实际证据和共享预算；无需调用真实模型。

## 3. 问题与答案

**为什么回答模型还需要原追问和历史？** 完整问题解决检索对象；原追问和历史保留“第二条结论”“说简单一点”等编号和表达要求，使回答符合用户当前意图。

**为什么先澄清再检索？** 如果“它”可能指两个方法，直接检索会把错误对象带进答案。先请用户确定对象，下一轮再形成完整问题，澄清本身不冒充论文结论。

**准备是否有额外三次额度？** 没有。准备调用消耗同一轮的三次额度；补全、Agent 首轮决定和补查后回答正常合计三次，此后不再发起修复或第四次调用。
