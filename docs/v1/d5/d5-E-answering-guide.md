# D5 任务 E：通用问答 CLI、运行导出与组合检查

完成日期：2026-10-03（Asia/Shanghai）。本指南保留 E 阶段的结果与用量。F 已保存十题初跑，新增六题保留候选；G 已汇总工程验收与 D6 交接，见 [G 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md)。正式十六题初跑与新答案人审待补，自动补检索仍是 D8 计划。

新增 [answer_question.py](/D:/course/paper-research-assistant/scripts/answer_question.py)、[answer_export.py](/D:/course/paper-research-assistant/paper_assistant/answer_export.py) 与 [check_answering.py](/D:/course/paper-research-assistant/scripts/check_answering.py)。CLI 直接复用 D 的 `rag.answer_question()`，旧 A–D 源码、正式数据和历史验收记录没有改变。

37 项离线检查通过：58 个 CLI 场景，51 个场景进入实际 RAG 检索流程，59 次安装 SDK MockTransport 模拟 HTTP 发送，真实网络 0 次。真实 CLI 首题退出码 0、终态 `answered`：3 条结论、5 次引用定位检查、2 个来源（RAG PDF 文件页序 1/2）；新增问题 embedding 1 次/34 tokens，聊天 1 次/2758 tokens，无重试或修复。这些数字分别是工程检查和一次实际运行，不是问答准确率。

完成记录：[task_e.json](/D:/course/paper-research-assistant/artifacts/d5/task_e.json)。E 首题：[不可覆盖原始历史](/D:/course/paper-research-assistant/archive/run_logs/d5/answer_20261003_120147_728995_8ce78831d965.json)。最近问答会随后续运行更新：[answer_result.md](/D:/course/paper-research-assistant/artifacts/d5/answer_result.md)、[完整 JSON](/D:/course/paper-research-assistant/artifacts/d5/answer_result.json)。前置设计见 [D 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-D-rag-guide.md) 与 [D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)。

## 1. 单篇问答

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.answer_question `
  --paper-id arxiv_2005.11401v4 `
  --parse-revision r_269ac0cb1263292d `
  --query 'What forms of parametric and non-parametric memory are combined in the RAG model?' `
  --top-k 5
$LASTEXITCODE
```

这条命令会请求问题 embedding 和聊天模型，使用真实服务额度；再执行也会产生新请求。默认终端输出结论、引用 ID、原文、PDF 链接和用量，保存 JSON/Markdown。`--json` 改为只在标准输出打印完整 JSON；依赖的启动警告进入标准错误，不污染机器结果。

## 2. 多篇、参数和退出码

多篇使用重复的完整 `--version`，不与单篇参数混用：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.answer_question `
  --version arxiv_2005.11401v4 r_269ac0cb1263292d `
  --version arxiv_2303.11366v4 r_d7736b29a2d8b39e `
  --query 'What memory mechanisms are described in the selected papers?' `
  --max-chars 8000 `
  --json
```

上面是多篇用法示例，本次没有额外执行它或把它计入真实评测。可选版本用已有离线命令 `python -X utf8 -m scripts.search_evidence --list-ready` 查询。

| 参数 | 规则 |
|---|---|
| `--query` | 必填非空问题，保留原问题用于记录与检索 |
| `--paper-id` + `--parse-revision` | 一篇的完整配对，两项必须同时提供 |
| `--version PAPER_ID PARSE_REVISION` | 可重复，1–3 个非空、无首尾空白且不重复的完整配对 |
| `--top-k` | 默认 5，当前只允许 5 |
| `--max-chars` | 默认 8000，允许 1–8000；统计真正展示原文的 Python 字符，不是 tokens |
| `--json` | 标准输出为完整 JSON，便于批量 runner 解析 |

| 退出码 | 情况 |
|---|---|
| 0 | `answered` 或 `insufficient_evidence`，且记录导出成功 |
| 1 | `tool_error`、`invalid_output`、`budget_exceeded`，或记录导出失败 |
| 2 | 参数用法错误；不读取配置、不建资源、不调用服务、不写本轮记录 |

退出码 0 不等于问题回答正确。批量 runner 仍须保存资料不足和所有非零结果，不能跳过失败题。

## 3. CLI 负责哪一层

入口只校验参数、创建同一份 `ChatBudget`、读取公开索引身份、管理资源、调用核心和导出。业务仍是 D 的固定一轮检索 → C 展示证据与生成 → D 引用回查，调用核心一次。

SQLite 以只读模式打开；一个进程只拥有一个本地 Qdrant 客户端，`QdrantStore` 借用它；查询前检查持久化目录和 collection 已存在。`ExitStack` 在成功和故障路径关闭资源。配置、资源或清理失败使用固定安全摘要，异常正文、密钥和认证头不进入报告。

生成、格式/引用修复与网络重试仍共用 B 的预算：最多 3 次聊天 SDK 尝试，最多 1 次修复、1 次网络重试；SDK 隐式重试关闭。默认 temperature 0.2、max_tokens 1200、单次聊天超时 30 秒、整轮截止预算 120 秒。检索及各阶段、清理和最终输入核对都检查截止时间；同步调用第 120 秒精确中止仍未验证。

## 4. 记录与故障保存

| 文件 | 内容 |
|---|---|
| `artifacts/d5/answer_result.json` | 最近一次完整机器记录，可原子更新 |
| `artifacts/d5/answer_result.md` | 最近一次答案、完整引用原文、PDF 页序与链接 |
| `archive/run_logs/d5/answer_<run_id>.json` | 逐次完整记录；已存在路径拒绝覆盖 |
| `archive/run_logs/d5/answer_<run_id>_export_failure_<id>.json` | 导出故障后的独立失败事件，原历史保持原样 |
| `artifacts/d5/boundary_validation.json/.md` | E 组合工程检查，与问答质量分开 |
| `artifacts/d5/semantic_case_review.json/.md` | 两个来源/语义案例的 AI 复核材料，0 API、人审 pending |

机器记录保存 run_id、UTC 开始/结束时间、原问题、所选完整版本、索引 profile、实际公开配置、RAG/提示词/选择版本、相关源码 SHA 和题集文件 SHA。`result` 中保留完整候选、真正展示的快照、实际消息、原始响应、解析草稿、引用检查、修复与最终输出。题集 SHA 仅标记运行时输入身份，题目期望要点和引文不进入运行提示词或选证据。

核心结果和 embedding 统计在关闭资源前保存；清理/正式输入核对失败会清空顶层与核心的可发布 `answer`，保留实际步骤、原始响应和预算记录。已用聊天统计始终来自共享预算；若核心意外异常导致 embedding 次数无法确认，该次数和总网络次数记 `null`，不写成零。供应商 usage 缺失时 total_tokens 为 `null`，另保留 known_total_tokens。

历史先完整写入临时文件，再通过独占硬链接发布；目标存在时不覆盖。最近 JSON/Markdown 独立原子更新。原始正常历史里的 `export.status=prepared` 表示导出前快照；后续写盘故障保存独立恢复事件，最终终态以恢复事件和本轮终端 JSON 为准。导出失败不重跑模型。磁盘完全不可写时无法保证有新文件，终端保留完整安全记录和已发生调用的统计。

Markdown 对原问题、结论和完整原文使用动态反引号围栏，避免正文自身的反引号破坏内容；元数据转义，PDF 链接来自程序核验后的绝对路径。`pdf_page` 是 PDF 文件页序，从 1 开始。

## 5. 实际验证范围

```powershell
# 离线：临时目录、真实临时 PDF、合成片段、假检索和 SDK MockTransport
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_answering
```

37 项检查通过，覆盖单/多篇完整配对、参数先行拒绝、JSON 与最新/历史一致、历史碰撞拒绝、精确原文围栏与绝对 PDF 链接、未知/全库未展示/预算省略/用户伪造引用、错论文/版本/页码/哈希、畸形结构/空响应/截断、无命中与工具错误、共享重试/修复/请求上限/截止时间、缺失 usage、资源构造和关闭故障、输入变化，以及导出失败后的费用与步骤保留。未读取 `.env`、未打开正式数据库、真实网络 0 次。

真实 CLI 首题使用新检索与新生成：5 条展示证据、4837 正文字符、3 条结论、5 次引用检查、2 个来源，真实 PDF 总页数 19，引用页序 1/2。纯 JSON 标准输出、最近 JSON 和不可覆盖历史内容一致，正式输入/源码前后不变。新增 embedding 1 次/34 tokens、聊天 1 次/2758 tokens，无修复/重试。见 [CLI 核验记录](/D:/course/paper-research-assistant/archive/run_logs/d5/answer_cli_verification_20261003_120147_728995_8ce78831d965.json)。

## 6. 两个来源/语义案例

案例一复用 ReAct D2-003 原正式 top-5。正文第 4 页列出 HotPotQA 和 FEVER，但题目指定“摘要”。手写“摘要提到了这两个基准”的反例可以通过引用定位检查，却缺少摘要来源依据。AI 复核建议本轮资料不足；题目本身仍是可回答题，不能把错误拒答计成成功。

案例二从 Reflexion D2-005 原候选中只选原 rank 3、第 2 页的真实片段做离线局部展示。它说明反馈转为文字总结并作为下一轮上下文，单独不能说明是否更新模型权重。手写完整结论也可通过定位检查，但只得到部分支持；AI 复核建议说明缺项并返回不足。原完整 top-5 的 rank 1 摘要有完整依据，本案例不冒充原检索整体不足。

两例的错误草稿是手写反例，建议结果不是新模型输出；0 API，新的人审 pending，不计入 37 项程序通过数或问答准确率。当前实现尚未自动判断所有语义支持与章节归属，F 要逐条评价答案与原文。

后续进度见 [F 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-F-evaluation-guide.md)：十题初跑保留，六题仍待人工复核后合并补跑。G 已完成工程汇总与 [D6 交接](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md)，D5 评测/人审仍待补。
