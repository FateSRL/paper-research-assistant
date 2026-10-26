# D5 任务 A：接口、回答规则与首轮配置

完成日期：2026-10-02（Asia/Shanghai）。依据：[D5 执行计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md)、当前业务源码和 [D4 正式验收](/D:/course/paper-research-assistant/artifacts/d4/validation.json)。

后续进度：B 已完成，见 [任务 B 指南](/D:/course/paper-research-assistant/docs/v1/d5/d5-B-llm-guide.md)。本指南与 `task_a.json`、`baseline_config.json` 描述 A 执行时的状态；下文“B–G 待执行”及旧聊天配置是当时快照，当前进度以 D5 总计划为准。

**A 的准备工作已完成：指定课程内容已阅读并映射到项目，接口与状态规则已整理，正式 ready 范围和非敏感配置已离线核对。** 本次没有运行问答模型、修改业务源码或重建索引。B–G 仍待执行，使用者的理解程度没有被测量，也没有新增人工确认。

机器记录：[task_a.json](/D:/course/paper-research-assistant/artifacts/d5/task_a.json)。首轮参数：[baseline_config.json](/D:/course/paper-research-assistant/artifacts/d5/baseline_config.json)。后续实现和初跑读取这里的约定，并记录届时实际使用值；它还不是 D10 冻结配置。

## 1. 本次实际核对了什么

| 检查 | 实际结果 | 结论的范围 |
|---|---|---|
| `search_evidence --list-ready` | 退出码 0，三篇共 1188 个 chunk，均 ready | 从 SQLite 读取当前状态，不重新检查全部向量 |
| 索引指针与固定清单 | 身份重算及清单一致 | 当前正式 profile 可读取 |
| 本机 embedding 配置 | 与正式 profile 完整一致 | 只验证本地配置，没有重新验证服务连通 |
| D4 源码绑定 | 30 项引用核对，涉及 20 个不同文件，全部 SHA 匹配 | 没有重跑此前 81 项测试或 G 全量验收 |
| 现有草稿结构演示 | 五种样例都表现为预期接受/拒绝 | 验证已有结构规则，不代表 D5 引用业务检查已实现 |
| 文件保护 | 本次核对的 86 个文件前后哈希一致 | 包含业务源码、分块快照、SQLite、Qdrant 数据文件、题集及指定 D4 报告；不是全项目逐文件验收 |
| 模型/API | embedding 0 次、聊天 0 次、网络 0 次 | 无本次 tokens 或答案准确率可统计 |

正式范围：

| 论文 | paper_id | parse_revision | ready chunk 数 |
|---|---|---|---:|
| RAG | `arxiv_2005.11401v4` | `r_269ac0cb1263292d` | 385 |
| ReAct | `arxiv_2210.03629v3` | `r_22af23d03fcb87a8` | 480 |
| Reflexion | `arxiv_2303.11366v4` | `r_d7736b29a2d8b39e` | 323 |

本次直接执行的命令：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready
$LASTEXITCODE
```

这条命令不读取 `.env`、不打开 Qdrant、不写查询报告。后续配置预检另外调用了现有配置加载函数：读取 `.env` 仅为本地检查，保存时只取模型、公开地址与超时等非敏感字段，未保存密钥。

预检第一次把存储层内部的计数别名误当成公开返回字段，提前退出，未写报告或发请求。已改为从公开 `list_versions()` 获取期望 chunk 数，随后检查通过；两次尝试均在机器记录中保留。

## 2. 课程学到这里，怎样对应当前代码

建议使用者按下面路径用约 25 分钟阅读，再用本节例子解释自己的实现。本次已完成材料整理，但没有替使用者记录学习耗时或“已经掌握”。

| 内容 | 本地课程位置 | 在项目里怎样落实 |
|---|---|---|
| 检索、增强、生成 | [第八章 8.3.1](</D:/course/hello-agents-study/docs/chapter8/第八章 记忆与检索.md:1093>) | D4 找候选；D5 把实际证据放进提示词，然后生成草稿 |
| 数据准备与查询生成 | [第八章 8.3.2](</D:/course/hello-agents-study/docs/chapter8/第八章 记忆与检索.md:1120>) | 正文解析/分块/向量化已经完成，每次问答复用它们 |
| RAG 是职责清楚的 pipeline | [第八章 8.3.4](</D:/course/hello-agents-study/docs/chapter8/第八章 记忆与检索.md:1185>) | 检索、上下文、生成、引用检查分别处理，外围流程连接起来 |
| 能运行还需要评价质量 | [第十二章 12.1.1](</D:/course/hello-agents-study/docs/chapter12/第十二章 智能体性能评估.md:46>) | JSON 合法、引用定位、语义支持和回答完成率分别判定 |
| 质量、效率与鲁棒性 | [第十二章 12.1.2](</D:/course/hello-agents-study/docs/chapter12/第十二章 智能体性能评估.md:82>) | 同时保存回答质量、请求/耗时与失败状态 |

课程里的高级检索、长期记忆和通用评测工具是其他实现示例。当前 D5 沿用项目的一轮原问题检索与严格索引契约；教程中切换模型、维度兜底或性能提升的示例不能当成本项目已验证结论。

## 3. 可直接复用的接口清单

| 接口 | 输入与输出 | 使用边界 |
|---|---|---|
| [load_current_profile()](/D:/course/paper-research-assistant/scripts/search_evidence.py:29) | 返回与固定清单一致的完整 profile | 仅读文件，不加载密钥，不发请求 |
| [load_llm_settings()](/D:/course/paper-research-assistant/paper_assistant/config.py:68) | 返回已有 `LLMSettings` | 只加载/校验配置，不保证服务仍可用；不整体序列化设置对象 |
| [EvidenceSearcher](/D:/course/paper-research-assistant/paper_assistant/search.py:53) | 接收 store、vectors、embedding settings、profile，可注入 embedder | 调用者打开并关闭资源；不能缺库时创建空库来查询 |
| [search_evidence()](/D:/course/paper-research-assistant/paper_assistant/search.py:208) | 问题、完整版本配对、top-k → 候选字典 | 正常为 `success/no_hits`；故障抛 `SearchError` |
| [PaperStore.get_chunk()](/D:/course/paper-research-assistant/paper_assistant/storage.py:499) | chunk ID → 含原文/来源的字典，或 `None` | 只读回查，损坏/来源不一致会报错 |
| [EvidenceRef](/D:/course/paper-research-assistant/paper_assistant/schemas.py:38) | `chunk_id/paper_id/parse_revision/pdf_page` | 只检查结构，不能独立确认存在性或语义支持 |
| [Claim](/D:/course/paper-research-assistant/paper_assistant/schemas.py:52) | 一条 `claim` 和非空 `citation_ids` | 事实结论必须有引用 ID，ID 仍需业务检查 |
| [AnswerDraft](/D:/course/paper-research-assistant/paper_assistant/schemas.py:62) | 模型草稿为回答或证据不足 | 不允许额外字段、未知状态或矛盾内容 |
| [invoke_llm()](/D:/course/paper-research-assistant/paper_assistant/llm_client.py:8) | messages + 可选设置 → 文本 | 当前适合 D2 连通入口，B 需补完整响应调用 |

检索的固定调用约定：

```python
result = searcher.search_evidence(
    query=question,
    selected_versions=[("arxiv_2005.11401v4", "r_269ac0cb1263292d")],
    top_k=5,
)
```

这只是接入示例，本次没有执行。多篇继续使用完整配对列表，不能把论文列表和版本列表分别过滤形成交叉范围。底层允许 top-k 为 1–20，D5 首轮固定 5。

后续直接使用 `result["results"]` 中已回 SQLite 的原文和来源；保留 `query`、`selected_versions`、`index_profile_id`、`statistics`。分数是相似度排序依据，PDF 页码是从 1 开始的文件页序。

## 4. 四个关键判断，结合实际材料解释

### 4.1 为什么检到了，还可能没有答案

检索按相似度找候选，不会证明候选包含完整答案。例如 ReAct D2-003 问“摘要列了哪些基准”，D4 的正文候选包含相同事实，但正式 top-5 没有摘要依据。位置限定属于题目要求，不能仅把相关正文换个说法就当摘要回答。

本次离线回查确认摘要 `arxiv_2210.03629v3_r_22af23d03fcb87a8_p1_c6` 真实存在，却不在 E 原请求的 top-5。没有重新向量化，也没有把它送入生成器。F 新实验的 rank 9 继续保留为独立测量。

因此，有候选且证据不足不是 `no_hits`；D5 应明确说“本轮候选没有足够的摘要依据”。该题仍是可回答题，若因此拒答，问答完成率仍计未完成。

### 4.2 为什么真实 ID 仍可能是无效引用

ID 在全库存在，只能说明可以找到这条记录。它还可能来自未选论文/版本，或是本轮检到了但因预算没有实际展示的 chunk。引用允许集合必须从真正展示的证据建立。

ReAct 摘要就是“真实存在但不在原 top-5”的具体例子。已知它在哪，不代表可以把它偷偷补进原检索结果。后续模型也不能通过猜 ID 扩展允许集合。

### 4.3 为什么结构通过不能证明原文支持结论

本次在现有 `AnswerDraft` 上执行五种演示，全部符合已有约定：

| 输入 | 实际结构检查结果 |
|---|---|
| 一条结论引用 `d5_task_a_demo_nonexistent` | 接受：字符串格式合法 |
| `answered` 却没有结论 | 拒绝 |
| `insufficient_evidence` 无结论、有原因 | 接受 |
| `insufficient_evidence` 仍携带事实结论 | 拒绝 |
| 模型草稿自行声明 `tool_error` | 拒绝 |

同时，用 `get_chunk()` 回查演示 ID 得到 `None`。这证明结构校验和存在性是两步；本次只演示现有能力，引用业务校验仍在 D。

即使 ID 真实、范围正确，也可能出现“原文只是图标题，结论却声称图里某项实验机制”的情况。定位检查不能验证这种语义跳跃，仍须逐条对照实际展示正文。界面应说明引用可回查，不显示“答案真实性已验证”。

### 4.4 为什么证据不足与系统失败要分开

正常查完但无依据，是这次回答材料不足；鉴权、服务、库或来源失败，则连正常检索/生成都没有完成。把故障统一改成“论文未提到”，既误导使用者，也让评测把系统故障错当正确拒答。

`SearchError` 应保留安全消息、失败阶段与已有统计，由程序转为错误终态。没有候选或模型判断证据不足，分别记录原因后进入正常不足状态。

## 5. 本次固定的回答与状态规则

| 层次 | 规则 | 实现状态 |
|---|---|---|
| 模型草稿 | 只返回 `answered` 或 `insufficient_evidence` | 现有 schema 已定义；生成链路待 C |
| 回答内容 | `answered` 至少一条结论，每条有非空引用 | 结构已检查，支持度待逐题评价 |
| 不足内容 | claims 为空，reason 非空 | 现有 schema 已定义 |
| 引用来源 | 存在、属于所选完整配对、实际展示、页码与哈希一致 | 待 D 的业务校验 |
| 引用定位 | 四字段、原文与 PDF 来源由程序从事实库补齐 | 待 D |
| 实际证据 | 按 rank 去重，完整 chunk 累计最多 8000 字符，超出停止 | 待 C，并保存真正的 shown_text/messages |
| 题目标注 | 期望答案/证据、answerable 不进入检索或提示词 | 运行与评分分开，待 F 验证 |

外围终态约定：

| 状态 | 何时使用 | 产生者 |
|---|---|---|
| `answered` | 草稿与引用检查通过 | 模型给草稿，程序批准发布 |
| `insufficient_evidence` | 正常无候选，或候选不足以支持题目 | 无候选由程序处理；不足可由模型给草稿 |
| `tool_error` | 配置、检索、服务或数据/来源故障 | 程序 |
| `invalid_output` | 格式/引用修复后仍未通过 | 程序 |
| `budget_exceeded` | 请求数或阶段检查达到截止预算 | 程序 |

后续 CLI 退出码约定：正常业务终态 0；系统/输出/预算失败 1；参数用法错误 2。当前问答 CLI 尚未实现，不把检索命令退出码当作已经存在的问答行为。

## 6. 实际配置与准备采用的参数

本次通过配置加载器确认，当前聊天配置是 **DeepSeek / `deepseek-flash`**，请求超时 30 秒；不是凭 `.env.example` 推测。只做本地检查，服务连通及完整 JSON 输出仍需 B 验证。

| 项目 | 当前观察 | D5 准备采用 |
|---|---|---|
| 聊天模型 | `deepseek-flash` | 沿用当前模型 |
| 输出上限 | 旧薄层固定 128 tokens | 1200，真实样例再核对 |
| 温度 | HelloAgents 默认 0.7 | 显式 0.2 |
| 响应 | 仅文本 | content、finish_reason、实际 usage、耗时 |
| SDK 隐式重试 | OpenAI 默认 2 次 | 显式关闭，项目代码统一执行 |
| 聊天请求预算 | 旧 wrapper 次数不等于 HTTP 次数 | 正常 1 次，总最多 3 次尝试 |
| 修复/重试 | 尚无 D5 控制层 | 最多一次格式或引用修复、一次可重试网络故障重试，均计总预算 |
| 请求超时 | LLM 配置 30 秒；embedding 固定 HTTP 30 秒 | 聊天超时按剩余整轮预算收紧 |
| 整轮截止预算 | 没有问答外围计时器 | 起点 120 秒，阶段间检查；严格墙钟中止未验证 |

当前安装版本：hello-agents 0.1.1、openai 3.19.2、pydantic 2.13.5、httpx 0.28.1、qdrant-client 1.19.1，已保存在配置记录中。旧 `invoke()` 丢弃 usage/finish_reason，给 HelloAgents 构造器增加 `max_retries=0` 不会自动改变底层客户端；B 需要在项目薄层明确控制，不能只改参数名字。

索引继续是 `ep_cbf0f6caa97b962a`，百炼 `qwen3.7-text-embedding`、1024 维、cosine、`identity-text-v1`。不改变分块或索引身份来推进问答。

## 7. 首轮具体跑哪一道题

`baseline_config.json` 已保存第一题的实际输入，不包含期望要点或期望引文：

```text
case_id: D2-001
question: What forms of parametric and non-parametric memory are combined in the RAG model?
paper_id: arxiv_2005.11401v4
parse_revision: r_269ac0cb1263292d
top_k: 5
execution_status: not_started
```

先在 B 完成聊天响应记录，在 C/D 接通证据与引用检查，再做真实问答。完整首轮记录需要保存检索候选、实际展示证据、messages、原始草稿、引用校验、最终状态和实际用量；本次没有提前调用它或写问答结果。

## 8. A 的完成范围与下一步

- [x] 指定课程要点已阅读，形成与项目对应的学习说明。
- [x] 现有接口、草稿结构和引用能力边界已核对。
- [x] 三篇 ready 范围与本机向量配置一致。
- [x] D4 源码绑定仍匹配，指定正式文件本次未改变。
- [x] 回答规则、程序终态、评测边界与首轮参数已保存。
- [x] 当前配置与尚未实现的目标参数分别记录。

使用者理解可以通过复述本指南第四节的四个例子自检；当前记录为 `not_assessed`，不冒充人工确认。A 的工程准备已具备进入 B 的条件。

**B 的第一步：在 `llm_client.py` 保留现有 D2 入口，新增完整响应的问答调用函数；显式设置输出长度、温度和 SDK 重试，记录每次请求尝试、usage、finish_reason 与脱敏错误。** 这个文件未被本次核对的 D4 源码记录绑定；其他已绑定公共文件继续复用，确需改动时保留旧记录并重新核对受影响检查。

本地 Qdrant 同目录只能由一个客户端拥有，后续调用失败也要关闭。A 没有打开 Qdrant 客户端，也没有运行会覆盖 D4 当前报告的 `validate_d4`。
