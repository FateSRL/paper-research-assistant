# D8 B：三动作结构、提示词与严格解析

完成日期：2026-10-05（Asia/Shanghai）。B 已完成；A 的初始策略保持不变，C–G 待执行。此次交付是供 C 接入的动作与消息接口，尚未运行完整 Agent。

新增两个业务模块：[动作模型与解析](/D:/course/paper-research-assistant/paper_assistant/agent_actions.py)、[Agent 提示词](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py)。新增离线检查脚本：[check_agent_actions.py](/D:/course/paper-research-assistant/scripts/check_agent_actions.py)。旧固定 RAG、检索、引用校验、页面和正式数据保持原样。

当前源码的 **42 项离线检查全部通过**，0 失败、0 错误、0 跳过；embedding、聊天、网络及 mock HTTP 发送均为 0。786 个受保护文件匹配，其中 781 个继承 A 的基线，另 5 个 A 交付物对照 A 原完成清单核对；8 项初始契约对齐检查通过。见 [当前检查报告](/D:/course/paper-research-assistant/artifacts/d8/agent_action_boundary_validation.json)、[保护与契约核对](/D:/course/paper-research-assistant/artifacts/d8/task_b_integrity.json) 和 [B 完成记录](/D:/course/paper-research-assistant/artifacts/d8/task_b.json)。检查数量不代表问答准确率，也不代表 D 的完整故障验证已完成。

## 1. 模型现在能表达什么

`AgentAction` 是以 `action` 为判别字段的三个严格分支。字段类型严格、分支禁止额外字段，外层模型冻结；`answer` 内部复用旧 `AnswerDraft/Claim` 并重新校验嵌套实例。契约版本为 `d8-agent-actions-v1`。

| 动作 | 必填数据 | B 校验 | 后续 C 执行 |
|---|---|---|---|
| `answer` | `answer` | 必须为 `status=answered`、非空 claims 和引用 ID | 回查本轮引用，合格后发布 |
| `retry_search` | `missing_information`、`retry_query` | 非空白字符串；最多 500、1000 Python 字符，原文字串保留 | 检查同查询、轮次、预算后才检索 |
| `insufficient_evidence` | `reason` | 非空白字符串，最多 1000 Python 字符 | 转为现有不足草稿 |

例如下面是合法的补查结构；这只是格式示例，不是一次真实模型输出或检索记录：

```json
{"action":"retry_search","missing_information":"缺少摘要中对应的表述","retry_query":"ReAct abstract reasoning acting synergy"}
```

回答分支形如 `{"action":"answer","answer":{"status":"answered","claims":[{"claim":"由证据支持的事实","citation_ids":["当前展示的chunk_id"]}]}}`。示例 ID 是占位符。通过结构检查不证明 ID 合法、来源符合摘要限制或事实得到支持；这些仍需引用回查及语义评价。

模型不能增加 `tool_name`、`top_k`、版本、路径等执行字段。原问题、论文原文、补查文本和旧模型输出均视为数据；提示词保留原问题的论文、版本、摘要和实验条件等限制，不要求长篇思考过程。

## 2. 阶段决定允许动作

阶段和证据是否存在由程序根据当前真实上下文传入，不能从模型输出读取。

| 当前阶段 | 有展示证据 | 无展示证据 |
|---|---|---|
| `initial_decision` | answer、retry_search、insufficient_evidence | retry_search、insufficient_evidence |
| `final_decision` | answer、insufficient_evidence | insufficient_evidence |
| 任一阶段的引用修复 | answer、insufficient_evidence | insufficient_evidence |

`allowed_actions(*, phase, has_shown_evidence, terminal_only=False)` 返回允许动作。`parse_agent_action(content, *, phase, has_shown_evidence, terminal_only=False)` 先严格解析结构，再检查阶段权限。补轮仍返回 `retry_search` 会得到 `action_not_allowed`，不会成为工具调用。

解析拒绝重复 JSON 键（包括嵌套）、NaN/Infinity/溢出的非有限浮点、Markdown 围栏、额外文本、未知动作、缺字段、额外字段和错误类型。`ActionParseError.code` 使用固定安全错误码，不把模型原文或 Pydantic 输入泄露到错误消息。常见码为 `empty_output`、`invalid_json`、`duplicate_json_key`、`non_finite_json`、`invalid_action_schema`、`action_not_allowed`。

`query_comparison_key(query)` 折叠空白并 `casefold()`，只供 C 比较是否重复。结构合法的同查询动作在 B 可以解析；C 必须在收费前与原问题及已执行查询比较，不能把折叠后的文字当作实际请求。

`action_to_answer_draft(action)` 只转换终止动作；补查动作会报 `non_terminal_action`。它重新展开并校验嵌套字段，没有调用第二次模型，也没有发布答案或证明引用合法。

## 3. 消息怎样绑定当前证据

`build_agent_messages(question, context, *, phase, terminal_only=False)` 返回 system/user 两条消息。先复用旧 `context.build_messages()` 校验原问题一致、版本配对、原文哈希、证据 ID、完整 chunk 和字符预算，再替换旧 D5 的输出协议。不会同时放入互相冲突的 AnswerDraft 与 AgentAction system 提示词。

user JSON 包含原问题、实际 `shown_evidence`、`allowed_citation_ids`、阶段、允许动作、分支结构及版本。Agent 提示词版本为 `d8-evidence-agent-actions-v1`。B 另外限制首轮最多 5 条展示证据、补后最多 8 条；合并顺序、去重及候选选择由 C 实现。

最终 context 的 question 必须仍为原问题，不能替换成补查 query。轮次与原 rank/score 等轨迹放在 C 的外层记录，引用校验用符合旧契约的 context。新消息不会修改调用者传入的 context。

## 4. 修复接口与权限必须一起使用

`build_action_repair_messages(question, context, previous_content, *, phase, error_code, repair_kind="format")` 返回四条消息：system、当前证据 user、旧输出 assistant、修复要求 user。旧输出是待纠正的数据，当前证据和白名单保持一致。

| repair_kind | 修复含义 | 动作权限 |
|---|---|---|
| `format` | JSON 或字段结构不合法 | 保持当前阶段权限 |
| `action` | 动作不在当前允许范围 | 保持当前阶段权限 |
| `citation` | 引用回查不通过 | 当前阶段也只能终止，禁止 retry_search |

引用修复消息自动设置 `terminal_only=True`；**C 解析该修复响应时也必须传入 `terminal_only=True`**，不能只依赖提示词。格式/动作修复的解析使用 `False`，最终阶段本身仍禁止补查。`error_code` 只接受最多 64 字符的安全小写代码，不接受原始异常全文。

本接口只构建消息。共享一次修复额度、三次聊天尝试、网络重试和 deadline 均需由 C 通过同一个 `ChatBudget/RecordedLLM` 强制执行；B 没有实际执行修复请求。

## 5. 离线检查、失败现场与修复

检查使用合成证据和真实动作解析/消息构造，覆盖严格 JSON、字段、阶段、空证据、证据哈希、条数、修复权限、原问题约束、输入不变及终止转换。没有加载 `.env`，没有打开正式 SQLite/Qdrant，也没有使用冻结验收题。

所有运行都保留在 [D8 运行日志目录](/D:/course/paper-research-assistant/archive/run_logs/d8)：

| 运行 ID | 实际结果 | 说明 |
|---|---|---|
| `20261005_042757_954285` | 35 个方法，6 个失败条目 | 检查夹具误把修复消息数写成 2；实际接口为 4，已修正夹具 |
| `20261005_042919_214336` | 41 个方法通过 | 当时覆盖；之后加入独立审查发现的嵌套实例回归 |
| `20261005_043007_196779` | 42 个方法，2 个失败条目 | 暴露字典内构造/修改后的 Claim 实例可能跳过校验 |
| `20261005_043112_166345` | 42 个方法全部通过 | 当前源码；嵌套字段展开重验后回归通过 |

计数是 unittest 方法数，失败条目可来自 subTest，不与题目数混用。独立审查复核了修复：字典内或现有草稿内不合法 Claim 被拒绝，合法草稿仍接受。旧失败记录未覆盖，当前报告绑定五个源码 SHA。

可在项目根目录重跑以下离线命令，每次保存新的历史记录，并刷新当前检查报告：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_agent_actions
```

无需配置密钥或付费调用。A 指南和记录保存当时状态，其中“B 待执行”是历史描述；最新阶段状态见本指南和 D8 总计划。

## 6. 你怎样检验、C 怎样接入

建议先花约 15–20 分钟阅读两个模块，再运行上述命令。你应能解释下面四题；当前没有测量你的学习程度，也没有新增人工验收确认。

1. 为什么合法 JSON 仍可能是非法动作？请指出补轮 retry_search 的拒绝位置。
2. 没有展示证据时为什么禁止 answer？这个判断来自哪里？
3. 为什么首轮引用修复也不能补查？消息和解析器分别怎样限制？
4. 为什么一个结构合法、带 citation_ids 的 answer 仍不能直接发布？

C 接入顺序：用原问题和真实 context 构造消息；通过共享 `RecordedLLM.invoke(purpose="answer", require_json=True)` 请求，随后用本解析器校验动作。`require_json` 只检查语法，不代替动作解析。若需修复则先预留共享预算，调用 purpose=`repair`，按同样的阶段/terminal_only 重新解析。

补查动作还需 C 检查重复查询、剩余额度与轮次；C 保存两轮统计、合并完整证据并检查新增展示，最后调用已有引用业务校验。C–G 尚未执行，四题成对冒烟、实际代价及收益仍未测量；验收集继续留到 D11。
