# D6 任务 D：最小论文问答页面

完成日期：2026-10-04（Asia/Shanghai）。页面已实现并完成离线检查和一次真实浏览器问答。开发集仍为 16 题，20 道冻结验收题未运行。

## 1. 怎么打开和使用

当前本地地址：[打开论文研究助手](http://127.0.0.1:8501)。如果服务已经关闭，在 PowerShell 中运行：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -m streamlit run .\app.py `
  --server.address 127.0.0.1 --server.port 8501 --server.headless true `
  --browser.gatherUsageStats false
```

Streamlit 已安装并固定为 `1.65.0`，`pip check` 通过。新环境先用项目 `.venv` 安装 `requirements.txt`，并按 `.env.example` 配置聊天和 embedding 服务。

1. 选择 1–3 篇已完整入库的论文，所选完整版本可在折叠项中查看。
2. 输入问题，点击“提交问题”。只有提交才执行问答；这一步会使用模型额度。
3. 查看本次状态、结论及引用原文。页码表示 PDF 文件从第一页开始的页序。
4. 下载完整 JSON 或 Markdown，保存本次问题、原文、回答及运行记录。

页面保留当前会话最近一次结果。切换选择、展开证据、页面重绘和下载已有结果不会重复执行问答；页面刷新或会话结束后，已保存的 JSON/Markdown 和历史文件仍可回查。页面只监听本机，现阶段不支持上传、多人并发或公网部署。页面与 CLI 使用同一份本地 Qdrant，避免同时提交；资源占用会显示工具失败。

## 2. 五种状态怎么看

| 状态 | 页面显示 | 可以做什么 |
|---|---|---|
| `answered` | 已回答、结论、引用 ID、原文和文件页序 | 读原文判断结论是否被充分支持；下载记录 |
| `insufficient_evidence` | 本轮证据不足、缺少什么及实际展示的证据 | 检查问题范围和本轮证据；不足不代表全文没有答案 |
| `tool_error` | 工具或本机步骤失败、已有证据及用量 | 检查配置、索引占用或导出记录，手动决定后续处理 |
| `invalid_output` | 模型输出未通过检查 | 查看记录；本轮没有发布答案 |
| `budget_exceeded` | 本轮预算已到 | 查看已有记录和用量；流程停止，不自动重新提交 |

未知用量显示为“未知”，记录中保留 `null`。输入为空、选择非法或版本未 ready 时，在收费和运行文件写入前拒绝。

五种终态的实际页面元素通过 AppTest 构造检查，使用 mock runtime；只有下述首题是真实浏览器与模型运行。这两种证据分别保存。

## 3. 实际完成了什么

- [app.py](/D:/course/paper-research-assistant/app.py)：表单、五终态、引用原文、用量与下载。完整报告保存在 `session_state`，只有表单提交分支调用问答。
- [web_runtime.py](/D:/course/paper-research-assistant/paper_assistant/web_runtime.py)：页面服务适配层，直接复用现有 `rag.answer_question`，固定 top-5、8000 字符。C 的 top-k 对照结果没有改变页面或 CLI 的默认值。
- 每次提交新建预算、聊天客户端和只读 SQLite 连接，只打开一个 Qdrant 客户端，结束或失败均关闭资源；页面不缓存这些资源。
- 复用既有 `answer_export.py` 保存独占历史、生成 Markdown；下载根据当前会话报告生成，不读取其他会话的最近答案。Markdown 的完整 JSON 链接指向本轮 D6 历史。
- 原 D5 核心、CLI、历史输出及正式题集保留；新记录进入 `artifacts/d6/` 和 `archive/run_logs/d6/`。

沿用现有有界聊天策略，保留请求、重试、修复和已知/未知用量。同步调用的硬性总墙钟中断尚未验证；本次没有扩大这项保证。

表单和下载的行为参考 [Streamlit 表单文档](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form) 与 [下载按钮文档](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button)。

## 4. 验证记录

新增离线检查：**27/27 通过**，覆盖资源构建/关闭、单 Qdrant、错误保留费用、不可覆盖历史、五终态，以及实际 AppTest 点击下载和重绘不重新提交；外部 API 为 0，没有重跑 D5 旧测试。

- [最终离线检查](/D:/course/paper-research-assistant/artifacts/d6/web_validation_20261004_085349_258484.json)
- [五终态实际 AppTest 展示记录](/D:/course/paper-research-assistant/artifacts/d6/web_five_state_examples_20261004_085349_258484.json)
- [真实浏览器验证](/D:/course/paper-research-assistant/artifacts/d6/web_browser_validation_20261004_084015_594560.json)
- [任务 D 完成记录](/D:/course/paper-research-assistant/artifacts/d6/task_d.json)

真实浏览器只提交已有开发题 **D2-001** 一次，选择 RAG 固定 ready 版本；终态 `answered`，3 条结论、5 次引用、2 个原文来源，PDF 文件页序为 1 和 2。实际点击 JSON、Markdown 下载，字节与本轮报告一致；使用 Rerun 菜单后仍只有一份历史记录。

本次真实用量：embedding **1 次 / 34 tokens**，聊天 **1 次 / 2758 tokens**，重试 0、修复 0。这是页面流程验证，未进行新的答案人审，也不提供准确率。

运行 ID：`20261004_084728_605824_56ee5aabb650`。不可覆盖历史见 [本轮完整 JSON](/D:/course/paper-research-assistant/archive/run_logs/d6/web_answer_20261004_084728_605824_56ee5aabb650.json)，可读副本见 [本轮 Markdown](/D:/course/paper-research-assistant/artifacts/d6/web_answer_result.md)。真实运行时的页面源码已单独保存；随后只修正输入失效提示，最终源码另经 27 项离线检查绑定。模型调用和运行记录没有重跑或覆盖。

![真实问答页面](/D:/course/paper-research-assistant/artifacts/d6/web_evidence/answered_page_20261004.png)

## 5. 下一步

D 已完成。继续 E 的四道开发候选题及实际复核，随后进行 F 边界汇总和 G 交接；自动补检索仍为 D8 计划，冻结验收题留到 D11。
