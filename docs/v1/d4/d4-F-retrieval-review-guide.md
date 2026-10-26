# D4 任务 F：读懂候选证据，并与原 PDF 对照

任务 F 要回答一个具体问题：**检索系统找回来的这段原文，真的能支持我们要回答的事实吗？**

任务 E 已经跑通“问题 → 向量 → 检索 → 原文回查”，三篇各一道开发题都返回了五条候选。任务 F 继续阅读这些已经保存的结果，核对原 PDF 中的文字、位置、事实范围和分块边界。为了复核已有候选，无需再发一遍问题向量请求。

本次已经完成三题、十五条候选的 AI 文字核对及十三个完整原 PDF 页的视觉对照。用户于 2026-10-02 明确确认“F 已核对”，同时确认 B 三十条分块抽样；具体范围记录在 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)，没有继承题集上一次的人工通过。ReAct 独立新实验诊断和当前结论以 [任务 F 正式报告](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md) 为准，结构化记录在 [retrieval_review.json](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.json)。G 正式验收已通过，D4 完成并保留已知问题，D5 待实现；见 [交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)。

## 1. 为什么程序运行成功以后，还要做 F

程序退出码为 `0`，可以说明本次执行完成；五条候选的来源和哈希核对通过，可以说明取回的是记录中的那段原文。两者都没有直接证明原文能回答问题。

例如，问题问“ReAct 的摘要提到了哪两个问答与事实核验基准？”。正文也可能出现 HotpotQA 和 Fever，参考文献也可能出现 question answering 和 verification。它们与问题有相似的词，甚至能得到较高分数；但参考文献尾句没有完整事实，正文也不能单独证明“摘要提到了”。

E 与 F 的职责可以这样对照：

| 阶段 | 主要检查 | 成功能说明什么 |
|---|---|---|
| E：检索流程 | 参数、模型配置、ready 状态、论文/版本过滤、返回来源 | 能从指定范围找出候选，并按 ID 取回可信原文 |
| F：证据复核 | 候选事实是否完整、是否符合题目来源条件、是否能在 PDF 对上 | 能指出哪些候选可支撑问题，哪些只相关，哪些缺少依据 |

embedding 相似度是检索排序的依据，不能替代上述阅读。`score=0.7` 也不表示有 70% 的答对概率。

## 2. 这次复核的输入是什么

这次采用任务 E 已保存的三道正常事实题。题目和期望事实来自 [开发集 eval/dev.jsonl](/D:/course/paper-research-assistant/eval/dev.jsonl)，E 的实际查询及五条候选索引见 [retrieval_validation.json](/D:/course/paper-research-assistant/artifacts/d4/retrieval_validation.json)。

| 题目 ID | 论文 | 处理版本 | 问什么 |
|---|---|---|---|
| `D2-001` | `arxiv_2005.11401v4`，RAG | `r_269ac0cb1263292d` | 参数化与非参数化记忆各由什么构成 |
| `D2-003` | `arxiv_2210.03629v3`，ReAct | `r_22af23d03fcb87a8` | 摘要提到的问答与事实核验基准 |
| `D2-005` | `arxiv_2303.11366v4`，Reflexion | `r_d7736b29a2d8b39e` | 是否更新权重，以及如何利用反馈和记忆 |

每个题目都有自己的历史结果文件，其中保存原始问题、当时的排名、分数、完整 chunk 原文和来源字段：

- [RAG 的 E 查询结果](/D:/course/paper-research-assistant/archive/run_logs/d4/retrieval_20261001_132621_898359.json)
- [ReAct 的 E 查询结果](/D:/course/paper-research-assistant/archive/run_logs/d4/retrieval_20261001_132627_532464.json)
- [Reflexion 的 E 查询结果](/D:/course/paper-research-assistant/archive/run_logs/d4/retrieval_20261001_132632_773919.json)

`retrieval_result.json` 是最近一次查询的结果，之后再次查询会更新它。复核这三题时使用上面固定的历史文件，才不会把下一次查询与本次的排名混在一起。

## 3. 每条候选按什么顺序核对

### 第一步：把问题拆成必须回答的事实

先看 `question` 和 `expected_points`，不要先被检索分数带着走。

RAG 这题需要两点：参数化记忆是预训练 seq2seq 模型；非参数化记忆是 Wikipedia 的稠密向量索引，由预训练神经检索器访问。只出现“parametric and non-parametric memory”这几个词，不足以回答它们分别是什么。

Reflexion 这题需要三点：不通过更新模型权重来强化智能体；对任务反馈进行语言反思；把反思文本放入 episodic memory buffer，以指导后续尝试。只说明“使用反馈”并没有覆盖完整机制。

ReAct 这题需要 HotpotQA 对应问答、Fever 对应事实核验，并且要证明它们确实出现在摘要。**这里的“摘要”是问题本身的限制，不能忽略。**

### 第二步：核对候选身份和原文

根据 `chunk_id` 回 SQLite 读取保存的原文，再与历史结果中的 `text`、论文 ID、处理版本、PDF 页序、文本哈希和 PDF 哈希比较。

这一步解决的是“当前看到的文字，到底是不是这个 ID 的真实记录”。本次十五条候选全部能与 SQLite 保存的原始字段一致对应，三份 PDF 的哈希也与记录相符。

如果你只想查看某条已经入库的原文，可以使用只读回查命令：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.query_chunk --chunk-id arxiv_2005.11401v4_r_269ac0cb1263292d_p1_c9
```

这条命令查询 SQLite，不调用 embedding 或聊天模型，也不重新构建索引。其他候选的完整 ID 从正式报告或原始历史结果直接复制。

### 第三步：打开正确 PDF 的正确文件页

`pdf_page` 是 PDF 文件从第一页起计数的页序，从 `1` 开始。请按阅读器的文件页数定位，而不是直接按正文印刷页码定位。

检查时使用清单对应的固定 PDF 版本。论文换成另一个 arXiv 版本后，文字和页序可能变动，此时即使标题相同也不能拿来验证当前 chunk。

本次文字交叉核对采用对应原 PDF 页的原生文本：只统一空白后比较，不自动改写原句、修正词义或补全句尾。十五条候选都能在自己的来源页中找到。视觉复核再检查实际排版、段落范围和上下文，相关页截图在 [retrieval_evidence 目录](/D:/course/paper-research-assistant/artifacts/d4/retrieval_evidence/)。

### 第四步：分别判断四件事

| 判据 | 你实际要判断什么 | 常见误判 |
|---|---|---|
| 事实覆盖 | 当前片段明确支持几个必要事实 | 看到相似关键词就认为答案完整 |
| 来源限定 | 是否来自题目要求的章节、实验或文档位置 | 正文有同样事实，就当作摘要的依据 |
| 原文完整 | 是否有可独立理解的句子，句尾或主语是否缺失 | 用前后未返回的段落，替当前 chunk 补全意义 |
| 证据边界 | 准备得出的结论是否只使用已提供的这段文字 | 看过整页后，把整页所有信息都算进这条 chunk |

看 PDF 上下文有助于确认文字来自哪里，也能发现截断问题。但阅读整页不会自动把整页内容加入本轮返回的证据。如果 D5 要使用邻接上下文，应明确取回它、记录新证据身份和来源，再交给模型。

### 第五步：写下判断与理由

本次将候选分为三类：

- **完整依据**：题目需要的事实在当前片段中明确出现，同时满足问题的来源范围。
- **部分相关**：谈到同一对象或支持部分事实，但有事实缺项、来源条件不符或上下文边界不足。
- **无答案依据**：对这个问题没有可用事实，例如只是一行图标题或参考文献尾句。

“无答案依据”是针对当前问题的判断，不表示这段文字在所有任务中都没有用途，也不表示 PDF 解析错误。

记录至少包括题目 ID、完整 chunk ID、文件页序、原排名、事实覆盖、来源是否满足、缺少什么及复核状态。存在问题时写具体理由，不能只写“感觉不相关”。

## 4. 本次十五条候选分别说明了什么

下面的 `p1_c9` 等是完整 ID 的末尾，方便阅读。完整 ID 由表中论文 ID、处理版本和末尾组成；操作时仍从报告直接复制完整 `chunk_id`。

### RAG：D2-001

问题是：What forms of parametric and non-parametric memory are combined in the RAG model?

| 原排名 | 文件页 / ID 末尾 | 本次判断 | 理由 |
|---:|---|---|---|
| 1 | 第 1 页，`p1_c9` | 完整依据 | 摘要明确给出预训练 seq2seq 模型、Wikipedia 稠密向量索引和预训练神经检索器，覆盖两项事实 |
| 2 | 第 2 页，`p2_c31` | 完整依据 | Introduction 再次给出两类记忆的定义，并解释 DPR 和 BART，可以独立支持题目 |
| 3 | 第 9 页，`p9_c6` | 部分相关 | Section 6 Discussion 讨论混合记忆、效果和替换索引，没有定义两种记忆的具体构成 |
| 4 | 第 2 页，`p2_c30` | 部分相关 | 只说将混合记忆带到 seq2seq 模型，没有给出 Wikipedia 索引及神经检索器等完整定义 |
| 5 | 第 2 页，`p2_c33` | 部分相关 | 介绍混合记忆的实验效果与非参数记忆可替换，没有回答它们各自是什么 |

这题没有限定答案必须来自摘要，所以第 2 页正文也能构成完整依据。它不与题集标注的摘要原句完全相同，但这不会让已经明确支持两项事实的正文失效。

第 1 项整个 chunk 的末尾在摘要下一句中切开；所需两项事实已经完整出现，因此本题的必要依据没有被截断。这里应区分“chunk 有边界问题”和“本题需要的句子不完整”。

### ReAct：D2-003

问题是：Which question-answering and fact-verification benchmarks are named in the paper's abstract?

| 原排名 | 文件页 / ID 末尾 | 本次判断 | 理由 |
|---:|---|---|---|
| 1 | 第 4 页，`p4_c7` | 部分相关：事实完整，来源条件不符 | Section 3.1 Setup 的 Domains 段正确写出 HotPotQA 与 FEVER 的任务类别，但它属于正文 |
| 2 | 第 12 页，`p12_c23` | 无答案依据 | 83 字符的参考条目尾句只出现 fact extraction and verification，当前 chunk 不含 Fever 名称，也不来自摘要 |
| 3 | 第 13 页，`p13_c11` | 无答案依据 | 82 字符的参考条目尾句只出现 open-domain question answering，没有两个目标基准 |
| 4 | 第 11 页，`p11_c25` | 无答案依据 | 127 字符的其他论文参考条目尾片段提到 few-shot open-domain QA，没有给出本题事实或摘要来源 |
| 5 | 第 3 页，`p3_c2` | 部分相关：事实完整，来源条件不符 | Introduction 的实验概述列出 HotPotQA、Fever 及其他任务，前两项事实吻合，但不是摘要 |

本次 top-5 中，两个正文候选能支持“论文使用哪些基准”的事实；它们不能单独证明“摘要提到了哪些基准”。因此严格按原问题判定，没有一项完整满足事实与来源两项条件。

不要把这个结果记录成“模型不知道 HotpotQA/Fever”，也不要为了让结果通过，把题目中的 abstract 删掉。问题要保留原样，原五条结果也保留原排名。

### Reflexion：D2-005

问题是：Does Reflexion improve agents by updating model weights, and what feedback mechanism does it use?

| 原排名 | 文件页 / ID 末尾 | 本次判断 | 理由 |
|---:|---|---|---|
| 1 | 第 1 页，`p1_c12` | 完整依据 | 摘要明确写不更新 weights、语言反馈、对任务反馈反思，并把文本放在 episodic memory buffer 中指导后续试验 |
| 2 | 第 5 页，`p5_c2` | 部分相关 | Section 3 的 The Reflexion process 解释反馈转为 verbal summary、存入 memory 并循环改进；未明确说不更新模型权重 |
| 3 | 第 2 页，`p2_c1` | 部分相关 | Introduction 说明反馈转成文本总结并成为下一 episode 的上下文；没有明确“不更新权重”和 episodic buffer |
| 4 | 第 4 页，`p4_c16` | 无答案依据 | 当前 chunk 只有 Figure 2 图标题，没有反馈机制、权重或记忆存储的事实 |
| 5 | 第 4 页，`p4_c19` | 部分相关 | Section 3 的 Self-reflection 解释语言反思、持久记忆和未来 trial；缺少明确“不更新权重”，句尾还在 `a′` 处截断 |

第 4 页完整 PDF 确实还有图、算法和正文，但第 4 项的当前 chunk 只包含图标题。不能把整张图中的信息未经取回就归到这条一行标题证据中。

三题中，RAG 与 Reflexion 的原 top-1 已包含必要完整依据；ReAct 保留明确来源限定下的召回问题。这只是三题抽查，没有生成聊天模型答案，也没有执行完整十题开发集评测，不能直接称为问答准确率。

## 5. ReAct 摘要为什么没在原 top-5 中

先检查数据链，再讨论排序原因。因为下面几类问题需要不同修复方法：

1. 原 PDF 的摘要就没解析出来。
2. 已解析，但过滤阶段排除了它。
3. 有 filtered segment，但没有对应 chunk。
4. 有 chunk，却没写到 SQLite 或向量索引。
5. 摘要已经入库，但本次排序没有把它放进 top-5。

本次诊断确认，ReAct 摘要的第 1 页 `p1_c6` 长度为 **1545 字符**，相关正文经过解析、过滤、分块和入库仍然存在；它没有因为公式、图中文字乱码或缺失记录而丢失。当前 `ABSTRACT` 标题是独立片段，摘要正文 chunk 没有跟该标题合并。当前检索按论文、处理版本和索引配置过滤，没有摘要章节过滤。

这些是数据链和实现事实。它们提示后续可以研究章节元数据、上下文和排序；但**不能据此直接认定“标题分开就是排名落后的原因”**。同一向量空间中，具体排名还与问题表述、段落长度、其他候选和模型表示有关。要验证某种解释，需保留当前结果，再做有明确变量与对照的实验。

进一步做了一次独立诊断：保持同一问题、论文/处理版本和索引配置，生成新的问题向量，然后检查 ReAct 范围内全部 480 条候选的排名。摘要 `p1_c6` 在**这次新实验**中排第 9，分数约 `0.540723`，因此取前五条时仍然不能看到它。全部 480 条向量的身份、哈希与缓存方向核对通过，排序结果逐条回 SQLite 对上来源。原五条的 ID 与顺序保持一致，但分数有很小变化，最大差约 `0.000109`。

E 当时没有保存问题向量，因此这份完整排名属于新实验，不能把第 9 名写成“E 那一次已测得的第 9 名”。实际诊断及每条排名见 [ReAct 摘要召回诊断](/D:/course/paper-research-assistant/artifacts/d4/retrieval_diagnostics/react_abstract_recall.json)。

该诊断额外调用一次问题 embedding API，实际用量 35 tokens；E 原三题仍是 3 次请求、103 tokens。你继续查看报告、候选和 PDF，不需要再执行这次诊断或再次付费查询。

由此已确认的现象是：摘要存在且已入库，当前无摘要章节硬过滤，本次语义排序中摘要位于 top-5 之外。长摘要包含多个主题、较短参考条目含相似词等，仍是可能影响表示和排序的**未验证假设**。本次没有通过改参数、重新分块或排除参考文献来验证这些假设，也没有直接宣称某种调整一定能解决问题。

任务 F 保留原 E 的 top-5，不把后来在 PDF 中找到的摘要手工塞到排名第一，不修改题目，也不在这次复核中顺手更改分块参数或重新生成整个索引。这样后续调优才有可信的原始对照。

## 6. 你怎样完成人工复核

本节保留复核操作方法。用户已于 2026-10-02 完成本次复核，状态为 `human_verified`；无需为了更新 G 再次执行相同查询或重新确认。今后产生新候选时，再按本节方法检查新的结果。

### 6.1 先打开报告，不用重新查询

打开 [retrieval_review.md](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)，查看每题的原问题、候选和判定理由。也可离线读取结构化记录：

```powershell
Get-Content -LiteralPath 'D:\course\paper-research-assistant\artifacts\d4\retrieval_review.json' -Encoding UTF8
```

读取报告、浏览截图、打开原 PDF 和按 chunk ID 回查 SQLite，都不需要调用模型。

### 6.2 逐篇按文件页序看原 PDF

| 论文及固定 PDF | 首先查看 | 再查看 | 目的 |
|---|---|---|---|
| [RAG PDF](/D:/course/paper-research-assistant/data/papers/2005.11401v4.pdf) | 文件第 1 页摘要 | 第 2 页、第 9 页 | 确认 top-1/top-2 的定义完整，其他候选只谈背景或结果 |
| [ReAct PDF](/D:/course/paper-research-assistant/data/papers/2210.03629v3.pdf) | 文件第 1 页摘要 | 第 4 页 Domains、第 3 页 Introduction、第 11/12/13 页参考文献 | 确认摘要确有两基准，同时确认原候选来自正文或参考文献，不能混用来源 |
| [Reflexion PDF](/D:/course/paper-research-assistant/data/papers/2303.11366v4.pdf) | 文件第 1 页摘要 | 第 2 页、第 4 页、第 5 页 | 确认完整机制、图标题的证据不足，以及 Self-reflection 片段末尾截断 |

这组页序覆盖本次候选和标注证据，共十三个不同 PDF 页面。截图用于方便对照，固定 PDF 才是原始来源；发现截图不清楚时回到 PDF 放大。

对于 ReAct 第 1 页，在 `ABSTRACT` 中找到 question answering、HotpotQA、fact verification、Fever。再看第 4 页原 top-1，确认它位于 `3.1 SETUP` 下的 `Domains` 段。这样能直观看出“事实相同”与“来源满足题目”是两个条件。

看第 11、12、13 页参考文献时，不仅看相似词，还看候选是否只有一条参考文献的后半句。完整参考条目中的标题和作者可能在相邻 chunk 中；不能假装当前短片段已经携带这些上下文。

### 6.3 核对结论，并留下真实的人审记录

每题可以按下面格式记录：

```text
题目：D2-001
原 PDF：2005.11401v4.pdf
检查的文件页：1、2、9
确认：rank 1/2 支持两种记忆的完整定义
发现的问题：如有，写具体位置及内容
复核人：user
复核日期：实际完成日期
状态：人工通过 / 需要修改
```

ReAct 可以记录“AI 对候选来源和问题的判断已核实；原检索仍存在摘要未进入 top-5 的质量问题”。**人工通过复核记录，不会让这次召回问题消失。**

如果你认为某条判定不正确，指出题目、rank、文件页及具体原句即可，再根据原文修订判断。不要只改状态而不说明证据。

## 7. AI 核对完成与人工通过为什么分开

题集里的 `human_verified` 表示你此前已检查题目、预期事实和标注引用。任务 F 新检查的是“这一次检索实际返回的候选”。这两次检查的对象不同。

因此，AI 可以完成候选的文字与视觉核对，并写明 `reviewed_by=codex_ai`；获得用户确认之前，`human_review_status` 保留为 `pending`。本次用户已在 2026-10-02 明确确认，现通过独立来源记录更新为 `human_verified`；没有把 AI 判断或题集人审字段自动复制为本次确认。

同样，记录为人工复核完成后，ReAct 的失败观察仍要保留。复核确认的是记录可靠，检索调优要靠后续实现与测量。

## 8. 接下来 G 和 D5 各做什么

任务 G 收拢 D4 的边界验收和操作说明：重复导入数量不增长、已有向量可复用、程序关闭再打开数据仍在、失败版本不能进入 ready 检索范围、论文/处理版本过滤不会串数据，并汇总当前真实数据、配置和已知问题。D/E 已有的有效验收可以引用，只有存在新改动、失败或未解决疑点时再追加必要检查。

当前 G 已记录 B/F 用户确认，并完成当前源码 59 项边界重跑及新增人审继承 22 项检查；正式新进程九项验收通过，本次零 API。D4 已完成，ReAct 摘要漏召回及其他候选边界问题继续保留。最终报告在 [validation.md](/D:/course/paper-research-assistant/artifacts/d4/validation.md)，0 API 验收命令与 D5 代码接入说明见 [d4-G-completion-guide.md](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)。

D4 完成以后，D5 再把本轮实际返回且核对来源的证据交给聊天模型生成回答。D5 需要确保引用来自提供的证据集合，结论不超过原文范围；证据不足时明确说明不足，不能用模型记忆填补摘要、章节或实验条件。

ReAct 的当前观察可以作为后续检索改进的开发案例。先保留这轮结果，再决定是否增加章节信息或带来源的上下文扩展；不能只因为找到一个看似可行的方案，就改写已经保存的失败基线。

本次十五条文字判断的独立记录见 [候选文字复核日志](/D:/course/paper-research-assistant/archive/run_logs/d4/retrieval_candidate_text_review.json)。最终视觉核对、诊断与进度统一看 [任务 F 正式报告](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)。
