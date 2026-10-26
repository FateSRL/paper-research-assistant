# D9 B：摘要来源范围与共用发布校验

执行日期：2026-10-06（Asia/Shanghai）。本任务对应 [D9 计划的 B](/D:/course/paper-research-assistant/docs/v1/d9/d9-ABCDEFG-plan.md#5-任务-b摘要要求必须落到实际引用范围)。用户四问继续适用：“用户让你做了吗？结果需要它吗？有证据吗？没它会失败吗？”

## 1. B 改了什么

问题来自 D2-003：题目要求 **ReAct 摘要**点名的问答与事实核查基准，旧 Agent 引用第 4 页正文回答 HotPotQA、FEVER。名字正确、引用可以定位，但“摘要里说了什么”需要摘要证据。B 把这个要求接入程序校验。

三篇现有论文都有独立的 [摘要范围表](/D:/course/paper-research-assistant/artifacts/d9/source_regions.md)及 [JSON 绑定](/D:/course/paper-research-assistant/artifacts/d9/source_regions.json)。核定依据是原 PDF 的 Abstract → Introduction 段落结构、实际解析块/行、过滤 segment 和完整字符区间。范围表同时绑定 PDF、解析、过滤、不可变分块快照和核定图片的 SHA256；程序会重新核对这些文件及候选原文。范围表不包含题号或答案要点。

核定状态是 **AI 结构复核 verified、人审 confirmed**。用户明确“人审全部通过”，三篇范围及 B 自检项目已记录为用户总体确认，见 [人审记录](/D:/course/paper-research-assistant/artifacts/d9/human_review_confirmation.md)。已查看三篇原 PDF 首页的完整渲染图；“在第一页”“含 Abstract 关键词”“模型说这是摘要”都不能替代范围匹配。现有数据没有重新解析、重新分块或重新生成向量。完整 chunk 横跨边界时不会裁剪成纯摘要证据。

来源要求由原问题确定，支持明确的 `in the abstract`、`the paper's abstract names`、`摘要中/摘要提到` 等表达。包含摘要字样但否定、引用或混合章节要求的表达保守记为歧义并停止；普通 `abstract class` 不自动成为摘要要求。这是有限规则，不是通用自然语言理解器。

## 2. 运行时会怎样

| 条件 | 固定 RAG | Agent |
|---|---|---|
| 首轮检到正文，但没有合格摘要可展示 | 保留原搜索 success，来源不足，聊天请求 0 | 首次动作只开放一次补查或不足 |
| 首轮有合格完整摘要 | 按合格展示生成，逐引用检查 | 正常决策，可按预算选择一次补查 |
| 摘要补查 | 固定模式没有补查 | 只检索程序计算的摘要 point 白名单，与原论文/版本/profile 取交集，仍 top-5 |
| 表有效，但尚未核定或没有完整可用摘要 chunk | 程序直接返回来源不足 | 同左；不发送明知无可用范围的检索或聊天请求 |
| 表缺失、文件/版本/原文不一致或人审状态矛盾 | tool_error | tool_error；不能让模型修复数据 |
| 模型引用正文、混合片段或未展示的摘要 | 使用剩余共享修复；仍错不发布 | 同左；修复只允许终态，不能重新开检索 |
| 补查没有新增合格展示 | 不适用 | 来源不足，不执行第三次检索 |

原始物理 top-5 及 rank 留在检索记录，来源资格、排除原因和展示映射放在外层 `source_qualification`。不能把“检到了正文，但不合格”改写成物理 `no_hits`。**每条结论的每一个引用**都要满足原问题来源要求，一条摘要引用不能替另一条正文引用过关。

原问题约束会进入首次、补轮和修复的提示消息；补查 query 可以改变，来源要求不能随之解除。合并仍按补轮 rank、首轮 rank 顺序，去重后最多 8 条完整证据、8000 Python 字符，不跨查询混排相似度分数。聊天最多 3 次 SDK 尝试，格式/动作/引用共享 1 次修复，补检索最多 1 次。

发布时根据原始检索与当前范围表重新构建资格和上下文，不能信任调用者改过的 eligible 标志或表面哈希。即使某条原始候选最终被排除，身份或原文损坏仍归工具错误。

## 3. 接口与当前接入范围

| 位置 | B 的变化 |
|---|---|
| [source_scope.py](/D:/course/paper-research-assistant/paper_assistant/source_scope.py) | 来源要求、只读 Registry、资格筛选、合并和逐引用校验 |
| [rag.py](/D:/course/paper-research-assistant/paper_assistant/rag.py)、[agent.py](/D:/course/paper-research-assistant/paper_assistant/agent.py) | 显式 `source_registry` 参数；来源不足、受限补查、共享终态修复 |
| [generation.py](/D:/course/paper-research-assistant/paper_assistant/generation.py)、[agent_prompt.py](/D:/course/paper-research-assistant/paper_assistant/agent_prompt.py) | 原问题来源要求随正常消息和修复消息保留 |
| [search.py](/D:/course/paper-research-assistant/paper_assistant/search.py) | `allowed_point_ids=None`；先核验完整 ready 范围，再取白名单交集；非法/空列表在 embedding 前拒绝 |
| [agent_comparison.py](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py) | 首轮共享未过滤快照，补轮传递摘要白名单，两模式共用来源前检查 |

`source_registry=None` 保留旧调用行为。开启来源约束时使用独立 D9 来源版本；**现有 CLI/页面仍没有自动开启 B**，受控 D9 配置、stage、导出与页面接入留给 E。A 的起始配置/观察字段是历史记录，没有改写成“B 已经存在于 A 时”。embedding 剩余时限及终态提交点留给 C。

程序能证明来源范围与引用位置合规，不能证明所有结论完整、语义正确。完整开发实验和答案语义评分仍待后续任务，旧 D8 四题的成绩不能转成修复版本成绩。

## 4. 验证与复跑

当前离线结果和失败修复证据见 [B 完成记录](/D:/course/paper-research-assistant/artifacts/d9/task_b.md)。报告绑定执行时源码和输入哈希，首失败及后续成功各有独立历史。测试使用临时 PDF/SQLite/Qdrant、合成材料、旧 D2-003 物理首轮快照及真实 SDK 的 MockTransport；没有发出实际 embedding/chat 请求，没有使用验收题面。

在项目目录执行以下命令可复跑必要离线检查。`check_scoped_search` 的 23 项新检查输出到控制台；其余三项另存 D9 历史并更新当前报告。本次还单独保存了 38 项受影响的旧检索/成对兼容检查：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_source_scope
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_scoped_search
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_scoped_answering
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.check_d9_b_compatibility
```

范围表生成器只针对已进行结构核定的三篇固定版本，使用不可覆盖写入；不是给新论文自动授予 verified 的入口。已存在的表不要删除后直接重建；改范围需新的复核、版本和绑定。

## 5. 你怎样检验成果

用 15–20 分钟即可，基础是列表/字典、函数参数、异常与哈希，不需要先学习整套 Agent 框架。

1. 打开 [ReAct 原 PDF](/D:/course/paper-research-assistant/data/papers/2210.03629v3.pdf)，找到第一页 Abstract 和 Introduction。对照范围表，确认摘要起止；第一页作者信息和 Introduction 不能算摘要。三篇核定图片位于范围表链接中。三篇范围的人审已按本次用户总体确认记录通过。
2. 看旧 [D2-003 首次结果](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/D2-003.json)：名字对了为什么仍失败？答案是原题要求摘要，实际引用来自正文。
3. 看新离线记录：固定 RAG 应保留物理搜索成功、合格展示空，并直接不足；Agent 正常选择补查时应只补一次，最后 context 的 question 仍是原题。
4. 看越界反例：没有摘要却回答，或一个结论同时引摘要与正文，不能得到可发布答案；修复后再请求检索也不能实际追加一轮。
5. 看数据损坏反例：来源表哈希或候选原文不匹配，应是 tool_error，不能靠“模型再回答一次”消除。暂未核定则是正常不足，这两个状态不同。

本次“人审全部通过”已记录为 B 的用户总体确认，未另外提供逐行/逐引用评分表，也未测量新答案语义准确率。确认前范围表和原测试绑定保留；确认后的范围表重新绑定，并用必要的两项既有来源/成对检查验证。以后改变审核结论仍需另存记录和建立新绑定。
