# D12 C：展示与导出工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**C 已完成实现，D12 A–C 完成，下一步 D13。** 本日志记录页面与已有导出改动，以及实际离线验证。没有新测真实模型效果。

## 1. 实际完成什么

[Streamlit 页面](/D:/course/paper-research-assistant/app.py)已显示回答整体依据组成，模型知识或分析条目另行标注。真实论文引用继续通过点击句子/引用弹窗查看原文和位置；无引用的模型知识、分析直接显示内容，不创建空的引用弹窗。有引用的分析显示“分析前提引用”，明确引用支撑前提。

已有 [固定 RAG Markdown 导出](/D:/course/paper-research-assistant/paper_assistant/answer_export.py)与 [Agent 导出](/D:/course/paper-research-assistant/paper_assistant/agent_export.py)已保留逐条“论文原文／模型知识／分析”标签，分析引用同样标为前提。两者复用相同标签定义；结构化运行记录携带 `basis`、`evidence_status` 和可选限制原因，旧记录缺省依据时沿用原来的论文原文含义。旧资料不足记录仍能显示和导出。

页面使用方式保持现有入口：选择论文与固定 RAG/Agent 模式后提问。正常证据不足时查看实际回答与依据标记；有论文引用的句子可点开核对原文，下载问答时标记一并保留。本阶段不重启服务或开展真实模型演示。

## 2. 实际验证

首次执行调整后的 **4 个相关现有方法**，结果 **Ran 4 tests / OK，2.578 秒**。本次同时涉及两种核心问答、来源范围和页面/导出，因此各取一个方法覆盖实际调用链；未按模块或目录运行。随后修复双模式外层的来源不足短路，将同一个来源方法扩展到 `run_paired_case()`，只重跑这一方法，**Ran 1 test / OK，0.125 秒**；其余 3 个通过结果复用。最终仍为 **4 个不同方法通过**，不是 5 个。

| 方法 | 覆盖行为 |
|---|---|
| `scripts.check_rag.RAGChecks.test_no_hits_and_character_budget_empty_context_answer_without_paper_sources` | 无命中/字符预算空仍回答；混合原文、知识、分析的引用回查与发布 |
| `scripts.check_agent.AgentFlowChecks.test_duplicate_retry_results_still_produce_useful_final_answer` | 重复候选、补查无命中、重复查询后仍做最终回答；共享调用预算继续生效 |
| `scripts.check_scoped_answering.SyntheticSourceFlowChecks.test_unknown_unverified_scope_answers_without_search_or_paper_citations` | 两模式来源未核定时 0 搜索、1 次聊天，知识回答不附论文引用；扩展 paired 调用后确认无共享检索记录、embedding 0、两核心各 1 次聊天并 `answered` |
| `scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations` | 两模式五类状态（含历史不足）、原文/分析前提弹窗与无引用内容呈现；两种 Markdown 导出依据 |

首次 4 方法运行命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest scripts.check_rag.RAGChecks.test_no_hits_and_character_budget_empty_context_answer_without_paper_sources scripts.check_agent.AgentFlowChecks.test_duplicate_retry_results_still_produce_useful_final_answer scripts.check_scoped_answering.SyntheticSourceFlowChecks.test_unknown_unverified_scope_answers_without_search_or_paper_citations scripts.check_d9_e_page.PageChecks.test_two_modes_five_terminal_states_and_full_citations
```

外层来源不足调用修复后，仅重跑来源方法：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest scripts.check_scoped_answering.SyntheticSourceFlowChecks.test_unknown_unverified_scope_answers_without_search_or_paper_citations
```

使用模拟搜索/聊天和临时来源；页面覆盖通过现有离线页面方法完成，未做浏览器视觉验收。真实模型/embedding 请求为 0，没有新增哈希、审计、快照或独立验证报告，没有整批 D10 重跑或 D14 验收。文档本身不跑测试，其他未执行的检查不列为通过。上述结果确认控制流和呈现，不代表新模型准确率；D10 历史成绩仍归属原阶段。

## 3. 怎样学习：约 20 分钟

1. 读 `app.py` 的 `render_report()`：从回答 `claims` 追踪依据标签和引用弹窗，理解两者各自表达什么。
2. 读 `answer_export.py` 的 `render()` 和 `agent_export.py` 的 `render_agent_run()`：比较页面与下载的标记是否保留相同含义。
3. 看一份已有结构化记录，说明 `status=answered`、条目 `basis` 和论文引用来源三个字段为何不能互相替代，不需要再次运行问答。

## 4. 关键问题与答案

**为什么有答案不代表论文支持了全部答案？** `answered` 描述生成流程成功且有内容，`basis` 描述每条内容的依据。模型知识可以形成有用回答，但不能计入论文原文支持率。

**点击模型知识句子会弹出论文原文吗？** 不应显示任意论文来源。没有引用时只呈现该内容的依据；有引用的原文事实或分析前提才可回查对应 chunk 和页码。

**接下来要重跑整批评测吗？** 当前仅验证 D12 的实际改动。下一阶段 D13 完成混合检索，D14 再使用原 20 条冻结题做一次双模式首次最终验收，并分别评价回答有用性和论文原文支持。
