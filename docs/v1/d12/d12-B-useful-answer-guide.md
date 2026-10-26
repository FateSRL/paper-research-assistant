# D12 B：不足时仍回答工作日志、学习入口与参考答案

执行日期：2026-10-08（Asia/Shanghai）。**B 已完成实现。** 正常检索不足时仍回答或解析；技术故障保持真实状态。实际离线验证集中在 [C 日志](/D:/course/paper-research-assistant/docs/v1/d12/d12-C-display-export-guide.md)，不重复执行。

## 1. 实际完成什么

固定 RAG 复用 [answer_question()](/D:/course/paper-research-assistant/paper_assistant/rag.py) 与 [generate_draft()](/D:/course/paper-research-assistant/paper_assistant/generation.py)，移除无命中或字符预算导致展示为空时的程序拒答，仍使用空上下文进入生成，并传入 `evidence_limitation`。来源限定无可用核定摘要或存在歧义时，调用 [prepare_unavailable_source_context()](/D:/course/paper-research-assistant/paper_assistant/source_scope.py)创建真实的空展示和限制说明；不伪造检索记录，也不请求不可能满足限定的检索。模型知识/分析能发布，虚假的摘要或论文引用仍不能通过来源检查。

Agent 复用 [answer_question_agent()](/D:/course/paper-research-assistant/paper_assistant/agent.py)。`allowed_actions()` 在空证据时也允许 `answer`，首轮可选择回答或一次 `retry_search`；最终阶段只允许回答。缺核定来源、补查查询与原查询相同、一次补查未增加可展示正文等旧程序不足分支，改由 `answer_with_limitation()`进入 `final_decision`。最终消息保留原问题和真实当前证据，并要求模型给有用回答/解析；重复查询不会执行重复检索。

收尾时修复了 [run_paired_case()](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py) 的外层调用：原来来源限定不足会直接返回两模式不足结果，核心新行为无法被调用。现在 `source_stop` 只记录来源不足原因，不发起共享首轮检索；继续分别调用固定 RAG 和 Agent，由两核心各给知识回答/解析。共享检索记录为空，实际 embedding 为 0，两模式各使用一次聊天调用。

不足触发原因仍记入 `stop_reason`，例如 `no_new_shown_evidence`，但有用答案发布后状态为 `answered`。因此消费者应读当前 `status`、`answer` 和逐条 `basis`，不能把不足触发原因直接当作“没有答案”。发布新增 `evidence_status` 描述依据组成，语义支持仍为 `not_reviewed`。

补充知识由现有决策/回答调用产生，不单独启动兜底模型链。固定 RAG 若输出旧 `insufficient_evidence`，会沿现有一次格式修复要求回答；Agent 的活动动作不再接受该动作，可沿现有修复纠正。一次补查、三次共享聊天尝试和现有修复额度保留。真实网络/工具错误、超时、预算耗尽、持续非法输出仍保留技术失败状态，不能声称已经回答。

实际离线方法覆盖固定 RAG 空证据、混合依据的真实引用回查、Agent 补查重复/无命中/重复查询后的最终回答，以及两模式未核定来源时零搜索、一次模型决策的知识回答。外层修复后扩展同一个来源方法覆盖 paired 入口，只重跑该方法，**Ran 1 test / OK，0.125 秒**；其余 3 个已通过方法结果复用，仍为 4 个不同方法。响应全部为模拟，不测新的模型回答准确率。

## 2. 怎样学习：约 25 分钟

1. 从 `rag.py` 的检索后上下文一路读到 `generate_draft()`，找到空证据为什么以前提前停止、现在应如何进入回答。
2. 从 `agent.py` 的首轮决策追踪直接回答、一次补查、最终回答三条路径；特别留意补查没有新增正文时的终态。
3. 比较 [generation.py](/D:/course/paper-research-assistant/paper_assistant/generation.py) 的格式修复与 [agent_actions.py](/D:/course/paper-research-assistant/paper_assistant/agent_actions.py) 的动作解析：修复共用现有额度，不获得无限新尝试。
4. 读 `agent_comparison.py` 的 `run_paired_case()`：追踪 `source_stop` 为什么不再生成外层拒答、为何来源不足时不伪造共享检索记录。
5. 用“什么是 BM25”和“这篇论文某个未展示实验的数值是多少”口头说明应答区别，不发起新的模型请求。

## 3. 关键问题与答案

**检索为空是否还需要生成？** 需要。检索结果只说明当前语料未提供相关原文；一般概念问题仍可用模型知识解释。具体论文事实无法确认时，说明该限制并给出相关概念、指标解读或查找方向，不能只停在“检索不足”。

**补查没有新正文就要不停地搜吗？** 不需要。一次补查上限继续适用；此后复用当前材料和模型知识形成最终回答/解析。D12 改变不足时的回答行为，没有引入无限搜索。

**模型接口失败时能保证回答吗？** 不能伪造。D12 针对正常证据不足，而非让程序凭空产生模型输出。接口、源文件、预算等技术问题保留真实状态和错误信息；这样用户能区分“已给一般解析”与“这次调用没有完成”。
