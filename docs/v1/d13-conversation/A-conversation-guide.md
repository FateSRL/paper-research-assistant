# 连续对话 A：会话与历史日志、学习入口及参考答案

执行日期：2026-10-09（Asia/Shanghai）。**A 已完成实现及针对性离线验证。** 本日志记录会话与页面接入；追问准备和两模式回答见 [B 日志](/D:/course/paper-research-assistant/docs/v1/d13-conversation/B-followup-guide.md)，后续完成的回查问题展示与导出增强见 [C 日志](/D:/course/paper-research-assistant/docs/v1/d13-conversation/C-citation-export-guide.md)。

## 1. 工作日志

[app.py](/D:/course/paper-research-assistant/app.py) 在已有 `session_state` 中保存 `d9_conversation_id` 和 `d9_conversation_versions`。所选完整 `(paper_id, parse_revision)` 集合变化时开启新会话；只调整选择顺序或问答模式继续使用原会话。侧边栏增加“新对话”按钮，旧提交记录、回答和原文回查继续保留。

发送问题时，现有提交记录同时固定 `conversation_id` 和 `conversation_history`，随该次提交传给 `d9_runtime.run_question()`。重绘、切换控件和下载只读取保存的报告，已消费的提交不重新选择历史或重新调用问答。

[select_conversation_history()](/D:/course/paper-research-assistant/paper_assistant/conversation.py) 从同会话中选择最近 3 个有效回答、证据不足回答或澄清交互；故障和未完成记录不作为知识回答。历史保留轮次、原问题、完整问题和原顺序的 `claims`，每条保留 `claim`、`basis`、`citation_ids`；澄清交互保留 `clarification_question`。结论的列表位置从第 1 条起解释“刚才第二条”。历史不包含证据原文、检索轨迹或技术用量。

历史以 `json.dumps(history, ensure_ascii=False)` 的长度计入 4000 Python 字符上限，超限先删除较早完整轮次；若最新单轮仍超过上限，也不传入残缺历史。保留下来的引用 ID 供 B 在明确针对旧原文时重新取回本轮证据，ID 自身不授予本轮引用资格。

页面优先展示 `user_question`，兼容没有该字段的旧报告；B 返回 `needs_clarification` 时展示澄清问题，用户在同会话中回复后继续。引用仍从被点击回答的原报告映射读取。

只就地扩展既有 `PageChecks.test_saved_mode_query_pairs_survive_control_changes_and_reruns`，覆盖同会话历史、选择集合与版本变化、新对话、有限窗口、澄清续答、旧回答引用以及重绘／下载不重跑。该方法离线通过，与 B 的两个既有方法一同执行；B 的运行时方法初跑失败后单独修复重跑，页面方法结果直接复用。三个方法最终均通过，实际结果见 B 日志；本任务未请求真实模型、embedding 或重排服务。没有新增哈希、审计、保护快照、通用校验层或测试脚本。

## 2. 怎样学习：约 15 分钟

1. 在 `app.py` 阅读 `_ensure_conversation()`、`_new_conversation()`，追踪论文版本集合和会话 ID 如何对应。
2. 阅读 `_queue_submission()` 与 `_execute_submission()`，区分“当前控件状态”和“本次已经固定的提交参数”。
3. 阅读 `select_conversation_history()`，比较历史结论和实际原文证据的职责；随后查看已有页面测试方法中的同会话、切版本和澄清续答场景。阅读这些离线材料无需请求模型。

## 3. 问题与答案

**为什么只换问答模式不新建会话？** 固定 RAG 和 Agent 处理的是同一组论文中的同一主题。模式只决定当前轮检索流程，不改变用户正在讨论的论文对象。

**为什么保留结论顺序和依据类别？** “解释刚才第二条”需要能定位上一轮的第 2 条结论；`basis` 同时区分论文事实、模型知识与分析，避免把历史中的分析误当作已经核实的论文事实。

**为什么历史引用不能直接作为本轮引用？** 历史引用只说明上一轮用了什么原文。当前轮需要由 B 重新取回相关片段并纳入本轮展示证据，之后继续使用现有引用检查和当轮来源映射。
