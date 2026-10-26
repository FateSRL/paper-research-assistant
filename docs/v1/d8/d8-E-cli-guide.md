# D8 E：独立命令行、运行导出与成对比较接口

执行日期：2026-10-05。E 完成 CLI、完整记录、共享首轮的成对 runner 和多轮事后评分。真实四题实验属于 F，本次没有调用真实 embedding 或聊天 API。D7 继续暂缓，验收题仍留 D11；页面继续使用固定 RAG。

## 1. 本次可以使用什么

`scripts.answer_question_agent` 可提交一个问题及 1–3 个完整论文/解析版本。它打开既有 ready 索引和只读 SQLite，关闭本轮聊天客户端及库资源；全过程启动同一预算，配置、检索、判断、修复、引用回查与关闭后的截止检查都计入。实际公开模型、index profile 和执行上限必须匹配 A 的初始策略。记录不含密钥或认证头。

五种终态为 `answered`、`insufficient_evidence`、`tool_error`、`invalid_output`、`budget_exceeded`。前两种且导出完成退出 0；执行或导出失败退出 1；命令参数不合法退出 2，参数检查不发请求、不生成问答记录。`answered` 表示结构和引用定位通过，语义支持仍待评阅。

JSON 包含原问题、版本、公开配置、policy、源码/data/eval SHA、每轮检索与展示上下文、实际消息/响应/动作、修复、引用检查、补查原因和停止原因、SDK/HTTP 尝试及供应商 usage。Markdown 展示问题、答案/不足、实际来源及 PDF 文件页序、补查和用量。用量缺项保留 `null`，另存已知小计；失败和导出失败仍保留已发生调用。

| 用途 | 路径 |
|---|---|
| Agent 最近记录 | `artifacts/d8/agent_result.json/.md` |
| D8 固定 RAG 最近记录 | `artifacts/d8/fixed_rag_result.json/.md` |
| 两种模式不可覆盖历史 | `archive/run_logs/d8/agent_<run_id>.json/.md`、`fixed_rag_<run_id>.json/.md` |
| 导出失败独立恢复事件 | 同一历史目录下的 `*_export_failure_<唯一ID>.json` |
| 成对批次 | `artifacts/d8/comparison/<batch_id>/` |

D5/D6 的最近记录、首次结果和旧评分器保持原样。旧 B/C/D 检查报告绑定当时源码，E 的当前检查报告单独保存。

## 2. 先做零费用检查

在项目根目录 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.answer_question_agent --help
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --help
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_agent_cli
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_agent_comparison
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_agent_evaluation
```

当前E检查共119个方法执行通过：CLI41、成对43、评分19、导出兼容16，其中14个为D记录适用回归、105个为E新增方法；101次SDK模拟HTTP、真实API/网络0。另有 `scripts.check_agent_export_modes` 可复跑16个适用导出检查。上述检查使用临时 PDF、合成检索与 SDK MockTransport，禁止真实网络；每次保留独立日志。它们检验控制、记录和评分接口，不证明模型能答对开发题。最终方法数、模拟 HTTP 和源码 SHA 见 [E 完成记录](/D:/course/paper-research-assistant/artifacts/d8/task_e.json)。

以下成对命令只准备新批次，不读 `.env`、不打开正式数据库、不发模型请求。名字应换成未使用的新 ID：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --batch-id d8_my_prepare_001
```

默认选四道正式开发题 `D2-001 D2-002 D2-003 D5-006`。manifest 冻结原题与事后标注、公开配置、ready 配对、源码/data/eval/A策略 SHA；验收文件仅作 SHA 绑定，不解析题目用于运行或调参。本次已用正式资料执行零费用准备：`d8_e_interface_prepare_20261005`，默认四题及169个正式输入/A策略文件绑定通过，重复批次被拒且原manifest不变；未打开正式库或读取环境配置，见 [准备核对](/D:/course/paper-research-assistant/artifacts/d8/agent_formal_preparation_validation.json)。准备成功不是 F 实验完成。

## 3. 后续真实执行的命令

以下命令会使用供应商 API 配额，留给 F 或明确需要的独立问答。E 本次只验证其接口。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.answer_question_agent --query "What components does a RAG model combine?" --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d --json
```

多篇使用重复 `--version PAPER_ID PARSE_REVISION`；不能和单篇参数混用。首轮/补轮 top-k 固定 5，完整正文预算默认 8000；同一运行最多一次补查，聊天三次 SDK 尝试、一次修复和一次网络重试共享。

执行已准备批次：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --batch-id d8_my_prepare_001 --execute-prepared
```

也可用一个新 ID 配 `--live`，先准备后立即执行。每题在请求前独占写入 `.attempt.json`。批次遇到故障或任一模式异常就保存现场并停止；先看 `state.json`、`summary.json` 和 `failure_*.json`。同一批次需要继续时，`--resume` 只处理未尝试题，公开配置、源码及正式输入必须不变。已尝试题不会再次请求；有预占但无最终题记录、孤立题记录或绑定不一致时拒绝执行，需先检查现场。模型失败不能用同名批次悄悄重跑。

## 4. 成对比较怎么检验

每题实际首轮检索一次。`FrozenFirstSearcher` 校验原快照及调用的 query、完整配对、top-k，给两种模式独立深副本；固定模式不能补查，Agent 最多再检索一次。期望要点、标注引文、case_id 和可答标签在模型结束后用于评分，问答核心只接收原问题与配对。

两模式独立预算。若首轮检索实耗 20 秒，固定 RAG 开始时剩 100 秒；固定模式随后耗 25 秒，Agent 开始时仍剩 100 秒。各自初始化、消息判断、修复和关闭耗时扣本模式额度；首轮已耗完 120 秒则两模式均不创建聊天客户端。阶段检查及聊天剩余超时已经实现，同步 embedding 30 秒超时和 PDF 检查尚未统一硬中断，不能声称进程严格在 120 秒结束。成功导出保存核对结束时的结果快照，写盘耗时没有额外的成功状态截止重判。

看 `pair.costs.actual_batch`：实际 embedding 为一次共用首轮，加一次可能的 Agent 补轮，聊天按两客户端实耗相加。看 `standalone_logical`：每种模式各计一次首轮，Agent 补查则逻辑 embedding 为两次。逻辑成本不能相加当作实际批次请求，也不能把“共用首轮组件 + 本模式实耗”称为两次独立实测墙钟时间。

新事后评分分别统计 `initial_returned`、`initial_shown`、`retry_returned`、`retry_shown`、`merged_returned`、`final_shown`。补轮独立 shown 是诊断快照，真正最终发给模型的证据是合并后 context。命中要求标注原文、PDF SHA、文件页序、完整配对以及真实候选全文/哈希匹配；只返回但最终未展示仍算 shown 未命中。补轮未执行为不适用，尝试失败保留在适用分母。引用定位、标注引文命中、程序完成率都不是 QA accuracy。

## 5. 你需要做什么或学习什么

建议约 20 分钟：先读前四节，再运行三份零费用检查，然后查看对应 JSON。重点能自己说明这五点：

1. CLI 的 0/1/2 分别表示什么；为什么不足也可以退出 0。
2. 首轮花 20 秒、另一模式花 25 秒时，Agent 为什么还剩 100 秒。
3. 首轮与补轮各一次时，实际 embedding 是 2 次，逻辑两模式分别是 1 和 2 次。
4. 为什么 Returned 命中而 Final Shown 未命中不能算已展示依据；引用合法为什么不能等同正确答案。
5. 为什么导出失败仍要保留调用费用，以及已预占的题不能同批次自动重跑。

你不需要在 E 自己发真实问答。F 完成后再核对四题真实轨迹，逐条比较结论与 PDF 原文、原问题的限定条件，检查资料不足是否合理。使用者理解、人工复核、真实收益和最终验收均未在 E 测量。
