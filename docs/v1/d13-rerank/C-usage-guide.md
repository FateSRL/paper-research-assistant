# 重排 C：使用日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**C 已完成，本机配置与说明已写，3 个相关现有离线方法最终通过。** 文档修改本身不跑测试；本轮真实模型、embedding 和重排请求为 0，没有新增哈希、审计或独立验证报告。

## 1. 配置与启动

本机 [`.env`](D:/course/paper-research-assistant/.env) 已配置：

```dotenv
RERANK_MODEL=qwen3-rerank
RERANK_BASE_URL=https://ws-dpnyjvvx2lsryczn.cn-beijing.maas.aliyuncs.com/compatible-api/v1
RERANK_TIMEOUT=30
```

`RERANK_API_KEY` 留空时使用现有 `EMBEDDING_API_KEY`，需要独立密钥时填写该字段，不需要把密钥发到聊天或写入日志。模型、地址两项一起配置启用重排；移除这两项沿用 RRF。修改环境后重新启动页面，无需重新入库或生成 embedding。

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m streamlit run .\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

打开[论文助手](http://127.0.0.1:8501)，选择论文和问答模式，发送问题。点击带引用的完整句子查看原文与 PDF 页序；模型知识和分析继续标明依据。“回答详情与下载”用于查看运行过程和 JSON/Markdown。

真实提问会使用现有 embedding 与聊天服务，启用重排后每个有候选的检索轮最多额外一次重排请求。固定 RAG 通常一次，Agent 实际补查时最多两次。查看引用与下载已有结果不会再次发出问答。

## 2. 工作日志与实际验证

- 已把 D13 后重排补充写入总规划，A/B/C 日志分别保存；D14 仍为下一阶段首次最终验收。
- 根任务只执行以下 3 个相关现有离线方法，使用临时资源和模拟响应，没有新增测试方法或运行全量套件。
- 本轮没有新增题集、整批开发重跑、真实 API 或准确率数字。新增重排的回答效果检查并入 D14 原 20 题双模式验收。

已有 D13 三个方法通过记录属于 BM25＋向量＋RRF 原实现；不能把旧结果当成本次新客户端验证，也不能把接口离线通过当成真实服务已开通或回答效果提升。

| 实际现有方法 | 覆盖行为 | 最终结果 |
|---|---|---|
| `scripts.check_retrieval.RetrievalChecks.test_query_requests_one_vector_and_returns_complete_sqlite_evidence` | 完整融合池重排后截取 top-1、返回位置映射原文、来源白名单、503 回退、截止保留已发 1 请求与用量、客户端关闭与配置密钥复用 | 单独重跑通过 |
| `scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` | 两模式实际核心、原文引用、资源关闭、Markdown 与网络调用统计 | 首次通过，复用结果 |
| `scripts.check_agent_comparison.PairedExecutionChecks.test_retry_adds_one_actual_search_without_repeating_shared_search` | 真实混合检索层配模拟重排客户端；共享首轮一次加实际补轮，逻辑使用固定 1 / Agent 2，实际总重排 2 次 | 首次通过，复用结果 |

初跑 3 项耗时 **0.577 秒**，后两项通过，检索方法因旧模拟 embedding 缺少剩余时限适配失败。仅把该测试的旧模拟接入已有 `LegacyEmbedderAdapter`，单独重跑这一项，**0.097 秒 / OK**。对应代码未变的后两项不重复运行。最终为 3 个不同现有方法通过，不把失败初跑写成全通过，不新增验证报告。此处的请求数均来自模拟响应，真实 API 为 0。

## 3. 怎样学习：约 20 分钟

1. 按 [A](D:/course/paper-research-assistant/docs/v1/d13-rerank/A-client-guide.md)看请求和位置映射，再按 [B](D:/course/paper-research-assistant/docs/v1/d13-rerank/B-integration-guide.md)追踪“完整候选→重排→前 5 条”。
2. 读一个已有运行结果，找每轮候选与最终展示原文，分清 RRF 分数和重排相关性；不为读记录再次运行题目。
3. 对一个实际回答点击句子，核对引用正文是否支持句子；有相关性高分仍要检查支持关系。
4. 用自己的话说明一次首轮、一次 Agent 补查和共享首轮的真实重排请求数。

## 4. 问题与答案

**我还需要重新导入论文吗？** 不需要。重排使用已召回的正文，原解析、chunks、embedding 和索引均可复用。

**怎样知道这次有没有真正用重排？** 单轮 `ranking_method=rerank` 表示成功，`rerank_statistics` 给出执行状态、真实请求数和耗时，`retrieval_trace.rerank.candidates` 给出评分。启用配置并不代表每轮都完成调用，没有候选会跳过，服务失败可能回退。Agent 两轮合并标记 `retry_then_initial`，应分别查看各轮记录。

**现在能说准确率提升了吗？** 不能。实现与离线方法说明程序路径按约定工作；真实问题的效果属于 D14 保存输出与评价，不能使用 D10 历史成绩或他人简历数字代替。
