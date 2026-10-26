# D5 任务 C：证据上下文、提示词与结构化草稿

完成日期：2026-10-02（Asia/Shanghai）。任务 C 已完成，D 的引用业务校验与完整问答流程仍待实现。依据：[D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md) 与 [B 聊天接口](/D:/course/paper-research-assistant/docs/v1/d5/d5-B-llm-guide.md)。

后续进度：D 已完成，见 [任务 D 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-D-rag-guide.md)。本文与 C 机器记录保留当时的草稿 `pending` 状态；D 的离线回查和新真实运行另存，没有改 C 的旧报告。

38 项核心离线检查通过；三组 D4 候选完成离线回放。固定 RAG 首题的新检索与真实生成返回 `draft_valid`：展示 5 个完整片段、4837 个正文字符，草稿包含 3 条结论。问题 embedding 1 次、34 tokens；聊天 1 次、输入 2539 + 输出 219 = 2758 tokens，无网络重试、无格式修复。这些是本次真实用量，不计入 B 的旧连通用量。

`draft_valid` 表示草稿结构通过。草稿内部 `status="answered"` 仍须交给 D 回查引用；C 尚未发布最终答案或计算问答准确率。完成记录见 [task_c.json](/D:/course/paper-research-assistant/artifacts/d5/task_c.json)，本次真实结果见 [generation_smoke.json](/D:/course/paper-research-assistant/artifacts/d5/generation_smoke.json)。

## 1. 新代码放在哪里

| 文件 | 接口与职责 |
|---|---|
| [context.py](/D:/course/paper-research-assistant/paper_assistant/context.py) | `select_context()`、`prepare_context()`、`build_messages()`：选证据、保存快照、生成消息 |
| [generation.py](/D:/course/paper-research-assistant/paper_assistant/generation.py) | `parse_answer_draft()`、`generate_draft()`：严格解析、借用 B 生成与有界格式修复 |
| [preview_context.py](/D:/course/paper-research-assistant/scripts/preview_context.py) | 回放 D4 三组旧候选，生成默认/较小字符预算示例，0 API |
| [smoke_generation.py](/D:/course/paper-research-assistant/scripts/smoke_generation.py) | 显式 `--live` 执行固定首题的新检索和草稿生成，保存实际过程 |
| [check_generation.py](/D:/course/paper-research-assistant/scripts/check_generation.py) | 38 项核心离线边界，用真实 SDK 与 MockTransport |

现有 `schemas.py`、`search.py`、`llm_client.py`、配置、embedding、存储与向量模块保持原样；未安装新依赖。C 复用 `AnswerDraft`，不会另建一套回答字段。

## 2. 检索候选怎样变为展示证据

`prepare_context(search_result, max_chars=8000)` 接受 `EvidenceSearcher` 的 `success` / `no_hits` 返回值，读取原问题、选定论文/版本与 `results`。错误检索状态、候选数矛盾或非法参数先失败，不发聊天请求。

选择规则固定为：按 rank 稳定排序 → 按 chunk ID 去重 → 依次放完整 chunk → 首个无法容纳的唯一片段起停止。不会跳过大块再装低 rank 的小块。`max_chars` 只能是 1–8000 的整数，统计原始 `shown_text` 的 Python 字符数，包括空格、换行；不冒充 token，也不包含 JSON 字段和系统提示词长度。

所有候选都会先核对非空身份、完整论文/版本配对、页序、rank、有限 cosine 分数及原文 SHA，省略的候选也不能带着损坏数据混过去。同一 ID 原文或身份冲突时明确失败；相同 ID/原文重复时仅展示首次。此处检查传入候选的内部一致性，真实库与 PDF 来源回查留给 D。

每条展示快照保存：

```text
chunk_id, paper_id, parse_revision, pdf_page, rank, score, text_sha256
shown_text, shown_char_start=0, shown_char_end=len(text), shown_text_sha256
```

正文不截断、不改写。全片段的两个文本 SHA 一致；允许引用集合只由 `shown_evidence` 的真实 ID 派生，候选但未展示、问题中伪造的 ID、题集期望引文均不会扩大集合。另存 `omitted_evidence` 和 `duplicate` / `character_budget` / `after_budget_stop` 原因。

`build_messages()` 再核对快照、允许集合、计数、范围及字符预算，输出独立的 system/user 消息；候选、快照和消息互不持有可变共享引用。

## 3. 提示词与草稿规则

提示词版本为 `d5-evidence-answer-v1`。系统消息规定只用展示证据、每条事实提供引用、满足摘要/实验设置/版本等来源限定、证据不足说明欠缺，不把相似度当可信概率。用户问题和论文正文在 user 消息中按 JSON 数据编码，不能作为扩大范围或执行工具的指令。此做法配合后续程序校验；离线检查不能证明模型在所有输入下都遵守提示词。

模型只返回 `AnswerDraft` 字段，程序来源、页码与错误终态由后续业务层产生。严格 JSON 解析拒绝围栏、额外文字、重复键、NaN/Infinity/浮点溢出；Pydantic 再拒绝未知字段、无引用结论、空 `answered` 与状态矛盾。错误摘要使用固定 code，不复制可能含敏感输入的 Pydantic 异常正文。

例子：`{"status":"answered","claims":[{"claim":"简短结论","citation_ids":["本轮展示ID"]}]}`。结构允许 `answered` 附带 `reason`；现有 schema 会清理草稿字符串首尾空白。伪造的非空 ID 可以通过结构检查，所以不能省略 D。

| 生成结果 | 含义 |
|---|---|
| `draft_valid`，草稿为 `answered` | 结构通过，`citation_validation_status=pending` |
| `draft_valid`，草稿为 `insufficient_evidence` | 合法资料不足草稿，无事实引用，`not_applicable` |
| `invalid_output` | 结构/输出检查失败，修复后仍错或已无修复额度 |
| `tool_error` | 上下文、模型服务或本地资源故障，不包装成资料不足 |
| `budget_exceeded` | 请求数或截止时间已耗尽，没有可发布草稿 |

无展示证据时不调用聊天模型：没有候选说明本次无命中；候选未能放入字符预算说明本轮无可展示依据，两者都不声称论文没有相关内容。

## 4. 怎样接入后续 D

```python
from paper_assistant.context import prepare_context
from paper_assistant.generation import generate_draft
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM

policy = ChatPolicy()
budget = ChatBudget(policy)  # 在整轮检索前建立；检索前后也检查截止时间
# search_result = searcher.search_evidence(question, selected_versions, top_k=5)
context = prepare_context(search_result)
with RecordedLLM(policy=policy, budget=budget) as client:
    result = generate_draft(context, client)
    # D 使用 result['draft'] 与 context['shown_evidence'] 回查引用。
    # 如 C 未使用修复额度，D 可用同一 client/budget 做一次引用修复。
```

`generate_draft()` 借用客户端，不擅自打开/关闭或重置预算。空响应、截断、非法 JSON、草稿结构错误最多触发一次 `purpose="repair"`；保留原始 system/user 数据，附上已脱敏输出与安全错误 code。网络重试由 B 决定，C 不另写网络循环。服务/鉴权故障直接失败。

格式修复与 D 的引用修复全轮共用一次额度；总聊天 SDK 尝试最多三次。生成阶段前、B 请求前后、结构解析结束后检查 deadline；超时清空有效草稿。这是阶段检查，仍不保证同步请求在第 120 秒精确中止。

每次生成保留 `generation_attempts` 中的实际 messages、response 和 `parse_error_code`；共享 `statistics` 只汇总一次，不能把两次调用中累计统计重复相加。

## 5. 已执行验证与复现命令

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
# 离线：三组旧候选与较小预算示例，不请求服务
.\.venv\Scripts\python.exe -X utf8 -m scripts.preview_context
# 离线：合成证据、真实 SDK + MockTransport，不加载 .env/正式库
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_generation
# 离线：临时目录与假资源，检查关闭故障时计数和结果保留
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_generation_smoke
# 已执行过；再次运行会消费服务额度
.\.venv\Scripts\python.exe -X utf8 -m scripts.smoke_generation --live
```

38 项核心检查通过，25 次模拟 HTTP 发送、真实网络 0 次。覆盖排序/去重/Unicode、精确预算与停止、完整配对与哈希、快照篡改、只发送展示证据、JSON/schema、安全错误、空证据零调用、一次修复、网络重试共享预算、鉴权失败与解析后超时。见 [generation_boundary_validation.json](/D:/course/paper-research-assistant/artifacts/d5/generation_boundary_validation.json)。失败的首轮历史记录保留。

另 8 项 smoke 记录检查通过，使用临时目录和假资源，真实网络 0 次。SQLite、Qdrant、向量借用层或聊天客户端关闭失败时，已发生的费用和原始结果仍保留，故障不会被输出为成功。

离线回放 RAG / ReAct / Reflexion 分别展示 4837 / 2483 / 4217 个正文字符；较小预算示例明确省略后续候选。见 [context_preview.md](/D:/course/paper-research-assistant/artifacts/d5/context_preview.md)。这不是新检索，旧 embedding 用量不计作本次请求；未补入 ReAct 缺失的摘要。

真实首题输出 219 tokens，finish_reason 为 `stop`，1200 输出上限能容纳这一个样本；其余题目与质量仍待 F。真实脚本随后补了资源关闭故障时即时保留计数/结果的记录逻辑，该修订使用独立离线检查验证，没有重复付费；原真实结果及对应脚本源码字节保留在历史目录。最新故障记录检查见 [generation_smoke_boundary_validation.json](/D:/course/paper-research-assistant/artifacts/d5/generation_smoke_boundary_validation.json)。

正式论文、chunks、SQLite/Qdrant、题集和旧 D4/A/B 报告保持原状。本次检查与真实运行分别绑定自己的源码 SHA，后续源码不能直接冒充旧运行版本。

下一步 D：检查引用是否在本轮展示集合，并通过 SQLite 回查真实 ID、论文/处理版本、页码与文本哈希；通过后再输出可回查的答案。不能将 C 的结构通过当作引用存在或语义支持的证明。
