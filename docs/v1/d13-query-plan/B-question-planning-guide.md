# B：前置问题理解与规划日志

完成日期：2026-10-12（Asia/Shanghai）。B 已完成实现和针对性离线验证，范围来自 [A–C 执行计划](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/d13-query-plan-ABC-plan.md)。C 尚未实施。

## 实际交付

`conversation.py` 在同一次准备调用中理解当前问题、补全追问、处理歧义并生成 `planned_queries`。每条包含具体 `query` 和当前所选论文的 `selected_versions` 配对。提示要求简单事实一条查询，机制、比较、概览和多部分问题按独立信息需求拆解，结合论文主题及术语；跨论文比较按同一维度分别指定论文，不固定查询数量，不新增分类或规划修复调用。

`d9_runtime.py` 在统一页面请求（`library_mode=True`）的检索前调用准备，首问也执行一次；有历史时直接扩展原理解调用。复用 `load_paper_information()` 读取当前所选版本的标题与已有可用摘要背景，传入准备消息；没有生成摘要、增加缓存或元数据哈希。这些背景只用于规划，答案仍须使用本轮实际原文。

保留 `user_question`、`standalone_question`、`clarification_question` 和明确原文回查对应的 `referenced_evidence_ids`。对象不明确时保存澄清并停止检索。完整问题明确但计划缺失、为空、查询不可用或目标版本未被选中时，回退为该完整问题及全部所选版本的一条查询，不追加模型请求。整个理解调用失败时保留实际错误，不猜测指代对象。

来源限制从完整问题确定，放入会话上下文供后续子查询共享；当前问题的明确摘要限制若在补全中遗漏，会补回完整问题，既有来源处理继续执行。子查询无需重复写“摘要”才能保留限制。有效计划同时保存在本轮报告顶层及回答调用的会话上下文，JSON 历史与下载均保留计划。

统一页面首问通常增加一次准备请求，追问仍只使用原有的一次准备；请求与既有回答、补查及修复共用原 `ChatBudget`。CLI／对照实验保持原运行路径和调用策略。当前仍用完整问题执行现有单查询 Agent；C 才会消费多条计划、合并原文并综合回答。本项不证明多主题证据覆盖已经改善。

## 实际验证

只运行三个既有方法，合计 4.144 秒，全部通过：

- `scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved`：就地扩展首问单条／多条计划、标题和摘要输入、追问补全、歧义澄清、摘要限制、无效或越界计划单查询回退、JSON 历史与下载保存；确认当前检索及回答仍使用完整问题，计划回退不追加修复调用。
- `scripts.check_d9_e_runtime.RuntimeChecks.test_unfrozen_full_pair_is_zero_requests`：沿用临时本地论文与实际核心，更新首问准备响应，确认所选 ready 版本、新论文标题／摘要、正文与旧引用回查及原交互预算继续生效；未 ready 版本在请求前失败。
- `scripts.check_agent.AgentFlowChecks.test_format_repair_then_retry_then_bad_citation_does_not_send_fourth_chat`：沿用现有共享预算场景，确认一次准备生成计划仍计入原三次额度，明确旧引用恢复后才进入本轮证据，未明确引用的历史 ID 不自动授权。

测试使用临时合成论文、模拟检索和 SDK `MockTransport`；没有读取冻结验收题调优，真实模型、embedding、重排请求均为 0。没有测试失败，只有既有 PyMuPDF `fitz` 弃用提示。A 的页面代码在已通过验证后未再改动，其结果直接复用，没有全量回归、重复验证、独立验证报告、哈希或快照。

## 取舍与下一步

离线模拟确认接入、字段、范围与失败流程，不能证明真实模型拆解的语义质量。下一步只按 C 的既有计划执行子查询、合并完整原文并回答完整问题，同时记录真实查询与用量；目前不增加依赖式多跳、每个子问题独立答案或通用策略框架。
