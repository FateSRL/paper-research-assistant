# D6：新论文 50 道官方原题与对照评测安排

日期：2026-11-03。

**当前范围：第 17 节追加第二批新 50 道官方原题、10 篇新论文准备与新版固定 RAG / Agent 配对验证规划，第 18 节为文末当前 DeepSeek 提示词。本次只离线选题并修改本文件，不实施或发起真实请求。第一批题目、前三步及容量调整的历史规划和实际记录保留；第 11、14、16 节为历史提示，本轮不重跑。**

## 1. 本文件已经完成什么

已从本地官方 **QASPER v0.3 dev** 数据中挑出 **50 道原题，涉及 10 篇论文，每篇 5 题**。原始问题、大小写、拼写和 question_id 均保留；没有自编、翻译改写、合并问题，也没有把单篇题拼成跨论文题或连续追问。

筛选时只考虑**尚未入库的论文**。已对照本地 `data/index/papers.sqlite3` 的论文题名及 arXiv 来源：这 10 篇均未在当前库中出现；50 个 question_id 与本地 `artifacts/v2`、`artifacts/v3` 历史批次 input.json 中记录的官方题目 ID 无重合。这是相对于本项目当前数据和历史记录的“新论文、新题”，不意味着模型预训练时没有见过这些论文。

**本次只完成选题和规划。未下载 PDF、未入库、未发起解析、embedding、重排或问答请求；未修改业务代码。** 下列 PDF v1 链接是准备阶段的候选来源，尚未确认与官方标注匹配；不将候选版本写成已经固定的实际版本。

本文件保留题目清单、官方参考索引和后续执行安排，不另建报告。选题已固定；实际 PDF 版本、paper_id、parse_revision 和证据映射在准备完成后回填本文件，再冻结正式运行输入。

## 2. 实际题型和统计范围

不强求原先六类配比。按官方原题的实际内容，主类型如下；类型只用于分组描述，不输入业务模型。

| 主类型 | 代码 | 数量 |
|---|---|---:|
| 事实与设置 | F | 11 |
| 方法、机制与多项说明 | M | 21 |
| 结果、比较与统计数值 | R | 11 |
| 官方标注资料缺失 | U | 7 |
| 合计 | — | 50 |

R 包含最佳模型、结果比较、数据规模等，**不等于 11 道全部要求读表**。是否依赖表格或图，需按实际 PDF 证据确认，不能为了凑“表格题”改写原问。

本批都是单篇、单轮官方问题：跨论文题 0、连续追问题 0。原题的并列要求保留在 M / R 中，不另造问题补比例。因此，这轮能够比较单篇论文问答与取证，不能据此声称验证了跨论文比较或多轮对话能力。

按当前官方标签：

- 可回答 43 题，官方 unanswerable 7 题：**E50-009、014、021、023、025、039、041**。
- 43 道可回答题中，**E50-026、031** 是有确定“否”答案的 yes/no 题，但官方没有给正向 evidence 段；它们不属于资料缺失题。
- 有官方正向 evidence 的可回答题 **41 题**，作为检索对照的候选评分集。
- 全部 **50 题**进入最终问答对照，包含两道否定题和七道资料缺失题。

官方标签和参考答案是起点。执行前须与实际 PDF 核对；如原参考存在范围差异或标注错误，在本文件明确记录裁定及依据，再冻结评分。保持原题和 question_id，不根据系统答题结果更换题目或改标签。

## 3. 原始数据和论文清单

题目与所有官方答案、evidence 均可由 `question_id` 回查：
[官方原始 JSON（本地）](/D:/course/paper-research-assistant/eval/qasper/raw/qasper-dev-v0.3.json)。

精确定位方式：`raw[arxiv_id]["qas"]` 中 `question_id` 相等的条目；业务问题只取该条目的 `question`。参考答案取全部 `answers[*].answer`，不能只取第一个标注。本文的“官方参考”仅便于阅读，实际评分仍需原始完整标注与固定 PDF。

| 编号 | 论文 | arXiv ID | 候选 PDF | 当前状态 |
|---|---|---|---|---|
| P01 | Named Entity Recognition for Nepali Language | `1908.05828` | [1908.05828v1](https://arxiv.org/pdf/1908.05828v1) | 未下载、未入库；实际版本待核对 |
| P02 | FacTweet: Profiling Fake News Twitter Accounts | `1910.06592` | [1910.06592v1](https://arxiv.org/pdf/1910.06592v1) | 未下载、未入库；实际版本待核对 |
| P03 | Combating Adversarial Misspellings with Robust Word Recognition | `1905.11268` | [1905.11268v1](https://arxiv.org/pdf/1905.11268v1) | 未下载、未入库；实际版本待核对 |
| P04 | Evaluating Tag Recommendations for E-Book Annotation Using a Semantic Similarity Metric | `1908.04042` | [1908.04042v1](https://arxiv.org/pdf/1908.04042v1) | 未下载、未入库；实际版本待核对 |
| P05 | A Multi Purpose and Large Scale Speech Corpus in Persian and English for Speaker and Speech Recognition: The Deepmine Database | `1912.03627` | [1912.03627v1](https://arxiv.org/pdf/1912.03627v1) | 未下载、未入库；实际版本待核对 |
| P06 | Macaw: An Extensible Conversational Information Seeking Platform | `1912.08904` | [1912.08904v1](https://arxiv.org/pdf/1912.08904v1) | 未下载、未入库；实际版本待核对 |
| P07 | Named Entities in Medical Case Reports: Corpus and Experiments | `2003.13032` | [2003.13032v1](https://arxiv.org/pdf/2003.13032v1) | 未下载、未入库；实际版本待核对 |
| P08 | Prose for a Painting | `1910.03634` | [1910.03634v1](https://arxiv.org/pdf/1910.03634v1) | 未下载、未入库；实际版本待核对 |
| P09 | Shallow reading with Deep Learning: Predicting popularity of online content using only its title | `1707.06806` | [1707.06806v1](https://arxiv.org/pdf/1707.06806v1) | 未下载、未入库；实际版本待核对 |
| P10 | Using Monolingual Data in Neural Machine Translation: a Systematic Study | `1903.11437` | [1903.11437v1](https://arxiv.org/pdf/1903.11437v1) | 未下载、未入库；实际版本待核对 |

上表保留选题时的候选来源与状态。**实际十篇现已全部 ready**；明确版本及本地 `paper_id` / `parse_revision` 见第 12.2 节和 `eval/qasper/d6-new50-v1/papers.json`，第三步直接复用这些实际配对，不使用候选状态或伪造的 ID。

## 4. 50 道原题与官方参考索引

表中的“原题”是业务输入，ID、主类型、参考答案、章节和图表索引均是评测侧信息。**严禁把下面参考答案、evidence、可答标签、预期表号或正确数值拼进用户问题、前置规划或工具参数。** 正常目录和实际检索到的原文仍由现有流程提供。

参考中的 `BIBREF`、`INLINEFORM`、`TABREF` / `FIGREF` 是官方数据占位符，不能当作本地引用或实际数值。下列章节名和表图说明属于 QASPER 索引，尚不是本地 PDF 页码或解析 chunk 映射。

### P01 · Named Entity Recognition for Nepali Language

arXiv：`1908.05828`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、5、7、9、11 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-001 | `567dc9bad8428ea9a2658c88203a0ed0f8da0dc3` | R | What is the best model? |
| E50-002 | `8a7615fc6ff1de287d36ab21bf2c6a3b2914f73d` | M | Which machine learning models do they explore? |
| E50-003 | `bb2de20ee5937da7e3e6230e942bec7b6e8f61ee` | F | What is the source of their dataset? |
| E50-004 | `1462eb312944926469e7cee067dfc7f1267a2a8c` | R | How many different types of entities exist in the dataset? |
| E50-005 | `9bd080bb2a089410fd7ace82e91711136116af6c` | R | What is the performance improvement of the grapheme-level representation model over the character-level model? |

官方参考与证据索引：

- **E50-001**：BiLSTM+CNN(grapheme-level) and BiLSTM+CNN(G)+POS 。 证据索引：章节「Conclusion and Future work」。 **评分注意：原问没有限定模型设置；按固定 PDF 中的模型、数据集和是否加入 POS 区分最佳项，不能把某一设置的最优扩成所有设置最优。**
- **E50-002**：BiLSTM；BiLSTM-CNN；BiLSTM-CRF；BiLSTM-CNN-CRF；另一个官方标注：BiLSTMBIBREF14, BiLSTM+CNNBIBREF20, BiLSTM+CRFBIBREF1, BiLSTM+CNN+CRFBIBREF2；CNN modelBIBREF0 and Stanford CRF modelBIBREF21。 证据索引：章节「Experiments」；章节「Related Work」。
- **E50-003**：daily newspaper of the year 2015-2016。 证据索引：章节「Dataset Statistics ::: OurNepali dataset」。
- **E50-004**：OurNepali contains 3 different types of entities, ILPRL contains 4 different types of entities；另一个官方标注：three。 证据索引：章节「Dataset Statistics ::: ILPRL dataset」；章节「Dataset Statistics ::: OurNepali dataset」；Table 1: Dataset statistics。 **评分注意：官方参考同时涉及 OurNepali 与 ILPRL；须标明所答数据集，不能把 3 类与 4 类混为同一统计口径。**
- **E50-005**：On OurNepali test dataset Grapheme-level representation model achieves average 0.16% improvement, on ILPRL test dataset it achieves maximum 1.62% improvement；另一个官方标注：BiLSTM+CNN(grapheme-level) which turns out to be performing on par with BiLSTM+CNN(character-level) under the same configuration。 证据索引：章节「Conclusion and Future work」；Table 5: Comparison of different variation of our models。 **评分注意：官方数值参考分别是 OurNepali 的平均提升和 ILPRL 的最大提升，另一个标注概括为表现相近；不能混用 average / maximum，也不能脱离固定 PDF 把其中一种表述机械设为唯一答案。**

### P02 · FacTweet: Profiling Fake News Twitter Accounts

arXiv：`1910.06592`；原始数据：QASPER dev v0.3；选取原始 qas 的第 3、4、5、6、9 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-006 | `71fe5822d9fccb1cb391c11283b223dc8aa1640c` | M | What baselines do they compare to? |
| E50-007 | `97d0f9a1540a48e0b4d30d7084a8c524dd09a4c3` | M | How are chunks defined? |
| E50-008 | `1062a0506c3691a93bb914171c2701d2ae9621cb` | M | What features are extracted? |
| E50-009 | `8e12b5c459fa963b3e549deadb864c244879fe82` | U | How many layers does their model have? |
| E50-010 | `3e1829e96c968cbd8ad8e9ce850e3a92a76b26e4` | R | How big is the dataset used in this work? |

官方参考与证据索引：

- **E50-006**：LR + Bag-of-words；Tweet2vec；LR + All Features (tweet-level)；LR + All Features (chunk-level)；FacTweet (tweet-level)；Top-$k$ replies, likes, or re-tweets；另一个官方标注：Top-$k$ replies, likes, or re-tweets；FacTweet (tweet-level)；LR + All Features (chunk-level)；LR + All Features (tweet-level)；Tweet2vec；LR + Bag-of-words。 证据索引：章节「Experiments and Results」；章节「Introduction」；章节「Methodology」。
- **E50-007**：Chunks is group of tweets from single account that  is consecutive in time - idea is that this group can show secret intention of malicious accounts.；另一个官方标注：sequence of $s$ tweets。 证据索引：章节「Methodology」；章节「Introduction」。
- **E50-008**：Sentiment；Morality；Style；Words embeddings；另一个官方标注：15 emotion types；sentiment classes, positive and negative；care, harm, fairness, cheating, loyalty, betrayal, authority, subversion, sanctity, and degradation；count of question marks；exclamation marks；consecutive characters and letters；links；hashtags；users' mentions；uppercase ratio；tweet length；words embeddings。 证据索引：章节「Methodology」；章节「Introduction」；章节「Experiments and Results」。
- **E50-009**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-010**：Total dataset size: 171 account (522967 tweets)；另一个官方标注：212 accounts。 证据索引：章节「Experiments and Results」；Table 1: Statistics on the data with respect to each account type: propaganda (P), clickbait (C), hoax (H), and real news (R).。 **评分注意：官方参考同时有 171 accounts / 522967 tweets 和 212 accounts。QASPER 正文给出初始候选来源与筛选过程；正式评分前用 PDF 表格区分候选账户与最终使用数据，不能拿某一个标注数字直接硬判。**

### P03 · Combating Adversarial Misspellings with Robust Word Recognition

arXiv：`1905.11268`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、2、3、6、7 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-011 | `0d9fcc715dee0ec85132b3f4a730d7687b6a06f4` | M | What does the "sensitivity" quantity denote? |
| E50-012 | `8910ee2236a497c92324bbbc77c596dba39efe46` | F | What end tasks do they evaluate on? |
| E50-013 | `2c59528b6bc5b5dc28a7b69b33594b274908cca6` | M | What is a semicharacter architecture? |
| E50-014 | `67ec8ef85844e01746c13627090dc2706bb2a4f3` | U | Why do they experiment with RNNs instead of transformers for this task? |
| E50-015 | `ba539cab80d25c3e20f39644415ed48b9e4e4185` | M | How do the backoff strategies work? |

官方参考与证据索引：

- **E50-011**：the number of distinct word recognition outputs that an attacker can induce；另一个官方标注：The expected number of unique outputs a word recognition system assigns to a set of adversarial perturbations ；另一个官方标注：the number of distinct word recognition outputs that an attacker can induce, not just the number of words on which the model is “fooled”。 证据索引：章节「Model Sensitivity」。
- **E50-012**：Sentiment analysis and paraphrase detection under adversarial attacks。 证据索引：章节「Robustness to adversarial attacks」。
- **E50-013**：A semi-character based RNN (ScRNN) treats the first and last characters individually, and is agnostic to the ordering of the internal characters；另一个官方标注：processes a sentence of words with misspelled characters, predicting the correct words at each step。 证据索引：章节「ScRNN with Backoff」；章节「Introduction」。
- **E50-014**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-015**：In pass-through, the recognizer passes on the possibly misspelled word, backoff to neutral word backs off to a word with similar distribution across classes and backoff to background model backs off to a more generic word recognition model trained with larger and less specialized corpus.；另一个官方标注：Pass-through passes the possibly misspelled word as is, backoff to neutral word backs off to a word with similar distribution across classes and backoff to background model backs off to a more generic word recognition model trained with larger and less specialized corpus.；另一个官方标注：Backoff to "a" when an UNK-predicted word is encountered, backoff to a more generic word recognition model when the model predicts UNK。 证据索引：章节「ScRNN with Backoff」。

### P04 · Evaluating Tag Recommendations for E-Book Annotation Using a Semantic Similarity Metric

arXiv：`1908.04042`；原始数据：QASPER dev v0.3；选取原始 qas 的第 2、3、4、5、6 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-016 | `ab54cd2dc83141bad3cb3628b3f0feee9169a556` | R | which algorithm was the highest performer? |
| E50-017 | `249c805ee6f2ebe4dbc972126b3d82fb09fa3556` | M | how is diversity measured? |
| E50-018 | `b4f881331b975e6e4cab1868267211ed729d782d` | R | how large is the vocabulary? |
| E50-019 | `79413ff5d98957c31866f22179283902650b5bb6` | R | what dataset was used? |
| E50-020 | `29c014baf99fb9f40b5171aab3e2c7f12a748f79` | M | what algorithms did they use? |

官方参考与证据索引：

- **E50-016**：A hybrid model consisting of best performing popularity-based approach with the best similarity-based approach。 证据索引：章节「Recommendation Accuracy Evaluation」。
- **E50-017**：average dissimilarity of all pairs of tags in the list of recommended tags；另一个官方标注： the average dissimilarity of all pairs of tags in the list of recommended tags。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-018**：33,663；另一个官方标注：33,663 distinct review keywords 。 证据索引：章节「Dataset」。
- **E50-019**：48,705 e-books from 13 publishers；search query logs of 21,243 e-books for 12 months；另一个官方标注： E-book annotation data: editor tags, Amazon search terms, and  Amazon review keywords.。 证据索引：章节「Dataset」。 **评分注意：参考包含 e-book 数量、出版社数量与日志覆盖范围；按原文区分书籍主体和日志子集。**
- **E50-020**：popularity-based；similarity-based；hybrid。 证据索引：章节「Introduction」。

### P05 · A Multi Purpose and Large Scale Speech Corpus in Persian and English for Speaker and Speech Recognition: The Deepmine Database

arXiv：`1912.03627`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、2、3、4、5 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-021 | `ee2ad0ab64579cffb60853db6a8c0f971d7cf0ff` | U | who transcribed the corpus? |
| E50-022 | `fde700d5134a9ae8f7579bea1f1b75f34d7c1c4c` | F | how was the speech collected? |
| E50-023 | `b1a068c1050e2bed12d5c9550c73e59cd5b1f78d` | U | what accents are present in the corpus? |
| E50-024 | `f9edd8f9c13b54d8b1253ed30e7decc1999602da` | M | what evaluation protocols are provided? |
| E50-025 | `d93c0e78a3fe890cd534a11276e934be68583f4b` | U | what age range is in the data? |

官方参考与证据索引：

- **E50-021**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-022**：The speech was collected from respondents using an android application.；另一个官方标注：Android application。 证据索引：章节「Data Collection」。
- **E50-023**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-024**：three experimental setups with different numbers of speakers in the evaluation set；three experimental setups with different number of speaker in the evaluation set are defined； first one, respondents with at least 17 recording sessions are included to the evaluation set, respondents with 16 sessions to the development and the rest of respondents to the background set；second setup, respondents with at least 8 sessions are included to the evaluation set, respondents with 6 or 7 sessions to the development and the rest of respondents to the background set。 证据索引：章节「DeepMine Database Parts」；章节「DeepMine Database Parts ::: Part1 - Text-dependent (TD)」；章节「DeepMine Database Parts ::: Part2 - Text-prompted (TP)」；章节「DeepMine Database Parts ::: Part3 - Text-independent (TI)」。 **评分注意：官方证据跨 Part1 / Part2 / Part3，参考抽取并不等于完整协议。评分须按原问覆盖实际给出的协议，不能只命中一个设置就通过。**
- **E50-025**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。

### P06 · Macaw: An Extensible Conversational Information Seeking Platform

arXiv：`1912.08904`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、3、4、5、6 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-026 | `58ef2442450c392bfc55c4dc35f216542f5f2dbb` | F | Does the paper provide any case studies to illustrate how one can use Macaw for CIS research? |
| E50-027 | `375b281e7441547ba284068326dd834216e55c07` | M | What is a wizard of oz setup? |
| E50-028 | `05c49b9f84772e6df41f530d86c1f7a1da6aa489` | F | What interface does Macaw currently have? |
| E50-029 | `6ecb69360449bb9915ac73c0a816c8ac479cbbfc` | F | What modalities are supported by Macaw? |
| E50-030 | `68df324e5fa697baed25c761d0be4c528f7f5cf7` | M | What are the different modules in Macaw? |

官方参考与证据索引：

- **E50-026**：yes_no=false（可回答的否定结论）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。 **评分注意：官方标为可回答且 yes_no=false；它不是 unanswerable，也不能因为无正向证据段就算检索漏召回。**
- **E50-027**：seeker interacts with a real conversational interface；intermediary (or the wizard) receives the seeker's message and performs different information seeking actions；另一个官方标注：a setup where the seeker interacts with a real conversational interface and the wizard, an intermediary, performs actions related to the seeker's message。 证据索引：章节「Macaw Architecture」。
- **E50-028**：File IO；Standard IO；Telegram；另一个官方标注：The current implementation of Macaw supports a command line interface as well as mobile, desktop, and web apps.。 证据索引：章节「User Interfaces」；章节「Introduction」；章节「Retrieval and Question Answering in Macaw」；章节「Limitations and Future Work」。 **评分注意：不同参考分别描述 IO 适配器和用户端接口，需结合 PDF 对应段落评价，不能把两个层次的描述判成互斥。**
- **E50-029**：text, speech, image, click, etc。 证据索引：章节「Introduction」。
- **E50-030**：Co-Reference Resolution；Query Generation；Retrieval Model；Result Generation。 证据索引：章节「Retrieval and Question Answering in Macaw」；章节「Introduction」；章节「User Interfaces」；章节「Limitations and Future Work」；章节「Macaw Architecture」。

### P07 · Named Entities in Medical Case Reports: Corpus and Experiments

arXiv：`2003.13032`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、2、3、4、5 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-031 | `8df35c24af9efc3348d3b8d746df116480dfe661` | F | Do they experiment with other tasks? |
| E50-032 | `277a7e916e65dfefd44d2d05774f95257ac946ae` | M | What baselines do they introduce? |
| E50-033 | `2916bbdb95ef31ab26527ba67961cf5ec94d6afe` | R | How large is the corpus? |
| E50-034 | `f2e8497aa16327aa297a7f9f7d156e485fe33945` | M | How was annotation performed? |
| E50-035 | `9b76f428b7c8c9fc930aa88ee585a03478bff9b3` | R | How many documents are in the new corpus? |

官方参考与证据索引：

- **E50-031**：yes_no=false（可回答的否定结论）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。 **评分注意：官方标为可回答且 yes_no=false；与资料缺失题分开计分。**
- **E50-032**：Conditional Random Fields；BiLSTM-CRF；Multi-Task Learning；BioBERT
；另一个官方标注：Conditional Random Fields；BiLSTM-CRF；Multi-Task Learning；BioBERT。 证据索引：章节「Baseline systems for Named Entity Recognition in medical case reports ::: Conditional Random Fields」；章节「Baseline systems for Named Entity Recognition in medical case reports ::: BiLSTM-CRF」；章节「Baseline systems for Named Entity Recognition in medical case reports ::: Multi-Task Learning」；章节「Baseline systems for Named Entity Recognition in medical case reports ::: BioBERT」。
- **E50-033**：8,275 sentences and 167,739 words in total；另一个官方标注：The corpus comprises 8,275 sentences and 167,739 words in total.。 证据索引：章节「A Corpus of Medical Case Reports with Medical Entity Annotation ::: Corpus Overview」。
- **E50-034**：Experienced medical doctors used a linguistic annotation tool to annotate entities.；另一个官方标注：WebAnno。 证据索引：章节「A Corpus of Medical Case Reports with Medical Entity Annotation ::: Annotators」；章节「A Corpus of Medical Case Reports with Medical Entity Annotation ::: Annotation Tools and Format」。
- **E50-035**：53 documents。 证据索引：章节「A Corpus of Medical Case Reports with Medical Entity Annotation ::: Corpus Overview」。

### P08 · Prose for a Painting

arXiv：`1910.03634`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、3、4、5、6 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-036 | `72e4e26d0dd79c590c28b10938952a9f9497ff1e` | M | What models are used for painting embedding and what for language style transfer? |
| E50-037 | `58ee0cbf1d8e3711c617b1cd3d7aca8620e26187` | M | What limitations do the authors demnostrate of their model? |
| E50-038 | `f71b52e00e0be80c926f153b9fe0a06dd93af11e` | R | How does final model rate on Likert scale? |
| E50-039 | `8db6f8714bda7f3781b4fbde5ebb3794f2a60cfe` | U | How big is English poem description of the painting dataset? |
| E50-040 | `54e945ea4b014e11ed4e1e61abc2aa9e68fea310` | R | What is best BLEU score of language style transfer authors got? |

官方参考与证据索引：

- **E50-036**：generating a poem from images we use an existing actor-critic architecture；various types of sequence to sequence models。 证据索引：章节「Methods ::: Image To Poem Actor-Critic Model」；章节「Methods ::: Shakespearizing Poetic Captions」；章节「Methods ::: Shakespearizing Poetic Captions ::: Seq2Seq with Attention」；章节「Methods ::: Shakespearizing Poetic Captions ::: Seq2Seq with a Pointer Network」。
- **E50-037**：Since we do not have an end-to-end dataset, the generated English poem may not work well with Shakespeare style transfer；另一个官方标注：we do not have an end-to-end dataset, the generated English poem may not work well with Shakespeare style transfer as shown in Figure FIGREF12 for "Starry Night" with a low average content score。 证据索引：章节「Results ::: Limitations」。
- **E50-038**：average content score across the paintings is 3.7；average creativity score is 3.9；average style score is 3.9 ；另一个官方标注：average content score across the paintings is 3.7；average creativity score is 3.9；average style score is 3.9。 证据索引：章节「Results」。
- **E50-039**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。 **评分注意：保留原问，不改为另一数据集问题。官方没有给出可回答标注；需核对论文中 image–poem / poem corpus 与 end-to-end 数据集的区别，不能拿其他语料规模冒充所问规模。**
- **E50-040**：seq2seq model with global attention gives the best results with an average target BLEU score of 29.65；另一个官方标注：average target BLEU score of 29.65。 证据索引：章节「Methods ::: Shakespearizing Poetic Captions ::: Prediction」。

### P09 · Shallow reading with Deep Learning: Predicting popularity of online content using only its title

arXiv：`1707.06806`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、2、4、5、6 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-041 | `252a645af9876241fb166e5822992ce17fec6eb6` | U | What is the average length of the title text? |
| E50-042 | `ed67359889cf61fa11ee291d6c378cccf83d599d` | M | Which pretrained word vectors did they use? |
| E50-043 | `955de9f7412ba98a0c91998919fa048d339b1d48` | M | Which shallow approaches did they experiment with? |
| E50-044 | `3b371ea554fa6639c76a364060258454e4b931d4` | F | Where do they obtain the news videos from? |
| E50-045 | `ddb23a71113cbc092cbc158066d891cae261e2c6` | F | What is the source of the news articles? |

官方参考与证据索引：

- **E50-041**：unanswerable=true（官方认为无法由论文回答）。 官方未给正向 evidence；需在实际 PDF 范围内复核结论。
- **E50-042**： pre-trained GloVe word vectors ；另一个官方标注：GloVe word vectors BIBREF16 pre-trained on two datasets: Wikipedia 2014 with Gigaword5 (W+G5) and Common Crawl (CC)。 证据索引：章节「Text Representation」；章节「Embeddings」。
- **E50-043**：SVM；另一个官方标注：SVM with linear kernel using bag-of-words features。 证据索引：章节「Baselines」。
- **E50-044**：NowThisNews Facebook page。 证据索引：章节「Datasets」。
- **E50-045**：main news channels, such as Yahoo News, The Guardian or The Washington Post；另一个官方标注：The BreakingNews dataset。 证据索引：章节「Datasets」。

### P10 · Using Monolingual Data in Neural Machine Translation: a Systematic Study

arXiv：`1903.11437`；原始数据：QASPER dev v0.3；选取原始 qas 的第 1、2、3、4、5 条（从 1 开始计数）。

| 本批 ID | 官方 question_id | 主类型 | 原题（原文保留） |
|---|---|---|---|
| E50-046 | `87bb3105e03ed6ac5abfde0a7ca9b8de8985663c` | M | why are their techniques cheaper to implement? |
| E50-047 | `d9980676a83295dda37c20cfd5d58e574d0a4859` | M | what data simulation techniques were introduced? |
| E50-048 | `9225b651e0fed28d4b6261a9f6b443b52597e401` | M | what is their explanation for the effectiveness of back-translation? |
| E50-049 | `565189b672efee01d22f4fc6b73cd5287b2ee72c` | F | what dataset is used? |
| E50-050 | `b6f7fadaa1bb828530c2d6780289f12740229d84` | F | what language pairs are explored? |

官方参考与证据索引：

- **E50-046**：They use a slightly modified copy of the target to create the pseudo-text instead of full BT to make their technique cheaper；另一个官方标注：They do not require the availability of a backward translation engine.。 证据索引：章节「Conclusion 」；章节「Stupid Back-Translation 」。
- **E50-047**：copy；copy-marked；copy-dummies。 证据索引：章节「Setups」。
- **E50-048**：when using BT, cases where the source is shorter than the target are rarer; cases when they have the same length are more frequent；automatic word alignments between artificial sources tend to be more monotonic than when using natural sources。 证据索引：章节「Properties of back-translated data 」。
- **E50-049**：Europarl corpus ；WMT newstest 2014；News-Commentary-11；Wikipedia from WMT 2014；Multi-UN；EU-Bookshop；Rapid；Common-Crawl (WMT 2017)；另一个官方标注：Europarl tests from 2006, 2007, 2008; WMT newstest 2014.。 证据索引：章节「In-domain and out-of-domain data 」；章节「NMT setups and performance 」。 **评分注意：官方参考有训练语料和测试集两种范围；评分前结合原文固定范围，接受有证据、明确标注用途的列举，不做机械字符串比较。**
- **E50-050**：English-German, English-French.；另一个官方标注：English-German, English-French。 证据索引：章节「In-domain and out-of-domain data 」。

## 5. 第一步规划：10 篇论文准备、入库与证据标注

### 5.1 目标和固定输入

目标是把第 3 节的 **P01～P10 十篇未入库论文、E50-001～050 五十道官方原题**，准备为同一批可复现的检索输入和评测依据。本轮题目数量、question_id 和原始 question 保持不变；不补自编题，不改写为中文，不按题型重新凑配比。

从本地 `eval/qasper/raw/qasper-dev-v0.3.json` 按 arXiv ID / question_id 提取完整原始记录，保留全部 `answers[*].answer`。准备工作不调用聊天模型来判答案、生成证据或挑题。官方标签暂为 43 道可回答、7 道 unanswerable；其中 41 道有正向 evidence、另 2 道为无正向 evidence 的否定题。

### 5.2 取得并确认具体 PDF 版本

1. 按 P01～P10 顺序下载第 3 节候选 `arxiv_id + v1` PDF，放在现有 `eval/qasper/pdfs/` 下，文件名保留明确版本。已有相同的本地 PDF 可以复用，不重新下载或删除旧文件。
2. 对照官方 full_text、选中原题的 evidence 和关键表格，确认该 PDF 含有对应研究与实验。至少核对：题名 / 作者、所选证据的章节、数值题对应的表头与数据、原参考存在差异的题目范围。图表必要时查看 PDF 页面，不能只核对标题或表题。
3. v1 若不能匹配，先确认是否只是排版差异；若内容确实不同，取得并记录该论文的其他明确版本，再核对。不能自动把无版本链接指向的最新版作为已匹配版本，也不能把官方 full_text 写进库来补缺。
4. 版本仍不能确认的论文记录为 `pending_version`，保留具体原因；不换论文或问题凑数。先报告准备进度，不启动依赖该版本的正式检索。

这里固定的是本次实际使用的 PDF 版本，不声称 QASPER 发布了某个原始 PDF 版本号。只要证据与问题范围能经核对一致，就记录对应关系和必要差异。

### 5.3 通过当前正式入口入库

复用 [import_runtime.py](/D:/course/paper-research-assistant/paper_assistant/import_runtime.py:30) 的 `import_pdf`。当前默认入口为 `parser="mineru-api"`；使用既有解析、过滤、分块、parent / child、embedding 和索引配置。传入实际 PDF bytes、带版本的文件名、官方题名及包含版本的 source_url。不要另建一套为了评测而更有利的分块或清洗策略。

每篇完成后保存实际返回的 `paper_id`、`parse_revision`、状态、chunk 数、解析 / 索引用量和耗时；以当前 profile 下真实 `ready` 状态及完整入库结果为准。旧数据和其他解析版本保留；若执行时已经有本批同一 PDF 的 ready 配对，复用正式入口已有的缓存 / ready 结果，不额外重解析。

本步骤允许未来执行时发生这 **10 篇必要的 PDF 下载、MinerU 解析、文档 embedding 和索引写入**。解析任务数、embedding 批次数、tokens 与金额以真实日志为准，不能预先把“10 篇”写成“10 次 embedding”。这些成本属于入库准备，单列于后续查询检索成本。

不改 Agent 提示、工具、停止规则、召回参数或业务引用规则；也不重建其他论文的索引。执行中如发现解析缺表或缺段，本批记录缺口及其影响，不顺带启动新的解析器修复轮次。

### 5.4 在检索前核定评分证据

完成入库后，先用官方完整标注和实际 PDF 核定五十道题的回答范围，再运行检索。重点处理第 4 节已列出的 E50-004 / 005 / 010 / 019 / 024 / 028 / 039 / 049；E50-026 / 031 的 No 结论与七道 unanswerable 分开。

为当前 **41 道有正向 evidence 的题**建立必要证据组，至少保存：

| 字段 | 内容 |
|---|---|
| 题目绑定 | E50 ID、官方 question_id、所属论文和固定 paper_id / parse_revision |
| 预期要点 | 原问要求的必要信息及对应官方标注，区分数据集、实验条件和统计口径 |
| PDF 证据 | 实际页码、原文片段；数值题保存表头 / 行列含义及必要单元格，或正文中的等价数值证据 |
| 证据替代位置 | 同一要点的其他有效位置，允许答案在不同段落获得支持 |
| 入库映射 | 实际 chunk / parent 及 source_spans，标注自动映射或人工确认、是否跨块 |
| 准备状态 | 已确认、PDF 版本未确认、官方参考范围待裁定、解析后缺失等实际状态 |

复用 `qasper_evaluation.build_paragraph_mapping` 及现有来源位置辅助定位，自动映射不了时核对原文；不新建通用标注平台。`FLOAT SELECTED` 表图描述只能帮助定位，不能用表题替代数据证据。

同一必要要点有多个原文位置时，作为**替代证据**；不同必要要点才需要分别覆盖。不同标注者给出不同但有效的完整证据集合时，保留可接受集合，不把所有标注机械并起来要求全部命中。证据横跨两个 chunk 时按真实原文跨度核对，不能因为命中其中一个 chunk 就算覆盖了整段。

若证据在固定 PDF 中确实存在，但解析结果没有保留下来，记录 `parse_missing`：该题仍保留在原有检索分母，相关组无法命中时按实际缺失计，不只保留容易映射的题。若 PDF 中本身无法确认原参考，则先解决版本 / 标签范围，不在看到检索结果后再删改标注。

七道资料缺失题核对全文相关范围，保留否定结论的依据；不为它们伪造“应召回的答案 chunk”。标签或检索资格如确需修订，必须在真实检索前记录原因和新分母，不根据系统结果改题。

### 5.5 准备产物与完成条件

沿用现有 QASPER 数据文件形式，只在实际执行时产生必要普通文件：

- `eval/qasper/d6-new50-v1/sample.json`：本文件固定的 50 道原题、官方 ID、全部参考及评测侧证据组；不是随机重新抽样。
- `eval/qasper/d6-new50-v1/papers.json`：10 篇实际 PDF 路径 / 版本 / 来源、paper_id / parse_revision、ready 状态及证据映射。相关字段可复用已有结构，不加审计或哈希框架。
- 本文件第 3 节及步骤记录：回填实际版本配对、已确认的标签 / 范围修订、准备完成数与未就绪项。解析与入库沿用项目已有正常日志，不另建验证报告。

完成条件是：10 篇版本匹配且 ready、50 个原题准确绑定、回答范围已核定、41 题的 PDF 证据及入库映射状态已记录。解析缺失可以作为已确认的实验事实保留，但不能把未确认的版本或评分依据当成已完成。此时冻结样本和配置，再进入第二步。

## 6. 第二步规划：四种检索策略真实对照

### 6.1 比较对象和统一条件

**问题：BM25、向量、RRF 融合与重排，对同一问题的必要证据覆盖分别有什么影响？** 本步骤只检索和离线评分，聊天模型请求数为 **0**。

| 配置 | 取得方式 | 本次要比较的作用 |
|---|---|---|
| A1 纯 BM25 | 本篇固定版本的 BM25 top-20 | 关键词定位 |
| A2 纯向量 | 本篇固定版本的 dense top-20 | 语义定位 |
| A3 混合 RRF | 相同两路 top-20 按既有 RRF 融合，最多 40 条 | 两路证据互补 |
| A4 混合 + rerank | 对 A3 完全相同的融合池重排 | 必要证据能否排到更前面 |

统一使用第一步冻结的 **41 道原题**，按 E50 ID 升序执行。每题 query 直接取官方 `question`，检索范围只包含该篇唯一完整 `(paper_id, parse_revision)` 配对。保持相同 chunk、索引 profile、过滤范围和正文；不向任何检索器传入 gold、正确答案、证据原文、预期表号或关键词补充。

参数提前固定：当前 `BM25Index` 的 k1=1.5、b=0.75，dense / BM25 各最多 20，RRF rank_constant=60、candidate_limit=20、融合最多 40；A4 使用现有 rerank 模型和整个融合池。所有组统一报告 top-5 / top-10；不足 k 条按实际返回数量评分，不补入其他配置的候选。

不把不同分数体系统一设为 0.7，不使用 MQE / HyDE、LLM 查询规划、`read_context` 或 JS。参数不在这批题上搜索最优，也不根据 A 的成绩替后续问答实验挑选配置。

### 6.2 实现顺序与组件复用

旧 `scripts/run_retrieval_comparison.py` 主要比较旧开发集的 top-k 前缀，不直接运行其默认 main。允许后续为这批数据写一个窄入口，例如 `tmp/d6_prepare_new50.py`、`tmp/d6_retrieval_new50.py`；本次写规划不创建脚本，也不改业务代码。

一次题目执行按下面组织：

1. 从冻结输入提取 `question` 和唯一论文版本，读取该版本的 chunks，复用现有 ready / 版本检查及候选 envelope。BM25 本地得到 A1 排序，不调用 embedding 服务来“实现纯 BM25”。
2. 通过 `EvidenceSearcher.search_evidence(query, selected_versions, top_k=20)` 做一次 query embedding / dense 搜索，保存 A2 的真实排序及用量；不为 A3 / A4 再发同一个 query 请求。
3. 用现有 `reciprocal_rank_fusion` 对这两份排序生成 A3；从同一固定版本补齐 BM25 独有候选的原文。A1、A2、A3 的候选身份、文本和范围必须一致。
4. 用现有 `RerankClient.rerank` 对 A3 的去重融合池请求一次重排，得到 A4。保存实际重排 rank 和 relevance_score；空池不发重排请求。
5. 四组保存各自排名，从同一排名截取 top-5 / top-10。使用相同 `prepare_context(..., max_chars=8000)` 计算 Shown；这是本次统一的上下文准备视图，不是 Agent 多轮后的最终上下文，也不额外补 parent / 相邻块。
6. 运行完该题的四组排序后，才由独立评分代码读取冻结 gold 计算覆盖；gold 从始至终不进入检索 / 重排请求。保存题目状态及真实成本，再进行下一题。

`HybridEvidenceSearcher` 已提供两路候选、融合池和 rerank 轨迹，可复用其中相同能力或数据。若借用它取得整套轨迹，不要再额外跑 dense / rerank；纯 BM25 的逻辑成本仍应单独记录。保留四组各自排序，不能把融合结果截断后假装成纯 BM25 / 纯向量结果。

### 6.3 评分口径

每题的 gold 在步骤一冻结。对每个 k，分别以 Returned 原文和 Shown 原文评价，不把 parent 相关、标题相关或同页相关当作原文已经覆盖。

| 指标 | 计算规则 |
|---|---|
| 单题证据覆盖率@k | 被完整覆盖的必要证据组数 / 该题必要证据组总数；替代位置命中一个有效位置即可 |
| 宏平均证据覆盖率@k | 先算每题覆盖率，再对同一评分题集取平均，避免证据多的题权重过大 |
| 全部必要证据命中@k | 该题满足一个已接受的完整证据集合才记 1；再报命中题数 / 实际比较题数 |
| Returned / Shown 差异 | 分别按候选原文和 `prepare_context` 实际展示文本计算，观察上下文裁剪影响 |
| 运行与成本 | 实际返回数、耗时、embedding / rerank 请求、tokens、失败 / 降级状态 |

“证据覆盖率”仅针对本批核定标注，是检索证据覆盖指标，不是最终答案准确率，也不代表全库相关资料的完整 Recall。本轮没有完整候选相关性标注，因此不把未标注候选当不相关来计算 Precision@k。

空结果属于有效检索，命中与覆盖按 0 计；PDF 有证据但解析缺失同样按实际覆盖计，并单列 `parse_missing`。服务失败与未执行须另列，不能伪造为空结果。四组纯排序效果在**共同有效题集**上配对比较，同时报告计划 41 题、各组有效 / 失败 / 未执行数；不拿各组不同的成功子集直接比较后宣称整体提升。

现有重排失败可能回退到 RRF。若发生，保留实际回退结果和请求用量，但标为 A4 重排失败 / 降级，不能写成 A4 重排成功；单列它与真正重排成功结果的区别。失败不触发为本次实验另设的自动补跑。

七道官方 unanswerable 和 E50-026 / 031 共九题不进入上述证据召回分母，也不进行额外拒答生成。它们的完整问答评价留到后续第 7～8 节。

### 6.4 规模、真实调用与耗时

默认计划为 **41 题 × 4 配置 = 164 份排序结果**。top-5 / top-10 从各自已有排序取前缀，不能再计成两轮真实检索。

正常无重试、每题只取得一次 dense、每个非空融合池只重排一次时，查询阶段预期约 **41 次 query embedding、最多 41 次 rerank**；实际值取日志，空池、缓存、失败或原服务内部请求策略需如实记录。BM25 / RRF 本地计算；解析与文档 embedding 已归入第一步，不再计为查询成本。

共享执行只统计一份物理请求账。各组逻辑耗时可以按组件单列：A1 为 BM25，A2 为 query embedding + dense，A3 为两路召回 + 融合，A4 另加 rerank；同时保留整批实际墙钟。不能把读取缓存排序的几毫秒写成完整在线检索耗时，也不能把共享 embedding 的费用累加四次。只报告实测与有日志的已知值，不为统计另发计费或连通性请求。

### 6.5 离线验证与真实执行顺序

本次只有文档修改，不跑测试、不发请求。未来执行时：

1. 先生成固定数据文件，检查 50 个 question_id、原始 question、论文绑定及 41 题评分资格；这是离线数据一致性检查，不启动模型或 embedding。
2. 若为评测新增 / 修改代码，仅做对应文件所需的语法 / 导入检查，按实际影响选 1～3 个现有方法。涉及前缀与展示预算可用 `scripts.check_retrieval_comparison.RetrievalChecks.test_same_search_prefix_and_display_budget`；涉及 QASPER 输入隔离可用 `scripts.check_qasper.QasperChecks.test_prepare_and_run_keep_annotations_out_of_runtime`。不因只调用未改组件而重跑其已通过验证，不跑整个目录或全量回归。
3. 可用保存的本地候选回放检查四组顺序、top-k 前缀及评分读入顺序，复用现有假客户端；不为“验证运行器”额外请求服务，不新增只复述实现的测试。
4. 第一步完成并冻结标注后，执行当前 41 题的正式真实检索一次。保存已尝试状态、候选及实际用量；已有结果直接使用，不补跑到通过。中断时保留执行进度，未执行项如实列出。
5. 对保存排序离线评分，比较四组共同有效题集，回看差异来自哪个证据组、排名或 Shown 裁剪。发现旧题或新题失误不修改提示 / 检索参数后再重跑这批成绩。

### 6.6 结果文件与本轮结束点

实际执行时在 `artifacts/v3/d6-retrieval-new50-<YYYYMMDD>/` 保存普通 `input.json` / `results.json`：input 记录固定题目、版本、gold 映射引用和实际配置；results 记录每题四组排序 / Shown、覆盖结果、真实用量和运行状态。按实际执行日取目录名，不覆盖既有批次。准备文件和索引成本引用第一步产物，不重复计费。

回写本文件的内容只需：10 篇准备情况、实际版本配对、标签 / 映射裁定、41 题执行完成度、四组覆盖 / 全命中 / 耗时 / 成本对比及主要差异。沿用已有日志，不生成额外审计、哈希快照、验证报告或独立检查清单。

**这是前两步阶段的结束点，实际记录见第 12 节，该阶段聊天问答请求为 0。** 当前另行规划的第三步按第 7～8 节执行；复用前两步的原题、版本和证据，不重做选题、入库或四组检索。

## 7. 第三步规划：50 题固定 RAG 与当前 Agent 的真实问答对照

### 7.1 目的与已有输入

目标是在同一批新论文、相同检索组件和生成模型上，比较两条正式流程的答案完整性、原文支持和实际成本。比较的是端到端流程，不将差异单独归因于某个工具或提示词。

前两步已经有实际产物，见第 12 节：

- 十篇论文全部 ready，实际 PDF 均为经核对的 arXiv v1，固定版本配对已经写入 `eval/qasper/d6-new50-v1/papers.json`。
- 五十道原题和官方参考、证据映射在 `eval/qasper/d6-new50-v1/sample.json`，仍是 43 道 answerable、7 道 unanswerable。
- 检索对照完成 40/41 题，E50-001 因评测脚本手工上下文字段错误而丢失排序，不是该论文未入库。**第三步保留全部 50 题，包括 E50-001**；不补跑第二步，不缩成 40 题。
- 前两步的记录保持原样。本次不重新下载、解析、入库、生成文档向量或重跑四组检索；第三步流程内的正常 query embedding / rerank 则属于本次问答成本。

### 7.2 题目与实际版本绑定

按 E50-001 → E50-050，从冻结 sample 读取 `case_id`、`question_id` 和原始 `question`；必要时仅离线对照官方 JSON 确认读取无误，不重新抽样或改写问题。

**注意现有字段含义：**

| 数据位置 | 含义 / 用法 |
|---|---|
| `sample.cases[*].paper_id` | QASPER arXiv 文献 ID，例如 `1908.05828`，不是本地入库 ID |
| `sample.cases[*].local_paper_id` | 实际本地入库论文 ID，交给问答运行入口 |
| `sample.cases[*].parse_revision` | 该题固定解析版本 |
| `papers.papers[arxiv_id].paper_id / parse_revision` | 与 case 的本地配对核对，应完全一致 |
| `papers.papers[arxiv_id].version_check` | 已确认的 v1、PDF 路径及版本核对记录 |
| `papers.papers[arxiv_id].ready` | 当前已准备状态；原生 runtime 仍负责正常资源 / ready 检查 |

业务入口的 selected_versions 只含本题的 **一个完整本地配对**：
`[(case["local_paper_id"], case["parse_revision"])]`。不把同一论文的不同版本混用，不把所有十篇都交给单篇问题。

原题、实际配对和双方一致的普通语言要求可以进入运行；官方答案、answerable、question_type、evidence_groups、acceptable_sets、预期表号、正确数值和旧检索排名不能进入前置理解、提示或工具参数。论文正常目录、摘要及运行时真实取得的原文继续按现有流程提供。

### 7.3 在生成答案前补齐内容评分口径

前两步冻结的是**检索证据映射**，不自动等于已经核定完整答案。复用第 12.3 节现有裁定，只补齐仍未明确的内容范围和必要要点，不重做整批证据映射，不修改旧检索成绩。

在本批 `input.json` 的评测侧字段记录每题必要要点、允许的回答范围及裁定依据；全部 100 次问答开始前固定，运行后不能为了接受某组答案再放宽。

重点包括：

- **E50-005**：官方 0.16/1.62 的统计口径与表 5 单行直接读数不同。先核对固定 PDF 的表格与说明，明确平均 / 最大 / 单一设置的区别；不能把相互不同的统计口径直接当同一数值，也不能因官方文字占位或概括不同就机械判错。
- **E50-010**：沿用已核对的 171 个账户 / 522,967 条推文；212 是表中某类账户的最少推文数，不作为账户数量参考。不要重新恢复已确认错误的官方字段理解。
- **E50-004 / 019 / 024 / 028 / 049**：保留已经确认的数据集、数据用途、协议部分和接口层次；原问允许的范围先说明，多个合法等价范围按同一规则接受。
- **E50-026 / 031**：正确的 No 是可回答的否定结论，不是资料不足；七道官方 unanswerable 也要区分“论文没有提供”与“本次未取得”。

若仍有确实无法裁定的内容争议，在生成前记录已知歧义及接受边界，不临时换题，不把某一组的措辞设为标准。人工 / 执行者直接依据现有 PDF 与参考核对，**不另发 LLM judge 或固定证据生成请求**。

### 7.4 两组条件与固定参数

| 项目 | B1 固定 RAG | B2 当前 Agent |
|---|---|---|
| 正式入口 | `d9_runtime.run_question(..., mode="fixed_rag")` | `d9_runtime.run_question(..., mode="agent")` |
| 流程 | 正常前置理解、一次检索、生成和既有必要纠错 | 正常前置理解、当前图与工具循环、既有收尾 |
| 检索组件 | 当前 BM25 + dense + RRF + rerank | 同一当前检索组件，允许自主补搜 / 读正文 |
| 论文范围 | 本题一个固定本地配对 | 相同配对 |
| 运行参数 | `library_mode=True, top_k=5, max_chars=8000` | 相同；轮数用已记录的当前正式配置 |
| 历史 | `conversation_history=[]` | `conversation_history=[]` |
| 普通语言要求 | `answer_instructions="Please answer in English."` | 完全相同 |
| 会话与提交 | 本题本组独立新 ID | 另一独立新 ID |

模型以现有 `deepseek-flash` 为起点，两组使用相同实际模型、temperature 和输出上限；embedding / rerank 沿用 `qwen3.7-text-embedding`（1024 维、cosine）/ `qwen3-rerank` 及现有 profile。执行前离线读取并记录实际配置，不为取配置发服务探测；发现配置已经变化时如实记录并在本批内固定。

保留两条正式路径各自的 policy、超时、重试与上下文准备规则，分别记录实际值；不为实验手工覆盖 policy 或改源码来抹平差异。当前库入口两组输出上限均为 4096、temperature 默认为 0.2；Agent 轮数由 `load_agent_max_iterations()` 读取（默认 120），普通请求超时取其现用设置、综合收尾为现有 90 秒。不能照抄旧开发批次 5 轮，也不能把固定 RAG 的 policy 误写成与 Agent 完全相同。

`max_chars=8000` 是共同调用参数，不保证两组最终展示原文严格相同：现有结构化上下文可能采用 token 预算，Agent 也可能补读。记录实际 Shown、预算与工具行为，并将结果解释为**当前两条产品流程的质量 / 成本取舍**，不声称是等 token、等调用预算的单变量消融。

第二步中 A4 并未优于 A3；这条事实保留，但**本次仍沿用事先约定的当前混合 + rerank**。不利用这批测试成绩临时关闭重排、改 top-k 或更换检索器来提高主对照分数。

### 7.5 执行次数、顺序与正常真实调用

**50 道不同问题 × 2 组 × 每题 1 次 = 100 次完整问答**，不是 100 个 HTTP 请求。每组都独立执行其正常前置理解和问答，所有这些调用计入本组用量。

固定顺序：

1. E50 ID 升序，逐题执行两组。
2. 奇数题先 fixed_rag、后 agent；偶数题先 agent、后 fixed_rag。
3. 每个题目 / mode 在调用前记录 attempted、会话和唯一 submission_id；原生入口继续负责自己的提交预占与日志。
4. 每个 mode 返回后立即保存完整原生结果和历史 JSON / Markdown 路径，再开始下一组或下一题。先保存结果，再抽取统计和评分字段，避免再次因评测字段错误丢掉已付费结果。
5. 不共享两组的答案、已读证据或工具历史，不将第二步保存排序作为固定 RAG / Agent 的实际首次检索回放。共用入库索引正常，运行产生的查询与取证各自计费。
6. 允许模型按原流程调用 search、read_context、run_javascript 或直接作答；不强制某题读表、读指定 parent、增加工具次数或穷尽目录。

本次真实请求只包括上述 100 次完整流程内部的前置理解、聊天 / 工具循环、query embedding、rerank，以及既有策略内重试、纠错和必要收尾。新增解析、文档 embedding、单独判分生成、连通性 / 计费探测和额外冒烟问答为 0。

### 7.6 失败、继续与重复范围

答案部分正确、合理拒答或个别题取证不足属于要评价的结果，保存后继续下一题，不现场修提示或重跑直到通过。

单题异常保留原生状态、异常阶段、已知费用和缺失字段。若只是包装器统计 / 序列化失败，优先从已经返回的对象或原生历史日志补回记录，不能再提交同一问答来补日志。某一 mode 失败也不把它从计划分母删除。

如果认证、额度或共享资源状态导致整批无法继续正常调用，保存进度和原因，结束无效付费调用；未运行的题目 / mode 明确列出。后续续接只处理原批次**未尝试的 mode**，复用已经保存的结果；已尝试 mode 不自动换新 submission_id 重跑。

E50-001 本次两组是其首次完整问答，不属于补跑第二步检索。不得因为其旧检索缺失而跳过；也不额外补齐其旧四组排名。

本轮不升级为三次重复、不挑最好一次、不根据前 20 题的成绩提前宣布胜负；50×2×3=300 次是其他范围，本次不执行。

### 7.7 必要运行器、产物与验证

可新增一个窄入口 `tmp/d6_qa_new50_paired.py` 读取已有 sample / papers，调用当前原生 runtime，保存和汇总本批结果。复用现有结果保存、统计函数与 `agent_comparison.summarize_current_costs`；不重构业务模块。

`run_current_case(..., modes=...)` 支持两组顺序，但其接口未直接暴露本批全部会话 / 提交参数。可直接依次调用 `d9_runtime.run_question` 或用薄包装传入固定参数；不要因此改共享函数合同，也不要走 legacy 的共享首轮检索实现。

实际执行产物使用一个新的普通批次目录：
`artifacts/v3/d6-qa-paired-new50-<YYYYMMDD>/`。

- `input.json`：50 个固定题目、每题本地版本配对、两组顺序、普通运行参数、实际配置和评测侧预先核定的内容口径。业务调用只取 question / selected_versions 与明确列出的正常参数。
- `results.json`：计划 100 个 mode 任务及逐次 attempted / completed / failed / not_executed，原生结果或路径、用量、盲评标签和最终评价。新结果到达即按现有普通方式保存。
- 原生 JSON / Markdown 和提交记录：沿用 `archive/run_logs/d9/`，引用其实际路径，不伪造 run_id 或成功记录。

只做规划时不创建运行器、不跑测试、不发请求。未来执行若仅准备数据，离线核对绑定即可；确需适配代码时，仅检查修改文件，按实际影响选 1～3 个现有方法。原问 / 完整版本传递可参考 `scripts.check_d9_e_runtime.RuntimeChecks.test_original_query_and_complete_pairs_preserved`，原生交付与引用可参考 `test_actual_cores_citations_closed_resources_and_stage_records`；未改对应代码且已有通过结果则复用，不因为新增脚本就全量回归。不追加真实“试跑两题”或额外模型探测，再正式重跑同题。

执行完保存 100 次实际结果、统一评分，并把第三步实际记录写入第 13 节；第 14 节保留第三步历史提示，当前容量调整提示在文末第 16 节。前两步文件和第 12 节历史记录不覆盖。

## 8. 第三步评分：先统一口径，最后结合检索结果评价

### 8.1 评分对象和依据

只对真实最终交付答案评分。原生 `answered`、`citation_status=valid` 是交付 / 引用定位状态，不能自动转换为内容通过。合法恢复后的最终交付按实际答案评价，中间失败和费用保留；未交付的内部草稿不能替代失败结果。

依据为原始问题、第一步固定 PDF、全部官方参考和第 7.3 节运行前核定的内容口径。支持同一要点的其他真实原文也可以接受，不要求答案只引用 gold 中唯一的 chunk。检索 gold 的“完整命中”也不能直接替代答案完整性评分。

全部结果生成完，再隐藏组别、按与得分无关的固定顺序混排后进行同一标准的内容评价，评分完解盲对应模式。直接阅读已有答案、PDF 和证据，不新增外部 LLM judge 请求，不把 gold 发回业务模型让它重答。

### 8.2 每份答案记录的项目

| 项目 | 判定 |
|---|---|
| 核心完整通过 | 原问全部必要要点正确、范围 / 条件 / 单位明确，关键结论有原文支持，没有改变结论的实质错误 |
| 部分通过 | 有正确内容，但漏必要数据集、协议、条件、数值或比较对象；承认缺口也仍然是部分通过 |
| 未通过 | 核心错误、关键编造、可答题无依据拒答，或最终无有效交付 |
| 关键结论支持 | 实际引用原文是否支持关键事实，独立于引用 ID / 版本定位是否合法 |
| 额外无据陈述 | 记录核心之外仍存在的无据细节；核心通过不能据此宣称全文无幻觉 |
| 执行状态 | 原生交付、运行失败和未执行分别保留 |
| 成本 | 实际耗时、tokens、请求、搜索 / 阅读 / JS、重试 / 纠错 / 恢复次数；未知值保持未知 |

主要二值成绩只把“核心完整通过”计为 1，部分通过和未通过计为 0；同时保留三档结果，不把部分通过按整题正确统计。未执行属于缺测，不能假装模型已经答错或答对；主表必须同时展示计划分母 50 和实际完成数，批次未完成时不声称完整验收结果。

43 道可答题与 7 道官方不可答题分开：

- 可答题须回答所问内容；只说“当前片段不足”不能当正确拒答。正确回答 No 的 E50-026 / 031 归入正常答对。
- 不可答题须准确限制所选论文的信息范围，不编造所问事实。仅声称“本次没检索到”不自动视为已经证实论文未提供；评价其结论、解释与范围。
- 所有主表沿用生成前冻结的标签 / 范围，不能看到某组答案后把缺失要点改成可选。确有无法消除的原题歧义，按已预先记录的接受边界处理并披露。

### 8.3 两组质量、配对和成本

主结果至少包括：

1. 每组计划 50、实际尝试 / 交付 / 失败 / 未执行数，以及完整通过、部分通过、未通过数量。按计划给出完整通过数 / 50，同时明确完成度。
2. 43 道可答题与 7 道官方不可答题的结果；类型分组按第 2 节实际数量，不新凑跨论文或追问题型。
3. 同题配对：两组都完整通过、只有 Agent 完整通过、只有固定 RAG 完整通过、两组均未完整通过。缺测单列；有失败交付的题保留其执行失败标记，不用不同成功子集直接比较总分。
4. 两组完整通过差用百分点描述；关键结论支持和额外无据陈述另列，不将定位 valid 写成语义正确率。
5. 每组总 tokens、平均 / 中位耗时、实际聊天 / embedding / rerank 请求，以及 Agent 搜索 / 阅读次数。包含失败和正常重试成本，不把未知用量补成 0；不重复计入前两步的解析 / 文档 embedding / 独立检索实验成本。

两组有各自正常流程与预算，若差异主要来自超时、上下文容量或其他产品设置，按实际原因说明，不直接归结为 Agent 推理能力。单次结果描述这 50 道题的表现，不声称已经证明模型稳定性或普遍显著提升。

### 8.4 和第二步结果一起解释

第三步完成后再统一评价，不因中间个别失误暂停修改。第二步有可比排序的仅 40 题，关联时使用这些题的对应记录；E50-001 及不在检索分母的九题仍保留在问答主表，不给它们虚构旧检索成绩。

按实际证据和轨迹区分：

- 首次检索已取得必要证据，固定 RAG / Agent 是否正确完整利用。
- 首次不足，Agent 是否通过正常补搜 / 补读获得新证据，并最终补齐答案。
- Agent 取得更多证据但仍漏答、误解，或已知道缺口仍结束。
- 两组都没有取得证据、原文没有所问信息，或发生执行异常。
- 质量相近时，多轮路径增加了多少耗时和 tokens。

“Agent 比固定 RAG 多通过几题”和“其中哪些题确实由新增取证补齐”分开描述。个别成功案例、工具调用更多或检索覆盖提高，都不单独证明总体问答收益；同样如实保留 Agent 反而漏答或成本更高的题。

本轮到联合评价与第 13 节回写结束；不因结果接着修改提示词、补跑旧题、增加模型 / 工具消融或升级三次重复。

## 9. 需要评测多少题、多少次

| 阶段 | 不同题目数 | 配置 / 次数 | 计划结果数量 | 是否调用生成模型 |
|---|---:|---|---:|---|
| 论文准备（已执行） | — | 10 篇均 ready，复用实际版本 | 10 个固定论文版本 | 本轮新增准备调用 0；旧成本见第 12 节 |
| A 检索对照（已执行） | 计划 41 | 4 配置；实际完成 40 题，1 题脚本失败 | 计划 164，实际 160 份排序 | 本轮不补跑；旧请求见第 12 节 |
| B 第三步问答对照（本次规划） | **50** | **2 组，每题 1 次** | **100 次完整问答** | 未来按提示执行时计全部正常流程请求；本次写规划为 0 |
| 可选升级：B 每题 3 次 | 仍是 50 | 2 组 × 3 次 | 300 次完整问答，较本轮多 200 次 | 未纳入默认执行 |
| 工具消融 / 模型对比 / 框架迁移 | 本轮不安排 | — | 0 | 0 |

**不是 41 + 50 = 91 道新题。** 检索实验用的是这同一份 50 题中的 41 题；不同题目始终只有 50。本次规划新增执行范围只有 **100 次完整问答及统一评价**；10 篇准备与已有 160 份排序均复用，E50-001 的旧排序不补跑。

当前顺序：复用第 12 节已完成产物 → 离线补齐内容评分范围和固定运行输入 → 执行 100 次完整问答 → 统一评分并结合已有检索记录评价 → 回写第 13 节结束。A 不为 B 挑参数，运行期间不因个别错误调整提示或创建其他对照组。

## 10. 与现有代码怎样衔接

前两步的导入、映射与独立检索已完成。本轮以第 7 节的当前问答入口和结果统计为主；下面的独立检索组件仅供解释已有结果，不重新执行旧批次。

- [agent_comparison.py](/D:/course/paper-research-assistant/paper_assistant/agent_comparison.py:118) 已有 `run_current_case`，可复用其独立运行与成本统计逻辑；需要让运行器按本文件固定两组顺序调用，不能走旧共享首轮检索的 legacy 配对。
- [d9_runtime.py](/D:/course/paper-research-assistant/paper_assistant/d9_runtime.py:105) 已提供两种正式模式，可承接本次原题、论文版本、新会话和实际运行日志。
- [run_qasper_evaluation.py](/D:/course/paper-research-assistant/scripts/run_qasper_evaluation.py:145) 可参考“从官方原题读取、隔离 gold、已有论文配对”的流程；不能直接随机抽 50 覆盖本文名单，也不能把旧 direct_answer 输出要求或官方 token-F1 当成本批人工内容完整性评价。
- [run_retrieval_comparison.py](/D:/course/paper-research-assistant/scripts/run_retrieval_comparison.py:227) 当前主要是旧开发集的 top-k 前缀比较，**不是现成四检索配置开关**；后续只需为本批接一个窄的评测入口，复用现有 dense / BM25 / RRF / rerank，不重构业务检索器。
- [hybrid_search.py](/D:/course/paper-research-assistant/paper_assistant/hybrid_search.py:14) 已有两路 top-20、RRF 常数 60、融合池及 rerank 轨迹，适合在实验 A 中复用同一批候选，避免重复请求。
- 后续运行输入 / 结果沿用项目现有普通 JSON 与逐题日志；本次不提前新增代码、审计、哈希快照、保护层或单独验证报告。准备 / 运行记录可追加本文件，保持问题和来源 ID 可追溯。

## 11. 历史前两步提示词（已执行，本轮不重跑）

本节是前两步的历史执行提示，实际结果见第 12 节。保留作来源说明，本轮不再复制执行；第 14 节保留第三步历史提示，**当前容量调整提示词在文末第 16 节**。

```text
在 D:/course/paper-research-assistant 工作，遵守当前 AGENTS.md。执行 docs/v3/d6-plan.md 的前两步：第5节“10篇论文准备、入库与证据标注”和第6节“四种检索策略对照”。读取第1～6、9～11节；第7～8节只作后续背景，本次不执行。保留已有工作区修改，不提交推送，不继续修D5错题，不调整Agent提示或业务检索策略。

固定选题：按第4节的50个question_id，从 eval/qasper/raw/qasper-dev-v0.3.json 对应arxiv_id的qas中提取原始question和全部官方answers。保持原题大小写、拼写和ID，不自编、不改写、不翻译、不随机重抽，不拼成跨论文或追问。题型允许自然偏差。所有gold、标签、正确数值、证据片段和预期章节只留在评测侧，检索侧只接收原始query与论文版本。

第一步：
1. 按P01～P10取得第3节10篇论文的明确版本PDF，先核对候选v1。已有相同PDF可复用；核对官方full_text、选题证据及关键表格，不能只看标题。内容不匹配时确认其他明确版本并记录原因，不默认最新版，不用QASPER全文代替PDF入库。
2. 使用现有 import_runtime.import_pdf 正式入口及当前mineru-api解析/过滤/分块/父子关系/embedding/索引配置入库。允许这10篇必要的下载、真实MinerU解析、文档embedding与索引写入；保留原有缓存与ready复用，别重解析无关论文。记录真实PDF版本、来源、paper_id/parse_revision、ready状态、chunk数、耗时与用量，准备成本单列。
3. 在真实检索前核定50题回答范围和标签，重点处理004/005/010/019/024/028/039/049。026/031是yes_no=false而非unanswerable；官方unanswerable为009/014/021/023/025/039/041，不为它们伪造正向gold。
4. 为当前41道有正向evidence的题建立必要证据组到实际PDF页码/片段/表头单元格、chunk/parent/source_spans的映射。复用qasper_evaluation.build_paragraph_mapping，自动映射失败时核对原文。同要点的有效位置是替代，多个必要要点才要求分别覆盖；跨块证据不能只命中一块就算全覆盖。保留全部有效标注范围，别机械合并所有标注者证据。
5. PDF中有证据、解析后没有的记录parse_missing，保留原分母并据实际覆盖计分，不改解析或只留容易映射的题。版本或参考范围无法确认的先记录未就绪，不换题凑数、不开始依赖未确认标注的检索。标签/资格确需修订要在检索前记录原因和新分母。
6. 保存 eval/qasper/d6-new50-v1/sample.json 和 papers.json 等现有形式的普通数据，回填本文实际版本配对、范围裁定和准备情况。10篇ready、50题绑定和评分依据确认后冻结输入，进入第二步。不加审计、哈希框架、标注平台或独立验证报告。

第二步：
1. 原则上用已冻结的41题，按E50升序、每题一次，范围限本篇唯一paper_id/parse_revision。比较纯BM25、纯向量、混合RRF、混合+rerank四组；参数固定BM25 k1=1.5/b=0.75，两路各top20，RRF常数60/candidate_limit20，融合最多40，rerank整个相同融合池。报告统一top5/top10，不设跨分数体系的统一0.7阈值。
2. 允许写本批窄准备/运行脚本，复用EvidenceSearcher、BM25Index、reciprocal_rank_fusion、RerankClient和prepare_context。旧run_retrieval_comparison主要是旧题top-k，不直接跑其默认main，也不要重新抽样。每题BM25本地一次、dense/查询embedding一次，复用两路生成RRF，对相同融合池仅重排一次；不要为每个配置或每个k重复请求。保留各组真实原文和排名，不能把混合排序当成单路排序。
3. 四组分别从已有排名取top5/top10，统一prepare_context(max_chars=8000)取得Shown。这个Shown是同一上下文准备函数的输出，不是Agent多轮最终上下文；不额外read_context或补邻域。评分代码在排序后读取冻结gold，检索/重排请求不能看到gold。
4. 比较Returned/Shown的单题证据覆盖、宏平均覆盖、全部必要证据命中题数，以及耗时/真实请求成本。空结果按0；服务失败和未执行单列。按共同有效题集比较四组排序效果，并报告计划41和各组有效/失败/未执行数，不拿不同成功子集硬比较。rerank失败的RRF回退必须标明降级，不能写成重排成功。
5. 正常共享计算预期约41次query embedding、最多41次非空池rerank，实际以服务日志为准；总计164份排序而非164次embedding，top5/top10不另发请求。共享物理费用只算一次，逻辑组件耗时单列，别把缓存读取时间冒充在线检索耗时。解析与文档embedding成本归第一步。
6. 保存 artifacts/v3/d6-retrieval-new50-<实际执行日>/input.json、results.json 及现有正常日志，保留尝试/完成状态、候选与用量。已尝试题不额外补跑到通过，不做连通性、计费探测或额外模型裁判。已有结果复用，未执行项如实标明。

验证：纯文档/数据不跑测试。若确需新增/适配评测代码，只检查修改文件，并按实际影响选1～3个相关既有测试方法；已通过且代码未变的结果复用。可用现有假客户端或保存候选回放核对前缀/输入隔离/评分，不额外发真实请求验证运行器，不跑整个模块、目录或全量回归。

范围：本次聊天问答请求必须为0。不要调用d9_runtime.run_question或run_current_case，不执行run_qasper_evaluation的run，不运行第7节100次fixed_rag/Agent完整问答，也不做三次重复、MQE/HyDE、工具消融、模型对比、框架迁移或旧错题回归。真实服务仅限这10篇必要入库及本轮查询embedding/rerank和服务原有必要调用。

完成后在本文追加实际记录：10篇论文准备/版本配对、50题标注范围、实际检索分母、164份计划结果的完成度、四组覆盖/全命中/耗时与成本、主要差异及未就绪项。不要写问答准确率或Agent收益，因为本次没有生成答案。结束于前两步，不自动进入下一阶段，不额外生成审计/哈希/验证报告。
```



## 12. 实际执行记录（2026-11-03，仅第 5–6 节）

### 12.1 范围与完成状态

本轮只执行准备与检索对照，不生成答案，不运行 `d9_runtime.run_question`／`run_current_case`、`run_qasper_evaluation` 的 `run`、100 题 fixed_rag/Agent 问答、LLM judge、MQE/HyDE 或工具消融。聊天侧问答请求为 0，本记录不报告问答准确率或 Agent 收益。

- 固定 50 题：按第 4 节 `E50-001`～`E50-050` 原顺序，从 `eval/qasper/raw/qasper-dev-v0.3.json` 按 `arxiv_id`＋`question_id` 取原始 `question` 和全部官方 `answers`；未改写、翻译、重采样或拼接。
- 50 题中 43 题 answerable、7 题 unanswerable（009/014/021/023/025/039/041）；026/031 为 answerable 的否定结论、无正向 evidence，不进入证据召回分母。
- 有正向 evidence 的 41 题构成本轮检索分母，按 `E50` 升序执行。41 题的 evidence 映射已冻结在 `eval/qasper/d6-new50-v1/sample.json`。
- 10 篇论文全部 ready。检索实际完成 **40/41 题**；失败 **1** 题，未执行 **0** 题。四组计划结果 **164** 份，实际形成 **160** 份排序结果；失败题为 `E50-001`，原因见 12.6，未补跑。

### 12.2 十篇论文的明确版本、入库与准备成本

十篇均采用 QASPER dev 对应的 **arXiv v1** 明确版本，先核对整篇 PDF 的标题、摘要/正文和选题官方 evidence 句，再入库；没有默认取最新版，也没有用 QASPER `full_text` 代替 PDF。候选 PDF 在 `eval/qasper/pdfs/`，下载来源为对应的 `https://arxiv.org/pdf/<arxiv>v1`。

| 论文 | arXiv | PDF | paper_id | parse_revision | chunks | 入库耗时(s) | embedding 请求 | tokens |
|---|---|---|---|---|---|---:|---:|---:|
| P01 | 1908.05828 | v1 | `local_1a357bf97afe42c8be9b67f7ef3ea136` | `r_b22132ec20eee885` | 40 | 66.6 | 4 | 8817 |
| P02 | 1910.06592 | v1 | `local_7e4232cb4ac943f88a87bebd6e676de1` | `r_c88d17ac33361b89` | 17 | 35.2 | 2 | 4462 |
| P03 | 1905.11268 | v1 | `local_75d3419977b543aba949f769ed4e80c0` | `r_1b75f45702948a24` | 36 | 62.2 | 4 | 11352 |
| P04 | 1908.04042 | v1 | `local_de778b72149f40459f23d379f0682e10` | `r_ac85fcb80198fcf5` | 27 | 43.3 | 3 | 6256 |
| P05 | 1912.03627 | v1 | `local_ab96fffc59414b1aac0afec3c6053e4e` | `r_a5bfa80f55c8e628` | 38 | 54.3 | 4 | 11500 |
| P06 | 1912.08904 | v1 | `local_565341cc848a4ec0a3f6333571ede85d` | `r_67088947d869af75` | 16 | 40.9 | 2 | 2982 |
| P07 | 2003.13032 | v1 | `local_1a4939d1674d445aa489f7f9a58b946d` | `r_c9adf6a31fb2e4d2` | 31 | 57.4 | 4 | 7599 |
| P08 | 1910.03634 | v1 | `local_d58a3b658c4143aebb35d7e4e0399171` | `r_e814b1d5f3c7fcc1` | 20 | 55.4 | 2 | 2887 |
| P09 | 1707.06806 | v1 | `local_549e290ff76d476c97eff635b544a574` | `r_e63e8866dbbfcd17` | 26 | 69.0 | 3 | 6764 |
| P10 | 1903.11437 | v1 | `local_738a5d026f674ede874cf82efc4e4439` | `r_0008397a53cc7c94` | 61 | 77.1 | 7 | 16213 |

- 十篇标题在 PDF 中全部命中；摘要精确命中 7/10，未精确命中的 P01/P03/P10 均继续用整篇正文和官方 evidence 句核对，标题与 evidence 句均命中，故仍确认 v1。
- 入库统一走 `paper_assistant.import_runtime.import_pdf`，当前 `mineru-api` 解析/过滤/分块/父子关系/embedding/索引配置，未重解析无关论文。
- 准备阶段（成功入库）合计 wall **561.5 s**、embedding 请求 **35** 次、tokens **78,832**。P10 第一次 MinerU 解析在 **41.98 s** 后返回 “parsing failed, please try again later”，未写索引；同一 PDF 第二次成功（计入上表 77.1 s）。若把失败尝试计入 wall，准备墙钟约 **603.5 s**；失败尝试没有可计的 embedding tokens，未把它伪装成成功成本。
- 准备成本与查询成本分开：上表是文档解析与文档 embedding/索引成本；12.5 的 query embedding/rerank 不重复计入。

各篇证据映射：

| 论文 | 题数 | 原始 evidence 组 | 必要组 | 已映射 | 非证据定位标记 | 有效可接受集 |
|---|---:|---:|---:|---:|---:|---:|
| P01 | 5 | 9 | 9 | 9 | 0 | 6 |
| P02 | 5 | 20 | 18 | 18 | 2 | 6 |
| P03 | 5 | 10 | 10 | 10 | 0 | 6 |
| P04 | 5 | 7 | 7 | 7 | 0 | 6 |
| P05 | 5 | 7 | 6 | 6 | 1 | 2 |
| P06 | 5 | 15 | 13 | 13 | 2 | 6 |
| P07 | 5 | 12 | 8 | 8 | 4 | 5 |
| P08 | 5 | 8 | 8 | 8 | 0 | 5 |
| P09 | 5 | 7 | 7 | 7 | 0 | 6 |
| P10 | 5 | 13 | 13 | 13 | 0 | 7 |

### 12.3 50 题回答范围、标签与证据裁定

- 保留全部官方 `answers`、`annotation_id`、`worker_id`、`yes_no`、`free_form_answer`、`extractive_spans`、`evidence`、`highlighted_evidence`；gold 只在 `sample.json` 的评测侧，检索输入 `input.json` 不含答案、证据文本、表号或数值。
- **E50-004**：官方两个标注分别给 OurNepali 三类、ILPRL 四类；表 1 的 MISC 行在 OurNepali 为 0、ILPRL 为 461，支持“3 类 vs 4 类”。接受集只要求表 1 数据块，不把只讲 OurNepali 三类的段落当完整答案。
- **E50-005**：表 5 是必要证据；表 5 单次运行显示 OurNepali `BiLSTM+CNN(C)` 86.45→`(G)` 86.71（+0.26），ILPRL 80.51→78.24（-2.27）；官方参考答案的 0.16/1.62 与表 5 单行直接读数不一致，可能是跨设置/多次运行汇总。未改写官方答案，本轮只评证据覆盖，不评数值答案。
- **E50-010**：PDF 表 1 的账户数为 96+36+7+32=**171**，推文数为 291,885+112,050+19,065+99,967=**522,967**。参考答案中的 **212** 是 real-news 账户的“Min # of tweets/account”，不是账户总数；第二个标注按字段混淆记录，接受集仍以表 1 数据为准。
- **E50-019**：48,705 本电子书/13 家出版社是 editor-tag 数据；21,243 是 Amazon search-term 覆盖的电子书数；另有 Amazon review keyword 评测集，三者用途不同，不机械合并成一个“数据集大小”。
- **E50-024**：DeepMine 的 Part1/Part2/Part3 是不同评测协议；Part1 的固定短语和多个 speaker setup、Part2 的 text-prompted trials、Part3 的 text-independent setups 分别保留为必要组，不能只命中 Part1 就算完整。
- **E50-028**：File IO、Standard IO 是适配器/开发接口；Telegram bot 及命令行、移动、桌面、Web 是用户端接口；另有一个标注直接列“command line + mobile/desktop/web”。这两类范围作为替代接受集，不把 File IO 当 Telegram。
- **E50-039**：保留原问“English poem description of the painting dataset”，该题官方为 unanswerable；没有为了凑分母改问其他语料规模，也没有伪造正向 gold。
- **E50-049**：官方 evidence 混合训练语料（Europarl/News-Commentary 等）与测试集；接受能明确语料和用途的列举，不把“4 million out-of-domain sentences”误当唯一数据集。
- 官方 evidence 中的 `[leftmargin=4mm]`、`[leftmargin=*]`、`... ::: 方法名/章节名` 共 **9** 组是版式/章节定位标记，不是答案内容；保留在 `evidence_groups` 并以 `status="non_evidence"` 溯源，但不进入必要组或接受集。未把它们误记为 `parse_missing`。
- 41 题均有至少一个全部必要组已映射的接受集；`parse_missing` 为 **0**。另有跨块证据组，按实际 chunk_ids 全子集判定，命中一块不算全覆盖；表题只作定位，表数据块才计表格证据。

### 12.4 四组检索设置与输入冻结

- 输入：`artifacts/v3/d6-retrieval-new50-20261103/input.json`，41 题、10 个唯一 `(paper_id, parse_revision)`，只含原始 question 与版本，不含 gold。
- A1 纯 BM25：`k1=1.5`、`b=0.75`、top20；A2 纯向量：`EvidenceSearcher` 单路 top20；A3：同一 A1/A2 候选做 RRF，`rank_constant=60`、`candidate_limit=20`、融合上限 40；A4：对**完全相同的 40 项融合池**整体 rerank，不截断后再重排。
- 每题一次 dense/query embedding；A3/A4 复用该结果；仅对非空融合池发一次 rerank。没有按配置或 top-k 重复请求；top5/top10 只从已保存排名切片。
- Shown 统一用 `prepare_context(max_chars=8000)`。实际函数对含 `source_spans` 的结构化候选启用既有 8192-token 预算，`selection_version` 为 `rank-deduplicate-full-chunks-token-v1`；因此 Shown 可能比 top-k 更短，记录中保留 `shown_chars`、`omitted_evidence` 与原因，未改业务上下文函数。
- 评分在排序完成后由独立离线脚本读取冻结 gold；检索/重排请求看不到 gold。没有统一 0.7 分阈值。

### 12.5 四组结果（共同有效题集）

| 组 | 共同有效题 | top5 Returned 覆盖 | top5 Shown 覆盖 | top5 全命中 | top10 Returned 覆盖 | top10 Shown 覆盖 | top10 全命中 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A1 纯 BM25 | 40 | 0.6150 | 0.5335 | 24/40 | 0.8388 | 0.5447 | 32/40 |
| A2 纯向量 | 40 | 0.7754 | 0.6279 | 29/40 | 0.9054 | 0.6529 | 34/40 |
| A3 BM25+向量+RRF | 40 | 0.7867 | 0.7492 | 30/40 | 0.8388 | 0.7554 | 32/40 |
| A4 同一融合池+rerank | 40 | 0.7417 | 0.6435 | 29/40 | 0.8300 | 0.6497 | 32/40 |

四组均无 rerank 失败/回退；上表 A4 是真实重排结果，不是 RRF 回退。41 题计划中 `E50-001` 失败，四组各缺 1 题，故共同有效题集为 40 题；没有拿 40 题与 41 题混比。A1 在 40 题上 top5/top10 分别只有 24/32 题全命中；A2 的 top10 Returned 最高（34/40），A3 的 top5 Returned 最高（30/40）且 Shown 两组均最高。

**实际请求与耗时（40 题完成部分，另 1 题失败未计）**：40 次 query embedding、可核 **971 tokens**；40 次 rerank、可核 **257,522 tokens**；0 次 LLM/Agent 请求。`E50-001` 在失败前已发出 1 次 query embedding 与 1 次 rerank，但未留存 usage，故“尝试次数”是 41/41，“可核完成请求”是 40/40；没有把未知用量补成 0。四组共享同一次 query embedding、同一融合池与同一次 rerank，top5/top10 不另发请求；可核查询/重排 tokens 合计 **258,493**，全部是真实用量而非缓存读取时间。

耗时（逐题串行、含本地上下文准备与结果序列化）：dense 调用均值 **4.196 s**（其中 embedding **3.727 s**、query **0.243 s**），rerank 均值 **0.421 s**，BM25 均值 **0.0003 s**，RRF 均值 **0.0032 s**，单题 wall 均值 **10.690 s**；40 题逐题 wall 合计 **427.6 s**。从 05:01:46 到 05:10:50 UTC 的会话时段约 **544 s**，中间含一次本地结果写入的权限重试/重启，不把这个墙钟冒充纯在线检索延迟。准备阶段 78,832 tokens 不在 12.5 内重复计算。

### 12.6 失败、降级与未完成项

- **E50-001 失败（评测侧上下文字段错误，未补跑）**：第一次尝试已经完成 A1/A2/A3/A4 的检索/融合/重排，但在调用 `prepare_context` 时使用了手工 envelope 的 `question` 字段，而该函数要求 `query`，抛出 `ContextError: invalid_question`；结果在写入 rankings 前丢失。修正字段后只继续执行未尝试的 40 题，没有重跑 E50-001，符合“已尝试题不额外补跑到通过”。因此该题四组结果缺失，失败单列；失败前已发出的 1 次 query embedding 与 1 次 rerank 没有留存 usage，未伪统计。
- 其余 40 题均完成；A4 的 rerank 状态 40/40 success，0 次 `rerank_failed_fallback`，0 个空融合池。没有服务连通性/计费探测、额外重试或模型裁判。
- `E50-032` 等题中的 9 个 `[leftmargin=...]`/`... ::: 方法名` 是官方标注的版式/章节定位标记，已作为 `non_evidence` 排除；没有任何正向 evidence 被记为 `parse_missing`（41/41 有已映射接受集）。
- P10 第一次 MinerU 解析失败已单列于 12.2；第二次成功入库，没有用 QASPER 全文替代 PDF。

### 12.7 主要差异与结论边界

- 纯 BM25 对本题集的措辞变化最敏感，top5 只有 24/40 全命中；纯向量在 top10 Returned 最高（34/40），但长 chunk 在 Shown 中更早触发预算。RRF 把两路互补候选压缩成较紧凑的融合块，top5 Returned 最高（30/40），Shown 也最高（top5 0.749、top10 0.755）。
- 对**完整 40 项融合池**做 rerank 后，A4 的 top5/top10 全命中均为 29/40、32/40，低于 A3 的 30/40、32/40；覆盖也下降（top5 0.742 vs 0.787，top10 0.830 vs 0.839）。这不是回退降级，而是重排本身改变了顺序：A3→A4 的 top5 Jaccard 仅 0.459。A4 在 E50-010、E50-049 的 top5 有改善，在 E50-005、E50-049 的 top10 有改善；但 E50-002、E50-037、E50-043 的 top5 从全命中变为不全命中，E50-024 更从 0.8 降到 0.0（多段协议证据被重排打散）。因此本批数据不能得出“rerank 更好”的结论。
- 表数据题差异明显：E50-004 的 A2 在 top5/top10 的 Returned/Shown 都命中表 1，A1/A3/A4 虽在 top10 Returned 命中，但 Shown 为 0；E50-005 只有 A2/A4 在 top10 Returned 命中表 5，Shown 仍为 0；E50-010 A2/A4 在 top5 Returned 命中表 1，A3 要到 top10，A1 未命中。表题命中不等于表数据一定进入 Shown，表题本身也没有被当作表数据。
- Shown 与 Returned 的差距主要来自上下文预算：结构化候选启用既有 8192-token 选择预算，A1/A2 的长正文块在 top10 分别损失 0.294/0.253 的覆盖，A3 只损失 0.083；这说明“排序命中”与“最终可展示证据”在本项目当前上下文中不是同一件事。A1/A2 的 Shown 差异不能解释成排序差，A3 的 Shown 优势也不等于答案质量。
- 本轮没有生成答案，以上只是 41 题冻结证据组上的检索覆盖与上下文展示覆盖；不能外推为 QASPER 问答准确率，也不能外推为 Agent 收益。

本记录只到检索证据覆盖；164 份是四组排序结果数，不是 164 次 embedding。top5/top10 不另发请求，缓存读取时间没有冒充在线检索耗时。未提交、未推送。


## 13. 第三步实际记录（2026-11-03）

### 13.1 批次、实际完成度与入口

本批为 `d6-qa-paired-new50-20261103`，产物在 `artifacts/v3/d6-qa-paired-new50-20261103/`，原生报告引用 `archive/run_logs/d9/`。复用 `eval/qasper/d6-new50-v1/sample.json` 的 50 道原题和 `papers.json` 的 10 篇 ready 配对；50 题全部运行，包括 E50-001。运行使用 `case.local_paper_id` 与 `case.parse_revision`，并与 `papers.papers[arxiv_id].paper_id/parse_revision` 核对；每题只选本篇一个版本，没有把 arXiv ID 当本地 paper_id。没有重新下载、解析、入库或生成文档 embedding，也没有补跑旧检索。

实际按 E50-001～050 升序、奇数题 fixed_rag 先、偶数题 agent 先，两个 mode 相邻但各用独立的新 `conversation_id` / `submission_id`；100 个提交 ID 和 100 个会话 ID 均唯一。计划 50 题、100 个 mode 任务；attempted 100、delivered 100、native `answered` 100、export completed 100；失败 0、未执行 0、缺测 0。这里的“100 次完整交付”不等于 100 题全对，内容三档见 13.3。逐题串行，第一题开始于 2026-11-03T05:33:18Z，最后一题结束于 2026-11-03T06:08:59Z，墙钟 **2,141.1 s（35.7 min）**。

执行前有一次入口预检：`selected_versions` 以 dict 行传入时被 `validate_agent_input` 在预留提交前拒绝（`InvalidQuestion`），未产生模型 / embedding / rerank 请求，也未占用 runtime 提交；改为 `(paper_id, parse_revision)` 元组后从零开始 100 个正常任务。运行器的首次交付判断只接受字符串 answer，而两条路径的 answer 都是结构化对象，导致 100 行一度被标为 failed；随后只从已保存的 `native_reports/` 重新提取 `direct_answer` / `claims` / `text` 并恢复交付状态，**没有重新提交任何题目**；这次恢复不产生新请求，最终 `results.json` 为 `completed`。这不是 100 次之外的重跑。

### 13.2 实际配置与两条路径的真实容量

两组都通过 `d9_runtime.run_question` 正式入口，`library_mode=True`、`top_k=5`、`max_chars=8000`、`conversation_history=[]`、`answer_instructions="Please answer in English."`。实际模型为 `deepseek-flash`，temperature 0.2，`max_tokens=4096`；embedding 为 dashscope `qwen3.7-text-embedding`（1024 维、cosine、profile `ep_cbf0f6caa97b962a`），rerank 为 `qwen3-rerank`；Agent 迭代上限按 `load_agent_max_iterations()` 的实际值 **120**。两组提示版本分别为 `fixed_prepare=v2.20-shared-sufficiency-v1`、`fixed_final=v2.18-normal-term-citation-answer-v1`、`agent=v3.2-native-tool-loop-reading-stop-v1`、`agent_final=v4.0-direct-prose-final-v1`；runtime 为 `d9-native-tool-loop-runtime-v2`。

两条路径保留各自 policy，没有为等预算手工覆盖：fixed_rag 为 request_timeout 30 s、max_network_retries 1、max_repairs 1、retry_per_invoke false；agent 为 request_timeout 300 s、max_network_retries 1、max_repairs null、retry_per_invoke true。实际没有网络重试或 repair（两组均为 0）。

`max_chars=8000` 只是调用参数，真实容量并不相同：fixed_rag 的 `prepare_context` 走既有结构化 **8192-token** 选择预算，Agent 的 trace 报告 `context_capacity_mode=full_request`、`max_chars=null`。因此本文不把这批结果解释为等 token、等证据容量的单变量消融。E50-001 fixed_rag 是已记录的产品行为：候选 5 个，但结构化 token 预算未纳入任一 chunk，`shown_chars=0`，运行以 `Unanswerable` 正常结束，没有崩溃；同一题 Agent 正常取得证据并完整回答。全批 fixed_rag 只有这 1 题 `shown_chars=0`，候选均值 5.26；Agent 候选均值 6.62。

### 13.3 统一内容评价

评分在全部真实交付后、组别隐藏的条件下进行（`blind_review.json` 与独立 `blind_map.json`）。按运行前固定在 `input.json` 的 `d6-qa-content-v1` rubric、实际 PDF 和全部官方参考答案判断；没有 LLM judge，也没有固定证据生成。只有核心要点完整通过计为 complete；部分通过（partial）不算整题正确；未通过（fail）包括核心缺失、核心错误或对可答题的错误拒答。最终 100 份真实交付全部进入评分，无内部草稿顶替。

| 组 | 计划 | attempted | delivered | complete | partial | fail | complete / 50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed_rag | 50 | 50 | 50 | 32 | 9 | 9 | **64.0%** |
| current Agent | 50 | 50 | 50 | 44 | 4 | 2 | **88.0%** |
| 合计 | 100 | 100 | 100 | 76 | 13 | 11 | **76/100** |

按官方可答性拆开（43 可答 / 7 官方不可答）：

| 组 | 43 可答 complete / partial / fail | 7 不可答 complete / partial / fail |
|---|---|---|
| fixed_rag | **26 / 8 / 9**（60.5%） | **6 / 1 / 0** |
| current Agent | **37 / 4 / 2**（86.0%） | **7 / 0 / 0** |

E50-026、E50-031 均按可答且答 No 处理，不把 No 当拒答：fixed_rag 在 E50-026 complete、E50-031 fail；Agent 在 E50-026 partial、E50-031 complete。7 道官方不可答题中，Agent 7/7 complete，fixed_rag 6/7（E50-025 为 partial）；没有把“本次没检索到”自动判成“论文没提供”。

总体 complete 为 **76/100**；fixed_rag 为 32/50，Agent 为 44/50。相对差为 **+24 个百分点**（64.0%→88.0%）；43 道可答题上为 **+25.6 个百分点**（60.5%→86.0%）。这只是本批 50 题的描述统计，不作显著性或稳定泛化声明。

### 13.4 同题四格配对

50 个同题配对（每个 mode 各一次，无缺测）：

| 范围 | 两者都 complete | 仅 fixed_rag complete | 仅 Agent complete | 两者都未 complete | 缺测 |
|---|---:|---:|---:|---:|---:|
| 全部 50 对 | **30** | **2** | **14** | **4** | 0 |
| 43 道可答 | 24 | 2 | 13 | 4 | 0 |
| 7 道官方不可答 | 6 | 0 | 1 | 0 | 0 |

仅 fixed_rag complete 的 2 对是 E50-026、E50-049；仅 Agent complete 的 14 对中，5 对属于“旧 A4 top5 已命中但 fixed_rag 未答全”（E50-004、006、010、019、046），6 对属于“旧 A4 top5 未命中而 Agent 答全”（E50-015、024、036、037、043、047；E50-032 为两者都 complete），另 3 对是旧检索没有记录的 E50-001、025、031。两者都未 complete 的 4 对是 E50-002、005、030、048；其中 E50-030 两边都 fail，E50-002、005、048 至少一边 partial。

这个配对是实际当前两条产品流程的整题结果，不是把两组答案混合后重新打分，也没有用旧排名回放替代本次首次检索。

### 13.5 关键结论支持、额外无据陈述与成本

**关键结论支持（与内容分开放）：**

- 82 份为 supported（fixed_rag 37、Agent 45），15 份为 partial（10 / 5），3 份无可用引用（fixed_rag 3）。原生 citation 检查在 100 份上全部标为 valid、无 invalid；这只能说明引用对象/格式通过检查，**不等于关键结论有原文支持，更不等于整题正确**。例如 E50-001 fixed_rag 没有展示证据，仍被原生检查记为 valid 形态；E50-021 fixed_rag 的正确不可答结论没有引用。
- 76 份 complete 中 75 份同时为 supported，1 份为 no_citation（E50-021 fixed_rag 的不可答结论）；没有 complete 却只有 partial 支持的条目。反过来，partial 中有 7 份为 supported、5 份为 partial；fail 中有 10 份仍带 partial 支持，说明“有引用”和“核心正确”必须分开看。
- 13 份存在核心之外的无据或过度陈述（fixed_rag 9、Agent 4）：fixed_rag 为 E50-001、004、005、010、030、031、037、043、047，Agent 为 E50-002、005、030、049。典型是漏掉比较对象却给出“没有/未报告”的结论、把不同统计口径混成一个数、或把可答题判成不可答。核心通过不等于全文无幻觉；本记录不把 76 份 complete 写成 76 份无任何无据细节。

**本批真实用量（来自原生日志 / `summarize_current_costs`）：**

| 指标 | fixed_rag | current Agent | 合计 / 说明 |
|---|---:|---:|---|
| chat 请求 | 100 | 159 | 259 |
| chat tokens | 406,015 | 1,177,110 | **1,583,125** |
| query embedding 请求 | 50 | 39 | 89 |
| embedding tokens（可核） | 1,229 | 1,010（total=null） | 2,239 known |
| rerank 请求 | 50 | 39 | 89 |
| rerank tokens（可核） | 331,031 | 237,542（total=null） | 568,573 known |
| network 请求 | 200 | 237 | 437 |
| 逐题 elapsed 合计 | 1,069.496 s | 1,026.284 s | 2,095.780 s（会话墙钟 2,141.1 s，含题间读写） |
| 平均 / 中位 wall | 21.390 / 21.508 s | 20.526 / 20.000 s | — |
| Agent search / read_context | —（trace 不计隐式检索） | 39 / 85 | JS 0 |

可核 tokens 合计 **2,153,937**（embedding 2,239 + chat 1,583,125 + rerank 568,573）。Agent 的 embedding/rerank 聚合 `total_tokens` 为 null，不能把 1,010 / 237,542 之外的未记录部分补成 0。fixed_rag 每题各 1 次 query embedding、1 次 rerank，100 次 chat（前置理解 + 终答）；Agent 39 题触发 search、11 题没有 search，85 次 read_context，0 次 JS。相对 fixed_rag，Agent 在本批多 12 个 complete（44 vs 32），chat tokens 多 771,095，network 请求多 37，embedding/rerank 各少 11 次，逐题均值耗时低 0.864 s；这些是当前路径的实际成本/效果差异，不是等预算比较，也不作显著性声明。

旧准备/检索成本引用第 12 节，不重复计入本批：10 篇准备 561.5 s、35 请求、78,832 tokens；旧检索 40 题可核 query embedding 971 tokens、40 次 rerank 257,522 tokens，E50-001 旧失败前 1 次 embedding + 1 次 rerank 的 usage 未知。本批没有把这些旧成本、旧排名或旧答案混入新 QA 的计费与评分。

### 13.6 与第二步已有检索的联合评价

旧检索只有 **40 道**可关联（E50-001 旧脚本字段失败；E50-009、014、021、023、025、026、031、039、041 没有旧检索记录）。这 10 道仍保留在 50 题问答主表，但不为它们虚构旧排名；E50-001 的新 QA 结果单列，不拿旧检索缺失解释成论文缺证据。

在 40 题交集中，旧 A4 top5 **Returned 全命中 29/40，Shown 全命中 25/40**；有 4 题 Returned 已命中但 Shown 未命中（E50-004、006、010、019），当前 fixed_rag 分别为 partial、partial、fail、partial，Agent 全部 complete。按可复核的当前结果：

- **初始已有但没利用（fixed_rag 侧）**：旧 A4 top5 已全命中、fixed_rag 仍未 complete 的有 **5 题**（E50-004、006、010、019、046）；同一 5 题 Agent 均 complete。其中 4 题还有“Returned 命中、Shown 预算未展示”的上下文原因，不能简单归因于模型不会答。
- **Agent 补搜 / 补读后答全**：旧 A4 top5 未命中、Agent 最终 complete 的有 **7 题**（E50-015、024、032、036、037、043、047）；7 题都至少有 search 或 read_context，其中 6 题是仅 Agent complete，E50-032 两边都 complete。
- **取得更多仍漏答**：旧 A4 top5 未命中、Agent 也至少有 search/read、但仍未 complete 的有 **4 题**（E50-002、005、030、048）。
- **已知缺口仍停止（fixed_rag 无补搜步骤）**：旧 A4 top5 未命中且 fixed_rag 未 complete 的有 **10 题**；这是“固定流程没有补搜机会”的描述，不是说系统内部知道缺口却主动停止。E50-032 是唯一旧 A4 top5 未命中而 fixed_rag complete 的题，说明旧排名与本次实际上下文不能机械等同；E50-049 则是旧 A4 已命中但 Agent partial 的反例。

这些分类是实际结果与旧 top5 覆盖的交叉描述，不把旧排名当成当前运行的因果输入，也不把“补搜次数”当成质量本身。

### 13.7 边界、未做事项与结束状态

- 没有改 Agent 提示、检索策略、top-k、rerank 或共享函数合同；没有因 A4 在第二步不优于 A3 而临时关 rerank；没有对旧错题回归、没有新增模型对比、工具消融、LLM judge、服务探测或额外冒烟问答。
- 没有重复 3 次、没有取最好一次、没有在看到前 20 题后提前宣布胜负；部分答案、正常拒答和提前结束均按实际交付评分并保留。
- 旧准备/检索、10 篇论文、索引和文档 embedding 只引用，不重复计费；未记录 usage 保持未知。没有生成审计报告、哈希快照或独立验证报告。
- 本记录完成后即结束第三步；不因结果继续改提示、加题、补跑或开展其他对照。未提交、未推送，工作区修改保留。

## 14. 历史第三步执行提示词（已执行，本轮不重跑）

本节保留已执行的第三步提示，实际结果见第 13 节，本轮不再执行。固定 RAG 容量调整与复测按第 15～16 节安排。

```text
在 D:/course/paper-research-assistant 工作，遵守当前 AGENTS.md。执行 docs/v3/d6-plan.md 第7～8节的第三步：50道官方原题，固定RAG与当前Agent两组各运行一次，共100次完整问答，完成后统一评分并结合已有检索结果评价。读取第1～4、7～10、12～14节。第5～6、11节是前两步历史，不重新执行。保留工作区修改，不提交推送，不修旧错题或改Agent提示/检索策略。

一、复用已有数据和实际版本
使用 eval/qasper/d6-new50-v1/sample.json 的50题和 papers.json 的10篇ready配对，参考 artifacts/v3/d6-retrieval-new50-20261103/input.json、results.json 与D6第12节。全部50题都要运行，包含E50-001；它旧检索失败是评测脚本字段问题，不是论文未入库。本次不补跑旧检索，不下载/解析/重新入库，不生成文档embedding。

按E50-001至050提取原始question、question_id。sample.case.paper_id是arxiv ID，运行必须使用case.local_paper_id与case.parse_revision，并与papers.papers[arxiv_id].paper_id/parse_revision核对；不能把1908.05828之类arxiv ID当成本地paper_id。每题只选本篇一个完整版本配对，不选全部十篇。

问题原文保留，不翻译、改写、重抽或补自编题。参考答案、answerable、类型、evidence_groups、acceptable_sets、表号、正确数值和旧排名只留在评测侧，不送入前置理解、聊天提示或工具参数。正常目录与运行时真实取得的原文按产品现有流程提供。

二、在生成前固定内容评分范围
复用第12.3节已有裁定，补齐仍未明确的必要要点和可接受回答范围，记录在本批input.json的评测侧。无需重做整批证据映射，不另发LLM judge或固定证据生成请求。
重点核对E50-005的平均/最大/表中单一设置数值差异；010按PDF的171账户/522967推文处理，212不是账户总数；004/019/024/028/049沿用已确认的数据集、协议、接口或语料用途范围。026/031是可回答且No，009/014/021/023/025/039/041是官方unanswerable。先用实际PDF和全部参考确定接受边界，不在看到模型答案后放宽标准。

三、固定两组条件
两组均通过当前 d9_runtime.run_question 正式入口，mode分别fixed_rag和agent；library_mode=True、top_k=5、max_chars=8000、conversation_history=[]，普通语言要求都为answer_instructions="Please answer in English."。每个题目/mode使用独立新conversation_id和submission_id。
两组使用相同实际deepseek-flash、temperature、输出上限、论文版本和现有混合检索+rerank。沿用qwen3.7-text-embedding（1024维、cosine）与qwen3-rerank及现有profile，记录实际配置和提示版本。
保留两条正式路径各自的policy/超时/重试/上下文规则，分别记录，不手工覆盖policy以强行等预算。当前输出上限4096、temperature默认0.2；Agent轮数按load_agent_max_iterations实际值（默认120），不照抄旧5轮。结构化文本可能采用token预算，记录真实Shown与上下文限制，不把max_chars参数当成两组严格相同的最终证据容量。
第二步中A4不优于A3也不改变本次既定配置：不要临时关闭rerank、改top-k、换检索器或调整提示来抬高分数。

四、执行100次完整问答
按E50升序逐题执行：奇数题fixed_rag先，偶数题agent先。每题两组相邻，均独立走正常前置理解与问答，不共享答案、工具历史或Agent补读材料，不用第二步排序回放代替真实首次检索。
允许当前Agent正常自主search/read_context/JS/结束，不强制读某个parent、表格或固定工具次数。保留正常网络重试、纠错、必要收尾，所有前置理解、聊天、query embedding、rerank与工具调用成本计入本组。100次完整问答不是100个HTTP请求。
每个mode调用前保存attempted及唯一提交ID，返回后立即保存完整原生结果和history_report/history_markdown，再做统计。可新增窄入口tmp/d6_qa_new50_paired.py，复用原生保存与summarize_current_costs；不要为传会话参数改共享函数合同，也不要走legacy共享首轮检索。
单题部分正确、合理拒答或提前结束都保存并继续，不现场修复重跑。包装器出错优先从已有原生日志恢复结果，不再次提交同题补日志。共同认证/额度/资源故障则保留进度并停止无效付费调用；未执行项单列。续接只做未尝试mode，已尝试的结果直接复用，不换新提交ID补跑到通过。不升级三次重复，不取最好一次，不根据前20题提前宣布胜负。

五、全部结果后统一评分
评分时隐藏组别，按运行前固定的原问、实际PDF、必要要点和全部参考，分别判核心完整通过/部分通过/未通过；原生执行失败、未执行另记。只有核心完整通过计为1，部分通过不算整题正确。
关键结论的原文支持单独核对，citation_status=valid和answered不等于内容正确。核心外无据细节单独记录，不能把核心通过写成全文无幻觉。只评价真实最终交付，不拿内部草稿顶替失败答案；合法恢复按实际交付评分，中间成本保留。
可答题只说片段不足不是正确拒答，026/031答No属于正常答对；不可答题要准确限制论文信息范围、不能编造，仅“这次没检索到”不自动证明论文没提供。无法消除的原题歧义按预先记录的接受边界处理。
主报每组计划50、实际完成度、三档内容结果和完整通过数/50；再列43可答/7官方不可答、同题四种配对结果与缺测、关键结论支持、额外无据陈述、总tokens/平均和中位耗时/真实请求/搜索阅读次数。差异用百分点，不承诺显著或稳定泛化。
结合已有检索结果分析“初始已有但没利用”“Agent补搜补读后答全”“取得更多仍漏答”“已知缺口仍停止”和成本。旧检索有效题仅40，关联时用实际对应记录；E50-001及九道非检索题不虚构旧排名，仍保留在50题问答主表。
不新增独立LLM judge、服务探测、额外冒烟问答、fixed-evidence生成、模型对比、工具消融或旧题回归。真实调用范围仅100次正常流程内请求及既有策略内重试/纠错/必要收尾。

六、验证、产物和结束
纯文档/数据不跑测试。若确需适配运行器，只检查修改文件，按实际影响选1～3个相关既有测试，已通过且代码未变的直接复用；不用额外真实模型或embedding请求验证运行器，不跑全模块/目录/全量回归。
在新的 artifacts/v3/d6-qa-paired-new50-<实际执行日>/ 保存普通input.json、results.json，引用archive/run_logs/d9/原生日志。旧准备和检索成本引用但不重复计入本批，未知用量保留未知。结果到达即保存，不生成审计、哈希快照或独立验证报告。
完成后把第三步实际记录写入D6第13节，保留第12节历史和文末本提示词，说明真实已完成数、统一评价、同题差异及全部已知成本。联合评价后结束，不因结果继续改提示、加题、补跑或自动开展其他对照。
```

## 15. 固定 RAG 按模型完整请求容量选取证据与复测规划

**状态：仅完成规划，未实施、未跑测试、未发起真实请求。** 本轮拟修改当前页面 / library 模式的固定 RAG 上下文容量，再用 D6 同一批 50 道原题各跑一次新版 fixed_rag。D6 的旧 fixed_rag 与 Agent 结果直接复用。

### 15.1. 判断与目标

**好做，属于局部改动，但不等于替换一个 8192 常量。** 项目已经有模型上下文长度配置、完整请求 token 计数、输出预留和超容量处理基础；不需要重建索引、重新分块或修改检索器。

目标是让当前固定 RAG 从“结构化证据预先限制在 8192 token”改为“按配置模型的完整输入容量放入当前已取得的证据”。保留固定流程的一次检索、top-5、现有父块补读、来源范围、生成 / 修复与引用校验。它仍然是固定 RAG，不增加 Agent 工具循环。

本次去掉的是独立的固定证据窗口，**不是让请求无限长**。模型完整上下文上限、输出空间与既有计数余量继续生效。

### 15.2. 代码与真实结果依据

| 位置 | 当前行为 | 对本次修改的意义 |
|---|---|---|
| [context.py:19](/D:/course/paper-research-assistant/paper_assistant/context.py:19) | `token_context_options` 对结构化来源 / 候选默认返回 `max_tokens=8192`；registry 的 `full_context_mode` 可跳过此默认值 | 不宜全局改成一个更大常量，应由当前固定流程选择模型容量模式 |
| [context.py:240](/D:/course/paper-research-assistant/paper_assistant/context.py:240) | `select_context(max_chars=None)` 已支持不使用旧证据字符 / token 窗口 | 只删 token 默认仍可能落回 8000 字符限制，需要同时使用正确的内部模式 |
| [rag.py:31](/D:/course/paper-research-assistant/paper_assistant/rag.py:31) | 公共参数仍验证 `max_chars` 为 1～8000；先选证据，再构造生成请求 | 公共调用参数可保留，内部用有效容量模式，不能直接删除公共校验 |
| [rag.py:125](/D:/course/paper-research-assistant/paper_assistant/rag.py:125) | 当前历史恢复 / 父块补读部分依赖 `context.max_tokens is not None` | 若只让 max_tokens 消失，会意外跳过原来存在的补读，必须解除这种错误耦合 |
| [generation.py:94](/D:/course/paper-research-assistant/paper_assistant/generation.py:94) | 生成时组装 system / user；格式修复会追加原响应和修复消息 | 完整请求容量必须覆盖首轮和修复，不只算正文长度 |
| [rag.py 的 citation_repair 路径](/D:/course/paper-research-assistant/paper_assistant/rag.py) | 引用修复在生成模块之外直接发请求 | 这一请求也要用同一容量规则，不能漏接 |
| [message_fit.py](/D:/course/paper-research-assistant/paper_assistant/message_fit.py) | 已有 `context_fit_budget`、`count_request_tokens`，使用模型长度、97% 余量和输出预留 | 复用计数与预算，不新建一套容量框架 |
| [agent.py:79](/D:/course/paper-research-assistant/paper_assistant/agent.py:79) | Agent 已按完整请求控制容量，但裁剪还涉及历史组、工具消息 | 本轮不迁移或修改 Agent；固定 RAG 只复用基础预算 / 计数，并保留适合检索排名的裁剪顺序 |

D6 的真实证据：

- 两组的模型上下文配置实际为 **1,048,576**，生成上限为 **4096**；固定 RAG 仍使用独立的 8192-token 证据选择预算。
- E50-001 fixed_rag 的 5 个候选中，首块触发 `token_budget` 后，其余为 `after_budget_stop`，最终 `shown_chars=0`；Agent 取得正文后答全。该问题不是模型实际容量已经耗尽的证据。
- D6 的记录成绩为旧 fixed_rag **32/50 complete**、Agent **44/50 complete**。上下文容量不同，是解释这 24 个百分点差距时必须考虑的因素。
- 现有 D6 原始结果在 [results.json](/D:/course/paper-research-assistant/artifacts/v3/d6-qa-paired-new50-20261103/results.json)，各题 `native_report` 中保留实际检索、上下文、消息与调用。

### 15.3. 改动边界与预期文件

只给当前 `d9_runtime.run_question(..., mode="fixed_rag", library_mode=True)` 接入完整请求容量。兼容现有参数和旧 CLI / 离线检索实验的显式有限窗口；不全局改变 `token_context_options` 默认，也不把所有含 8192 的测试和回退值一起删除。

| 文件 | 计划改动 |
|---|---|
| `paper_assistant/d9_runtime.py` | 仅在当前 library fixed_rag 分支传入明确的内部容量选项；外部 API、Agent 分支和其他 mode 不变 |
| `paper_assistant/rag.py` | 新增默认关闭的关键字选项，例如 `use_model_context=False`；当前入口开启后走模型容量，保留一次检索 / top-5 / 既有补读与引用流程 |
| `paper_assistant/generation.py` | 放置或接入一个固定 RAG 用的完整请求适配函数，首轮与格式修复共用；供 rag 的引用修复复用 |
| `paper_assistant/context.py` | 优先直接复用已有 `max_chars=None`；仅在新模式的裁剪记录 / 一致性校验确有需要时小改，不影响旧显式预算语义 |
| `scripts/check_d9_e_runtime.py`、`scripts/check_generation.py` | 在相关既有方法内补充容量、修复和引用同步断言，不新增测试框架 |

`message_fit.py` 的现有预算与计数优先直接导入复用；不复制一份计数器，不引入新 tokenizer，也不把 Agent 的历史 / 工具裁剪循环整段搬进固定 RAG。

本轮不改 BM25 / dense / RRF / rerank、top-k、分块、PDF、父子关系、模型、temperature、输出上限、超时、重试额度、正文提示词、回答格式或充分性判断。请求 / 容量策略版本可更新，区分新旧行为；D6 历史文件保持原样。

### 15.4. 实施步骤

#### 15.4.1 当前固定入口显式选择模型容量

在 `rag.answer_question` 增加一个内部关键字选项，默认保留旧行为；由 d9 runtime 仅在 `library_mode=True` 且 `mode="fixed_rag"` 时开启。

外部继续接受原来的 `top_k=5, max_chars=8000`，避免改变调用合同。开启后，在公共输入校验结束后确定内部有效模式：

- 当前 run 的来源 registry 使用已有 `full_context_mode=True`。
- 普通上下文、来源限定上下文和来源不可用的空上下文，都使用内部 `max_chars=None`，不再次传回旧 8000 字符窗口。
- 结构化候选不因自动识别 `source_spans` 再回到 8192 证据窗口。
- 普通旧调用和明确指定有限预算的上下文工具仍按原规则运行。

这是内部流程选择，不增加页面开关、环境变量菜单或多套常驻基线实现。

#### 15.4.2 保留历史恢复和父块补读

固定 RAG 已有的历史引用恢复与 parent / child 补读不能依赖“是否存在 max_tokens 字段”来决定是否执行。

将“是否执行原有结构化补读”和“如何限制容量”分开：在新模式下，原来应该恢复 / 展开的证据仍然恢复 / 展开，沿用原来的来源限制、排序和 `max_chunks=5` 等规则。只改变能够容纳多少已取得原文，不提高 top-k，不把补读改成无限，不自动读全部论文。

补读函数已经通过 `context.max_chars` 和 registry 取得容量选项；需确认这条传播链使用新模式，不被某个默认参数重新切回 8192 / 8000。

#### 15.4.3 用模型容量计算完整请求预算

使用 `client.settings.context_length` 和 `client.policy.max_tokens`，直接复用：

```python
budget = context_fit_budget(client.settings.context_length, client.policy.max_tokens)
request_tokens = count_request_tokens(messages)
```

现有输入预算规则为：

`min(floor(context_length × 0.97), context_length - output_tokens)`。

实际模型长度为正整数时按实际值；未配置时保留 `message_fit.py` 原有的 8192 **模型上下文回退**。这个回退与本次要解除的“结构化证据固定 8192”不是同一层，不能把未配置当成无限或在代码里硬编码 1,048,576 来掩盖配置缺失。

完整计数包含真正发出的 system、问题、conversation_context、实际证据和元数据、允许引用 ID、来源限制、已有 assistant 响应及修复说明。固定 RAG 没有工具定义，不为它附加 Agent 的工具 schema。

计数沿用项目现有估算器和余量，输出上限保持 4096；不把“放开输入证据”实现成增大输出 max_tokens。

#### 15.4.4 只在完整请求确实超容量时裁剪

首轮先构造与原先相同格式的完整消息；请求在模型预算内就完整保留当前检索 / 补读证据，不先按独立证据窗口删除。

只有完整请求超过实际预算，才按**当前候选的低优先级尾部**删除完整证据块并重新计算。保留 rank 语义，不照搬 Agent 因历史时间顺序而优先删除旧消息 / 首块的策略。保持 chunk 原文完整，不切断 HTML 表格、公式或正文句子，不引入额外摘要模型。

每次裁剪后同步：

- 实际 messages 中出现的证据与允许引用集合。
- context 的 shown_evidence、allowed_citation_ids、shown_chars、reading_origins、omitted_evidence 和 candidate_count 等现有字段。
- 来源 qualification 的 shown_ids 及最终 result 中的对应记录。
- generation_attempts / citation_repairs 保存的实际消息，避免“日志称已展示但请求中未发送”。

原始 search.results 保留，不覆盖检索快照。裁剪不扩大 source 许可，也不允许被删掉的证据继续得到引用授权。

如果新模式下 empty_selection_reason / max_chars / max_tokens 的组合与现有 build_messages 校验不一致，最小适配这一个新模式，正确记录完整请求超容量原因；旧有限窗口的语义和检查继续保留。没有证据可展示时仍按原来的正常缺证据流程处理；如果非证据消息本身就超出模型容量，沿现有 `request_too_large` 类错误结束，不发必然超限的请求。

#### 15.4.5 首轮、格式修复、引用修复统一接入

固定 RAG 的三个发送位置都需要使用同一容量适配：

1. `generate_draft` 的首轮生成。
2. `generate_draft` 的格式 / 截断修复：追加原响应和修复说明后重新计数。
3. `rag.py` 的 citation_repair：包含来源指令、原响应和引用错误说明，重新计数。

优先在 generation 中提供一个薄的固定请求适配函数，rag 的引用修复复用它；不导入 Agent 主循环来实现固定请求裁剪，不改 Agent 的 `fit_agent_request` 行为。

修复继续沿用既有次数和预算。裁剪后若模型引用了已移除的 ID，原有引用校验继续拒绝，不能为了提高通过率放宽引用规则。

#### 15.4.6 记录实际容量模式

新 fixed_rag 结果明确记录 `context_capacity_mode="full_request"` 及实际模型长度、输出预留、请求预算 / 计数、因完整请求超限删掉的 ID。使用现有 result、generation_attempts 和 citation_repairs 承载，字段按最小需要增加，不新建观测平台。

实际 context 的 max_chars / max_tokens 应表达有效模式；外部传入的 8000 只是历史调用参数，不能再被解释成当前正文已经限制在 8000 字符内。版本字段能区分 D6 原策略与本轮新策略，正文提示字符串保持不变。

### 15.5. 离线验证：默认两个相关现有方法

本次写规划不运行任何测试。未来实施时，默认只调整并运行以下两个现有方法：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records scripts.check_generation.GenerationChecks.test_structural_error_repairs_once_in_same_budget_and_evidence_scope
```

在这些现有方法的相关 fixture / 断言中覆盖真实行为，不只检查某个常量变大：

- 使用 D6 E50-001 已保存 native report 的检索候选，或等价的结构化大块 fixture，回放到新 fixed 路径和假客户端。配置模型长度 1,048,576、输出 4096；完整请求能装下时，实际模型消息应含原文，不再因旧独立 8192 窗口得到零正文。
- 固定检索仍是一次、top-5，既有父块补读 / 来源限定仍执行；不因 max_tokens 消失而漏掉补读，也不额外增加检索或真实 embedding。
- 用较小模型容量离线强制超限，确认整块裁剪优先保留高 rank，消息、context、qualification 和引用集合一致，完整请求计数不超过有效预算。
- 格式修复追加 assistant 文本与修复说明后重新计算；引用修复同样覆盖。不以无限增长修复消息绕过容量计算。
- 模型容量缺失时使用既有 fallback，旧显式 `max_tokens=8192` 的纯上下文选择验证继续成立。不能把全文件 8192 断言统一改掉。
- Agent 调用和消息行为保持；已通过且对应代码未变的验证结果直接复用。

如果实际小改了 `source_scope.py`，才按影响补一个现有来源范围测试，例如 `scripts.check_scoped_answering.SyntheticSourceFlowChecks.test_page_one_body_and_mixed_chunk_are_excluded_before_both_modes_answer`，总计仍按 1～3 个方法控制。测试失败或有明确跨模块影响再扩大，不默认跑模块、目录或全量回归；语法 / 导入检查仅针对改过的文件。

离线验证全部使用已有原文 / 候选和假客户端，真实聊天、embedding、rerank 请求为 0。不要额外付费“试跑一题”后再把同题纳入正式复测。

### 15.6. 真实复测：只新增 50 次新版 fixed_rag

#### 15.6.1 固定数据和复用对象

用 D6 同一份 50 道官方原题，**E50-001～E50-050 全部保留**，原题与 question_id 不变：

- `eval/qasper/d6-new50-v1/sample.json`。
- `eval/qasper/d6-new50-v1/papers.json` 的十篇 ready 实际配对。
- `artifacts/v3/d6-qa-paired-new50-20261103/input.json` 中冻结的内容评分口径。
- `artifacts/v3/d6-qa-paired-new50-20261103/results.json` 及原生报告：复用旧 fixed_rag 50 份和旧 Agent 50 份结果。

sample 的 `paper_id` 是 arXiv ID。实际调用使用 `local_paper_id` 和 `parse_revision`，并与 papers.json 对应配对核对。Gold、正确数值、旧答案、旧成绩、预期表号与补读位置仍只在评测侧，不输入运行。

不重新准备论文、入库、索引、四配置检索或 Agent 问答。不只挑五道旧容量失误题跑分；全 50 题用于观察收益与回退，避免将容量变化只在挑选的有利案例上评价。

#### 15.6.2 实际运行

按 E50 升序每题只运行一次新版：

```python
d9_runtime.run_question(
    case["question"],
    [(case["local_paper_id"], case["parse_revision"])],
    mode="fixed_rag",
    library_mode=True,
    top_k=5,
    max_chars=8000,
    conversation_history=[],
    answer_instructions="Please answer in English.",
    # 独立新 conversation_id / submission_id，沿用当前正式入口
)
```

相同模型、temperature、输出上限、embedding / rerank、top-k、来源、既有父块读取规则与 fixed_rag policy；只改变本次明确的证据 / 请求容量策略。实际模型上下文长度和运行时间记录在新 input 中，不能把模型别名在不同时间的变化完全排除掉。

每题独立新会话 / 提交 ID，调用前记 attempted，返回后先保存完整原生结果及历史路径，再提取指标。部分通过、合理拒答和容量不带来改善也按实记录，不修改后补跑。包装器错误从已保存 native report 恢复，不为补日志重发；未尝试项与失败单列。

**真实新增范围：50 次 fixed_rag 完整问答**，包括正常前置理解、生成、query embedding、rerank 和既有修复 / 网络重试。没有异常时通常对应约 100 次聊天、50 次查询 embedding 和 50 次 rerank，实际以日志为准；这不是 50 个 HTTP 请求。

Agent 代码和实际请求行为不变，因此其 D6 50 份结果直接复用，不再产生 50 次 Agent 问答；也不重复跑旧 8192 fixed_rag。这样新增完整问答是 50 次，而不是 100 或 150 次。

#### 15.6.3 重点诊断包含在 50 题内，不额外加跑

| 题目 | 重点观察 | 不预先承诺的结果 |
|---|---|---|
| E50-001 | 原来 5 候选却 Shown=0；现在完整请求可容纳时是否实际传入原文 | 不把“原文进入消息”自动判成答对 |
| E50-004 | 实体类别表是否进入实际消息，能否区分两个数据集 | 不把命中表题当成表数据已展示 |
| E50-006 | baseline 列表的必要项是否因更完整上下文而覆盖 | 不强制补读某个已知正确 parent |
| E50-010 | 数据规模表、171 / 522967 与字段解释是否得到支持 | 不在业务输入中提示正确数字 |
| E50-019 | 数据来源、出版社和日志范围是否完整 | 不只看答案变长 |

这五题只是事后解释的重点，全体 50 题均按同一策略、相同评分口径运行；不为它们建专用逻辑。

### 15.7. 怎样评价这次修改

#### 15.7.1 三列结果，只有一列新增运行

| 对象 | 数据来源 | 本次新增运行 | 用途 |
|---|---|---:|---|
| D6 旧 fixed_rag（8192 证据窗口） | D6 已保存 50 份报告 | 0 | 看容量策略变化带来的实际差异 |
| 本轮新 fixed_rag（模型完整请求容量） | 本轮 50 次正式问答 | **50** | 新的固定流程基线 |
| D6 当前 Agent（full_request） | D6 已保存 50 份报告 | 0 | 在减少容量差异后，重新观察剩余质量 / 成本差距 |

复用 D6 已冻结 rubric 和已记录分数作为主口径；新 50 份先按同一标准评价，再揭示旧标签和配对，避免按预期改善给分。完整通过、部分通过、未通过、关键结论支持和额外无据陈述分开，native answered / citation valid 不等于内容通过。

D6 已知边界判分（如 E50-005 / 026 / 036）保留说明，不在本轮单方面放宽新 fixed_rag 标准。如果以后统一修正某项内容标准，应对旧新结果一并离线重评，不以更换 rubric 伪装容量收益；不为此重跑模型。

#### 15.7.2 必须比较的内容

- 旧 / 新 fixed_rag 完整通过数 / 50、部分 / 未通过及执行完成数；旧错→新对和旧对→新错分别有多少。
- 新 fixed_rag 与旧 Agent 的同题配对及完整通过差，实际差值可能缩小、不变或反向，不预设结果。
- 实际消息的证据数 / shown_chars、完整请求 token 计数、因容量删块的数量及 zero-Shown 题数；旧候选快照和最终真正发送的消息分开看。
- 原有父块补读是否继续执行、检索次数是否仍是固定一次、来源 / 引用是否一致。
- 聊天 tokens、平均 / 中位耗时、query embedding / rerank、重试 / 修复与失败成本。旧 D6 入库、独立检索和旧问答费用只作参考，不加进新批次账。
- 旧新固定 RAG 的原始检索排名如果不同，明确记录，避免把服务时点、重排变化或单次模型波动都归因于容量。

#### 15.7.3 结论边界

若新 fixed_rag 改善，先确认对应题确有更多有效原文进入实际请求；有证据进入但仍答不全的情况也保留。不能只凭改了模式名就说限制已解除，也不能因为扩大容量而保证准确率提高。

本轮容量调整减少了一项独立证据窗口差异，但两条流程仍有提示、工具、实际证据量、超时和决策机制差异，因此不称为完全等预算的 Agent 消融。

本批单次重测用于工程对照。模型别名和服务时点可能影响新旧结果，记录实际时间 / 配置并结合消息内容解释，不把所有分数变化归因于唯一因素。没有额外重复、模型对比或工具消融。

### 15.8. 产物与实施顺序

未来执行时使用一个新的普通批次：
`artifacts/v3/d6-fixed-full-context-new50-<YYYYMMDD>/`。

- `input.json`：固定 50 题 / 本地版本、D6 来源、实际模型上下文与输出预算、fixed policy、容量策略版本、评分标准引用。
- `results.json`：计划 50、每题 attempted / delivered / failed / not_executed、原生路径、真实容量与用量、内容评价和旧新配对。
- 原生 JSON / Markdown、提交记录沿用 `archive/run_logs/d9/`；不覆盖 D6 报告，不另建审计、哈希快照或验证报告。

顺序：局部实施 → 两个相关现有本地方法 → 用旧候选离线确认容量与引用链 → 同一批 50 题真实新版 fixed_rag 一次 → 统一评分并与 D6 两列比较 → 回写本文件第 15.9 节并结束。没有“mock 完成后再另起规划决定真实题目”的步骤。

本次仅在 D6 追加容量调整规划，不创建实施代码或运行器，不更新 D6 历史成绩，也不发真实请求。

### 15.9. 实际执行记录（2026-11-03）

#### 15.9.1 实际改动与离线验证

本次只在 `mode=fixed_rag` 且 `library_mode=True` 的路径启用完整请求容量；旧调用默认路径、旧显式 `max_chars`/`max_tokens` 语义和 Agent 行为未改。改动文件为 `paper_assistant/context.py`、`paper_assistant/evidence_reading.py`、`paper_assistant/generation.py`、`paper_assistant/rag.py`、`paper_assistant/d9_runtime.py`，对应测试为 `scripts/check_d9_e_runtime.py` 与 `scripts/check_generation.py`；未改 `source_scope.py`。

- `context.py`：`context_capacity_mode=full_request` 时 `build_messages` 使用 token 预算语义；旧显式预算仍按原分支处理。
- `evidence_reading.py`：为 full request 增加 `full_request_mode` 触发父块补读；仍是一次检索、top5 候选、`max_chunks=5` 父块读取和原来源限制，没有改成全文无限读取。
- `generation.py`：新增薄适配 `fit_fixed_request`，首轮、格式修复和 `rag` 的 `citation_repair` 共用；使用 `message_fit.context_fit_budget` / `count_request_tokens`，按 `client.settings.context_length` 与 `client.policy.max_tokens` 对完整 messages 计数，保留 97% 余量、4096 输出预留和 `message_fit` fallback。超限时只从低优先级尾部整块删除证据，不切表格/公式、不摘要、不新增模型调用；删除后同步 `shown_evidence`、`allowed_citation_ids`、`omitted_evidence`、`shown_chars`、`reading_origins`、`candidate_count`，并由 `rag` 同步 `source_qualification.shown_ids`。无可删证据仍超限时使用既有 `request_too_large` 类错误。
- `rag.py`：公开 `max_chars=8000` 仍可传入并原样记录，但 library fixed 内部有效 `max_chars=None`、`max_tokens=None`、`context_capacity_mode=full_request`；完整请求适配后的实际 messages 保存进生成记录，原始 `search` 快照不覆盖。`d9_runtime.py` 只在 library fixed 设置 `registry.full_context_mode=True`，并传入 `use_model_context=True`；Agent 路径不设置该分支。
- 策略版本为 `d14-fixed-full-request-capacity-v1`，模型上下文 `1048576`、输出预留 `4096`、输入预算 `1,017,118`；公开 `top_k=5`/`max_chars=8000` 合同未变。

离线只运行了两个指定现有方法：`RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records` 通过（29.329 s），`GenerationChecks.test_structural_error_repairs_once_in_same_budget_and_evidence_scope` 通过（1.032 s）。另用 D6 E50-001 已有候选做容量对照：1,048,576 上下文/4096 输出下完整请求 `26,622` tokens、5 个候选全部保留并实际进入消息；强制按 8192 上下文计算时 5 个证据块全部被尾部整块删除、Shown 变为 0（剩余 base 请求 1,704 tokens）。这确认旧窗口导致的空证据不是“没有检索结果”。离线验证未发真实模型、embedding 或 rerank 请求；旧显式 8192 与 fallback 测试保留。

#### 15.9.2 新版 fixed_rag 50 题执行

批次目录为 `artifacts/v3/d6-fixed-full-context-new50-20261103/`，`input.json` 固定 E50-001～050、每题 `local_paper_id`/`parse_revision`、原题、原 rubric 引用和上述容量策略；`results.json` 记录 50 个 task。实际运行时间为 2026-11-03 15:41:26–15:56:26（Asia/Shanghai，UTC 07:41:26–07:56:26）。

- 计划 50、attempted 50、completed 50、delivered 50、failed 0、not_executed 0；50 个独立 submission/conversation，无重试、无 repair、无补跑。
- 50 次固定流程对应聊天请求 100（每题正常前置理解 + 回答各一次）、query embedding 50（1,229 tokens）、rerank 50（331,031 tokens）、网络请求 200；50 份原生 JSON/Markdown 保存在 `archive/run_logs/d9/`，批次内复制到 `native_reports/`。
- D6 旧 fixed_rag 50 份和旧 Agent 50 份全部复用，旧 fixed/Agent 均未重跑；旧费用不进入新批次账。

#### 15.9.3 三列内容评分

沿用 D6 冻结 rubric `d6-qa-content-v1`；新 50 份先按原题、原 rubric、实际来源块/实际 PDF 抽查与官方参考评分，再与旧标签配对。完整 = 所有 core requirements 满足；部分 = 部分满足或保留实质歧义；未通过 = 核心缺失、方向错误或可答题拒答。

| 对象 | 完整 | 部分 | 未通过 | 完整率 | answerable 完整 | 官方 unanswerable 完整 |
|---|---:|---:|---:|---:|---:|---:|
| D6 旧 fixed_rag（8192/8000 窗口，复用） | 32 | 9 | 9 | 64.0% | 26/43 | 6/7 |
| 本轮新 fixed_rag（完整请求容量） | 40 | 3 | 7 | 80.0% | 33/43 | 7/7 |
| D6 旧 Agent（复用） | 44 | 4 | 2 | 88.0% | 37/43 | 7/7 |

新 fixed 的 3 个 partial 为 E50-026、E50-036、E50-048；7 个 fail 为 E50-005、E50-024、E50-030、E50-031、E50-037、E50-043、E50-047。新 fixed 的 citation support 为 supported 38、partial 10、no_citation 2；native citation 检查 50/50 valid；额外无据/口径不一致记录 1 条（E50-010 的 144 与表 1 合计 171 的差异）。

旧 fixed → 新 fixed：

- 旧错/部分 → 新完整共 9 题：E50-001、E50-002、E50-004、E50-006、E50-010、E50-015、E50-019、E50-025、E50-046（旧 fail 2 题、旧 partial 7 题）。
- 旧完整 → 新非完整 1 题：E50-026（旧 complete，新 partial）。
- 旧部分 → 新部分 2 题：E50-036、E50-048；旧未通过 → 新未通过 7 题；没有旧完整 → 新未通过。
- 完整数 32→40（+8）；answerable 完整 26→33（+7），官方 unanswerable 完整 6→7（+1）。

新 fixed 与旧 Agent：

- 两边完整 38 题；新 only 2 题：E50-002（旧 Agent fail）、E50-049（旧 Agent partial）。
- 旧 Agent only 6 题：E50-024、E50-031、E50-036、E50-037、E50-043、E50-047。
- 两边均非完整 4 题；完整数 40 vs 44，净差 -4（answerable 完整 33 vs 37，差 -4；官方 unanswerable 7 vs 7）。新 fixed 仍低于旧 Agent，未把容量调整解释成 Agent 等价。

#### 15.9.4 实际消息容量、检索与重点题

50 题全部 `context_capacity_mode=full_request`，实际 `max_chars=None`、`max_tokens=None`，使用 `1,048,576` 模型上下文和 `1,017,118` 输入预算。完整请求 token 计数（含 system、问题、历史、原文元数据、允许引用、来源、修复消息）为最小 6,936、最大 26,622、均值 13,546.4、中位 12,320；45/50 超过旧 8192 上下文阈值，50/50 超过旧 4096 输入预算。没有题目需要尾部删块，`trimmed_chunk_ids=[]`，zero-Shown 0；实际 Shown 为 5～10 块（5:14、6:18、7:8、8:8、9:1、10:1），均值 6.34，Shown 字符总数 316,359。

- 36 题在 top5 之外实际执行了父块补读（Shown>5）；50 题 `source_qualification.shown_ids` 与实际 Shown 完全一致，50 题保存的实际发送 user payload 中 `shown_evidence` 文本与最终 context 一致。
- 旧 fixed 的原始检索 top5 与新 fixed 逐题比较，排名变化 0 题、相同 top5 50 题；没有重入库、重检索或额外四路检索。容量只改变了“已排序证据能带入多少”。
- 旧 fixed 的 zero-Shown 为 1 题（E50-001）；新 fixed 为 0 题。E50-001 从旧 Shown=0/答 Unanswerable 变为 5 块、26,622 tokens，两个数据集的最佳模型均给出；实际消息含原文，但 single-run 不把该结果自动外推到所有题。

重点五题（均包含在 50 题内，无额外运行）：

| 题 | 旧 fixed | 新 Shown | 新请求 tokens | 新结果 | 说明 |
|---|---|---:|---:|---|---|
| E50-001 | fail | 5 | 26,622 | complete | 旧窗口 zero-Shown；新实际含 5 块原文 |
| E50-004 | partial | 6 | 19,570 | complete | 两数据集实体类别区分 |
| E50-006 | partial | 7 | 21,310 | complete | baseline 列表覆盖必要项 |
| E50-010 | fail | 6 | 21,409 | complete | 171/522,967 正确；但 144+32 与 171 口径不一致，记为额外问题 |
| E50-019 | partial | 5 | 14,439 | complete | 出版社、12 个月日志、2,896/33,663 均覆盖 |

#### 15.9.5 成本与耗时

新批次只计本轮 50 次 fixed；旧 fixed/旧 Agent 数字仅作参考，未重复计入。

| 项目 | 新 fixed（50） | 旧 fixed（50，复用） | 旧 Agent（50，复用） |
|---|---:|---:|---:|
| 聊天请求 / tokens | 100 / 593,609 | 100 / 406,015 | 159 / 1,177,110 |
| query embedding 请求 / tokens | 50 / 1,229 | 50 / 1,229 | 39 / 1,010 |
| rerank 请求 / tokens | 50 / 331,031 | 50 / 331,031 | 39 / 237,542 |
| 网络请求 | 200 | 200 | 237 |
| 合计 tokens | 925,869 | 738,275 | 1,415,662 |
| 逐题 elapsed 合计 / 均值 / 中位 | 888.094 / 17.762 / 16.195 s | 1,069.496 / 21.390 / 21.508 s | 1,026.284 / 20.526 / 20.000 s |
| 逐题 elapsed 最小 / 最大 | 10.703 / 36.438 s | 13.515 / 29.843 s | 11.688 / 34.407 s |

旧 Agent 的 embedding / rerank provider `total_tokens` 原记录为 null，表中按已有 `known_total_tokens` 汇总，未把未知值当作 0，也未把旧成本重复计入新账。新 fixed 相对旧 fixed 增加聊天 tokens 187,594（+46.2%），合计 tokens 增加 187,594（+25.4%）；embedding/rerank 请求与 tokens 相同，聊天请求仍为 100，未增加重试或修复请求。批次墙钟 900.221 s（旧 D6 的 2,141.1 s 是 100 个 fixed+Agent task 的墙钟，不能直接当作 fixed 单列对照）。本轮逐题 elapsed 比旧 fixed 少 181.402 s，但这是单次运行，不能单独归因于容量；服务时点、模型输出长度和单次波动仍可能影响。

#### 15.9.6 已知边界与结论

- E50-005：D6 既有官方口径为 0.16/1.62，Table 5 的读数存在已知边界；本轮仍按冻结 rubric 判 fail，新回答“没有量化提升”没有满足官方核心，不为新 fixed 放宽。
- E50-026：官方答案为明确 No；旧 fixed 为 complete，新回答只写“不能确定/未见 case study”，判 partial，是本轮唯一旧完整 → 新非完整；旧 Agent 为 partial。该回归保留，不通过改 rubric 消除。
- E50-036：旧 fixed/新 fixed 均因未明确写出 actor-critic 判 partial；旧 Agent 完整，说明两条流程仍有提示和证据组织差异。
- E50-048：旧 fixed/旧 Agent/新 fixed 均缺 source 短于 target 更少、等长更多的长度统计，均 partial。
- E50-043、E50-047 仍 fail（旧 fixed 也 fail）；E50-031 新 fixed 答 Yes 而官方为 No（旧 Agent 完整）。
- E50-010 核心数字完整，但 144 账户脚注与 171/表 1 合计的口径差需保留说明，不能把“答出 171”当作所有附加陈述都被支持。

结论：本次实际验证的是“library fixed_rag 不再使用独立 8192-token/8000 字符证据窗口，而按模型完整请求容量携带已检索证据”；45/50 题的完整请求确实超过旧 8192 阈值，实际消息也包含原 top5/父块原文，zero-Shown 从旧 1 题降为 0。新 fixed 完整数 40/50，高于旧 fixed 32/50（旧错/部分→新完整 9，旧完整→新非完整 1），但仍低于旧 Agent 44/50（净差 -4）。这是单次工程对照，不声称全部 +8 都来自容量，也不声称已消除与 Agent 的提示、工具、决策机制差异；未重跑、未做重复/消融，未提交或推送。文末第 16 节提示词保留。

## 16. 历史固定 RAG 容量调整与复测提示词（已执行）

```text
在 D:/course/paper-research-assistant 工作，遵守当前 AGENTS.md。执行 docs/v3/d6-plan.md 第15～16节：只为当前 library fixed_rag 解除独立的8192-token/8000字符证据窗口，按模型完整请求容量处理；完成相关离线验证后，用D6原50题各跑一次新版fixed_rag，并复用D6旧fixed_rag/Agent结果比较。保留工作区修改，不提交推送。

先读D6第15～16节及第12～13节、已有sample/papers和QA input/results。目标不是改成无限上下文，也不是简单把8192换成更大常量。不要重建索引、改分块、换检索器或改Agent。

实施：
1. d9_runtime仅在mode=fixed_rag且library_mode=True时开启rag内部的新模型容量选项，旧调用默认保持。外部top_k=5/max_chars=8000合同继续兼容，内部有效max_chars=None，并让本次registry走已有full_context_mode，避免结构化来源再次回到8192或8000。
2. 注意rag当前的restore_conversation_evidence/read_evidence_context依赖max_tokens字段。把原有补读触发条件与容量策略分开，保留原来一次检索、top5、max_chunks=5父块补读和来源限制，不因取消max_tokens而跳过，也不改成全文无限读取。
3. 复用message_fit.context_fit_budget与count_request_tokens，按client.settings.context_length、client.policy.max_tokens对完整messages计数，包含system、问题、历史、原文元数据、允许引用、来源及修复消息。沿用97%余量与输出预留，不增加4096输出限制。未配置模型长度时保留message_fit原有fallback，不硬编码1M，不删除所有8192。
4. 在generation中提供/接入薄的fixed请求适配，首轮、格式修复、rag的citation_repair全部共用。容量内保留已取得原文；超限时按低优先级尾部整块裁剪，不切表格/公式，不引入摘要或新模型。不要搬动Agent历史/工具裁剪循环或修改Agent实际行为。
5. 裁剪后同步实际messages、context、allowed_citation_ids、omitted、shown_chars、reading_origins、candidate_count和source_qualification.shown_ids，保存真正发送的消息。原始search快照不覆盖，删掉证据不能继续得到引用授权。新模式empty_selection_reason与build_messages校验只作必要适配，旧显式预算语义保留。非证据请求也超容量时用既有request_too_large类错误结束。
6. 记录full_request容量模式、实际模型长度、输入预算/计数、裁剪ID和策略版本。正文提示、输出格式、充分性、模型、temperature、rerank、超时和重试额度不改；不全局改token_context_options默认。

离线验证：
默认只调整并运行两个现有方法：
scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records
scripts.check_generation.GenerationChecks.test_structural_error_repairs_once_in_same_budget_and_evidence_scope
用D6 E50-001已有候选或等价结构化大块fixture+假客户端，确认1M模型/4096输出能容纳时，真实消息含原文而非旧8192导致空上下文；强制小容量确认整块裁剪、引用/来源同步、格式及引用修复也按完整请求计数。保留旧显式8192和fallback测试，不批量改常量断言。若实际改了source_scope才按第15.5节补一个相关现有来源方法。只检查修改文件，不全模块/目录/全量回归；代码未变的已通过结果复用。离线不发真实模型/embedding/rerank，也不额外试跑同题后再重跑。

真实复测：
数据使用 eval/qasper/d6-new50-v1/sample.json、papers.json，原题E50-001～050全部保留。实际selected_versions用local_paper_id/parse_revision，不用arxiv paper_id，且每题只选本篇固定版本。Gold、旧答案/成绩、正确数值/表号/parent不送入问题、前置理解或工具参数。
按E50升序，每题新会话/新submission_id，调用正式d9_runtime.run_question：
mode=fixed_rag，library_mode=True，top_k=5，max_chars=8000，conversation_history=[]，answer_instructions="Please answer in English."。
只新增50次完整fixed_rag流程，正常前置理解、生成、query embedding/rerank及既有修复/重试都计费并保存。Agent未改，直接复用 artifacts/v3/d6-qa-paired-new50-20261103/ 中旧Agent50份与旧fixed_rag50份，不重跑它们，不重入库、不重跑四种检索，不做三次重复/模型或工具消融。
重点看001/004/006/010/019的Shown与答案，但它们已在50题中，不额外加跑、不建专用分支。每题先记attempted，返回立即保存完整native与历史路径再统计；不补跑到通过，包装器错误从已有日志恢复，未知费用保留未知。

评价与产物：
复用D6冻结内容rubric，对新50份先统一评分，再对比旧标签，分完整/部分/未通过与执行状态，另核对关键结论支持。不要单方面放宽新fixed标准；D6边界争议保留说明，若以后改标准需对旧新一并离线重评，不能伪装容量收益。
三列报告旧fixed(原32/50)、新版fixed实际成绩、旧Agent(原44/50)，列旧错新对/旧对新错、新fixed与Agent净差、真实消息容量/裁剪/零Shown、tokens/耗时/请求成本。检索排名如有变化单列，单次模型/服务波动不全部归容量，不预设放开后必然提高。
保存新的 artifacts/v3/d6-fixed-full-context-new50-<实际执行日>/input.json、results.json，引用现有原生日志；旧成本不重复计入。回写D6第15.9节实际改动、验证和50题比较，保留文末提示。不要生成额外审计、哈希快照或验证报告。完成后结束，不继续修模型提示、补跑或扩展其他机制。
```

## 17. 第二批新 50 题：独立验证规划（2026-11-03）

### 17.1 本轮目标、已完成事项与范围

第一批 E50-001～050 已经用于排查问题和调整固定 RAG 容量。本轮使用另外 **50 道官方原题、10 篇不同论文**，验证容量调整后的固定 RAG 与当前 Agent 在新题上的表现。第一批的新固定 RAG 为 40/50、原 Agent 为 44/50，仅作为已有结果参考；本轮不预设 Agent 必须领先，也不把新题用来继续逐题修改提示词。

本次已离线选定下列题目，编号 **N50-001～050**，与第一批 E50 编号分开。来源仍为本地官方 `eval/qasper/raw/qasper-dev-v0.3.json`，保留 question_id、问题文字和全部官方标注；不自编、翻译改写或拼接问题。执行时问题必须从官方 JSON 按 ID 取原始字符串，包括尾部空格，不能从 Markdown 表格复制后改写。

选题时核对了当前 `eval/qasper/*/sample.json` 以及 `artifacts/v2`、`artifacts/v3` 下的历史 `input.json`，共 65 个可读取文件；本批 50 个 question_id 均未出现，10 个 arXiv ID 也未出现在这些记录中。另以 arXiv 来源和规范化题名核对当前 `data/index/papers.sqlite3`，10 篇均未入库。这是相对于已检查的本项目记录的新题、新论文，不声称模型预训练未见过。

**本次只做离线选题并追加本规划；未下载 PDF、未入库、未发起解析、embedding、rerank 或问答请求，未修改业务代码。** 后续执行范围包含必要的新论文准备、50×2 次真实问答和统一评价，具体执行提示词见第 18 节。

### 17.2 配比、标签与可以评价的能力

尽量接近上一批实际配比，并增加结果、数值相关问题；允许偏差，不为凑比例改写原题。

| 主类型 | 代码 | 第一批 | 第二批初选 |
|---|---|---:|---:|
| 事实与设置 | F | 11 | 9 |
| 方法、机制与多项说明 | M | 21 | 21 |
| 结果、比较与统计数值 | R | 11 | 13 |
| 官方标注资料缺失 | U | 7 | 7 |
| 合计 | — | 50 | 50 |

原先六类方案中的表格数值、多条件和资料缺失仍是选题方向；官方 QASPER 的这些原题均为单篇、单轮问题，因此**跨论文题和连续追问题仍为 0**，不通过拼题制造两类能力覆盖。R 的 13 题也不等于 13 道必须读表的题。

按当前全部官方标注初步统计：

- 7 道全部标注均为 unanswerable：**N50-004、023、024、029、034、040、041**；其余 43 道至少有一个可回答标注。
- 其中 N50-002、017、021、026 同时存在可回答与 unanswerable 标注；N50-046 存在 Yes/No 冲突，必须在正式问答前核定。
- 16 道题的官方证据包含选中的表格：N50-005、006、008、011、012、013、014、019、020、022、025、026、046、047、048、049。是否真正依赖表格，由固定 PDF 和必要答案要点确认，作为辅助标签；不把一个题重复计入多个主类型。
- N50-039 是官方 No、无正向 evidence，不能仅因缺 evidence 就归为资料缺失。

上面的 U 数量和 answerable 分母是**官方初始标签**，不是最终 PDF 裁定。若 PDF 证实标注错误或范围不同，必须在生成任何答案前记录依据、固定最终范围并更新实际配比；接受偏差，不为保持 7 道拒答题而硬判。问题和 question_id 保持不变，生成后不能再按某组表现改标签。

### 17.3 十篇论文及待确认版本

| 编号 | 论文 | arXiv ID | 原始 qas 序号 | PDF 候选来源 |
|---|---|---|---|---|
| N01 | Short Text Language Identification for Under Resourced Languages | `1911.07555` | 1、3、6、8、9 | [候选 v1](https://arxiv.org/pdf/1911.07555v1) |
| N02 | Mining Supervisor Evaluation and Peer Feedback in Performance Appraisals | `1712.00991` | 1、3、5、6、7 | [候选 v1](https://arxiv.org/pdf/1712.00991v1) |
| N03 | Neural Architectures for Fine-Grained Propaganda Detection in News | `1909.06162` | 1、2、3、5、6 | [候选 v1](https://arxiv.org/pdf/1909.06162v1) |
| N04 | Understanding Car-Speak: Replacing Humans in Dealerships | `2002.02070` | 1、2、4、5、6 | [候选 v1](https://arxiv.org/pdf/2002.02070v1) |
| N05 | Harnessing Cognitive Features for Sarcasm Detection | `1701.05574` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1701.05574v1) |
| N06 | Structured Embedding Models for Grouped Data | `1709.10367` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1709.10367v1) |
| N07 | Argumentation Mining in User-Generated Web Discourse | `1601.02403` | 2、3、4、5、6 | [候选 v1](https://arxiv.org/pdf/1601.02403v1) |
| N08 | Structuring an unordered text document | `1901.10133` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1901.10133v1) |
| N09 | Text Summarization using Abstract Meaning Representation | `1706.01678` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1706.01678v1) |
| N10 | Shallow Syntax in Deep Water | `1908.11047` | 1、2、3、4、5 | [候选 v1](https://arxiv.org/pdf/1908.11047v1) |

上表 v1 仅是准备阶段的候选，尚未下载或核对，不能当成实际已固定的 PDF 版本。执行时优先复用已存在且匹配的 PDF；版本核对完成后才写入实际版本、本地 paper_id、parse_revision 和 ready 状态。

### 17.4 五十道官方原题清单

精确读取方法为 `raw[arxiv_id]["qas"]` 中匹配 question_id 的条目，并核对下表对应的原始序号。下表类型仅供评测分组，不进入业务模型；完整参考从该条目的全部 `answers[*].answer` 获取，不只取第一个标注。

#### N01 · Short Text Language Identification for Under Resourced Languages

arXiv：`1911.07555`；取原始 `qas` 的第 1、3、6、8、9 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-001 | M | What is the approach of previous work? | `012b8a89aea27485797373adbcda32f16f9d7b54` |
| N50-002 | M | How do they obtain the lexicon? | `ca4daafdc23f4e23d933ebabe682e1fe0d4b95ed` |
| N50-003 | F | Which datasets are employed for South African languages LID? | `c8541ff10c4e0c8e9eb37d9d7ea408d1914019a9` |
| N50-004 | U | What are the languages represented in the DSL datasets? | `6415f38a06c2f99e8627e8ba6251aa4b364ade2d` |
| N50-005 | R | Does the algorithm improve on the state-of-the-art methods? | `e5c8e9e54e77960c8c26e8e238168a603fcdfcc6` |

#### N02 · Mining Supervisor Evaluation and Peer Feedback in Performance Appraisals

arXiv：`1712.00991`；取原始 `qas` 的第 1、3、5、6、7 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-006 | M | What summarization algorithms did the authors experiment with? | `443d2448136364235389039cbead07e80922ec5c` |
| N50-007 | M | What clustering algorithms were used? | `4c18081ae3b676cc7831403d11bc070c10120f8e` |
| N50-008 | M | What methods were used for sentence classification? | `197b276d0610ebfacd57ab46b0b29f3033c96a40` |
| N50-009 | R | What is the average length of the sentences? | `e025061e199b121f2ac8f3d9637d9bf987d65cd5` |
| N50-010 | R | What is the size of the real-life dataset? | `61652a3da85196564401d616d251084a25ab4596` |

#### N03 · Neural Architectures for Fine-Grained Propaganda Detection in News

arXiv：`1909.06162`；取原始 `qas` 的第 1、2、3、5、6 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-011 | R | What is best performing model among author's submissions, what performance it had? | `c9305e5794b65b33399c22ac8e4e024f6b757a30` |
| N50-012 | R | What extracted features were most influencial on performance? | `56b7319be68197727baa7d498fa38af0a8440fe4` |
| N50-013 | R | Did ensemble schemes help in boosting peformance, by how much? | `2268c9044e868ba0a16e92d2063ada87f68b5d03` |
| N50-014 | R | What participating systems had better results than ones authors submitted? | `e949b28f6d1f20e18e82742e04d68158415dc61e` |
| N50-015 | M | What is specific to multi-granularity and multi-tasking neural arhiteture design? | `a1ac2a152710335519c9a907eec60d9f468b19db` |

#### N04 · Understanding Car-Speak: Replacing Humans in Dealerships

arXiv：`2002.02070`；取原始 `qas` 的第 1、2、4、5、6 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-016 | M | Is car-speak language collection of abstract features that classifier is later trained on? | `25c1c4a91f5dedd4e06d14121af3b5921db125e9` |
| N50-017 | M | Is order of "words" important in car speak language? | `f88036174b4a0dbf4fe70ddad884d16082c5748d` |
| N50-018 | R | How big is dataset of car-speak language? | `899ed05c460bf2aa0aa65101cad1986d4f622652` |
| N50-019 | R | What is the performance of classifiers? | `d53299fac8c94bd0179968eb868506124af407d1` |
| N50-020 | M | What classifiers have been trained? | `29f2954098f055fb19d9502572f085862d75bf61` |

#### N05 · Harnessing Cognitive Features for Sarcasm Detection

arXiv：`1701.05574`；取原始 `qas` 的第 1、2、3、4、5 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-021 | F | What other evaluation metrics are looked at? | `49c32a2a64eb41381e5f12ccea4150cac9f3303d` |
| N50-022 | R | What is the best reported system? | `bbb77f2d6685c9257763ca38afaaef29044b4018` |
| N50-023 | U | What kind of stylistic features are obtained? | `22732cb9476e521452bf0538f3fdb94cf3867651` |
| N50-024 | U | What traditional linguistics features did they use? | `4e748cb2b5e74d905d9b24b53be6cfdf326e8054` |
| N50-025 | M | What cognitive features are used? | `74b338d5352fe1a6fd592e38269a4c81fe79b866` |

#### N06 · Structured Embedding Models for Grouped Data

arXiv：`1709.10367`；取原始 `qas` 的第 1、2、3、4、5 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-026 | F | Do they evaluate on English only datasets? | `40c0f97c3547232d6aa039fcb330f142668dea4b` |
| N50-027 | M | What experiments are used to demonstrate the benefits of this approach? | `777217e025132ddc173cf33747ee590628a8f62f` |
| N50-028 | M | What hierarchical modelling approach is used? | `2dbf6fe095cd879a9bf40f110b7b72c8bdde9475` |
| N50-029 | U | How do co-purchase patterns vary across seasons? | `7d483077ed7f2f504d59f4fc2f162741fa5ac23b` |
| N50-030 | F | Which words are used differently across ArXiv? | `de830c534c23f103288c198eb19174c76bfd38a1` |

#### N07 · Argumentation Mining in User-Generated Web Discourse

arXiv：`1601.02403`；取原始 `qas` 的第 2、3、4、5、6 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-031 | M | What argument components do the ML methods aim to identify? | `eac9dae3492e17bc49c842fb566f464ff18c049b` |
| N50-032 | M | Which machine learning methods are used in experiments? | `7697baf8d8d582c1f664a614f6332121061f87db` |
| N50-033 | F | How is the data in the new corpus come sourced? | `1cb100182508cf55b3509283c0e2bbcd527d625e` |
| N50-034 | U | What argumentation phenomena encounter in actual data are now accounted for by this work? | `206739417251064b910ae9e5ff096e867ee10fb8` |
| N50-035 | M | What challenges do different registers and domains pose to this task? | `d6401cece55a14d2a35ba797a0878dfe2deabedc` |

#### N08 · Structuring an unordered text document

arXiv：`1901.10133`；取原始 `qas` 的第 1、2、3、4、5 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-036 | M | What is an unordered text document, do these arise in real-world corpora? | `559920ebe19e99e43418c2f0455a0ffdc8edaaa2` |
| N50-037 | M | What kind of model do they use? | `43f56301c5d2f50b6449b582652f2351cbe90e70` |
| N50-038 | F | Do they release a data set? | `68cd8433a75eee7d100dbbfedebbf53873a21720` |
| N50-039 | F | Do they release code? | `0a01341ddca3fe4c8727be7cf5841091c6ca3d0b` |
| N50-040 | U | Which languages do they evaluate on? | `a8c862d8c5da3f060eedf3395a3d0a97fd8a12d8` |

#### N09 · Text Summarization using Abstract Meaning Representation

arXiv：`1706.01678`；取原始 `qas` 的第 1、2、3、4、5 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-041 | U | What is the performance of their method? | `0767ca8ff1424f7a811222ca108a33b6411aaa8a` |
| N50-042 | F | Which evaluation methods are used? | `e8f969ffd637b82d04d3be28c51f0f3ca6b3883e` |
| N50-043 | F | What dataset is used in this paper? | `46227b4265f1d300a5ed71bf40822829de662bc2` |
| N50-044 | M | Which other methods do they compare with? | `a6a48de63c1928238b37c2a01c924b852fe752f8` |
| N50-045 | M | How are sentences selected from the summary graph? | `b65a83a24fc66728451bb063cf6ec50134c8bfb0` |

#### N10 · Shallow Syntax in Deep Water

arXiv：`1908.11047`；取原始 `qas` 的第 1、2、3、4、5 条（从 1 开始）。

| 编号 | 类型 | 官方原始问题 | question_id |
|---|---|---|---|
| N50-046 | R | Does this method help in sentiment classification task improvement? | `f2155dc4aeab86bf31a838c8ff388c85440fce6e` |
| N50-047 | R | For how many probe tasks the shallow-syntax-aware contextual embedding perform better than ELMo’s embedding? | `ed6a15f0f7fa4594e51d5bde21cc0c6c1bedbfdc` |
| N50-048 | M | What are the black-box probes used? | `4d706ce5bde82caf40241f5b78338ea5ee5eb01e` |
| N50-049 | R | What are improvements for these two approaches relative to ELMo-only baselines? | `86bf75245358f17e35fc133e46a92439ac86d472` |
| N50-050 | M | Which syntactic features are obtained automatically on downstream task data? | `9132d56e26844dc13b3355448d0f14b95bd2178a` |

### 17.5 阶段 A：取得 PDF、正常入库并冻结输入

1. 按 N01～N10 取得明确版本的原始 PDF，先核对候选 v1 的题名、正文、官方 evidence 对应段落和关键表图。若不匹配，确认具体其他版本并记录原因；不默认取最新版，不用 QASPER `full_text` 替代 PDF 进入业务索引。
2. 通过当前正式论文准备入口执行必要的解析、分块、文档 embedding 和入库。执行时若已存在匹配且 ready 的完整版本，直接复用，不重复解析或生成文档向量。本次允许为这 10 篇新论文执行这些正常准备请求，准备成本与问答成本分别记录。
3. 为每题绑定本篇唯一完整 `(local_paper_id, parse_revision)`。记录 PDF 实际版本、路径、解析状态和当前索引 profile；业务范围不能把全部 10 篇同时选入单篇问题。
4. 在任何问答生成之前，依据实际 PDF、全部官方答案及 evidence 写好每题内容 rubric：必要要点、条件和单位、允许的同义表述、否定与资料不足的边界、必要表图及正文依据。只标注支持这些要点所需的 PDF 位置及已有 chunk；本轮没有独立检索排名实验，不扩展成四组召回评分的全量映射工程。
5. 如果 PDF 中存在依据而解析结果缺失，记录为解析覆盖缺口；评测依据仍保留真实 PDF 内容，不把这题改成 unanswerable，也不把人工摘录的 gold 塞入索引或本题提示。图像或表格无法被当前流程读取时，如实保留这个系统限制。
6. 50 个原题绑定、10 篇 ready、评分范围核定后，冻结 `eval/qasper/d6-new50-b2-v1/sample.json` 和 `papers.json`，再开始阶段 B。这里只新建本批数据，不覆盖第一批 `d6-new50-v1`。

冻结字段沿用现有形式：`sample.cases[*].paper_id` 可继续表示 QASPER arXiv ID，但运行只能使用 `local_paper_id` 与 `parse_revision`；与 `papers.papers[arxiv_id]` 的实际配对一致。保留全部官方 annotations，并将 PDF 裁定、最终 answerable、rubric 和证据依据留在评测侧。

Gold、题型、预期答案、正确数值、表号和人工确定的 parent/chunk 位置，均不能进入原题、前置理解或工具参数。两条流程仍可使用当前正常提供的论文题名、摘要、目录和运行中自行取得的正文。

### 17.6 评分准备中已发现的具体边界

本轮使用内容标准 `d6-b2-content-v1`，沿用第 8 节“完整 / 部分 / 未通过”的含义，但在生成前统一接受语义等价的事实与结构描述，不要求命中某个架构名称才算完整。枚举题事先说明需要覆盖完整列表还是主要类别；图表中的数字必须注明对应条件，不按官方单个短答案机械匹配。

以下核对基于已读取的官方标注，尚不是 PDF 最终裁定，须在阶段 A 完成：

| 题目 | 需要在生成前固定的范围 |
|---|---|
| N50-002、017、021、026 | 官方可回答 / 不可回答冲突；从实际正文判断是有依据的结论、明确 No，还是确实未提供。N50-026 还需区分英语文本数据和非语言购买数据，不能由未注明语言直接推断非英语。 |
| N50-004、023、024、029、034、040、041 | 逐题核对官方资料缺失是否成立，尤其特征类问题可能与表格中的特征类别存在范围交叉。资料未提供与本次没取得原文分别处理。 |
| N50-006、007、008 | 摘要、聚类和句子分类属于不同阶段；核对算法列表的完整范围，不把一个阶段的方法当成另一个阶段的答案。 |
| N50-009、010、018 | 句长、句子总数、员工数、评论数、车型数和制造商数不能混用；先明确题目主要所问及其他可接受补充。 |
| N50-011、014 | 原问分别问作者提交中的最佳模型、优于作者的参赛系统；官方参考可能把榜首其他团队当成作者最佳，必须以正文和表格区分，不直接抄参考。 |
| N50-012、013 | 特征贡献和 ensemble 收益须区分 SLC/FLC、dev/test、最佳单模型与 ensemble 的比较基准；先确定各必要差值及单位。 |
| N50-019、020 | 分类器名单和不同指标下的性能分开；官方“某模型最佳”的概括与单列指标最高值可能不同，按指定指标及完整表格裁定。 |
| N50-025、028、045、048、050 | 接受覆盖必要结构、机制或特征家族的等价描述；若确实要求完整枚举，先列出必要项，避免事后因少一个术语扣分。 |
| N50-037 | 官方依据主要指向流程图，参考答案仅写 Figure 1；须阅读实际 PDF 确认模型流程，不能把“见图 1”当成充分内容 rubric。 |
| N50-038、039 | “论文未声明发布”与“作者明确说明不发布”分开；确定可接受的否定表述及证据范围，不把官方 No 自动等同于全文已证明绝对不存在。 |
| N50-046、047、049 | 官方 Yes/No、探针任务计数及收益概括存在冲突；区分下游情感任务与 probing、模型对照和表中全部任务，再冻结判断与数值口径。 |

有多个合理解读时，在运行前列出共同适用的接受范围。确实无法裁定的题保留原题并单列争议，汇报计划 50、可裁定数量及争议数量，不把争议强行记成某组失败，也不看到答案后换题。上述规则同时用于两组；不修改第一批冻结评分或用新规则重写旧成绩。

### 17.7 阶段 B：新版固定 RAG 与当前 Agent 的主对照

| 项目 | B1 新版固定 RAG | B2 当前 Agent |
|---|---|---|
| 正式入口 | `d9_runtime.run_question(..., mode="fixed_rag")` | `d9_runtime.run_question(..., mode="agent")` |
| 流程 | 正常前置理解、一次混合检索、既有父块补读、生成与既有必要纠错 | 当前工具循环，自主决定搜索、显式读取和结束 |
| 检索组件 | 当前 BM25＋dense＋RRF＋rerank，top_k=5 | 同一组件，允许自主补搜和补读 |
| 上下文容量 | 第 15.9 节已完成的模型完整请求容量，`full_request` | 当前模型完整请求容量，保留正常历史 / 工具管理 |
| 论文范围 | 本题一个固定本地版本配对 | 相同配对 |
| 会话与语言 | 新会话，空历史，`Please answer in English.` | 独立新会话，空历史，相同语言要求 |
| 运行参数 | `library_mode=True, top_k=5, max_chars=8000` | 相同外部参数，迭代上限使用当前正式配置 |

固定 RAG 的 `max_chars=8000` 只是兼容的外部调用参数，library 模式内部应继续为 `max_chars=None/max_tokens=None`、`context_capacity_mode=full_request`，按模型完整请求预算处理；不能再用旧 8192 窗口作为本轮基线。放开容量也不表示读取整篇全文，仍保留一次检索和现有父子补读范围。

执行前离线读取实际配置并固定到本批 input：相同的生成模型、temperature、输出上限和模型上下文长度，相同的 embedding / rerank 模型、索引 profile，以及两条路径各自现有 policy、超时、重试、runtime、prompt 和容量策略版本。当前起点为 `deepseek-flash`、temperature 0.2、输出 4096、模型上下文 1,048,576，embedding `qwen3.7-text-embedding`、rerank `qwen3-rerank`；实际值以正常配置读取为准，不为探测配置发真实请求。

本批开始到结束不改变业务代码、提示词、top-k、重排和预算。两条路径本来存在工具、提示及请求数差异，本次比较完整流程的质量与消耗，不称为单一工具或等 token 消融。若入口配置仍指向旧容量模式，先解决入口或配置绑定，不把错误基线的结果混入新批次。

### 17.8 真实问答题数、顺序、调用范围与失败处理

正式运行 **50 道新题 × 2 组 × 每组每题 1 次 = 100 次完整问答**。这不是 100 个 HTTP 请求；前置理解、生成、工具循环和正常策略中的重试 / 纠错都属于相应完整流程。

按 N50-001～050 升序逐题串行，奇数题先 fixed_rag、偶数题先 agent；同题两组相邻执行，但各用独立的新 conversation_id / submission_id，`conversation_history=[]`。调用参数中的 query 只取官方原始 question；不共享双方的答案、取证轨迹或首轮检索结果，不把离线 gold 或第一批记录当成运行输入。

必要真实请求分两类记录：

- **阶段 A 准备**：实际新增论文所需的 PDF 获取、解析及文档 embedding；可复用资源不重复处理。
- **阶段 B 问答**：上述 100 次流程内部的聊天、query embedding、rerank、正常工具调用及现有策略内重试和修复。Agent 允许按正式行为直接读目录定位的正文或直接回答，不强制每题搜索、增加阅读次数或读指定表格。

每个 mode 提交前先保存 attempted 和实际输入；返回后立即保存完整原生报告及已有历史路径，再提取统计和评分字段，避免包装器错误丢掉已付费结果。部分正确、拒答或个别取证不足保存后继续，不现场修提示或换模型重答。

单题失败保留异常阶段、已有用量与缺失字段，另一组及后续题正常继续；若认证、额度或共享服务故障影响整批，保存进度并停止无效调用。续接仅处理原批次未尝试的 mode，已尝试结果从原生记录恢复，不自动再次提交同题。

本批不加独立冒烟问答，不重跑第一批，不重跑四组检索，不做模型 / 工具消融或三次重复；不能看前 20 题分数就提前宣布胜负。运行中只因执行条件故障中断，不因某组成绩差提前结束。

### 17.9 阶段 C：统一评分、配对比较和证据解释

全部结果保存后，沿用已有盲评文件形式隐藏模式、按固定顺序混排，对实际最终交付内容直接核对 PDF 和冻结 rubric；评分后再解盲。不增加外部 LLM judge 请求，不把答案或 gold 发回业务模型重新生成。

记录并汇报：

1. 每组计划 50、尝试 / 交付 / 失败 / 未执行数量；完整、部分、未通过及未裁定争议数。明确计划分母和实际可评价分母；完整率不混同检索准确率，部分正确不按整题正确计。
2. 阶段 A 最终核定的可答 / 不可答题表现；9/21/13/7 是初选配比，正式分组采用核定后的实际标签。题型和单篇题数较少时只做描述和案例，不作可靠的分组优越性结论。
3. 同题配对四格：双方完整、仅固定 RAG 完整、仅 Agent 完整、双方不完整；缺测与未裁定争议分别列明。净差用题数及百分点表示，不通过不同成功子集抬高某组成绩。
4. 实际引用对关键结论的支持、额外无据陈述和内部数值矛盾分别统计；native citation valid 只是定位 / 来源校验，不能替代语义支持。
5. 每组实际 Chat / embedding / rerank 请求及 tokens、耗时均值和中位数，Agent 搜索 / 阅读 / JS 次数，以及失败、重试和修复成本；未知用量保持未知。论文准备成本另列，不重复计入每次问答，也不把所有服务 token 相加当实际费用。
6. 从已有原生记录核对实际 Shown、完整请求容量和是否裁剪。对双方有分歧的题，区分“未找到必要位置”“找到但未进入请求”“原文已在请求仍漏答或误解”“Agent 新增阅读补齐”“Agent 仍提前结束”；没有记录支撑时不推断原因，不为解释结果再调用模型。

对比主表只用本批新 50 题两组的实际结果。第一批 80% / 88% 可并列作为开发过程参考，但第一批已用于排错和容量调整，不能将两批包装成 100 道从未参与开发的测试题；若补充合计，只能注明批次、版本和开发 / 新题性质。

本轮用于观察已有差距能否在新题复现，不预设 8 个百分点一定保留，也不预设样本 50 足以确认小差异。单次运行保留波动和评分争议，不把全部差异归因于 Agent 工具能力。

### 17.10 产物、必要验证与结束点

沿用现有数据和报告格式，只产生执行必需的普通文件：

- `eval/qasper/d6-new50-b2-v1/sample.json`：本节 50 道原题、全部官方标注、PDF 裁定和冻结内容 rubric。
- `eval/qasper/d6-new50-b2-v1/papers.json`：10 篇实际版本、准备状态、本地配对及必要入库结果引用。
- `artifacts/v3/d6-qa-paired-new50-b2-<实际执行日>/input.json`、`results.json`：冻结设置、100 个 mode 的状态、答案、原生日志引用、用量和统一评分；复用已有盲评 / 解盲文件结构，不另建评分平台。
- 已有 `archive/run_logs/d9/` 原生报告与历史导出按正常入口产生，必要时在批次中引用或复用现有复制方式。

本次为文档修改，**不运行测试**。后续执行尽量复用现有正式入口、准备组件和报告格式；确需调整批次编排时，只改必要脚本并选 1～3 个覆盖其实际改动的现有测试方法，使用假客户端验证字段、版本绑定和输入隔离。已通过且代码未变的验证直接复用，不全量回归、不为离线检查发真实模型或 embedding 请求，也不为了试包装器额外消耗一道真实问答。

阶段 A 完成后直接执行本节已经安排的真实问答，不再另起“只有 mock、之后再规划真实测试”的一轮。完成后将实际论文版本、最终配比、运行完成度、两组成绩、配对分歧、证据案例和成本回填第 17.11 节。到统一评价结束，不因错题继续改提示、扩展消融或追加调用，不另建 D7、验证报告、审计或哈希快照。

### 17.11 实际执行记录（2026-11-03）

本轮完成阶段 A、阶段 B 的首次 100 次提交、阶段 C 的 79 份有效答案盲评，以及 21 次失败项的重试和补评。首次失败项按新请求重新执行；原失败记录保留在 `results_initial_79.json` 和最终 `results.json` 的 `attempt_history` 中，未覆盖、未删除。重试后最终 100/100 完成，未再修改检索、提示词、工具、分块或 Agent 停止策略；第 18 节提示词原样保留。

#### 17.11.1 阶段 A：论文、PDF 版本与冻结配比

10 篇论文均通过正式 `import_pdf` 入口准备，最终 10/10 `ready`。除 N09 外均使用 v1；N02 首次 MinerU 转换因 `code_caption.sub_type="algorithm"` 的 pydantic 额外字段失败，删除本地缓存 layout 中该字段后从同一缓存重转，未重复上传，首次失败耗时 31.663 秒已单列。

| 编号 | arXiv | 实际版本 | 本地 paper_id | parse_revision | chunks |
|---|---|---|---|---|---:|
| N01 | 1911.07555 | v1 | `local_cfdfbc1c006344aeb0a54d197aaca137` | `r_071836e68f01dbaa` | 14 |
| N02 | 1712.00991 | v1 | `local_aed5055cdd954c8e9bed4985269535be` | `r_f44bb8b117f17ffa` | 38 |
| N03 | 1909.06162 | v1 | `local_d5819c071d90465cb18d7807aa0d5d3e` | `r_900990d2a645f609` | 26 |
| N04 | 2002.02070 | v1 | `local_e4ef7d4c7d3140b99fbb9726205e25cd` | `r_f73a9ea0a1657f47` | 17 |
| N05 | 1701.05574 | v1 | `local_08dad3346d9d4fe486b787c4628b25a6` | `r_b2f87653fecee111` | 50 |
| N06 | 1709.10367 | v1 | `local_f29519b01f6f4da0a67ed7c362861a45` | `r_9c5305c34029c850` | 34 |
| N07 | 1601.02403 | v1 | `local_404cb18a683547deacea55a76763bc23` | `r_b19bf144f8af3edc` | 138 |
| N08 | 1901.10133 | v1 | `local_874a31259984411997ed737da64ce481` | `r_0c4bc25744fbf169` | 10 |
| N09 | 1706.01678 | **v3** | `local_ac1981c0b332415f8208ba88da56fdff` | `r_b7586072c86c965c` | 36 |
| N10 | 1908.11047 | v1 | `local_6a473cbf40234dd598a729886afbc10e` | `r_b9d47abd86bfb9c7` | 29 |

N09 是唯一改版本：候选 v1 页数虽匹配，但官方 evidence 中的“Lead-3 strong baseline”“first-n method”等段落不在 v1 正文；v2 前 6 页与 v1 等价且仍不匹配，v3 含这些段落及 Table 1/2/4，故固定 v3。官方 evidence 92 组最终 92/92 映射到冻结 chunk；不以 QASPER `full_text` 代替 PDF 入库。

最终配比：**45 可答、5 资料不足**；题型 **M22 / F9 / R14 / U5**。官方初选 7 道全 unanswerable 为 004、023、024、029、034、040、041；生成前依据 PDF 改判 **N50-024、N50-041 可答**（024 的语言学特征、041 的 ROUGE 表均有明确依据），最终 U 为 **004、023、029、034、040**。N50-038、039 的官方 No 属于可答否定，不归入资料不足；N50-039、041 没有正向 evidence，分别是可答否定和可答结果题。rubric 冻结为 `d6-b2-content-v1`，冻结时未解决争议 0；接受语义等价、不因缺少某个架构名称机械扣分，表图数值要求带条件。

产物：`eval/qasper/d6-new50-b2-v1/sample.json`、`papers.json`。准备成本单独记录：42 次文档 embedding、110,686 known tokens、入库耗时 437.77 秒；含 N02 首次失败共 469.434 秒。10 次 MinerU 解析请求；解析 token 用量未提供，保持未知；PDF 下载耗时未单独计时，保持 `null`。准备 embedding 不摊入每题问答成本。

#### 17.11.2 阶段 B：首次 100 次、21 次失败与重试

首次批次目录：`artifacts/v3/d6-qa-paired-new50-b2-20261103/`。按 N50-001～050 升序串行；奇数题 fixed_rag 先、偶数题 Agent 先；同题两组相邻但各自使用独立 `conversation_id`/`submission_id` 和空历史。参数固定为 `library_mode=True, top_k=5, max_chars=8000, conversation_history=[], answer_instructions="Please answer in English."`；fixed_rag 仍为 `full_request`（模型 1,048,576、输出预留 4096、输入预算 1,017,118），Agent 保留当前工具循环与停止策略。

首次执行：

- 计划 100，**提交 100，完成 79，执行失败 21，未执行 0**。
- fixed_rag：完成 38，失败 12；Agent：完成 41，失败 9。
- 21 次失败均发生在共享聊天服务异常期间：`http_error`、`request_timeout`、`malformed_response`、`invalid_json`；失败阶段集中在 `conversation_preparation` 或 `generation`，无内容评分。
- 同题两组都失败：N50-024、025、026、035、036、037、038、039（8 题）；仅 fixed_rag 失败：N50-027、033、034、041（4 题，Agent 分别完成/完成/部分/完成）；仅 Agent 失败：N50-040（fixed_rag 完成）。
- 首次批次从 17:07:57 到 18:41:44（Asia/Shanghai），约 94 分钟；服务异常时暂停约 3 分钟，恢复后只续跑未尝试的 mode。

失败项重试：

- 目录：`artifacts/v3/d6-qa-paired-new50-b2-20261103/retry_20261103/`；只取首次 `status != completed` 的 21 个 task/mode，成功题不重跑。
- 每个重试使用新 `submission_id`/`conversation_id`（`d6qa_r2_*`），相同冻结题目、论文配对、模型、参数和 `answer_instructions`；每个 task 的首次失败快照放入 `original_attempt`，重试原始报告单独存放。
- **21/21 重试完成，0 失败**：fixed_rag 12/12、Agent 9/9；重试从 19:10:48 到 19:18:53（Asia/Shanghai），约 8 分钟。重试内容盲评为完整 12、部分 5、未通过 4。
- 最终 `results.json` 为 100/100 完成；原首次 79/21 保存在 `results_initial_79.json`，最终每题的 `attempt_history` 同时保留首次失败与重试记录。这样既补全主表，也不把首次失败伪装成成功。

#### 17.11.3 阶段 C：最终盲评、配对比较与分歧

首次 79 份按隐藏 mode 的哈希顺序评分；21 份重试再次按独立哈希顺序盲评，之后才解盲合并。最终 100 份中 **完整 70、部分 15、未通过 15**；没有执行失败。

| 组 | 计划 | 完成 | 执行失败 | 完整 | 部分 | 未通过 | 完成中完整率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed_rag | 50 | 50 | 0 | 33 | 6 | 11 | 66.0% |
| Agent | 50 | 50 | 0 | 37 | 9 | 4 | 74.0% |

按最终标签拆分：

| 组 | 可答 45：完整/部分/未通过 | 资料不足 5：完整/部分/未通过 |
|---|---|---|
| fixed_rag | 29 / 5 / 11 | 4 / 1 / 0 |
| Agent | 33 / 8 / 4 | 4 / 1 / 0 |

配对四格（50 题全部双方完成）：**双方完整 31、仅 fixed_rag 完整 2、仅 Agent 完整 6、双方不完整 11**。双方完整率分别为 33/50 与 37/50，净差 **+4 题（+8 个百分点）**；配对独占差也是 Agent 多 4 题（6 vs 2）。

- 仅 fixed_rag 完整：N50-018（车型数据集规模；fixed 完整给出 3,209/553/49，Agent 只给 10,867 词）、N50-034（论文实际纳入的论证现象；fixed 完整，Agent 只列模型组件、未指出 pathos 等仍未解决，记部分）。
- 仅 Agent 完整：N50-022（最佳系统；Agent 找到 Table 3 的 MILR/Gaze+Sarcasm）、N50-023（stylistic 特征边界；Agent 补齐 Table 2 类别）、N50-032（实验 ML 方法；Agent 搜索到 SVMhmm 正文）、N50-025（词典构造；Agent 完整，fixed 只答“从数据构建”而漏训练/测试词汇）、N50-036（无序文档；Agent 完整，fixed 未明确“通常不出现在真实语料”）、N50-041（AMR 摘要性能；Agent 完整，fixed 重试仍拒答）。
- 双方不完整：N50-011、012、013、016、017、019、026、038、039、045、047。其中 N50-026（English-only 判定）、N50-038/039（数据/代码发布声明）重试后 fixed 与 Agent 仍有缺失或拒答；N50-019 Agent 只输出 “The”，fixed 记部分。

关键结论支持：fixed_rag 为 supported 37 / partly 11 / not applicable 2；Agent 为 supported 45 / partly 3 / not applicable 2。额外无据陈述两组均为 0；数值矛盾 fixed_rag 0、Agent 1（N50-013 Agent 把 FLC 增益表述为约 +0.063，而官方/表 4 约 +0.044，已记部分）。

重试后的主要变化：fixed_rag 从 27 完整增至 33（+6），Agent 从 31 增至 37（+6）；双方完整从 25 增至 31，双方不完整从 8 增至 11；重试的 13 题中，6 题变为双方完整、3 题仅 Agent 完整、1 题仅 fixed 完整、3 题仍双方不完整。重试纠正了大部分服务失败，但不是所有答案都达到完整：固定 RAG 重试仍有 N50-026/038/039/041 未通过，Agent 重试仍有 N50-026/038/039 部分。

分歧案例按原生 Shown/工具轨迹核对：

1. **N50-022、N50-032、N50-023（Agent 补齐）**：fixed_rag 没有工具循环，答案停在“Unanswerable/仅部分类别”；Agent 实际发起检索并读取目录。例如 N50-022 Agent 查询 “best reported system sarcasm detection F-score comparison baseline”，读取 `parent26` 后取得 Table 3 的 MILR 行；N50-032 Agent 查询 “CRF structured perceptron SVM sequence labeling BIO argument components classifier used”，读取到 p34 的 SVMhmm 正文。这不是单纯“Agent 更会写”，而是 fixed 的一次检索没有把必要表/方法段带入请求。
2. **N50-018（反向案例）**：fixed 完整请求直接包含 3,209 reviews/553 cars/49 manufacturers 的正文，答完整；Agent 虽读了 2 次上下文，但最终只说过滤后 10,867 词并称规模不可得，漏掉必要数字。说明工具次数多不保证覆盖，Agent 也会漏读。
3. **N50-019（Agent 生成截断）**：fixed 给出 KNN 的 macro/micro 数值，但未指出 MLP micro-F1 .6778 高于 KNN .6762，记部分；Agent 做了 2 次读取却只输出 “The” 三个字符，记未通过，属生成/交付失败而非内容推理差异。
4. **N50-047（找到表仍少一项）**：fixed 未找到 Table 3，答 Unanswerable；Agent 读取 Table 3 后仍写 “2 of 10”，与冻结 rubric 的 3 项不一致，记部分。
5. **N50-011（术语边界）**：fixed 答 Unanswerable；Agent 找到 Table 2，给出 MIC-CIS 的 SLC/FLC 数值和排名，但没有完整给出 ltuorp/newspeak 的 P/R/F1 并明确区分“作者系统/总榜首”，记部分。
6. **N50-016、N50-045（共同边界，不作模式归因）**：N50-016 两组都答 Unanswerable；N50-045 两组都把 “from the summary graph” 按生成阶段理解，未给 first-n/实体共现，均未通过。它们是题目语义/证据边界案例，不是 Agent 工具差异。
7. **重试后的 N50-034/025/036/041**：N50-034 fixed 重试补齐论证现象，Agent 只列模型组件，故 fixed 独占完整；N50-025 Agent 完整说明词典含训练/测试词汇，fixed 只答“从数据构建”；N50-036 Agent 明确“无序文档通常不由自然语料产生”，fixed 停在“无法确定”；N50-041 fixed 重试仍答 Unanswerable，Agent 给出 AMR 摘要的 ROUGE 数值。这里仍是证据覆盖/回答充分性差异，不是模型或超参差异。

复核发现 **N50-016** 的官方两条 `yes_no=false` 与冻结 rubric 首条“明确回答是”存在口径冲突；这是生成前未识别、评分后复核发现的问题。为遵守“看到答案后不改标准”，不重写该 rubric、不重评该题；两组该题均按冻结 rubric 记未通过，并作为 **1 项未解决评分争议** 保留，不据此推断两组优劣。其余冻结边界（N50-011 的“作者提交/总榜首”、N50-017 的“论文未直接回答”、N50-019 的“论文称 KNN 四项最好但表 2 micro-F1 为 MLP 最高”、N50-045 的“summary graph”措辞）均在评分说明中保留，不向某一组放宽。

#### 17.11.4 成本与证据使用

以下为最终 100 份完成任务的 known 用量；provider 未返回的 usage 保持未知，不把未知 token 当 0。首次失败尝试和重试成本单列，避免把补跑成本藏进最终答案成本。

| 指标 | fixed_rag（50 完成） | Agent（50 完成） |
|---|---:|---:|
| Chat 请求 / known tokens | 102 / 590,077 | 164 / 1,330,313 |
| Embedding 请求 / known tokens | 49 / 1,273 | 37 / 1,018 |
| Rerank 请求 / known tokens | 49 / 356,704 | 37 / 284,425 |
| 总耗时均值 / 中位数 / 最大 | 21.206s / 19.648s / 54.953s | 60.206s / 21.047s / 934.828s |
| 网络重试 / 修复 | 2 / 0 | 0 / 2 |
| 搜索 / 读上下文 / JS / action steps | 0 / 0 / 0 / 0 | 37 / 85 / 1 / 114 |
| evidence calls（完成项合计） | 0 | 122 |

重试 21 次单独成本：fixed_rag 12 次，chat 24 请求/143,050 known tokens、embedding 12/310、rerank 12/91,175，耗时均值 23.483 秒、中位数 21.227 秒；Agent 9 次，chat 29/233,381、embedding 6/147、rerank 6/47,843，耗时均值 22.430 秒、中位数 19.203 秒。

把首次失败尝试也计入的总尝试成本：fixed_rag 62 次，chat 129/616,110 known（14 个 unknown），embedding 52/1,346，rerank 52/375,913；Agent 59 次，chat 180/1,330,844 known（8 个 unknown），embedding 37/1,018，rerank 37/284,425。首次失败尝试的已知 chat tokens 约 fixed_rag 26,033、Agent 531；重试把失败成本与最终质量分开记录，不用最终 100 份的 token 掩盖首次失败开销。

一次 Agent 调用耗时 934.828 秒（N50-034，完成），另有 635.937 秒（N50-019，完成）和 611.438 秒（N50-040，首次失败、重试 15.938 秒）；这些长尾是总耗时的主要原因之一。准备成本按 17.11.1 单列，未摊入每题。

#### 17.11.5 产物、验证与限制

产物：本批 `input.json`、最终 `results.json`、`results_initial_79.json`（首次 79/21 快照）、`retry_20261103/input.json`、`retry_20261103/results.json`、`retry_20261103/blind_review.json`、`retry_20261103/blind_map.json`、`retry_20261103/judgments.json`、`blind_review.json`、`blind_map.json`、`judgments.json`、`unblinded_scores.json`；原生报告分别位于 `native_reports/` 与 `retry_20261103/native_reports/`。最终 `results.json` 每题保留 `attempt_history`，首次失败与重试均可追溯。

本批未重跑第一批 E50，也未把第一批成绩混入新题主表；第一批 40/50（新 fixed）与 44/50（旧 Agent）只作为开发过程参考，不包装成 100 道从未参与开发的测试题。

本次为数据、评分和文档回填；首次问答/重试按已授权任务执行，盲评和合并只读已有 PDF、冻结 rubric、答案和原生轨迹，没有新增 LLM judge、消融或额外问答。**未运行测试**（无业务代码或提示词修改）。

限制：最终 100/100 是首次 79 份加 21 份重试的结果，不是 100 次首次提交全部一次成功；21 次首次执行失败仍是真实的服务稳定性记录。79+21 的合并样本和 50 题规模仍不足以支持分组优越性结论；N50-016 的口径争议保留；服务波动和单次生成长尾不能全部归因于容量或 Agent 工具能力。到统一评价结束，不再改提示、补跑其他题或扩展消融。

## 18. 给 DeepSeek 的第二批新 50 题执行提示词（文末当前提示）

以下供后续执行本规划时使用；本次仅写规划，没有执行这些请求。

```text
在 D:/course/paper-research-assistant 工作，遵守当前 AGENTS.md。执行 docs/v3/d6-plan.md 第17节的第二批新50题规划，最后将实际结果回填第17.11节，保留本提示词。只处理本批，不新建D7，不提交推送，保留工作区已有修改。

目标：
使用N50-001～050这50道官方新题，比较第15.9节已经实现full_request容量的library fixed_rag与当前Agent。两组在本批各跑50题、每题一次，共100次完整问答。第一批E50结果仅作历史参考，不重跑、不混入新题主成绩。

先读：
D6第17～18节，以及第15.9节的实际容量行为；查看现有d9_runtime.run_question、准备入口、第一批sample/papers和批次input/results格式。读取实际配置即可，不发连通性、计费或模型探测。不得继续修改检索、提示词、工具、分块或Agent停止策略。

阶段A：原题与10篇论文准备
1. 按第17.3～17.4节的arxiv_id、原始qas序号和question_id，从eval/qasper/raw/qasper-dev-v0.3.json精确取得50条原始question和全部answers，保留原字符串，包括尾部空格。不要重新随机选题、翻译、自编、拼接跨论文或追问题。编号固定N50-001～050，主类型初选F9/M21/R13/U7，允许PDF核定后变化，不为配比硬判。
2. 按N01～N10取得并确认具体版本PDF，先核对候选v1的正文和关键表图；不默认最新版、不用QASPER全文代替PDF入库。若已有匹配PDF或ready版本直接复用，否则按当前正式流程解析、分块、生成文档embedding并入库。新论文准备请求属于本批执行范围，成本另记。
3. 绑定每题唯一local_paper_id/parse_revision，核对papers里的实际配对。sample.paper_id是QASPER arxiv ID，不能当本地入库ID。记录实际PDF版本、路径、索引profile和ready状态。
4. 在任何问答生成前，核对全部官方参考及实际PDF，按第17.6节裁定标注冲突、表格数值口径和接受范围，写好每题必要要点、同义表述、否定与资料缺失边界，冻结d6-b2-content-v1。官方初始unanswerable是004/023/024/029/034/040/041；最终标签必须依PDF，不为保持7题而坚持错误参考。
5. 特别核对002/017/021/026的可答性冲突，011的作者模型与榜首团队，012/013的任务和指标，019的分类器性能，037的Figure1流程，038/039的发布信息，046/047/049的表格及Yes/No/任务计数。接受必要结构的等价描述，不因缺一个架构名称机械扣分。确有无法消除的争议先记录，不看两组答案后改标准或换题。
6. 保存eval/qasper/d6-new50-b2-v1/sample.json和papers.json。Gold和rubric留在评测侧，不能把正确数值、预期表号或人工定位parent/chunk塞进问题、前置理解或工具参数。PDF证据解析缺失如实记录，不注入人工摘录补题。10篇ready、50题版本绑定及评分范围固定后进入阶段B，不再另起真实测试规划。

阶段B：100次真实配对问答
1. 调用正式d9_runtime.run_question，query取官方原题，selected_versions只含本题一个完整本地配对；library_mode=True，top_k=5，max_chars=8000，conversation_history=[]，answer_instructions="Please answer in English."。固定RAG内部应继续full_request，不能恢复旧8192-token/8000字符证据窗口；外部max_chars参数仍按当前兼容合同传入。
2. 两组用相同实际生成模型、temperature、输出上限和模型上下文设置，相同embedding/rerank模型与索引；记录当前runtime、prompt、容量策略版本及双方现有policy。当前起点是deepseek-flash/0.2/4096/1048576、qwen3.7-text-embedding、qwen3-rerank；实际配置以正常读取为准，批次内固定，不手工抹平双方流程差异。
3. 按N50升序逐题串行，奇数题fixed_rag先、偶数题agent先；每个mode独立新conversation_id和submission_id。两组不共享答案、取证或检索回放，不强制Agent多搜索、读指定表格或调用指定工具。
4. 每个mode提交前保存attempted，返回即先保存完整native对象及原生日志/历史路径，再抽统计，避免付费结果丢失。普通错误答案、部分正确和拒答照常保留后继续，不改提示或重复到通过。包装器错误从已有结果恢复，不再提交同题。
5. 本批范围是新论文必要准备＋50×2正常问答内部的聊天、query embedding、rerank和既有策略内重试/修复。不额外发真实冒烟、LLM judge，不重跑旧50题或四组检索，不加消融、三次重复或按分数早停。共享服务不可用时保存进度，续接只跑未尝试mode。
6. 复用现有编排与导出，必要脚本调整只做1～3个覆盖其改动的现有离线测试，假客户端验证字段和输入隔离；不修改未涉及的代码，不全量回归，不为离线检查发真实请求。

阶段C：评分与回写
全部答案保存后按冻结rubric统一盲评，随后解盲；直接阅读已有PDF和原文，不新增模型判分请求。记录完整/部分/未通过、执行失败/未执行及未裁定争议，分母写明；引用定位valid不当成内容正确。
主表比较本批fixed_rag与Agent各50题，列可答/不可答表现、双方完整/仅fixed完整/仅Agent完整/双方不完整，以及关键结论支持、额外无据事实和数值矛盾。对分歧题依据实际Shown和工具轨迹区分定位缺失、上下文遗漏、理解错误、Agent新增阅读和提前结束，不靠猜测，也不为归因再调用模型。
分别汇总真实Chat/embedding/rerank请求和tokens、耗时均值/中位数、搜索/阅读/JS及失败重试费用；准备成本单列，未知用量保持未知。两组token不同，如实解释质量与资源消耗，不把token总量当实际费用。
保存artifacts/v3/d6-qa-paired-new50-b2-<实际执行日>/input.json、results.json，沿用已有盲评文件及原生日志方式；回填D6第17.11节实际PDF版本、本地配对、最终配比、完成度、成绩、配对案例、容量与成本。旧80%/88%仅并列作开发参考，不能将两批宣传成100道未见测试集。结束后停止，不接着修提示、挑最好结果或扩展实验；不另生成审计、哈希或验证报告。
```
