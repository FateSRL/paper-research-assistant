# D9 E：两模式入口、页面与自检

执行日期：2026-10-06。完成记录见 [task_e.json](/D:/course/paper-research-assistant/artifacts/d9/task_e.json)。D9 A–E 完成各自范围，下一步 F；D7 继续暂缓。

E 把 B 的摘要来源门槛和 C 的剩余预算接到实际入口。页面现在可以选择固定 RAG 或一次补检索 Agent；D9 有自己的配置、历史、latest 和成对批次目录。

2026-10-07 精简后，新运行使用 [runtime_config.json](/D:/course/paper-research-assistant/artifacts/d9/runtime_config.json) 的必要配置和预算，不再绑定历史契约、源码或整份范围表的 SHA。摘要问题使用已核定的 [来源表](/D:/course/paper-research-assistant/artifacts/d9/source_regions.json)，加载一次版本、正文快照与摘要范围；发布时核对实际引用。保留 embedding/index 匹配、输入/输出结构、预算和提交防重跑。成对批次只绑定题目、参数、论文版本、摘要范围和评分标准，续跑不能混用不同条件；旧 prepared 批次需新建，旧输出保持原样。

入口与记录路径：

| 用途 | 实际入口或路径 |
|---|---|
| 两模式单次问答 | `python -m scripts.answer_question_d9 --mode fixed_rag\|agent --query ... --version PAPER_ID PARSE_REVISION` |
| 两模式页面 | `python -m streamlit run app.py` |
| D9 成对批次 | `python -m scripts.run_agent_comparison --stage d9 --batch-id 新ID`；默认只准备 |
| 固定/Agent 当前导出 | `artifacts/d9/fixed_rag_result.json/.md`、`artifacts/d9/agent_result.json/.md` |
| 单次不可覆盖历史 | `archive/run_logs/d9/fixed_rag_<ID>.json/.md`、`agent_<ID>.json/.md` |
| 单次提交预占 | `archive/run_logs/d9/submissions/<token>.attempt.json` |
| 新成对批次 | `artifacts/d9/comparison/<batch_id>/` |

表中的单次问答和明确提交页面会发真实请求。成对 runner 只有明确执行标志才收费：`--live` 为新建并运行，`--execute-prepared` 执行已准备，`--resume` 仅续跑未尝试题。三个标志互斥。旧命令默认 D8，需显式 `--stage d9` 才用新策略；D8 已保存的首次、费用、评分、人审与批次没有迁移或覆盖。本次没有建立 F 的正式批次。

页面提交时固定模式、原问题和完整版本；之后改选择框，已保存结果仍属于原提交。展开证据、重绘和下载只读会话报告，不取可能被别的运行更新的全局 latest。相同提交 token 在执行前预占，发生异常也不能自动重跑；再次明确点击提交才产生新的运行，同样的问题文字也会重新执行。

结果展示五种状态、实际引用原文/PDF 文件页序、来源资格、原始查询、首/补轮轨迹、新召回/新展示、停止原因和用量。未知用量显示未知，不当作 0。资源按每次运行打开和关闭；索引占用在付费前失败。失败诊断中的 `pre_export_result` 保留用于核查，页面和 Markdown 依顶层失败状态隐藏其中的旧成功答案。

按改动选择相关测试方法，不默认运行整套检查。文档/注释修改不跑测试；普通小改动只选 1–3 个现有方法，失败或有具体跨模块影响时再扩大范围。例如检查两模式入口与资源关闭：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -B -m unittest scripts.check_d9_e_runtime.RuntimeChecks.test_actual_cores_citations_closed_resources_and_stage_records -q
```

测试使用临时 PDF、存储和模拟响应，不写新审计报告。页面修改按需要选择已有 AppTest 方法。历史 task_e 及其报告只描述当时版本，不作为当前代码的哈希门槛。学习时重点检查答案对应原文、摘要来源限制、补检索停止条件、用量和下载行为。

完整新 20 题真实对照和 40 模式评分留给 D10，验收题首次运行留给 D11。当前完成不证明答案准确率，也不证明严格 120 秒进程强杀。
