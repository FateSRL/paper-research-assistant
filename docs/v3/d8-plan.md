# D8 引用回查中的原 PDF 预览与定位

日期为 2026-11-07（Asia/Shanghai）。

状态为已规划。本文确定三段交付范围，细化第一段的实现与验收。执行提示词见文末。

## 1. 基线与目标

当前 Streamlit 页面在 Agent 回答下方提供「引用来源」。弹窗从回答的 `evidence_sources` 读取已保存的论文片段、PDF 文件页序和来源区域。引用校验已通过 `chunk_id` 回查论文及解析版本，并取得对应的本地 `pdf_absolute_path`。目前查看原版面需要用户按页序自行翻 PDF。 [页面引用入口](../../app.py) · [引用回查](../../paper_assistant/citations.py)

目标是沿现有引用入口打开已入库的原 PDF，自动定位并高亮对应的解析区域，最终让聊天和 PDF 可同时查看。参考 RAGFlow 的文件加载、页内滚动和区域高亮。三段共用一个 PDF 查看器，以现有引用来源作为选中文档与位置的依据。 [RAGFlow PDF 预览](/E:/project/ragflow/web/src/components/document-preview/pdf-preview.tsx:69) · [区域坐标转换](/E:/project/ragflow/web/src/utils/document-util.ts:24)

## 2. 三段交付范围

| 阶段 | 页面交付 | 主要工作量 |
|---|---|---|
| A 原 PDF 预览与按页定位 | 从「引用来源」打开引用对应的原 PDF，自动到达文件页序，并可连续翻阅 | 接入一个 PDF.js 查看器，打通原文件和引用页序的传递 |
| B 原版面区域高亮 | 在 A 的预览上叠加引用区域，滚到首个有效框，同一引用的其他框仍可查看 | 按各页的尺寸换算 `source_spans` 坐标，核对正文、表格和跨页引用。只有页序的来源使用按页定位 |
| C 右侧预览与引用切换 | 让聊天与原 PDF 同时可见，从现有引用卡片切换引用、页码和论文 | 将同一查看器接入右侧区域，处理打开、切换、关闭与对话状态 |

A 完成后即可使用原 PDF 和按页定位。B、C 分别在这一入口上增加区域定位和页面联动。

## 3. A 段固定输入与边界

范围为 Agent 自然语言回答的「引用来源」弹窗，预览对象来自该回答中通过引用校验的来源。阶段目标是文件页序定位和连续浏览。页序按 PDF 文件从 1 开始计数。

复用 D7 已保存的真实问答。由 [D7 执行结果](../../artifacts/v3/d7-qa-paired-new50-20261105/results.json) 按题号和 `mode=agent` 查找 `native_report`，使用报告中原始 `answer.citations` 和 `answer.evidence_sources`。下表中的块后缀用于核对引用身份，选择时以完整 `chunk_id` 为准。

| 题目 | 固定论文与解析版本 | 选择的引用与预期位置 |
|---|---|---|
| V50-018 `what are the state-of-the-art models?` | arXiv `1809.06537v1`，`local_81aacbe9528c4bbb81c48a24c837dd0c`，`r_e5096b3f4fa354e2` | 先打开正文来源 `_p6_c3`，预期 PDF 第 6 页。关闭后打开同一回答的 `_p8_c4`，预期同一份 PDF 第 8 页 |
| V50-050 `How do they analyze contextual similaries across datasets?` | arXiv `1801.02073v1`，`local_dd10ee7083024b03a5ad5a543348bd32`，`r_f97dfdd0edfc280c` | 打开表格来源 `_p2_c1`，预期对应论文 PDF 第 2 页和原表格版面 |

本段验收通过本地页面回放读取以上两份真实结果。规划时已核对两份报告的引用，所指的本地 PDF 文件均存在。模型、embedding、rerank 调用范围均为 0，评价对象是引用展示和 PDF 定位。

## 4. A 段实现顺序

1. **接通现有引用入口。** 在 `app.py` 的 Agent「引用来源」卡片中为每个有效来源加「在 PDF 中查看」。以现有 `key_prefix` 和完整 `chunk_id` 区分按钮，点击后取这条来源，打开一个共享 PDF 预览弹窗。保留原文卡片和页序说明。
2. **通过一个本地查看器读取原文件。** 在当前 Streamlit 里接入 PDF.js 小组件。可用已安装版本的 `streamlit.components.v1.declare_component` 加载本地构建产物。Python 侧沿用已校验的引用来源，按需读取对应 PDF 并通过组件通道传送文件数据、文档身份和目标页。前端用文件数据加载 PDF，Worker 与所需前端资源随组件本地提供。依赖版本和构建入口随组件记录。
3. **在查看器就绪后定位。** 打开时到 `pdf_page` 对应的文件页，并保留正常的滚动或翻页。随后打开同一文件的另一引用时，定位使用当前点击的目标页。缺少可用文件或有效页序时，在预览位置说明原因，原有片段仍可查阅。

改动集中在页面的引用预览入口和查看器组件。A 的预览容器使用弹窗，B 继续使用该查看器接入区域坐标，C 再调整其在聊天页的位置。

## 5. A 段验收

用临时本地回放把第 3 节报告交给正式的 `render_report` 页面路径，在真实浏览器点击新增按钮。用原生报告和已入库 PDF 验证如下行为，结果写入第 6 节。

| 检查 | 验收标准 |
|---|---|
| 打开与切页 | V50-018 第一次打开直接到第 6 页，能连续浏览相邻页。关掉后从另一条引用打开同一文件时直接到第 8 页 |
| 文件切换与版面 | V50-050 打开的是对应论文的原 PDF 第 2 页，显示原表格版面 |
| 来源不可预览 | 在临时回放副本中把 `pdf_absolute_path` 指向不存在的本地 PDF，页面仍显示引用文本和来源位置，预览给出可理解的提示 |
| 问答会话 | 点击、翻页和关闭后仍可查看同一份答案和已有引用。预览过程的新增问答、embedding、rerank 请求均为 0 |

先按现有启动方式验证组件可以加载，再核对上述实际页序。按 `AGENTS.md` 选取必要的现有验证，已有结果可复用。浏览器验收使用真实报告的回放输入。

## 6. A 段执行记录与产物

已完成。以下为实际执行记录。

#### 6.1 实际改动

- [app.py](../../app.py) 在 Agent 自然语言正文的「引用来源」来源卡片上新增「在 PDF 中查看」。按钮 key 为 `pdf_preview_<回答 key_prefix>_<完整 chunk_id>`，来源仍按本轮 `answer.citations` 的 chunk_id 从 `answer.evidence_sources` 取；fixed RAG 的 claim 路径不变。
- 新增共享预览弹窗 `_render_pdf_preview_dialog`，由一次按钮点击写入会话中的请求，再由页面末尾的 `_render_pdf_preview` 统一打开；不使用每条来源各自独立的预览实例。
- `_load_pdf_preview` 只读取来源的 `pdf_absolute_path`，要求位于 `data/papers`、扩展名为 `.pdf`，用 PyMuPDF 复核页数和目标页上界，再把文件字节以 base64 交给组件；不查询模型、索引或网络。缺失路径或页序越界时，弹窗给出提示，并展开保留的 `source.text`；原来源卡片和页序说明不被替换。
- 新增本地组件 [components/pdf_preview/index.html](../../components/pdf_preview/index.html)：A 段按宽度渲染全部页面、连续滚动、上一页／下一页、当前页与总页数；打开时在文档渲染完成后定位到目标页并加页边框。A 段只做按页定位；B 段在同一查看器增加区域框（见 §8.4），右侧联动仍属于 C。
- `CHAT_STYLE` 增加一条作用域样式：PDF 弹窗打开时隐藏仍处于展开状态的引用 popover，避免其浮层压在预览弹窗之上；关闭预览后引用弹窗需重新展开。

#### 6.2 组件依赖、构建与启动

- 组件产物目录为 `components/pdf_preview`，使用 **PDF.js 6.3.289 legacy build**（来自本机 `.venv-mineru` 的 MinerU PDF 预览 vendor），包含 `pdf.min.js`、`pdf.worker.min.js`、`cmaps/`、`standard_fonts/`、`wasm/` 和 `PDFJS-LICENSE`。
- 源文件是 `.mjs`；Python 的 `mimetypes` 会把 `.mjs` 报成 `text/plain`，因此复制为 `.js` 由 HTTP 以 JavaScript 提供。Worker 以 `type: "module"` 加载，组件内设置 `GlobalWorkerOptions.workerPort`，没有外部 CDN、远程 Worker 或 Node 构建步骤。
- 本次实际产物由本机 MinerU vendor 复制（重新生成时使用同一源目录）：

  ```powershell
  $pdfjs = ".venv-mineru\Lib\site-packages\mineru\resources\pdf_preview\vendor\pdfjs"
  Copy-Item "$pdfjs\legacy\build\pdf.min.mjs" "components\pdf_preview\pdf.min.js"
  Copy-Item "$pdfjs\legacy\build\pdf.worker.min.mjs" "components\pdf_preview\pdf.worker.min.js"
  Copy-Item "$pdfjs\cmaps" "components\pdf_preview\cmaps" -Recurse
  Copy-Item "$pdfjs\standard_fonts" "components\pdf_preview\standard_fonts" -Recurse
  Copy-Item "$pdfjs\wasm" "components\pdf_preview\wasm" -Recurse
  Copy-Item "$pdfjs\LICENSE" "components\pdf_preview\PDFJS-LICENSE"
  ```
- 实际启动页面：

  ```powershell
  .\.venv\Scripts\python.exe -m streamlit run app.py `
    --server.address 127.0.0.1 --server.port 8501 --server.headless true
  ```

- 本次浏览器验收的临时回放（不调用问答）：

  ```powershell
  .\.venv\Scripts\python.exe -m streamlit run `
    artifacts/v3/d8-a-pdf-preview-20261107/replay_app.py `
    --server.address 127.0.0.1 --server.port 8511 --server.headless true `
    --server.fileWatcherType none --browser.gatherUsageStats false
  ```

- 回放输入来自 D7 原生报告：V50-018 `native_reports/V50-018_agent_20261105_073512_034561_77242c590359.json`、V50-050 `native_reports/V50-050_agent_20261105_075438_772415_628d3939a867.json`；回放副本另存 `replay_V50-050-missing.json`，其中 `pdf_absolute_path` 指向不存在的 `data/papers/does-not-exist-d8.pdf`。

正式 `app.py` 另在 8512 端口启动，真实浏览器加载论文选择与对话页无页面异常；预览按钮只在带真实报告的回放中点击验证。

#### 6.3 实际页序与页面表现

用 Playwright 驱动本机 Chrome，打开临时回放并通过真实的引用来源按钮点击；页面截图保存在同一产物目录。

| 来源 | 固定论文/解析版本 | 预期 | 实际 |
|---|---|---|---|
| V50-018 `_p6_c3` | `local_81aacbe9528c4bbb81c48a24c837dd0c` / `r_e5096b3f4fa354e2`，PDF 共 10 页 | 第 6 页 | 第 **6 / 10** 页，10 个画布已渲染，滚动位置 7021 |
| V50-018 `_p8_c4` | 同一文件 | 第 8 页 | 关闭后重新展开引用并点开，第 **8 / 10** 页，滚动位置 9827 |
| V50-050 `_p2_c1` | `local_dd10ee7083024b03a5ad5a543348bd32` / `r_f97dfdd0edfc280c`，PDF 共 5 页 | 第 2 页及表格 | 第 **2 / 5** 页，5 个画布，原 Table 1 版面可见，滚动位置 1409 |

截图：[V50-018 第 6 页](../../artifacts/v3/d8-a-pdf-preview-20261107/final-v50-018-p6.png)、[V50-018 第 8 页](../../artifacts/v3/d8-a-pdf-preview-20261107/final-v50-018-p8.png)、[V50-050 第 2 页](../../artifacts/v3/d8-a-pdf-preview-20261107/final-v50-050-p2.png)、[缺文件副本](../../artifacts/v3/d8-a-pdf-preview-20261107/final-missing2.png)。

- 连续浏览：在 V50-018 第 6 页点「下一页」到第 7 / 10 页（滚动 8432），再点「上一页」回第 6 / 10 页（滚动 7029）；所有页面在同一滚动容器中。
- 关闭弹窗后，V50-018 和 V50-050 的原回答正文及引用来源仍在页面中；再次展开引用即可切换来源。弹出预览时引用 popover 被临时隐藏，关闭后不会自动保持展开。
- 缺文件副本：点击 `_p2_c1` 后弹窗显示「来源 PDF 文件不存在：does-not-exist-d8.pdf」，没有 iframe/画布；弹窗同时展开引用原文，首行为 `Table 1: Comparisons between the four corpora...`，chunk_id 和页序 `2` 仍显示。原来源卡片未被删除。
- 页序不可用时：`pdf_page` 非正整数在来源卡片直接提示且不显示按钮；页序大于实际页数时弹窗走缺省提示与原文展开分支，不加载 PDF。

#### 6.4 请求数与验证边界

- 回放页面只读取本地 JSON/PDF；浏览器请求主机只有 `127.0.0.1:8511`，Worker 请求为本地 `/component/app.pdf_preview/pdf.worker.min.js`（3 次，对应 3 次预览打开）。
- **Chat / query embedding / rerank 调用均为 0**；没有新的问答提交、没有模型请求，也没有写入运行记录。
- 组件打开完成后的控制台无 `componentReady`/页面异常警告；组件高度在 `componentReady` 之后设置。
- A 段只验证原文件加载和按页定位；区域高亮已在 B 段完成（见 §8.4），右侧联动仍属于 C。B 不做区域坐标换算之外的页面布局调整。

#### 6.5 尚有限制

- 组件一次性渲染全部页面，没有按页懒加载或虚拟滚动；本批 10 页/5 页正常，超长 PDF 首次打开会更慢。
- 只提供适应宽度的连续滚动与上一页/下一页，没有缩放、全文搜索、文本选择或目录跳转。
- 只接受 `data/papers` 下已存在的本地 PDF；不提供远程 URL 预览。路径失效或页序越界时以提示和原文摘录降级，不显示伪造页面。
- PDF 弹窗会临时隐藏展开中的引用 popover；关闭弹窗后需重新展开引用来源，未做自动恢复。

## 7. 给 DeepSeek 的 A 段执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 docs/v3/d8-plan.md，只实施 A 段「原 PDF 预览与按页定位」，以第 5 节为验收边界，最后回填第 6 节。

先读 app.py 的 render_report 和 _show_source，及 paper_assistant/citations.py 的引用来源字段。当前 Agent 正文的「引用来源」弹窗已保存 answer.citations 和 answer.evidence_sources。在每条可预览来源上加「在 PDF 中查看」，以本轮实际引用的 chunk_id 取来源，在一个共享弹窗中展示原 PDF。使用已校验的本地 PDF 文件和 pdf_page，页序从 1 开始。按钮身份按回答 key_prefix 和 chunk_id 区分。

按 D8 第 4 节用一个 Streamlit PDF.js 查看器实现。可参考 E:/project/ragflow/web/src/components/document-preview/pdf-preview.tsx 的原文件加载与定位。使用本地组件产物和 Worker，文档就绪后定位到目标页，支持连续浏览。同一文件再打开另一引用时使用新页序。来源文件或页序不可用时，保留原文展示并给出提示。区域框高亮属于 B 段，右侧联动属于 C 段。

用 artifacts/v3/d7-qa-paired-new50-20261105/results.json 定位 V50-018 和 V50-050 的 Agent native_report，按 D8 第 3 节核对固定论文和解析版本。通过临时回放把原生报告交给正式页面渲染，在浏览器实际点开 V50-018 的 _p6_c3 和 _p8_c4，核对同一文件第 6、8 页与连续浏览。再点 V50-050 的 _p2_c1，核对另一份原 PDF 第 2 页和原表格版面。在回放副本将 pdf_absolute_path 指向不存在的本地 PDF，确认仍能看到引用文字和预览提示。回放过程的模型、embedding、rerank 调用均为 0。

按 AGENTS.md 做必要验证。将实际改动、构建与启动方法、实际页序和异常表现写入 D8 第 6 节。A 段验收完成即交付。
```

## 8. B 段原版面区域高亮规划（2026-11-07）

### 8.1 基线与交付范围

A 段已经从「引用来源」打开原 PDF 并跳到对应页。B 段沿用同一个弹窗和 PDF.js 查看器，将当前选中引用的 `source_spans` 画到原版面上。打开时滚到该页最靠上的有效框，用户可以继续滚动和翻页。整页蓝框仍表示当前页，引用区域用独立的半透明框表示。右侧联动属于 C 段。 [A 段实测](#63-实际页序与页面表现) · [当前查看器](../../components/pdf_preview/index.html)

### 8.2 实现与坐标口径

1. 在 `app.py` 的 `_render_pdf_preview_dialog` 把当前来源已有的 `source_spans` 传给 PDF 组件。沿用现有引用选择、本地文件读取和页序核对。预览所用的框随当前 `chunk_id` 选取。
2. 在 `components/pdf_preview/index.html` 的页面包装层上叠加区域框。当前 MinerU 结构来源的 `bbox` 是左上角为原点的归一化 `[x0, y0, x1, y1]`。用画布实际显示区域的百分比定位，框的宽高分别取 `x1-x0` 和 `y1-y0`。结构子块的来源页与 `pdf_page` 一致。只使用选中页上四个有限数值、范围在 0–1 且有正宽高的归一化框。表格的多行可能共用同一框，相同页和坐标只绘制一次。 [来源坐标](../../paper_assistant/mineru_parser.py) · [页内来源约束](../../paper_assistant/storage.py)
3. 等待选中页的画布和覆盖层完成布局，再在预览滚动容器内定位到最靠上的有效框。后续翻页沿用 A 的行为。重新打开另一条引用时，随现有页面重绘替换区域框。无可用框的来源继续按 `pdf_page` 定位。只有旧 `segment_bbox` 的记录也使用按页定位，该字段表示父段区域。 [旧分块坐标定义](../../paper_assistant/chunking.py)

V50-050 的来源记录先列出表题，后列出表体。按页面上方的位置定位，可以先看到表体，同时保留表题的高亮。

### 8.3 固定输入与浏览器验收

沿用第 3 节的论文版本、解析版本和 D7 两份 Agent 原生报告，复用 A 段 `render_report` 回放入口。下面的框数已经从原生 `evidence_sources` 核对，按页和坐标去重。 [A 段回放入口](../../artifacts/v3/d8-a-pdf-preview-20261107/replay_app.py)

| 固定来源 | 实际验证动作 | 通过标准 |
|---|---|---|
| V50-018 `_p6_c3` | 打开第 6 页，随后翻到第 7 页再返回 | 4 个框落在第 6 页右栏的基线正文上，打开时首框在视野内。第 7 页无该引用的框，返回后原框仍可见 |
| V50-018 `_p8_c4` | 关闭第 6 页预览，打开同一回答的另一条引用 | 跳到第 8 页的对应正文位置，绘制该来源的 4 个框，第 6 页的旧引用框已清除 |
| V50-050 `_p2_c1` | 打开另一份论文的第 2 页 | 6 条来源坐标去重后绘制 2 个框，分别对齐 Table 1 表体和表题。打开时先定位到表体 |
| V50-050 `_p2_c1` 的临时回放副本 | 仅将这一来源的 `source_spans` 清空 | 仍打开同一 PDF 第 2 页，原版面和引用文字可看，页面无区域框 |

在浏览器核对实际滚动落点与原版面的对齐情况，同时检查页码和框数。A 的缺文件验证可在文件读取路径未改的情况下复用。B 仅使用已保存的真实问答结果回放，新增模型、embedding 和 rerank 调用范围均为 0。

### 8.4 B 段执行记录

已完成。B 段改动集中在现有预览入口和查看器，没有新增右侧联动或独立预览实例。

#### 8.4.1 实际改动

- [app.py](../../app.py) 的 `_render_pdf_preview_dialog` 把当前来源的 `source_spans` 传给现有组件；按钮、共享弹窗、本地 PDF 读取和 `pdf_page` 校验沿用 A。
- [components/pdf_preview/index.html](../../components/pdf_preview/index.html) 增加逐页覆盖层：只接受 `pdf_page` 等于当前来源页、`coordinate_system` 为 `normalized`（缺省也按归一化处理）、四个有限数值且 `0 <= x0 < x1 <= 1`、`0 <= y0 < y1 <= 1` 的 bbox；按同一页的 bbox 去重。框用百分比定位在页面包装层（与画布显示区域同尺寸），落在原版面上。
- 画布和覆盖层布局完成后，预览滚动容器定位到该页 `y0` 最小的有效框；没有有效框时按 A 的原 `pdf_page` 定位。`segment_bbox` 不参与 B 的框绘制，旧记录仍按页打开。
- 翻页沿用 A 的上一页/下一页与当前页状态；切换引用时随共享弹窗重绘替换框，旧页框不会带到新页。页面顶部显示「引用区域 N」，翻到非目标页时目标页框隐藏，返回后恢复。
- 本次未改 PDF.js 资源、Worker、启动方式或 A 的缺文件降级路径。

#### 8.4.2 浏览器验证

用 D7 V50-018、V50-050 的 Agent 原生报告，经 A 的 `replay_app.py` 调用正式 `render_report`；Chrome 实际点击并检查画布上的框位置和滚动，不只看 DOM 数。

| 来源 | 实际结果 |
|---|---|
| V50-018 `_p6_c3` | 第 **6 / 10** 页，绘制 **4** 个框；归一化范围约 x 0.507–0.887、y 0.127–0.584，全部落在右栏正文。打开后滚动 7196，首框顶部约 55.7 px，进入视野。 |
| V50-018 翻到第 7 页再返回 | 第 7 / 10 页时 4 个目标框均不可见；返回第 6 / 10 页后 4 个框恢复，滚动 7029。 |
| V50-018 `_p8_c4` | 跳到第 **8 / 10** 页，绘制 **4** 个框，范围约 x 0.114–0.887、y 0.522–0.895；首框顶部约 56.0 px，滚动 10550。第 6 页旧框未保留。 |
| V50-050 `_p2_c1` | 第 **2 / 5** 页，6 条来源坐标去重后绘制 **2** 个框：上方 x 0.122–0.881、y 0.070–0.170 对齐 Table 1 表体，下方 x 0.114–0.886、y 0.179–0.244 对齐表题。打开后滚动 1504，表体框顶部约 56.4 px，表体和表题同时可见。 |
| V50-050 `_p2_c1` 无 `source_spans` 副本 | 仍打开第 **2 / 5** 页，**0** 个区域框，滚动 1409；原表格版面和引用文字入口保留。副本同时设置了旧 `segment_bbox`，确认不据此画框。 |

截图：[V50-018 第 6 页](../../artifacts/v3/d8-a-pdf-preview-20261107/b-v50-018-p6.png)、[V50-018 第 8 页](../../artifacts/v3/d8-a-pdf-preview-20261107/b-v50-018-p8.png)、[V50-050 第 2 页](../../artifacts/v3/d8-a-pdf-preview-20261107/b-v50-050-p2.png)、[无 source_spans 副本](../../artifacts/v3/d8-a-pdf-preview-20261107/b-v50-050-nospans.png)。

#### 8.4.3 请求与边界

- 回放请求主机只有 `127.0.0.1:8511`，PDF.js Worker 仍为本地产物；新增 Chat、query embedding、rerank 请求均为 **0**，没有新的问答提交。
- 沿用 A 的 PDF.js 6.3.289、`components/pdf_preview` 和启动命令；没有新增前端依赖或构建步骤。
- B 的交付止于现有预览弹窗。右侧联动属于 C，未实现；区域框仅处理归一化坐标，非归一化旧坐标不做换算。

## 9. 给 DeepSeek 的 B 段执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 docs/v3/d8-plan.md 第 8 节，只实现 B 段「原版面区域高亮」，完成后回填第 8.4 节。

复用 app.py 的 _render_pdf_preview_dialog 和 components/pdf_preview/index.html。由现有「在 PDF 中查看」入口把当前引用的 source_spans 传给现有查看器。按选中页、归一化坐标和有效矩形范围取框。bbox 是左上角原点的 [x0, y0, x1, y1]。覆盖层相对画布的实际显示区域定位，同一页相同 bbox 只画一次。画布和覆盖层完成布局后，在查看器内部滚到该页最靠上的有效框。翻页继续使用 A 的逻辑，切换引用随现有重绘更新框。无可用 source_spans 时按原 pdf_page 打开，旧 segment_bbox 按页处理。B 的交付止于现有弹窗，右侧联动属于 C 段。

使用 D8 第 3 节固定的 D7 两份 Agent 原生报告，沿用 A 的本地回放和正式 render_report 渲染路径。在浏览器打开 V50-018 的 _p6_c3，确认第 6 页右栏 4 个框对齐正文，首框进入视野，翻到第 7 页再回第 6 页。再打开同一回答的 _p8_c4，确认跳到第 8 页的对应区域并显示该来源的 4 个框。打开 V50-050 的 _p2_c1，确认第 2 页有 2 个框对齐 Table 1 表体和表题，首屏定位到表体。最后在临时回放副本中清空这一来源的 source_spans，确认仍跳到第 2 页并保留原文入口。验收看实际画布上的位置和滚动，不只数 DOM 元素。

使用已有本地 PDF.js 资源和启动方式。回放新增模型、embedding、rerank 请求均为 0。按 AGENTS.md 复用仍有效的 A 段验证，把本段实际改动和浏览器结果简要写入 D8 第 8.4 节，完成 B 段即交付。
```

## 10. C 段右侧预览与引用切换规划（2026-11-07）

### 10.1 B 段验收与 C 段目标

核对 B 段浏览器记录和正文、表格截图后，可以进入 C 段。V50-018 的第 6、8 页各有 4 个对应区域框，V50-050 的第 2 页分别高亮 Table 1 表体与表题。已有回放覆盖跳到首个框、翻页返回、切换引用和缺坐标时按页定位。 [B 段实测](#842-浏览器验证)

C 将同一个 PDF 查看器从弹窗移到聊天页右侧。打开后，左侧的回答、引用入口和提问框可继续使用。点另一条引用会更新同一右侧预览，包括同一论文换页和换一篇论文。关闭预览回到单列聊天。

### 10.2 实现顺序

1. **把预览接到正常聊天布局。** 在 `app.py` 的 `main()` 中，用当前引用选择决定页面布局。打开时采用 Streamlit 宽屏和双列，左列保留原对话渲染和提问入口，右列展示原 PDF 和「关闭预览」。把现有 `.stMainBlockContainer` 的 `850px` 限宽用于单列模式，让双列使用可用宽度。长回答在左列可滚动，PDF 使用已有滚动容器。引用入口沿用回答下方「引用来源」中的「在 PDF 中查看」，页面提示与入口对应。
2. **复用现有预览和引用状态。** 将当前弹窗中的文件读取、页序、降级提示和组件参数用于右列。点击引用沿用现有 `pdf_preview_request`，以请求 token 区分新选中的引用，页面只挂载一个预览。移除弹窗的一次性打开控制及其遮挡样式。同一选中来源继续使用同一个组件身份，新引用更新文件、页序和 `source_spans`，沿用 B 的自动跳转和高亮。
3. **把关闭和会话切换接到既有入口。** 点击「关闭预览」时清空当前预览请求并恢复单列，保留已显示的回答。通过现有「新对话」、历史对话选择或论文选择切换会话时，同步清空当前预览。左列沿用同一个聊天输入和 `_queue_submission` 回调。

### 10.3 固定输入与浏览器验收

复用第 3 节两份 D7 Agent 原生报告及对应 PDF。C 的临时回放将这两份报告放进同一个页面测试会话，该会话选择两份报告绑定的论文版本。将已有报告按正式会话状态放入 `SUBMISSIONS_KEY`，设置所选版本和当前会话，调用正式 `app.main()`。这样验收覆盖实际双列布局和会话切换。报告正文、引用及 PDF 使用既有记录。

| 检查 | 浏览器操作与通过标准 |
|---|---|
| 打开并同屏查看 | 从左列点 V50-018 `_p6_c3`。桌面浏览器同时显示左侧回答、可用提问框和右侧原 PDF。右侧跳到第 6 页正文位置，4 个框在较窄视口仍对齐原文 |
| 在右侧连续切换 | 保持预览打开，从左列点 V50-018 `_p8_c4`，再点 V50-050 `_p2_c1`。同一右侧位置依次显示原论文第 8 页 4 个框和另一份论文第 2 页 2 个表格框。确认文件标题、页序和实际画布匹配，且只有一个预览组件 |
| 关闭和切换会话 | 点击右侧关闭，回到单列并能查看原有两份回答。重新打开后点「新对话」，再从历史回到回放会话，确认旧预览已清空，原回答可重新打开对应引用 |

页面回放使用桌面 Chrome 和原有 Streamlit 启动方式。只检查提问框可用状态，所有预览交互新增的模型、embedding 和 rerank 调用均为 0。文件读取与坐标逻辑沿用仍有效的 A、B 验证，C 重点核对双列中的位置和状态。

### 10.4 C 段执行记录

已完成。C 段把 A/B 使用的同一个 PDF 查看器接到聊天页右列，主页面不再通过 PDF 弹窗打开预览。

#### 10.4.1 实际改动

- [app.py](../../app.py) 的 `main()` 在存在有效 `pdf_preview_request` 时使用 Streamlit `layout="wide"`，并在宽屏样式下解除 `.stMainBlockContainer` 的 850px 限宽；无预览时回到 `centered` 和 850px 单列。
- 宽屏使用左右两列（约 1:1.25）。左列保留原 `render_chat()`：品牌、同一个 `st.chat_input`、回答、引用来源和下载；右列 `_render_pdf_preview_pane` 显示原 PDF 和「关闭预览」。右列设为 `position: sticky`，左列提问框也吸附在顶部，滚动长回答时仍与 PDF 同屏。
- 右侧组件使用固定 key `pdf_preview_pane`，因此同一右侧位置随 `pdf_preview_request` 的 token 更新文件、页序和 `source_spans`，不会为每次引用挂载新的预览实例。读取本地文件、页序校验、归一化区域框和自动定位沿用 A/B。
- 关闭按钮清空 `pdf_preview_request` 并回到单列；旧回答保留。`_new_conversation`、`_select_conversation` 以及论文选择触发的 `_ensure_conversation` 都调用 `_clear_pdf_preview`。
- 主页面移除了 PDF 弹窗的触发和遮挡样式。引用来源 popover 的 key 包含当前预览 token：点击「在 PDF 中查看」后，右侧打开会触发重绘，原 popover 关闭，不再遮住聊天或 PDF。A/B 的临时回放入口仍保留旧弹窗函数用于历史复现，但正式 `main()` 不再调用它。
- 没有新增前端依赖；PDF.js 6.3.289、本地 Worker 和 `components/pdf_preview` 未改。

#### 10.4.2 正式 main() 回放与浏览器结果

回放入口 [replay_c.py](../../artifacts/v3/d8-a-pdf-preview-20261107/replay_c.py) 将 V50-018、V50-050 两份 D7 Agent 报告放入同一个 `SUBMISSIONS_KEY` 会话，设置两篇固定论文版本和当前会话后调用正式 `app.main()`，监听 `127.0.0.1:8513`。桌面 Chrome 在 1500×1000 视口操作。

| 操作 | 实际结果 |
|---|---|
| 从 V50-018 `_p6_c3` 打开 | 左侧回答、提问框和右侧 PDF 同屏；右侧第 **6 / 10** 页，4 个区域框对齐第 6 页右栏；主内容宽约 1200px，右列约 599px。 |
| 右侧切到 V50-018 `_p8_c4` | 同一右侧位置、同一个 iframe 更新为第 **8 / 10** 页和 4 个框；文件标题仍为 V50-018，左列输入框仍在视口内。 |
| 右侧切到 V50-050 `_p2_c1` | 同一 iframe 更新为另一篇论文，第 **2 / 5** 页、2 个表格框；文件标题和页序同步更新，只有一个 iframe。 |
| 点击「关闭预览」 | iframe 和关闭按钮消失，主内容恢复 850px 单列；原回答仍在，提问框保留。 |
| 重新打开后点「新对话」 | 右侧预览清空、iframe 0；新会话不显示旧回答；主内容 850px。 |
| 从历史对话回到回放会话 | 旧预览仍为空（iframe 0、关闭按钮 0），两份回答恢复；再点引用可重新打开右侧预览。 |
| 取消一篇已选论文 | 触发新会话并清空预览（iframe 0、850px 单列），确认论文选择切换也走清理路径。 |

截图：[打开 p6](../../artifacts/v3/d8-a-pdf-preview-20261107/c-final-p6.png)、[切换 p8](../../artifacts/v3/d8-a-pdf-preview-20261107/c-final-p8.png)、[切换 p2](../../artifacts/v3/d8-a-pdf-preview-20261107/c-final-p2.png)、[关闭后单列](../../artifacts/v3/d8-a-pdf-preview-20261107/c-closed.png)。

#### 10.4.3 请求与边界

- 回放新增 Chat、query embedding、rerank 请求均为 **0**；页面只读取本地报告和 PDF，PDF.js Worker 请求仍为本地 `/component/app.pdf_preview/pdf.worker.min.js`。
- C 的交付止于现有聊天页右列；没有新增独立路由或第三方预览依赖，A/B 的文件读取、页序和区域框逻辑复用。
- 右列和提问框使用 sticky 定位，极大或极长的单页 PDF 仍由 A 的整页渲染方式承担；未新增按页虚拟化。

## 11. 给 DeepSeek 的 C 段执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 docs/v3/d8-plan.md 第 10 节，只实施 C 段「右侧预览与引用切换」，完成后回填第 10.4 节。

基于当前 app.py 的 main、render_report、pdf_preview_request、_load_pdf_preview 与会话切换入口，把 A/B 的同一个 PDF 查看器接到右列。预览打开时用 Streamlit 宽屏和双列，解除双列下的 850px 主内容限宽。左列保留现有聊天、引用来源和同一个提问框，右列显示原 PDF 与关闭按钮。继续通过「在 PDF 中查看」选择来源。用现有预览请求 token 更新同一个右侧位置，沿用本地文件和区域坐标的渲染路径。关预览回单列。新对话、历史对话或选定论文切换会话时清空当前预览。用右列取代 PDF 弹窗的触发和遮挡样式。

按第 3 节取 V50-018 和 V50-050 两份 D7 Agent 原生报告及固定论文版本。用临时回放把两份真实回答放进同一个选择这两篇论文的页面测试会话，调用正式 app.main()，以验证实际布局。浏览器从左侧依次打开 V50-018 的 _p6_c3、_p8_c4 和 V50-050 的 _p2_c1，按第 10.3 节检查左侧聊天和输入框与右侧 PDF 同屏，右侧依次正确显示 6、8、2 页，区域框数量依次为 4、4、2，并核对实际对齐位置。验证关闭后原回答还在，新对话和返回历史时旧预览已清空。整个回放新增模型、embedding、rerank 调用均为 0。

沿用已有本地 PDF.js 组件资源和正常启动方式。按 AGENTS.md 复用 A、B 已通过且仍有效的验证，把实际改动与本轮浏览器结果写入第 10.4 节。C 段验收完成即交付。
```

## 12. D 段行内引用徽标与悬停卡片规划（2026-11-07）

### 12.1 基线与交付范围

C 段已能从「引用来源」打开右侧 PDF、定位并高亮。当前正文把 `[ID:n]` 渲染成普通 `[n]`，读者需要到回答下方找对应来源。D 段借鉴 RAGFlow 的行内徽标和悬停卡片，用现有右侧预览承接打开 PDF 的动作。 [C 段实测](#1042-正式-main-回放与浏览器结果) · [RAGFlow 行内引用](/E:/project/ragflow/web/src/components/next-markdown-content/index.tsx:397) · [RAGFlow 原文卡片](/E:/project/ragflow/web/src/components/next-markdown-content/index.tsx:355)

范围为 Agent 自然语言回答。已校验的引用在原位置显示为有浅色底、深色文字和圆角的数字徽标。悬停显示论文标题、PDF 文件页序和原文片段，鼠标可移入卡片并点击「在 PDF 中查看」。悬停由浏览器处理，点击 PDF 按钮才更新右侧预览。「引用来源」继续提供完整来源列表。

### 12.2 实现顺序

1. **按回答渲染徽标。** 在 `app.py` 的 `render_report` 中，用 `answer.citations` 的 `ref` 和 `chunk_id` 找到对应 `answer.evidence_sources`。只把能解析到来源的 `[ID:n]` 生成为带回答作用域的 Markdown 锚点，沿用原 `ref` 显示并与来源列表同号。同一回答的重复引用指向同一来源，普通 `[n]` 仍按正文渲染。原来的 `st.markdown` 继续负责段落、列表、表格与公式。
2. **在现有 Streamlit 页面接入卡片。** 使用当前 Streamlit 1.65 已有的 `st.components.v2` 注册一个小型交互组件，给本条回答生成的引用锚点加徽标样式和悬停事件。卡片从该回答已保存的来源读取标题、页序和原文，以文本展示，长片段可在卡片内滚动。悬停在浏览器内完成，卡片打开时可将鼠标移到按钮上操作。
3. **接通现有右侧预览。** 组件只在点击「在 PDF 中查看」时传回所选 `ref`，由该回答作用域内的 Python 回调查到已保存的来源，调用 `_request_pdf_preview`。按钮可用性沿用 `_pdf_preview_issue`。右侧查看器使用 C 段现有入口和坐标。将侧栏和欢迎区的提示改为悬停引用看原文、点击卡片按钮打开原 PDF。

### 12.3 固定输入与浏览器验收

复用第 3 节固定版本的 D7 Agent 报告 V50-018、V50-050，以及 C 段调用正式 `app.main()` 的同会话回放。编号和 `chunk_id` 已按两份原生报告核对。 [C 段回放入口](../../artifacts/v3/d8-a-pdf-preview-20261107/replay_c.py)

| 检查 | 浏览器操作与通过标准 |
|---|---|
| 徽标与普通编号 | V50-018 的 `[ID:8]` 在正文中重复出现，徽标均显示同一个编号，悬停均指向 `_p6_c3`、第 6 页右栏基线正文。在临时报告副本末尾追加普通书目编号 `[8]`，确认普通编号仍是正文 |
| 按回答区分来源 | 依次悬停 V50-018 和 V50-050 的 `[2]`。前者显示 V50-018 的 `_p8_c4`、第 8 页，后者显示 V50-050 的 `_p1_c3`、第 1 页。核对两张卡片的标题、页序和原文来自对应报告 |
| 原文卡片与右侧联动 | 从 V50-018 的 `[8]` 移入卡片，点击「在 PDF 中查看」，右侧打开第 6 页并显示 4 个框。右侧打开时悬停 V50-050 的 `[5]`，仍停在原预览。点击卡片按钮后，右侧更新到 `_p2_c1`、第 2 页和 Table 1 的 2 个框 |

浏览器使用正常聊天布局，核对徽标在列表与段落中的实际可辨识度，并确认卡片点击和原「引用来源」入口都可使用。沿用 C 段的布局与会话验证，D 段只回放已保存的回答，新增模型、embedding 和 rerank 调用范围均为 0。

### 12.4 D 段执行记录

已完成。D 段在正式 `render_report` 的正文中增加行内引用徽标和浏览器内悬停卡片，点击卡片按钮沿用 C 的右侧预览。

#### 12.4.1 实际改动

- [app.py](../../app.py) 的 `render_report` 不再把正文直接改成普通 `[n]`：`_inline_ref_links` 用当前回答的 `answer.citations` 建立 `ref -> evidence_sources`，只把本轮有来源的 `[ID:n]` 改为带回答作用域的 Markdown 锚点，徽标文字仍为原 `ref` 的 `[n]`；没有对应来源的 `[ID:n]` 和普通 `[n]` 保持正文文字。
- 每个回答挂载一个 `st.components.v2` 小组件 [components/inline_refs.js](../../components/inline_refs.js) + [inline_refs.css](../../components/inline_refs.css)。组件按回答的 `scope` 找到锚点，加浅色圆角徽标；悬停/聚焦时在 `document.body` 显示固定卡片，展示论文标题、PDF 文件页序和保存的 `source.text`，可从徽标移入卡片。
- 卡片中的「在 PDF 中查看」把 `{ref, nonce}` 通过 `setTriggerValue` 传回 Python；`_mount_inline_refs` 由该回答的来源表取得真实来源，校验非重复 nonce 后调用现有 `_request_pdf_preview`。按钮可用性沿用 `_pdf_preview_issue`，无可用文件/页序时按钮禁用。
- 悬停仅由浏览器组件处理，不触发 Python/模型；原「引用来源」popover、来源列表和其中的「在 PDF 中查看」入口保留。侧栏和欢迎页提示已改为“悬停正文引用看原文，点击卡片按钮打开原 PDF”。
- 组件以当前预览 token 作为挂载 key 的一部分，布局从单列切到双列后重新挂载，避免旧卡片的 DOM 闭包失效。没有改 PDF.js、A/B 区域框或 C 的右侧布局逻辑。

#### 12.4.2 浏览器结果

使用 C 的 `replay_c.py` 调用正式 `app.main()`；正常会话含 V50-018、V50-050 两份 D7 报告。Chrome 1500×1000。

| 检查 | 实际结果 |
|---|---|
| V50-018 重复 `[8]` | 正文共 10 个 V50-018 徽标，其中 `[8]` 4 处，均指向同一 `#d8-ref-d8-c-v50-018-8`；悬停卡片标题为 V50-018，PDF 文件页序 **6**，原文来自 `_p6_c3`。 |
| 普通书目 `[8]` | 临时报告副本末尾追加 `参考文献 [8]`；V50-018 的 `[8]` 徽标仍为 4 个，普通 `[8]` 无锚点/卡片，正文可读。 |
| V50-018 `[2]` | 卡片显示 V50-018，PDF 文件页序 **8**，原文来自 `_p8_c4`。 |
| V50-050 `[2]` | 卡片显示 V50-050，PDF 文件页序 **1**，原文来自 `_p1_c3`；与 V50-018 的 `[2]` 不串来源。 |
| V50-018 `[8]` 卡片按钮 | 点击后右侧打开第 **6 / 10** 页，4 个区域框；左侧回答和徽标仍在。 |
| V50-050 `[5]` 悬停 | 卡片显示 V50-050、PDF 文件页序 **2**、Table 1 原文；悬停期间右侧仍是此前的 V50-018 第 6 页。 |
| V50-050 `[5]` 卡片按钮 | 点击后右侧更新为 V50-050 第 **2 / 5** 页、**2** 个 Table 1 区域框。 |
| 旧来源列表 | 展开原「引用来源」仍显示来源正文，底部「在 PDF 中查看」按钮仍可用（V50-018 列表 6 个来源）。 |

截图：[V50-018 [8] 悬停卡片](../../artifacts/v3/d8-a-pdf-preview-20261107/d-hover-8.png)、[V50-018 [2] 卡片](../../artifacts/v3/d8-a-pdf-preview-20261107/d-hover-018-2.png)、[V50-050 [2] 卡片](../../artifacts/v3/d8-a-pdf-preview-20261107/d-hover-050-2.png)、[V50-018 [8] 打开右侧](../../artifacts/v3/d8-a-pdf-preview-20261107/d-click-8.png)、[V50-050 [5] 悬停时右侧保持](../../artifacts/v3/d8-a-pdf-preview-20261107/d-hover-050-5b.png)、[V50-050 [5] 打开右侧](../../artifacts/v3/d8-a-pdf-preview-20261107/d-click-050-5b.png)、[普通 [8] 副本](../../artifacts/v3/d8-a-pdf-preview-20261107/d-plain8.png)。

#### 12.4.3 请求与边界

- 回放新增 Chat、query embedding、rerank 请求均为 **0**；组件只操作本页 DOM，点击按钮也只调用现有本地预览请求。
- 徽标只作用于可解析到 `evidence_sources` 的 `[ID:n]`；同一回答重复编号共享同一来源，跨回答按 `scope` 隔离。
- D 段交付止于现有聊天页和右侧预览；原「引用来源」列表保留，不新增独立引用详情路由。

## 13. 给 DeepSeek 的 D 段执行提示词

```text
在 D:/course/paper-research-assistant 工作，遵守 AGENTS.md。读取 docs/v3/d8-plan.md 第 12 节，只实施 D 段「行内引用徽标与悬停卡片」，完成后回填第 12.4 节。

参考 E:/project/ragflow/web/src/components/next-markdown-content/index.tsx 的行内徽标、悬停原文和文件点击交互。适配现有 Streamlit 的 render_report，继续用 st.markdown 展示回答。用 answer.citations 的 ref、chunk_id 对应 answer.evidence_sources，只给本轮能查到来源的 [ID:n] 生成带回答作用域的引用锚点。徽标沿用原 ref 并与下方「引用来源」列表同号，普通 [n] 继续按正文渲染。

用当前 Streamlit 已有的 st.components.v2 给这些锚点接悬停卡片和点击事件。卡片展示论文标题、PDF 文件页序和保存的原文片段，鼠标可移到卡片里的「在 PDF 中查看」。悬停只在浏览器内显示卡片。点击该按钮时用组件事件传回 ref，由对应回答的 Python 回调取得真实来源并调用现有 _request_pdf_preview。保留原「引用来源」入口，将侧栏和欢迎页提示改成与新交互一致。

按第 3 节复用 V50-018、V50-050 两份 D7 Agent 原生报告和原 PDF，用 C 段回放调用正式 app.main()。在真实浏览器按第 12.3 节验收。V50-018 重复的 [8] 均映射到 _p6_c3，临时副本的普通书目 [8] 无引用卡片。两份回答的 [2] 分别对应 V50-018 第 8 页、V50-050 第 1 页。点 V50-018 [8] 卡片的 PDF 按钮，确认右侧第 6 页 4 个框。悬停 V50-050 [5] 时右侧保持当前预览，点按钮后切到第 2 页 Table 1 的 2 个框。检查旧来源列表仍可用。

回放新增模型、embedding、rerank 调用均为 0。按 AGENTS.md 复用仍有效的 C 段验证，把本段实际改动、悬停来源和右侧跳转结果简要写入第 12.4 节，D 段验收完成即交付。
```
