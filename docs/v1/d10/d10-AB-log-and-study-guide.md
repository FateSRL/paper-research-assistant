# D10 A/B：工作日志、学习路线与参考答案

执行日期：2026-10-07（Asia/Shanghai）。A/B 已完成问题定位和提示改动；C–G 待执行。本日志记录已经发生的工作，学习安排是建议，不表示用户已学习或确认通过。

## 1. A 工作日志：定位为什么有引用仍未答全

A 使用 D9 已保存的 [D2-002 原始结果](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/D2-002.json)和[方法题 AI 初审](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/ai_review_mechanism_abstract_cases.md:14)，没有重新调用模型复现旧失败。

| 对照项 | 实际观察 | 对定位的意义 |
|---|---|---|
| 原问题 | 比较 RAG-Sequence / RAG-Token 如何使用检索文档 | 需要一般生成机制的依据 |
| 首轮展示 | 5 条、554 字符，涉及结果表、长度 1 时分类等价、测试时解码近似 | 有相关事实，但没有所问的一般文档使用机制 |
| Agent 动作 | 初始阶段允许补查，却直接选择 `answer`；没有执行补查 | 现有补查能力已经存在，本轮没有使用 |
| 两条结论 | 解码近似方法不同；长度 1 时模型等价，均有实际引用支持 | 事实有据，但没有覆盖原问题 |
| 固定 RAG | 根据该展示说明证据不足 | 拒答与本轮证据相符；这道可答题仍未完成 |

定位结果：优先改进 Agent 对“所问内容是否已有证据”的判断及回答目标。负责位置是 [agent_prompt.py 的 AGENT_SYSTEM_PROMPT](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:21)。这一步没有发现需要新增完整性判定器、增加检索轮次或更换模型的依据。

A 已明确本轮修改范围：现有 Agent 系统提示和实际提示版本。标准答案只用于解释旧结果为什么不完整，没有加入问答输入，也没有按题号或目标 chunk 选择行为。

## 2. B 工作日志：用现有动作处理缺口

B 在同一系统提示中增加了下面的决策要求，初始决策、补查后决策和修复消息都会使用它。

| 当前情况 | 提示要求 |
|---|---|
| 展示证据支持原问题的所有必要部分 | 直接回答；不因为有补查能力就强制补查 |
| 比较、机制或多部分问题只有相关事实或特例 | 不能拿这些事实替代原问题所需的机制或关系 |
| 缺少必要依据，选定论文内可以寻找，且当前允许 `retry_search` | 使用已有一次补查，查询针对缺少的信息 |
| 选定范围不能提供所问信息 | 说明证据不足 |
| 补查后或不能继续补查时仍缺必要依据 | 说明本轮不足，不编造缺失部分 |

修改文件只有 [agent_prompt.py](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:19)；同时更新了两个版本常量：

| 使用场景 | 原版本 | 当前版本 |
|---|---|---|
| 普通 Agent 消息 | `d8-evidence-agent-actions-v1` | `d10-question-complete-agent-v1` |
| 带来源要求的 Agent 消息 | `d9-source-scoped-agent-v1` | `d10-source-scoped-agent-v1` |

现有 `build_agent_messages()` 把对应常量写入消息的 `prompt_version`，`answer_question_agent()` 把它写入运行结果。没有增加新的输出字段；版本号用于区分实际使用的提示，不能证明答案正确。

固定 RAG、动作 JSON、引用与来源规则、top-5、8000 字符、一次补查、最终最多 8 条证据和调用预算沿用现有实现。提示负责引导选择；允许动作和实际调用仍由原程序控制。

实际验证：上一轮仅对修改后的 `agent_prompt.py` 做了一次 AST 语法解析，结果为 `syntax OK`、退出码 0。没有运行测试、哈希审计、真实聊天或 embedding，也没有新建实验批次。本次补日志只改文档，复用这项语法结果，不重复执行。

B 的完成含义是提示改动已经落到代码。新版本是否会对 D2-002 补查并完整回答，需要 D 的真实开发输出和 E 的语义评价判断；现在没有新的问答成绩。

## 3. 你怎样学习：按一次决策走读，约 45 分钟

只需要掌握 Python 字符串、字典、列表、条件判断、函数参数和 `import`。先读下面几个位置，不必通读整个项目或补完一门 Agent 课程。

1. **5 分钟：先读失败，不先读代码。** 打开方法题 AI 初审的 D2-002 段。分别说出“题目要什么”“本轮展示了什么”“实际回答了什么”。这里最关键的区别是：句子正确，仍可能没有回答题目。
2. **10 分钟：读新增提示。** 从 [agent_prompt.py:33](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:33) 的 `Choose answer only when...` 开始，读到 `For answer...` 之前。把它用中文复述成“证据足够直接答；缺依据且有用的补查被允许时补查；无法补齐时说明不足”。
3. **10 分钟：读消息怎么构造。** 看 [build_agent_messages()](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:87)：`system` 是行为规则，`user` 的 JSON 保存原问题、实际展示、允许引用和动作；注意 `phase`、`allowed_actions` 和 `prompt_version`。再看 [build_action_repair_messages()](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py:108) 怎样复用相同系统提示。
4. **10 分钟：读谁真正控制动作。** 看 [allowed_actions()](/D:/course/paper-research-assistant/paper_assistant/agent_actions.py:85)和 [parse_agent_action()](/D:/course/paper-research-assistant/paper_assistant/agent_actions.py:103)，再到 [answer_question_agent()](/D:/course/paper-research-assistant/paper_assistant/agent.py:60) 搜索 `initial_decision`、`retry_gate`、`retry_retrieval`、`final_decision`。按顺序理解：请求模型给动作 → 程序解析 → 检查补查条件 → 执行检索 → 最终决策。
5. **10 分钟：做下面的题并对照答案。** 能解释为什么同一段提示在初始阶段可以引导补查，在最终阶段却不能再补查，就理解了提示和程序权限的区别。学习时读保存记录即可，不必运行真实请求。

走读顺序可以记为：原问题和展示证据 → 构造消息 → 模型选择动作 → 程序限制与执行 → 引用检查 → 事后判断是否答全。

## 4. 练习与参考答案

### 题 1：D2-002 的两条结论都有引用，为什么仍算没有完成？

**参考答案：**引用支持的是“测试时解码近似不同”和“长度 1 时模型等价”。题目问的是一般生成时如何使用检索文档，两条事实没有解释这个机制。引用定位、来源合规、结论支持和整题完整性是不同判断；某一层通过不能替代后面的判断。

现有 `validate_citations()` 主要核对引用是否实际展示以及来源身份、原文等是否一致，不自动证明语义支持或整题完整性。因此程序的 `answered` / `answer_validated` 也不能直接当作整题正确。

这道题应覆盖的机制要点是：RAG-Sequence 按整段输出使用同一检索文档，RAG-Token 的不同 token 可使用不同文档。它们是学习和事后评价的参考，不是当前旧答案已经展示或引用的证据。依据见 [D9 方法题说明](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/ai_review_mechanism_abstract_cases.md:14)。

### 题 2：为什么先改提示，而不是加一个完整性校验器或提高 top-k？

**参考答案：**保存记录已显示“缺关键依据，但补查动作被允许且没有使用”。先改现有决策提示可以直接针对这个已观察到的缺口。增加程序语义校验需要新的判断机制，提高 top-k 则会改变检索和上下文成本；当前 A/B 没有必须做这些改动的证据。提示改动是否有效仍须看新输出，不能仅凭改了文字就宣布修复成功。

### 题 3：下面四种情况应该选什么动作？

| 情况 | 参考答案 | 理由 |
|---|---|---|
| 证据完整覆盖比较双方和所问关系 | `answer` | 已可回答，无需额外检索 |
| 初始阶段缺机制证据，选定论文内有寻找空间，允许补查 | `retry_search` | 查询所缺依据，不用相关事实凑答案 |
| 已补查一次，仍只有结果表，没有所问机制 | `insufficient_evidence` | 不能再补查，也不能推测缺失机制 |
| 用户问项目私人发布日期，选定论文不可能提供这项信息 | `insufficient_evidence` | 选定范围无法回答，无需无效补查 |

没有展示证据时，程序不允许 `answer`。不足理由应说“本轮缺什么”，不能把一次检索未命中写成“整篇论文没有”。

### 题 4：提示里写“需要时补查”，模型是不是就能随时调用工具？

**参考答案：**不能。提示引导模型返回一个 JSON 动作，并不执行检索。`allowed_actions()` 根据程序传入的阶段、是否有展示及 `terminal_only` 决定动作集合，`parse_agent_action()` 拒绝不允许的动作。随后 `agent.py` 还检查重复查询、预算及来源范围等条件，只有通过实际执行条件才会检索。

### 题 5：为什么补查后的决策和引用修复不能再次补查？

**参考答案：**补查后的阶段是 `final_decision`，允许动作中没有 `retry_search`。引用修复设置 `terminal_only=True`，即使处于初始阶段也不允许补查；消息构造和动作解析都使用这个参数。模型若仍请求补查，会被解析器拒绝，不能自动变成工具调用。这样沿用现有一次补查上限，修引用不会重新开放检索。

格式或动作修复不一律等于引用修复，其权限仍由当前阶段决定；不要把所有 repair 都理解为禁止补查。

### 题 6：版本号为什么要改？两个版本号怎么选？

**参考答案：**这次改变了模型实际看到的规则，新旧实验需要能识别使用了哪版提示。`build_agent_messages()` 在传入 `source_requirement` 时使用 `d10-source-scoped-agent-v1`，否则使用 `d10-question-complete-agent-v1`。`answer_question_agent()` 在提供来源表时记录来源约束版，否则记录普通版。这个区别表示来源规则的使用场景，不表示一个版本质量更高；当前 D9 受控入口使用来源约束路径。

真正改变模型输入规则的是 `AGENT_SYSTEM_PROMPT` 文本；仅改版本标签不会改善回答。

### 题 7：语法检查通过，可以证明新版本一定会补查、一定答对吗？

**参考答案：**不能。AST 解析只证明该 Python 文件可以被解析，没有这次编辑造成的语法错误。它不调用模型、不验证模型如何选择动作，也不评价答案支持或完整性。这些要在 D 保存的新输出和 E 的事后评价中判断；A/B 没有新增真实成绩。

### 题 8：为什么固定 RAG 没一起改？下一步应该做什么？

**参考答案：**D2-002 的固定模式根据不足的实际展示拒答，行为与证据相符；Agent 的问题是可补查却直接发布相关事实。A/B 因此只改 Agent 提示。下一步 C 按实际影响判断必要验证，D 新建同一版本的完整 20 题双模式开发批次，E 检查新输出是否有据、合规且答全，再根据开发证据决定必要修复与冻结。不能把某次合理拒答算作完成可答题，也不能拿旧成功答案补新批次的失败。

## 5. 读完后应能讲清什么

你可以用这段话概括本次工作：

> D9 的一个机制比较问题检索到了相关事实，Agent 直接回答，但没有覆盖题目。D10 A 先从保存的展示、动作和引用定位这个缺口；B 调整现有提示，让模型判断证据是否覆盖必要部分，缺依据时在原范围和权限内使用已有一次补查。程序继续控制动作、来源和预算。提示改动已经完成，语法检查通过，语义效果等待完整开发对照评价。

这段是参考表达，不是学习通过记录。A/B 的当前阶段状态和后续安排见 [D10 总计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。
