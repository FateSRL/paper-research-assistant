# D9 A：来源与预算契约、修改前保护和学习自检

执行日期：2026-10-06（Asia/Shanghai）。状态：**任务 A 的准备范围已完成**。本次产出 D9 独立契约、接口约定和修改前备份；来源校验、剩余时限和 D9 运行入口分别进入 B/C/E 实施。B–G 仍待执行。

当前机器可读契约见 [agent_config.json](/D:/course/paper-research-assistant/artifacts/d9/agent_config.json)，完成证据见 [task_a.json](/D:/course/paper-research-assistant/artifacts/d9/task_a.json)。这是 `frozen_for_implementation` 的起始契约，尚不是 D10 最终评测冻结。`rules` 记录待实现要求，`observed_implementation_at_A` 记录 A 时实际能力，两者不能混读。

## 1. 按用户的四问控制范围

用户在本轮明确要求记住：**“用户让你做了吗？结果需要它吗？有证据吗？没它会失败吗？”** 后续每个动作都以这四问检查必要性；已授权任务内的必要常规步骤继续执行，无需逐项重复请示，不能只因为某件事可能有帮助就扩大当前任务。

| 本次动作 | 授权和结果需要 | 证据 | 省略会造成什么 |
|---|---|---|---|
| 读当前计划、接口和 D2-003 旧输出 | A 明确要求冻结有依据的规则 | D9 A 条目、实际源码和旧四题记录 | 契约脱离实现，误解真实失败 |
| 保存新策略与接口说明 | A 的直接产物 | 旧策略缺章节硬门槛，runtime 绑定 D8 schema | 后续实现无明确判定/兼容边界 |
| 备份拟修改源码及本次导航 | A 要求保护旧成果 | 后续 B/C/E 会改这些现有接口 | 无法回查修改前版本、混用历史 SHA |
| 核对 JSON、哈希、状态和本地链接 | 让 A 的交付可复核 | 新配置、备份和完成记录 | 配置或绑定错误却被标为完成 |

A 使用已有实验和文件作证据，新增项目 embedding/聊天调用均为 0。旧测试结果按匹配的源码绑定继承；没有为准备工作重跑 186/119 方法、创建新实验批次、实施页面或添加新的全局规则文件。

## 2. D2-003 的失败究竟是什么

原题：`Which question-answering and fact-verification benchmarks are named in the paper's abstract?`

所选版本为 ReAct `arxiv_2210.03629v3` / `r_22af23d03fcb87a8`。旧实验两个模式共享首轮 top-5，完整展示同五块，文件页序为 **4 / 12 / 13 / 11 / 3**。没有展示摘要。

- 固定 RAG 返回不足，理由明确说展示内容没有摘要。它保住了来源要求，但没有完成这道可答题。
- Agent 没有补查，发布两条“摘要点名 HotPotQA / FEVER”的结论，两次都引用 `arxiv_2210.03629v3_r_22af23d03fcb87a8_p4_c7`。引用原文从 `Domains` 开始，是正文。

| 检查层 | 它检查什么 | 旧 Agent 结果 |
|---|---|---|
| 引用定位 | ID 是否存在、属于所选版本、原文/PDF 身份是否一致、是否实际展示 | 两次定位检查合法 |
| 章节来源 | 实际引用是否来自题目指定的摘要范围 | 失败：引用正文 |
| 语义支持 | 实际原文是否支持每条声明及其附加措辞 | AI 初审为部分支持；定位合法不能证明整句成立 |
| 整题完成 | 请求的事实、范围与完整性是否同时满足 | 失败：摘要要求没有满足 |

旧输出见 [D2-003.json](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/D2-003.json)，AI 评价见 [ai_semantic_review.json](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/ai_semantic_review.json)。用户“我的审核和AI相同”的 [总体确认](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review.json) 保持 2026-10-05 的历史时间和方式；它不新增独立逐结论/逐引用评分，也不确认尚未建立的摘要范围表。

## 3. 冻结的来源规则

来源要求只从**原始用户问题**确定一次，记录问题哈希、规则版本、识别结果和匹配表达。首版支持明确的中英文摘要限定，补查查询与修复消息都不能解除该要求。普通正文问题沿用原证据规则；识别到否定、引用或冲突等疑义时保守说明约束不清，不静默降成不限章节。

在线业务不能读题号、标准答案、预期引文、是否可答、rubric 或 AI/人工评分来决定来源、查询和答案。来源表描述固定论文结构，可服务任意问题。

### 3.1 三种状态分开存

| 维度 | 状态 | 含义 |
|---|---|---|
| 区域核定 | `candidate / verified / rejected` | 只有对照原 PDF 与解析/过滤来源区间，有证据绑定的核定才可为 verified |
| 完整片段覆盖 | `abstract_full / body / mixed / unknown` | 完整 chunk 是否全部属于核定摘要；跨章节或未核定不合格 |
| 人审 | `pending / confirmed / rejected` | 人工是否实际确认，独立于 AI 结构核定 |

人审拒绝必须同步将区域核定标为 rejected；若同时写 verified 与人审 rejected，组合矛盾判为 tool_error，不放行。AI verified＋人审 pending 可按已核定证据使用，但不声明用户已确认。

B 建立 `artifacts/d9/source_regions.json`，schema 为 `d9-source-regions-v1`。每个必需论文/版本记录绑定 PDF、解析/过滤/分块快照、segment、块/行、字符区间及原文 SHA；每次运行及 prepared manifest 再绑定整张表的 SHA。

AI 结构核定可以如实记为 AI 核定、人审 pending；模型只提出标签或检索命中正确答案不能成为核定证据。第 1 页、关键词、相似度和模型自报章节均不作为摘要权威；父片段 bbox 不冒充 chunk 精确边框。完整片段不裁剪成“合格摘要”。A 尚未创建或核定这张表。

### 3.2 双模式与错误决策

| 条件 | 固定 RAG | Agent |
|---|---|---|
| 有合格实际展示原文 | 生成并逐引用检查 | 正常决策，最多一次补查 |
| 首轮只有正文/未知/混合片段 | 一轮结束，来源不足；无须为没有合格证据额外生成回答 | 不开放 answer；正常首次门最多一次补查或不足 |
| 摘要补查 | 固定模式不补查 | 核定摘要 point 白名单与原论文/版本/profile 取交集，top-5，原问题仍是回答目标 |
| 有效表内尚未核定/没有可用摘要范围 | 正常来源不足 | 没有可检索范围就提前不足，不发明知无效的 embedding |
| 预期必需表/论文记录缺失，或 schema、范围、版本/哈希损坏 | tool_error | tool_error，不让模型猜测修好 |
| 模型实际引用越界 | 只允许剩余共享终态修复，仍错则 invalid_output、不发布答案 | 同左，修复不能再检索 |
| 补后无合格新增展示或仍不足 | 不适用 | 不足，不发第三次检索；无新增展示停止规则继续生效 |

每条结论的**每一个引用**都必须属于最终实际展示且来源合格；一条摘要引用不能豁免另一条正文引用。数据损坏先归工具错误，模型输出越界才走剩余共享修复。核定表中尚未展示的文字不能直接塞进答案或为它补证明。

先核验所有物理候选的身份/原文，再筛来源，最后按现有条数和字符预算选择。原始召回状态、rank 和文本保留；来源排除原因、合格候选与展示映射另存在外层。物理检到了正文仍是原搜索 success，不能冒称 no_hits；页面/不足理由使用外层来源不足原因。

## 4. 最小接口契约与兼容边界

以下是待 B/C/E 实现的接口，不是 A 新增的可调用代码。

| 接口 | 已确定输入/输出 | 实施阶段 |
|---|---|---|
| `identify_source_requirement(original_question)` | 一次生成原问题绑定和来源要求，评测标签不进入输入 | B |
| `prepare_scoped_context(search_result, requirement, verified_registry, *, max_chars=8000)` | 返回旧严格字段的 context ＋外层 qualification；后者存表 SHA、候选资格、原 rank、排除原因和实际展示映射 | B |
| `validate_citation_scope(answer, context, qualification, verified_registry)` | 定位核验后逐引用校验，修复后再次检查；数据损坏与模型越界分开 | B |
| Searcher 可选关键字 `allowed_point_ids=None, remaining_seconds=None` | 旧三参调用兼容；白名单由程序构造，空摘要集合提前不足，不把空集合转 None；ready 数量仍核验完整所选版本 | B/C |
| embedding 可选关键字 `remaining_seconds=None, request_timeout=30.0` | 旧两参保持 30 秒；实际发送前重算时间；返回/异常携带发送尝试、timeout 和已知/未知 usage | C |
| runtime/CLI/export 的 `stage=d8\|d9` | 受控枚举、默认 d8；D9 策略/schema/保护绑定和目录独立；成对首轮/补轮正确透传 | E |

旧自定义 embedder 用明确适配器兼容，不捕获 TypeError 后重新发送。`context.py` 证据字段集合严格，来源字段放版本化外层，而非直接塞入旧证据对象。[Searcher](/D:/course/paper-research-assistant/paper_assistant/search.py:208) 目前没有 point 过滤或剩余时间参数；[embedding](/D:/course/paper-research-assistant/paper_assistant/embedding_client.py:25) 目前仍固定 30 秒。

首轮两模式共享同一真实 top-5；摘要限定的补轮才增加可信来源 point 过滤。原版本/profile ready 总数检查保持完整范围，摘要子集不能冒充完整入库数量。

## 5. 沿用预算，明确发送与提交点

继续沿用：首轮/补轮各 top-5、Agent 最多一次补查、最终最多 8 条完整 chunk / 8000 Python 字符；每模式每题聊天最多 3 次 SDK 尝试，网络重试最多 1 次，格式/动作/引用共享 1 次修复；单请求上限 30 秒、总预算 120 秒。补查、修复和重试不重置预算。

- 纯用户参数结构校验后、运行输入核对及资源/初次检索前建立单调时钟预算；各阶段与资源清理、末输入核对计入本模式。
- 成对共享首检索有自己的剩余时间；每模式再扣共享首检索实际耗时，不扣另一个模式的执行/等待。首轮耗 119 秒，两模式各自只剩约 1 秒。
- 实际发送尝试前 timeout 取 `min(30, remaining)`。未进入 HTTP 发送尝试为 0；已发送失败为 1；未知 tokens 为 null。不能在进入 embedder 函数时一律算 1；本地记录不替供应商计费作保证。
- 业务终态提交点按资源归属区分：独立 runtime 在业务结束、自有资源清理、末输入核对和全终态 deadline 检查后冻结核心结果；成对运行中，每模式在自己的 client 清理、模式末核对和 deadline 检查后、下一个模式开始前冻结。提交前已过期统一 budget_exceeded，原故障保留 interrupted_failure。
- 成对 runner 持有的共享检索资源关闭和批次最终核对属于独立收尾，不能再次检查已提交模式的绝对 deadline，从而扣入另一模式等待；收尾失败保留已提交模式和费用，但批次须报 attention_required。导出可稍后使用已冻结核心结果，失败保留费用与 pre_export_result 等诊断；已提交不可变历史不因后续导出/渲染迟到追溯改写。当前导出异常仍有 deadline 分支，C/E 要按新契约统一。

完成 C 后能表述阶段检查和 embedding/聊天按剩余时间限制；同步网络/检索/PDF 操作仍可能阻塞，**严格 120 秒强制中止未验证**。

## 6. 新版本和修改前保护

D9 schema：`d9-initial-agent-contract-v1`；策略版本：`d9-source-scope-deadline-policy-v1`。当前 D8 runtime 硬绑定旧 schema，A 没有接线，因此不能拿新文件直接宣称已运行 D9。

未来 D9 最近结果放 `artifacts/d9/`，不可覆盖历史放 `archive/run_logs/d9/`，成对批次放 `artifacts/d9/comparison/`。D9 策略及范围表必须显式进入保护绑定；现有 D8 输入清单不会自动保护这两个新路径。

新代码/策略/范围表改变后新建对应 prepared 批次。D8 已完成四题不能续加 16 题，也不能迁成 D9 成绩；新四题和新完整 20 题分别建批次，A 尚未建立这些实验。

修改前快照见 [保护清单](/D:/course/paper-research-assistant/archive/planning_snapshots/d9_task_a_20261006_040641_795424/manifest.json)。按已确定后续接口保存 13 份拟修改源码、4 份本次导航的修改前副本；正式数据、D8 首次/费用/AI/人审记录和原 D9 规划记录按哈希保护。没有复制虚拟环境、密钥或另建语料。

公开模型目标沿用 D8 保存的 deepseek/deepseek-flash、qwen3.7-text-embedding 和 profile `ep_cbf0f6caa97b962a`。本次仅核对已有公开配置/数据绑定，未读取 .env 或检测服务连接；实际运行时仍须按新策略验证当前公开配置。

## 7. 你怎样检验 A

用 15–20 分钟看上面的 D2-003 对照、错误表和预算规则即可：

1. 名称正确、ID 合法为什么仍不满足摘要要求？对应上表哪一层失败？
2. 有效表内暂未核定与预期必需表损坏，为什么分别是证据不足和工具错误？
3. 120 秒已耗 119 秒，下一次 embedding timeout 应是多少，发送前到期怎样计数？
4. 新 JSON 的 rules 写“要连接剩余时间”，为什么 observed 状态仍是 false？
5. 以后改了规则或范围表，为什么要新批次，而不是覆盖旧四题？

需要的基础只有字典/函数参数、异常、哈希与单调时钟；不要求重读整章或重跑模型。学习清单不代表用户已掌握，也不新增人审确认。

下一步为 **B：生成并核定三篇摘要范围表，实现两模式共用来源门槛**。本次 A 的核对范围、当前源码和产物 SHA、实际零请求及已知限制均记录在完成文件中。
