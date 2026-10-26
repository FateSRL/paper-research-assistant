# D8 任务 A：接口核对、初始策略冻结与学习自检

完成日期：2026-10-05（Asia/Shanghai）。依据：[D8 执行计划](/D:/course/paper-research-assistant/docs/v1/d8/d8-ABCDEFG-plan.md) §4、当前源码和 D6 工程交接。

**A 的准备范围已完成：当前接口与正式数据已离线核对，三动作、一次补查、证据选择、预算和停止策略已冻结。** 这些新规则尚待 B/C 实现、D 验证。Agent 未实现，B–G 未执行；没有运行论文问答或调用模型，使用者的学习、自检与理解程度尚未测量。

入口：[完成记录](/D:/course/paper-research-assistant/artifacts/d8/task_a.json)、[可读记录](/D:/course/paper-research-assistant/artifacts/d8/task_a.md)、[初始配置](/D:/course/paper-research-assistant/artifacts/d8/agent_config.json)、[完整预检](/D:/course/paper-research-assistant/artifacts/d8/task_a_preflight.json)。配置是 `d8-initial-agent-contract-v1`，不是 D10 最终评测冻结。

## 1. 本次实际检查了什么

| 项目 | 实际结果 | 结论范围 |
|---|---|---|
| 离线核对 | 57 项通过 | 数据/配置/绑定预检，不是 Agent 边界测试通过数 |
| ready CLI | 退出码 0，3 个 ready 版本、1188 个 chunk | SQLite 状态读取；未打开 Qdrant，不重新核对全部向量方向 |
| SQLite 版本计数 | 385/480/323，与 ready 记录一致 | 只读读取版本计数，没有重新遍历每条正文 |
| 配置身份 | 本机 embedding 配置与正式 profile 完全相同 | 不证明服务当前连通或额度可用 |
| 聊天参数 | `deepseek-flash`；temperature 0.2、max_tokens 1200；单次30秒、三次尝试、一修复、一网络重试、整轮120秒 | 本机配置与既有 ChatPolicy 核对；未发连通请求 |
| 原始来源 | 三份实际 PDF SHA 与 corpus 一致；清单声明页数合计71 | 本次未重新渲染、逐页阅读或重数页码 |
| 开发集 | 20 题，17可答/3无答案，21条期望引文；四道冒烟 ID 均存在 | 题目标注人审与生成答案人审分开 |
| 验收冻结 | 正式题集、评分规则、人审记录 SHA 与 D6 冻结声明一致 | 只校验文件字节；不解析验收题内容、不运行验收 |
| 当前源码与旧证据 | 保存21份接口相关源码/依赖文件绑定；34项历史引用、26个不同源码文件全部匹配 | 没有重跑 D5/D6 的旧边界或问答实验 |
| 文件保护 | 781个受保护文件，前后路径及内容SHA一致；配置另绑定168份data/eval文件 | 保护列表见预检JSON，不是全项目任意文件不变声明 |
| 模型和网络 | embedding 0、聊天0；审计主进程网络尝试0 | 子进程仅执行已核对的离线ready路径，无本次模型用量 |

配置检查调用既有加载函数在本地读取 `.env`，仅序列化明确白名单字段与凭据是否存在，不保存密钥或整个配置对象。当前 `qdrant-client=1.19.1`、`streamlit=1.65.0`；完整实际包版本见预检，不代表 D7 新环境预演已补做。

实际执行的公开 ready 命令：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.search_evidence --list-ready --json
```

本次在预检脚本中以该命令启动独立进程，stdout、退出码和 profile 已保存。一次性审计脚本为 [task_a_preflight.py](/D:/course/paper-research-assistant/artifacts/d8/task_a_preflight.py)，已有产物时拒绝覆盖；平时复查可以运行上面的 ready 命令，不能把重复运行当成新的完整数据验收。

## 2. 当前接口怎样接到 D8

| 复用接口 | 当前能力 | D8 待实现部分 |
|---|---|---|
| [rag.answer_question](/D:/course/paper-research-assistant/paper_assistant/rag.py:21) | 一轮检索/回答/引用回查，严格 top-5、最多8000字符 | 保持原核心；新 Agent 独立编排，不能先生成固定答案再叠加一次决策 |
| [EvidenceSearcher.search_evidence](/D:/course/paper-research-assistant/paper_assistant/search.py:208) | 完整版本配对、ready检查、一次问题embedding、Qdrant检索与SQLite原文回查 | 同一选定范围补查最多一次；聚合两轮成功和失败统计 |
| [select_context](/D:/course/paper-research-assistant/paper_assistant/context.py:88) / [prepare_context](/D:/course/paper-research-assistant/paper_assistant/context.py:129) | 稳定rank顺序、去重、完整片段和首次字符超限停止 | 新合并层先按补轮→首轮去重、连续选择序号与8条上限，再进入现有字符选择 |
| [Claim/AnswerDraft](/D:/course/paper-research-assistant/paper_assistant/schemas.py:52) | 回答/不足的结构契约 | B新增独立AgentAction，旧草稿不改；answer动作直接携带草稿 |
| [parse_answer_draft](/D:/course/paper-research-assistant/paper_assistant/generation.py:20) | 拒绝重复键、非有限值、额外文本和错误结构 | 借用严格解析原则，不能把三动作直接交给此旧草稿解析器 |
| [ChatBudget](/D:/course/paper-research-assistant/paper_assistant/llm_client.py:77) / [RecordedLLM.invoke](/D:/course/paper-research-assistant/paper_assistant/llm_client.py:200) | 共享三次SDK尝试、一修复、一聊天网络重试；单次和剩余时限 | 决策/补后回答共用同一对象；仍用purpose=answer，外层另记phase |
| [validate_citations](/D:/course/paper-research-assistant/paper_assistant/citations.py:112) | 最终实际展示集合、SQLite全文身份、实际PDF SHA及页序回查 | 新最终context保持旧严格格式；定位合法仍需独立语义复核 |
| [exclusive_json](/D:/course/paper-research-assistant/paper_assistant/answer_export.py:84) | 历史独占创建，最近记录可原子更新 | D8新路径与Markdown适配；旧render含D5链接，不直接当D8导出 |
| [evaluation.score_case](/D:/course/paper-research-assistant/paper_assistant/evaluation.py:35) | 单个search/context的事后机器统计 | E新增多轮评分适配；页面task/下载兼容留D9 |

两处结构差异已经冻结：`StrictSchema` 会清理字符串首尾空白，因此未来 retry_query 不直接继承该清理行为；保留原字符串并单独验证非空白。`RecordedLLM(require_json=True)` 只做 JSON 语法门槛，重复键、字段、三动作和阶段限制仍须 B 严格校验。

## 3. A 已冻结的动作与停止规则

| 场景 | 允许/终态 | 后续实现要求 |
|---|---|---|
| 首轮有实际展示证据 | answer / retry_search / insufficient_evidence | 回答原问题；模型不能指定版本、k、工具名、路径或页码 |
| 首轮成功但无可展示证据 | retry_search / insufficient_evidence | 可依据原问题改写一次，禁止answer；固定RAG现有直接拒答保留 |
| 补查后新增实际展示证据 | answer / insufficient_evidence | 不允许再次执行补查；最终引用只限最终展示集合 |
| 补查query显然相同 | insufficient_evidence；retry_query_unchanged | 比较键为`' '.join(query.split()).casefold()`；收费前拦截，实际请求仍用原文 |
| 没有新增最终展示ID | insufficient_evidence；no_new_shown_evidence | 不再为相同原文调用补后回答；新增返回和新增展示分别记录 |
| 补轮再次retry或非法动作 | 可用剩余共享修复；失败则invalid_output | 修复后也不得重新放开补查工具 |
| 首轮/补轮工具异常 | tool_error | 成功空结果和工具失败分开；不静默回退未经验证答案 |
| 请求或截止额度耗尽 | budget_exceeded | 先检查最终决策还有额度，再发补查embedding |
| 答案引用无效 | 共享一次引用修复，失败则invalid_output | 修复只使用当前最终证据，可转不足，不能再开工具 |

新动作采用严格类型、禁止多余字段、重复键和非有限值；missing_information最多500字符、retry_query最多1000字符、reason最多1000字符。各字段非空白；保存原query，不把比较键当请求。动作的语义/阶段判断由程序执行，结构通过不能直接触发工具。

合并顺序固定为补轮rank→首轮rank，chunk ID去重；同ID身份或全文冲突报错。对合并后候选赋连续选择序号，原轮次/rank/score留外层，不跨查询按cosine分数排序。新层先入围最多8条，旧选择器再按8000 Python字符选完整chunk，首次长度超限停止；数量省略、重复与原始完整候选另留轨迹。8000字符不等于8000tokens。

第一轮看过但最终省略的chunk不能引用。首轮返回但未展示的chunk后来进入上下文，算新增展示，不能冒充新增召回。新策略的控制实现与这些边界通过证据均留B–D，本次只有契约冻结。

## 4. 预算要怎样理解

首轮/补轮各top-5，最多两轮、补查一次；embedding无自动网络重试。每题每模式的聊天上限三次SDK尝试，HTTP尝试另外记；格式、动作和引用修复共用一次，聊天网络重试共用一次，这些都占三次额度。

例如：首次网络失败→网络重试得到畸形动作→修复后请求补查，已用三次聊天。即使补查次数尚未使用，也没有最终决策额度，应在补查embedding前停止。这是本次规则例子，尚未作为新Agent故障场景执行。

独立问答在首轮检索前启动120秒截止；成对实验各模式从“120秒减共享检索实际耗时”获得剩余额度，另一模式等待不扣本模式时间。调用前后检查截止，聊天请求取单次/配置/剩余时限最小值。embedding当前固定30秒、同步本地步骤无硬中断；A没有证明进程严格120秒中止，D9再补统一时限及故障组合。

## 5. 使用者的28分钟学习与自检

本次AI已按下列范围实际阅读并完成课程到项目映射；未运行课程示例，未替使用者记录“已学会”。第十四章本次没有阅读，现有材料足以解释一次补查职责。

| 时间 | 阅读入口 | 学习目标 |
|---|---|---|
| 0–5分钟 | [Ch9 9.1](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:25>)、[9.2.2](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:83>) | 知道模型只能根据本次实际上下文决策，工具查询由程序执行 |
| 5–11分钟 | [9.3.1](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:129>)、[Select](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:312>) | 候选和展示不同；把8条、8000字符、完整chunk解释清楚 |
| 11–17分钟 | [Structure](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:437>)、[Compress](</D:/course/hello-agents-study/docs/chapter9/第九章 上下文工程.md:497>) | 原问题、证据和输出结构如何组织；压缩示例为何不能直接替代引用原文 |
| 17–23分钟 | [Ch7 ReAct](</D:/course/hello-agents-study/docs/chapter7/第七章 构建你的Agent框架.md:964>)、[工具解析](</D:/course/hello-agents-study/docs/chapter7/第七章 构建你的Agent框架.md:764>) | 模型动作→严格解析→程序闸门→工具→停止；请求上限由程序计数 |
| 23–28分钟 | 看配置、回答下列自检 | 能对照契约解释具体结果，而不仅复述流程 |

教材的三处实现不照搬：Ch9 Compress允许截半段文本，D8保持完整引用chunk；Ch9 Gather把部分检索异常记警告后继续，D8明确tool_error；Ch7 [工具迭代上限后仍调用模型](</D:/course/hello-agents-study/docs/chapter7/第七章 构建你的Agent框架.md:753>)说明只限制工具轮次不足以限制聊天请求。

自检问题及核对要点：

1. 模型和程序分别能决定什么？——模型选择三个动作及补查query；程序固定范围、次数、证据与引用，执行预算。
2. 原问题只换大小写/空白，以及补轮再要求检索，怎么处理？——前者收费前拦截并说明不足；后者不执行工具，非法动作按共享修复/invalid_output处理。
3. 在库中存在、首轮展示过而最终被省略的chunk还能引用吗？——不能；最终白名单只含实际展示，定位合法也不保证语义支持。
4. 首轮成功无证据与工具超时有什么区别？——前者可一次改写或不足，禁止回答；后者是工具错误。
5. 网络失败、重试、格式修复已占三次后，还能补查吗？——不能先收费补查；没有最终决策额度，budget_exceeded。

自检答案只作为学习对照。使用者实际回答、阅读和人审确认尚未发生，相关状态保持 `not_measured/pending`，不作为本次机器核对的通过项。

## 6. 下一步 B 的明确交接

读取已冻结配置，新增独立三动作模型/提示词/严格解析；answer直接携带现有草稿，retry仅携带缺失事实和query。保留原query、拒绝同查询、区分首轮与补轮允许动作，不新增工具或扩大预算。

A 的源码绑定是准备快照。B–E 新增实现要记录自身源码与prompt/选择策略版本；如果起始策略需要变化，保留本配置并建新版本/说明原因，不覆盖初始冻结。四题首次成对实验留F，完整20题开发对照留D9–D10，验收仍D11；D7继续暂缓。
