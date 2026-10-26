# 论文研究助手

当前架构、进展与遗留问题见 [v3 总规划](docs/v3/plan.md)，下一批十题完整 Agent 测试安排见 [D1](docs/v3/d1-plan.md)。下方旧阶段说明按各自日期保留。

仓库提交源码、文档、评测样本与必要的运行配置；密钥放在本机 `.env`，不提交。虚拟环境、模型权重、原 PDF、本地索引、解析资产及原始运行日志保留在本机，需按实际环境准备。历史文档中的本机绝对路径及运行产物链接用于本地回查。

当前 PDF 解析默认（2026-10-22）：MinerU 4.0.12 Standard，使用独立环境 `.venv-mineru` 的 Torch＋LMDeploy CUDA 后端。页面上传与默认入库统一使用 `mineru-standard`，关闭额外图片／图表语义分析，保留原图资产、图注和结构来源。已保存的 Advanced 版本与实验结果保留原记录；新档位按现有解析方案生成独立版本。

文档整理（2026-10-16）：原阶段文档已归入 [docs/v1](/D:/course/paper-research-assistant/docs/v1)，当前问题与后续安排见 [docs/v2/plan.md](/D:/course/paper-research-assistant/docs/v2/plan.md)。

统一聊天入口与问题规划更新（2026-10-12）：[A–C 计划](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/d13-query-plan-ABC-plan.md) 的 A–C 已全部完成。页面选择论文后直接提问，不显示方式选择或标签；首问与追问在检索前用一次准备调用完成理解、澄清和子查询规划。简单问题执行一条实际计划查询，按需最多补查一次；复杂问题逐条检索、合并完整原文，再一次综合回答完整问题。页面及 JSON／Markdown 区分计划检索与补查，保留实际用量和失败缺口。分别见 [A 日志](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/A-unified-chat-guide.md)、[B 日志](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/B-question-planning-guide.md)、[C 日志](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/C-planned-retrieval-guide.md)。A 的两个页面方法、B 的三个后端方法与 C 的三个既有方法最终通过，模拟浏览器的布局、两篇论文引用和失败资料开合通过，真实模型／embedding／重排请求均为 0；未新测准确率，未运行 D14。

当前进度（2026-10-12）：**D13 后独立重排、连续对话、新论文入库及统一入口与问题规划 A–C 均已完成实现；下一步 D14。** 页面可上传文本型 PDF，后台局部显示入库阶段／批次进度，失败可重试；成功后选择新论文，直接提问、连续追问和回查原文。入库完成保留原论文选择与当前对话，等待时仍可查看历史和引用。入库实现与当时验证见 [C 上传日志](/D:/course/paper-research-assistant/docs/v1/d13-import/C-upload-guide.md)和 [入库 A–C 计划](/D:/course/paper-research-assistant/docs/v1/d13-import/d13-import-ABC-plan.md)。未新测准确率；原 20 题双模式单轮首次验收仍留 D14，后续 D15 必要局部修复 → D16 启动／录屏／可行部署 → D17 简历与求职，见 [总规划](/D:/course/paper-research-assistant/docs/v1/plan-codex.md)。

当前校验已于 2026-10-07 精简：保留论文/PDF/正文身份、embedding 与索引/缓存匹配、引用原文和摘要范围、输入/输出结构、调用预算与防重复提交。问答和对照实验不再扫描全仓库、不再校验源码/截图/历史审计文件哈希；摘要范围加载一次，发布时只检查真正引用的来源。D4–D6 汇总字节审计及 D9 F 审计脚本已删除，旧文档与报告仅作为历史记录。精简前 prepared 批次保留，执行时需新建批次；不覆盖旧结果。

按改动范围验证：文档/注释修改不跑测试；普通小改动只选 1–3 个相关现有测试方法，失败或有具体跨模块影响时才扩大范围，不默认跑全量回归。测试使用临时资源与模拟响应，不生成审计报告。具体规则见 [AGENTS.md](AGENTS.md)。

D10 交接时记录（2026-10-07，历史）：**A–G 已完成记录范围，状态 `completed_with_known_issues`；下一阶段 D11。** 同一完整开发批次 `d10_d_dev20_20261007_195707` 的 20 题、40 模式、89 条 claim 已保存并完成 AI 评价；严格完整有据的可答题为固定 RAG **13/17**、Agent **15/17**，负题合理拒答各 **3/3**。D2-002 Agent 补查后机制完整有据；D3-004 两模式章节/实验归属未独立证实，D6-003 两模式生成者措辞歧义保留，新答案人审 **pending**。这些是开发集 AI 观察，不是验收或人工准确率。G 仅汇总交接，结果、提示和配置不变，没有新增源码行为、测试、哈希或模型请求。见 [G 独立日志与学习答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-G-completion-guide.md)、[开发总结第 7 节 G 交接](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md:414)及 [D10 A–G 计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。D11 专用验收入口尚待实现，验收尚未运行，验收题面未用于调优；D7 暂缓。

D10 E/F 执行时记录（2026-10-07，历史，保留当时状态）：**当时 A–F 已完成，G 待执行，下一步 G 汇总交接。** E 已评价同批次 20 题、40 模式保存输出；AI 严格完整有据的可答题为固定 RAG **13/17**、Agent **15/17**，负题合理拒答各 **3/3**，新答案人审仍为 **pending**。D2-002 Agent 补查后两种文档使用机制完整有据；D3-004 两模式章节/实验归属未被实际引用独立证实，D6-003 两模式生成者措辞有歧义，均作为已知问题保留。F 直接冻结 D 的同一批次 `d10_d_dev20_20261007_195707` 与实际提示版本，未再改提示或增加测试、哈希、模型请求。见 [完整开发评价与冻结说明](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md)、独立 [E 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-E-semantic-review-guide.md)、[F 日志、学习路线与答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-F-freeze-guide.md)及 [D10 A–G 计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。当时 G 尚未执行；D11 专用验收入口及首次验收运行仍待实施，验收题面未用于本轮调优。

D10 C/D 执行时记录（2026-10-07，历史）：**当时 A–D 已完成，E–G 待执行，下一步 E 评价新输出。** C 复用 A/B 已通过的 AST 语法结果，没有新增测试或哈希核对；D 已完成新批次 `d10_d_dev20_20261007_195707` 的 20 题、40 模式输出，导出成功、CLI 退出 0。机器状态为固定 RAG 15 `answered` / 5 不足、Agent 17 `answered` / 3 不足；Agent 补查 3 次（D2-002、D2-003、D5-005）。实际 embedding 23 次 / 922 tokens，聊天 SDK/HTTP 42/42 次 / 已知 106692 tokens，原总量保留 `null`，网络重试与修复均 0。D2-002 本次确实补查并输出了两机制，结论支持与完整性留 E；这些机器结果不代表准确率，语义评价与新答案人审尚未完成。阶段日志分别见 [C：验证选择与学习答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-C-verification-guide.md)、[D：开发执行与学习答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-D-development-run-guide.md)，当前安排见 [D10 A–G 计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。

D10 A/B 执行时记录（2026-10-07，历史）：**A/B 已完成，C–G 待执行。** A 已定位 D2-002 缺机制证据却直接回答的问题；B 只调整现有 Agent 系统提示，要求比较、机制及多部分问题覆盖所问内容：缺证据且选定论文内可补查、允许 `retry_search` 时补查，证据足够时直接回答，补查或修复终态仍不足时拒答。提示版本为 `d10-question-complete-agent-v1` / `d10-source-scoped-agent-v1`，固定 RAG 与检索预算不改。本轮仅检查修改文件语法，未运行测试、模型或真实问答，未做哈希审计；语义效果留 D/E。下一步 C 按实际改动判断必要验证，D 新建并执行完整 20 题双模式开发批次，E 逐题评价。见 [D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。

D10 A/B 学习入口：[工作日志、学习路线与八道题参考答案](/D:/course/paper-research-assistant/docs/v1/d10/d10-AB-log-and-study-guide.md)。按 D2-002 旧失败 → 系统提示 → 消息构造 → 动作权限 → 补查执行走读，约 45 分钟；阅读保存材料即可。

D10 规划时记录（2026-10-07，历史）：已制定 [D10 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d10/d10-ABCDEFG-plan.md)。先处理 D2-002 缺机制证据却直接回答的问题，再用当前精简入口新建 20 题双模式开发对照、逐题评价并固定最终版本。当时各任务尚待执行；该轮只改规划与导航，未改业务、跑测试或调用模型。

D9 交接时进度（2026-10-07，历史）：**D9 A–G 已完成记录中的任务范围，状态 completed_with_known_issues。** 三篇摘要范围/双模式来源硬检查、embedding 剩余时限、D9 CLI/页面及故障回归已完成；F 旧六题 AI 补评、新四题八模式首次与待人审材料、完整 20 题零请求准备已保存。新 D2-003 Agent 根据核定摘要完整回答；D2-002 事实有据但机制解释不完整，AI 可答完成观察固定 1/3、Agent 2/3，不是人审准确率。F 实际 embedding 5 次/191 tokens、聊天 8 次/已知 16781 tokens；G 当时新增请求 0；旧结果和数据保留，当前源码及运行配置已按上方说明精简。见 [G 完成与 D10 交接](/D:/course/paper-research-assistant/docs/v1/d9/d9-G-completion-guide.md)、[G 记录](/D:/course/paper-research-assistant/artifacts/d9/task_g.json)、[新八模式人审包](/D:/course/paper-research-assistant/artifacts/d9/comparison/d9_f_dev4_20261006/human_review.md)。下一步 D10：定位 D2-002、完成 20 题双模式开发验证/评分并正式冻结；原 prepared 改绑定后须重建。新旧答案人审 pending、严格 120 秒进程强杀未证明；验收 D11、D7 暂缓，用户四问继续控制扩展。

D8阶段记录（2026-10-05，历史）：**D8 A–G已按记录中的工程范围完成，保留已知问题。** 固定RAG之外已有最多一次受控补检索的Agent CLI、完整导出及共享首轮/独立预算的成对开发入口；现有Streamlit页面仍固定RAG。四题八模式首次、AI初审和用户总体确认保留；D2-002补查支持、D2-003摘要来源失败。完整开发对照、Agent页面及冻结验收待后续，D7继续暂缓。当前汇总/命令/学习自检见 [D8 G指南](/D:/course/paper-research-assistant/docs/v1/d8/d8-G-completion-guide.md)，实际完成证据见 [G记录](/D:/course/paper-research-assistant/artifacts/d8/task_g.json)。

D9 规划时记录（2026-10-05，历史）：已制定 [D9 A–G 执行计划](/D:/course/paper-research-assistant/docs/v1/d9/d9-ABCDEFG-plan.md)，**各任务均待执行**。优先将摘要来源要求落到可信范围表和两模式硬校验，接 embedding 剩余时限并验证故障；随后适配新阶段入口/Agent 页面、补旧六题 AI 评价、新四题回归和完整20题零请求准备。全量20题真实对照安排 D10，冻结验收仍留 D11；本次只规划，未修改业务或调用模型。

D6交接时记录（历史）：独立 Python 项目，使用本目录的 `.venv`。D4 已完成三篇论文共 1188 个 chunk 的原文/向量入库、版本检索与来源复核，保留摘要漏召回问题。D5 固定 RAG 与引用回查已实现，首次十题记录保留。**D6 A–G 已按记录中的工程范围完成：开发集补至 20 题（全部 human_verified），20 条验收题人审并冻结（D11 前不运行），检索对照完成（top-5/10/20 命中 9/13→11/13→13/13），最小 Streamlit 页面可用并验证，修正后的 F 680 项离线核对通过。** 全量答案语义人审仍待补；三个首次批次共 38 条结论，仅三题整题抽审，不代表逐条评分。G 的当前交接与简历草稿见 [审核后指南](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)。本次 E 审核见[补充记录](/D:/course/paper-research-assistant/artifacts/d6/task_e_audit.md)：四题来源与机器统计核对通过，已说明训练数据措辞歧义、单例范围及共享背景证据。

## 先看哪些文件

D6 完成与交接（2026-10-04）：开发集 20 题（10 fact / 4 method / 3 retrieval_paraphrase / 3 unanswerable），由三个批次覆盖（D5 十题、D6 六题、D6-E 四题）；验收集 20 题已冻结。C 在 E 扩充前 16 题（13 道可答）上的检索对照：返回候选 top-5/10/20 命中 9/13、11/13、13/13，展示 9/13、11/13、12/13；top-20 有 8/13 触发预算停止、仅 D2-004 丢依据；不代表答案准确率。F 强化核对覆盖 680 项，新增 25 项篡改回归；原 67 项记录保留历史。详见 [F 审核说明](/D:/course/paper-research-assistant/docs/v1/d6/d6-F-validation-guide.md)。汇总、风险与 D7 投递材料清单见 [D6 完成与交接指南](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)；页面操作见 [D 使用说明](/D:/course/paper-research-assistant/docs/v1/d6/d6-D-web-guide.md)。

D5 G 当时交接记录（2026-10-04）：新进程离线核对通过，新增模型请求 0 次；旧 A–F、正式十题和首次失败均保留。见 [G 完成与 D6 交接指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md)、[D5 当时通过的验收历史](/D:/course/paper-research-assistant/archive/run_logs/d5/d5_validation_20261004_064249_754431.json) 和 [G 阶段记录](/D:/course/paper-research-assistant/artifacts/d5/task_g.json)。六题与新答案人审待补，`full_d5_acceptance_completed=false`，不宣称正式十六题已完成。

D5 F 当时进度记录（2026-10-04）：正式十题已首次真实运行，7 题 answered、3 题 insufficient_evidence，其中 2 道可回答题因本轮缺证据而拒答。最终引用定位合法 21/21；这是定位检查，答案支持度另看逐题评价。新增 embedding 10 次/379 tokens、聊天 10 次/22612 tokens，无重试/修复。见 [F 操作说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-F-evaluation-guide.md)、[F 进度与结果](/D:/course/paper-research-assistant/artifacts/d5/task_f.md)、[AI 逐题评价](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/ai_semantic_review.md) 与 [六题候选复核包](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_review.md)。用户明确“暂未复核，先保留候选”，正式开发集仍为十题；新答案人工支持率 N/A。

E 阶段记录（2026-10-03）：37 项离线组合检查通过，通用 CLI 首题 answered；embedding 1 次/34 tokens、聊天 1 次/2758 tokens，无重试/修复。见 [E 操作说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)、[E 完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_e.json) 和 [E 不可覆盖首题历史](/D:/course/paper-research-assistant/archive/run_logs/d5/answer_20261003_120147_728995_8ce78831d965.json)。[最近答案](/D:/course/paper-research-assistant/artifacts/d5/answer_result.md) 随后续运行更新。

D5 A、B、C、D 已完成：固定一轮检索、生成和引用回查已串通。D 的 57 项离线检查通过；新真实首题 answered，5 次引用/2 来源，新增 embedding 1 次/34 tokens、聊天 1 次/2758 tokens；语义支持尚未评分。B/C 的旧检查与费用分别保留。见 [D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)、[任务 B 说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-B-llm-guide.md) 和 [B 完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_b.json)。当前 D 的操作与范围见 [任务 D 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-D-rag-guide.md)、[完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_d.json) 与 [真实答案和原文](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke.md)。C 的操作与范围见 [任务 C 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-C-generation-guide.md) 和 [C 完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_c.json)。`docs` 文件名现已标明实施日及任务字母；[重命名清单](/D:/course/paper-research-assistant/artifacts/d5/docs_rename_manifest.json) 保存九个旧名称与新入口、原始快照。

[目录使用说明](/D:/course/paper-research-assistant/docs/v1/00-directory-guide.md) 逐项解释当前输入、正式结果和历史归档。[归档清单](/D:/course/paper-research-assistant/archive/manifest.json) 保存此次 94 个文件的旧路径、新路径和内容哈希。

| 目录 | 用途 |
|---|---|
| `paper_assistant/` | 当前业务源码 |
| `scripts/` | 当前命令行入口与可复现检查 |
| `data/papers/` | 三份固定版本原 PDF |
| `data/parsed/` | 原生逐页解析，仍是过滤和诊断输入 |
| `data/filtered/` | 后续 D4 使用的保留正文片段 |
| `data/chunks/` | 三篇的不可变分块、输入及处理代码快照，共 1188 个 chunk |
| `data/index/papers.sqlite3` | SQLite 论文、处理版本与原文事实库 |
| `data/index/qdrant/` | 已持久化的 1188 个正文向量 |
| `data/index/embeddings/`、`profiles/` | 成功向量响应缓存及不可混用的模型配置 |
| `eval/` | 正式语料清单、20 题开发集、20 题冻结验收集及评分规则 |
| `artifacts/d3/` | 当前报告、图文/数学恢复结果和可读预览 |
| `artifacts/d4/` | 当前分块/入库/检索、B/F 人审和 G 验收报告；F 全页对照在 retrieval_evidence/，独立诊断在 retrieval_diagnostics/ |
| `artifacts/d5/` | A–E 完成记录、F 十题初跑/候选、G 验收与交接、问答结果和边界检查 |
| `artifacts/d8/` | 受控Agent、成对开发实验、实际/逻辑账本、用户确认、G当前回归与交接 |
| `artifacts/d9/` | A–G 完成记录、来源表/人审、运行配置、边界/入口/页面证据、新四题首次及完整 20 题 prepared；保留已知问题 |
| `artifacts/d10/` | `dev_comparison.md` 集中保存完整 20 题双模式 AI 评价、已知问题、F 同版本冻结与第 7 节 G 交接；新答案人审 pending |
| `docs/d4/`、`docs/d5/`、`docs/d6/`、`docs/d8/`、`docs/d9/`、`docs/d10/`、`docs/d11/`、`docs/d12/`、`docs/d13/` | 按实施阶段分组的计划与日志；既有历史保留，D11–D13 A/B/C 独立记录，目录入口和总规划留在 docs 顶层 |
| `archive/` | 已被取代的候选、旧预览、测试副本和历史运行记录 |

当前正式开发集为 `eval/dev.jsonl`，共 20 题；六题与四题两次扩充均经用户实际复核后合并，新题材料保留为历史。正式验收集为 `eval/acceptance.jsonl`，共 20 题，题目及标准证据保留，按新顺序 D14 前不运行或用于优化。D12 改变回答规则后，D14 区分有用回答与论文原文支持；归档题目副本不作为当前题集。

## 已完成的内容

- D8受控Agent：严格三动作、最多一次补查、最终最多8条完整证据/8000字符、共享聊天预算和最终引用定位回查；独立CLI/不可覆盖历史/两模式成对runner已验证。当前G186方法回归通过，E119按当前SHA继承且存在14方法重叠；四题真实用量embedding5/201tokens、聊天9/22188tokens。用户确认AI总体结论，独立逐结论/引用评分未提供；摘要章节硬校验、严格120秒硬中止及全量准确率未完成。
- 三份固定 PDF：RAG `arxiv_2005.11401v4`（19 页）、ReAct `arxiv_2210.03629v3`（33 页）、Reflexion `arxiv_2303.11366v4`（19 页），共 71 页。
- 逐页解析与质量过滤：1179 个保留片段、412 条排除行；过滤降低已知抽取问题的影响，不代表全文准确性已经验收。
- ReAct 文件页 2 Figure 1：八个图框独立恢复，3110 次文字字形在核对的英语库存内匹配，AI 对照完成、人工 pending。
- 六项数学内容：RAG 五组表达式来自同版本作者 LaTeX 源码；Reflexion 一个行内变量来自原 PDF 转写，AI 对照完成、人工 pending。
- arXiv 搜索、固定版本下载、缓存、限速与失败回退已有真实和离线验证记录。
- 正式开发题 20 条，题目标注全部 `human_verified`：三个批次的首次问答分别保留；D6 A 的三题整题抽审已记录，生成答案的**全量**语义人审仍待补，抽审不代表全量。正式验收题 20 条已实际人审并冻结；F 列出的 35 份本地运行记录中未发现验收执行证据，问答验收留 D11。

- D4 任务 B 三篇：RAG 385、ReAct 480、Reflexion 323 个 chunk，共 71 页、1179 个父片段、1188 个 chunk；完整原文切片、来源、哈希及覆盖范围检查通过，重复执行复用版本。用户于 2026-10-02 确认每篇十条抽样，共三十条；这不表示逐条人工检查全部 1188 个 chunk。
- D4 任务 C：SQLite 已保存 3 篇、3 个处理版本、1188 个 chunk；重复导入新增 0，新进程按 ID 读回全部字段一致。14 项存储边界检查通过，39 个输入/快照未改。
- D4 任务 D：沿用 `qwen3.7-text-embedding`、1024 维、cosine；RAG 385、ReAct 480、Reflexion 323 个点均为 ready。含十条试运行共 120 次真实请求，实际用量 84046 tokens；重复运行 0 次请求、点数不增长。新进程完整读回、25 项离线边界检查、原始输入与 SQLite 原文事实不变均通过。
- D4 任务 E：问题向量、完整论文/处理版本过滤、ready 门槛、top-5 与 SQLite 原文/页码/哈希回查已接通。20 项离线检查通过；三篇各一题实际返回五条候选，共 3 次问题 API、103 tokens、LLM 0 次。RAG/Reflexion 标注引文在 rank 1，ReAct 未召回预期摘要第 1 页，F 已诊断并保留该问题；原文、导入状态、向量文件和 39 个输入/快照未改。
- D4 任务 F：三题十五候选、十三个完整 PDF 页的 AI 对照完成，用户于 2026-10-02 确认。RAG rank 1/2、Reflexion rank 1 是完整依据；ReAct 正式 top-5 缺少摘要来源证据，独立新实验中摘要排第 9。严格事实与来源条件观察为 2/3；人工确认不改变失败基线。
- D4 任务 G：已记录 B/F 人工确认，当前源码 SQLite 14 项、索引 25 项、检索 20 项共 59 项重跑通过，新增人审继承 22 项通过；分块器此前 12 项另有记录。正式新进程九项验收通过，1188 条正文/向量/缓存方向一致，39 个输入/快照、SQLite 四表及 Qdrant 两个数据文件保持一致。本次无模型请求，状态 `completed_with_known_issues`，D4 完成并保留 ReAct 摘要漏召回。

当前通用问答 CLI 已能输入问题、检索原文、生成并回查引用、导出完整记录；20 题验收集已冻结，最小页面已实现并验证，问答质量验收仍待完成。三题检索观察不等于问答准确率，D4 B/F 人工确认见单独记录。独立 LaTeX 排版稿因内置编译器环境异常，尚未验证编译成功。

## 常看的结果

- [当前进度与操作说明](/D:/course/paper-research-assistant/artifacts/d3/continuation_guide.md)
- [PDF 质量报告](/D:/course/paper-research-assistant/artifacts/d3/pdf_quality_review.md)
- [ReAct 第 2 页可读预览](/D:/course/paper-research-assistant/artifacts/d3/page_previews/arxiv_2210.03629v3_page_2.txt)
- [图框恢复稿](/D:/course/paper-research-assistant/artifacts/d3/figure_recovery/arxiv_2210.03629v3.page_2.md)
- [六项数学恢复稿](/D:/course/paper-research-assistant/artifacts/d3/formula_recovery/recovered_formulas.md) 与 [恢复方法](/D:/course/paper-research-assistant/artifacts/d3/formula_recovery/recovery_guide.md)
- [新四题复核说明](/D:/course/paper-research-assistant/eval/d3-review.md)；原六题历史记录在 [归档复核说明](/D:/course/paper-research-assistant/archive/eval/h-review.md)
- [三篇分块预览目录](/D:/course/paper-research-assistant/artifacts/d4/chunk_preview.md)、[分块汇总](/D:/course/paper-research-assistant/artifacts/d4/chunking_report.json)、[分块检查](/D:/course/paper-research-assistant/artifacts/d4/chunk_validation.json)
- [任务 C 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-C-storage-guide.md)、[SQLite 入库报告](/D:/course/paper-research-assistant/artifacts/d4/storage_report.json)、[SQLite 验收](/D:/course/paper-research-assistant/artifacts/d4/storage_validation.json)
- [任务 D 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-D-index-guide.md)、[当前向量导入报告](/D:/course/paper-research-assistant/artifacts/d4/import_report.json)、[正式索引验证](/D:/course/paper-research-assistant/artifacts/d4/index_validation.json)
- [任务 E 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-E-retrieval-guide.md)、[最近一次候选预览](/D:/course/paper-research-assistant/artifacts/d4/retrieval_result.md)、[真实查询与问题记录](/D:/course/paper-research-assistant/artifacts/d4/retrieval_validation.json)
- [任务 F 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-F-retrieval-review-guide.md)、[15 个候选与 PDF 对照](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)、[ReAct 独立排名诊断](/D:/course/paper-research-assistant/artifacts/d4/retrieval_diagnostics/react_abstract_recall.json)
- [任务 G 与 D5 交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)、[B/F 人工确认](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)、[D4 正式验收](/D:/course/paper-research-assistant/artifacts/d4/validation.md)

## 环境和配置

Python 3.11.5，依赖版本见 `requirements.txt`。`.env.example` 是配置模板，`.env` 是本机设置；聊天模型使用 `LLM_*`，独立向量模型使用 `EMBEDDING_*`。配置读取/校验在 `paper_assistant/config.py`，不会自行发起请求。

本机已配置 `RERANK_MODEL=qwen3-rerank`、`RERANK_BASE_URL=https://ws-dpnyjvvx2lsryczn.cn-beijing.maas.aliyuncs.com/compatible-api/v1`，单次超时 30 秒；`RERANK_API_KEY` 留空复用 `EMBEDDING_API_KEY`，密钥不写入文档。设置模型、地址两项启用重排，移除两项沿用 RRF；修改后重启页面。具体配置、调用次数和阅读方式见 [重排使用日志](D:/course/paper-research-assistant/docs/v1/d13-rerank/C-usage-guide.md)。

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import paper_assistant; print('项目包导入成功')"
```

### 当前环境启动页面

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -m streamlit run .\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

打开 http://127.0.0.1:8501，在左侧选择 1–3 篇论文，在底部输入问题并发送。首问与追问都会先理解和规划，需要明确对象时先请你补充说明。用户消息立即显示，助手位置显示加载提示，后台完成后显示回答；等待时仍可查看旧引用和切换对话。同一组论文可继续追问；“新对话”返回空白聊天区，侧栏“历史对话”可切回旧记录。**正文按段落显示，点击段末引用编号可弹出对应原文和 PDF 文件页序**；相同来源在本轮复用编号，来源 ID 收在“来源定位”中。每轮的问题详情、轨迹、用量及 JSON/Markdown 下载在“回答详情与下载”里。当前页面沿用 D9 来源规则，回答组织与页面操作见 [段落与引用日志](/D:/course/paper-research-assistant/docs/v1/answer-paragraphs-guide.md)，交互问答策略见 [问答兜底日志](/D:/course/paper-research-assistant/docs/v1/answer-fallback-guide.md)。发送问题会使用 embedding 和聊天额度；查看引用、下载及重绘不再次提交。不要让页面问答与 CLI 同时使用同一个本地 Qdrant 目录。

新论文入库 A–C 已完成：侧栏展开“添加论文”，上传文本型 PDF，可填写标题／来源链接，点击“开始入库”。页面局部显示实际阶段和批次计数，失败可点“重试入库”；成功后在“本次阅读的论文”中选择它即可问答。入库完成保留当前论文选择和对话，等待时仍可查看旧记录与引用。真实入库会使用 embedding 额度，纯扫描 PDF 暂不支持。本次实现验证仅使用模拟服务，详情见 [C 上传日志](D:/course/paper-research-assistant/docs/v1/d13-import/C-upload-guide.md)。

页面问答现使用 4096 输出 token，取消整轮三次聊天和 120 秒硬限制；单次请求超时、一次网络重试／修复仍保留。简单问题执行一条计划查询并保留按需一次补检索；复杂问题按计划逐条检索，共享混合检索和重排，每条返回 top-5，合并最多 8 条完整片段／8000 字符后一次综合回答。所有查询保留完整问题的来源要求和当前所选论文范围；明确回查的旧引用优先恢复，各子查询命中片段先于邻近正文纳入。部分查询失败时保留已取得的原文、实际用量和对应信息缺口。正常回答按问题逻辑组织连贯段落，截断后的修复重新生成完整短答；仍失败时给出简短提示，已找到的原文默认收起，具体错误留在详情。默认 CLI／冻结评测的调用策略保持。升级后需停止原 Streamlit 并按上面的命令重启，详情见 [计划检索日志](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/C-planned-retrieval-guide.md)、[问答兜底日志](D:/course/paper-research-assistant/docs/v1/answer-fallback-guide.md)和 [段落与引用日志](/D:/course/paper-research-assistant/docs/v1/answer-paragraphs-guide.md)。

### D7 新环境预演步骤（已写操作草案，尚未实际执行）

以下新 venv 复用当前项目的三篇固定数据。需要 Python 3.11、requirements.txt 和本机服务配置；仅安装依赖不能恢复已有语料。迁移时还需保持 data/papers、data/filtered、data/chunks、data/index/papers.sqlite3、data/index/qdrant、data/index/embeddings、data/index/profiles 与 eval 的相对结构和版本记录。本项目的 .env.example 只提供字段示例。

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
py -3.11 -m venv .venv-d7
.\.venv-d7\Scripts\python.exe -m pip install -r .\requirements.txt
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
# 在本机 .env 填好聊天和 embedding 配置后继续；不把密钥放进记录
.\.venv-d7\Scripts\python.exe -m pip check
.\.venv-d7\Scripts\python.exe -c "import paper_assistant; print('项目包导入成功')"
.\.venv-d7\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready
.\.venv-d7\Scripts\python.exe -m streamlit run .\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

预演应记录实际 Python/依赖版本、安装与启动失败及修复、三个 ready 版本是否存在。最后用开发题确认问答闭环会产生新的模型请求与运行历史，正式验收题按新顺序留 D14。当前 requirements 固定直接依赖版本，传递依赖未完整锁定；尚不能宣称已验证新环境复现。

## 常用命令

D9 当前两模式与成对开发参数见 [G 命令说明](/D:/course/paper-research-assistant/docs/v1/d9/d9-G-completion-guide.md#5-命令与实际入口)。`python -B -X utf8 -m scripts.answer_question_d9 --help` 与 `python -B -X utf8 -m scripts.run_agent_comparison --help` 只显示帮助。真实问答会消耗额度；成对 runner 默认 D8，当前策略须显式 `--stage d9`，默认仅准备四题。F 完整 20 题已独立 prepared，绑定未变才可执行；若改绑定，显式传全部 ID 并新建批次。`--execute-prepared`/`--live`/`--resume` 才执行，已有四题 manifest 不能续增 16 题；当前 runner 不接验收 split，验收入口按新顺序留 D14。D8 原入口与参数保留为 [历史命令](/D:/course/paper-research-assistant/docs/v1/d8/d8-G-completion-guide.md#5-可复用命令与记录位置)。

通用问答入口与参数/退出码见 [任务 E 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)。`python -X utf8 -m scripts.answer_question --help` 只显示帮助；实际问答会使用 embedding 与聊天额度。离线组合检查为 `python -X utf8 -m scripts.check_answering`。当前使用上述离线单元测试；旧交付哈希审计入口已移除。

```powershell
# 原 PDF -> 原生逐页文本
.\.venv\Scripts\python.exe -X utf8 -m scripts.parse_pdfs

# 原生页 -> 保留片段与排除记录
.\.venv\Scripts\python.exe -X utf8 -m scripts.filter_pdf_text

# 指定一篇的保留片段 -> 稳定版本 chunks；重复执行会核对并复用
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2005.11401v4
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2210.03629v3
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2303.11366v4

# 三篇已有版本 -> SQLite；重复导入核对并复用
.\.venv\Scripts\python.exe -X utf8 -m scripts.store_chunks

# 根据稳定 ID 回查原文及论文来源
.\.venv\Scripts\python.exe -X utf8 -m scripts.query_chunk --chunk-id arxiv_2005.11401v4_r_269ac0cb1263292d_p1_c9

# 已有ready版本：完整复核并复用；新/未完成版本：先十条验证再分批生成向量
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index

# 新进程离线读回核对；不请求模型
.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_index

# 离线查看当前可检索的论文/处理版本；不读密钥，不调用模型
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready

# 一次问题向量请求 + 本地BM25 -> RRF融合后的top-5原文、ID、页码与融合分数
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d --query 'What forms of parametric and non-parametric memory are combined in the RAG model?'

# 图框恢复 + 同步当前整页可读预览，乱码备份写入 archive
.\.venv\Scripts\python.exe -X utf8 -m scripts.recover_figure_text

# 从已有固定来源离线生成六项数学恢复稿
.\.venv\Scripts\python.exe -X utf8 -m scripts.recover_formulas

# 搜索候选元数据；不自动下载全文
.\.venv\Scripts\python.exe -X utf8 -m scripts.arxiv_search --query 'all:"retrieval augmented generation"' --max-results 3

# 下载一个明确版本；默认输出到 archive/run_outputs/download_checks
.\.venv\Scripts\python.exe -X utf8 -m scripts.arxiv_download --arxiv-id 2210.03629v3
```

论文清单的 `paper_id` 包含版本，`arxiv_version` 单写 `v4` 等；`local_path` 相对项目根目录。`pdf_page` 从 1 开始表示 PDF 文件页序。哈希、页数或来源变更后，需要重新解析和核对，不能沿用旧坐标规则。

`scripts/check_*.py` 仍是有效检查工具；历史检查产物已归档，新检查日志进入 `archive/run_logs/`。`smoke_llm` 和 `smoke_embedding` 会真实调用服务，整理目录时未运行它们。D2 历史模型连通记录可在 `archive/artifacts/d2/` 回查；D5 B 当前聊天验证见 [llm_smoke.json](/D:/course/paper-research-assistant/artifacts/d5/llm_smoke.json)，34 项离线结果见 [llm_boundary_validation.json](/D:/course/paper-research-assistant/artifacts/d5/llm_boundary_validation.json)。

## 下一步

D13 已完成，学习与独立日志分别见 [A：BM25](/D:/course/paper-research-assistant/docs/v1/d13/d13-A-bm25-guide.md)、[B：RRF 与入口](/D:/course/paper-research-assistant/docs/v1/d13/d13-B-rrf-integration-guide.md)、[C：使用与实际验证](/D:/course/paper-research-assistant/docs/v1/d13/d13-C-usage-validation-guide.md)。3 个相关现有离线方法通过（0.655 秒），没有真实模型/embedding API 请求或新增回答准确率。混合检索已接现有页面和 CLI，没有新增 UI 开关；原 `EvidenceSearcher` 保留作 dense 组件与历史检索诊断。D12 的回答依据与不足时仍解析保持，已有日志保留在 [执行计划](/D:/course/paper-research-assistant/docs/v1/d12/d12-ABC-plan.md)。

连续对话 [A–C](/D:/course/paper-research-assistant/docs/v1/d13-conversation/d13-conversation-ABC-plan.md)已完成，下一步 D14 接入验收入口，原 20 题以空历史执行固定 RAG/Agent 首次最终验收，分别看回答有用性和论文原文支持；本轮没有运行验收。D7 交付由 D16 承接。D10 的完整开发结果与交接保留在 [开发总结第 7 节](/D:/course/paper-research-assistant/artifacts/d10/dev_comparison.md:414)和 [G 独立日志](/D:/course/paper-research-assistant/docs/v1/d10/d10-G-completion-guide.md)，开发集 AI 结果不代表验收或人工准确率，新答案人审 pending，已知问题保留。

D6当时的下一步（历史，已由上段顺序更新）：**D7 交付**：录屏、环境重建预演、简历初稿与少量投递，清单见 [D6 完成与交接指南](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md) §4。再造方向：D8 实现一次受控补检索（Agent 核心故事）；上传本地论文排在 D8 之后。页面与 CLI 保持固定 top-5，验收题留到 D11，全量答案人审待补。D7 表示下一实施阶段，录屏、新环境重建预演和投递完成状态仅以实际记录为准。D6 A–G 的完整安排见 [D6 总计划](/D:/course/paper-research-assistant/docs/v1/d6/d6-ABCDEFG-plan.md)，两周总计划见 [plan-codex](/D:/course/hello-agents-study/log/plan-codex.md)。
