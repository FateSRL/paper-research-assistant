# D9 C：把剩余时间传到实际请求

执行日期：2026-10-06（Asia/Shanghai）。对应 [D9 任务 C](/D:/course/paper-research-assistant/docs/v1/d9/d9-ABCDEFG-plan.md#6-任务-c剩余时间要传到实际请求)。继续遵循用户四问：“用户让你做了吗？结果需要它吗？有证据吗？没它会失败吗？”

## 1. C 做了什么

原来聊天请求使用本轮剩余时间，但问题 embedding 仍固定等待最多 30 秒。现在原生检索路径把同一个 `ChatBudget.remaining_seconds` 函数传给 embedding，在 ready 核验后、HTTP 发送前再次读取时间，并使用 `min(30, 剩余秒数)`。

例如，总预算 120 秒，前面的步骤已经花掉 119 秒，下一个向量请求的网络超时上限就是 1 秒。补检索、聊天网络重试和共享修复都不能重新获得 120 秒。如果发送前已经到期，程序停止，请求次数和失败次数均为 0。

预算使用单调时钟：只衡量经过的时间，不受系统日期调整影响。测试用假时钟直接推进 119/120/121 秒，无须真的等待两分钟。

## 2. 次数和用量怎样记录

| 情况 | embedding 尝试 | 失败尝试 | tokens |
|---|---:|---:|---|
| ready 或 HTTP 发送前到期 | 0 | 0 | `null`，没有供应商用量记录 |
| 已发送，网络请求失败 | 1 | 1 | 没收到用量时为 `null` |
| 成功响应迟到，带有 17 tokens | 1 | 0 | 保留 17，终态为 `budget_exceeded` |
| 返回格式无效，响应带有用量 | 1 | 1 | 保留已知值 |
| 完整响应已到，但客户端关闭失败 | 1 | 1 | 保留收到的用量；同时过期时保留原关闭故障 |
| 明确适配旧自定义 embedder | `null` | `null` | 能取得的值保留，HTTP 细节未知 |

原生客户端在 httpx 请求 hook、进入 transport 尝试前记录 `request_started`、实际尝试次数和 `timeout_seconds`。不在“进入函数”时一律记一次；不自动重试 embedding。这里记录的是本地发送尝试和供应商返回的用量，不保证供应商的最终计费。

`null` 表示没有可靠值，不能把未知失败费用写成 0。Agent 的每轮 `search_rounds[].statistics` 保留原始计数和超时信息，汇总另有已知小计；成对运行区分实际批次账本与各模式的逻辑账本。

## 3. 什么时间算业务结果提交

向量返回、Qdrant 查询、SQLite/PDF 核验、生成、修复、资源准备/关闭和末次输入核对都有适用的阶段检查。资源准备已经超时，就关闭已打开资源，不再构造聊天客户端。

独立 runtime 的提交点位于自有资源关闭、最后输入核对和全终态时限检查之后。成对运行的每个模式在自己的聊天客户端关闭、模式末次核对之后提交，随后才开始下一个模式。记录中有 `business_commit`，包含提交阶段、状态和单调时钟耗时。

提交前任何终态超过 deadline 都变为 `budget_exceeded`，`answer` 清空。先发生的工具或输出故障保存在 `interrupted_failure`；重复检查保留首次过期的位置；过期后继续核对发现的新故障写入 `post_deadline_failures`，不覆盖首次过期和原故障。外层报告和内层业务结果保持有效状态一致，原结果可在诊断快照中追查。

提交之后的导出/渲染时间不会追溯改变已提交的业务状态。导出失败单独记为 `export_error`，保留 `pre_export_result`、提交状态及已发生的费用。成对批次的共享资源关闭与批次末次核对属于独立收尾，失败需要关注，但不能把另一模式耗时扣回已经提交的模式。

共享首检索有自己的 120 秒预算。若它用了 119 秒，固定 RAG 和 Agent 各开始时约剩 1 秒；两者都扣同一段共享耗时，不扣对方执行或等待的时间。共享检索只在实际账本付一次，在两个逻辑账本各归属一次；某模式还未重放快照就超时，也不能丢掉已经发生的共享费用。

## 4. 接口、启用范围和限制

| 位置 | 当前变化 |
|---|---|
| [embedding_client.py](/D:/course/paper-research-assistant/paper_assistant/embedding_client.py) | 可选 `remaining_seconds=None, request_timeout=30.0`；旧两参调用保持 30 秒 |
| [search.py](/D:/course/paper-research-assistant/paper_assistant/search.py) | 可选 `remaining_seconds=None`，与 B 的 `allowed_point_ids` 同时使用；旧三参调用继续可用 |
| [deadline.py](/D:/course/paper-research-assistant/paper_assistant/deadline.py) | 预算适配、全终态截止检查、业务提交记录 |
| [rag.py](/D:/course/paper-research-assistant/paper_assistant/rag.py)、[agent.py](/D:/course/paper-research-assistant/paper_assistant/agent.py) | 显式来源表会启用 D9 预算路径；也可独立传 `enforce_remaining_budget=True` |
| [agent_comparison.py](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py) | 共享首轮、当前模式补轮、每模式提交点与费用保留 |
| 独立 Agent/固定 CLI/web runtime | 修正清理、末核对和导出边界；程序化 Agent/web 支持预算 opt-in |

开启预算的原生 Searcher 要求 embedder 明确支持剩余时间参数。旧自定义两参函数可以用 `LegacyEmbedderAdapter` 显式适配，只调用一次；它只能检查阶段，无法改写隐藏的 HTTP 超时，因此 HTTP 次数和 timeout 不冒充已知。旧自定义 Searcher 使用单次旧签名适配；不会捕获 `TypeError` 后回退重发。

核心记录的 `deadline_enforcement` 描述检索预算适配、聊天剩余超时和阶段检查；是否实际使用了原生 embedding HTTP 超时，应查看检索统计的 `request_started`、`timeout_seconds` 和 `accounting_basis`。原生成功路径为 `http_send_hook`，旧不透明函数为 `opaque_legacy_callable`。不能用旧适配器的阶段检查证明隐藏请求已经使用 1 秒超时。

独立版本为 `d9-remaining-budget-v1`；来源加预算的核心版本为 `d9-fixed-rag-source-budget-v1`、`d9-bounded-source-scope-budget-agent-v1`、`d9-source-budget-paired-v1`。A 的起始契约与 B 的历史记录仍描述各自完成时事实，不追溯修改。

**完整 D9 stage/配置校验/独立导出目录、CLI 与页面接入仍待 E。** 当前默认 D8 CLI 不会自动启用 D9 来源表或 embedding 总预算；不能拿当前 opt-in 核心证明页面已经完成 D9 接入。本任务未发起新的真实模型问答实验。

已实现请求剩余超时和阶段检查，**未证明整个进程严格在 120 秒内强制退出**。同步本地操作和底层网络阶段仍可能阻塞，网络阶段超时也不等于进程总时长硬中止。

## 5. 验证结果与复跑

32 个 C 针对性方法、317 个受影响既有流程方法通过，分别记录，不与模拟 HTTP 次数或真实题数相加。覆盖 HTTP 发送前/后、ready、Qdrant、SQLite/引用、网络重试、资源关闭、业务提交、共享首轮与两模式公平性；既有生成、固定 RAG、Agent、消息、来源过滤、CLI/web/批次清理和导出行为也复核通过。

测试使用假时钟、httpx/真实聊天 SDK 的 MockTransport、临时 PDF/SQLite/Qdrant和 B 的既有回放证据；真实 API/网络均 0，未读 `.env`，未打开正式数据库，未使用验收题面。正式输入、D8 首次/费用/评分、人审、A/B 记录和当前摘要范围表保持原样。

有一条旧 Agent runtime 断言按 A 的提交契约更新：已提交之后导出失败应是独立 `export_error`，不再追溯记为超预算。旧测试源码有修改前副本；原报告不覆盖。首次失败、修复和最终成功均保留，见 [C 完成记录](/D:/course/paper-research-assistant/artifacts/d9/task_c.md)、[时限报告](/D:/course/paper-research-assistant/artifacts/d9/c_deadline_validation.json)、[兼容报告](/D:/course/paper-research-assistant/artifacts/d9/c_compatibility_validation.json)。

可在项目目录复跑，两个命令仅写新的 D9 离线历史和各自当前报告：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_d9_c_deadline
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_d9_c_compatibility
```

C 只完成本任务所需验证；D 的完整故障组合验收仍待执行，C 的检查通过不代表 D–G 已完成。

## 6. 你怎样检验成果

用 10–15 分钟看 [时限检查源码](/D:/course/paper-research-assistant/scripts/check_d9_c_deadline.py) 和报告即可，基础是函数参数、异常、字典和经过时间。

1. 找 `test_ready_119_seconds_forwards_one_second`：ready 后还剩多少？应是 1 秒，请求 timeout 为 1，请求次数为 1。
2. 找 `test_hook_expiry_after_client_setup_does_not_enter_transport`：在客户端创建期间耗尽时间，发送 hook 应挡住 transport，次数为 0。
3. 找 `test_late_success_keeps_one_attempt_and_known_tokens`：响应有 17 tokens，但返回时已经 121 秒。终态超预算，次数为 1，用量仍为 17。
4. 找 `test_shared_119_seconds_leaves_each_mode_one_second`：两个模式开始时都剩 1 秒；查看后一模式不能重新拿到 120 秒的断言。
5. 对照兼容报告的导出提交断言：业务提交时 answered，导出之后失败，保留提交结果和费用，独立报告 export_error。

不需要重新调用付费模型。用户对 B 的人审已保留；C 的学习掌握与人工复核尚未记录为已完成。下一任务是 D。
