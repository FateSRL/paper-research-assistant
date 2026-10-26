# B：新论文接入问答日志

完成日期：2026-10-09。B 已实现并通过针对性离线验证；当时前端上传与局部入库进度留给 C，现已接通，见同目录 C-upload-guide.md。

## 实际修改

`d9_runtime.run_question()` 增加 `library_mode` 参数。现有页面后台调用传入 `True`，从当前 embedding 配置对应的 SQLite ready 集合选择论文，并保存本轮论文信息；默认 `False` 仍使用原冻结范围，原 CLI／批量评测不会因上传扩充样本。

新本地版本的来源从 SQLite 已保存版本信息中的 filtered／chunks 路径和 `source_regions` 读取。旧三篇继续使用旧来源表；只选本地论文时不依赖旧三篇的来源文件。没有新增第二套来源库或校验机制。

`detect_abstract_regions()` 根据明确的 `Abstract`／“摘要”标题与后续章节或关键词边界定位实际字符区间，不生成摘要或摘要哈希。A 在这些边界切块；范围无法确定时保留空范围，普通正文问答仍可执行，明确摘要限定问题沿用现有范围不可用处理，不给予正文摘要引用资格。

本地论文的空 arXiv 版本、可选来源链接已接通列表、引用读取和展示。两模式共享原混合检索、重排、调用预算、连续对话和逐轮引用；旧答案继续使用自身保存的来源，新上传不改写评测清单、历史配置或旧来源表。

## 使用入口

对 A 返回的 ready 结果，可以直接调用现有问答核心；这会使用正常问答额度。本轮没有发起真实调用。

```python
from paper_assistant.d9_runtime import run_question

report = run_question(
    "这篇论文提出的方法是什么？",
    [(result["paper_id"], result["parse_revision"])],
    mode="fixed_rag",  # 也可用 agent
    library_mode=True,
)
```

已有入库论文会出现在页面选择列表中；C 已提供侧栏“添加论文”的上传按钮和局部进度。连续追问沿用页面原会话机制。

## 实际验证

扩展并运行既有 `RuntimeChecks.test_unfrozen_full_pair_is_zero_requests`，1.601 秒通过：保留默认冻结入口拒绝的原断言，覆盖本地 ready 版本两模式、正文／摘要、追问重新读取旧引用、缺摘要及未 ready 版本；使用 SDK 模拟响应和临时来源。

页面原 runtime 模拟签名同步增加 `library_mode`，并断言页面传入 `True`。运行既有 `PageChecks.test_saved_mode_query_pairs_survive_control_changes_and_reruns`，10.808 秒通过，覆盖模式、论文集合、会话、旧引用和导出。

没有请求真实模型、embedding 或重排服务，没有运行全量回归、新批量评测或生成独立验证报告。离线结果不代表真实问答准确率；后续上传浏览器操作验证记录于 C 的日志。
