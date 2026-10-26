# D11 B：缺口化补查工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**B 已完成实现。** 新提示仍使用现有 Agent 决策调用；没有新增分类、摘要或查询生成调用。最终离线验证见 [C 日志](/D:/course/paper-research-assistant/docs/v1/d11/d11-C-evidence-body-guide.md)。

## 1. 实际完成什么

在 [AGENT_SYSTEM_PROMPT](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:21) 中要求模型结合 `selected_papers` 和当前证据，围绕实际 `missing_information` 生成 `retry_query`。查询包含与缺口有关的主题、方法或实体；使用论文正文语言，并保留技术名、缩写。只列“摘要、方法、贡献、结论”或只换一种说法，都不足以表达论文主题。

概述问题需要研究问题、方法、贡献和结果；作者问题可以将姓名作为有效证据。这些要求放在同一决策提示里，不另建关键词分类路由，也不把 RAG 论文答案、题号或目标 chunk 写进规则。

普通、补查后及修复消息均继续传入论文信息。[build_action_repair_messages()](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:124) 使用同样的当前信息和阶段权限，修复没有扩大补查次数。`reading_origins` 还向模型说明哪些正文是从检索锚点邻接读到的，以及其分数沿用锚点。

实际提示版本为：

| 场景 | 版本 |
|---|---|
| 普通 Agent | `d11-paper-informed-agent-v1` |
| 使用来源范围 Registry | `d11-paper-informed-source-scoped-agent-v1` |

一次补检索、三次共享聊天尝试、原论文/版本范围及严格原文回答规则保留。D11 没有实现“无原文仍用模型知识回答”，该项属于 D12。

## 2. 怎样学习：约 20 分钟

1. 读系统提示的 `selected_papers` 和 `For retry_search` 两段，用中文复述“论文主题＋实际缺口＋正文术语”。
2. 读 [build_agent_messages()](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:100)，确认它只组织消息，并不执行检索。
3. 到 [agent.py](/D:/course/paper-research-assistant/paper_assistant/agent.py:349) 顺着 `retry_decision`、`retry_gate`、`retrieve(action.retry_query, 2)` 走读：原问题用于回答，补查查询用于搜索，程序负责范围和次数。

## 3. 关键问题与答案

**补查不就是把问题换个说法吗？** 这次要求补充可搜索的信息。例如选定论文研究检索增强生成，缺方法时查询应包含论文相关方法名和缺失关系；仅将“介绍论文”改成“论文讲了什么”仍缺少主题。

**是否增加了一次模型调用来判断概述问题？** 没有。现有首轮 Agent 决策同时判断证据需求并给出补查查询，复用现有动作和预算。

**改提示后，模型一定会带主题词吗？** 提示引导这个行为，不能保证每次遵守或一定召回答案。程序仍控制动作、范围、预算与引用，语义效果需要实际输出判断。

