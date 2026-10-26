# A：统一页面聊天入口日志

实施日期：2026-10-12（Asia/Shanghai）。范围来自 [A–C 执行计划](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/d13-query-plan-ABC-plan.md) 的 A。

## 实际交付

`app.py` 移除侧栏问答模式选择与两种方式解释，回答顶部不再显示保存报告中的模式标签。新提交与追问的快照固定为 `mode="agent"`，旧会话中残留的 `question_mode` 不再参与请求。欢迎页沿用“选择论文、提出问题、点击引用回到原文”的现有文案，详情沿用问题、来源、用量和下载。

历史报告仍按原格式读取，固定 RAG 与 Agent 的正文、逐轮引用、来源轨迹和下载使用各自保存的内容。没有改写历史报告，也没有新增 `auto` 模式字段。即时用户消息、局部加载、新对话、历史切换、论文选择与上传流程继续复用原页面逻辑。

## 实际验证

调整既有 `scripts/check_d9_e_page.py` 的提交 helper 和旧模式控件操作：页面入口始终向模拟 runtime 传入 `agent`；两种保存报告格式继续作为展示 fixture，并断言页面没有模式选择、固定 RAG／Agent／自动模式标签。只运行以下两个既有方法，合计 18.519 秒，通过：

- `PageChecks.test_saved_mode_query_pairs_survive_control_changes_and_reruns`：新问与追问、残留旧模式状态、两种历史报告格式、论文与会话切换、各轮原文恢复、重绘和历史下载不再次执行问答。
- `PageChecks.test_downloads_and_download_failure_only_use_saved_report`：已有 JSON／Markdown 下载继续使用保存报告；导出失败时回退完整 JSON，下载不再执行问答。

另在临时模拟服务中打开真实 Streamlit 页面，查看欢迎页和侧栏，分别切回两种旧报告，展开回答详情，点击引用编号看到对应原文与 PDF 文件页序，并下载旧报告 JSON。下载内容保留原 `fixed_rag` 字段和原问题，页面没有方式标签。随后开启新对话、提交首问与追问，看到同会话内两轮消息；服务只记录这两次明确提交，历史切换、引用及下载没有重复问答。临时服务和标签页已关闭，没有保存截图或独立验证报告。自动审批以 `blocked by policy` 拒绝临时文件清理，改用逐个指定文件的清理命令仍被拒绝；模拟脚本及服务输出保留在 `C:\Users\ggy\AppData\Local\Temp\paper-query-plan-ui-20261012`，模拟下载保留在 `E:\Downloads\answer_offline-history-one.json`。

两个测试方法没有失败。浏览器首次等待引用弹窗定位超时；读取按钮仍为关闭的实际状态后重新打开，成功看到原文。运行输出包含 Streamlit AppTest 的 `missing ScriptRunContext` 提示和现有 PyMuPDF `fitz` 弃用提示，方法均正常完成。真实模型、embedding 与重排请求均为 0；未运行整个测试模块或回归批次，未新增哈希、审计或独立验证报告。

## 取舍与下一步

页面直接统一使用现有 Agent 入口，后台仍保存实际模式与过程，CLI／对照实验中的固定 RAG 能力继续沿用。此次统一入口只改变页面操作，不代表检索覆盖已经改善。同轮完成的 B 见 [问题规划日志](/D:/course/paper-research-assistant/docs/v1/d13-query-plan/B-question-planning-guide.md)；下一步 C 接通多查询执行与统一回答。
