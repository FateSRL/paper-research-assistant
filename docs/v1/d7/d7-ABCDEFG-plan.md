# D7 执行计划：新环境预演、演示与投递准备

制定日期：2026-10-04（Asia/Shanghai）。状态：**已规划，A–G 尚未执行**。D7 表示下一实施阶段；原总计划 D7/10月3日的日期基准保留，执行日期按实际记录填写。

依据：[D6 G 审核后的交接](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)、[G 审核结果](/D:/course/paper-research-assistant/artifacts/d6/task_g_audit.md)、[F 当前核对](/D:/course/paper-research-assistant/artifacts/d6/validation.md)、[两周总计划](/D:/course/hello-agents-study/log/plan-codex.md)、[README 操作草案](/D:/course/paper-research-assistant/README.md)。

## 1. D7 的交付目标

把已有固定 RAG 做成“能在独立环境启动、能演示原文回查、能写进简历并讲清楚”的项目。今天的规划只新增 D7 文件；已有题集、问答首跑、D6 记录和文档绑定保留。

D7 结束时应留下：

1. 新六题的独立 AI 语义评价与明确的人审待办。
2. 一份使用固定数据副本的新 Python 环境预演记录。
3. 一份 3–5 分钟演示录屏，能看到正常回答、证据不足、原文页码和导出。
4. 精简简历条目、面试讲述和岗位/投递准备材料。
5. 如实区分完成与未完成的 D7 汇总，以及 D8 一次补检索交接。

Agent 自动补检索、重排、上传/搜索导入新模块仍放在后续；正式验收题留 D11。D7 不安排全量重跑 20 题、重新生成 1188 条向量或云部署。

## 2. 已有基础与待补缺口

| 项目 | 已有证据 | D7 如何使用 |
|---|---|---|
| 固定语料 | 3 篇、71 页、1188 个 chunk；SQLite、Qdrant 和原文来源已留证 | 使用相同数据副本，不从零建库 |
| 开发题集 | 20 题的题目/标注已人审；10/6/4 三个不同问题首跑批次 | 保留首次结果，演示选开发题 |
| 首跑输出 | 15 answered、5 insufficient_evidence，共 38 条结论；引用定位 43/43 | 这些是机器观察，不写总体答案准确率 |
| 语义评价 | AI 已审 14 题/29 条结论；人审仅三题整题抽审 | A 补新六题的 9 条结论及两条拒答理由；逐条人审仍单独记录 |
| 检索对照 | C 仅原 16 题/13 道可答；全部标注依据返回 top-5/10/20 为 9/13、11/13、13/13，展示 9/13、11/13、12/13 | 简历与面试保留样本和返回/展示区别，不在 D7 调参 |
| 页面 | 最小 Streamlit 页面、五终态、一次真实浏览器问答及下载验证 | B 预演启动，D 做新演示；原验证不等于已有录屏 |
| 文档与材料 | G 的架构图、录屏脚本、README 操作草案、简短项目条目 | 实际复现后再定稿，未来工作仍标预计 |
| 验收 | 20 题及规则人审冻结；F 列出的 35 份本地运行记录中未发现执行证据 | 只保护冻结内容，不拿验收题演示或优化 |

## 3. A–G 安排：7 小时 15 分钟＋45 分钟缓冲

| 任务 | 预计用时 | 要做什么 | 完成时留下什么 |
|---|---:|---|---|
| A | 1 小时 | 补齐新六题 AI 语义评价，整理人工复核材料 | 9 条结论及两条不足理由逐项对照来源；AI 和人审状态分开 |
| B | 2 小时 | 新环境重建与固定数据副本预演 | 新 venv、实际版本、pip check、三个 ready 版本、页面启动及失败记录 |
| C | 45 分钟 | 只修影响交付的明确阻塞 | 问题→最小修复→必要验证；无问题时记“无阻塞”，无需强行改代码 |
| D | 1 小时 | 完整演示、录屏与导出核对 | 实际可播放视频、两个开发题的新运行记录、导出文件和用量 |
| E | 45 分钟 | 精简项目条目并整合简历 | 可直接使用的简历文本；实际完成与预计 Agent 分列 |
| F | 1 小时 | 面试讲述、少量岗位筛选与投递准备 | 讲述稿、设计取舍/失败案例、岗位或投递台账；实际投递单列 |
| G | 45 分钟 | D7 汇总、材料定稿与 D8 交接 | 完成/待办清单、材料链接、真实费用和适用检查范围 |

主要顺序：**A→E→F；B→C→D；最后 G 汇总**。A 与 B 的材料准备可并行；E 可以先用已核对数字起草。D 的两道真实提交同时作为新环境闭环验证，不在 B 和 D 各重复跑一轮。

环境安装或启动超过 2 小时，先记录具体阻塞，使用缓冲处理；额外岗位筛选和口述可顺延。不要靠跳过实际启动或把历史结果当新演示来宣布完成。

## 4. A：补齐新六题的独立语义评价

材料：[六题首跑汇总](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d6_f_dev16_20261004/summary.json)、[六题结果目录](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d6_f_dev16_20261004/results)、[六题题目复核包](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_review.md)、[既有 AI 评价口径](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/ai_semantic_review.md)。

- 逐条检查 D5-001～D5-004 的 9 条实际结论，判断是否由它自己引用的本轮原文支持；复合结论及来源范围分别说明。
- 检查 D5-005、D5-006 两条不足理由，区分“题目确实不在论文中”和“本轮未检到”。
- 记录结论、citation IDs、chunk/文件页序、原文、AI 判断和理由，绑定原始结果 SHA。
- 保存 AI 初审，不新调用外部付费评判接口，不重生成答案。人工状态保持 pending，只有用户实际核对后才更新。
- 整理三批共 38 条结论及 5 条不足理由的复核入口，标明已有三题整题抽审；不把覆盖的 7 条结论记成逐条支持 7/7。

完成标准：六题有独立可回查评价；能说明支持、歧义或缺失，不预设六题全部正确。全量人审不作为 B–D 的强制前置。

预期输出：artifacts/d7/six_case_ai_semantic_review.json/.md、artifacts/d7/answer_human_review_packet.md、artifacts/d7/task_a.json/.md。以上是计划路径，尚未生成。

## 5. B：新环境和固定数据副本预演

依照 [README 的 D7 操作草案](/D:/course/paper-research-assistant/README.md)，优先验证 Python 3.11 与当前固定依赖。

- 建议创建 artifacts/d7/rehearsal/<run_id>/project/，按明确清单复制 app.py、业务源码、scripts、requirements、配置示例、必要文档与数据；不要递归复制整个 artifacts/archive 或正在创建的副本。
- 先确认所有访问原 Qdrant 目录的客户端已关闭（含页面问答和索引/检索 CLI）；副本使用真实文件复制，不用硬链接/目录联接，不回退读取原项目路径。Qdrant 业务读取仍可能维护锁文件，因此使用独立数据副本。
- 保留 data/papers、data/filtered、data/chunks、data/index/papers.sqlite3、data/index/current_profile.json、data/index/qdrant、data/index/embeddings、data/index/profiles、eval 的相对结构；复制前后记录内容 SHA。SQLite 连接只读。
- 在副本创建新的 venv，按 requirements 安装，记录 Python 和实际依赖版本、pip check 与导入结果。当前只固定直接依赖，传递依赖的实际列表也要保存。
- 用离线 list-ready 确认 3 个完整版本，再启动页面。副本可用独立端口，例如 8502，以实际可用端口为准。
- 配置只记录字段、来源和是否缺失，不把密钥写入日志或材料。B 不提交在线问题、不生成新文档向量。

完成标准：在副本的新环境中，从命令启动到看见三个可选 ready 版本有实际记录；数据与源码来源明确。它证明“依赖环境＋既有数据移植可运行”，不宣称任意机器或从零建库均已验证。在线闭环留给 D 的两次提交。

预期输出：docs/d7/d7-B-environment-guide.md、artifacts/d7/environment_rehearsal_<run_id>.json/.md、artifacts/d7/task_b.json/.md。

## 6. C：修复真实交付阻塞

根据 B 和录屏准备发现的问题，只处理安装/导入失败、启动命令、路径、资源关闭、导出或引用导航中的明确故障。服务额度、429 或超时要单列为服务问题，不改题目标签。

每项保存失败现场、定位原因、最小改动及对应验证。没有阻塞就记录“检查通过，无需修改”。不为完成 C 临时增加功能。

如果确需修改源码，先保存旧版本和 SHA；新版本用新记录验证受影响行为。旧 27/680/25 项记录仍对应其当时源码和输入，不能冒充新代码的验证。修改业务核心或依赖配置时另留明确版本和必要验证，不覆盖首次答案、旧检查或冻结声明。

预期输出：docs/d7/d7-C-blocker-guide.md、artifacts/d7/task_c.json/.md，以及确有改动才生成的定向检查记录。

## 7. D：两题演示、录屏与导出

沿用 [G 的录屏脚本](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)，在 B 的副本新环境演示：

1. 选择 RAG：arxiv_2005.11401v4 / r_269ac0cb1263292d。提交 D2-001：  
   What forms of parametric and non-parametric memory are combined in the RAG model?
2. 切换 ReAct：arxiv_2210.03629v3 / r_22af23d03fcb87a8。提交 D5-006：  
   According to the selected ReAct paper (arXiv:2210.03629v3), what is the scheduled release date of the Streamlit interface for the local paper-research-assistant project?
3. 展开答案/不足理由、原文与 PDF 文件页序；下载 JSON/Markdown，检查 run_id 和来源一致。
4. 演示重绘和下载只复用会话结果，没有新增提交或历史。

常规路径预计共 2 次问题 embedding、2 次聊天；这是计划值。沿用现有共享预算：每题聊天总尝试硬上限为 3 次，含最多一次网络重试和一次格式/引用修复；两题合计聊天预算最多 6 次，真实请求和 tokens 据记录统计。不要为了画面好看无限重跑，也不提前承诺零重试或相同输出。

两个问题即可同时验证新环境闭环和录屏。异常结果保留，先记录再诊断；不能把业务错误静默换成历史成功。历史文件可以辅助展示，必须标“历史回放”，当前页面没有加载历史会话入口。

完成标准：实际产出并播放核对 3–5 分钟视频；保存两题新 run_id、配置/源码/数据绑定、终态、原文/页码、实际用量及下载 SHA。录制工具不可用时先交付脚本、截图和录制说明，视频仍标待录制，不将脚本等同录屏完成。

预期输出：docs/d7/d7-D-demo-guide.md、artifacts/d7/demo_<run_id>/、artifacts/d7/task_d.json/.md。具体视频名和副本内部运行记录路径以实际输出登记。

## 8. E：简历整合

沿用 [G 的简短草稿](/D:/course/paper-research-assistant/docs/v1/d6/d6-G-completion-guide.md)，以 Python、RAG、Qdrant、SQLite 为技术栈，正文突出版本过滤、证据检索、引用回查及可解释的评测。

- 20 题说明题目标注经人审；C 数字说明样本为扩充前 16 题中的 13 道可答。
- 9/13→13/13 表示全部标注依据返回命中；实际展示 12/13。43/43 只表示引用定位。
- “预计加入最多一次自动补检索并对比效果与成本”单独列出，不写已实现 Agent。
- API 接入和库使用简要提及，不作为主要贡献。
- 个人简历使用[已有 Markdown](/E:/Project_Metroidvania/Metroidvania/葛广一/葛广一.md)，执行时先读当前版本、保存备份，并沿用现有版式；当前只规划，没有修改该文件。

完成标准：一份可直接使用的精简条目；实际简历整合以真实编辑记录为准。即使 A 发现局部歧义，仍如实使用已经核对的工程数字，不用语义缺口虚构准确率。

预期输出：docs/d7/d7-E-resume-guide.md、artifacts/d7/resume_project_entry.md、artifacts/d7/task_e.json/.md；个人简历修改另留备份及路径记录。

## 9. F：面试讲述与投递准备

准备 3–5 分钟讲述，按“问题→流程→自己的实现→实际结果→一个失败→下一步”组织，包含两个取舍：

- 固定 RAG 的工程流程与未来 Agent 判断证据不足分别由谁负责。
- 保留完整证据片段与 8000 字符预算的取舍；用 D2-004 在 top-20 标注依据因完整片段预算未进入展示上下文说明。

准备三类追问：检索命中怎么测、引用定位为什么不等于答案正确、可答题拒答如何计分。实际口述演练有记录才标完成。

岗位先筛 3–5 个，优先比较 Python/AI 应用/Agent 实习要求与已实现项目的匹配。执行筛选时核对仍开放的真实岗位和来源，不把过期信息列成可投。台账区分 candidate、prepared、submitted；用户实际提交及回执另记，不把已准备当已投递。

完成标准：讲述稿、追问要点、真实岗位/投递准备材料可审阅；个人实际口述与投递状态按证据填写。当前不检索岗位、不发送申请。

预期输出：docs/d7/d7-F-interview-guide.md、artifacts/d7/interview_outline.md、artifacts/d7/application_tracker.json/.md、artifacts/d7/task_f.json/.md。

## 10. G：汇总与 D8 交接

汇总 A–F 的实际状态、阻塞、材料及新请求用量；人审、视频、实际投递各自单列。将 README/架构说明按实际预演反馈定稿，整理材料入口。

文档或源码改动的记录分别说明：当前新验证、按相同源码继承的旧验证、因输入变化仅保留历史的验证。D7 无源码变化时不用为了凑数量重跑旧检查；确有变化时只做适用检查。更新已经绑定的 README、目录、总计划时，先保存旧快照，再留下新修订的证据，旧 D6 历史不改。

D8 交接只列待实现接口和对照：

- 判断具体缺少什么事实，最多改写并补检索一次。
- 固定核心首轮 top-5/8000、论文/解析版本及模型配置作为对照起点。
- 记录缺失信息、补查 query、新增证据、停止条件、实际请求/重试/修复与成本。
- 验收题 D11 前不参与实现或调参。

完成标准：读者能找到可运行/可展示材料，清楚哪些已完成、哪些仍待用户实际操作。即使有待办也可以做 G 汇总，但不能据此把 D7 整体写成全部完成。

预期输出：docs/d7/d7-G-completion-guide.md、artifacts/d7/task_g.json/.md、D8 交接清单。

## 11. 执行纪律与学习重点

- 每项任务用新记录；正式题集、三批首跑输出、冻结规则、旧运行历史保持原样。
- 只在 D 使用必要的新真实问答；原始 token 用量和新实际用量分开，不从 tokens 虚构人民币费用。
- AI 评价、程序核对、用户实际人审分别记录；新增计划材料不计作任务已执行。
- 学习限于当前需要的 venv/pip、依赖与配置、数据版本/路径、页面重绘和资源生命周期。读懂后能解释为什么“代码能运行”还不足以证明别人可以复现，专题学习控制在 30–45 分钟并计入各任务时间。
- 一天只够 4 小时时，先 B→C→D（预计 3 小时 45 分钟），余 15 分钟记录完成与阻塞；E 先沿用已有草稿，A/F、简历新整合及完整 G 汇总顺延，状态保持 pending。
