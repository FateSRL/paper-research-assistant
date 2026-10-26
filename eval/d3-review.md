# D3 任务 D：四条新开发题的复核说明

记录日期：2026-10-01。正式题集是 [dev.jsonl](/D:/course/paper-research-assistant/eval/dev.jsonl)，已由六条扩充到十条，全部保持 `split=dev`。

原 D2-001–006 的内容与人工通过状态保留。新 D3-001–004 已完成 AI 全页视觉对照、原文/来源核对与独立 AI 标注审查；使用者于 2026-10-01 在聊天中明确确认人工复核完毕，现统一为 `human_verified`，追加 `human_reviewed_by=user`、`human_reviewed_at=2026-10-01`，保留原 AI 标注人和日期。

这些是准备给后续检索和问答评测使用的问题及参考要点。本次没有调用问答模型、没有计算问答成功率、没有创建冻结验收集。来源一致性记录见 [validation.json](/D:/course/paper-research-assistant/artifacts/d3/dev_expansion/validation.json)。

## 如何复核

1. 打开下文固定版本 PDF，跳到指定的 PDF 文件页序（从 1 开始）。
2. 找到指定段落，对照英文引文。引文只合并空白，保留原词、连字和提取后的下标形式。
3. 判断正文是否足够支持每个中文期望要点；回答可以换一种说法，只要含义和范围准确。
4. 有问题时说明题号与需要修改的内容；实际核对完成后，记录通过的题号。人工状态只根据实际复核结果更新。

## 四题概览

| ID | 论文/文件页 | 类型 | 考查点 |
|---|---|---|---|
| D3-001 | RAG v4 / 4 | method | 微调的冻结/更新规则及原因 |
| D3-002 | RAG v4 / 4 | fact | Wikipedia 快照、切分和规模 |
| D3-003 | ReAct v3 / 4 | method | search、lookup、finish 的具体作用 |
| D3-004 | Reflexion v4 / 6 | retrieval_paraphrase | HotpotQA 实验对同一任务的连续失败停止条件 |

## D3-001：论文在微调 RAG 时冻结哪些组件、更新哪些组件？为什么不更新文档编码器？

原文：[打开 RAG v4 PDF](/D:/course/paper-research-assistant/data/papers/2005.11401v4.pdf)，PDF 文件第 4 页。位置：页首延续上一页的 2.4 Training 段落，找 Updating the document encoder。

英文问题：During RAG fine-tuning, which components are kept fixed, which are updated, and why is the document encoder not updated?

期望要点：

1. 冻结 document encoder（文档编码器）和 document index（文档索引）。
2. 只微调 query encoder（查询编码器）与 BART generator（生成器）。
3. 更新文档编码器需要周期性更新文档索引，代价较高；作者认为取得较强表现不必做这一步。

原文证据：

> Updating the document encoder BERTd during training is costly as it requires the document index to be periodically updated as REALM does during pre-training [20]. We do not ﬁnd this step necessary for strong performance, and keep the document encoder (and index) ﬁxed, only ﬁne-tuning the query encoder BERTq and the BART generator.

定位辅助：`arxiv_2005.11401v4:p4:b1:l0-4:d42a9b80332b`；过滤版本 `d3-quality-filter-v1`。

复核重点：核对更新与冻结的对象是否分清。原 PDF 的 BERT 下标在文本中线性显示成 BERTd/BERTq；引文保留这个提取结果，题目依赖正文的训练规则。

新增价值：考查训练组件和计算代价，区别于原题中的两种记忆组成及 Sequence/Token 的文档使用方式。

## D3-002：RAG 实验使用哪个时间版本的 Wikipedia 数据？文章如何切分，最终形成多少个检索文档？

原文：[打开 RAG v4 PDF](/D:/course/paper-research-assistant/data/papers/2005.11401v4.pdf)，PDF 文件第 4 页。位置：3 Experiments 标题下面的第一段。

英文问题：Which Wikipedia snapshot do the RAG experiments use, how are articles split, and how many retrieval documents does that create?

期望要点：

1. 使用 2018 年 12 月的 Wikipedia 快照。
2. 每篇文章切成互不重叠、100 个词的片段。
3. 总计约 2100 万个检索文档（21M documents），这里的文档是切分后的片段。

原文证据：

> For all experiments, we use a single Wikipedia dump for our non-parametric knowledge source. Following Lee et al. [31] and Karpukhin et al. [26], we use the December 2018 dump. Each Wikipedia article is split into disjoint 100-word chunks, to make a total of 21M documents.

定位辅助：`arxiv_2005.11401v4:p4:b10:l0-7:a10d1a26082f`；过滤版本 `d3-quality-filter-v1`。

复核重点：核对日期、100-word、disjoint 和 21M 的含义。100-word 按词描述；这只是论文实验设置，我们项目的最终分块方案尚未确定。

新增价值：考查实验语料的快照与切分设置，区别于原题中的模型记忆和生成方法。

## D3-003：论文在知识密集型推理任务中使用的 search[entity]、lookup[string] 和 finish[answer] 三种动作分别做什么？

原文：[打开 ReAct v3 PDF](/D:/course/paper-research-assistant/data/papers/2210.03629v3.pdf)，PDF 文件第 4 页。位置：3.1 Setup 中的 Action Space 段落。

英文问题：In the paper's knowledge-intensive reasoning setup, what do search[entity], lookup[string], and finish[answer] each do?

期望要点：

1. search[entity]：页面存在时返回对应 Wikipedia 实体页面的前五句；页面不存在时，返回搜索引擎建议的前五个相似实体。
2. lookup[string]：在当前页面里返回下一句包含指定字符串的句子，模拟浏览器 Ctrl+F。
3. finish[answer]：以给定答案结束当前任务。

原文证据：

> (1) search[entity], which returns the ﬁrst 5 sentences from the corresponding entity wiki page if it exists, or else suggests top-5 similar entities from the Wikipedia search engine, (2) lookup[string], which would return the next sentence in the page containing string, simulating Ctrl+F functionality on the browser. (3) finish[answer], which would ﬁnish the current task with answer.

定位辅助：`arxiv_2210.03629v3:p4:b7:l0-9:6ca71578e9fb`；过滤版本 `d3-quality-filter-v1`。

复核重点：区分 search 的两种返回内容、lookup 的当前页面范围，以及 finish 的结束作用；这道题只问论文的知识密集型推理设置。

新增价值：考查具体工具动作的语义，区别于原题中的基准名称和一般外部信息获取方式。

## D3-004：在第 4.2 节的 HotpotQA 实验中，同一道题反复答错时，Reflexion 在什么情况下不再重试这道题？

原文：[打开 Reflexion v4 PDF](/D:/course/paper-research-assistant/data/papers/2303.11366v4.pdf)，PDF 文件第 6 页。位置：4.2 Reasoning: HotpotQA 的开头范围说明与同页 Results 段落。

英文问题：In the Section 4.2 HotpotQA experiment, when did Reflexion stop retrying the same task after repeated failures?

期望要点：

1. 在这项 HotpotQA 实验的 Reflexion 运行中，同一任务出现三次连续失败尝试时，不再继续重试该任务。

原文证据：

证据 1：

> HotPotQA [28] is a Wikipedia-based dataset with 113k question-and-answer pairs that challenge agents to parse content and reason over several supporting documents.

定位辅助：`arxiv_2303.11366v4:p6:b23:l0-10:e913d87b5912`；过滤版本 `d3-quality-filter-v1`。

证据 2：

> In the Reflexion runs, we allowed the agent to gather experience and retry on failed tasks until it produced 3 consecutive failed attempts on the particular task.

定位辅助：`arxiv_2303.11366v4:p6:b25:l0-9:bb1409c31b98`；过滤版本 `d3-quality-filter-v1`。

复核重点：保留 HotpotQA 实验、同一任务、连续三次失败三个限定。两条引文分别定位任务范围和停止条件，不跨缺失行拼接成一条引用。

新增价值：考查实验中的重试停止条件及换一种说法定位原文，区别于原题中的权重更新、反馈/记忆机制和价格负例。

## 人工复核记录

- [x] D3-001 原文、训练更新规则和原因一致。
- [x] D3-002 日期、100-word、互不重叠和21M含义一致。
- [x] D3-003 三种动作及各自返回/结束行为一致。
- [x] D3-004 停止条件成立，且保留HotpotQA实验范围。

以上完成状态依据使用者于 2026-10-01 的明确确认：“人工复核完毕,把人工复核的关键字写进去吧”。复核人记录为 `user`，四题均标记 `human_verified`；记录见 [human_review.json](/D:/course/paper-research-assistant/artifacts/d3/dev_expansion/human_review.json)。任务 D 已完成，下一步继续 D4 的分块、解析版本和入库。以后修改受影响题目的问题、证据或期望要点时，应重新复核。
