# D4 任务 C：SQLite 实现与逐步解释

执行日期：2026-10-01。任务 C 已完成：三篇论文、三个处理版本、1188 个 chunk 已保存到 `data/index/papers.sqlite3`。下面说明实际代码做了什么，以及为什么需要这些步骤。

## 1. 这一步解决什么问题

任务 B 给了每段原文一个稳定的 `chunk_id`。任务 C 建立“给出这个 ID，就能找到保存的原文和论文来源”的能力。

例如，输入 `arxiv_2005.11401v4_r_269ac0cb1263292d_p1_c9`，程序能返回 RAG 的标题、作者版本、处理版本、PDF 文件页 1、文本哈希和当时保存的摘要原文。后续向量检索找到 ID 后，用同一个接口取得证据，不需要再次解析 PDF。

SQLite 是本机磁盘上的数据库，项目使用 Python 的标准库 `sqlite3`，无需安装数据库服务。关闭 Python 程序后，数据库文件和已提交的内容继续保留。[Python 3.11 官方说明](https://docs.python.org/3.11/library/sqlite3.html)

## 2. 第一步：加载已经保存的分块版本

入口是 [load_chunk_version()](/D:/course/paper-research-assistant/paper_assistant/chunk_snapshot.py:40)。它读取：

```text
data/chunks/<paper_id>/<parse_revision>/
  version_manifest.json
  paper.json
  chunks.jsonl
  raw.pages.jsonl
  filtered.pages.jsonl
  quality_rules.json
  pipeline/ 中的三个处理代码快照
```

程序先核对目录中的论文与版本，再验证处理指纹、文件哈希、PDF 来源、页序，以及每个 chunk 是否等于父片段的准确字符切片。还检查重叠和覆盖，避免少存一段或跨越过滤边界。

**为什么：**数据库的输入也需要检查。文件存在、JSON 能读出来，都不代表它就是指定论文的完整分块结果。如果文件改过却沿用旧 ID，后续引用会指向不确定的文字。这里在写库之前拒绝这种情况，而不是入库时重新生成或修补旧版本。

处理代码快照只用于核对字节，程序不会执行其中的源码。历史版本使用自己保存的派生文本，不要求它等于未来最新的过滤文件；已入库旧版本可以直接回查。

## 3. 第二步：连接数据库并建立四张表

实现位于 [PaperStore](/D:/course/paper-research-assistant/paper_assistant/storage.py:312)。数据库不存在时，写入入口创建空库和表；已有数据库必须符合当前 `user_version=1` 的结构。未知结构会明确报错，不自动删除或重建。

| 表 | 当前条数 | 保存什么 | 为什么独立保存 |
|---|---:|---|---|
| `papers` | 3 | ID、标题、作者版本、链接、PDF 路径/哈希、页数 | 每篇论文的来源只保存一次，所有 chunk 共用 |
| `parse_versions` | 3 | 论文+处理版本、完整指纹、快照位置、统计及完整清单 | 同一篇论文以后可有多个处理版本，旧版本仍能定位 |
| `chunks` | 1188 | chunk ID、原文、页码、哈希、父片段和字符范围 | 保存后续检索、引用回查真正需要的证据 |
| `index_imports` | 0 | 处理版本与向量索引配置的导入状态 | 供任务 D 使用，区分向量导入 pending/ready/failed |

表可以理解为一种有字段约束的记录集合，行是一条记录，列是某一个字段。例如 `chunks` 一行对应一个 chunk，`text` 列就是它的原文。

上表的 `index_imports=0` 是任务 C 完成时的状态；后续任务 D 已建立三条 ready 记录。当前状态见 [向量导入报告](/D:/course/paper-research-assistant/artifacts/d4/import_report.json)，这份 C 说明及历史报告保留 C 阶段的统计。

## 4. 第三步：用主键和外键保持数据关系

主键负责唯一身份：

- `papers.paper_id`：同一篇固定论文不能出现两条相互冲突的来源。
- `parse_versions` 的 `(paper_id, parse_revision)`：同一论文的同一处理版本只能登记一次。
- `chunks.chunk_id`：同一个原文块 ID 只能有一份保存内容。

外键负责关联：

```text
papers.paper_id
    ↓
parse_versions.(paper_id, parse_revision)
    ↓
chunks.(paper_id, parse_revision)
```

**为什么：**只有唯一 ID 还不够。一段 chunk 如果引用不存在的论文或处理版本，就是失联数据；外键阻止这种记录进入数据库。程序在每个连接上开启 `PRAGMA foreign_keys=ON`，因为该开关属于连接。[SQLite 外键官方说明](https://www.sqlite.org/foreignkeys.html)

页码必须大于零、字符范围必须合法、文本长度必须与区间长度一致等约束，也写入表定义。Python 在入库前检查一次，数据库再守住最基本的边界。

## 5. 第四步：用一篇一个事务写入

核心函数是 [import_version()](/D:/course/paper-research-assistant/paper_assistant/storage.py:424)。顺序为：

```text
校验内存中的论文、清单与 chunks
    ↓
BEGIN IMMEDIATE
    ↓
核对已有论文与处理版本
    ↓
必要时写入论文 → 处理版本 → 全部 chunks
    ↓
全部成功：COMMIT
发生异常：ROLLBACK
```

**为什么：**如果论文信息已写入，只写了前一百块程序就失败，用户不应该看到一份缺少后续原文的“完整版本”。事务把同一篇的这些修改当成一组：全部成功才保留，失败则撤销本次这篇的修改。

`BEGIN IMMEDIATE` 在核对是否已有记录之前取得写锁，减少两个导入进程同时判断“还不存在”而争抢插入的情况。三篇分别提交；一篇的写入错误不会撤销另一篇已经成功保存的版本，命令报告会明确区分成功与部分失败。

## 6. 第五步：重复导入先核对，内容相同才复用

程序发现论文/版本已有记录后，会核对元数据、处理指纹、清单哈希、快照位置、全部 chunk ID 和完整 chunk 内容：

- 全部相同：返回 `reused=True`、`inserted_chunks=0`。
- 同一 ID 的内容不同、缺失或多出：报 `StorageConflict`，不覆盖，也不静默补洞。
- 新处理版本：新增该版本及其 chunk，保留旧版本。

**为什么：**你之后可能反复运行同一个命令。重复执行不能把 1188 条变成 2376 条，也不能把已有 ID 对应的原文改掉，否则旧答案的引用会失效。

数据库还为论文、处理版本和 chunks 建立禁止 UPDATE/DELETE 的触发器。触发器是在数据库收到指定操作时自动执行的规则；它让误用直接 SQL 也不能改写已经保存的证据。未来确需修改表结构时，应明确做数据库迁移。

## 7. 第六步：参数化 SQL 保存原文

写入代码使用 `?` 占位符传数据，查询也是：

```python
row = connection.execute(
    "SELECT * FROM chunks WHERE chunk_id = ?",
    (chunk_id,),
).fetchone()
```

**为什么：**SQL 命令和数据需要分开。原文中有引号、中文、换行，甚至一段看起来像 SQL 的文字，都应该作为数据保存，而不是参与拼接 SQL 命令。`(chunk_id,)` 是只包含一个元素的元组，末尾逗号不能省略。

原文不调用 `strip()`，不替换断词或换行。数据库同时保存易查询的普通列和完整 `record_json`；JSON 记录保留字符范围、行号、bbox 等完整信息，读回时还会核对两者一致。

## 8. 第七步：按 ID 只读回查

核心函数是 [get_chunk()](/D:/course/paper-research-assistant/paper_assistant/storage.py:483)。它使用 JOIN 把 chunk、处理版本和论文关联起来，补齐标题、作者版本、来源链接和 PDF 路径。然后重算原文哈希，核对页码和来源，返回一个字典。

**为什么：**后续检索通常先拿到 chunk ID，用户需要的是能阅读和核对的完整证据。代码从保存的事实中补齐来源字段，避免让模型自行编造页码或原文。

命令 [query_chunk.py](/D:/course/paper-research-assistant/scripts/query_chunk.py) 使用 `mode=ro` 的只读连接；库不存在就报错，不会意外创建一个空库。ID 不存在返回明确的 NOT FOUND 与退出码 2；数据库错误返回退出码 1；成功回查退出码 0。

`with PaperStore(...)` 使用结束会关闭连接，释放资源；已经提交的数据库内容仍在磁盘上。

## 9. 第八步：验证保存结果并留下报告

实际验收如下：

- 首次导入：3 篇、3 个版本、1188 个 chunk。
- 再次导入：三篇均复用，新增 chunk 为 0。
- 新 Python 进程只读打开数据库，逐一核对 1188 个 chunk 的全部字段与快照一致。
- SQLite 完整性检查通过，外键检查没有失联记录。
- 39 个原始输入和分块快照的内容哈希保持不变。
- [check_storage.py](/D:/course/paper-research-assistant/scripts/check_storage.py) 的 14 项边界检查通过，包括事务中途失败回滚、旧版本保留、冲突拒绝和直接 SQL 改写保护。测试材料只在系统临时目录。

当前结果见 [入库报告](/D:/course/paper-research-assistant/artifacts/d4/storage_report.json) 与 [完整验收报告](/D:/course/paper-research-assistant/artifacts/d4/storage_validation.json)。每次导入的历史日志进入 `archive/run_logs/d4/`，保持当前目录简洁。人工抽样状态仍 pending，数据库入库没有替你完成论文内容的人工判断。

## 10. 自己运行的命令

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'

# 三篇当前版本入库；已经存过时核对并复用
.\.venv\Scripts\python.exe -X utf8 -m scripts.store_chunks

# 只入库一篇的明确处理版本
.\.venv\Scripts\python.exe -X utf8 -m scripts.store_chunks --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d

# 回查 RAG 第 1 页的一个摘要块
.\.venv\Scripts\python.exe -X utf8 -m scripts.query_chunk --chunk-id arxiv_2005.11401v4_r_269ac0cb1263292d_p1_c9

# 查看上一条命令退出码
$LASTEXITCODE
```

阅读代码建议按 `store_chunks.main()` → `load_chunk_version()` → `PaperStore` 建表 → `import_version()` → `get_chunk()` 的顺序。`main()` 是实际命令流程，负责参数、调用和结果报告；检查脚本是另一套只用临时材料的验收入口。

任务 D 已为这些已保存 chunk 生成 embedding 并写入 Qdrant，见 [逐步说明](/D:/course/paper-research-assistant/docs/v1/d4/d4-D-index-guide.md)。下一步 E 由问题向量检索找出相关 ID，再调用本次的 `get_chunk()` 取得原文，串成语义检索命令。
