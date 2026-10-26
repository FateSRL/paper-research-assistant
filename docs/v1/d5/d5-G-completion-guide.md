# D5 任务 G：验收汇总与 D6 交接

记录日期：2026-10-04（Asia/Shanghai）。**G 的汇总与交接已完成；D5 总状态为“实现完成，评测/人审待补”，可以进入 D6 界面接入。** 用户选择六题“暂未复核，先保留候选”，本次做 G 不改变这一决定，也不表示答案人审通过。

目录整理补记（2026-10-04）：D4/D5 文档分别移入 `docs/d4/`、`docs/d5/`，导航和验收脚本里的文档路径同步更新。G 原验收、评分和运行快照保持当时内容；本次仅文档路径迁移及其核对，原文件和旧/新路径见 [分组清单](/D:/course/paper-research-assistant/artifacts/docs_stage_reorganization.json)。

当前验收入口：[validation.md](/D:/course/paper-research-assistant/artifacts/d5/validation.md)、[完整 JSON](/D:/course/paper-research-assistant/artifacts/d5/validation.json)。阶段记录见 [task_g.json](/D:/course/paper-research-assistant/artifacts/d5/task_g.json)，设计与执行范围见 [D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)。

## 1. 完成了什么，还缺什么

| 项目 | 当前结论 |
|---|---|
| A–E 固定 RAG、结构化回答、引用回查、CLI 与导出 | 已实现并有边界与真实运行记录 |
| F 正式十题首次运行与逐题 AI 评价 | 已完成，第一次结果和失败保留 |
| G 源码/检查/原始记录核对与交接 | 已完成，新增模型请求 0 次 |
| 三篇正式数据 | 71 个 PDF 文件页、1188 个 chunk，3 个 ready 处理版本 |
| 六道新增题 | AI 来源初审完成，仍为候选；人工复核、合并、补跑待做 |
| 新答案人工评价 | pending，人工准确率/支持率 N/A |
| 正式十六题初跑 | 尚未完成；正式题集仍是十题 |
| Streamlit 界面 / 自动补检索 Agent | 分别为 D6 / D8 后续任务 |

十题本轮有 7 个 `answered`、3 个 `insufficient_evidence`。AI 逐题判断可回答题完成 7/9，资料外合理拒答 1/1；19 个发布结论由各自引用原文并集支持。最终引用定位合法 21/21，其中单个结论与引用的配对有两次只提供部分支持，由同结论的其他引用补齐。AI 支持判断、程序定位和人工评价分别记录，不能合写成“准确率 100%”。

两道可回答题仍未完成：RAG D2-002 没检到 Sequence/Token 的文档使用规则；ReAct D2-003 没检到题目指定的摘要。它们的拒答符合本轮证据限制，但仍计未完成。原始十题不改标签、不增大 top-k、不覆盖首次失败，详见 [F 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-F-evaluation-guide.md) 和 [逐题评价](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/ai_semantic_review.md)。

这次只初跑十道开发题，来自三篇固定论文；仅有一道明显资料外题，尚未测多次稳定性或冻结验收集。答案中 HotpotQA 停止条件依赖题面的实验范围，单独转载应保留该范围；部分回答有额外参数细节，事实支持通过不代表表达质量满分。

## 2. G 如何验收

新增入口 [validate_d5.py](/D:/course/paper-research-assistant/scripts/validate_d5.py) 在新的 Python 进程离线运行，读取 A–F 原记录及不可覆盖历史，核对当前源码 SHA、原始输出和事实库。它不会重跑此前的测试或问答。

| 已有检查记录 | 历史实际执行数量 | G 如何使用 |
|---|---:|---|
| B 聊天适配 | 34 | 核对通过记录与当前源码 SHA |
| C 生成核心 / 运行记录 | 38 / 8 | 分组继承，保留各自覆盖范围 |
| D 引用与固定 RAG / 运行记录 | 42 / 15 | 分组继承，保留实际检查记录 |
| E CLI 与导出组合 | 37 | 继承纯 JSON、资源、故障及导出边界记录 |
| F 批跑与机器统计 | 46 | 继承冻结、恢复、未知用量和不重复付费边界 |
| F 独立真实记录核对 | 174 项记录核对 | 保留原报告，另核对本轮文件仍一致 |

上述数量是此前执行的记录，不能称作 G 新运行的测试，也不能混入问答准确率。A 的首轮配置保留为历史起点；实际问答以 [E 运行配置](/D:/course/paper-research-assistant/artifacts/d5/answer_runtime_config.json) 和 [F 冻结配置](/D:/course/paper-research-assistant/artifacts/d5/qa_runtime_config.json) 为准。

旧记录的格式与迁移也分别保留：D4 原验收对应当时的 `validate_d4.py`，后来只更新了三条指南路径，原源码有归档快照，旧 SHA 没有被改写；E 边界记录与其历史 JSON 内容相同，换行格式导致字节 SHA 不同。详情见 [G 证据审计](/D:/course/paper-research-assistant/artifacts/d5/g_evidence_audit.md)。这些例外不替代当前 D5 源码绑定核对，交接技术说明另见 [复核记录](/D:/course/paper-research-assistant/artifacts/d5/g_handoff_review.md)。

本轮新检查包括：A–F 原历史仍一致；源码绑定没有漂移；正式十题未改；十次首次运行的 stdout、报告、历史和 run_id 一致；机器逐题及总分重算一致；AI 评价仍对应其原始证据；六题人工状态符合用户真实决定。SQLite 用只读连接新读数量和 ready 版本；PDF、正文、向量文件继承字节未变的保护快照，不冒充重新检查全部向量。G 不读取 `.env`，不打开 Qdrant，不发 API，不写正式题集或数据。

## 3. 可以怎样讲清这个项目

```text
问题 + 明确论文/处理版本
  → 一次问题 embedding 与 top-5 检索
  → 回 SQLite 取真实正文，只保留本轮实际展示的片段
  → 模型生成结论和引用 ID，或说明证据不足
  → 程序核对结构、允许 ID、版本、原文哈希和实际 PDF 页序
  → 展示答案/不足/错误，保存证据、原始输出、用量和历史
```

Qdrant 用来找相近片段，SQLite 保存原文与来源事实。版本配对防止把另一篇或另一次处理的正文混进回答。模型只能引用这次实际展示的 ID；库里存在但没有展示的片段也不能引用。正文预算统计的是 Python 字符，不冒充精确 token。

结构合法只说明字段符合要求，引用合法只说明来源能定位；原文是否支持结论还要单独评阅。证据不足和工具失败分别显示，避免服务故障被包装成论文没有答案。固定 RAG 只有一轮检索，Agent 是否补查仍待 D8 实现。

模型调用采用共享预算：温度 0.2、输出上限 1200 tokens；单次聊天超时起点 30 秒、全轮截止预算起点 120 秒；最多 3 次聊天尝试，其中最多 1 次网络重试、1 次格式或引用修复，SDK 隐式重试关闭。阶段之间会检查截止时间；正在进行的同步请求恰在第 120 秒被强制取消尚未验证。

## 4. 现在如何操作

先查看已有记录，不产生模型请求，也不改初跑文件：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
Get-Content -LiteralPath '.\artifacts\d5\validation.md' -Encoding UTF8
Get-Content -LiteralPath '.\artifacts\d5\qa_baseline\d5_f_dev10_20261004\ai_semantic_review.md' -Encoding UTF8
```

需要重新核对当前交付是否仍与这些记录绑定，可执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_d5
$LASTEXITCODE
```

该命令保存最近一次 G 核对及新的不可覆盖历史，旧 A–F 不变。退出码 0 表示工程证据核对通过；JSON 的 `full_d5_acceptance_completed=false` 表示评测/人审仍待补。源码或证据变化时退出码 1，应按变化补新的检查/运行记录，而不是改旧 SHA 让记录通过。历史路径在报告的 `history_report` 中。

离线列出可检索版本：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready --json
```

本轮实际执行退出码 0，列出 RAG 385、ReAct 480、Reflexion 323 个 chunk，embedding/聊天均 0 次。纯查看可以不加载模型配置、不打开 Qdrant。

执行通用问答见 [E 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)。问答会产生新的服务请求；[最近答案](/D:/course/paper-research-assistant/artifacts/d5/answer_result.md) 随问答更新，回看 F 首次结果用批次 `results/` 和各题的历史来源。`run_qa_baseline --resume` 不带 `--live` 虽无 API，仍会更新 manifest/summary 并创建临时锁；日常纯查看不要把它当作不写文件的阅读命令。

## 5. D6 第一件事

先让最小 Streamlit 页面选择 1–3 个 ready 的完整论文/处理版本配对，提交问题，显示终态、结论、原文和 PDF 文件页码。PDF 页码从 1 开始，表示文件第几页，可能不同于论文印刷页码。来源字段使用程序返回的 `evidence_sources`，不让模型或用户填写页码。

直接复用 [rag.answer_question](/D:/course/paper-research-assistant/paper_assistant/rag.py)，实际签名为：

```python
answer_question(query, selected_versions, searcher, store, client,
                *, project_root, top_k=5, max_chars=8000)
```

核心不创建或关闭这些资源，调用者负责。页面提交动作沿 [E CLI 的组合方式](/D:/course/paper-research-assistant/scripts/answer_question.py) 打开只读 PaperStore、一个 QdrantClient，以及借用同一个客户端的 QdrantStore；先检查正式 collection 存在，再构造搜索器。不能在页面和业务层各开一个同目录客户端，也不能让“查看”创建空 collection。

每次提问建立新的 ChatBudget 和 RecordedLLM，提交结束或失败时由 ExitStack 关闭资源。不要缓存跨会话 SQLite 连接、预算或聊天客户端；页面自动重绘只展示 session_state 中已有结果，不在页面顶层重新发请求。首版先用提交动作内的资源生命周期，后续并发另行设计。

`rag` 返回的是核心结果，E 外围还负责完整 run_id、配置/源码/输入快照、资源关闭失败、导出和费用记录。D6 需要沿 E 的组合方式保留这些能力，复用 [answer_export.py](/D:/course/paper-research-assistant/paper_assistant/answer_export.py)，不能只存 claims 或悄悄复制另一份 RAG 业务逻辑。本次没有新增 UI 通用运行工厂，必要的适配抽取属于 D6 工作。

页面至少区分五个状态：`answered` 展示结论与实际来源；`insufficient_evidence` 展示缺什么及本轮证据；`tool_error` 展示安全错误与失败阶段；`invalid_output`、`budget_exceeded` 展示终止原因和已经发生的用量。缺失 usage 保留 null，不填 0；证据不足不能直接断言整篇论文没有答案。

## 6. 待补事项如何接着做

先对照 [六题材料](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_review.md) 实际复核，明确通过后再合并和补跑。六题使用新的题集绑定，保留原十题批次；不将 AI 初审自动写成人审通过。新答案语义人审也单独记录。

D6 开发集目标为 20 条：当前正式 10 条，先确认并合并候选 6 条，再补 4 条独立题。另准备并冻结 20 条验收题及评分规则；不把已用于开发的十题成绩当作保留题成绩。D3 六页覆盖、图文/公式恢复稿仍按各自人审状态推进，本次 G 不扩大确认范围。

本次 G 已把可复用的实现、真实结果、已知问题和下一步放在同一入口。使用者能否独立解释和修改仍未测量，可按上面的流程自行练习讲述，不新增虚构学习验收。
