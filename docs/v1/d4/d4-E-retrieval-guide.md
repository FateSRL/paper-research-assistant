# D4 任务 E：把问题接到证据检索上

任务 D 已把三篇论文的 1188 个正文 chunk 变成向量并保存。任务 E 要做的是：你输入问题，明确选择论文和处理版本，程序从这些范围里找出最相似的候选，再把对应原文、页码和 ID 展示出来。

这一阶段返回的是**候选证据**。它调用 embedding 服务把问题变成向量，不调用聊天模型生成答案；命中第一名也需要阅读原文才能判断是否包含所问的依据。

实际执行更新（2026-10-01）：任务 E 已实现并跑通，20 项离线检查通过。三篇各一道开发题，每题返回五条且只调用一次问题向量，共 3 次请求、实际 103 tokens；没有 LLM 请求。RAG D2-001 和 Reflexion D2-005 的标注引文位于 rank 1，ReAct D2-003 的 top-5 未召回标注的摘要第 1 页。这个召回问题已在 F 对照与诊断报告中真实保留，不能用三次命令成功代替三题事实依据都命中。SQLite 四表、Qdrant 文件和 39 个原输入/快照保持不变，见 [真实查询验证](/D:/course/paper-research-assistant/artifacts/d4/retrieval_validation.json)。用户于 2026-10-02 明确确认本次 F 候选/PDF 对照及 B 抽样，记录在 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)；G 正式验收已通过，D4 完成并保留已知问题，D5 尚未实现。

## 1. 先理解整条流程

```text
用户问题 + 明确的论文/处理版本
              ↓
检查参数、索引配置和 ready 状态
              ↓
用文档入库时的相同配置得到问题向量
              ↓
Qdrant 在所选版本范围内比较 cosine 相似度
              ↓
得到前 k 条 point：分数 + chunk 身份
              ↓
按 chunk_id 回 SQLite，核对来源字段和哈希
              ↓
展示候选原文、PDF 页序、版本、ID 和分数
```

每一层回答的问题不同：embedding 模型负责把文字表示成数字；Qdrant 负责按数字相似程度找候选；SQLite 负责提供可核对的原文；最后由人阅读证据并对照 PDF。

例如，问题是“RAG 使用哪两种知识存储？”。系统会比较问题向量与所选 RAG 正文的向量，返回几个可能讲到 parametric、non-parametric memory 的片段。它不会仅凭分数自动给出“答案正确”的结论。

## 2. 第一步：明确要从哪些论文、哪些版本里找

本项目有三个不同层次的身份，不能只看其中一项：

| 身份 | 当前例子 | 含义 |
|---|---|---|
| 论文 ID | `arxiv_2005.11401v4` | 指向作者发布的这一版论文，`v4` 是 arXiv 版本 |
| 处理版本 | `r_269ac0cb1263292d` | 指向本项目某一套 PDF、解析、过滤和分块输入 |
| 索引配置 ID | `ep_cbf0f6caa97b962a` | 指向 embedding 模型、维度、接口输入方式和距离等配置 |

三篇当前已入库的处理版本如下：

| 论文 | `paper_id` | `parse_revision` | chunk 数 |
|---|---|---|---:|
| RAG | `arxiv_2005.11401v4` | `r_269ac0cb1263292d` | 385 |
| ReAct | `arxiv_2210.03629v3` | `r_22af23d03fcb87a8` | 480 |
| Reflexion | `arxiv_2303.11366v4` | `r_d7736b29a2d8b39e` | 323 |

**为什么必须带处理版本：**以后改了分块参数，同一篇论文可以同时保留多个处理版本。它们的 chunk ID、边界和文字范围可能不同。查询和引用都要明确采用哪一个版本，才能按原 ID 复现证据。

多篇选择以完整配对表示：`(paper_id, parse_revision)`。例如选 `(RAG, r1)` 和 `(ReAct, r2)`，允许的就是这两个组合。把论文名单和版本名单分别筛选，会错误地放行 `(RAG, r2)`；源码中的版本过滤使用完整配对来避免这个问题。

## 3. 第二步：确认所选版本确实可以检索

SQLite 的 `index_imports` 保存每个“论文 + 处理版本 + 索引配置”的导入状态：

| 状态 | 含义 | 是否允许正常检索 |
|---|---|---|
| `pending` | 尚在构建，可能只完成一部分 | 否 |
| `failed` | 导入发生异常，保留了错误摘要 | 否 |
| `ready` | 任务 D 已完整核对该版本 | 是，查询仍需核对配置与返回证据 |

**为什么不能仅检查 Qdrant 有没有数据：**一次导入可能在第十批失败，库中已有点，论文却没有完整入库。让这份不完整索引参与查询，会把没有召回的内容误认为论文没有提到。

核心代码的 `EvidenceSearcher._ready_filter()` 读取 SQLite 状态。如果选择了不存在的论文、处理版本，或当前索引配置下尚未 ready 的版本，就应明确报错，并在问题向量化之前停止，避免错误范围仍触发模型请求。它还比较当前所选 Qdrant 范围的实际点数与 SQLite 登记的完整数量；发现已缺失数据时，也不会继续调用模型。

检索入口读取事实库，不把 pending/failed 自动改成 ready。修复导入需要使用任务 D 的构建入口和完整性检查。

## 4. 第三步：核对问题使用的向量配置

当前正式索引采用：

```text
backend:       dashscope
model:         qwen3.7-text-embedding
dimension:     1024
input_mode:    openai-compatible-default
preprocessing: identity-text-v1
distance:      cosine
profile:       ep_cbf0f6caa97b962a
```

`1024` 表示一段文字被表示成 1024 个数字，不是原文字数，也不是 token 数。问题与文档向量需要在同一空间中才能比较，因此使用相同模型、维度、接口输入方式和预处理。

**为什么维度相同还不够：**两个不同模型都可以返回 1024 个数，但每个数字所表示的含义未必相同。就像两个坐标系统都有两个坐标轴，也不能直接把它们的坐标混在一起算距离。程序核对整个索引配置身份，而不只检查列表长度。

D4 沿用已验证的兼容接口默认输入方式，正文与问题都原样送入；不会在查询时临时加入另一套 `query`/`document` 指令。CLI 的 `load_current_profile()` 核对当前指针与固定配置清单，核心的 `_check_configuration()` 再核对实际配置。以后要变更模型或输入预处理，应创建新的索引配置并重新生成对应的文档向量。

API 密钥用于向服务发请求，不进入索引身份、证据输出或报告。密钥轮换本身不改变向量模型配置。

## 5. 第四步：把问题变成一个向量

问题是文字，Qdrant 保存的是数字列表。需要先调用已有 `embed_texts()`，把本次问题得到的一个向量交给 Qdrant。

**为什么问题也要向量化：**普通字符串和数字向量无法直接进行 cosine 比较。embedding 模型让问题与正文都有可比较的数字表示，从而能找到意思相近、用词不完全相同的段落。

返回时仍检查数量、输入顺序、维度、有限数值和非零方向。如果服务失败、返回向量长度错误，或出现 NaN/无限值，就应作为查询失败报告，不能拿补零或截断后的向量继续检索。

正文的 1188 个向量已经在任务 D 生成。查询时只需要得到本次问题的向量，不需要重新给整篇论文向量化。当前 E 不新增问题向量缓存：每次正常查询调用一次 embedding API，即使你重复输入同一个问题也会再次调用。单纯列出 ready 版本不调用 API。

## 6. 第五步：先限定版本，再进行相似度检索

Qdrant 的 `query_points()` 接收问题向量、版本过滤条件和 `top_k`。版本条件限定允许的完整论文/处理版本配对，同时限定当前索引配置。

**为什么先过滤：**如果先在全部论文中取前五条，再从结果里删掉其他论文，就可能删到零条，却错过所选论文中本来应该返回的候选。把范围交给数据库作为查询条件，能直接在允许的范围内排序。

默认 `top_k=5` 表示最多返回五条候选。它不是保证“有五个答案”，也不是每篇返回五条；选择多篇时，排序在整个已选范围中进行。一篇比较相关的论文可能占据全部五个位置。

cosine 分数反映向量方向的相似程度，通常越大越相似。它不是答案正确概率，不表示“0.7 就有 70% 的正确率”，也不能凭一个通用阈值保证证据可靠。

几段相似文字可能只是背景介绍，未回答问题；一句很短的关键词也可能分数较高，但缺少完整上下文。因此必须阅读候选的实际原文。当前 E 不把相似度高自动解释为论文支持某个结论。

## 7. 第六步：按 chunk ID 回查原文并再核对一次

Qdrant point 保存向量及 payload，payload 提供 `chunk_id`、论文、处理版本、PDF 页序、文本哈希、PDF 哈希和索引配置。正文以 SQLite 中保存的不可变 chunk 为事实来源。

核心的 `EvidenceSearcher._read_hit()` 根据命中的 `chunk_id` 调用 `PaperStore.get_chunk()`，读取原文，并核对：

1. point 的 UUID 是否对应当前配置与该 chunk ID。
2. 论文和处理版本是否在本次允许的完整配对中。
3. PDF 页序、文本 SHA-256、PDF SHA-256 是否与 SQLite 一致。
4. 索引配置是否与本次问题使用的配置一致。
5. 原文记录是否真实存在，且其文本/来源通过事实库内部校验。

**为什么不能直接相信 payload：**即使数据库返回了一个分数较高的点，也可能存在人工改动、错写来源或串版本等问题。取回原文时重新核对，可避免“向量对应 A，引用却指向 B”的错误。

已知异常应明确失败，不能悄悄丢弃错误点，再把剩下的列表标成完全正常。没有匹配候选是正常查询结果；服务失败或来源损坏是错误，它们需要不同的状态和退出码。

`pdf_page` 是 PDF 文件从第一页开始计数的页序，从 1 开始。它不一定等于页面里印刷的页码。打开本地 PDF 时按这个文件页序定位。

## 8. 输出应该怎样阅读

先看本次选择的论文、处理版本和索引配置，确认检索范围符合意图。再按排名查看候选的分数、chunk ID、页码和原文。

分数适合用来了解本次排序，不能替代原文。判断是否支持问题时，可以按下面的顺序：

1. 这段文字是否明确在谈问题中的对象？
2. 它是否给出所需事实，还是仅出现了相似词？
3. 一句话是否被分块边界切开，需要看对应 PDF 的上下文？
4. 该 PDF 页序里是否确实能找到相同依据？

短片段、断词、被过滤的图中文字或公式会影响召回。任务 E 记录和展示实际候选，后续根据观察再决定是否调整分块或增加带来源的上下文。它不会直接把待人工确认的恢复材料混入正式正文。

## 9. main 函数是命令入口

`scripts/search_evidence.py` 的 `main()` 负责解析参数、读取配置、选择版本、打开存储、调用检索核心、展示结果和保存本次运行报告。具体检索步骤由模块中的函数完成。

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

执行 `python -m scripts.search_evidence` 时，这段代码会调用 `main()`。它不是只检查字符串格式，也不是可以省略的示例；没有入口调用，定义好的函数不会自动执行整条查询流程。

用 `main()` 返回退出码，可以让 PowerShell 的 `$LASTEXITCODE` 区分运行成功与错误：`0` 表示成功，包括正常空结果 `no_hits`；`1` 表示配置、服务或数据等操作失败；`2` 表示参数用法错误，例如缺少处理版本或 `top-k` 超出 CLI 的 1 至 20 范围。之后界面或 D5 可以直接调用检索模块，而不必复制 CLI 中打印结果的代码。

## 10. 实际 PowerShell 操作步骤

直接使用项目虚拟环境中的 Python，不要求先激活 `.venv`。每条使用 Qdrant 的命令都等上一条结束后再执行，因为同一份本地目录一次只能由一个客户端持有。

### 10.1 进入项目并离线列出可用版本

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready
$LASTEXITCODE
```

`--list-ready` 用于确认当前索引配置下有哪些已完成导入的论文和处理版本。它不读取 `.env`，不发网络请求，不生成问题向量；不需要为了看版本就调用模型。

`-X utf8` 让 Python 按 UTF-8 处理文本，减少 Windows 下中文输入、输出和文件编码的问题。`--list-ready` 会提供可明确复制的版本，查询不会替你猜最新版本，也不会在省略范围时默认搜全库。

### 10.2 查询一篇论文的一个明确处理版本

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d --query 'RAG 使用哪两种知识存储？'
$LASTEXITCODE
```

三个必需参数的含义是：

| 参数 | 用处 |
|---|---|
| `--paper-id` | 指定作者发布的论文版本 |
| `--parse-revision` | 指定项目内的处理版本 |
| `--query` | 你这次要检索的问题 |

单篇模式中的前两个参数必须同时明确提供。代码会先核对它们确实配对存在、并在当前配置下 ready；不会仅按论文名选择一个碰巧可用的版本。

本命令正常执行会调用一次问题 embedding API，然后显示最多五条候选原文。它会使用 `.env` 中已有的 embedding 配置，但不要求提供聊天模型配置，也不生成聊天模型答案。

另外两篇可以这样查：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2210.03629v3 --parse-revision r_22af23d03fcb87a8 --query 'ReAct 为什么要把推理与行动结合起来？'
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2303.11366v4 --parse-revision r_d7736b29a2d8b39e --query 'Reflexion 怎样利用反馈改进下一次尝试？'
```

这些是便于体验检索的自然语言问题；F 的正式事实题抽查采用 `eval/dev.jsonl` 中的题目和预期依据。

### 10.3 查询多篇，逐项写出完整配对

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --version arxiv_2005.11401v4 r_269ac0cb1263292d --version arxiv_2210.03629v3 r_22af23d03fcb87a8 --query '这些方法怎样利用模型外部的信息？' --top-k 5
```

每个 `--version` 后面跟两个值：论文 ID 和它自己的处理版本。这个参数可以重复。多篇模式与单篇的 `--paper-id` / `--parse-revision` 互斥，选一种表达方式即可。

`--top-k` 默认是 5，允许 1 至 20；例如改成 `--top-k 3` 会最多返回三条。多篇时这个上限是所有选定版本的总候选数，不是每篇各三条或各五条。

### 10.4 需要机器读取时输出 JSON

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d --query 'RAG 使用哪两种知识存储？' --json
```

`--json` 让标准输出采用 JSON，便于之后由其他脚本或界面读取。候选正文仍在结构化结果中，不需要从排版后的终端文本反向提取字段。

这一命令也是一次真正的查询，会调用一次 embedding API；它不是先前结果的离线格式转换。仅想查看上次保存的结果时，直接打开报告文件即可。

## 11. 源码、数据和报告分别放哪里

| 位置 | 用途 |
|---|---|
| [paper_assistant/search.py](/D:/course/paper-research-assistant/paper_assistant/search.py) | 参数/状态/配置检查、问题向量化、候选回查与核对 |
| [paper_assistant/retrieval.py](/D:/course/paper-research-assistant/paper_assistant/retrieval.py) | Qdrant 持久化、完整配对过滤和向量检查 |
| [paper_assistant/storage.py](/D:/course/paper-research-assistant/paper_assistant/storage.py) | SQLite 原文、来源及导入状态 |
| [scripts/search_evidence.py](/D:/course/paper-research-assistant/scripts/search_evidence.py) | CLI 的参数、组织执行、输出和报告 |
| `data/index/papers.sqlite3` | 原文事实库，不是一次运行报告 |
| `data/index/qdrant/` | 正式磁盘向量库 |
| `data/index/profiles/` 与 `current_profile.json` | 已保存的向量配置与当前入口 |
| `data/index/embeddings/` | D 生成的文档向量缓存，后续重复入库继续复用 |
| [artifacts/d4/retrieval_result.json](/D:/course/paper-research-assistant/artifacts/d4/retrieval_result.json) | 最近一次查询的结构化结果、范围与请求统计 |
| [artifacts/d4/retrieval_result.md](/D:/course/paper-research-assistant/artifacts/d4/retrieval_result.md) | 最近一次查询的便于阅读版本 |
| [artifacts/d4/retrieval_validation.json](/D:/course/paper-research-assistant/artifacts/d4/retrieval_validation.json) | E 的实际查询、范围和来源检查汇总 |
| `archive/run_logs/d4/retrieval_<时间>.json` | 每次查询的历史结果，避免最新报告覆盖后失去记录 |

当前结果文件会随着新查询更新，想回看某一次就到历史日志找该次时间。历史里有问题和候选原文，但不保存 API 密钥。运行结果还记录本次问题向量请求数、供应商返回的实际 token 用量及耗时；用量缺失时保留缺失，不按字符数伪造精确 token 数。

纯参数错误在真正查询之前由 `argparse` 停止，不会更新最新结果文件；此时不要把旧报告误当成这次命令的结果。`--list-ready` 同样只展示列表，不写查询结果报告。

文档向量缓存是正式可复用数据，不是过期报告；E 的问题向量没有另外落盘缓存。不要因为查询已经成功就删除文档缓存、SQLite 或 Qdrant 目录，它们仍承担后续重跑、回查和 D5 的检索工作。

## 12. 任务 F 为什么还要人工对照 PDF

F 的 AI 对照已经完成：三题、十五个真实候选和十三个完整 PDF 页；用户于 2026-10-02 明确确认。RAG/Reflexion 完整依据在 rank 1，ReAct 同事实在正文但摘要漏出正式 top-5。独立新实验测得完整摘要 rank 9，额外 1 请求 35 tokens，与 E 原 3 请求 103 tokens 分开记录。结果见 [复核报告](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)，具体步骤见 [任务 F 说明](/D:/course/paper-research-assistant/docs/v1/d4/d4-F-retrieval-review-guide.md)。G 正式验收已通过，D4 完成并保留已知问题，D5 待实现；见 [D4 验收与 D5 交接](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)。E 原结果没有被新诊断覆盖。

E 验证的是检索流程、范围过滤和来源一致性。F 要进一步检查**候选对真实事实题有没有用**：从 `eval/dev.jsonl` 每篇选至少一道正常事实题，保存实际排名和候选，打开对应 PDF 页，核对期望依据是否在命中的原文中。

人工记录至少包括：问题 ID、明确的论文/处理版本、命中的 chunk ID、文件页序、期望依据的名次、是否包含完整事实、发现的问题和复核人状态。若未命中或上下文不足，要真实记录原因，不把“程序退出码 0”当成检索质量通过。

本阶段没有聊天模型答案，因此不能把候选召回观察称为问答准确率。D5 再将已提供的证据交给模型生成带引用的答案，并检查引用是否来自本轮实际证据。
