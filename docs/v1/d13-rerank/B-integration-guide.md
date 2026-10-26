# 重排 B：检索集成日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**B 已完成实现。** 集成入口是 [hybrid_search.py](D:/course/paper-research-assistant/paper_assistant/hybrid_search.py)，将重排接在 RRF 融合之后、外部 `top_k` 截取之前。相关现有方法验证了两模式原文引用、完整候选排序、失败回退、截止，以及共享首轮和补轮真实计数，实际结果见 C。

## 1. 工作日志

原 D13 两路各取最多 20 条，RRF 按 chunk ID 去重，最多留下 40 条。本次把这批完整候选原文交给重排模型，再按返回顺序取外部请求的 `top_k`。正常问答仍前 5 条；独立检索入口沿用其参数。

固定 RAG 与 Agent 共用检索层。首轮按用户问题评分；Agent 发生补查时按补查查询给该轮候选评分。两轮证据继续采用现有合并方式，最终最多 8 条/8000 字符。D11 邻接正文仍从选中锚点读取，补读片段没有被独立重排，不把继承锚点分数说成逐段重排评分。

原 `score` 继续代表 RRF 分数。重排相关性、重排顺序和执行状态进入检索记录，最终候选 `rank` 对应真正展示顺序；提示、页面详情和导出说明分数与排名含义。这样保留原证据结构，也能解释候选为什么被提升。

单轮 `ranking_method=rerank` 表示重排成功，关闭或失败时为 `rrf`；成功的 `retrieval_method=bm25_dense_rrf_rerank`，其余继续 `bm25_dense_rrf`。`rerank_statistics` 保存 `status`、`model`、`requests`、`elapsed_seconds`、`usage`。`retrieval_trace.rerank` 另含 `candidates` 和 `error`：候选保存 `chunk_id`、重排名次 `rank`、原 RRF 名次 `rrf_rank`、独立相关性分数 `relevance_score`。Agent 两轮合并后的 `ranking_method=retry_then_initial` 表示补轮优先，不能解释为对两轮并集又做了一次全局语义重排。

论文/解析版本及 `allowed_point_ids` 已在两路召回时限制候选；重排只处理已有候选，不能扩大可用来源。回答依据标记和点击整句查看实际原文继续使用 D12 路径。

重排耗时属于现有总时限。失败且还剩时间时继续使用原 RRF 顺序并保存失败状态；截止时停止，不能在超时后继续生成答案。没有候选时不发送重排请求。没有新增聊天决策、重排重试或另一层模型取证摘要。

真实问答每个检索轮最多增加一次重排请求。成对比较复用共享首轮的重排结果，实际用量只计一次；Agent 独立补查产生的重排再计一次。不能将共享结果的使用次数写成两次 HTTP 请求。

问答结果的 `statistics.rerank` 汇总实际请求和耗时，并在 `rounds` 保留各轮服务返回的 `usage`。使用量字段不一定跨服务具有同一含义，因此不虚构总 token 数或金额；成对结果的实际总量按共享首轮一次与真实补轮分别合计。

## 2. 怎样学习：约 25 分钟

1. 从 `HybridEvidenceSearcher.search_evidence()` 找到 dense、BM25、RRF 三段，再定位重排与最终截取顺序。
2. 对照 [lexical_retrieval.py](D:/course/paper-research-assistant/paper_assistant/lexical_retrieval.py) 的 RRF：理解 RRF 用名次，重排模型用查询与正文。
3. 从首轮结果追踪 [agent_context.py](D:/course/paper-research-assistant/paper_assistant/agent_context.py) 的合并，解释单轮前 5 条和最终最多 8 条的区别。
4. 查看运行记录的排序、状态、耗时和请求数，分清“模型重新排序”“失败沿用 RRF”和“没有候选未调用”。

## 3. 问题与答案

**为什么不能只对 RRF 前 5 条重排？** 那只能交换已有 5 条的顺序，无法让原来第 6–40 条的有效证据进入前 5。要先重排完整候选，再截取。

**重排失败会导致检索完全没结果吗？** 服务失败时已有 RRF 候选仍然可用；有剩余时间就回退并记录本轮未完成重排。总时限耗尽则停止，失败回退不延长预算。

**如果正确段落没有出现在两路候选里，重排有用吗？** 它不能找回不存在的候选。此时应定位查询、召回或正文读取问题；D11 的缺口化补查和实际邻接正文仍承担这些职责。
