# D6 任务 A：六题复核合并、新答案抽审与开发集更新

日期：2026-10-04。**任务 A 完成：六道候选题经用户实际复核全部通过并合并；新六题完成首次真实运行；十题旧答案完成三题整题抽审。** 全量语义人审仍为待补，本指南不把它写成已完成。用户原话：六题复核“没问题，六个题目都可以”；抽审“三个题我都觉得合理”。

记录入口：[合并记录](/D:/course/paper-research-assistant/artifacts/d6/candidate_merge_record.json)、[抽审记录](/D:/course/paper-research-assistant/artifacts/d6/human_review_spotcheck_10case_answers.json)。合并前备份：`artifacts/d6/dev.jsonl.pre_merge_backup_20261004`（SHA256 `53fc378d…`）。

## 1. 六题人工复核与合并

用户对 D5-001 ~ D5-006 的问题、期望要点、标注原文与 PDF 页码实际核对后确认全部通过。复核前后的事实分开记录：

- **AI 视觉核对（不替代人审）**：六处引文与 `artifacts/d5/eval_candidate_evidence/` 的整页截图逐字核对，页码全部一致；核对记录写入复核材料附录。
- **用户复核**：六题实际确认；`eval_candidate_human_review.json` 的 `status` 由 `pending` 更新为 `approved`，记录确认日期与用户原话。
- **合并**：六题以 `human_verified` 并入 `eval/dev.jsonl`，正式题集 10 → 16 题；原十题逐字节未变（与备份逐行核对通过）；候选 JSONL 保持只读未改（哈希核对一致）。
- 目标分布达到 `8 fact / 3 method / 2 retrieval_paraphrase / 3 unanswerable`。

## 2. 新六题首次真实运行

新批次 `d6_f_dev16_20261004`（`artifacts/d5/qa_baseline/`），只补跑六道新题，前十题保持 unattempted，未重复付费。结果：

| 指标 | 数值 |
|---|---|
| 程序终态 | 4 answered + 2 insufficient_evidence（两道无答案题均未编造答案） |
| 精确全部标注引文命中 | 4/4（返回与展示同） |
| 最终引用定位合法 | 10/10，拦截 0 |
| 重试 / 修复 | 0 / 0 |
| 用量 | embedding 6 次/292 tokens；聊天 6 次/12736 tokens；总耗时 37.3 秒 |

两个批次（D5 十题、D6 六题）源码哈希相同、题集绑定不同；聚合 16 题统计时必须说明来源批次。批次的 AI 语义评价尚未生成，本条不提供该批的语义支持数字。

## 3. 十题旧答案三题整题抽审

从 D5 十题批次抽 D2-001、D2-005（answered）与 D2-003（insufficient_evidence）三题，每题整题审、逐条结论对照所引原文；D2-003 审拒答理由。抽审材料由 AI 从冻结输出与 SQLite 原文准备，判断由用户做出。

用户确认三题均合理。记录要点：

- 这是**整题确认**，涉及两道回答的 7 条结论和一道不足理由；**不提供**逐条人工支持率，全批 19 条结论的整体人工支持率仍为 `null`。
- 旧的 AI 复核计数保持独立；程序定位检查、AI 判断、用户确认三者分开记录。
- 抽审不改变任何已保存输出与 AI 记录；绑定哈希见抽审记录。

## 4. 本次修正与遗留

- 合并改变了 `eval/dev.jsonl` 的哈希：`scripts/validate_d5.py` 按设计会报告源码漂移（失败码 `D4_data_and_A_E_old_records_unchanged`），这是**预期自检**，不是事故；旧通过记录保留在 `archive/run_logs/d5/`。
- 16 题里剩余 12 条结论的人工核对、六道新题的语义评价，按需要再补；本任务不把它们写成已完成。
- 两道首次运行中的检索不足（D2-002、D2-003）原样保留，未改标注、未加大 top-k 覆盖。

## 5. 相关入口

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
Get-Content -LiteralPath '.\artifacts\d6\candidate_merge_record.json' -Encoding UTF8
Get-Content -LiteralPath '.\artifacts\d6\human_review_spotcheck_10case_answers.json' -Encoding UTF8
.\.venv\Scripts\python.exe -X utf8 -c "import json; [print(json.loads(l)['case_id']) for l in open('eval/dev.jsonl', encoding='utf-8')]"
```

逐题运行记录在 `artifacts/d5/qa_baseline/d6_f_dev16_20261004/results/`；D5 十题首次结果保持在其原批次目录。
