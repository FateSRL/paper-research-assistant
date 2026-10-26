# D4 任务 D：向量入库的步骤、作用与命令

本文解释本项目已经实现的任务 D 代码。正式运行结果看 [当前导入报告](/D:/course/paper-research-assistant/artifacts/d4/import_report.json)，最终完整性核对看 [索引验证报告](/D:/course/paper-research-assistant/artifacts/d4/index_validation.json)。请求次数、实际 token 用量及是否全部 ready，以报告为准。

任务 D 的输入是任务 C 已保存的三篇原文，共 1188 个 chunk：RAG 385 个、ReAct 480 个、Reflexion 323 个。任务 D 把这些原文转换成可比较的向量，并保存到本地 Qdrant。后续 E 已实现“输入问题，找出相关原文”，见 [任务 E 说明](/D:/course/paper-research-assistant/docs/v1/d4/d4-E-retrieval-guide.md)。

当前进度更新（2026-10-02）：用户已确认 B 三十条抽样与 F 三题十五候选/十三个完整 PDF 页的对照，G 正式新进程九项验收通过，D4 完成并保留已知召回问题，D5 尚待实现。当前人工确认见 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)，整体报告见 [validation.md](/D:/course/paper-research-assistant/artifacts/d4/validation.md)，后续调用入口见 [D5 交接指南](/D:/course/paper-research-assistant/docs/v1/d4/d4-G-completion-guide.md)。

## 1. 先理解这一步为什么需要

任务 C 的 SQLite 已能解决“知道 chunk ID，取回这一段原文”。但用户一般只会输入问题，例如“RAG 的两种生成方式有什么区别”，不会知道相关 chunk 的 ID。

直接按关键词查找有时会漏掉同义表达。embedding 模型把一段文字变成一组数字；意思较接近的文字，模型通常会给出方向较接近的数字组。向量数据库保存这些数字，后续可以按相似度找候选段落。

当前实际配置是 `qwen3.7-text-embedding`，维度是 `1024`。也就是说，每个 chunk 得到 1024 个数，这 1024 个数共同构成一个向量。不能把某个数简单理解为“第几个单词”或一个人工指定的语义标签。

项目使用 cosine 距离比较向量方向。相似度用于挑选候选证据；较高的分数本身不能证明论文包含问题的答案，也不能证明候选段落的结论正确。任务 D 只完成建库，尚未生成问答答案。

## 2. SQLite、缓存和 Qdrant 各保存什么

| 位置 | 保存内容 | 在流程中的作用 |
|---|---|---|
| SQLite 的 `chunks` 表 | 原文、chunk ID、论文、处理版本、PDF 页码、文本哈希、来源范围 | 原文与引用的事实来源 |
| 本地 embedding 缓存 | 模型返回的原始向量、对应 chunk 身份和哈希、批次实际 usage | 保存成功的模型响应，重跑时复用 |
| Qdrant collection | 向量、确定性 point ID、回查身份与哈希 | 后续执行向量相似度检索 |
| SQLite 的 `index_imports` 表 | 某论文/处理版本/索引配置的状态与完成数量 | 决定该版本是否已经完整，可以被检索 |

Qdrant 中的 collection 可以理解为一组遵守相同向量配置的数据。一个 point 是其中一条记录，包含向量和附带信息 payload。payload 保存 `chunk_id`，后续通过这个 ID 回 SQLite 取原文。

项目不在 Qdrant payload 中复制正文。这样原文只有明确的事实来源，也能在取回正文时重新核对来源哈希。

## 3. 第一步：核对输入的论文与处理版本

入口先调用 [selected_versions()](/D:/course/paper-research-assistant/scripts/build_index.py)。省略论文参数时，从 `eval/corpus.json` 选三篇，再从每篇当前分块报告定位 `parse_revision`。指定处理版本时，必须同时指定论文。

当前输入配对为：

| 论文 | paper_id | parse_revision | chunk 数量 |
|---|---|---|---:|
| RAG | `arxiv_2005.11401v4` | `r_269ac0cb1263292d` | 385 |
| ReAct | `arxiv_2210.03629v3` | `r_22af23d03fcb87a8` | 480 |
| Reflexion | `arxiv_2303.11366v4` | `r_d7736b29a2d8b39e` | 323 |

`paper_id` 中的 `v4`、`v3` 表示 arXiv 作者发布的论文版本；`parse_revision` 表示本项目解析、过滤、分块配置对应的处理版本。两者描述不同事情。例如，作者没有更新 PDF，本项目改变分块参数，仍然需要一个新的处理版本。

程序通过 `load_chunk_version()` 检查不可变快照，并把快照中的完整 chunk 集合与 SQLite 逐字段比较。原文、来源、数量或身份不一致，就停止构建。

**为什么：**向量必须准确对应当时保存的原文。不能只见到文件名相同就认为内容相同，也不能向量来自新文字、引用却回查旧文字。

这一步不会重新解析 PDF 或重写 chunk。已排除的乱码、待人工确认的图中文字和公式恢复材料，不会因为向量建库而自动混进正式正文。

## 4. 第二步：建立索引配置的稳定身份

[make_index_profile()](/D:/course/paper-research-assistant/paper_assistant/indexing.py) 从当前 embedding 配置建立索引配置清单，清单包含：

- backend、实际模型名与维度。
- API 基地址和请求形式。
- 默认输入方式 `openai-compatible-default`。
- 预处理 `identity-text-v1`，即使用保存的原文，不静默改写或截断。
- float 向量编码与 cosine 距离。

程序把配置按固定 JSON 格式计算 SHA-256，由完整哈希生成 `ep_...` 索引配置 ID，并使用独立 collection 名称。API 密钥不进入配置指纹、缓存或报告。

**为什么：**模型和输入方式共同决定向量含义。两个模型即使都返回 1024 个数，也不代表它们的数字可以放在一起比较。以后改模型、维度或预处理方式，需要新配置身份和新 collection，不能覆盖旧库。

当前客户端沿用 D2 已跑通的 OpenAI 兼容接口；正文和后续问题使用同一默认输入方式。代码没有擅自切换到另一种接口，也没有追加新的 `query`、`document` 指令。

配置写入 `data/index/profiles/<index_profile_id>.json`。已有相同 ID 的文件必须内容一致，否则拒绝覆盖。正式导入成功后，`data/index/current_profile.json` 保存本次配置的入口信息。

## 5. 第三步：打开持久化 Qdrant 并核对 collection

实现是 [QdrantStore](/D:/course/paper-research-assistant/paper_assistant/retrieval.py)。客户端指定 `path`，把向量保存在 `data/index/qdrant/`。项目安装 `qdrant-client`，本地模式不需要单独启动 Qdrant 服务。[Qdrant 官方客户端说明](https://github.com/qdrant/qdrant-client#local-mode)

第一次运行创建指定维度、cosine 距离的 collection。以后打开同名 collection，会先检查它的向量配置。如果既有维度或距离与当前配置不一致，程序拒绝继续。

**为什么：**程序能打开一个目录，只能证明目录存在；不能证明里面的数据适合当前模型。这个检查防止向量被写入错误的库。

本地 Qdrant 目录有占用锁，一个目录由一个客户端持有。试运行 collection 借用正式构建器的同一个客户端，避免自己与自己争锁。退出 `with` 后关闭客户端，释放锁，另一个进程才能重新打开该目录。

构建命令运行时，不要同时再启动使用同一 Qdrant 目录的命令或应用。等上一条命令结束后再运行下一条即可。

## 6. 第四步：先对十条原文做小规模验证

[IndexBuilder.smoke()](/D:/course/paper-research-assistant/paper_assistant/indexing.py) 选第一篇待完成版本的前十条 chunk，先检查缓存；缺少缓存的条目才请求模型。

收到响应后检查：

1. 输入多少条，就必须返回多少条。
2. 响应中的 index 必须唯一、合法，并按输入顺序还原。
3. 每条向量必须是 1024 维，数值有限，且不是全零向量。
4. 模型响应成功保存到缓存后，写入独立临时 collection。
5. 读回 point，核对 ID、来源、文本哈希和向量方向。

检查结束删除临时 collection。成功生成的十条向量缓存保留，正式导入能够复用。

**为什么：**先用少量输入验证模型、响应和本地存储组合，可以尽早发现配置问题。只有十条试验成功不能说明一篇或三篇已全部入库，所以这一步不设置正式 `ready`。

正常默认命令会自动执行这一环节；所选版本已经全部 ready 时跳过试验，并直接完整复核已有库。`--smoke-only` 则只做十条试验和缓存，不进行整篇正式导入。

## 7. 第五步：按批次生成并先保存缓存

正式导入由 [IndexBuilder.import_version()](/D:/course/paper-research-assistant/paper_assistant/indexing.py) 协调。默认每批十条，最后一批可以少于十条。当前 CLI 允许批次大小为 1 至 10。

每批按如下顺序处理：

```text
确定本批尚未完成的 chunks
        ↓
读取已有缓存，只有缺少的条目才请求 embedding
        ↓
校验响应数量、顺序、维度和有限数值
        ↓
先原子保存这批模型响应
        ↓
把对应向量写入 Qdrant
        ↓
更新 SQLite 中该版本的完成进度
```

“原子保存”由 [atomic_json()](/D:/course/paper-research-assistant/paper_assistant/indexing.py) 完成：先写同目录临时文件、刷新文件，再替换成正式缓存文件。读取时又验证整个批次的 SHA-256、索引配置、chunk 身份和来源。

缓存一批一个 JSON 文件，路径是 `data/index/embeddings/<index_profile_id>/batches/b_<批次哈希>.json`。文件中保存原始模型向量；Qdrant 为 cosine 比较保存归一化方向，两者读回时按方向核对。

**为什么先缓存：**如果模型已经成功返回、缓存已经落盘，但向量库写入失败，下一次重跑可以直接用这批缓存继续，不需要重新请求同一批模型。

缓存是之后会用到的正式数据，不是过期报告，不应移入 `archive/`。缓存损坏会明确失败，代码不会把坏缓存当成“没有缓存”并悄悄重新请求服务。

实际 token 用量来自供应商响应的 `usage.total_tokens`。日志记录真实请求数、成功/失败、耗时和 usage 缺失情况，不用字符数假装计算出精确 token 数。当前程序不会对错误请求无限自动重试。

## 8. 第六步：给每个 point 一个可重复计算的 ID

[point_id()](/D:/course/paper-research-assistant/paper_assistant/retrieval.py) 使用固定命名空间下的 UUID5，根据 `index_profile_id` 和 `chunk_id` 生成 point ID。

UUID 可以理解为一种标准格式的唯一标识。这里的 UUID5 是由输入确定的：相同索引配置、相同 chunk，反复计算得到同一个 point ID；改变配置或 chunk 身份，得到另一个 ID。

**为什么：**如果每次随机生成新 ID，同一条原文重跑就会变成新 point，数量不断增长。确定性 ID 配合 upsert，使重试能够写回同一个位置。

Qdrant point 的 payload 保存：

| 字段 | 作用 |
|---|---|
| `chunk_id` | 回 SQLite 找原文 |
| `paper_id` | 确定是哪篇论文 |
| `parse_revision` | 确定是哪一个处理版本 |
| `pdf_page` | 返回 PDF 文件页码 |
| `text_sha256` | 核对向量所对应的原文 |
| `pdf_sha256` | 核对原始 PDF 来源 |
| `index_profile_id` | 核对模型与输入配置 |

模型的向量列表按输入顺序与这些 chunk 配对。任何数量、来源或哈希不一致都不能靠补零、截断或随便更换 ID 来继续。

## 9. 第七步：协调两份存储的状态

SQLite 与 Qdrant 是两份独立存储，它们没有共同的一笔事务。SQLite 成功提交，不代表 Qdrant 已经成功写完；Qdrant 里有部分 point，也不代表完整版本能发布。

因此 `index_imports` 按明确的三项身份登记一条记录：

```text
(paper_id, parse_revision, index_profile_id)
```

导入键由这三项身份稳定计算。重试复用同一条记录，不靠新建另一个导入键掩盖失败。

| 状态 | 意义 | 后续是否允许按这个版本检索 |
|---|---|---|
| `pending` | 开始或继续构建，可能已完成若干批次 | 否 |
| `failed` | 出现明确异常，错误摘要保留 | 否 |
| `ready` | 完整版本全部点已核对成功 | 是，检索入口仍需检查所选配置与版本 |

普通错误会把当前导入记为 failed。用户中断命令时，未完成版本可能保留 pending；报告记录 interrupted。两种情况都不会把半份数据标为 ready，重跑同一命令可以继续检查已有点与缓存。

一篇完成后才对这一篇设置 ready。三篇的完成状态分别登记，因此不能因 RAG 完成就宣称 ReAct 和 Reflexion 也已完成。

## 10. 第八步：完整核对之后才写 ready

[QdrantStore.validate()](/D:/course/paper-research-assistant/paper_assistant/retrieval.py) 与构建器的 `_verify_complete()` 负责核对完整版本：

1. collection 的维度和 cosine 配置正确。
2. 对指定论文与处理版本范围，Qdrant 点数等于 SQLite chunk 数。
3. 保存的 point ID 集合与期望 UUID 集合完全相同，没有额外点或缺失点。
4. 每个 point 的论文、版本、页码、文本哈希、PDF 哈希和索引配置与 SQLite 一致。
5. 每个向量维度正确，数值有限，且非零。
6. 每个读回向量的单位方向与它对应的原始缓存向量一致，允许 float32 保存产生的小幅舍入误差。

通过后才调用 `finish_index_import()`，写入完整数量和 ready 状态。

**为什么还比较缓存向量：**只有 payload 正确仍不足以排除“向量列表串位”。同一条原文的来源和缓存方向一起核对，才能发现向量被错误配给另一条原文。

按版本筛选使用完整 `(paper_id, parse_revision)` 配对。允许 `(RAG, r1)` 和 `(ReAct, r2)` 时，不能因为分别筛选两组列表而误放行 `(RAG, r2)`。

重复运行已 ready 的版本时，程序重新验证真正的磁盘数据与缓存，不重新请求文档 embedding，也不增加 point 数。假如缓存缺失或库已损坏，验证会失败，不会在 ready 复用阶段自动发起收费修补。

## 11. 实际 PowerShell 命令

无需重新激活虚拟环境，直接使用项目内 Python 的路径即可。下面每条命令都应等上一条结束后再运行。

### 11.1 只查看配置和待处理版本，不调用模型

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index --dry-run
$LASTEXITCODE
```

`--dry-run` 只读检查输入和配置，打印将要使用的论文、版本和模型信息，不写正式索引、缓存或本次报告。成功退出码是 `0`。这个命令并不表示向量已经生成。

### 11.2 只做十条小规模验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index --smoke-only
$LASTEXITCODE
```

这个命令可以调用 embedding 服务并保存成功缓存，结束后删除临时 collection。它不将一篇或三篇标为正式 ready。

### 11.3 默认构建三篇，或者复核并复用已完成索引

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index
$LASTEXITCODE
```

默认执行三篇当前分块版本，批次大小为十条。第一次会生成缺少的文档向量；已经 ready 且完整核对通过时复用已有数据，本次文档 embedding 请求数应为 `0`。

### 11.4 只构建一篇，明确指定处理版本

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d
$LASTEXITCODE
```

省略 `--parse-revision` 时，使用这篇当前分块报告指向的版本。指定它时必须同时提供 `--paper-id`，避免不知道版本属于哪篇论文。

### 11.5 调整为较小批次

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_index --paper-id arxiv_2210.03629v3 --batch-size 5
```

批次变小只改变一次请求处理多少条，不改变 chunk 原文和索引配置。代码按每条 chunk 检查已有缓存，因此改变批次大小仍能复用此前成功生成的向量。

不需要为了重跑先删库、删状态或删缓存；直接运行同一命令即可。失败时先看本次报告中的安全错误摘要和完成数量，再确认配置或文件问题。

### 11.6 在新进程离线核对正式索引

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_index
$LASTEXITCODE
```

构建命令结束后再执行。此命令不读取密钥、不请求模型，重新打开磁盘数据库，逐条核对三篇的 ID、来源哈希和缓存向量方向，再检查原输入/快照与 SQLite 原文事实是否保持一致。它把结论写入 `artifacts/d4/index_validation.json`。内部使用一条缓存文档向量做读回探针，不代表已完成真实问题检索的任务 E/F。

本项目每批十条；当前模型官方说明允许列表最多二十条，每条最长 128,000 tokens。这里的 chunk 上限是 1600 个字符，字符数和实际 token 数分别记录。[百炼同步接口说明](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)

## 12. main 函数是不是只做检查

[scripts/build_index.py 的 main()](/D:/course/paper-research-assistant/scripts/build_index.py) 是正式命令入口。它负责解析参数、读配置、选择版本、打开两份存储、协调小规模试验与正式构建、更新报告并返回退出码。

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

执行 `python -m scripts.build_index` 时，这段代码调用 `main()`。`main()` 返回 `0` 表示本次所选模式成功，返回 `1` 表示未完成；PowerShell 的 `$LASTEXITCODE` 就能读取这个结果。

`main()` 本身不包含全部算法。具体工作分别交给 `selected_versions()`、`make_index_profile()`、`EmbeddingCache`、`IndexBuilder`、`QdrantStore` 和 `PaperStore`。这样以后其他入口可以复用模块，而不必复制整段 CLI 程序。

可以把入口理解为“组织执行的负责人”，把模块中的函数理解为“负责一种明确工作的步骤”。`main()` 需要写；这里只是我们已经替项目实现了它，不需要你另手写一份才能运行。

## 13. 哪些目录以后继续使用

```text
paper_assistant/indexing.py         配置身份、向量缓存、状态协调
paper_assistant/retrieval.py        Qdrant 持久化、完整性核对、版本过滤
paper_assistant/storage.py          SQLite 事实与向量导入状态
scripts/build_index.py             正式建库命令入口
scripts/check_index.py             临时数据上的离线边界检查
scripts/validate_index.py          正式磁盘索引的离线核对入口
data/chunks/<论文>/<处理版本>/       不可变分块与来源快照
data/index/papers.sqlite3           原文与导入状态
data/index/profiles/                各索引配置清单
data/index/current_profile.json     正式导入成功后的当前配置入口
data/index/embeddings/              可复用的原始模型向量缓存
data/index/qdrant/                  磁盘向量数据库
artifacts/d4/import_report.json     最近一次构建的结果、请求与实际用量
artifacts/d4/index_validation.json  完整性、持久化、重复运行等验证结果
archive/run_logs/d4/                每次运行的历史记录
```

`artifacts/d4/import_report.json` 会被下一次非 dry-run 运行更新，所以第一次生成向量的请求和用量需要结合历史运行记录查看。重复验证报告显示本次零请求，与历史生成记录存在请求并不矛盾。

`data/index/embeddings/`、`profiles/`、`qdrant/` 和 SQLite 都是当前功能使用的数据；只有历史运行日志放到 `archive/run_logs/d4/`。此前任务 C 报告中的 `index_imports=0` 描述的是任务 C 结束时的状态，任务 D 当前状态看新的导入与验证报告。

## 14. 后续任务 E 如何使用索引

任务 E 已实现问题检索入口：检查所选明确论文/版本在当前配置下 ready，给问题生成一次向量，按完整论文/版本配对筛选，调用 Qdrant 的 `query_points()` 找候选，再按 chunk ID 回 SQLite 取得并复核原文、页码与来源。

任务 E 已完成 `scripts/search_evidence.py` 查询 CLI 和 `paper_assistant/search.py` 核心：ready 检查、一次问题向量、完整版本过滤和 SQLite 候选原文核对。F 完成三题十五候选/十三个完整 PDF 页的 AI 对照及 ReAct 独立排名诊断，用户于 2026-10-02 明确确认；见 [任务 F 报告](/D:/course/paper-research-assistant/artifacts/d4/retrieval_review.md)。实际查询命令见任务 E 说明，G 正式验收已通过，D4 完成并保留已知问题；D5 尚待接入答案生成与引用校验。

三篇各一道正常事实题已有真实命中与 PDF 对照，并已获用户确认；ReAct 正式 top-5 未满足摘要来源限定，问题保留，独立新实验摘要 rank 9。图中文字与公式的专门恢复材料继续遵守原来的质量过滤规则，其 D3 人工状态不因本次 B/F 确认而改变。
