# A：本地 PDF 入库日志

完成日期：2026-10-09。A 已实现并通过针对性离线验证；当时前端上传入口留给 C，现已接通，见同目录 C-upload-guide.md。

## 实际修改

新增 `paper_assistant/import_runtime.py` 的 `import_pdf()`，直接串联现有 PDF 解析、过滤、分块、SQLite 和向量入库。保存原 PDF、raw、filtered、chunks 和存储所需的版本清单；不调用旧整套快照流程，不复制 Python 源码，不生成全文件哈希列表或审计产物。

新 PDF 使用 `local_` 标识，标题默认文件名，arXiv 版本和外部链接允许为空。存储、引用读取及既有 Markdown 导出已接通本地来源；新摘要的实际边界传给原分块函数，使摘要与正文不落在同一个混合 chunk，原调用不传边界时行为保持一致。

相同 PDF 通过已有 `pdf_sha256` 找到库内原论文与处理版本，包括已有三篇论文；直接复用元数据、原文文件和 embedding 缓存，不重新解析或改写旧版本。索引失败后再次调用可沿用同一版本重试，已完成版本再次导入不发 embedding 请求。解析、过滤、分块、索引和批次进度通过 `on_progress` 回调返回，供 C 使用。

不能打开、需要密码或没有可索引正文的 PDF 在 embedding 前停止。结果含 `status`、`stage`、论文／版本、chunk 数及本次 embedding 请求数，失败返回原因；未增加自动重试或另一套入库状态。

## 使用入口

下面是服务调用方式；实际入库会使用当前配置的 embedding 服务。本轮验证使用模拟服务，没有运行这段真实调用。

```python
from pathlib import Path
from paper_assistant.import_runtime import import_pdf

pdf = Path(r"D:\你的论文.pdf")
result = import_pdf(pdf.read_bytes(), pdf.name, on_progress=print)
print(result)
```

`status="ready"` 后可以用返回的 `paper_id` 和 `parse_revision` 进入 B 的问答入口。重试再次调用同一 PDF 即可；不需要修改 `eval/corpus.json`。

## 实际验证

只扩展并运行两个既有方法：`SQLiteStorageChecks.test_first_import_preserves_text_and_all_source_fields` 和 `IndexChecks.test_successful_import_and_repeat_make_no_second_embedding_request`，初次 1.358 秒通过。后者使用真实临时 PDF、临时 SQLite／Qdrant 和模拟 embedding，覆盖首次失败、同版本重试、重复导入零新增请求及本地原文回查。

补充“实际薄版本由 B 的 Registry 读取，并仅认定真实摘要 chunk”的衔接断言后，只重跑索引方法，1.259 秒通过；存储方法结果复用。没有全量回归、独立验证报告或真实模型／embedding／重排请求，正式三篇与索引未改动。
