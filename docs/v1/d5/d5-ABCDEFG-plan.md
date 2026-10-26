# D5 执行计划：固定 RAG、结构化回答与引用校验

制定日期：2026-10-02（Asia/Shanghai）。依据：[D4 完成与交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)、[两周总计划](/D:/course/hello-agents-study/log/plan-codex.md)，并核对当前源码、正式验收记录和开发题集。

**当前阶段：D4 已完成；D5 A–E 已完成，F 已保存十题初跑与 AI 评价，六题保留候选。G 工程验收汇总和 D6 交接已完成，D5 总状态为“实现完成，评测/人审待补”。** 正式十六题初跑与新答案人审尚未完成；总计划中“D5 / 10 月 1 日”是原始日历，不是本次实际完成日期。

A 执行更新（2026-10-02；保留 A 阶段当时记录）：三篇 ready、1188 个 chunk；本机 embedding 配置与正式 profile 一致。30 项 D4 源码引用、20 个不同文件的 SHA 全部匹配，未重跑旧测试；本次核对的 86 个文件前后哈希不变。已完成课程映射、接口清单、四类判断解释、五个现有结构演示与首轮非敏感配置，embedding/聊天/网络均 0 次。使用者理解未测量，不新增人工确认。见 [任务 A 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-A-contract-guide.md)、[机器记录](/D:/course/paper-research-assistant/artifacts/d5/task_a.json) 和 [首轮配置](/D:/course/paper-research-assistant/artifacts/d5/baseline_config.json)；下一步任务 B 补完整聊天调用。

B 执行更新（2026-10-02；保留 B 阶段当时记录）：已新增 `RecordedLLM`、`ChatPolicy` 与共享 `ChatBudget`，保留 D2 的字符串入口。完整记录响应文本、finish_reason、实际 usage、耗时、SDK/HTTP 尝试；关闭 SDK 隐式重试，正常生成/一次修复/一次网络重试共用最多三次预算。34 项离线检查通过；真实 DeepSeek 连通验证成功，1 次聊天请求、56 tokens、embedding 0 次。详见 [任务 B 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-B-llm-guide.md) 与 [完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_b.json)。A 的配置文件保留为当时快照，B 实际配置另存 [chat_runtime_config.json](/D:/course/paper-research-assistant/artifacts/d5/chat_runtime_config.json)。下一步 C 选择实际证据、构建提示词并解析 `AnswerDraft`。

C 执行更新（2026-10-02；保留 C 阶段当时记录）：已新增完整片段上下文选择、精确展示快照、版本化提示词与严格 AnswerDraft 解析；格式修复和 B/D 共用预算。38 项核心离线检查通过，三组 D4 候选离线回放；固定 RAG 首题执行新检索与真实生成，5 条展示证据、4837 正文字符、3 条草稿结论。问题 embedding 1 次/34 tokens，聊天 1 次/2758 tokens，无重试/修复。终态为 draft_valid，引用业务校验 pending，未计算答案准确率。见 [任务 C 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-C-generation-guide.md) 与 [完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_c.json)。正式数据与旧验收不变；下一步 D 回查引用并串通固定流程。

D 执行更新（2026-10-02；保留 D 阶段当时记录）：已实现引用允许集合、SQLite身份/全文快照、实际PDF路径/字节SHA/真实页序回查；固定一轮检索、生成、共享修复与程序终态已串通。42项核心+15项运行记录检查通过；C旧草稿离线5次引用/2来源全部valid（0网络）。D新真实首题为 answered，5条展示证据、4837字符、3结论、5次引用检查与2来源；embedding1次/34 tokens、聊天1次/2758 tokens，无重试/修复。answered仅说明结构与来源定位通过，semantic_support_status=not_reviewed；未计算问答准确率。见 [任务D指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-D-rag-guide.md)、[完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_d.json) 与 [真实答案和原文](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke.md)。下一步E提供通用CLI、日志导出和组合边界。

E 执行更新（2026-10-03）：通用 `scripts.answer_question` CLI、完整 JSON/Markdown 与不可覆盖历史已实现，复用 D 固定核心。37 项离线检查通过，58 个 CLI 场景、59 次 SDK MockTransport 模拟 HTTP，真实网络 0 次。新真实 CLI 首题退出码 0/answered，3 条结论、5 次引用定位检查、2 来源（PDF 文件页序 1/2）；新增 embedding 1 次/34 tokens、聊天 1 次/2758 tokens，无重试/修复。纯 JSON 输出与最近/历史记录一致，正式输入和旧源码未改。两项来源/部分支持案例另作 AI 复核，0 API、人审 pending，不计问答准确率。见 [任务 E 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)、[完成记录](/D:/course/paper-research-assistant/artifacts/d5/task_e.json) 和 [当前答案](/D:/course/paper-research-assistant/artifacts/d5/answer_result.md)。下一步 F 开发题集初跑、扩充与语义评价；G 总验收待完成。

F 执行更新（2026-10-04）：新增顺序批跑与事后机器评分，46 项离线检查通过，真实 API 0 次；冻结评分规则后先跑四类代表题，再同批继续剩余六题，前四题不重复调用。正式十题首次运行均保存：7 题 answered、3 题 insufficient_evidence；其中 2 道可回答题缺所需依据，1 道资料外题返回不足。最终引用定位合法 21/21，精确全部标注引文命中 5/9（单条 7/12）；这些机器统计不是语义准确率。AI 按实际所引展示原文逐条评价，答案人审 pending。实际新增 embedding 10 次/379 tokens、聊天 10 次/22612 tokens，无重试/修复；174 项记录核对通过，332 项旧源码/正式输入/验收文件哈希不变。四事实题、两资料外题的来源复核包已准备，用户明确“暂未复核，先保留候选”，所以正式文件仍为十题，十六题初跑未完成。见 [F 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-F-evaluation-guide.md)、[进度记录](/D:/course/paper-research-assistant/artifacts/d5/task_f.md)、[逐题 AI 评价](/D:/course/paper-research-assistant/artifacts/d5/qa_baseline/d5_f_dev10_20261004/ai_semantic_review.md) 和 [候选材料](/D:/course/paper-research-assistant/artifacts/d5/eval_candidate_review.md)。G 尚待执行；界面及自动补检索仍按 D6/D8 推进。

G 执行更新（2026-10-04）：已完成 A–F 证据汇总、新进程离线验收与 D6 交接。当前源码绑定的 B 34、C 38+8、D 42+15、E 37、F 46 项旧检查记录均可继承，本次没有重跑这些测试；F 174 项原始记录核对保留。新 `scripts.validate_d5` 192 项证据/状态核对通过，正式 SQLite 仍为三篇、三个版本、1188 个 chunk、三个 ready 导入；模型请求 0，正式题集/数据及原十题批次不改。G 汇总任务已完成，D5 全体验收仍为 false：六题人工复核及合并补跑、新答案人审继续待补；两道可回答题的检索不足保留。下一步可进入 D6 最小界面，直接复用固定核心与 E 外围的资源/记录方式。见 [G 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md)、[验收记录](/D:/course/paper-research-assistant/artifacts/d5/validation.md)、[阶段记录](/D:/course/paper-research-assistant/artifacts/d5/task_g.json) 和 [独立证据审计](/D:/course/paper-research-assistant/artifacts/d5/g_evidence_audit.md)。上方 A–F 段落保留各阶段当时的进度与费用，不改写旧历史。

## 1. D5 做完以后能用什么

输入问题，明确选择一篇或多篇论文及处理版本，CLI 执行一次检索，基于实际提供的证据生成结构化结论，程序检查引用后展示答案、原文和 PDF 文件页序。证据不足时明确说明本轮不足；服务或数据故障时返回错误状态。每次运行都能从记录还原问题、候选、真正发送给模型的证据、原始输出和校验结果。

```text
问题 + 明确的论文/处理版本配对
    → D4 EvidenceSearcher：一次问题 embedding，top-5，SQLite 原文核验
    → 选择并保存本轮实际展示的证据
    → 聊天模型：AnswerDraft（回答 / 证据不足）
    → 程序检查结构、引用存在性、范围与来源
    → 答案或明确终态 + 可回查证据 + 本轮记录
```

开发目标沿用总计划：固定 RAG CLI、拒答与工具错误区分、开发集从 10 题增至 16 题并保存初跑。D6 接界面，D8 才加入一次补检索。

## 2. 当前基础与必须保留的问题

| 项目 | 已核实的当前状态 | D5 的处理 |
|---|---|---|
| D4 验收 | `completed_with_known_issues`；技术验收通过，交接 `ready` | 复用正式库，不重新解析或生成文档向量 |
| 正式数据 | 3 篇、71 页、1188 个 chunk；SQLite/Qdrant 三个版本均 ready | 查询只读事实库，用完整论文/版本配对限定范围 |
| 索引配置 | `ep_cbf0f6caa97b962a`，`qwen3.7-text-embedding`，1024 维，cosine | 维持当前问题与文档配置 |
| 检索入口 | `EvidenceSearcher.search_evidence()` 已实现 | 直接调用核心，不通过 CLI 子进程拼接 |
| 聊天配置 | `LLMSettings`、`load_llm_settings()`、`invoke_llm()` 已存在 | 补全问答调用，不重复建立配置体系 |
| 输出结构 | `EvidenceRef`、`Claim`、`AnswerDraft` 已存在 | 复用结构，新增引用业务校验与运行结果 |
| 正式开发集 | `eval/dev.jsonl` 十题，全部 `human_verified` | 保留原十题，新增六题经复核后再并入 |
| 已知召回问题 | ReAct D2-003 原正式 top-5 没有题目要求的摘要依据 | 保留来源约束失败样例，不偷补摘要 |
| 人工确认范围 | D4 B 三十条抽样、F 三题十五候选/十三页 | 不扩展成全部 chunk 或未来答案人工通过 |

三个固定版本：

| 论文 | paper_id | parse_revision | chunk 数 |
|---|---|---|---:|
| RAG | `arxiv_2005.11401v4` | `r_269ac0cb1263292d` | 385 |
| ReAct | `arxiv_2210.03629v3` | `r_22af23d03fcb87a8` | 480 |
| Reflexion | `arxiv_2303.11366v4` | `r_d7736b29a2d8b39e` | 323 |

ReAct 的目标摘要 chunk 完整在库，F 的独立新请求测得 rank 9；这不是 E 原请求的完整排序。D4 的严格来源依据 2/3 只是三题检索观察，不是问答准确率。

D3 六页人工覆盖及图文/公式恢复稿保留各自状态。D5 继续使用正式正文索引，这些待确认事项不阻塞已有正文的问答，也不自动并入证据。

D4 验收记录绑定了当时源码 SHA，包括 `schemas.py`、`config.py`、`embedding_client.py`、`search.py` 等。D5 优先新增外围模块、修改未被这些检查绑定的聊天薄层，保留 D4 输入、数据、原始查询与验收历史。若确需修改被绑定的公共源码，先保留旧验收，重跑受影响边界并保存新的实际记录；不能改旧 SHA 来制造通过，也不能用原 G 成功代表修改后源码已经验证。`validate_d4` 会更新当前 `validation.json/.md`，执行前须明确本次复验要绑定哪些新记录。

## 3. 七项任务与一天的时间安排

明确任务 400 分钟，休息 30 分钟，阻塞缓冲 20 分钟，共 7 小时 30 分钟；第 8 小时用于补未通过的核心验收。估时按复用现有代码计算，逐行学习或人工复核较慢时拆成两次，不以到点代替完成。

| 顺序 | 用时 | 任务 | 完成时留下什么 |
|---|---:|---|---|
| A | 40 分钟 | 读懂现有契约，固定问答参数与判定规则 | 已完成；[接口清单、状态约定与首轮配置说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-A-contract-guide.md) |
| B | 50 分钟 | 补全聊天调用适配层 | 已完成；[响应、共享预算、错误与验证说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-B-llm-guide.md) |
| C | 65 分钟 | 实现上下文选择、提示词和结构化生成 | 已完成；[证据快照、消息与草稿解析说明](/D:/course/paper-research-assistant/docs/v1/d5/d5-C-generation-guide.md) |
| D | 65 分钟 | 引用业务校验，串通固定 RAG 核心 | 已完成；[引用回查、固定流程与实际验收](/D:/course/paper-research-assistant/docs/v1/d5/d5-D-rag-guide.md) |
| E | 65 分钟 | CLI、运行记录与离线故障检查 | 已完成；[通用 CLI、导出与组合检查](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md) |
| F | 80 分钟 | 四题试跑、十题初跑、新增六题与初步评分 | 十题初跑/AI 评价及候选材料已完成；六题复核、十六题初跑待补；[F 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-F-evaluation-guide.md) |
| G | 35 分钟 | 汇总验收、讲解设计、更新交接 | 已完成工程汇总和交接；D5 评测/人审待补；[G 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-G-completion-guide.md) |

依赖顺序为 `A → B → C → D → E → F → G`。新题选材和原文定位可在实现间隙并行准备；正式问答初跑需使用已经通过引用边界检查的主链路。

## 4. A：先固定要回答什么、怎样算完成

课程限时约 25 分钟：第八章 8.3 的证据到回答部分、第十二章 12.1 的评价口径；剩余时间对照 `schemas.py`、`search.py` 和 `llm_client.py`。不重读已经完成的入库流程。

需要能解释四件事：为什么检到片段还不等于有答案；为什么真实 ID 仍可能是无效引用；为什么结构校验不能证明语义支持；为什么拒答和系统失败必须分开。

先离线列出 ready 版本，并读取当前 D4 报告。正式库有变化或完整性存疑时，先确认源码与验收记录的绑定关系，再按上节规则执行 `scripts.validate_d4`；不为每次问答重复全量验收。运行前结束其他持有同一 Qdrant 目录的进程。

本次起始参数是计划值，真实执行时保存实际值：

| 参数 | D5 起始约定 |
|---|---|
| 论文范围 | 1–3 篇，使用完整 `(paper_id, parse_revision)` 配对 |
| 检索 | 一轮，`top_k=5`，直接向量化原问题 |
| 证据正文预算 | 最多 8000 个 Python 字符，统计 `shown_text`；不冒充 token |
| 生成采样 | 显式低温度，起点 `temperature=0.2`；记录实际值 |
| 生成输出上限 | 起点 `max_tokens=1200`，用真实 JSON 样本确认足够 |
| 聊天请求 | 正常一次；总上限三次，包含最多一次格式/引用修复、最多一次可重试网络故障重试 |
| 超时 | 每次聊天请求起点 30 秒；整轮截止预算起点 120 秒，按下述阶段检查执行 |

以上预算由程序执行。D5 先实现计数、阶段之间的截止时间检查和有界重试；D9 再系统补充更全面的预算故障组合。问答开始时建立 deadline，检索前后、生成/修复/重试前后都检查；聊天请求按剩余时间收紧超时，达到截止时间后不再发后续请求。

现有问题 embedding 固定使用 `httpx` 30 秒超时，`EvidenceSearcher` 没有 deadline 参数。D5 默认保留该入口，检索返回后若已超时则结束，不再进入生成；这不能保证正在进行的同步请求在整轮第 120 秒被精确中止。记录实际耗时与超时阶段，不宣称墙钟硬截止已经通过。若实现时增加可控检索超时，优先使用现有 embedder 注入口；修改公共客户端时遵守 D4 源码绑定与回归规则。

## 5. B：补全已有聊天入口

执行前，`paper_assistant/llm_client.py` 只有 D2 连通验证薄层：输出上限固定 128 tokens，只返回字符串。B 已保留这一旧入口，并新增问答用的 `RecordedLLM`。以下说明保留原设计依据，实际接口和验证结果以任务 B 指南为准。

本地已安装的 HelloAgentsLLM 还存在两个具体限制：`invoke()` 不返回 usage/finish_reason；其 OpenAI 客户端默认允许两次 SDK 重试。因此一次 wrapper 调用不能直接记为一次真实 HTTP 请求，给 HelloAgentsLLM 构造器传 `max_retries=0` 也不会自动关闭底层重试。

最小实现建议：保留 D2 的 `invoke_llm()`；在同一项目适配模块增加问答用的完整响应函数，沿用已有模型与 `LLM_*` 配置，通过已安装底层 SDK 的公开接口显式关闭隐式重试。这样可以取得文本、usage、finish_reason，并由项目代码统一执行重试和计数。无需新增框架，不改 `site-packages`。

需要做到：

- 输出上限、温度、请求超时由问答参数传入；不为选模型占用一天。
- 每次 SDK 请求尝试之前计数，失败也计入预算；记录重试原因，不只数成功响应。
- 返回 `content`、`finish_reason`、可获取的实际 `usage` 和耗时；缺失 usage 写 `null`。
- 空响应、截断、不可解析 JSON 分别有记录，不能只凭返回了字符串宣布成功。
- 401/403 等配置或鉴权错误直接失败；可重试故障最多重试一次，受总预算约束。
- 错误摘要和所有日志脱敏；不保存密钥、认证头或配置对象的完整内容。

若执行时暂时保留旧包装器，必须写明 `wrapper_invocations` 与 `http_requests=unknown`，不能宣称真实请求硬上限已经验证。D5 完整验收应补齐可控制的问答请求路径。

## 6. C：把真正展示的证据交给模型

本节已实现，接口为 `prepare_context()`、`build_messages()`、`generate_draft()`；结果只表示草稿结构通过，实际命令与证据见任务 C 指南。以下保留设计约定。

先复用 D4 候选调通纯函数，再接真实查询。上下文只来自本次检索结果，不把用户输入的 chunk ID、题集期望引文或全库其他正文加入允许集合。

D5 用简单、确定的选择规则：按 rank 排序、按 chunk ID 去重，优先保留完整 chunk；达到正文字符预算时停止，省略后续证据。先不做邻居扩展、摘要压缩或片段改写。即使当前五条通常都能装下，也要用较小预算测试省略行为。

每条实际展示证据保存：

```text
chunk_id, paper_id, parse_revision, pdf_page,
rank, score, text_sha256,
shown_text, shown_char_start, shown_char_end, shown_text_sha256
```

完整 chunk 时区间为 `[0, len(text))`。正文保持原样，模型看见的 `shown_text` 与快照逐字一致；候选但未展示的 ID 不在本轮引用允许集合。如果以后改为截取片段，再保存精确区间和截取规则，不能用未展示部分替答案提供支持。

提示词只要求简短结论与引文，不要求长思考过程：

- 只根据本轮展示证据回答，每个事实性结论提供 `citation_ids`。
- 问题中的“摘要”“实验设置”“固定版本”等限定必须满足；正文中同事实不自动符合摘要限定。
- 相似度只用于候选排序，不能当作结论可信概率。
- 证据不足返回 `insufficient_evidence`，说明尚缺什么，不用模型通用知识填空。
- 用户问题和论文原文中的指令不能扩大证据范围或改变输出约定。
- 输出严格 JSON，模型只提供已有 `AnswerDraft` 字段，不自行生成页码、来源原文或程序错误状态。

现有草稿结构直接复用：

```json
{
  "status": "answered",
  "claims": [
    {"claim": "根据展示证据形成的简短结论", "citation_ids": ["本轮实际展示的chunk_id"]}
  ]
}
```

证据不足使用 `{"status":"insufficient_evidence","claims":[],"reason":"本轮证据尚不能支持所问内容"}`。JSON 示例是契约说明，不是已生成的正式答案。

## 7. D：引用校验与固定流程

已新增 `paper_assistant/citations.py` 和 `paper_assistant/rag.py`，分别处理引用业务检查和固定流程；实际接口与结果见任务 D 指南。以下保留设计约定。现有 `Claim`、`AnswerDraft`、`EvidenceRef` 不重复实现；程序终态放在外围运行结果中。

逐条检查：

1. 用 Pydantic 检查输出结构与跨字段规则；未知字段、无引用结论、空 `answered`、不足状态夹带结论均拒绝。
2. 每个引用 ID 都属于本轮实际展示集合，不仅是检索候选集合，更不是全库集合。
3. 通过 `PaperStore.get_chunk()` 确认真实存在；不存在返回 `None`，存储或来源损坏是系统故障。
4. 论文与处理版本属于本轮选定完整配对；页码、文本哈希与展示快照一致。
5. 由程序填入 `EvidenceRef` 四字段，补充原文、PDF 来源；模型生成的定位信息不能覆盖事实库。

引用有误时记录具体失败，可在同一展示证据集合内修复一次；仍失败则 `invalid_output`。不悄悄删除错误引用后把整份草稿显示为成功。引用校验通过只说明可以定位与回查，语义支持另行评阅。

当前 chunk 没有规范化的 `section` 字段，不能仅凭 PDF 第 1 页判定“摘要”。D5 通过问题约束、候选原文和逐条复核判断支持度；需要自动章节定位时另立后续任务。

| 情况 | 程序终态 | 应表达的意思 |
|---|---|---|
| 有依据、草稿合法、引用业务校验通过 | `answered` | 返回结论与可回查引用，支持度仍需评价 |
| 检索正常无候选 | `insufficient_evidence` | 本次检索未返回证据；可直接返回，不必调用聊天模型 |
| 有候选但不支持问题或来源限定 | `insufficient_evidence` | 本轮依据不足，不断言论文一定没有相关内容 |
| 配置、检索、模型服务、正式库或来源检查故障 | `tool_error` | 记录失败阶段与安全错误，不包装成资料不足 |
| 草稿结构/引用错误在修复后仍未通过 | `invalid_output` | 本轮没有可发布的有效答案 |
| 已达请求数或总时限上限 | `budget_exceeded` | 停止继续请求，保存已有步骤与终止原因 |

资源管理沿用 D4：SQLite 只读，一个进程拥有一个本地 Qdrant 客户端，借用者不另开目录锁；成功、异常和预算停止均关闭资源。

## 8. E：CLI、运行记录与边界验证

已实现入口 `scripts.answer_question`，详见 [任务 E 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-E-answering-guide.md)。下文保留设计约定。参数沿用检索命令的单篇 `--paper-id/--parse-revision` 与可重复的 `--version PAPER_ID PARSE_REVISION`。业务代码放在 `rag.py`，CLI 只负责参数、资源、输出和保存记录，便于 D6 界面复用。

下面的命令已可执行；本次已用它完成真实首题验证，再执行会使用新模型额度：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.answer_question `
  --paper-id arxiv_2005.11401v4 `
  --parse-revision r_269ac0cb1263292d `
  --query 'What forms of parametric and non-parametric memory are combined in the RAG model?' `
  --top-k 5
$LASTEXITCODE
```

建议退出码：`0` 为正常业务终态（`answered` 或 `insufficient_evidence`）；`1` 为系统、输出或预算失败；`2` 为参数用法错误。详细状态仍以 JSON 为准，批量 runner 必须保存非零结果，不能跳过失败题。

每次记录至少包含：`run_id`、实际时间、问题、selected_versions、索引身份、候选、shown_evidence、实际 messages、原始响应、解析草稿、引用校验明细、最终输出、失败阶段、实际配置、各次请求统计与耗时。保存本次使用的提示词版本、相关源码 SHA 和题集版本，便于比较初跑与回归。

文件安排建议：

| 位置 | 用途 |
|---|---|
| `artifacts/d5/answer_result.json/.md` | 最近一次问答，页面与日常核对入口 |
| `archive/run_logs/d5/answer_<run_id>.json` | 每次完整记录，历史结果不覆盖 |
| `artifacts/d5/qa_baseline/<batch_id>/` | 本批逐题结果、配置清单、评分与汇总 |
| `artifacts/d5/boundary_validation.json/.md` | 离线业务边界结果，与问答质量分别统计 |
| `docs/d5/d5-G-completion-guide.md` | 完成后按实际代码更新的操作与 D6 交接 |

离线检查延续现有 `scripts.check_*` 风格，按需新增 `check_answering`。不重建 D4 全套测试，用临时库、假检索/模型响应覆盖新增业务边界：

| 边界 | 必须观察到什么 |
|---|---|
| 引用 ID 不存在 | 被拦截，不能输出成功答案 |
| 全库存在但本轮未展示，包括预算省略的候选 | 被拦截 |
| 用户在问题中伪造/指定库外引用 ID | 不会扩展允许集合 |
| 错论文、错版本、错页码或快照哈希 | 不允许作为合法引用；数据损坏明确失败 |
| 畸形 JSON、多余字段、无引用结论、状态矛盾 | 结构失败，有界修复后仍错则失败 |
| 空响应、输出截断 | 有独立记录，不当作成功 |
| `no_hits` 与 `SearchError` | 分别得到资料不足与系统错误 |
| 超时/可重试服务错误/鉴权错误 | 分别按策略处理，所有尝试计入预算 |
| 修复和重试耗尽、总时限到达 | 停止，返回明确终态 |
| usage 缺失、故障后关闭、日志含密钥的异常文本 | 缺失据实记录、资源释放、日志脱敏 |

另做两个来源与语义案例复核：正文支持同事实但不满足“摘要”限定；候选只支持复合问题的部分事实。这两项不能仅凭结构测试判定正确，也不计入程序测试通过数来提高问答成绩。

## 9. F：真实题目、扩充与初跑

### 9.1 先用现有四题打通链路

| 题目 | 目的 | 依据当前 D4 候选的合理预期 |
|---|---|---|
| RAG D2-001 | 正常事实与精确引用 | 结论有支持，引用两类记忆的实际证据 |
| Reflexion D2-005 | 多要点事实 | 只回答候选明确支持的权重/反馈/记忆机制 |
| ReAct D2-003 | “摘要”来源限定 | 本轮仍缺摘要依据时明确不足，正文同事实不冒充摘要 |
| D2-006 | 资料外问题 | 说明选定论文证据不足，不用通用知识补价格 |

可以先回放 D4 已保存候选调试生成与引用校验：这是候选回放实验，新增 embedding 请求为 0。完整固定 RAG 初跑必须执行真实检索和真实聊天模型；回放结果不混写成新端到端运行。

新真实查询的候选可能波动，判断根据本轮结果，不强行写死 ReAct 必须拒答。若本轮合法展示了完整摘要证据，可正常回答并保存与旧基线的差异；不得从评分标注直接回查摘要，或静默增大 top-k。

**ReAct D2-003 仍是 `answerable=true`。** 因当前检索不足而拒答，是遵守证据规则的行为，但在可回答题完成率中仍计未完成/错误拒答；不能算作应拒答题正确，也不能改题目标注来制造通过。

四题试跑通过核心边界后运行全部现有十题，保存首次配置与原始输出。配置一致时四题可作为同批的前四题，不必重复付费；提示词或代码改变后明确新批次/回归，保留此前结果。

### 9.2 从十题扩到十六题

当前分布为 4 fact、3 method、2 retrieval_paraphrase、1 unanswerable。建议 D5 新增 4 条独立事实题、2 条独立无答案题，达到 `8/3/2/3` 共 16 条；事实题从三篇正文里选，避开已覆盖事实的简单改写。D6 再补 2 fact、1 method、1 retrieval_paraphrase，得到 `10/4/3/3` 的二十题开发集。

新题先保存到 `artifacts/d5/eval_candidates.jsonl`，配套可读原文/PDF 复核材料；用户明确复核后才并入唯一正式 `eval/dev.jsonl`。保留原十题及其确认记录，不自动把 AI 初审写成 `human_verified`。

题目记录沿用已有字段：题型、论文范围、可回答性、期望要点、原文 quote、PDF 文件页序、PDF 哈希、复核人和状态。无答案题要说明为什么选定资料不能支持，并核对它不是因当前 top-k 漏召回而被误标；避免复杂表格、恢复公式和跨论文深度比较。

检索和生成路径只接收问题、选定正式版本和本轮证据；`expected_points`、`expected_evidence`、`answerable` 只供事后评分，不进入运行提示词或选证据逻辑。

如果六题人工复核尚未完成，继续用正式十题初跑；如实写“十题正式 + 六题候选待确认”，不要宣布开发集已正式达到十六题。完整十六题初跑等确认合并后补齐。

### 9.3 先写评分规则，再读结果

逐题核对关键要点、每条结论所引原文及来源限定。程序引用合法、人审语义支持与 AI 辅助评价分别记录；D4 题目标注通过不代表 D5 答案已通过人审。

最小汇总包括：关键依据检索命中数/可回答题数（分别统计返回候选与实际展示集合）、可回答题完成数/可回答题数、错误拒答数、无答案题正确拒答数/无答案题数、定位合法引用数/输出引用数、原始校验拦截数、被原文支持的结论数/全部事实结论数，以及终态、真实请求、可获取 tokens 与耗时。无引用或支持度尚未人评时写 N/A/待评，不填虚构的 100%。

失败归因先区分：没检到关键证据；检到但没展示；展示了但生成错误；引用定位错误；结构/系统错误。保存原始失败与修复后回归，初跑不要求全部题目正确，更不能把开发集成绩称为冻结验收集成绩。

正常十六题若都进入生成，大致是 16 次问题 embedding + 16 次聊天请求；四题不再额外重复。实际请求可能因提前失败、无候选、重试或修复变化，一律以记录为准。六题标注和离线边界验证不需模型 API。

## 10. G：完成判定与 D6 交接

- [x] 固定 RAG CLI 能在现有正式库上执行一轮检索并生成回答或证据不足。
- [x] 输出结构复用现有契约；事实结论有引用，定位由程序补齐。
- [x] 不存在、未展示、跨范围与来源冲突等错误引用被拦截。
- [x] 展示正文、允许引用集合、实际 messages 和快照一致。
- [x] `no_hits`、候选不足、服务/数据失败、无效输出和预算停止有明确区别。
- [x] 聊天输出长度、采样、显式重试与调用统计可核对，缺失 usage 据实标注。
- [x] 现有十题真实初跑已保存，前四题未重复付费。
- [ ] 六条新增题完成人工复核后合并并补齐十六题初跑。
- [x] 正常事实、来源受限、资料外题有逐条 AI 证据复核记录；新答案人审未完成已明确列出。
- [x] D5 程序边界检查通过并与当前源码匹配，质量不足与系统失败保留；G 本次未重跑旧测试。
- [x] 操作说明包含命令、资源关闭方式、最近结果与历史结果入口。

代码闭环和离线边界通过，可进入 D6 的界面接入；如果新题复核或答案评分未完成，D5 总状态应写“实现完成，评测/人审待补”，不要写全部验收通过。答案质量存在已知失败时，在具备记录与合理边界的前提下保留问题继续推进，不要求先把所有召回问题消掉。

D6 第一件事：让 Streamlit 直接复用 `rag.py`，显示终态、结论和实际证据；不在页面复制业务逻辑或再次打开同一个 Qdrant 目录。随后开发集补至 20 条，另准备并冻结 20 条验收题及评分规则。

## 11. 今天暂缓什么，延期时怎样收缩

| 项目 | 后续安排 |
|---|---|
| Streamlit、上传和导出界面 | D6 |
| `retry_search` 动作、模型选择补查、Agent 对照 | D8 |
| 更全面的预算/重试组合与上下文工程 | D9，D5 已有基本硬限制 |
| HyDE、重排、参考文献过滤、邻居扩展、重分块 | 独立后续实验，不是 D5 前置条件 |
| 新 embedding 模型或索引 | 先保留当前正式配置；改变时建立新索引身份 |
| 复杂章节解析、图表/公式问答 | 当前文本主链路之外 |

B/C 卡住时先缩为单篇 RAG、一两条结论；保留完整引用检查与记录。F 时间不足时先完成十题真实初跑和六题候选材料，把待确认事项写清。核心问答仍未跑通时，D6 先继续修主链路，再缩减界面；不通过增加模型、检索轮数或论文数量掩盖问题。

**G 已完成工程汇总与 D6 交接，D5 实现完成、评测/人审待补。六题保持候选，正式十六题合并/初跑与新答案人审未完成；可以开始 D6 界面，不把待补事项写为已通过。**
