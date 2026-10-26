# D6 任务 B：验收题准备、来源核对与内容锁定

日期：2026-10-04。**任务 B 已完成：20 道验收题经用户实际核对通过，正式题集与评分规则已冻结。** 用户原话为“已实际核对，20题全部通过”。本次仅冻结题目标注，尚未运行验收问答或取得验收成绩。

正式入口：[验收题集](/D:/course/paper-research-assistant/eval/acceptance.jsonl)、[人审记录](/D:/course/paper-research-assistant/artifacts/d6/acceptance_human_review.json)。原候选材料保留人审前文本，当前状态以人审记录和正式冻结声明为准：[20题复核材料](/D:/course/paper-research-assistant/artifacts/d6/acceptance_candidate_review.md)、[候选 JSONL](/D:/course/paper-research-assistant/artifacts/d6/acceptance_candidates.jsonl)、[评分规则](/D:/course/paper-research-assistant/eval/acceptance_rubric.md)、[锁定声明](/D:/course/paper-research-assistant/artifacts/d6/acceptance_freeze_manifest.json)。

## 1. 已完成范围

候选覆盖 RAG、ReAct、Reflexion 三篇固定 PDF：10 fact、4 method、3 retrieval_paraphrase、3 unanswerable。17 道正例的 28 段原文逐一匹配 native PDF、正式 indexable filtered segment 和 SQLite；14 个相关完整 PDF 文件页已渲染并经 AI 视觉核对。三个无答案题分别问 Reflexion 每题 token 用量、RAG 索引人工事实核对比例、ReAct search 网络延迟；全文和相关小节核查与关键词结果一起保留，关键词缺失本身不作为证明。

候选与当前 16 道开发题做了 AI 事实级复核，剔除了过于接近旧开发答案的 BART 型号/参数题；四个独立事实族预留给 E，未来补题仍须再次审核与验收事实有无近似重复。本次没有运行验收题检索，没有生成验收题答案，项目 embedding/chat 请求均为 0。

证据与 AI 初审：[来源检查](/D:/course/paper-research-assistant/artifacts/d6/acceptance_source_validation.json)、[无答案范围核对](/D:/course/paper-research-assistant/artifacts/d6/acceptance_negative_source_validation.json)、[AI 交叉复核](/D:/course/paper-research-assistant/artifacts/d6/acceptance_ai_review.json)、[页图来源清单](/D:/course/paper-research-assistant/artifacts/d6/acceptance_evidence/manifest.json)。这些不能替代实际人审。

## 2. 本次同时修正的问题

A 的抽审记录改为 3 题整题确认：两道回答包含 3+4=7 条结论，另一道不足理由获确认。没有逐条独立打分，因此不写 4/4 或 7/7 人工结论支持率；其他 12 条旧批次结论未涉及。原十题内容未改，前六行仅 CRLF 规范化为 LF。旧记录的原文件已备份，不新增人审结论。

D6 计划、README 和两个总计划更新为开发集 16 题、A 已执行、B 待人审。C 只使用开发集；独立入口支持一次 top-20 检索派生 5/10/20，返回候选和实际展示分别打分，不调用聊天。旧 D5 问答/批跑继续固定 top-5。新入口的 13 项 mock 边界检查已通过；本轮仅离线汇总旧首次结果作为入口验证，C 的真实 top-k 实验尚未执行。

## 3. 实际人审与正式冻结

原 D6 计划第 5.2 节要求“人工核对的原文 quote、PDF 文件页序、PDF 哈希、复核人、状态”；第 2 节要求“AI 初审、程序检查、用户实际复核分别记录”。因此需要你实际对照 20 题材料确认问题、要点、页码和无答案标签。

用户已实际确认 20 题全部通过，已发布 `eval/acceptance.jsonl` 并记录正式 SHA；正式副本仅增加实际人审元数据，问题、期望要点、原文与可答性均与锁定候选相同。原候选继续保留初审时的 pending 字段，避免重写人审前快照。若有题需要修改，先形成新候选版本、重新核对和锁定，保留原内容锁定声明。D11 前不跑验收题、不使用它调优。

## 4. 查看或离线核对

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
Get-Content -LiteralPath '.\artifacts\d6\acceptance_candidate_review.md' -Encoding UTF8
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_acceptance_candidates
```

来源核对命令只读 PDF、filtered、SQLite 和题目文件，不加载 .env、不打开 Qdrant、不发 API，也不会把候选发布为正式验收集。完整阶段记录见 [task_b.json](/D:/course/paper-research-assistant/artifacts/d6/task_b.json)。
