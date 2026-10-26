# D8 D：离线边界、故障注入与记录恢复

执行日期：2026-10-05（Asia/Shanghai）。D 验证受控 Agent 的动作、检索、证据、引用、预算及记录边界；真实 API/网络为 0。最新进度见 D8 总计划，A/B/C 的文档和记录保留当时源码绑定。E 的独立 CLI/成对 runner、F 的真实四题实验和 G 汇总仍待执行。

统一入口为 [check_agent_boundaries.py](/D:/course/paper-research-assistant/scripts/check_agent_boundaries.py)，既有 [C 检查脚本](/D:/course/paper-research-assistant/scripts/check_agent.py)保持原样。D 不调用 B/C 的报告生成入口，所以它们的当前及历史报告均未覆盖。

## 1. 本次到底检查了多少

当前统一报告 **186 个 unittest 方法全部通过**，0 失败/错误/跳过，源码运行前后相同；经过实际 OpenAI SDK 的 `httpx.MockTransport` 模拟 HTTP 182 次。真实 embedding、聊天、网络请求均为 0，未加载 `.env`、打开正式 SQLite/Qdrant 或运行冻结验收题。

| 检查组 | 方法数 | 范围 |
|---|---:|---|
| B 接口回归 | 42 | 严格动作/JSON、阶段/空证据/修复权限与提示词 |
| C 编排回归 | 41 | 直接/补查/不足、共享预算、最终引用、deadline及轨迹 |
| D 新增动作/预算故障 | 22 | 异常输出、网络/修复组合、超时/连接故障、未知用量 |
| D 新增证据/引用故障 | 67 | envelope/候选篡改、完整片段/上限/来源、库/PDF故障 |
| D 新增记录/资源故障 | 14 | 五终态导出、独占冲突、所有保存阶段失败、客户端关闭 |
| 合计 | 186 | 新增 D 为 103，其余 83 为 B/C 当前源码适用回归 |

方法数与分组 subTest 数不同，也不与真实题数、正确率混用。独立组试运行与统一运行不累加冒充更多方法；182 只指本次统一运行的模拟发送数。

见 [统一 JSON 报告](/D:/course/paper-research-assistant/artifacts/d8/agent_boundary_validation.json)、[可读报告](/D:/course/paper-research-assistant/artifacts/d8/agent_boundary_validation.md) 和 [D 完成记录](/D:/course/paper-research-assistant/artifacts/d8/task_d.json)。报告绑定 21 份源码。

## 2. 各场景怎样证明边界

动作组使用真实 `RecordedLLM` 和解析器，注入未知动作、工具字段、错类型、重复键、非有限数、围栏、空查询、截断、空响应及异常 finish_reason。首/补阶段仍只允许当前动作；一次共享修复不能重新开放检索。

预算组把正常决策、修复、网络重试放在同一预算中：最多三次 SDK 尝试、一次网络重试、一次格式/动作/引用共享修复。实际 transport 抛 `httpx.ReadTimeout` 后只受控重试一次；首轮已用网络重试后补轮 `ConnectError` 不再重试。SDK 隐式重试为 0；假时钟验证每次剩余 timeout 和阶段前后停止，补查前无最终聊天额度就不花 embedding。

证据组分别篡改首/补 envelope 的 query、论文/处理版本、索引、top-k、返回数、状态、rank、页码、score 与正文哈希。全部候选先验证，数量/字符省略后的尾部冲突也必须拒绝；补轮优先顺序不能被跨 query 分数排序改变。

选择组检查 8 条及 8000 Python 字符、Unicode、恰好容纳/超一字符、完整片段和首次溢出即停止。记录区分新召回、新展示及首轮已返回后进入展示；消息 SHA、上下文 SHA 和原 rank/score 可回查。

引用组用临时真实 PDF 和假存储器：未展示/伪造/最终省略 ID 不能发布；存储查找异常、身份/正文/哈希损坏、PDF 缺失/损坏/哈希/页界或路径越界均是工具错误，不能消耗模型修复伪装成成功。输入问题中的指令及伪造 ID 不能扩大范围。

记录组实际运行新增保存基础，而非只模拟一个尚未实现的导出器。五终态 JSON/Markdown、重复 run/batch、原子发布时才发生的冲突、history JSON/渲染/history Markdown/latest Markdown/latest JSON 各阶段失败均有检查。调用者 `with RecordedLLM(...)` 在成功、服务/预算失败和导出失败后都关闭实际客户端；Agent 仍不擅自关闭调用者的其他资源。

## 3. 两项实际缺陷与修复

**非有限值让错误记录无法导出。** 非法候选 `score=NaN/+Inf/-Inf` 本应被拒绝，但 C 先保存原 envelope，导致失败结果仍含非有限数，严格 JSON 导出再次报错。已新增 [agent_records.py](/D:/course/paper-research-assistant/paper_assistant/agent_records.py)，用明确 `diagnostic_invalid_value` 标记及替换路径保存非 JSON 诊断值；验证仍使用原值，没有把非法分数改成 0 或接受为证据。合法证据的额外 metadata 也能安全记录，事实字段和实际展示不变。

[agent.py](/D:/course/paper-research-assistant/paper_assistant/agent.py)因此升级为 `bounded-retry-agent-v2`。A 策略、B 契约/提示词、合并策略、固定 RAG 与正式数据未改。C 原 `v1` 源码已备份，C 的 41 项当时报告不改写；D 统一报告是当前 v2 的适用回归。

**独占发布竞争冲突改写 latest。** 新保存基础的预检查之后，如果真正独占发布才遇到 `FileExistsError`，原实现会误按一般导出失败恢复，替换已有 latest。已把 history JSON/Markdown 的原子冲突也归为 `history_exists`，保留独立恢复事件并跳过 latest 更新；永久回归验证原历史与 latest 字节均保留。

独立审查的临时目录竞争复现与后续永久回归分别记录，未伪称统一检查曾因此失败。非有限值的实际失败日志已保留：

| 运行 | 实际范围/结果 |
|---|---|
| `d_fault_actions_20261005_052304_697757` | 20 方法通过；当时未包含真实 transport 超时/连接异常 |
| `d_fault_actions_20261005_052453_576760` | 补两项后 22 方法通过 |
| `d_fault_evidence_20261005_052546_350654` | 当时 63 方法通过；随后发现记录导出缺陷 |
| `d_fault_evidence_20261005_052710_812405` | 三个定向非有限值回归均出错，完整错误日志保留 |
| `d_fault_evidence_20261005_053145_862144` | 修复并补额外 metadata 回归后 67 方法通过 |
| `check_agent_boundaries_20261005_053206_955566` | 当前统一 186 方法全部通过 |

记录位于 [D8 日志目录](/D:/course/paper-research-assistant/archive/run_logs/d8)，旧通过报告不代替后来新增场景的验证。

## 4. 为记录边界提前提供的基础

新增 [agent_export.py](/D:/course/paper-research-assistant/paper_assistant/agent_export.py)，版本 `d8-immutable-agent-records-v1`。E 将复用两个接口：

```python
reserve_agent_batch(project_root, batch_id, manifest)
saved = save_agent_run(
    {"task": "D8", "mode": "agent", "run_id": run_id, "result": result},
    project_root=project_root,
)
```

`reserve_agent_batch` 在收费前独占创建 D8 批次；已有目录或失败残留目录均拒绝复用。非法 ID、Windows 保留名、路径越界及不可序列化 manifest 在预检查拒绝。

`save_agent_run` 返回独立副本，不修改原结果；历史为 `archive/run_logs/d8/agent_<run_id>.json/.md`，latest 为 `artifacts/d8/agent_result.json/.md`。它只写 D8；外部指定的历史路径和外层伪造终态不能覆盖程序结果。

历史 JSON 是导出前快照，`export.status=prepared`；全部保存完成后 latest/返回副本为 completed。失败时历史不改写，另存恢复事件，返回终态 tool_error 并清除外层与 result 的发布答案；原结果、实际步骤及费用放在 `pre_export_result` 供诊断。若整个磁盘不可写，返回副本仍保留失败和费用，保存标记为 false，由 E CLI 输出到终端。

这是 D 的记录基础，尚无 E CLI、成对运行、断点恢复或页面接入。记录保存不生成答案、不执行检索，也不证明语义准确。

## 5. 文件保护与使用者自检

D 起始核对 816 个受保护文件：815 个保持相同，唯一既有业务修改是有备份及理由的 `agent.py` 诊断记录修复。旧 D5/D6、A/B/C 报告/指南/检查器、正式语料、数据库、向量与冻结验收题不变。见 [保护报告](/D:/course/paper-research-assistant/artifacts/d8/task_d_integrity.json) 和 [修改前快照](/D:/course/paper-research-assistant/archive/planning_snapshots/d8_task_d_20261005/manifest.json)。新模块、测试及完成记录另行绑定。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_agent_boundaries
```

命令只运行离线夹具，保存新的不可覆盖历史并刷新 D 当前报告；本次完成记录仍绑定本次运行，不随重跑改写。建议花约 20 分钟查看两个真实缺陷及对应回归，回答：

1. 186 与 103 分别表示什么？为什么不能说完成了 186 道真实问答？
2. NaN 为什么已经被拒绝，却仍可能破坏故障记录？验证原值与诊断标记怎样分工？
3. 为什么预先检查文件不存在还不能保证独占安全？竞争冲突时为什么保留 latest？
4. 导出失败后怎样确认实际调用没有丢失？发布答案与诊断原结果在哪里？
5. 模拟 transport 超时、阶段 deadline 与进程硬中断分别验证了什么？

使用者学习和新增人工验收未测量。D 的离线结果不表示真实问答改善，也未验证进程严格 120 秒中止；embedding 剩余 deadline 接入仍留 D9。下一项 E 接 CLI、完整运行绑定与成对首轮快照/费用适配，验收题继续留到 D11。
