# D5 任务 D：引用回查与固定 RAG 核心

当前导航更新（2026-10-03）：E 通用问答 CLI 与完整导出已完成，见 [任务 E 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)；下一步 F 题集初跑与语义评价。以下保留 D 当时的实现、验收与用量。

完成日期：2026-10-02（Asia/Shanghai）。D 已完成引用业务校验与固定 RAG 核心。通用问答 CLI、完整导出与更多运行边界留给 E，题集初跑与质量评分留给 F。

本次 42 项核心 + 15 项运行记录检查通过，共 57 项离线检查。真实首题返回 `answered`：5 条展示证据、4837 个正文字符、3 条结论、5 次引用检查、2 个来源（RAG PDF 文件页序 1/2）。新增问题 embedding 1 次、34 tokens；聊天 1 次、2758 tokens（输入 2539、输出 219），无重试/修复。语义支持尚未评分。

入口：[D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)、[任务 C 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-C-generation-guide.md)。完成与实际用量见 [task_d.json](/D:/course/paper-research-assistant/artifacts/d5/task_d.json)。

## 1. D 补了哪一层

`AnswerDraft` 能检查字段、非空引用与状态一致，但 `citation_ids=["made_up_id"]` 仍可通过结构校验。D 新增 [citations.py](/D:/course/paper-research-assistant/paper_assistant/citations.py) 的 `validate_citations()` 和 [rag.py](/D:/course/paper-research-assistant/paper_assistant/rag.py) 的 `answer_question()`，先校验本轮引用范围，再回查真实来源。

固定核心只有一轮原问题检索：

```text
明确问题 + 1–3 个论文/处理版本完整配对
 → EvidenceSearcher，top_k=5
 → C 完整片段选择、展示快照、消息、结构化草稿
 → D 本轮引用集合 → SQLite 原文/身份 → 实际 PDF
 → answered / insufficient_evidence / 明确错误状态
```

不会自动补检索、增大 top-k、从题集期望引文补正文，也不会删除错误结论后宣称整份答案成功。程序通过来源定位后返回 `answered`，仍标记 `semantic_support_status="not_reviewed"`；这不能代替事实支持评价。

## 2. 引用检查的顺序与错误分类

`validate_citations(draft, context, store, project_root=...)` 再验证 C 展示快照与既有 `AnswerDraft`；模型对象也重新检查，不能用 `model_construct()` 绕开规则。上下文冻结为独立副本，回查时外部修改不能悄悄改变允许集合。

逐个 claim、逐个引用记录从 0 开始的 `claim_index` / `citation_index`、ID、状态和安全 code：

1. ID 必须属于本轮实际 `shown_evidence`；仅在全库存在、在检索候选但被预算省略、或由问题伪造的 ID 均不能进入允许集合。库外 ID 不用于查全库。
2. 展示 ID 调用 `PaperStore.get_chunk()`，确认真实存在。它本来就会核对 SQLite 查询列/完整 JSON、版本/PDF 元数据、文本 SHA 与页码。
3. 回查的论文、处理版本、页序、全文、文本 SHA 必须逐字对应展示快照。完整 pair 检查避免 `(A,r1)`、`(B,r2)` 被误当成允许 `(A,r2)`。
4. 从库的 `local_path` 定位项目 `data/papers/` 内相对 PDF，读实际字节核对 `pdf_sha256`，再读取真实页数，确认 PDF 文件页序合法。缺失、损坏、路径逃逸或已换文件都会失败。

| 情况 | 校验结果 | 固定核心怎样处理 |
|---|---|---|
| 模型 ID 不在展示集合、草稿结构非法 | `invalid_output` | 有额度时最多修一次；仍错则不发布 |
| 展示证据回查缺失、数据库异常、身份/原文/快照不符 | `tool_error` | 来源发生故障，直接失败，不让模型“修数据库” |
| 实际 PDF 不存在、哈希不符、不能读取或页码越界 | `tool_error` | 直接失败，保存安全 code |
| 一份草稿同时有模型引用错误与来源损坏 | `tool_error` 优先 | 全部失败，不发布部分来源 |
| 合法 `insufficient_evidence` 草稿 | `valid` | 无事实引用，不扫描全库/PDF |
| 所有事实引用回查通过 | `valid` | 程序填来源，才发布 `answered` |

同一个 chunk 每轮只回查一次，同一实际 PDF 每次校验最多读/打开一次；重复引用仍各有一条检查记录。来源按首次引用 ID 去重。任何失败时 `evidence_refs`、`evidence_sources` 都为空；未知异常正文不写入错误，避免服务或库回显进入日志。

## 3. 程序输出什么来源

`EvidenceRef` 沿用四字段：`chunk_id`、`paper_id`、`parse_revision`、`pdf_page`。它们全部由库记录填入，模型不提供定位字段。

单独的 `evidence_sources` 保存完整原文、文本/PDF SHA、论文标题、arXiv 版本、来源 URL、库内相对路径、实际绝对 PDF 路径与真实页数。`pdf_page` 是从 1 开始的 PDF 文件页序，不冒充印刷页码或自动章节标注。

核心仅在 `answered` / `insufficient_evidence` 正常业务终态返回 `answer`。`tool_error`、`invalid_output`、`budget_exceeded` 一律 `answer=None`；原始候选、消息、草稿、修复与检查步骤仍保留用于回查。

## 4. 固定流程与共享预算

`answer_question(query, selected_versions, searcher, store, client, project_root=..., top_k=5, max_chars=8000)` 借用现有资源。调用者在检索前创建同一个 `ChatBudget`；检索、C 格式修复、D 引用修复都沿用它。核心不会另开 SQLite、另抢 Qdrant 目录锁或关闭借用资源。

输入先检查非空问题、1–3 个完整配对、固定 top-5 与 1–8000 的正文字符预算。检索返回的问题、完整配对及 top-k 必须与原输入一致，不能只相信 envelope 自己内部一致。`no_hits` 或预算未容纳任何证据走资料不足，0 次聊天；检索异常保留请求统计及安全的失败子阶段，返回 `tool_error`。

模型引用有误时，D 复用原始 system/user 展示数据，附上原输出及安全检查 code，调用一次 `purpose="repair"`，严格解析后完整重查。D 不调用 C 再重新获得格式修复次数。若 C 已使用一次格式修复，D 遇到引用错误直接停止；网络重试最多一次，总 SDK 尝试最多三次。

检索前后、上下文、生成返回、引用检查前后、引用修复解析与最终返回都检查截止预算。超时不能发布答案；同步调用仍无法据此保证第 120 秒精确中止。

## 5. 操作与验证记录

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
# 离线：合成证据、临时真实 PDF、假检索/配置和 SDK MockTransport
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_rag
# 离线：临时目录检查固定验收脚本的清理/记录/保护逻辑
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_rag_smoke
# 离线：回查 C 已保存的真实草稿，仅读正式 SQLite 与 PDF，0 API
.\.venv\Scripts\python.exe -X utf8 -m scripts.review_draft_citations
# 已执行记录供回查；再次运行会消费额度
.\.venv\Scripts\python.exe -X utf8 -m scripts.smoke_rag --live
```

核心 42 项离线检查通过，36 次 SDK MockTransport 模拟发送，真实网络 0 次，未读取 `.env` 或正式数据库。检查覆盖伪造/未展示/省略引用、完整配对、实际 PDF/哈希/页数/路径、全失败不发布、共享修复与重试预算、截止时间和借用资源。见 [rag_boundary_validation.json](/D:/course/paper-research-assistant/artifacts/d5/rag_boundary_validation.json)。

另 15 项运行记录检查通过，执行 24 次模拟 smoke，真实网络 0 次。覆盖构造/关闭故障、费用与步骤保留、输入或源码删除/不可读、安全配置错误、业务退出码，以及清理/最终核对超时。这些次数是模拟运行，不是额外服务请求。

C 草稿离线回查有 5 次引用检查、2 个去重来源，全部 `valid`，SQLite 字节不变；没有新增 embedding 或聊天请求，不能把 C 的旧费用记入 D。见 [citation_replay.md](/D:/course/paper-research-assistant/artifacts/d5/citation_replay.md)。

新固定核心运行的候选、实际消息、输出、全部引用明细与本次费用见 [rag_smoke.json](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke.json)，可读答案和原文见 [rag_smoke.md](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke.md)。清理/保护检查见 [rag_smoke_boundary_validation.json](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke_boundary_validation.json)。拥有者使用 `ExitStack` 在所有终态关闭资源；关闭故障或输入/源码保护失败仍保留已用费用与原始步骤，清空可发布答案。

D 新增外围模块与验收脚本；旧 B/C 代码、正式数据、开发题集和 D4/A/B/C 历史报告保留原状，所有本次报告绑定实际源码 SHA。ReAct 原 top-5 摘要漏召回仍是已知检索问题，未改题目标注或偷补摘要。

下一步 E：围绕该核心提供通用 `scripts.answer_question` CLI、逐次 JSON/Markdown 保存、清晰退出码与更多组合故障检查；F 再做真实题集初跑和语义评分。
