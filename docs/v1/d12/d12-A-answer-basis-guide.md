# D12 A：回答依据工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**A 已完成实现。** 本日志记录实际修改，学习步骤不表示用户已学习或通过。实际离线验证在 [C 日志](/D:/course/paper-research-assistant/docs/v1/d12/d12-C-display-export-guide.md)集中记录，不另生成验证报告。

## 1. 实际完成什么

[Claim](/D:/course/paper-research-assistant/paper_assistant/schemas.py) 增加逐条 `basis`，可取 `paper_evidence`、`model_knowledge` 或 `analysis`。旧记录缺省 `basis` 时沿用 `paper_evidence`，保留已有数据含义；新的非论文内容应明确写出依据。

| 依据 | 内容 | 引用规则 |
|---|---|---|
| `paper_evidence` | 由本轮展示原文支持的论文事实 | 必须至少一个本轮允许的 `citation_ids` |
| `model_knowledge` | 模型已有的一般知识 | `citation_ids` 必须为空，不附任意论文引用 |
| `analysis` | 模型的解释、建议或推论 | 可以引用原文前提，也可以无引用；有前提引用不表示推论就是论文结论 |

不同依据的内容应拆成不同条目。比如原文说明使用检索器，接下来解释检索器的一般原理，两条分别标明原文和模型知识。若推测某个方法的适用场景，应写清是在分析，并避免把推测说成论文实验已经验证。

[固定 RAG 提示](/D:/course/paper-research-assistant/paper_assistant/context.py)与 [Agent 提示](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py)要求给出非空有用回答；空证据或无关证据时可以解释概念、分析问题或给出具体阅读方向，不能只给“资料不足”。论文具体作者、方法、结论和数字在没有展示依据时不能冒充核实事实。摘要限定等来源要求仍约束论文事实和引用，模型知识不能替代用户要求的摘要证据。

`answer_evidence_status()` 记录回答依据组成，`none` 表示没有论文引用、`paper_only` 表示条目均为原文依据、`mixed` 表示存在引用且有模型补充/分析。这是结构描述，不是事实准确率或检索充分性评分。

固定 RAG 提示版本为 `d12-useful-answer-v1`，来源限定版本为 `d12-useful-source-scoped-answer-v1`；Agent 为 `d12-useful-paper-informed-agent-v1` / `d12-useful-paper-informed-source-scoped-agent-v1`，动作契约为 `d12-agent-actions-v1`。活动流程要求 `answered`；旧 `insufficient_evidence` 数据结构仍保留用于读取历史，不能作为本轮正常决策的终态。

## 2. 怎样学习：约 20 分钟

1. 读 `schemas.py` 的 `Claim.check_basis()`：对照表格说明哪些条目必须有引用，哪些不允许有论文引用。
2. 读 `context.py` 的 `SYSTEM_PROMPT`、`agent_prompt.py` 的系统提示：比较“有原文就引用”和“无原文仍给解析”的分工。
3. 读 [validate_citations()](/D:/course/paper-research-assistant/paper_assistant/citations.py)：引用回查只验证实际引用的来源，不能证明整句事实一定正确。分析引用的前提依旧需要可回查。
4. 读 `answer_evidence_status()`：用一条原文事实、一条一般解释和一条推论分别口头描述结构，不需要重复调用模型。

## 3. 关键问题与答案

**只改提示词够吗？** 不够。旧结构要求每条结论带引用，空证据分支还会提前停止。D12 同时改变逐条依据、两模式控制流和消费者展示，才能让不带论文引用的有用回答通过整个流程。

**无引用回答会被当作论文已证明吗？** 不会按原文支持发布。一般知识标为 `model_knowledge`，解释与推论标为 `analysis`；既有原文引用仍只来自本轮实际展示允许集。结构允许补充知识，不保证模型知识天然正确。

**分析带引用为什么仍叫分析？** 引用可支撑推论使用的前提，但推论由模型形成。例如论文说方法减少一次检索，模型分析它可能降低调用成本；前提有据不等于论文已经测得具体费用下降。依据标签与引用回查分别表达这两件事。
