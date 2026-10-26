# 重排 A：客户端日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**A 已完成实现。** 本次复用现有 httpx，接入百炼 `qwen3-rerank`。入口是 [rerank_client.py](D:/course/paper-research-assistant/paper_assistant/rerank_client.py) 的 `RerankClient`、`RerankBatch` 和 `RerankError`，配置由 [config.py](D:/course/paper-research-assistant/paper_assistant/config.py) 的 `load_rerank_settings()` 读取。离线模拟响应验证包含位置映射、服务失败、截止、客户端关闭和密钥复用；没有发起真实服务请求，实际结果见 C。

## 1. 工作日志

用户已提供北京业务空间与 API HOST。使用配置：

```dotenv
RERANK_MODEL=qwen3-rerank
RERANK_BASE_URL=https://ws-dpnyjvvx2lsryczn.cn-beijing.maas.aliyuncs.com/compatible-api/v1
RERANK_TIMEOUT=30
```

本机已配置上述模型、地址和 30 秒超时，`RERANK_API_KEY` 留空复用 `EMBEDDING_API_KEY`；需要独立密钥时可填 `RERANK_API_KEY`。模型和调用地址是独立配置，正文 embedding 仍使用原配置。配置模型与地址两项时启用重排，移除两项时沿用 RRF；不把重排接入作为重新入库的条件。

`RerankClient.rerank()` 输入本轮查询和有序候选原文列表，以一次 `POST /reranks` 请求整个批次，`top_n` 为候选数量，`return_documents=false`。服务返回候选位置及 `relevance_score`；通过位置对应原 chunk，保留原文、页码、论文/版本、引用 ID。接口映射不能用服务返回文本覆盖本地原文。

单次请求使用剩余总时限与默认 30 秒超时中的较小值，没有新增自动网络重试。真实请求次数、耗时和服务实际返回的用量进入现有运行记录；服务未提供用量时不估算成已知 token 数。实际离线验证统一记录在 [C 日志](D:/course/paper-research-assistant/docs/v1/d13-rerank/C-usage-guide.md)。

接口格式以[百炼官方重排文档](https://www.alibabacloud.com/help/en/model-studio/text-rerank-api)为准，业务空间 ID 用在主机名中。API Key 留在本机环境配置。

## 2. 怎样学习：约 20 分钟

1. 先看官方文档的查询、候选文档、返回候选位置和相关性分数，理解一次请求可以评分一批候选。
2. 对照本机重排配置和现有 embedding 配置，解释“同一账号密钥”和“不同模型接口职责”的关系。
3. 在 `RerankClient.rerank()` 追踪查询与候选列表构造、单次 HTTP 请求、响应位置映射和 `RerankBatch`/`RerankError` 统计；不要为了读代码真实调用服务。
4. 手写三个候选，假设返回位置为 `2, 0, 1`，把位置映射到原 chunk，确认原文与页码保持对应。

## 3. 问题与答案

**重排会生成新的向量索引吗？** 不会。它给本轮已经召回的候选评分；正文向量、SQLite 和 Qdrant 均复用。

**为什么返回的位置要映射回本地候选？** 位置表示请求文档列表中的哪一条。引用需要本地原始 chunk ID、页码与原文，不能只把服务文字当成引用来源。

**相关性分数能表示回答正确率吗？** 不能。它表示模型判断的查询与段落相关程度；事实是否得到支持仍要看实际引用原文。第一版不照搬别人的 `0.7` 阈值。
