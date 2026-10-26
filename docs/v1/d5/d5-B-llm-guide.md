# D5 任务 B：完整聊天响应、共享预算与安全错误

完成日期：2026-10-02（Asia/Shanghai）。B 已完成，下一步是 C 的证据上下文与结构化生成。本文对应 [D5 总计划](/D:/course/paper-research-assistant/docs/v1/d5/d5-ABCDEFG-plan.md) 的任务 B；入口代码为 [llm_client.py](/D:/course/paper-research-assistant/paper_assistant/llm_client.py)。

本次 34 项离线检查通过；真实聊天连通验证成功，1 次 HTTP 请求、56 tokens、embedding 0 次。这是聊天适配层验证，尚未执行论文问答或计算答案正确率。完成汇总见 [task_b.json](/D:/course/paper-research-assistant/artifacts/d5/task_b.json)。

## 1. 为什么要补这一层

D2 的 `invoke_llm()` 使用 HelloAgentsLLM，固定输出上限 128 tokens，只返回字符串。B 保留这个入口，让原连通脚本继续可用；新增 `RecordedLLM` 使用已安装 OpenAI 兼容 SDK 的公开接口，取得文本、usage 和 finish_reason。

长 chunk ID 会占用答案长度；返回文本也可能是截断或空响应。因此调用成功、JSON 可解析、`AnswerDraft` 合法、引用真实有效需要逐层判断。B 负责前两层的传输与基础输出检查，C/D 接着完成草稿与引用检查。

SDK 设置 `max_retries=0`，HTTP 客户端关闭重定向。项目代码决定重试，并分别记录 SDK 尝试和 HTTP 发出尝试；失败请求也计入预算。HTTP 尝试数表示客户端进入发送流程，不表示服务端一定收到或完成请求。

## 2. 接口怎样配合

| 接口 | 职责 |
|---|---|
| `ChatPolicy` | 校验温度、输出长度、超时与次数限制；默认值见下表 |
| `ChatBudget` | 保存共享截止时间、尝试数、网络重试数、修复数与所有响应记录 |
| `RecordedLLM` | 读取既有聊天配置、发请求、记录结果、分类故障并关闭客户端 |
| `LLMCallError` | 携带 `status`、`code`、本次 attempts 和共享 statistics；使用安全错误摘要 |

| 参数 | B 实际默认值 |
|---|---:|
| `temperature` | 0.2 |
| `max_tokens` | 1200 |
| `request_timeout` | 30 秒 |
| `max_attempts` | 3 |
| `max_network_retries` | 1 |
| `max_repairs` | 1 |
| `total_timeout` | 120 秒 |

配置继续从 `load_llm_settings()` 读取；本机真实验证使用 `deepseek` / `deepseek-flash`。DeepSeek 请求显式关闭 thinking，以使本次温度参数参与采样。相关行为与参数见 [DeepSeek thinking mode 文档](https://api-docs.deepseek.com/guides/thinking_mode/)。实际非敏感配置见 [chat_runtime_config.json](/D:/course/paper-research-assistant/artifacts/d5/chat_runtime_config.json)。

输入只接受非空消息列表，角色为 `system`、`user`、`assistant`，每条包含非空字符串 `content`。非法参数在请求前失败，0 次请求。密钥、认证头、原始服务错误体和完整配置对象不写入记录；正常输出中的当前密钥及 Bearer 内容也会脱敏。

## 3. 生成与修复必须共用预算

```python
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM

policy = ChatPolicy()
budget = ChatBudget(policy)
messages = [
    {"role": "system", "content": "Return only valid JSON."},
    {"role": "user", "content": 'Return {"ok": true}.'},
]
with RecordedLLM(policy=policy, budget=budget) as client:
    result = client.invoke(messages, require_json=True)
    # C/D 检查输出与引用后，如确有错误，再调用：
    # repaired = client.invoke(repair_messages, purpose="repair", require_json=True)
```

这段是接口示例，执行会真实请求聊天服务。C/D 开始整轮问答时就创建 `ChatBudget`，让检索、生成、修复使用同一截止时间；检索前后由编排层检查剩余时间。不能在修复时创建新 budget 重置次数。重新打开客户端时也可传入原 budget。

正常生成、修复和网络重试最多合计三次 SDK 尝试；网络重试全局最多一次，显式修复最多一次。修复中的网络故障也受同一限制。B 不自动修复答案，C/D 根据草稿或引用错误构建修复消息，再用 `purpose="repair"` 请求。

401/403、普通 400 等错误直接结束；408/409/429、5xx 与连接/请求超时按策略最多重试一次。每次请求超时取配置超时、策略超时和剩余时间的最小值。截止时间在请求前后检查；同步请求不能据此保证第 120 秒被精确中止，墙钟硬截止仍未验证。

## 4. 返回结果怎样读

`invoke()` 返回字典：`status`、`output_issue`、`content`、`finish_reason`、`usage`、`elapsed_seconds`、本次 `attempts` 和共享 `statistics`。服务或预算故障抛出 `LLMCallError`，其记录可供后续运行日志保存。

| 情况 | 结果 |
|---|---|
| finish_reason 为 `stop`，非空文本，要求 JSON 时解析通过 | `success` |
| 空文本 | `invalid_output` / `empty_output` |
| finish_reason 为 `length`，即使残余文本可解析 | `invalid_output` / `truncated` |
| 要求 JSON 时解析失败或含非有限数值 | `invalid_output` / `invalid_json` |
| 非字符串文本或畸形响应 | `invalid_output` / `malformed_response` |
| 其他结束原因 | `invalid_output` / `unexpected_finish_reason` |
| 服务/配置故障 | 异常 status 为 `tool_error`，使用固定安全 code |
| 次数、修复数、重试数或截止时间耗尽 | 异常 status 为 `budget_exceeded` |

`success` 只说明适配层输出检查通过。`require_json=True` 不检查 `AnswerDraft` 字段，也不检查来源限定或事实支持；例如合法 JSON 数组仍须由 C 拒绝为不合契约的草稿。

usage 保留服务提供的非负整数，包括可用的缓存 token 细项。缺失 usage 不写 0；只要有一次尝试缺少实际 token 总量，共享 `total_tokens` 为 `null`，`known_total_tokens` 仅汇总已知部分。`attempts` 是本次调用，`statistics` 是整轮共享预算，汇总时不要重复相加共享统计。

## 5. 本次怎样验证

离线命令：

```powershell
Set-Location -LiteralPath 'D:\course\paper-research-assistant'
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_llm
$LASTEXITCODE
```

检查使用真实已安装 SDK 与 `httpx.MockTransport`，假配置与可控时钟；不加载 `.env`，不请求网络，不打开正式数据库。最终结果 34 项通过，0 失败、0 错误，59 次模拟 HTTP 发送。覆盖计数、共享预算、网络/鉴权故障、截止时间、usage 缺失、空响应、截断、JSON、脱敏、资源关闭与 D2 兼容性。报告绑定本次源码 SHA：见 [离线结果](/D:/course/paper-research-assistant/artifacts/d5/llm_boundary_validation.json)。开发中失败的历史记录保留，最终记录不替换旧失败。

真实连通命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.smoke_recorded_llm
$LASTEXITCODE
```

此命令会消费聊天额度；本次已经执行一次，无需为阅读指南重复运行。真实结果：HTTP 200、finish_reason `stop`、JSON 检查通过；输入 42、输出 14、合计 56 tokens；SDK/HTTP 尝试均 1，无重试、无修复，聊天调用约 1.25 秒。详见 [真实记录](/D:/course/paper-research-assistant/artifacts/d5/llm_smoke.json)。这份短输出不能证明 1200 tokens 足够覆盖完整论文答案，C/F 要用真实答案样本再核对。

## 6. docs 文件名与历史路径

现有九份文档已统一为“实施日 + 任务字母 + 内容”。总计划覆盖 A–G，用 `ABCDEFG`；跨任务目录入口用 `00`。新增本文直接使用 `d5-B-llm-guide.md`。

| 原文件名 | 当前文件名 / 对应任务 |
|---|---|
| `directory-guide.md` | `00-directory-guide.md`：目录入口 |
| `d4-plan.md` | `d4-ABCDEFG-plan.md`：D4 总计划 |
| `d4-storage-guide.md` | `d4-C-storage-guide.md`：SQLite |
| `d4-index-guide.md` | `d4-D-index-guide.md`：向量索引 |
| `d4-retrieval-guide.md` | `d4-E-retrieval-guide.md`：检索 |
| `d4-retrieval-review-guide.md` | `d4-F-retrieval-review-guide.md`：原文/PDF 复核 |
| `d4-completion-guide.md` | `d4-G-completion-guide.md`：验收交接 |
| `d5-plan.md` | `d5-ABCDEFG-plan.md`：D5 总计划 |
| `d5-contract-guide.md` | `d5-A-contract-guide.md`：接口与规则 |

README、当前 docs、课程日志和 D4 验收脚本的当前入口已同步。旧 JSON/验收记录里的路径与 SHA 仍表示当时状态，原始字节保存在 `archive/docs_pre_task_labels/`；通过 [重命名清单](/D:/course/paper-research-assistant/artifacts/d5/docs_rename_manifest.json) 回查。清单中的 `after_sha256` 是重命名时的快照，本次后续更新的文档 SHA 另存 B 汇总，不能用新 SHA 覆盖旧历史。

D4 G 指南逐字节不变；正式论文、chunks、SQLite、向量、题集与 D4 原验收结果保持原状。本次仅检查 D4 已记录测试的源码绑定，没有重新运行 D4 全量验收或覆盖旧报告。A 的 `baseline_config.json` 保留为 A 阶段快照，B 新配置另存。

下一步 C 按 rank、去重和正文字符预算选择候选，保存真正展示的证据快照；将消息交给此适配层，并用现有 `AnswerDraft` 解析草稿。D 再检查引用属于本轮展示范围并回查 SQLite。
