# D11 A：论文信息工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**A 已完成实现。** 本日志记录实际修改；学习步骤不表示用户已学习或通过。D11 的离线验证和旧失败回放集中记在 [C 日志](/D:/course/paper-research-assistant/docs/v1/d11/d11-C-evidence-body-guide.md)，本文件不重复运行或生成验证产物。

## 1. 实际完成什么

新增 [load_paper_information()](/D:/course/paper-research-assistant/paper_assistant/paper_information.py:8)，读取每个所选论文/解析版本的已有 chunks，用其中保存的 `title` 提供论文身份。核定摘要来自已有来源 Registry 的 `qualified_chunk_ids()` 对应正文，逐段保留 `chunk_id`、`pdf_page`、`text`，形成 `abstract_passages`。没有独立摘要字段时，不生成或假设存在元数据摘要；没有 Registry 时，摘要列表为空。

[answer_question_agent()](/D:/course/paper-research-assistant/paper_assistant/agent.py:334) 在一次问答开始时加载所选版本的正文，再将这份读取结果同时复用于论文信息与本地邻接阅读。论文信息保存为运行结果的 `paper_information`，并传入首轮、补查后最终决策和修复消息。消息中的字段名是 `selected_papers`。

标题和摘要用于帮助模型识别论文主题、生成补查查询，**不会自动加入回答证据或引用允许集**。即使模型在 `selected_papers` 看到了某段摘要，要引用它回答，也必须让该原文实际进入当前 `shown_evidence`。这样不将背景输入冒充本轮已检到的依据。

本任务没有重新解析、导入或生成论文向量，也没有新增摘要模型调用。严格原文回答规则继续使用；模型知识补充回答安排在 D12。

## 2. 怎样学习：约 20 分钟

1. 读 `load_paper_information()`：找到标题从哪里来、摘要 ID 如何选出、为什么保持原始段落而不是另写摘要。
2. 读 `agent.py` 的 `stage = "paper_information"` 和 `version_chunks`：画出“所选版本 → 一次读取 → 论文信息/正文阅读”的数据流。
3. 读 [build_agent_messages()](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:100)：比较 `selected_papers`、`shown_evidence`、`allowed_citation_ids` 三个字段的职责。学习时阅读已保存内容即可。

## 3. 关键问题与答案

**为什么只给论文 ID 不够？** ID 负责确定语料范围，不直接告诉模型论文讨论什么。标题和真实摘要提供主题、方法名和术语，使“介绍这篇论文”这样的简短问题有具体补查背景。

**摘要来自模型生成吗？** 不是。读取已有核定摘要 chunks，保留原文和定位。原文中存在重叠时也不擅自拼接成一个新文本，从而保持来源可解释。

**为什么读到摘要仍不能随便引用？** 论文背景用于规划检索；当前引用规则要求结论对应实际展示证据。不能用背景中的 ID 绕过本轮引用允许集。离线验证确认读取和传递，不证明模型已经答对；本轮未新测真实模型效果。
