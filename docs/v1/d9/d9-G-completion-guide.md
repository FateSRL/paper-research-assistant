# D9 G：完成范围、自检与 D10 交接

交接日期：2026-10-07（Asia/Shanghai）。**D9 A–G 已完成记录中的任务范围，状态为 `completed_with_known_issues`。** D2-002 的 Agent 回答仍不完整，新旧答案人审待提供；完整 20 题只准备，D10 开发验证和正式冻结尚未完成。G 本轮只做文件审计、总结和导航更新，新增 embedding、聊天和外部网络请求均为 0。

完成记录见 [task_g.json](/D:/course/paper-research-assistant/artifacts/d9/task_g.json)及 [可读记录](/D:/course/paper-research-assistant/artifacts/d9/task_g.md)。两份独立只读审计分别为 [实验与人审证据](/D:/course/paper-research-assistant/artifacts/d9/task_g_evidence_audit.md)、[当前接口与适用报告](/D:/course/paper-research-assistant/artifacts/d9/task_g_interface_audit.md)。用户四问继续适用：“用户让你做了吗？结果需要它吗？有证据吗？没它会失败吗？”

## 1. A–G 实际完成了什么

| 任务 | 完成范围 | 证据与限制 |
|---|---|---|
| A | 独立起始契约、接口/错误/提交点约定、保护基线 | [A 记录](/D:/course/paper-research-assistant/artifacts/d9/task_a.json)；保留起始观察，目标规则不冒充当时实现 |
| B | 三篇真实摘要范围表、原问题来源约束、两模式资格与逐引用硬校验、Agent 摘要白名单补查 | [B 记录](/D:/course/paper-research-assistant/artifacts/d9/task_b.json)和[来源表](/D:/course/paper-research-assistant/artifacts/d9/source_regions.md)；用户已确认三篇范围与 B 自检总体通过 |
| C | embedding 剩余超时、请求前后与全部终态提交检查、成对公平预算 | [C 记录](/D:/course/paper-research-assistant/artifacts/d9/task_c.json)；请求与阶段预算已连接，严格 120 秒进程强制退出未证明 |
| D | 来源/时间/故障组合、旧流程兼容与失败保存 | [D 记录](/D:/course/paper-research-assistant/artifacts/d9/task_d.json)；485 方法通过，其中新增组合 12，按当前源码绑定继承 |
| E | D9 独立运行配置、两模式 CLI/页面、显式 D9 成对批次、独立历史/latest、提交防重跑与会话纯下载 | [E 记录](/D:/course/paper-research-assistant/artifacts/d9/task_e.json)；21/29/13 方法通过，页面两模式五终态共 10 份实际组件树 |
| F | 旧六题独立 AI 补评；新四题八模式首次/账本/AI 与人审材料；新完整 20 题零请求准备 | [F 记录](/D:/course/paper-research-assistant/artifacts/d9/task_f.json)；完整性问题和人审 pending 保留 |
| G | 当前证据与接口独立只读核对、学习自检、D10/D11 门槛、导航备份与汇总 | 本指南和 G 记录；没有再问模型、修改业务规则或执行完整 20 题 |

D9 使用 [runtime_config.json](/D:/course/paper-research-assistant/artifacts/d9/runtime_config.json)，schema `d9-runtime-policy-v1`，运行版本 `d9-owned-two-mode-runtime-v1`；A 的 [agent_config.json](/D:/course/paper-research-assistant/artifacts/d9/agent_config.json) 保留原始契约。运行配置同时绑定 A 契约与 B 的人审来源表，不能把起始契约当作 D10 最终冻结。

固定来源仍是三篇固定版本 PDF、71 页、1188 个 chunk（RAG 385 / ReAct 480 / Reflexion 323），profile `ep_cbf0f6caa97b962a`；模型公开记录为 `deepseek/deepseek-flash` 与 `dashscope/qwen3.7-text-embedding`（1024 维）。本阶段没有更换模型、重新入库或重建向量。

## 2. D9 相比 D8 改在哪里

原问题明确要求摘要时，程序先从核定文档结构确定来源范围，再筛选候选和验证每条实际引用。PDF 第 1 页、关键词、相似度和模型自报章节均不能作为摘要身份。范围表绑定论文/处理版本、PDF 与解析/过滤/分块哈希、segment/块/行/字符区间及文本哈希；未知或跨摘要正文的完整 chunk 不作为纯摘要证据，不裁掉正文制造合格来源。

两模式继续共享首轮 top-5。固定模式来源不足即不足；Agent 可在原要求不变的条件下一次摘要 point 白名单补查，范围与完整版本/profile 取交集。原始召回、来源合格候选、实际展示与排除原因分别记录，“召回了正文但不合格”不能记成物理 no_hits。每条发布引用都须来自最终实际展示，引用修复不能重新开放检索。

每模式总预算 120 秒，单请求上限 30 秒；embedding 在实际发送前重新取剩余时间，超时为 `min(30, remaining)`，未发送计 0、已发送失败计 1，未知用量保留 null。首检索耗时分别扣入两模式，另一模式等待不扣；补查、网络重试与共享一次修复不重置预算。Agent 最多两轮检索、最终最多 8 条完整证据 / 8000 Python 字符、聊天最多 3 次 SDK 尝试。同步本地操作可能阻塞，阶段检查不等于整个进程在 120 秒被强制终止。

需要分别看四层结果：**引用定位合法 → 章节来源合规 → 原文支持结论 → 完整回答原问题**。前三层通过，仍可能卡在第四层。

## 3. 新旧实验怎样交接

F1 补评旧 `d6_f_dev16_20261004` 的 D5-001–006：4 份回答、9 条结论、10 次实际引用、2 份不足理由与 30 次展示核对；4 回答完整有据，2 次资料外拒答合理。结果与首次历史 SHA 绑定，没有重新生成答案或追改旧成绩。见 [旧六题补评](/D:/course/paper-research-assistant/artifacts/d9/legacy_dev6_review.md)。旧六题答案人审仍 pending。

F2 新 `d9_f_dev4_20261006` 四题八模式各留首次：

| 题目 | 固定 RAG | Agent | 独立 AI 观察 |
|---|---|---|---|
| D2-001 两种记忆 | 回答 | 回答，无补查 | 两模式完整有据 |
| D2-002 两种文档使用机制 | 本轮不足 | 回答 2 条相关事实，无补查 | 事实有据，缺少 Sequence 整段用同一文档 / Token 每 token 可用不同文档；两模式均未完成可答题 |
| D2-003 摘要点名的基准 | 首轮 5 条正文全排除，0 聊天，不足 | 一次白名单补查，引用完整核定摘要 | 两模式守住来源边界；Agent 回答 HotpotQA/Fever，整题完成 |
| D5-006 资料外项目日期 | 不足 | 不足 | 两模式合理拒答 |

D2-003 实际摘要 chunk 为 `arxiv_2210.03629v3_r_22af23d03fcb87a8_p1_c6`，PDF 文件第 1 页、核定 segment 字符范围 `[0,1545)`。固定拒答保住来源边界，仍不算完成可答题；Agent 新结果不能追溯替换 D8 引用第 4 页正文的失败记录。

程序可答生成观察是固定 1/3、Agent 3/3；AI 按支持与完整性观察为固定 1/3、Agent 2/3；负题合理拒答各 1/1。14 条发布结论各获自身实际引用并集支持；18 次引用定位通过，逐引用 14 次完整支持 / 4 次部分支持。新结果人审 0/8、QA accuracy 未测量。这些是四道开发题观察，不推出 Agent 整体优于 RAG；新 D2-002 没有补查，不能声称这一轮补查收益。

| 账本口径 | Embedding 次数 / tokens | 聊天 SDK/HTTP 次数 / 已知 tokens |
|---|---:|---:|
| 实际四题批次 | 5 / 191 | 8 / 16781 |
| 固定独立运行的逻辑归属 | 4 / 165 | 3 / 6407 |
| Agent 独立运行的逻辑归属 | 5 / 191 | 5 / 10374 |

四次共享首轮实际只算一次，Agent 摘要补轮另算一次，逻辑 embedding 不相加当实际费用。网络重试和输出修复均为 0。原聊天 `total_tokens=null` 由固定 D2-003 零聊天占位统计传播；8 次实际聊天响应都有 usage，已知总量 16781，原首次统计未改写。D8 原四题 5 embedding / 201 tokens、9 chat / 22188 tokens 是另一批历史，不合并成 D9 费用。

F3 新 [完整 20 题 manifest](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev20_prepared_20261006/manifest.json)和 [state](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev20_prepared_20261006/state.json)：17 可答 / 3 负题，33 份源码、175 份保护输入及当前策略/来源表/公开配置/rubric 已绑定，仅 prepared、0 attempt、0 输出、0 请求。不能向已完成四题批次追加 16 题，也不能拼旧四题成绩作为同一新冻结实验。

## 4. 当前验证证据怎样使用

[D 边界报告](/D:/course/paper-research-assistant/artifacts/d9/d_boundary_validation.md)的 485 方法与 E 的 [入口 21](/D:/course/paper-research-assistant/artifacts/d9/e_runtime_validation.md)、[成对/导出 29](/D:/course/paper-research-assistant/artifacts/d9/e_batch_validation.md)、[页面 13](/D:/course/paper-research-assistant/artifacts/d9/e_page_validation.md)仍与当前相应源码 SHA 一致，按适用范围继承；G 不重复运行这些 checker。D 的模拟聊天 435 / embedding 11，E 的模拟聊天 13 / 42、页面预设调用与框架 loopback 都不算真实供应商请求。方法存在兼容交集，不相加成独立场景总数。

[F 保存产物审计](/D:/course/paper-research-assistant/artifacts/d9/task_f_integrity.md)的 12 条证据链、9/14 条结论、10/18 次引用及保护文件数都各有单位，不加进测试方法或题数。首次失败、修复前源码、D/E 失败现场与后续通过记录分别保留。G 独立审计检查当前源码绑定和产物，不把历史导航 SHA 追改为最新值；G 更新四份导航有事前备份和最终 SHA。

本轮保护继承 1298 份文件；业务源码、策略、来源表、正式数据、验收冻结文件、A–F 和 D8 历史保持。G 完成清单及备份见 [最终保护清单](/D:/course/paper-research-assistant/archive/planning_snapshots/d9_task_g_20261007_041749_791409/completion_manifest.json)。验收文件只核对原始字节 SHA，没有读取题面用于优化、问答或演示。

## 5. 命令与实际入口

先在项目根目录操作。以下两条帮助命令不问模型：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.answer_question_d9 --help
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --help
```

单次入口使用 `scripts.answer_question_d9 --mode fixed_rag|agent --query ... --version PAPER_ID PARSE_REVISION`；`--version` 可重复传 1–3 个完整版本。页面用 `.\.venv\Scripts\python.exe -m streamlit run app.py`，选择模式后明确提交才调用模型。改模式、展开证据、重绘、下载只读当前会话保存结果；新提交即新运行。页面与 CLI 不能同时占用本地 Qdrant 目录。使用与状态详见 [E 指南](/D:/course/paper-research-assistant/docs/v1/d9/d9-E-runtime-guide.md)，真实问答会产生费用。

单次 latest 位于 `artifacts/d9/fixed_rag_result.json/.md` 和 `agent_result.json/.md`，不可覆盖历史位于 `archive/run_logs/d9/`，成对批次位于 `artifacts/d9/comparison/`。单次成功回答/不足且导出成功退出 0，业务或导出故障退出 1、参数错误退出 2；成对 prepared/completed 退出 0、attention-required 退出 1、预检/输入错误退出 2。退出 0 不等于答案完整正确。

**以下交接命令会发真实请求，G 没有执行。** D10 开始且全部绑定保持一致时，可以执行已有完整 prepared 批次：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --stage d9 --batch-id d9_f_dev20_prepared_20261006 --execute-prepared
```

如果先修 D2-002 等问题，或改源码/策略/范围/公开配置，原 prepared 失效，应使用新批次名并显式准备全部 20 个开发 ID：

```powershell
$d10CaseIds = @(Get-Content -LiteralPath 'eval/dev.jsonl' -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object { ($_ | ConvertFrom-Json).case_id })
$d10BatchId = 'd10_dev20_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.run_agent_comparison --stage d9 --batch-id $d10BatchId --case-ids $d10CaseIds
```

准备命令只写新 manifest/state、不发模型请求；它使用当前 D9 runtime，不代表已经实现新的 D10 strategy。runner 默认仍是 D8，必须显式 `--stage d9`。`--live` 为新建并执行、`--execute-prepared` 执行未尝试批次、`--resume` 只续未尝试题，三者互斥；已经预占/尝试的题不能借 resume 自动重播；已有 attempt 却缺最终记录时先核对失败现场，不删除 attempt 重跑。当前 runner 只接 dev，没有验收 split，D11 不能拿此命令冒充验收。

只核对 G 保存清单，可用下面的零模型请求命令。它不改报告或连接正式库：

```powershell
$gPath = 'archive/planning_snapshots/d9_task_g_20261007_041749_791409/completion_manifest.json'
$gRecord = Get-Content -LiteralPath $gPath -Raw -Encoding utf8 | ConvertFrom-Json
$gExpected = @{}
$gRecord.protected_expected_sha256.PSObject.Properties | ForEach-Object { $gExpected[$_.Name] = $_.Value }
$gRecord.authorized_updates | ForEach-Object { $gExpected[$_.path] = $_.after_sha256 }
$gRecord.newly_created_files_sha256.PSObject.Properties | ForEach-Object { $gExpected[$_.Name] = $_.Value }
$gBad = @(foreach ($gEntry in $gExpected.GetEnumerator()) {
    if (!(Test-Path -LiteralPath $gEntry.Key -PathType Leaf)) { $gEntry.Key }
    elseif ((Get-FileHash -LiteralPath $gEntry.Key -Algorithm SHA256).Hash.ToLower() -ne $gEntry.Value) { $gEntry.Key }
})
if ($gBad.Count) { $gBad; throw '保存文件发生变化，请先核对变更来源' }
'G 保存绑定一致：' + $gExpected.Count + ' 个文件'
```

这检查文件一致性，不代替语义评价。后续 D10 有意修改源码或导航后出现差异，表示应建立后续版本，不追改 G 清单。

## 6. D10 / D11 先做什么

| 后续工作 | 输入与完成门槛 |
|---|---|
| D10 先定位 D2-002 完整性不足 | 对照原问题、最终实际展示、决策、两条结论与引用；区分缺机制证据、未补查或生成偏离。改进应适用同类机制问题，不读取题号/标准答案去硬编码回答。任何修改需版本记录、受影响回归和新 prepared |
| D10 完整开发验证 | 修复版本 20 题 × 两模式，保存 40 模式首次/失败；17 可答与 3 负题按计划分母分别统计，生成状态/精确命中/来源/支持/完整性分开，实际与逻辑账本分开，AI 与人审分开，未审 pending |
| D10 根据开发证据修最高优先级问题并正式冻结 | 固定源码、提示/动作/选择/来源策略、范围表、公开模型配置、语料/索引、题集与 rubric；密钥不入记录。冻结后变更另建版本，复测不覆盖首次 |
| D11 实现验收入口并离线验证后再首次运行 | 使用冻结验收 20 题 × 两模式，共 40 模式首次、完整评分和费用；验收前不取题面作优化/演示，失败不覆盖，复测明确另标版本 |

D3 恢复稿人审、全量旧答案人审保持各自待办。D7 新环境预演、录屏、简历和投递继续暂缓；本轮交接不代表这些已完成。当前也没有全量人工准确率、最终验收成绩、广义来源语言理解或严格 120 秒进程强杀的证据。

## 7. 你怎样检验与学习

用 20–30 分钟查看已保存材料即可，不必重跑付费批次。先读 [新八模式人审材料](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/human_review.md)，再对照 [AI 评价](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/ai_semantic_review.md)和 [F 对照说明](/D:/course/paper-research-assistant/docs/v1/d9/d9-F-comparison-guide.md)：

1. D2-003：找到固定首轮的正文排除与 Agent 补轮的完整摘要，说明“位置合法”和“章节合规”的区别。
2. D2-002：用原问题解释为什么两条事实有引用支持，仍未答全 passage 使用机制。
3. 看 [C 预算案例](/D:/course/paper-research-assistant/docs/v1/d9/d9-C-budget-guide.md)：120 秒先耗 119 秒后，请求只剩约 1 秒；未发请求 0 次与发出失败 1 次怎样记账。
4. 看 [E 页面案例](/D:/course/paper-research-assistant/artifacts/d9/e_page_validation.md)：结果归属哪个提交，为什么改模式/重绘/下载不能再调用模型。
5. 解释实际 embedding 为什么是 5 次而逻辑归属共 9 次；再看两个 manifest，说明源码改动为何需要新批次。

如需跟代码学习，只看 [source_scope.py](/D:/course/paper-research-assistant/paper_assistant/source_scope.py)、[citations.py](/D:/course/paper-research-assistant/paper_assistant/citations.py)、[embedding_client.py](/D:/course/paper-research-assistant/paper_assistant/embedding_client.py)、[d9_runtime.py](/D:/course/paper-research-assistant/paper_assistant/d9_runtime.py)与 [agent_comparison.py](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py)对应函数；基础是字典/列表、参数、异常、哈希、单调时钟和 session_state，不需补完课程再检验。

人审时说明确认的是整题结论、逐条结论还是逐次引用。B 范围表已确认、D8 旧四题总体确认均保留；F 新八模式和旧六题补评没有继承这些确认。学习清单不表示用户已经掌握或已人审。
