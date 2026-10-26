# D13 C：使用与实际验证工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**C 已完成实现，D13 A–C 完成，下一步 D14。** 本阶段不开展整批开发或验收，不把离线机制结果写成真实回答效果。

## 1. 使用方式

页面继续选择论文和固定 RAG/Agent 模式后提问；检索改为 BM25＋向量＋RRF，D12 的论文原文、模型知识和分析依据标记继续显示。有真实引用的句子仍可点击查看原文和页码。无需重建已有向量或额外启动检索服务。

独立检索入口保持原有命令。例如：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d --query 'retrieval augmented generation parametric non-parametric memory' --json
```

命令会进行一次真实问题 embedding，BM25 和 RRF 本地完成；用户之后主动运行该命令才会使用服务额度，本阶段离线验证不执行。问答仍用现有 `scripts.answer_question`、`scripts.answer_question_agent` 或页面入口，无需添加混合检索开关。

## 2. 实际验证

最终执行 **3 个相关现有离线方法**，结果 **Ran 3 tests / OK，0.655 秒**。分别覆盖两路融合、版本/来源范围以及接入两模式核心的真实调用链；未按模块或目录运行，没有新增测试方法。

| 方法 | 实际覆盖 |
|---|---|
| `scripts.check_retrieval.RetrievalChecks.test_query_requests_one_vector_and_returns_complete_sqlite_evidence` | 临时真实 SQLite/Qdrant＋模拟问题向量，dense 第一页 rank 1、BM25 第二页 rank 1，融合后第二页提升且 chunk ID 去重；英文和中文查询处理；相同 searcher 第二查询复用词项索引，原文读取总一次、每查询一次模拟 embedding，没有正文重向量 |
| `scripts.check_scoped_search.ScopedRetrievalChecks.test_point_filter_intersects_selected_full_pair_not_other_versions` | dense 与 BM25 同时遵守选定完整论文/版本配对和 `allowed_point_ids`；旧版本、其他论文及不允许来源不进入融合 |
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | hybrid searcher 接入实际固定 RAG/Agent 核心，来源范围与真实引用回查、上下文/提示 `score_kind=rrf`、外部 top-5 与内部 top-20、资源关闭和既有导出；搜索/聊天供应商使用模拟响应 |

实际运行命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest scripts.check_retrieval.RetrievalChecks.test_query_requests_one_vector_and_returns_complete_sqlite_evidence scripts.check_scoped_search.ScopedRetrievalChecks.test_point_filter_intersects_selected_full_pair_not_other_versions scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
```

真实模型/embedding API 请求为 **0**，没有重建正文向量或新增哈希、审计、快照、独立验证报告，没有整批 D10 重跑或 D14 验收。已有临时来源身份字段沿用既有引用逻辑，不另扫文件。文档不跑测试，已通过且代码未变的结果复用；未执行的检查不列为通过。上述结果确认实现机制与调用链，不代表新回答准确率；D10 历史成绩仍归属原阶段。

## 3. 怎样学习：约 15 分钟

1. 阅读独立检索 CLI 的结构化输出：`score_kind=rrf` 时结果 `score` 为融合分数；`retrieval_trace` 中的 `dense_candidates` 和 `bm25_candidates` 保存两路原始分数，`fused_candidates` 保存各路名次与贡献来源。结构化运行记录中的这些字段不表示答案准确率。
2. 从页面服务追踪选定论文/版本传入混合 searcher，说明 top-5 外部结果与每路最多 20 条候选的关系。
3. 先读 [A BM25 日志](/D:/course/paper-research-assistant/docs/v1/d13/d13-A-bm25-guide.md)，再读 [B RRF 日志](/D:/course/paper-research-assistant/docs/v1/d13/d13-B-rrf-integration-guide.md)，用自己的话描述一次首轮检索和一次 Agent 补查的区别；学习无需重新调用模型。

## 4. 关键问题与答案

**现在就能说准确率提升了多少吗？** 不能。代码机制和离线结果只能说明候选融合、范围与调用流实现了对应行为。D14 使用原 20 条冻结题做首次双模式验收，再分别评价回答有用性和论文原文支持。

**运行现有页面或 CLI 要重建索引吗？** 不需要为 D13 重建已有正文向量。关键词统计从已选版本的原文读取，向量路径仍使用原有 ready 索引。正常使用入口和论文选择方式保持。

**下一步还要做什么？** D14 完成验收入口并跑原 20 题首次双模式验收；D15 根据真实失败必要局部修复；D16 完成启动、说明与演示交付；D17 将已实现功能和实际结果用于简历与面试。本阶段不提前运行验收题。
