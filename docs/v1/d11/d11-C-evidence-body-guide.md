# D11 C：正文获取工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**C 已完成实现，D11 A–C 完成。** 仅确认本轮实现和离线流程；没有新测真实模型效果。

## 1. 实际完成什么

新增 [read_evidence_context()](/D:/course/paper-research-assistant/paper_assistant/evidence_reading.py:29)。它保留检索锚点，在本地已有原文中读取必要邻接正文：

- 对摘要、常见节标题或短编号标题，查看同页后续最多 3 个 chunks，补读至多 2 条长度至少 80 字符的正文；遇到新节标题或跨页立即停止。
- 对普通正文，只补读同一 `segment_id` 的后续重叠连续块，不顺着任意短片段取旁边内容。
- 对摘要限定问题，只补读已有 Registry 核定的范围。
- 姓名等原始候选不会统一过滤；空证据保持空上下文。

Agent 在首轮和最终合并后使用这一步。首轮最多 5 条、最终最多 8 条和 8000 字符上限保留，因此本地读到的片段只有进入最终展示后才能用于引用。最终补查是否得到新证据，也按实际阅读后的展示 ID 判断。

原始检索候选及其 score 不重写。本地邻接片段在上下文中沿用检索锚点分数，`reading_origins` 保存锚点和 `score_basis=anchor_similarity`，说明这不是一次独立向量检索的相似度。实际展示包含原始 chunk ID、原文及来源，复用既有引用定位流程。

## 2. 实际验证与观察

扩展并运行了 3 个既有测试方法，没有新建测试方法。阅读窗口和空上下文处理调整后，最终版本重跑这 3 项，结果 **Ran 3 tests / OK，0.256 秒**：

| 方法 | 覆盖的改动 |
|---|---|
| `scripts.check_agent.AgentFlowChecks.test_direct_answer_is_one_search_and_one_decision_then_real_pdf_validation` | 标题命中后读到正文，沿既有来源回查发布；仍一次检索和一次决策 |
| `scripts.check_agent.AgentFlowChecks.test_retry_keeps_raw_query_original_question_scope_and_fixed_top_five` | 两次消息都有论文信息，原问题/范围/预算保留，作者候选仍可用 |
| `scripts.check_scoped_answering.RealFirstRetrievalChecks.test_ordinary_question_with_registry_keeps_body_evidence` | 使用真实核定摘要字段和原文，普通问题仍可读正文，范围没有变成只许摘要 |

运行方式为现有 `.venv` Python 的 `-B -X utf8 -m unittest` 加上上述 3 个方法全名。模型响应和搜索使用模拟资源；没有真实模型或 embedding 请求。未跑全模块/目录回归，未新增哈希扫描、审计或独立验证报告。

另用已保存的 [旧“介绍一下这篇论文”失败候选](/D:/course/paper-research-assistant/archive/run_logs/d9/fixed_rag_20261007_132630_740342_c522bc1ad3e0.json) 只读回放当前本地正文阅读：原 5 条候选经阅读后形成 5 条展示、2702 字符，顺序为 `p1_c11`、`p1_c12`、`p1_c8`、`p1_c9`、`p1_c10`，包含 3 条邻接读到的正文。没有重新执行 embedding 或模型，旧结果未改写。这项观察说明能从已命中的标题取到正文，**不代表已获得新的成功答案或准确率**。

## 3. 怎样学习：约 25 分钟

1. 读 `evidence_reading.py` 的 `_heading()`、邻接窗口和 `continuation` 判断，解释为什么标题与普通正文使用不同读取条件。
2. 看 `select_context()` 的调用：补读后仍需选择有限展示，未展示原文不会自动变成可引用证据。
3. 到 [agent.py](/D:/course/paper-research-assistant/paper_assistant/agent.py:175) 和 [最终阅读位置](/D:/course/paper-research-assistant/paper_assistant/agent.py:371)，分别追踪首轮 5 条和最终 8 条。
4. 对照旧失败候选与上面的回放结果，说明“本地读到了正文”和“模型已经完整答对”为什么是两个结论。无需重复执行真实请求。

## 4. 关键问题与答案

**为什么命中 `Abstract` 仍可能答不出？** 标题只说明章节存在，没有研究问题或方法细节。读取它后面的实际摘要正文，才有可支撑回答的内容。

**邻接阅读算又检索了一次吗？** 不算。它按现有定位读本地原文，没有新的 embedding 或搜索请求，不增加模型调用。一次补查上限仍适用。

**D11 后还能返回证据不足吗？** 能。D11 只改善论文信息、补查和取证，当前仍严格依据原文。D12 才调整两模式的不足分支、回答结构、依据标记和展示；D13 混合检索、D14 首次验收也尚未实施。
