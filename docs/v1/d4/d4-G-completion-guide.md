# D4 任务 G：最终验收与 D5 交接说明

记录日期：2026-10-02（Asia/Shanghai）。用户已在本次对话明确确认“F 已核对”“B 抽样已核对”。这份说明把现有实现、真实检查记录和人工确认整理到同一条操作路径，便于继续 D5。

正式验收入口是 [validation.json](/D:/course/paper-research-assistant/artifacts/d4/validation.json) 和 [可读验收报告](/D:/course/paper-research-assistant/artifacts/d4/validation.md)。人工确认记录见 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json)。最终是否通过以本次离线验收报告为准。

## 1. G 做什么，完成后可以用什么

G 汇总 B 到 F 的证据，并在新的 Python 进程中离线检查现有正式数据。它的作用是确认：后续问答代码可以复用已经完成的分块、事实库、向量库和检索入口。

当前链路是：

```text
D3 保留 segment
        ↓ B：片段内部切分，记录来源与处理版本
1188 个 chunk
        ↓ C：保存原文、来源和版本
SQLite
        ↓ D：文档 embedding，保存向量和 ready 状态
Qdrant
        ↓ E：用户问题 embedding，限定范围找候选，回查原文
最多 5 条候选证据
        ↓ F：程序核对来源，AI 与用户对照 PDF
已记录支持度和检索不足
        ↓ G：离线核对、汇总确认、整理可复用入口
D5 可以在这条证据链之上接入答案生成与引用检查
```

已有入口返回候选原文，还没有调用聊天模型生成最终答案。完成 D4 表示检索底座具备继续开发的条件；已发现的召回问题继续留在报告中。

## 2. 当前固定数据与三个版本层次

| 论文 | paper_id | PDF 页数 | chunk 数 | parse_revision |
|---|---|---:|---:|---|
| RAG | `arxiv_2005.11401v4` | 19 | 385 | `r_269ac0cb1263292d` |
| ReAct | `arxiv_2210.03629v3` | 33 | 480 | `r_22af23d03fcb87a8` |
| Reflexion | `arxiv_2303.11366v4` | 19 | 323 | `r_d7736b29a2d8b39e` |
| 合计 | 3 篇 | 71 | 1188 | 3 个正式处理版本 |

原始保留 segment 共 1179 个。大多数片段直接成为一个 chunk，9 个长片段切成多个，因此 chunk 数比 segment 数多 9。一个 chunk 只属于一个父 segment，保留原文与精确字符区间。

| 层次 | 当前例子 | 用来区分什么 |
|---|---|---|
| 论文版本 | `arxiv_2210.03629v3` 中的 `v3` | 作者发布的 PDF 版本 |
| 处理版本 | `r_22af23d03fcb87a8` | 本项目的 PDF、解析、过滤、分块配置和处理程序 |
| 向量索引配置 | `ep_cbf0f6caa97b962a` | 向量模型、维度、接口输入方式、预处理与距离类型 |

当前完整索引配置保存在 [current_profile.json](/D:/course/paper-research-assistant/data/index/current_profile.json)，固定清单保存在 [profiles/ep_cbf0f6caa97b962a.json](/D:/course/paper-research-assistant/data/index/profiles/ep_cbf0f6caa97b962a.json)：

```text
index_profile_id: ep_cbf0f6caa97b962a
collection_name:  paper_chunks_ep_cbf0f6caa97b962a
backend:          dashscope
model:            qwen3.7-text-embedding
dimension:        1024
input_mode:       openai-compatible-default
preprocessing:    identity-text-v1
distance:         cosine
```

问题与正文都使用同一套配置。更换模型或输入方式时，必须生成新的索引配置并准备对应文档向量。维度都是 1024 也不能证明两个模型的向量可以混用。

## 3. 程序验收已经检查了什么

本轮 G 收尾先实际执行当前源码的 SQLite 14 项、向量索引 25 项和检索 20 项检查，共 59 项通过；另新增并执行人审继承检查 22 项，确认用户复核不能被转移到已经变化的样本或来源。分块器 B 的 12 项采用此前通过记录。

`scripts.validate_d4` 的职责是读取检查记录、核对记录绑定的源码 SHA，并在新的 Python 进程中读回正式数据；它不会再次执行这些 81 项测试。实际运行测试与读取已产生的测试记录，分别记录。

| 阶段 | 检查项数与记录 | 检查目的 |
|---|---:|---|
| B 分块 | 此前 12 项通过 | 区间合法、原文精确保留、重叠与覆盖、稳定 ID、输入快照及重复复用 |
| C SQLite | 本轮重跑 14 项通过 | 重复导入不增长、旧版本不覆盖、事务回滚、外键、只读回查与来源冲突 |
| D 向量入库 | 本轮重跑 25 项通过 | 向量维度和数值、确定性 point ID、缓存复用、完整 ready、失败记录、重试和持久化 |
| E 问题检索 | 本轮重跑 20 项通过 | 参数、配置、完整版本配对、ready 门槛、候选来源、故障与无命中区分 |
| B/F 人审继承 | 本轮新增 22 项通过 | 仅在实际版本、样本/候选原文、来源和复核材料均一致时继承确认；变化后拒绝自动沿用 |

本轮人审继承检查记录见 [g_human_review_checks.json](/D:/course/paper-research-assistant/archive/run_logs/d4/g_human_review_checks.json)。当前三组业务边界检查记录与正式数据核对结论统一在 G 的 `validation.json/.md` 中列出。

实际正式数据检查包括：三篇 chunk、SQLite 中三篇/三个处理版本/1188 条正文、三个 ready 导入，以及相应 Qdrant 点的 ID、来源哈希和向量方向。

已有重复运行记录证明相同输入没有让记录增长；ready 文档索引复用时不重新请求文档 embedding。D 的新进程离线读回和 E 的三题真实新进程查询，已留下持久化使用记录。G 继续使用已保存向量检查正式库，不重新生成 1188 个向量。

## 4. 这次人工确认记录的范围

用户在 2026-10-02 明确确认以下两项：

- **B 分块抽样**：三篇各十条抽样预览，检查文字、页码、切分和上下文。
- **F 候选/PDF 对照**：三题的 15 个实际候选、13 个不同完整 PDF 页面，以及报告中的完整依据、部分相关和来源不符合等判断。

人工确认由 [human_review.json](/D:/course/paper-research-assistant/artifacts/d4/human_review.json) 记录，与各阶段程序检查、AI 判断分别保留。确认依据是用户本次明确反馈，不会新增用户没有报告的逐条意见、复核耗时或缺陷修复结论。

这一确认只覆盖 B 和 F。D3 的图中文字恢复、公式恢复和其他独立人工检查继续采用它们各自的记录；它们不会因为本次确认自动变成人工通过，也不会自动混入 D4 正式正文索引。

2026-10-01 生成的历史报告中，`pending` 表示当时尚未获得本次用户确认。判断当前状态时查看本次确认记录和 G 汇总；历史问题、排名和用量仍以原始运行记录为准。

## 5. F 的发现如何带入 D5

| 正式事实题 | F 结论 | 后续处理时应注意什么 |
|---|---|---|
| RAG D2-001 | rank 1、2 包含完整两类记忆依据 | 根据实际原文生成结论，引用对应 chunk |
| ReAct D2-003 | 正式 top-5 没有题目要求的摘要依据；正文候选包含同事实 | 回答必须尊重“摘要中”的来源限定，不能用正文位置冒充摘要证据 |
| Reflexion D2-005 | rank 1 包含不更新权重、语言反馈反思和 episodic memory 等完整依据 | 其他候选只支持部分机制，不能用较高分数补出未明确写出的事实 |

ReAct 的目标摘要 chunk 是 `arxiv_2210.03629v3_r_22af23d03fcb87a8_p1_c6`。F 已核对它完整保存在分块、SQLite、缓存与向量库中，所以这次问题不是摘要文字丢失。

F 另发起一次独立问题向量请求，在同一正式范围内查看完整排序，得到摘要 **rank 9**。这是后来新实验的排名，不能写成 E 原请求已经测得第 9 名。原正式 top-k 仍为 5，E 的三次查询记录保持原样；这里没有通过改变题目、标注或检索上限来消除旧失败。

三道题中，完整符合题目事实与来源限制的 top-5 依据观察为 2/3；这不是问答准确率，也不足以代表更大数据集的检索效果。人工确认表示核实这份记录，ReAct 漏召回问题继续保留。

当前检索不读取开发题的 `expected_points` 或 `expected_evidence` 来选候选。它们仅供验收对照。用户问题直接向量化；课程中的 HyDE 假设文档检索尚未接入。

## 6. 最少需要掌握的四条 PowerShell 操作

直接调用项目虚拟环境的 Python，无需先激活环境。以下命令依次执行，等前一条退出后再运行下一条。

### 6.1 离线完成整体验收：0 次 API

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'

.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_d4
$LASTEXITCODE
```

`validate_d4` 读取固定索引配置、正式数据、已保存向量和各阶段验收材料，生成 `artifacts/d4/validation.json` 与 `validation.md`。它不读取 `.env`，不调用 embedding 或聊天模型。退出码 `0` 表示本次验收通过；非零时先看本次报告的失败项，不能据旧成功报告宣布数据完整。

该命令需要打开正式 Qdrant 目录，因此运行前结束其他正在持有同一目录的查询或验证进程。它写验收报告，正式原文和向量按只读核对流程使用。

### 6.2 查看可检索版本：0 次 API

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence --list-ready
$LASTEXITCODE
```

它读取已保存索引配置和 SQLite 状态，不读取 `.env`、不打开 Qdrant、不写查询报告。输出应能看到三篇明确论文/处理版本及对应 chunk 数。

### 6.3 根据准确 chunk ID 回查原文：0 次 API

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.query_chunk --chunk-id arxiv_2005.11401v4_r_269ac0cb1263292d_p1_c9
$LASTEXITCODE
```

这个命令只读 SQLite。已知 ID 时无需向量模型，也无需 Qdrant。它显示原文与来源，适合回答“之前检索出的这条 ID 对应什么文字”。

本入口退出码：`0` 是找到并成功核对，`2` 是该 ID 不存在，`1` 是数据库或数据检查失败。它和检索 CLI 的 `2` 含义不同，应分别看各自入口。

### 6.4 输入新问题检索：正常查询 1 次问题 embedding

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.search_evidence `
  --paper-id arxiv_2005.11401v4 `
  --parse-revision r_269ac0cb1263292d `
  --query 'What forms of parametric and non-parametric memory are combined in the RAG model?' `
  --top-k 5
$LASTEXITCODE
```

这条命令在参数、配置和 ready 检查通过后正常发起一次问题 embedding 请求。它读取 `.env` 中已有的向量配置，不重新生成文档向量，不调用聊天模型。相同问题重复执行也会产生新的问题 embedding 请求，因为 E 尚未缓存问题向量。

`--json` 可以追加到本命令，让标准输出变成机器可读 JSON；仍是新查询。仅想看上一次结果时，直接读取保存文件即可：

```powershell
Get-Content -LiteralPath '.\artifacts\d4\retrieval_result.md' -Encoding UTF8
```

最新结果会更新 `retrieval_result.json/.md`，每次查询另存一份 `archive/run_logs/d4/retrieval_<时间>.json`。读取已保存文件为 0 次 API。

| 操作 | embedding 请求 | 聊天模型请求 |
|---|---:|---:|
| `validate_d4` | 0 | 0 |
| `search_evidence --list-ready` | 0 | 0 |
| `query_chunk --chunk-id ...` | 0 | 0 |
| 读取已保存结果 | 0 | 0 |
| 一次正常 `search_evidence --query ...` | 1 | 0 |

请求失败时也可能已经发起过调用，报告按实际次数记录；参数或 ready 检查提前拒绝时则为 0 次。

## 7. D5 在代码中怎样复用检索

检索核心在 [search.py](/D:/course/paper-research-assistant/paper_assistant/search.py)，调用模式是：

```python
searcher = EvidenceSearcher(store, vectors, settings, profile)
result = searcher.search_evidence(
    query=question,
    selected_versions=[(paper_id, parse_revision)],
    top_k=5,
)
```

`store` 是只读 `PaperStore`，`vectors` 是指向正式 collection 的 `QdrantStore`，`settings` 是实际向量配置，`profile` 是已保存并核对的完整索引配置。

下面的示例展示资源打开与关闭方式。它供后续代码接入参考；执行这段示例会发起一次问题 embedding 请求。

```python
from contextlib import closing
from pathlib import Path

from qdrant_client import QdrantClient

from paper_assistant.config import load_embedding_settings
from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher
from paper_assistant.storage import PaperStore
from scripts.search_evidence import load_current_profile

project = Path("D:/course/paper-research-assistant")
index_root = project / "data/index"
profile = load_current_profile()  # 核对当前指针与固定索引清单。
settings = load_embedding_settings()  # 读取模型认证配置，不打印密钥。

# 查询只能打开正式已有库。避免目录缺失时构造器创建新的空存储。
if not (index_root / "qdrant/meta.json").is_file():
    raise ValueError("正式 Qdrant 索引不存在，请先检查任务 D")

with PaperStore(index_root / "papers.sqlite3", read_only=True) as store:
    # QdrantClient 不直接支持 with；closing 保证失败路径也关闭客户端。
    with closing(QdrantClient(path=str(index_root / "qdrant"))) as client:
        if not client.collection_exists(profile["collection_name"]):
            raise ValueError("正式 collection 不存在")

        # 借用已经打开的同一个客户端，不再打开第二个目录锁。
        with QdrantStore(
            index_root / "qdrant",
            profile["collection_name"],
            profile["index_profile_id"],
            profile["recipe"]["dimension"],
            client=client,
        ) as vectors:
            searcher = EvidenceSearcher(store, vectors, settings, profile)
            result = searcher.search_evidence(
                "What forms of parametric and non-parametric memory are combined in the RAG model?",
                [("arxiv_2005.11401v4", "r_269ac0cb1263292d")],
                top_k=5,
            )

# 到这里 SQLite 连接和 Qdrant 客户端均已关闭；result 中仍有完整候选字典。
```

一份本地 Qdrant 目录同时只由一个客户端持有。多个 `QdrantStore` 若要使用同一目录，应借用同一个客户端，最终由拥有者关闭；CLI、离线检查和未来界面不要同时各自打开这个目录。当前 `QdrantStore` 构造器用于建库时可以创建 collection，因此查询必须先检查正式 collection 已存在。

完整多篇范围写成 `[(paper_a, revision_a), (paper_b, revision_b)]`。不要分别传论文列表和版本列表，否则可能错误地形成交叉组合。

## 8. 返回结果中 D5 应使用哪些字段

| 字段 | 用途 |
|---|---|
| `status` | 区分 `success` 与正常空结果 `no_hits` |
| `query` | 保存本轮实际检索问题 |
| `selected_versions` | 本轮允许的完整论文/处理版本配对 |
| `index_profile_id` | 本轮问题与文档使用的索引配置 |
| `top_k`、`returned_count` | 请求上限和实际候选数 |
| `results` | 已回 SQLite 并核对来源的完整候选列表 |
| `statistics` | 本轮问题向量请求次数、真实 token 用量及耗时 |

每条候选含 `rank`、`score`、`point_id`，以及原文 `text`、`chunk_id`、`paper_id`、`parse_revision`、`pdf_page`、文本/PDF 哈希、父 segment 与字符区间、论文来源等字段。

`pdf_page` 是从 1 开始的 PDF 文件页序，不一定是页面上印刷的页码。`score` 是 cosine 相似度，用于候选排序；它不是正确率、事实支持概率或自动通过标记。

D5 引用校验可以复用 [schemas.py](/D:/course/paper-research-assistant/paper_assistant/schemas.py) 的 `EvidenceRef` 四字段：`chunk_id`、`paper_id`、`parse_revision`、`pdf_page`。从完整候选中取出这四字段后构造引用，并额外检查引用确实属于本轮 `results`。结构合法的引用也可能指向不存在或不支持结论的内容，必须同时核对真实存在、来源和语义支持。

已知 `chunk_id` 的精确回查入口是 `PaperStore.get_chunk(chunk_id)`。它不调用模型；不存在返回 `None`，损坏或来源不一致会明确报错。

## 9. 区分三种结果，D5 才能正确处理

| 情况 | E 的表现 | D5 应怎样理解 |
|---|---|---|
| 检索成功且有候选 | `status="success"` | 还要判断候选能否支持问题，再生成有依据的回答 |
| 查询正常但没有候选 | `status="no_hits"` | 本次检索返回空集合；不能据此断言论文一定没有相关内容 |
| 配置、ready、模型服务、向量库或来源检查失败 | 核心抛出 `SearchError`；CLI 保存失败并返回非零 | 属于系统失败，需要显示明确失败原因，不能伪装成论文未提到 |

另有一种很常见的情况：有候选，但候选证据不足。当前 E 不自动把这种情况标为 `no_hits`，因为数据库确实返回了合法片段。ReAct 的摘要题就是例子；D5 先根据问题限制与本轮实际候选正文判断，并明确返回证据不足。受预算限制的自动补检索留到后续 Agent 阶段实现。

检索 CLI 的退出码 `0` 表示执行成功（含 `no_hits`），`1` 表示配置/服务/数据失败，`2` 表示参数用法错误。失败时查看当前命令输出与相应报告，不能让聊天模型编造一个看起来成功的回答。

## 10. D5 还需要实现什么

以下是交接内容，尚未由 D4 自动完成：

1. 接入聊天模型配置与调用，让它读取本轮真实候选。
2. 定义答案输出结构，明确结论、引用与证据不足状态。
3. 让模型依据候选作答，尊重“摘要”“实验设置”“某一版本”等来源限制。
4. 检查引用字段合法、chunk 真实存在、属于本轮候选，且论文/版本/页码一致。
5. 对结论与证据支持度做检查，测试正常事实题及拒答题，区分证据不足与系统失败。
6. 保存本轮问题、候选、答案、引用检查结果和实际请求用量，便于复核。

若进一步尝试 HyDE、重新分块、过滤参考文献或增加上下文，需要形成可解释的新实验，与当前基线比较。更改分块内容会产生新处理版本，更改 embedding 配置会产生新索引配置；不要直接修改已经被引用的旧 chunk。

开发集的标准事实和标注引文仅供评价，不能提前送给检索或答案生成器当作提示来制造通过结果。当前 3 道检索观察可以帮助定位问题，后续问答质量应使用明确题型和更完整的评估记录。

## 11. 之后仍会使用的文件

| 位置 | 后续用途 |
|---|---|
| `data/papers/`、`eval/corpus.json` | 固定原论文、版本和 PDF 哈希 |
| `data/chunks/<paper_id>/<parse_revision>/` | 不可变分块、输入与处理源码快照 |
| `data/index/papers.sqlite3` | 按 ID 回查正文、来源、版本和 ready 状态 |
| `data/index/qdrant/` | 指定范围的相似度检索 |
| `data/index/embeddings/` | 文档向量缓存，重复入库与完整性核对继续使用 |
| `data/index/current_profile.json`、`profiles/` | 当前与固定向量配置 |
| `paper_assistant/search.py`、`storage.py`、`retrieval.py` | D5 直接复用的核心模块 |
| `artifacts/d4/validation.json/.md` | 本次 G 整体验收入口 |
| `artifacts/d4/human_review.json` | 本次 B/F 人工确认与范围 |
| `artifacts/d4/retrieval_review.json/.md` | 三题候选、来源和支持度复核 |
| `artifacts/d4/retrieval_diagnostics/` | ReAct 独立诊断，与正式查询分开 |
| `archive/run_logs/d4/` | 历史结果、阶段边界检查和基线证据 |

运行报告更新后，历史日志继续用于解释旧结果。SQLite、Qdrant、版本快照和文档向量缓存都是后续仍会使用的数据；不要把它们当作已经淘汰的临时输出。
