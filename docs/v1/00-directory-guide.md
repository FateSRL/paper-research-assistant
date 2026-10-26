# 目录使用说明：当前文件与历史归档

整理日期：2026-10-01；进度导航更新于 2026-10-07（D8 A–G 工程范围完成，D9 A–G 记录范围完成并保留已知问题，D10 A–G 已完成记录范围、状态 `completed_with_known_issues`，D7 暂缓）。正式开发集为 20 题，另有 20 题已人审冻结的验收集；PDF 为三篇固定版本、共 71 页。D4 已完成三篇 1188 个 chunk 的分块、原文/向量入库与指定版本检索，三个版本均 ready；旧各阶段历史与人工确认分别保留。D10 同批次 20 题、40 模式、89 条 claim 已完成 AI 评价；固定 RAG / Agent 的严格完整有据可答题为 13/17、15/17，负题合理拒答各 3/3，新答案人审 pending。下一阶段 D11，专用验收入口尚待实现、验收尚未运行，验收题面未用于调优；开发集 AI 结果不代表验收或人工准确率。

D5 当时交接状态（历史）：A–E 已完成，F 已保存十题首次真实运行、机器统计和 AI 评价：7 answered、3 不足，其中 2 道可回答题缺所需依据；引用定位合法 21/21。G 已完成工程证据核对与 D6 交接，本轮模型请求 0，旧测试按当前源码绑定继承。D5 总状态为“实现完成，评测/人审待补”：六题仍为候选，正式十六题初跑与新答案人审未完成。F 既有用量为 embedding 10 次/379 tokens、聊天 10 次/22612 tokens，各阶段旧记录分别保留。

D6 状态（2026-10-04，A–G 全部完成）：开发集经两次人审扩充达到 20 题（10 fact / 4 method / 3 retrieval_paraphrase / 3 unanswerable），三个批次首次运行分别保留；20 条验收题人审并冻结，留到 D11。C 的 top-k 对照：返回候选 9/13、11/13、13/13，实际展示 9/13、11/13、12/13；8 道触发预算停止，仅 D2-004 遗漏依据。D 的最小页面 27 项检查、一次真实浏览器问答与下载通过；E 四题首跑 4 answered、精确命中 4/4；F 的 `validate_d6.py` 已强化为 680 项核对，并新增 25 项篡改回归；G 完成汇总交接与 D7 投递清单。汇总与下一步见 [G 完成指南](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)，当前状态以 [D6 总计划](/D:/course/paper-research-assistant/docs/v1/d6/d6-ABCDEFG-plan.md) 为准。

D8 当前状态（2026-10-05）：A–G已完成记录中的工程范围，D7暂缓，已知问题与全量评测待补。受控Agent/独立CLI/成对runner/完整轨迹与预算已实现，页面仍固定RAG；当前G186方法回归通过，182模拟HTTP，真实API 0，E119按当前SHA继承且14方法重叠。F四题八模式首次保留，实际embedding5/201tokens、聊天9/22188tokens；用户确认AI总体结论，D2-002补查支持、D2-003摘要来源失败，QAaccuracy未测量。当前命令、证据和D9–D11完成门槛见 [G指南](/D:/course/paper-research-assistant/docs/v1/d8/d8-G-completion-guide.md)、[G记录](/D:/course/paper-research-assistant/artifacts/d8/task_g.json) 和 [D8计划](/D:/course/paper-research-assistant/docs/v1/d8/d8-ABCDEFG-plan.md)；F细节见 [F指南](/D:/course/paper-research-assistant/docs/v1/d8/d8-F-comparison-guide.md) 与 [用户确认](/D:/course/paper-research-assistant/artifacts/d8/comparison/d8_f_dev4_20261005/human_review_confirmation.md)。D9先补来源硬检查/时限、按需页面/旧六题AI；D10新20题开发验证与正式冻结，D11验收入口待实现再执行，原四题manifest不能追加16题。D7与旧人审范围保留。

D9 当前状态（2026-10-07）：[A–G 计划](/D:/course/paper-research-assistant/docs/v1/d9/d9-ABCDEFG-plan.md) 的 A–G 已完成记录范围，整体 completed_with_known_issues。B 三篇摘要范围已人审确认，来源/预算/新入口/页面与适用回归完成；F 旧六题 AI 补评、新四题八模式首次/AI/待人审包、完整 20 题 prepared 保存。D2-003 Agent 摘要补查完整回答，D2-002 事实有据但未解释机制；AI 完整观察固定 1/3、Agent 2/3，新旧答案人审 pending。F 实际 embedding 5/191 tokens、聊天 8/已知 16781 tokens；G 文件审计/交接新增请求 0，D/E 按当前源码 SHA 继承，原源码/数据/历史不改。见 [G 交接指南](/D:/course/paper-research-assistant/docs/v1/d9/d9-G-completion-guide.md)、[G 记录](/D:/course/paper-research-assistant/artifacts/d9/task_g.json)、[F 人审材料](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/human_review.md)。下一步 D10 完整开发验证与正式冻结，D11 验收入口及首次运行尚待实施；D7 暂缓。

## 文档分组与命名规则（2026-10-05）

D10 当前状态（2026-10-07）：[D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md) 的 **A–G 已完成记录范围，状态 `completed_with_known_issues`，下一阶段 D11**。同一批次 `d10_d_dev20_20261007_195707` 的 40 模式、89 条 claim 已完成 AI 评价与冻结交接，严格完整有据可答题为固定 RAG 13/17、Agent 15/17，负题合理拒答各 3/3，新答案人审 pending。D2-002 Agent 补查后机制完整有据；D3-004 章节/实验归属和 D6-003 生成者歧义作为已知问题保留。G 只汇总交接，结果、提示和配置不变，没有新增源码行为、测试、哈希或模型请求。见 [G 独立日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-G-completion-guide.md)及 [开发总结第 7 节 G 交接](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md:414)。D11 专用验收入口尚待实现、验收尚未运行，验收题面未用于调优；开发集 AI 评价不代表验收或人工准确率，D7 暂缓。

D10 E/F 执行时记录（2026-10-07，历史，保留当时状态）：[D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md) 的 **当时 A–F 已完成，G 待执行，下一步 G 汇总交接**。E 已完成同批次全部 40 模式的 AI 事后评价，严格完整有据可答题为固定 RAG 13/17、Agent 15/17，负题合理拒答各 3/3，新答案人审 pending。D2-002 Agent 补查后机制完整有据；D3-004 两模式章节/实验归属未独立证实，D6-003 两模式生成者措辞歧义，均保留为已知问题。F 直接冻结 D 的同一批次 `d10_d_dev20_20261007_195707`，提示版本未再改，没有新增测试、哈希或模型请求。见 [开发评价与冻结说明](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md)、独立 [E 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-E-semantic-review-guide.md)、[F 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-F-freeze-guide.md)。当时 G 尚未执行，D10 未整体完成；D11 专用验收入口和首次运行仍待实施，验收题面未用于调优。

D10 C/D 执行时记录（2026-10-07，历史）：[D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md) 的 **当时 A–D 已完成，E–G 待执行，下一步 E 逐题评价**。C 复用 A/B 已通过的 AST 语法结果，没有新增测试、哈希或模型请求，见独立 [C 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-C-verification-guide.md)。D 已完成新批次 `d10_d_dev20_20261007_195707` 的 20 题、40 模式输出，导出成功、CLI 退出 0，见独立 [D 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-D-development-run-guide.md)。D2-002 本次实际补查并输出两机制，支持与完整性留 E；机器状态和用量不作为准确率，语义评价与新答案人审尚未完成。D9 G 的旧哈希/审计门槛仅作历史说明，精简前 prepared 未执行。

D10 A/B 执行时记录（2026-10-07，历史）：[D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md) 的 A/B 已完成，C–G 待执行。A 已定位缺机制证据却直接回答的问题；B 只调整现有 Agent 系统提示，覆盖比较、机制及多部分问题：缺证据且选定论文内可补查、允许 `retry_search` 时补查，证据足够时直接回答，补查或修复终态仍不足时拒答。提示版本为 `d10-question-complete-agent-v1` / `d10-source-scoped-agent-v1`，固定 RAG 与检索预算不改；语义效果留 D/E。本轮仅检查修改文件语法，未运行测试、模型或真实问答，未做哈希审计。下一步 C 按实际改动判断必要验证，D 新建并执行完整 20 题双模式开发批次；D9 G 的旧哈希/审计门槛仅作历史说明，精简前 prepared 不直接执行。

文档按实施阶段放入子文件夹：D4 的 6 份说明在 `docs/d4/`，D5 的 9 份说明在 `docs/d5/`。跨阶段的目录说明和两周总计划留在 `docs/` 顶层；D6 计划与说明放入 `docs/d6/`，D7 暂缓计划在 `docs/d7/`，D8 计划与 A–G 指南在 `docs/d8/`，D9 计划与 A–G 指南在 `docs/d9/`，D10 计划、A/B 日志及各自独立的 C/D/E/F/G 日志在 `docs/d10/`；完整开发评价、冻结说明与 G 交接集中在 `artifacts/d10/dev_comparison.md`，后续阶段沿用同一规则。

```text
docs/
├── 00-directory-guide.md   目录入口
├── plan-codex.md           两周总计划
├── d4/                    D4 总计划、任务 C–G 说明
├── d5/                    D5 总计划、任务 A–G 说明、设计问答
├── d6/                    D6 总计划与任务说明
├── d7/                    D7 交付计划（暂缓）
├── d8/                    D8 计划与 A–G 指南（工程范围完成）
├── d9/                    D9 计划与 A–G 指南（记录范围完成）
└── d10/                   D10 计划与 A/B、C、D、E、F、G 日志（A–G 已完成记录范围）
```

`d4-`、`d5-` 表示实施日；紧随其后的 `A`–`G` 表示对应任务。`ABCDEFG-plan` 是当天全部任务的总计划，`00-directory-guide` 是跨任务的目录入口。例如 `d4-C-storage-guide.md` 对应 D4 任务 C，`d5-A-contract-guide.md` 对应 D5 任务 A；后续说明沿用同一规则。

任务字母的首次重命名记录见 [重命名清单](/D:/course/paper-research-assistant/artifacts/d5/docs_rename_manifest.json)，本次分文件夹的对应关系和原文件备份见 [分组清单](/D:/course/paper-research-assistant/artifacts/docs_stage_reorganization.json)。当前导航和验收脚本里的文档路径已更新；旧验收、评测和运行快照中的路径与 SHA 保留原样。遇到历史路径 `docs/d4-*.md` 或 `docs/d5-*.md`，分别到 `docs/d4/` 或 `docs/d5/` 找同名文件。

## 1. 平时按这个顺序找文件

| 要做的事 | 读取哪里 | 是否是当前版本 |
|---|---|---|
| 看项目状态和常用命令 | 根目录 `README.md` | 当前入口 |
| 查看 D10 完成范围与下一阶段 | `docs/d10/d10-ABCDEFG-plan.md` | A–G 已完成记录范围，completed_with_known_issues；下一阶段 D11，专用验收入口尚待实现，验收尚未运行 |
| 学习 D10 A/B、查看工作日志与答案 | `docs/d10/d10-AB-log-and-study-guide.md` | 实际定位与提示改动日志、约 45 分钟代码走读、八道练习及参考答案；未作学习通过确认 |
| 学习 D10 C、查看验证选择与答案 | `docs/d10/d10-C-verification-guide.md` | C 已完成，复用已有 AST 语法结果；独立日志、约 16 分钟学习路线、四道题及答案，没有新增测试或哈希 |
| 学习 D10 D、查看开发执行与答案 | `docs/d10/d10-D-development-run-guide.md` + `artifacts/d9/comparison/d10_d_dev20_20261007_195707/` | D 已完成 20 题、40 模式输出并导出；独立日志及学习答案，机器指标与用量已保存，E 评价另见下行 |
| 查看 D10 E 完整评价、学习与答案 | [开发评价](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md) + [E 独立日志](/D:/course/paper-research-assistant/docs/v1/d10/d10-E-semantic-review-guide.md) | E 已完成 40 模式 AI 评价；严格完整有据可答题固定 13/17、Agent 15/17，负题合理拒答各 3/3，人审 pending |
| 查看 D10 F 冻结、学习与答案 | [同版本冻结说明](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md) + [F 独立日志](/D:/course/paper-research-assistant/docs/v1/d10/d10-F-freeze-guide.md) | F 已直接冻结同一 D 批次与提示版本，保留已知问题；F 日志保留当时 G 待执行状态，当前 G 交接见下行 |
| 查看 D10 G 完成与 D11 交接 | [开发总结第 7 节](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md:414) + [G 独立日志](/D:/course/paper-research-assistant/docs/v1/d10/d10-G-completion-guide.md) | G 已完成记录范围，仅汇总交接，无新增源码行为、测试、哈希或模型；D11 入口尚待实现、验收尚未运行，人审 pending |
| 直接从 D6 继续 D8 | `docs/d8/d8-ABCDEFG-plan.md` | A–G工程范围完成并保留已知问题，D7暂缓；四题冒烟与全量开发/最终验收分开 |
| 看 D9 完成并继续 D10 | `docs/d9/d9-ABCDEFG-plan.md` + `docs/d9/d9-G-completion-guide.md` + `artifacts/d9/task_g.json` | A–G 记录范围完成；当前接口/适用证据、自检与 D10–D11 门槛，D2-002 与人审待办保留 |
| 看 D8 A 契约与学习自检 | `docs/d8/d8-A-contract-guide.md` + `artifacts/d8/agent_config.json` + `artifacts/d8/task_a.json` | A 当时的初始策略与57项绑定预检；用户学习未测量，当前编排见 C |
| 看 D8 B 动作与阶段自检 | `docs/d8/d8-B-action-guide.md` + `artifacts/d8/task_b.json` + `artifacts/d8/agent_action_boundary_validation.json` | B 的严格三动作、证据与修复消息、42项离线检查；当前编排见 C，用户学习未测量 |
| 看 D8 C 编排与停止自检 | `docs/d8/d8-C-agent-guide.md` + `artifacts/d8/task_c.json` + `artifacts/d8/agent_orchestration_validation.json` | C当时的一次补查API、共享预算/最终引用及41项检查；当前D修复/统一回归见下行，问答收益未测量 |
| 看 D8 D 边界与故障自检 | `docs/d8/d8-D-boundary-guide.md` + `artifacts/d8/task_d.json` + `artifacts/d8/agent_boundary_validation.json` | D当时186方法全过（新增D103），记录恢复/批次独占基础；当前E入口见下行，真实API 0 |
| 使用 D8 E CLI / 成对入口与自检 | `docs/d8/d8-E-cli-guide.md` + `artifacts/d8/task_e.json` | E当时的独立问答、D8历史/恢复、共享首轮预算和多轮事后评分；当前F真实实验见下行 |
| 看 D8 F 真实成对实验与人审 | `docs/d8/d8-F-comparison-guide.md` + `artifacts/d8/task_f.json` + `artifacts/d8/comparison/d8_f_dev4_20261005/` | 四题八首次、139项核对与AI初审；D2-002收益/D2-003范围失败，用户已确认AI总体判断；F指南保留当时范围 |
| 看 D8 G 当前汇总与下一步 | `docs/d8/d8-G-completion-guide.md` + `artifacts/d8/task_g.json` | 当前186离线回归/独立审计、真实费用与限制、D9来源/时限修复及D10–D11门槛 |
| 回看暂缓的 D7 | `docs/d7/d7-ABCDEFG-plan.md` | 原交付计划保留；环境预演、录屏、简历和投递未因跳过而完成 |
| 看 D6 B 冻结验收题 | `eval/acceptance.jsonl` + `eval/acceptance_rubric.json` + `artifacts/d6/acceptance_freeze_manifest.json` | 20 题已人审通过，D11 前不用于运行或优化 |
| 看 D6 当前任务 | `docs/d6/d6-ABCDEFG-plan.md` + `artifacts/d6/` | A–G 工程范围完成；验收问答及全量答案人审待补 |
| 看 D6 汇总与 D7 投递清单 | `docs/d6/d6-G-completion-guide.md` | 审核后的完成范围、38 条结论/语义范围、简短简历与正确论文录屏脚本；D7 预演/录屏待做 |
| 看 D6 C 检索对照 | `artifacts/d6/task_c.json` + `artifacts/d6/retrieval_comparison/d6_c_topk_live_20261004/` | 开发集 16 题；返回与展示分开，精确标注命中不等于答案准确率 |
| 使用 D9 两模式页面 | `app.py` + `docs/d9/d9-E-runtime-guide.md` + `artifacts/d9/e_page_validation.json` | 本机 Streamlit；固定 RAG/Agent、来源轨迹、五终态、会话纯下载与提交防重跑；D6 历史说明保留 |
| 看 D6 E 开发集扩充 | `docs/d6/d6-E-dev-expansion-guide.md` + `artifacts/d6/task_e_audit.md` | 当前审核、中文要点、首跑答案 AI 评价；原合并记录与候选材料保留 |
| 跑 D6 F 离线核对 | `docs/d6/d6-F-validation-guide.md` + `scripts/validate_d6.py` + `artifacts/d6/validation.md` | 680 项证据核对 + 25 项新回归；0 模型请求；原 67 项保留历史 |
| 看后续实现安排 | `docs/plan-codex.md` + `docs/d9/d9-G-completion-guide.md` | 本项目总计划与 D10–D11 交接；旧各阶段计划保留 |
| 看 D5 完成范围 / 继续 D6 | `docs/d5/d5-G-completion-guide.md` + `artifacts/d5/task_g.json` | G 已汇总，D5 评测/人审仍待补，页面复用接口与资源管理 |
| 看 D5 历史工程验收 | `archive/run_logs/d5/d5_validation_20261004_064249_754431.json` + `artifacts/d5/task_g.json` | 对应 D5 十题状态；D6 合并后旧核对会报告题集漂移，不能当作当前 20 题验收 |
| 学习 D5 任务 F / 看初跑汇总 | `docs/d5/d5-F-evaluation-guide.md` + `artifacts/d5/task_f.md` | 十题首次真实运行、评分口径和未完成范围 |
| 看 F 原始结果 / 机器 / AI 评价 | `artifacts/d5/qa_baseline/d5_f_dev10_20261004/` | 冻结配置、逐题输出、机器汇总、AI 逐条原文判断分别记录 |
| 回查 D5 六题候选及 D6 合并 | `artifacts/d5/eval_candidate_review.md` + `artifacts/d6/candidate_merge_record.json` | 原候选包保留；D6 A 已记录实际人审确认、合并与首次补跑 |
| 使用 D5 通用问答 / 学习 E | `docs/d5/d5-E-answering-guide.md` + `scripts/answer_question.py` | 单/多篇版本参数、完整记录、退出码与资源管理 |
| 看最近问答 / E 历史 / 边界 | `artifacts/d5/answer_result.json/.md`、`boundary_validation.json`、`semantic_case_review.json` + `archive/run_logs/d5/answer_*.json` | 最近答案随 F 更新；E 首题通过原历史记录回查 |
| 学习 D5 任务 A | `docs/d5/d5-A-contract-guide.md` | 接口、状态与 A 阶段首轮配置快照 |
| 学习 D5 任务 D | `docs/d5/d5-D-rag-guide.md` + `artifacts/d5/task_d.json` | 引用允许集合、真实来源/PDF回查与固定核心 |
| 看 D 的实际答案/原文/费用 | `artifacts/d5/rag_smoke.md`、`.json` + `citation_replay.json` | 新真实核心验收与C旧草稿离线回查分别记录 |
| 学习 D5 任务 C | `docs/d5/d5-C-generation-guide.md` + `artifacts/d5/task_c.json` | 实际展示上下文、提示词、结构化草稿与本次验证 |
| 看 C 的实际候选/消息/输出 | `artifacts/d5/context_preview.json`、`generation_smoke.json` | 三组旧候选离线回放、新检索与真实草稿各自记录 |
| 学习 D5 任务 B | `docs/d5/d5-B-llm-guide.md` + `artifacts/d5/task_b.json` | 完整聊天响应、预算、错误与实际验证 |
| 看 B 实际配置与最近检查 | `artifacts/d5/chat_runtime_config.json`、`llm_boundary_validation.json`、`llm_smoke.json` | B 的运行配置、34 项离线检查和真实连通记录 |
| 改业务代码 | `paper_assistant/` | 当前源码 |
| 执行解析、过滤、恢复或检查 | `scripts/` | 当前命令入口 |
| 看原论文与核对引用 | `data/papers/` + `eval/corpus.json` | 固定来源 |
| 做 D4 分块 | `data/filtered/` 中的 `segments` | 当前可用正文输入 |
| 看三篇的分块结果 | `data/chunks/<paper_id>/<parse_revision>/` | 共 1188 个 chunk 与不可变输入/代码快照 |
| 看分块报告与预览 | `artifacts/d4/chunking_report.json`、`chunk_preview.md` | 三篇总入口；各篇记录放在对应子目录 |
| 按 ID 回查原文 | `data/index/papers.sqlite3` + `scripts/query_chunk.py` | 当前 SQLite 事实库，1188 个 chunk |
| 学习任务 C | `docs/d4/d4-C-storage-guide.md` | 按实际源码解释表、约束、事务和回查 |
| 学习任务 D | `docs/d4/d4-D-index-guide.md` | 向量配置、缓存、UUID5、Qdrant 与导入状态 |
| 学习任务 E / 输入问题找证据 | `docs/d4/d4-E-retrieval-guide.md` + `scripts/search_evidence.py` | 问题向量、版本范围过滤和原文回查 |
| 看最近一次候选 / 三题真实检索观察 | `artifacts/d4/retrieval_result.md`、`retrieval_validation.json` | 当前结果；单次历史在 archive/run_logs/d4/ |
| 学习任务 F / 对照原 PDF | `docs/d4/d4-F-retrieval-review-guide.md` + `artifacts/d4/retrieval_review.md`、`.json` | 15 候选的判断、完整原文及本次用户确认 |
| 查看 B/F 人工确认范围 | `artifacts/d4/human_review.json` | 用户 2026-10-02 的确认，绑定具体样本、候选和原 PDF 来源 |
| 查看 G 验收 / 接入 D5 | `artifacts/d4/validation.json`、`.md` + `docs/d4/d4-G-completion-guide.md` | 正式数据验收、已知问题、0 API 检查命令与复用接口 |
| 查看 F 全页来源与 ReAct 诊断 | `artifacts/d4/retrieval_evidence/`、`retrieval_diagnostics/` | 13张完整原页/manifest、独立新实验排名，正式E历史不变 |
| 看向量导入与验证 | `artifacts/d4/import_report.json`、`index_validation.json` | 当前结果；首次实际用量在历史日志与缓存统计中 |
| 保存可检索向量 | `data/index/qdrant/` | 正式持久化库，1188 个点 |
| 复用已生成向量 | `data/index/embeddings/` + `profiles/` | 正式缓存和模型配置，不能当旧副本移走 |
| 看开发题、期望证据 | `eval/dev.jsonl` | 唯一正式开发题集：20 题；另有 20 题冻结验收集 |
| 看 ReAct 第 2 页完整可读文字 | `artifacts/d3/page_previews/arxiv_2210.03629v3_page_2.txt` | 当前展示稿 |
| 看恢复出的图文字或公式 | `artifacts/d3/figure_recovery/`、`formula_recovery/` | 当前恢复稿；人工 pending |
| 找旧候选、旧预览或以前的运行日志 | `archive/` | 历史材料，不是当前输入 |

## 2. 根目录保留什么

```text
paper-research-assistant/
├── paper_assistant/       当前业务源码
├── scripts/               当前命令及可复现检查入口
├── data/                  正式论文、原始解析、过滤后正文
├── eval/                  正式语料清单、20 题开发集、20 题冻结验收集及评分规则
├── artifacts/d3/          当前处理报告、恢复结果和可读预览
├── artifacts/d4/          当前分块/入库/检索/PDF复核报告，页图与诊断各在子目录
├── artifacts/d5/          A–E 实现、F 初跑/候选、G 验收与 D6 交接
├── docs/                  本目录说明
├── archive/               统一历史归档
├── .venv/                 当前项目的 Python 环境
├── .env                   本机配置
├── .env.example           配置模板
├── .gitignore
├── requirements.txt       依赖版本
└── README.md              唯一总入口
```

`.venv`、`.env` 和业务代码还在使用。Python 自动生成的 `__pycache__` 是缓存，可忽略；它不是一份旧源码。此次未淘汰任何业务模块，也没有删除文件。

## 3. data：三层都有用途，parsed 不是淘汰版

| 目录 | 内容 | 为什么还要保留 |
|---|---|---|
| `data/papers/` | 三份固定版本 PDF | 原始来源、页码与 SHA 核对 |
| `data/parsed/` | 三份逐页原生解析 JSONL | 质量过滤输入、抽取问题诊断和原始证据回查 |
| `data/filtered/` | 三份质量过滤 JSONL | D4 的正文分块输入，1179 个保留片段 |

分块使用 `iter_indexable_segments()` 读取 filtered，只在单个保留片段内部切分。不要把页预览 TXT、候选 JSON 或恢复图文直接当成普通正文输入。当前 1179 个片段已生成 RAG 385、ReAct 480、Reflexion 323 个 chunk，共 1188 个，已存入 SQLite 并完成向量化。结果与版本清单保存在 `data/chunks/`；原始/过滤页和处理代码在版本目录中有快照，不能把这些快照当作重复文件归档移走。

`data/index/` 的 SQLite、`qdrant/`、`embeddings/`、`profiles/` 与 `current_profile.json` 都会在后续检索和重试时使用。原始向量缓存按批次嵌套保存，支持改变批次大小继续复用；删除缓存可能使完整性核对失败，或恢复时需要重新生成。当前模型配置为 qwen3.7-text-embedding、1024 维、cosine。

原 `data/download_checks/2210.03629v3.pdf` 与正式 ReAct PDF 字节相同，是验证下载副本，已归档到 `archive/data/download_checks/`。未来验证下载默认进入 `archive/run_outputs/download_checks/`。

## 4. eval：正式开发集与冻结验收集

- `corpus.json`：三篇论文的固定 ID、版本、来源、路径、哈希、页数和文本层信息。
- `dev.jsonl`：当前唯一正式开发集，20 条，均为 `human_verified`。候选文件为历史材料，不能替代正式题集。
- `acceptance.jsonl`：20 条人审并冻结的正式验收题；D11 前不运行或用于优化。
- `acceptance_rubric.json/.md`：验收评分规则，哈希与冻结声明绑定。
- `quality_rules.json`：当前过滤规则，程序仍读取。
- `d3-review.md`：新增四题的原文、中文要点与人工确认；原六题的历史复核说明在 `archive/eval/h-review.md`。

`new_cases.json`、`new_cases.ai_snapshot.json`、`*_candidates.json`、`d2_original.jsonl` 都是标注阶段的副本或候选，已经归档。正式题目、引文和人工状态未改变。

## 5. artifacts：当前结果与必要来源链

`artifacts/d3/` 根层保留解析报告、过滤报告、质量报告、继续执行说明和当前进度 JSON。

| 子目录 | 当前保留 | 用途 |
|---|---|---|
| `page_previews/` | ReAct 第 2 页可读 TXT、刷新报告 | 给人阅读，旧的原生 TXT 已归档 |
| `figure_recovery/` | 恢复 JSON/Markdown、AI 核对记录、原页 PNG | 当前八个图框的恢复结果与原图对照 |
| `formula_recovery/` | 六项恢复 JSON/Markdown/LaTeX、方法说明、AI 记录、验证报告、`evidence/` | 当前数学恢复结果与原图区域 |
| `formula_recovery/source_research/` | 官方源码压缩包、`source_text/methods.tex`、下载记录、最终独立核对记录 | 其中压缩包和 methods.tex 是复跑公式恢复的真实输入，不能当旧文件搬走 |
| `dev_expansion/` | `validation.json`、`human_review.json` | 十题来源一致性与新四题的人工确认记录 |
| `arxiv/` | 请求限速状态、缓存、验证汇总 | 搜索/下载共用的运行状态及当前能力证明 |
| `quality_evidence/` | 使用者提供的 ReAct Figure 1 截图 | 质量反馈的原始依据 |

恢复稿尚未自动入正文索引。图文和公式人工状态仍为 pending；题集十题的人工通过不能代替恢复稿的人工复核。

`artifacts/d4/retrieval_review.md/.json` 是 F 的当前入口，保留全部十五个 E 原候选及判断；用户于 2026-10-02 明确确认，范围记录在 `human_review.json`。`retrieval_evidence/` 保存十三张全页图和来源/渲染哈希清单；`retrieval_diagnostics/` 保存一次额外问题向量请求测得的 480 条 ReAct 排名。独立新实验摘要 rank 9，不应覆写为 E 的历史排名，也不改变正式 top-5 依据观察为 2/3。一次性诊断脚本和 AI 详细日志在 `archive/run_logs/d4/`；诊断脚本已有报告时拒绝重复付费运行。G 可复用业务验收入口是 `scripts/validate_d4.py`，总报告为 `artifacts/d4/validation.json/.md`，操作说明在 `docs/d4/d4-G-completion-guide.md`。

## 6. archive：统一放历史材料

归档保留原来的相对目录，方便从旧路径找到新位置：例如原 `artifacts/d3/formula_recovery/rag_candidates.json` 现在位于 `archive/artifacts/d3/formula_recovery/rag_candidates.json`。

| 归档位置 | 内容 |
|---|---|
| `archive/artifacts/d2/` | D2 连通测试、结构检查及首批标注过程 |
| `archive/artifacts/d3/dev_expansion/` | 题目候选、快照、旧六题副本和标注过程图片 |
| `archive/artifacts/d3/formula_recovery/` | 数学候选、诊断、重复页图、旧 bbox 试验和未使用的作者工程文件 |
| `archive/artifacts/d3/page_previews/` | 原生旧预览、ReAct 乱码备份和刷新前记录 |
| `archive/artifacts/d3/arxiv/` | 过去的单次请求和离线检查日志 |
| `archive/artifacts/d3/figure_recovery/` | 过去的检查记录和补充放大图 |
| `archive/eval/` | 原六题的历史复核说明 |
| `archive/data/` | 重复的测试下载 PDF |
| `archive/run_logs/` | 以后生成的连通测试、arXiv 请求和恢复检查日志 |
| `archive/run_outputs/` | 以后生成的测试下载文件 |
| `archive/relocation_snapshot/` | 此次改路径前的 README 与公式来源链快照 |

“归档”包括已被取代的草稿和仍可用于审计的历史记录，并不表示里面每个文件内容都有错误。归档文件不再充当当前正文或题集入口；公式的视觉来源记录仍可通过正式结果中的归档路径回查。

每个迁移文件的旧路径、新路径、原因、字节数和 SHA 见 `archive/manifest.json`。历史记录内部的旧路径保留为当时的执行信息，可用清单映射到现位置；当前导航链接已更新。

## 7. 常用命令与输出位置

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.parse_pdfs
.\.venv\Scripts\python.exe -X utf8 -m scripts.filter_pdf_text
.\.venv\Scripts\python.exe -X utf8 -m scripts.recover_figure_text
.\.venv\Scripts\python.exe -X utf8 -m scripts.recover_formulas
# G 整体离线验收；不读.env、不调用模型
.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_d4
```

解析/过滤更新 data 和当前报告；图文恢复更新当前可读预览，乱码备份留在 archive；公式恢复读取保留的官方源码，输出六项正式恢复稿。`scripts/` 的检查入口仍可运行，新日志会放在 archive/run_logs。

真实模型连通测试脚本仍会调用服务；目录整理与 D4 B/C 没有请求模型。D4 D 向量生成含试运行共 120 次请求、84046 tokens；ready 版本重复构建零请求。D4 E 三题实际问题检索共 3 次向量请求、103 tokens、LLM 0；20 项离线检查通过。F 独立诊断额外 1 次问题向量请求、35 tokens，原文/索引不变；B/F 已获用户 2026-10-02 明确确认。G 本轮当前源码 59 项重跑与新增人审继承 22 项通过，正式新进程九项数据验收通过，本次无模型请求；D4 完成并保留已知问题。分块/存储/索引/检索历史及离线边界记录统一在 `archive/run_logs/d4/`，当前结果和汇总在 `artifacts/d4/`。E 问题向量不另外缓存，重新查询会产生一次问题向量请求。
