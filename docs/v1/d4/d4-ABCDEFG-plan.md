# D4 执行计划：分块、版本、入库与证据检索

制定日期：2026-10-01。依据：[plan-codex.md](/D:/course/hello-agents-study/log/plan-codex.md)。按依赖执行 D4，不按旧日历跳过。

当前验收更新（2026-10-02）：用户已确认 B 三篇各十条抽样、F 三题十五候选/十三个完整 PDF 页的人工对照，记录在 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)。G 本轮 SQLite 14 项、索引 25 项、检索 20 项共 59 项重跑通过，新增人审继承 22 项通过；正式新进程九项验收通过，1188 条正文/向量/缓存方向一致，39 个输入/快照、SQLite 四表和 Qdrant 两个数据文件保持一致，本次零 API。D4 状态为 `completed_with_known_issues`，已完成并保留 ReAct 摘要漏召回；D5 尚待实现。以下 2026-10-01 执行段落保留当时状态，当前确认以本段与 G 汇总为准，不延伸确认 D3 恢复稿。见 [任务 G 与 D5 交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md) 与 [正式验收入口](/D:/course/paper-research-assistant/artifacts/d4/validation.md)。

执行更新：任务 B 已完成三篇，共 71 页、1179 个 segment → 1188 个 chunk。完整原文/哈希/来源/覆盖范围与快照检查通过；三篇重复运行均复用已有版本。分块器十二项边界检查已通过；[每篇十条抽样预览](/D:/course/paper-research-assistant/artifacts/d4/chunk_preview.md) 的人工状态仍 pending。任务 C 已完成 SQLite 的 3 篇、3 个版本、1188 个 chunk 保存和按 ID 回查，重复导入不增长，14 项存储边界检查及全部真实数据读回通过；说明见 [任务 C 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-C-storage-guide.md)。任务 D 已完成三篇 1188 个向量入库，全部 ready；模型为 qwen3.7-text-embedding、1024 维、cosine。含十条试运行共 120 次真实请求、84046 tokens，重复运行零请求；新进程完整核对及 25 项离线边界检查通过。后续 E/F 进度见下方更新；F 的 AI 对照已完成、人工确认 pending，G 汇总待做，整个 D4 仍进行中。见 [任务 D 逐步解释](/D:/course/paper-research-assistant/docs/v1/d4/d4-D-index-guide.md) 和 [正式索引验证](/D:/course/paper-research-assistant/artifacts/d4/index_validation.json)。

任务 E 执行更新（2026-10-01）：`search.py` 与 `search_evidence.py` 已接通一次问题向量、ready 门槛、完整论文/处理版本过滤、top-5 与 SQLite 原文回查。20 项离线边界检查通过；三篇各一题真实查询，共 3 次 API、103 tokens、LLM 0。RAG/Reflexion 的预期引文在 rank 1；ReAct 这题未召回标注的摘要第 1 页，真实保留问题。原文四表、向量文件和 39 个输入/快照未改。F 后续对照进度见下一段，D4 仍进行中。见 [任务 E 逐步说明](/D:/course/paper-research-assistant/docs/v1/d4/d4-E-retrieval-guide.md) 与 [真实查询记录](/D:/course/paper-research-assistant/artifacts/d4/retrieval_validation.json)。

任务 F 执行更新（2026-10-01）：已复用 E 三题的 15 条真实候选，完成文字/SQLite/哈希和 13 个完整原 PDF 页的 AI 对照。RAG ranks 1/2、Reflexion rank 1 是完整依据；ReAct ranks 1/5 含正确同事实却来自正文，其余三条是参考文献尾片段，正式 top-5 没有摘要依据。目标 p1_c6 完整保留，当前480条向量身份/来源/缓存方向核对通过；一次独立新问题请求测得摘要 rank 9，35 tokens，未改正式 top-k 或 E 历史。不能将新实验第9名冒充E旧请求排名。39个输入/快照、SQLite四表、Qdrant文件不变。AI复核完成，本次人工状态仍 pending，D4整体未完成；下一步G汇总。见 [任务 F 详细说明](/D:/course/paper-research-assistant/docs/v1/d4/d4-F-retrieval-review-guide.md) 与 [候选/PDF复核报告](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)。

| 论文 | 页数 | segment | chunk | 处理版本 |
|---|---:|---:|---:|---|
| RAG | 19 | 384 | 385 | `r_269ac0cb1263292d` |
| ReAct | 33 | 473 | 480 | `r_22af23d03fcb87a8` |
| Reflexion | 19 | 322 | 323 | `r_d7736b29a2d8b39e` |

沿用此前 7–8 小时的时间预算：明确任务 400 分钟，休息 30 分钟，阻塞缓冲 20 分钟，共 7 小时 30 分钟；第 8 小时用来补尚未通过的验收。估时按复用 D2/D3 代码、分阶段讲解与实现计算；逐行手敲并理解全部代码时，可能需要拆成两次完成。

## 1. 做完以后应该能看到什么

输入一个问题，并明确选择一篇或多篇论文及处理版本，程序返回最多五个候选证据片段。每条显示论文 ID、处理版本、chunk ID、PDF 文件页序、原文和相似度分数；退出程序再运行，数据仍然可查；同样的论文和配置重复导入，记录数量不增长。

流程是：

```text
过滤后的保留片段 → 带来源的 chunks → embedding → SQLite + Qdrant
问题 + 选定论文及版本 → 问题 embedding → 限定范围检索 → 原文、ID、页码
```

模型生成答案、逐条结论引用校验属于 D5；页面属于后续界面任务。D4 的交付是可持续使用的证据检索底座。

## 2. 当前可以复用的基础

- 三篇固定 PDF、71 页及其 SHA-256 已在 `eval/corpus.json` 中登记。
- `data/filtered/` 有 1179 个保留 segment：RAG 384、ReAct 473、Reflexion 322。segment 数不等于最终 chunk 数，切完后另行统计。
- 保留片段已有 `segment_id`、`paper_id`、`pdf_sha256`、`pdf_page`、`filter_revision`、`bbox`、原始块/行索引和 `text`。
- 分块入口复用 `paper_assistant.quality.iter_indexable_segments()`，从派生记录中的 `segments` 读取正文。
- 向量请求复用 `paper_assistant.embedding_client.embed_texts()` 与 `config.load_embedding_settings()`，不用再写一套 embedding 客户端。
- `schemas.EvidenceRef` 已规定引用位置的四个核心字段：`chunk_id`、`paper_id`、`parse_revision`、`pdf_page`。
- `eval/dev.jsonl` 是人工通过的十题开发集，可挑正常事实题做检索抽查。

D2 成功记录实际使用 `qwen3.7-text-embedding`、1024 维，与总计划最初写的默认 `text-embedding-v4` 不同。执行时先读取并确认当前非敏感配置；优先沿用已验证配置，把实际模型和维度写入索引记录。文档与问题使用相同 embedding 配置及当前兼容接口输入方式。更换模型、维度或输入预处理时新建索引配置，不能混用旧向量。

页预览 TXT、页汇总 `text`、恢复图文和公式稿不是这次的普通正文入口。恢复稿的人工状态继续保留，D4 不把它们的 AI 核对自动改为人工通过。

## 3. 七项任务与时间

| 任务 | 用时 | 做什么 | 完成时留下什么 |
|---|---:|---|---|
| A | 45 分钟 | 限时读 Ch8，固定字段、版本和目录约定 | 能解释 chunk、embedding、两种数据库和三个版本层次 |
| B | 70 分钟 | 实现保留片段内部切块、确定性 ID、输入快照 | 三篇版本化 chunk JSONL、配置清单与抽样预览 |
| C | 65 分钟 | 实现 SQLite 事实存储 | 能按 chunk ID 查正文；重复写入不增长；旧版本不覆盖 |
| D | 80 分钟 | 先少量验证，再完成 embedding 和 Qdrant 持久化 | 确定性 point ID、模型/维度记录、入库状态与统计 |
| E | 55 分钟 | 接通指定论文及版本的检索 CLI | 问题 → top-5 原文、ID、页码；范围过滤有效 |
| F | 45 分钟 | 三篇导入、正常事实题检索与 PDF 人工对照 | 当前导入报告、检索抽查报告，真实标出通过/问题 |
| G | 40 分钟 | 验证重复、重启、失败隔离；更新操作说明 | 边界验收记录与 D5 可复用的入口 |

休息穿插在 B、D、F 之后，各 10 分钟。卡住时优先使用 20 分钟缓冲；最后 30 分钟只补主链路，不增加功能。

## 4. 任务 A：先理解对象，再建库

课程只看第八章 8.3.1、8.3.2、8.3.4 中分块、向量化和检索部分，约 25 分钟；剩余时间画出字段关系。材料见[第八章](/D:/course/hello-agents-study/docs/chapter8/第八章%20记忆与检索.md)。

需要能用自己的话回答：

| 概念 | 在本项目里的含义 |
|---|---|
| segment | D3 已隔离坏行之后的一段连续保留文字，来源于一页中的一个文本块 |
| chunk | D4 准备存储与检索的一小段原文；较长 segment 会分成多个 chunk |
| embedding | 用同一个向量模型把文档和问题变成数字列表，使它们可以比较相似程度 |
| SQLite | 保存可回查的论文、版本、正文与导入状态，回答“这个 ID 对应什么原文” |
| Qdrant | 保存向量和筛选字段，回答“所选范围里哪些向量最接近问题” |
| top-k | 返回相似度排序前 k 个候选，排第一不等于其中一定有答案 |

三个版本层次分别记录：

1. **论文版本**：`arxiv_2005.11401v4` 中的 `v4`，由论文作者发布。
2. **处理版本**：`parse_revision`，由项目的 PDF、过滤输入、处理程序及分块配置决定。
3. **向量索引配置**：由 embedding 后端、模型、维度、输入方式及相似度类型决定。

换向量模型不必改写原 chunk；改变分块、过滤规则或输入则产生新处理版本。

## 5. 任务 B：可复现分块与处理版本

先处理 RAG 一篇，检查五至十个 chunk，再推广到三篇。顺序如下：

1. 加载论文清单与相应 filtered JSONL，核对论文 ID、PDF 哈希、完整页序和过滤版本。
2. 调用 `iter_indexable_segments()`，保持原页面和片段顺序。
3. **只在单个 segment 内切分**。不跨页、不跨 segment 拼接，也不恢复被排除的行。
4. 短 segment 原样保留。长 segment 按明确上限切分，优先在可用换行/词间边界停止，并保留少量重叠。
5. 记录 `segment_id`、`char_start`、`char_end`，满足 `chunk.text == segment.text[char_start:char_end]`；`char_end` 不包含在区间中。字符下标按 Python 字符串计数，不是 UTF-8 字节。
6. 原文不自动改写、合并断词或压平换行；后续如有预处理，单独记录规则与版本。
7. 保存输入快照、完整配置及其哈希，生成稳定处理版本和 chunk ID。

初版建议明确采用 `max_chars=1600`、`overlap_chars=200`，参数名和报告都写“字符”。当前仅九个 segment 超过 1600 字符，大多数片段较短；先保留这些边界建立基线，D5 再根据检索问题决定是否需要带来源的上下文扩展。总计划的约 300–400 token 是调优起点，这里不把 1600 字符冒充精确 token 数，也不声称每块都有目标长度。

`parse_revision` 使用规范 JSON 配置的 SHA-256 指纹，例如 `r_<指纹前16位>`；完整指纹仍保存在清单中，同短名而完整指纹不同必须拒绝混用。参与指纹的内容至少包括 PDF 哈希、原始解析文件哈希、filtered 文件哈希、质量规则哈希、解析器版本、过滤器/分块器版本及分块配置。不把时间戳和密钥放入身份计算。

chunk ID 示例约定：`{paper_id}_{parse_revision}_p{页序}_c{该页块序}`。示例中的页序从 1 开始、块序按稳定遍历顺序从 1 开始。文本哈希使用完整 SHA-256。

每块最少保存：

```text
chunk_id, paper_id, parse_revision, pdf_sha256, pdf_page,
segment_id, char_start, char_end, text, text_sha256,
filter_revision, source_block_index, source_line_indices, segment_bbox
```

`segment_bbox` 是父片段的区域，不能写成分块中某句话的精确坐标。记录继承的行索引也应明确指向父片段。

输出放 `data/chunks/<paper_id>/<parse_revision>/`，其中包括 `chunks.jsonl`、`version_manifest.json` 及原始/过滤页快照。相同配置重复运行复用并核对已有输出，不能静默覆盖不同内容。

## 6. 任务 C：SQLite 保存可回查事实

使用标准库 `sqlite3`，数据库放 `data/index/papers.sqlite3`。先做四张简单表：

| 表 | 内容与关键约束 |
|---|---|
| papers | 论文 ID、作者版本、来源与 PDF 哈希；论文 ID 唯一，来源冲突不能静默覆盖 |
| parse_versions | 论文 + 处理版本、完整处理指纹、快照位置、分块统计；二者组合唯一 |
| chunks | 不可变原文、页码、哈希与父片段信息；chunk ID 唯一，关联指定处理版本 |
| index_imports | 处理版本 + 索引配置的导入键、状态、完成数量、错误摘要；导入键唯一 |

每个连接启用外键。用参数化 SQL、明确事务和唯一约束；相同 ID 重写时核对内容一致并复用，不用覆盖语句修改旧证据。

验收：按 chunk ID 能读到原文和页码；同一批再写一次，数量相同；增加处理版本时旧版本仍可读。普通结构检查可以复用 `EvidenceRef`，真实存在及来源一致还需要存储层检查。

## 7. 任务 D：向量入库与导入状态

项目采用 `qdrant-client` 的本地持久化模式，指定 `path` 将数据保存在 `data/index/qdrant/`。本地模式由 Python 客户端运行，无需单独启动 Qdrant 服务，官方示例区分了内存和持久化两种方式。[Qdrant 客户端官方说明](https://github.com/qdrant/qdrant-client#local-mode)

执行时只新增必要依赖 `qdrant-client`，安装后记录实际版本到 `requirements.txt`，不为了 D4 更新已经跑通的全部依赖。SQLite 已随 Python 提供。

步骤：

1. 从当前配置得到模型与维度，建立索引配置指纹与独立 collection。
2. 先选择五至十条 chunk 做试运行；试运行用独立临时 collection，不能将仅十条的部分导入标为正式 ready。
3. 调用已有 embedding 客户端，验证向量数、顺序、维度及有限数值；复用已有验证逻辑。
4. 正式分批处理，每批初始取十条；核对当前模型/API 的批次及长度限制。百炼官方区分不同模型的限制，不能把一种模型的上限套在另一种上。[百炼向量化官方说明](https://help.aliyun.com/zh/model-studio/embedding)
5. collection 使用实际返回且核对通过的向量维度，距离类型固定为 cosine；不同模型配置不能写入同一个 collection。
6. Qdrant point ID 用固定命名空间下的 UUID5，根据索引配置 ID 与 chunk ID 生成；可读 chunk ID 放 payload，不直接当任意字符串 point ID。
7. payload 至少保存 chunk ID、论文、处理版本、PDF 页码、文本哈希和索引配置 ID；正文以 SQLite 快照为事实来源。
8. 成功批次记录已完成的 point ID，重试复用同一个导入键和 UUID；已完成的向量可复用，避免重复付费生成。
9. SQLite 和 Qdrant 对该版本的记录及哈希核对完成后，才把正式导入标成 ready。

状态流程为 `pending → ready`；失败记 `failed` 和安全错误摘要，重试可回到同一导入键的 pending。SQLite 与 Qdrant 不共享一笔事务，不能因为前者提交了就宣布整个导入成功。

失败时保留可解释状态，不发布半份索引。查询前从 SQLite 得到明确 ready 的论文/版本组合，再到对应 collection 检索。Qdrant 中已经有部分点也不能绕过状态检查。

由一个进程持有本地客户端，使用完关闭；CLI 与未来 Streamlit 不同时打开同一持久化目录。记录请求次数、实际返回 token 用量和耗时；不从字符数伪造每块的精确 token 用量。输入太长或 API 错误要明确失败，不静默截断。

## 8. 任务 E/F：接通检索并核对命中

实现 `search_evidence(query, selected_versions, top_k=5)`。`selected_versions` 使用明确的 `(paper_id, parse_revision)` 配对；不能分别筛选两组列表，导致不同论文/版本被交叉误选。

步骤：

1. 检查查询非空、论文存在、所选处理版本在当前索引配置下 ready。
2. 问题只向量化一次，使用与库中正文相同的模型、维度及输入预处理。
3. Qdrant 用筛选条件限定允许的论文/版本组合，再按相似度返回 top-5 候选；采用当前客户端的 `query_points()` 接口。[官方过滤说明](https://qdrant.tech/documentation/search/filtering/)
4. 依据命中 chunk ID 回 SQLite 读取正文，并复核论文、版本、页码和文本哈希。
5. 输出原文、位置、分数和真实候选数量；把“没有命中”与“查询服务/存储失败”分开。

正常事实题从正式开发集选，每篇至少选一道；十题全部可以做检索观察，但不把这一步写成问答模型准确率。打开对应 PDF 页，检查命中是否包含期望依据，记录实际名次及不足。

检查过滤范围时，明确只选择 RAG，结果就只能来自 RAG 的选定处理版本。需要模型生成答案才能判断的拒答题留到 D5；相似度最高不证明文献有答案。

## 9. 任务 G：完成 D4 的判定

- [x] 三篇都生成有稳定身份、来源和哈希的 chunks。
- [x] chunk 没有跨页/跨 segment，来源区间可以还原精确文本。
- [x] 三篇正式处理版本的 SQLite chunks 与 Qdrant 点数/ID/哈希对应，导入状态 ready。
- [x] 相同论文、处理配置和索引配置再导入，正文/向量数量都不增长；已有 ready 导入不再次请求文档 embedding。
- [x] 关闭整个进程，再以新进程打开能查询，证明使用了持久化存储（D 离线读回、E 三题真实新进程查询）。
- [x] 按所选论文和处理版本筛选有效；旧 chunk 可以直接按 ID 回查（真实单篇范围、离线完整配对交叉反例通过）。
- [x] 可控失败时状态 failed，ready 列表不包含部分版本；重试使用相同键和确定性 ID（D 临时库故障验证；E 已接入门槛，非法/未完成版本零付费请求）。
- [x] 每篇至少一道正常事实题有实际检索结果和 PDF 对照记录；F 已完成三题十五候选/十三个完整 PDF 页的 AI 对照，用户于 2026-10-02 明确确认；ReAct 漏摘要记录与诊断仍保留。
- [x] 当前报告、配置、版本与命令放在约定目录；G 九项正式验收通过，操作说明和 `EvidenceSearcher` / 按 ID 回查接口已整理供 D5 复用。

不要求一天内优化所有短片段、恢复所有表格或实现完整问答。任何必须项未通过，进度记为 D4 进行中；第 8 小时优先补这些边界，不能仅完成一篇就标记三篇交付已完成。

## 10. 后续新增文件及目录约定

任务 B/C/D/E 的分块、快照、存储、缓存、向量索引、问题检索及以下入口均已实现，三篇正式数据与当前报告已生成。每篇分块预览、运行记录和验证记录分别放在 `artifacts/d4/chunk_previews/`、`chunk_reports/`、`chunk_validations/`；根层同名报告是总入口。B 抽样与 F 对照已由用户于 2026-10-02 确认，G 正式验收通过，D4 完成并保留已知问题：

```text
paper_assistant/
  chunking.py           分块、来源区间、稳定版本与 ID
  storage.py            SQLite 表、不可变证据与导入状态
  retrieval.py          Qdrant 持久化、版本筛选、完整性核对
  indexing.py           索引配置、原子向量缓存、导入状态协调
  search.py             问题向量、ready门槛、候选原文回查
scripts/
  build_index.py        构建/复用索引，可先 dry-run 只读核对
  search_evidence.py    指定论文及版本的问题检索 CLI
  check_index.py        必要边界检查
  check_retrieval.py    检索范围、来源、故障与持久化边界
  validate_index.py     正式磁盘索引离线读回核对
  validate_d4.py        G 正式数据、人工范围与既有验收离线汇总
data/
  chunks/<paper_id>/<parse_revision>/
  index/papers.sqlite3
  index/qdrant/
  index/embeddings/     成功响应缓存，继续使用
  index/profiles/       模型/维度/输入方式配置清单
  index/current_profile.json
artifacts/d4/
  chunk_preview.md      三篇抽样预览目录；单篇样本在 chunk_previews/
  import_report.json    当前导入状态和实际配置
  index_validation.json 正式索引离线核对
  retrieval_result.json/.md 最近一次查询候选
  retrieval_validation.json 三题真实范围/来源与召回观察
  retrieval_review.md/.json 当前检索/PDF对照与人工状态
  retrieval_evidence/   13张完整原页及渲染来源清单
  retrieval_diagnostics/ ReAct独立新实验完整排名
  human_review.json     用户明确确认的 B/F 范围与来源绑定
  validation.json/.md  G 正式整体验收
archive/run_logs/d4/    历史试运行日志
```

初版继续沿用已有 `config.py`、`schemas.py`、`quality.py`、`embedding_client.py`，需要字段时在原模块扩展。数据目录保留所有版本用于回查；当前报告目录只展示本次结论，历史试验和旧候选进统一归档。

任务 B 已可执行：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2005.11401v4
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2210.03629v3
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2303.11366v4
# 只核对和展示统计，不生成文件
.\.venv\Scripts\python.exe -X utf8 -m scripts.chunk_paper --paper-id arxiv_2005.11401v4 --dry-run
```

任务 C 已可执行：`python -X utf8 -m scripts.store_chunks` 保存三篇当前版本，`python -X utf8 -m scripts.query_chunk --chunk-id <真实ID>` 回查原文。任务 D 已可执行：`python -X utf8 -m scripts.build_index --dry-run` 只读预检，省略 dry-run 正式构建/复用；构建结束后 `python -X utf8 -m scripts.validate_index` 在新进程离线核对。任务 E 已可执行：`python -X utf8 -m scripts.search_evidence --list-ready` 离线列范围，`--paper-id ... --parse-revision ... --query ...` 实际查询；多篇用重复的 `--version PAPER REV`。完整 PowerShell 命令与解释见任务 D/E 说明。

B 抽样与 F 的真实候选/PDF 对照已由用户于 2026-10-02 明确确认；G 正式新进程九项验收通过，D4 完成并保留已知问题。G 命令为 `python -X utf8 -m scripts.validate_d4`，不读取 `.env`、不请求模型，完整 PowerShell 命令与调用接口见 [交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)。D5 尚待将检索结果提供给模型生成带引用的回答，并校验引用是否来自本轮实际提供的证据集合；ReAct 摘要限定漏召回及候选上下文边界继续作为已知问题带入。
