# D13 B：RRF 与入口工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**B 已完成实现。** 本阶段沿用现有 dense 检索组件，用 wrapper 加入 BM25 和名次融合。实际验证集中在 [C 日志](/D:/course/paper-research-assistant/docs/v1/d13/d13-C-usage-validation-guide.md)。

## 1. 实际完成什么

[HybridEvidenceSearcher](/D:/course/paper-research-assistant/paper_assistant/hybrid_search.py)复用 [EvidenceSearcher](/D:/course/paper-research-assistant/paper_assistant/search.py) 的向量查询和已有原文回查，再在相同选定版本上取得 BM25 候选。两路各最多 20 条，以 chunk ID 合并，RRF 分数为：

```text
rrf_score(chunk) = sum(1 / (60 + rank_in_each_route))
```

名次从 1 开始；只在一个路径中出现的 chunk 只计该路贡献。同一 chunk 在两路出现只返回一次，每一路重复 ID 只计首次贡献，原文、页码和来源继续来自已有数据。同分时依次按 dense 名次、BM25 名次和 chunk ID 排序。RRF 只使用名次，向量相似度与 BM25 分数不直接相加；融合分数也不能解释成答案正确概率。

结果记录 `retrieval_method=bm25_dense_rrf`、`score_kind=rrf`，顶层结果 `score` 为 RRF 分数。`retrieval_trace` 保留 `recall_k=20`、`rank_constant=60`，以及 `dense_candidates`、`bm25_candidates` 和 `fused_candidates`；融合候选携带 `dense_rank`、`bm25_rank`、`dense_score`、`bm25_score`，缺少某一路时其字段为 `null`。这使运行记录可解释排名来源，不新增审计文件。

两路召回属于一次检索轮次。该轮向量查询仍产生一次问题 embedding，BM25 和 RRF 在本地完成；不增加聊天决策、HyDE 或独立重排模型。问答入口从融合结果取 top-5 后再按原有上下文规则展示，Agent 补查继续最多一次、最终最多 8 条/8000 字符。

接入范围是页面服务、固定 RAG CLI、Agent CLI、双模式入口和独立检索 CLI。核心问答仍接收同一 `search_evidence()` 合约；选定论文/版本与 `allowed_point_ids` 传入两路，摘要限定不得从 BM25 路径流入摘要之外的原文。原 dense 组件继续保留供直接调用和历史逻辑使用。

当前 D9 页面与成对运行入口借用 `agent_runtime.open_retrieval_resources()`，此处统一提供混合 wrapper；旧页面服务、固定 CLI 和独立检索 CLI 的构造位置也已替换。`source_scope.py`、`agent_context.py` 和正文补读上下文继续传递 `score_kind=rrf`，提示与导出使用融合分数含义，不把它当成 cosine 相似度。

固定 RAG 提示版本为 `d13-hybrid-useful-answer-v1`，来源限定版本为 `d13-hybrid-source-scoped-answer-v1`；Agent 为 `d13-hybrid-useful-paper-informed-agent-v1` / `d13-hybrid-useful-paper-informed-source-scoped-agent-v1`。提示解释 RRF 分数，回答依据沿用 D12；最终仅同步来源限定版本记录，没有再次改变来源行为，复用已经通过的相关结果。

## 2. 怎样学习：约 25 分钟

1. 从 `HybridEvidenceSearcher.search_evidence()` 追踪两路候选，再读 [lexical_retrieval.py](/D:/course/paper-research-assistant/paper_assistant/lexical_retrieval.py) 的 `reciprocal_rank_fusion()`，找到 chunk ID 去重、RRF 和截取 `top_k`。
2. 看 `search.py` 的 `EvidenceSearcher.search_evidence()`：区分已有向量路径负责的查询/原文回查与新增本地词项工作。
3. 读 [页面运行服务](/D:/course/paper-research-assistant/paper_assistant/web_runtime.py)、[固定 RAG CLI](/D:/course/paper-research-assistant/scripts/answer_question.py)、[Agent 运行服务](/D:/course/paper-research-assistant/paper_assistant/agent_runtime.py)和 [双模式入口](/D:/course/paper-research-assistant/scripts/run_agent_comparison.py)，找到 searcher 的构造位置。
4. 用两个有重叠 chunk 的排名列表手算一个 RRF 结果，解释“两路共同靠前”和“单路靠前”如何参与排序。

## 3. 关键问题与答案

**RRF 算重排模型吗？** 它是基于召回排名的融合规则，没有新增模型调用。D13 没有单独的 cross-encoder 或 LLM reranker；两路原始分数和融合名次是不同含义。

**两路各 20 条，会让模型收到 40 条正文吗？** 不会。广召回发生在检索阶段，融合去重后仍按调用入口的 `top_k` 返回。正常问答展示 top-5，Agent 最终证据仍最多 8 条并受 8000 字符约束。

**补查只允许摘要时，两路怎么办？** 同一个摘要 point 白名单用于 dense 与 BM25 候选。向量路径使用已有 Qdrant 条件，BM25 路径只让允许 ID 进入结果；两路的融合不能扩大所允许的来源范围。
