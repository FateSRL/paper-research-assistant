"""论文聊天页面；正文按段落展示，点击引用编号查看原文。"""

import base64
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from queue import Empty, Queue
import re
import uuid

import pymupdf
import streamlit as st
import streamlit.components.v1 as components
import streamlit.components.v2 as components_v2

from paper_assistant import d9_runtime, import_runtime
from paper_assistant.answer_export import BASIS_LABELS, EVIDENCE_STATUS_LABELS
from paper_assistant.conversation import select_conversation_history


ROOT = Path(__file__).resolve().parent
PDF_PREVIEW_COMPONENT = components.declare_component(
    "pdf_preview", path=str(ROOT / "components" / "pdf_preview"))
PDF_PREVIEW_REQUEST_KEY = "pdf_preview_request"
PDF_PREVIEW_SEQUENCE_KEY = "pdf_preview_sequence"
PDF_PREVIEW_SHOWN_KEY = "pdf_preview_shown_token"
D8_REF_HANDLED_KEY = "d8_inline_ref_handled"
D8_INLINE_REFS = components_v2.component(
    "d8_inline_refs",
    html='<div class="d8-ref-root" aria-hidden="true"></div>',
    css=(ROOT / "components" / "inline_refs.css").read_text(encoding="utf-8"),
    js=(ROOT / "components" / "inline_refs.js").read_text(encoding="utf-8"),
    isolate_styles=False,
)
REPORT_KEY = "current_report"
PENDING_KEY = "d9_pending_submission"
SUBMISSIONS_KEY = "d9_submission_records"
INFLIGHT_KEY = "d9_submission_inflight"
FUTURE_KEY = "d9_submission_future"
NOTICE_KEY = "d9_submission_notice"
CONVERSATION_KEY = "d9_conversation_id"
CONVERSATION_VERSIONS_KEY = "d9_conversation_versions"
IMPORT_FUTURE_KEY = "paper_import_future"
IMPORT_INPUT_KEY = "paper_import_input"
IMPORT_QUEUE_KEY = "paper_import_queue"
IMPORT_PROGRESS_KEY = "paper_import_progress"
IMPORT_RESULT_KEY = "paper_import_result"
IMPORT_STAGE_LABELS = {"parse": "解析 PDF", "filter": "整理可用正文", "chunk": "分块",
                       "store": "保存原文", "index": "生成向量并写入", "request_started": "生成向量",
                       "request_finished": "生成向量", "batch_upserted": "写入向量",
                       "paper_ready": "入库完成", "ready": "入库完成", "paper_failed": "向量入库"}
STATUS_LABELS = {
    "answered": "已回答",
    "insufficient_evidence": "本轮证据不足",
    "tool_error": "工具或本机步骤失败",
    "invalid_output": "模型输出未通过检查",
    "budget_exceeded": "本轮预算已到",
    "needs_clarification": "需要明确追问对象",
}
ERROR_SUMMARIES = {
    "tool_error": "本轮流程未完成，请检查本机配置、索引占用或运行记录。",
    "invalid_output": "本轮模型输出未通过结构或引用检查，没有发布答案。",
    "budget_exceeded": "本轮请求次数、时间或输出预算已到，流程已经停止。",
}

CHAT_STYLE = """
<style>
.stMainBlockContainer { max-width: 850px; padding-top: 2rem; padding-bottom: 2rem; }
[data-testid="stSidebar"] { border-right: 1px solid #e9e9e9; }
[data-testid="stSidebar"] .stSidebarBlockContainer { padding-top: 2rem; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppDeployButton"] { display: none; }
[data-testid="stChatMessage"] { background: transparent; padding: 0; gap: 0; }
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] { display: none; }
[class*="st-key-user_"] [data-testid="stChatMessage"] {
    margin-left: auto; max-width: 85%; width: fit-content;
    background: #f3f3f3; border-radius: 22px; padding: .85rem 1.15rem;
}
[class*="st-key-user_"] { margin-top: 1.2rem; margin-bottom: .6rem; }
[class*="st-key-reply_"] { margin-bottom: 1.8rem; }
[class*="st-key-reply_"] [data-testid="stCaptionContainer"] { color: #868686; }
[class*="st-key-paragraph_"] { gap: .25rem; }
[class*="st-key-paragraph_"] > [data-testid="stMarkdownContainer"] p {
    font-size: 1rem; line-height: 1.85;
}
[class*="st-key-citation_"] { margin-bottom: .3rem; }
[class*="st-key-citation_"] [data-testid="stPopoverButton"] > button,
[class*="st-key-citation_"] button[data-testid="stPopoverButton"] {
    padding: .15rem .45rem; min-height: auto; line-height: 1.35;
    border: 0; border-radius: 5px; color: #626262; background: #f1f2f4;
}
[class*="st-key-citation_"] [data-testid="stPopoverButton"] > button:hover,
[class*="st-key-citation_"] button[data-testid="stPopoverButton"]:hover {
    background: #e5e7eb; color: #262626;
}
[class*="st-key-citation_"] [data-testid="stPopoverButton"] [aria-hidden="true"] { display: none; }
[class*="st-key-citation_"] [data-testid="stMarkdownContainer"] p {
    font-size: .75rem; line-height: 1.35; font-weight: 500;
}
[data-testid="stPopoverBody"][data-testid="stPopoverBody"] {
    min-width: 0 !important; max-width: min(640px, calc(100vw - 32px)) !important;
    box-sizing: border-box;
}
[class*="st-key-source_"] [data-testid="stText"] {
    font-family: inherit; font-size: .92rem; line-height: 1.7;
    white-space: pre-wrap; overflow-wrap: anywhere;
}
[class*="st-key-actions_"] { margin-top: .45rem; }
[class*="st-key-actions_"] button { font-size: .8rem; color: #737373; }
[data-testid="stChatInput"] { border-radius: 22px; border: 1px solid #e2e2e2; }
[data-testid="stBottomBlockContainer"] { max-width: 850px; padding-bottom: 1.25rem; }
.chat-brand { font-size: 1rem; font-weight: 600; color: #333; margin-bottom: .5rem; }
.chat-welcome { padding: 17vh 0 10vh; text-align: center; }
.chat-welcome h1 { font-size: 2rem; letter-spacing: -.04em; font-weight: 600; }
.chat-welcome p { color: #8a8a8a; font-size: .95rem; line-height: 1.9; }
.chat-loading { display: flex; align-items: center; gap: .7rem; color: #737373; padding: .7rem 0; }
.chat-loading-dot { width: 8px; height: 8px; border-radius: 50%; background: #737373; animation: chat-pulse 1.2s ease-in-out infinite; }
@keyframes chat-pulse { 50% { opacity: .25; } }
@media (max-width: 640px) {
    .stMainBlockContainer { padding-top: 1.2rem; }
    .chat-welcome { padding-top: 12vh; }
    .chat-welcome h1 { font-size: 1.65rem; }
}
</style>
"""

WIDE_CHAT_STYLE = """
<style>
.stMainBlockContainer { max-width: 100% !important; padding-left: 2rem; padding-right: 2rem; }
[data-testid="stColumn"]:has([class*="st-key-pdf_preview_pane_wrap"]) {
    position: sticky; top: 4.5rem; align-self: flex-start;
}
[class*="st-key-question"] {
    position: sticky !important; top: 4.5rem; z-index: 20;
    background: #ffffff;
}
</style>
"""


def _number(value):
    return str(value) if type(value) is int and value >= 0 else "未知"


def _text(value):
    return value if isinstance(value, str) else ""


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _ids(value):
    return "、".join(v for v in value if isinstance(v, str)) if isinstance(value, list) else "未知"


def _render_questions(report):
    st.text("用户原问题：" + (_text(report.get("user_question")) or _text(report.get("query"))))
    question = _text(report.get("standalone_question"))
    if "standalone_question" not in report and report.get("status") != "needs_clarification":
        question = _text(report.get("query"))
    if question:
        st.text("补全后的完整问题：" + question)
    elif report.get("status") == "needs_clarification":
        st.text("补全后的完整问题：尚待澄清，未形成完整问题。")
    else:
        st.text("补全后的完整问题：本轮未形成完整问题。")


def _pdf_preview_issue(source):
    """返回来源能否进入原 PDF 预览；文件存在性留给弹窗报告。"""
    if not isinstance(source, dict):
        return "来源记录不可用。"
    page = source.get("pdf_page")
    if type(page) is not int or page < 1:
        return "来源没有可用的 PDF 文件页序。"
    if not _text(source.get("pdf_absolute_path")):
        return "来源没有已校验的本地 PDF 文件。"
    return None


def _load_pdf_preview(source):
    """读取已校验来源对应的本地 PDF；不访问模型、索引或网络。"""
    result = {"error": None, "page": 1, "total": None, "data": ""}
    if not isinstance(source, dict):
        result["error"] = "来源记录不可用。"
        return result
    page = source.get("pdf_page")
    if type(page) is not int or page < 1:
        result["error"] = "来源没有可用的 PDF 文件页序。"
        return result
    result["page"] = page
    path_text = _text(source.get("pdf_absolute_path"))
    if not path_text:
        result["error"] = "来源没有已校验的本地 PDF 文件。"
        return result
    try:
        papers = (ROOT / "data" / "papers").resolve()
        path = Path(path_text).resolve()
        if not path.is_relative_to(papers) or path.suffix.lower() != ".pdf":
            result["error"] = "来源 PDF 路径不在允许的论文目录内。"
            return result
        if not path.is_file():
            result["error"] = "来源 PDF 文件不存在：" + path.name
            return result
        with pymupdf.open(path) as document:
            total = document.page_count
            if total < 1:
                result["error"] = "来源 PDF 没有可显示的页面。"
                return result
            result["total"] = total
            if page > total:
                result["error"] = f"来源页序 {page} 超出 PDF 总页数 {total}。"
                return result
        result["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        result["error"] = "来源 PDF 无法读取。"
    return result


def _request_pdf_preview(source):
    sequence = int(st.session_state.get(PDF_PREVIEW_SEQUENCE_KEY, 0)) + 1
    st.session_state[PDF_PREVIEW_SEQUENCE_KEY] = sequence
    st.session_state[PDF_PREVIEW_REQUEST_KEY] = {
        "token": sequence, "source": deepcopy(source) if isinstance(source, dict) else {}}


def _dismiss_pdf_preview():
    st.session_state.pop(PDF_PREVIEW_REQUEST_KEY, None)


def _active_pdf_preview():
    request = st.session_state.get(PDF_PREVIEW_REQUEST_KEY)
    if not isinstance(request, dict) or type(request.get("token")) is not int:
        return None
    source = request.get("source")
    return request if isinstance(source, dict) else None


def _clear_pdf_preview():
    st.session_state.pop(PDF_PREVIEW_REQUEST_KEY, None)
    st.session_state.pop(PDF_PREVIEW_SHOWN_KEY, None)


def _close_pdf_preview():
    _clear_pdf_preview()


def _render_pdf_preview_pane(source):
    """右列预览；与 A/B 共用本地文件、页序和 source_spans。"""
    payload = _load_pdf_preview(source)
    page = payload["page"]
    total = payload["total"]
    page_label = str(page) if type(page) is int and page > 0 else "未知"
    if type(total) is int and total > 0:
        page_label += " / " + str(total)
    title = _text(source.get("title")) if isinstance(source, dict) else ""
    chunk_id = _text(source.get("chunk_id")) if isinstance(source, dict) else ""
    header = st.columns([5, 1])
    with header[0]:
        st.markdown("**原 PDF**")
    with header[1]:
        st.button("关闭预览", key="close_pdf_preview", on_click=_close_pdf_preview)
    st.caption((title + " · " if title else "")
               + "PDF 文件页序 " + page_label + "（从 1 开始计数）"
               + (" · " + chunk_id if chunk_id else ""))
    if payload["error"]:
        st.warning(payload["error"])
        st.caption("引用原文仍保存在左侧来源卡片中；下方同时保留本轮引用文字。")
        raw = _text(source.get("text")) if isinstance(source, dict) else ""
        if raw:
            with st.expander("查看引用原文", expanded=True):
                st.text(raw)
        return
    PDF_PREVIEW_COMPONENT(
        pdf_base64=payload["data"],
        page=page,
        total_pages=total,
        title=title or "原 PDF",
        chunk_id=chunk_id,
        source_spans=(source.get("source_spans") if isinstance(source, dict)
                      and isinstance(source.get("source_spans"), list) else []),
        error=payload["error"],
        key="pdf_preview_pane",
        height=730,
    )


@st.dialog("原 PDF 预览", width="large", on_dismiss=_dismiss_pdf_preview)
def _render_pdf_preview_dialog(source, *, request_token):
    payload = _load_pdf_preview(source)
    page = payload["page"]
    total = payload["total"]
    page_label = str(page) if type(page) is int and page > 0 else "未知"
    if type(total) is int and total > 0:
        page_label += " / " + str(total)
    title = _text(source.get("title")) if isinstance(source, dict) else ""
    chunk_id = _text(source.get("chunk_id")) if isinstance(source, dict) else ""
    st.caption("PDF 文件页序 " + page_label + "（从 1 开始计数）"
               + (" · " + chunk_id if chunk_id else ""))
    if payload["error"]:
        st.warning(payload["error"])
        st.caption("引用原文仍保存在来源卡片中；下方同时保留本轮引用文字。")
        raw = _text(source.get("text")) if isinstance(source, dict) else ""
        if raw:
            with st.expander("查看引用原文", expanded=True):
                st.text(raw)
        return
    PDF_PREVIEW_COMPONENT(
        pdf_base64=payload["data"],
        page=page,
        total_pages=total,
        title=title or "原 PDF",
        chunk_id=chunk_id,
        source_spans=(source.get("source_spans") if isinstance(source, dict)
                      and isinstance(source.get("source_spans"), list) else []),
        error=payload["error"],
        key=f"pdf_preview_{request_token}",
        height=730,
    )


def _render_pdf_preview():
    request = st.session_state.get(PDF_PREVIEW_REQUEST_KEY)
    if not isinstance(request, dict):
        return
    token = request.get("token")
    if type(token) is not int or token == st.session_state.get(PDF_PREVIEW_SHOWN_KEY):
        return
    st.session_state[PDF_PREVIEW_SHOWN_KEY] = token
    source = request.get("source")
    _render_pdf_preview_dialog(source if isinstance(source, dict) else {}, request_token=token)


def _inline_ref_scope(key_prefix):
    scope = re.sub(r"[^A-Za-z0-9_-]", "_", _text(key_prefix))[:80]
    return scope or "answer"


def _inline_ref_links(answer, key_prefix, lookup):
    """只把本轮有 evidence_source 的 [ID:n] 变成带作用域的锚点。"""
    citations = answer.get("citations") or []
    by_ref = {}
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        ref = citation.get("ref")
        source = lookup.get(_text(citation.get("chunk_id")))
        if type(ref) is int and ref >= 0 and isinstance(source, dict):
            by_ref.setdefault(ref, source)
    scope = _inline_ref_scope(key_prefix)
    text = answer.get("text") if isinstance(answer.get("text"), str) else ""

    def replace(match):
        ref = int(match.group(1))
        if ref not in by_ref:
            return "[" + str(ref) + "]"
        return f"[[{ref}]](#d8-ref-{scope}-{ref})"

    return re.sub(r"\[ID:(\d+)\]", replace, text), by_ref, scope


def _inline_preview_suffix():
    request = st.session_state.get(PDF_PREVIEW_REQUEST_KEY)
    token = request.get("token") if isinstance(request, dict) else None
    return str(token) if type(token) is int else "0"


def _mount_inline_refs(scope, by_ref, key_prefix):
    if not by_ref:
        return
    rows = []
    for ref in sorted(by_ref):
        source = by_ref[ref]
        rows.append({
            "ref": ref,
            "title": _text(source.get("title")) or "原论文",
            "page": source.get("pdf_page") if type(source.get("pdf_page")) is int else None,
            "text": _text(source.get("text")),
            "available": _pdf_preview_issue(source) is None,
        })
    result = D8_INLINE_REFS(
        data={"scope": scope, "sources": rows},
        on_ref_click_change=lambda: None,
        key=f"d8_inline_refs_{scope}_{_inline_preview_suffix()}",
        height=0,
    )
    event = result.ref_click
    if not isinstance(event, dict):
        return
    ref, nonce = event.get("ref"), event.get("nonce")
    if type(ref) is not int:
        return
    handled = st.session_state.setdefault(D8_REF_HANDLED_KEY, {})
    if nonce is None or handled.get(scope) == nonce:
        return
    handled[scope] = nonce
    source = by_ref.get(ref)
    if source is not None:
        _request_pdf_preview(source)
        st.rerun()


def _show_source(source, number, *, shown=False, preview_key=None):
    """仅展示程序返回的定位与原文，不按模型描述重建来源。"""
    page = source.get("pdf_page")
    page_label = _number(page) if type(page) is int and page > 0 else "未知"
    with st.container():
        title = _text(source.get("title"))
        if title:
            st.markdown("**" + title + "**")
        st.caption(f"引用 {number} · PDF 文件页序 {page_label}（从 1 开始计数）")
        raw = source.get("shown_text") if shown else source.get("text")
        st.text(_text(raw))
    if preview_key is not None:
        issue = _pdf_preview_issue(source)
        if issue:
            st.caption("原 PDF 预览不可用：" + issue)
        else:
            st.button("在 PDF 中查看", key=preview_key,
                      on_click=_request_pdf_preview, args=(source,))
    with st.expander("来源定位"):
        identity = _text(source.get("paper_id"))
        version = _text(source.get("arxiv_version"))
        if identity or version:
            st.text("论文 / arXiv 版本：" + " / ".join(v for v in (identity, version) if v))
        revision = _text(source.get("parse_revision"))
        if revision:
            st.text("解析版本：" + revision)
        st.text("chunk ID：" + _text(source.get("chunk_id")))
        if source.get("parent_id"):
            st.text("父内容 ID：" + _text(source.get("parent_id")))
        section = source.get("section_path")
        if isinstance(section, list) and section:
            st.text("章节：" + " / ".join(_text(item) for item in section))
        if source.get("content_type"):
            st.text("内容类型：" + _text(source.get("content_type")))
        if source.get("content_types"):
            st.text("来源内容类型：" + _ids(source.get("content_types")))
        spans = source.get("source_spans")
        if isinstance(spans, list):
            for region_number, span in enumerate(spans, start=1):
                if not isinstance(span, dict):
                    continue
                label = "来源区域 " + str(region_number)
                st.text(label + " · PDF 文件页序：" + _number(span.get("pdf_page")))
                st.text(label + "来源块：" + _text(span.get("block_id")))
                if span.get("content_type"):
                    st.text(label + "内容类型：" + _text(span.get("content_type")))
                coordinates = span.get("coordinate_system")
                coordinate_label = ("归一化坐标，0–1，相对页面宽高" if coordinates == "normalized"
                                    else _text(coordinates) or "原记录坐标")
                st.text(label + " bbox（" + coordinate_label + "）："
                        + json.dumps(span.get("bbox"), ensure_ascii=False))
                if span.get("page_size"):
                    st.text(label + "页面尺寸（PDF point）：" + json.dumps(span["page_size"]))
                if span.get("source_field"):
                    st.text(label + "转录字段：" + _text(span.get("source_field")))
                st.text(label + "子块文本范围：" + str(span.get("text_start"))
                        + "–" + str(span.get("text_end")))
        elif source.get("segment_bbox") is not None:
            st.text("来源块序：" + _number(source.get("source_block_index")))
            st.text("bbox（PDF point）：" + json.dumps(source["segment_bbox"], ensure_ascii=False))
        if source.get("assets"):
            st.text("关联图像与结构资产：")
            st.json(source["assets"], expanded=False)
        if source.get("reading_origins"):
            st.text("本地上下文读取来源：")
            st.json(source["reading_origins"], expanded=False)


def _shown_sources(report):
    result = report.get("result") or {}
    if not isinstance(result, dict):
        return []
    context = result.get("context") or {}
    if not isinstance(context, dict):
        return []
    rows = context.get("shown_evidence") or []
    metadata = report.get("selected_version_metadata") or []
    lookup = {(item.get("paper_id"), item.get("parse_revision")): item
              for item in metadata if isinstance(item, dict)} if isinstance(metadata, list) else {}
    if not isinstance(rows, list):
        return []
    return [{**lookup.get((row.get("paper_id"), row.get("parse_revision")), {}), **row}
            for row in rows if isinstance(row, dict)]


def _render_usage(report):
    embedding = report.get("embedding_statistics") or {}
    chat = report.get("chat_statistics") or {}
    rerank = _mapping(report.get("rerank_statistics"))
    if not isinstance(embedding, dict):
        embedding = {}
    if not isinstance(chat, dict):
        chat = {}
    with st.expander("本轮用量与运行信息"):
        st.text("运行 ID：" + _text(report.get("run_id")))
        st.text("提交 ID：" + _text(report.get("submission_id")))
        st.text("历史报告：" + _text(report.get("history_report")))
        st.text("问题 embedding 请求：" + _number(report.get("embedding_requests")))
        st.text("重排请求：" + _number(report.get("rerank_requests", 0)))
        st.text("重排耗时：" + str(rerank.get("elapsed_seconds", 0)) + " 秒")
        st.text("聊天请求尝试：" + _number(report.get("llm_requests")))
        st.text("网络请求尝试：" + _number(report.get("network_requests")))
        st.text("Embedding tokens：" + _number(embedding.get("total_tokens")))
        st.text("聊天 tokens：" + _number(chat.get("total_tokens")))
        st.text("已知聊天 tokens：" + _number(chat.get("known_total_tokens")))
        st.text("聊天重试：" + _number(chat.get("network_retries"))
                + "；输出修复：" + _number(chat.get("repairs")))
        st.caption("未知表示未取得完整用量，不代表没有发生调用。")


def _show_qualification(qualification):
    """显示 runtime 的资格记录，不在页面重新推断摘要或候选资格。"""
    requirement = _mapping(qualification.get("requirement"))
    st.text("来源要求：" + _text(requirement.get("required_scope"))
            + "；识别结果：" + _text(requirement.get("resolution")))
    st.text("原始召回数：" + _number(qualification.get("raw_candidate_count")))
    st.text("合格候选 ID：" + _ids(qualification.get("eligible_ids")))
    st.text("实际展示 ID：" + _ids(qualification.get("shown_ids")))
    for row in qualification.get("decisions") or []:
        if not isinstance(row, dict):
            continue
        st.text(" / ".join((_text(row.get("chunk_id")),
                "轮次：" + _text(row.get("round")), "来源：" + _text(row.get("coverage")),
                "摘要资格：" + ("合格" if row.get("eligible") is True else "不合格"),
                "本题候选：" + ("纳入" if row.get("included") is True else "排除"),
                "原因：" + (_text(row.get("reason")) or "无"))))


def _render_trajectory(report):
    result = _mapping(report.get("result"))
    autonomous = result.get("retrieval_strategy") == "autonomous"
    with st.expander("来源资格与检索轨迹"):
        st.text("停止原因：" + (_text(report.get("stop_reason"))
                              or _text(result.get("stop_reason")) or "未记录"))
        if autonomous:
            st.text(("自主轮数：" if result.get("loop_version") else "自主步数：") + _number(result.get("autonomous_steps_used"))
                    + " / " + _number(result.get("autonomous_step_limit")))
            st.text("触顶收尾：" + ("是" if result.get("limit_finalize") is True else "否"))
        if result.get("loop_version"):
            st.text("实际取证调用：" + _number(result.get("evidence_calls_used")))
            if result.get("recovery"):
                st.text("正文恢复：" + _text(result["recovery"].get("kind")))
            if result.get("synthesis"):
                st.text("无工具综合：" + _text(result["synthesis"].get("status")))
        plan = result.get("planned_queries", report.get("planned_queries"))
        if isinstance(plan, list) and plan:
            st.caption("建议查询（模型可调整或跳过）" if autonomous else "本轮检索计划")
            for number, query in enumerate(plan, start=1):
                if not isinstance(query, dict):
                    continue
                label = f"建议查询 {number}" if autonomous else f"计划查询 {number}"
                st.text(label + "：" + _text(query.get("query")))
                for version in query.get("selected_versions") or []:
                    if isinstance(version, dict):
                        st.text(label + "论文 / 解析版本：" + _text(version.get("paper_id"))
                                + " / " + _text(version.get("parse_revision")))
        if autonomous:
            for step in result.get("action_steps") or []:
                if not isinstance(step, dict):
                    continue
                label = ("触顶收尾" if step.get("limit_finalize") is True else
                         "自主步骤 " + _number(step.get("autonomous_step")))
                if step.get("repair_kind"):
                    label += "（修复）"
                action = _mapping(step.get("parsed_action"))
                names = [_text(_mapping(call.get("function")).get("name")) for call in step.get("tool_calls") or []]
                st.text(label + "模型动作：" + (", ".join(names) if names else _text(action.get("action")) or "未完成"))
                if step.get("error"):
                    error = _mapping(step["error"])
                    st.text(label + "本轮错误：" + (_text(error.get("code")) or "未记录"))
                st.text(label + "剩余步数：" + _number(step.get("remaining_steps")))
                if action.get("missing_information"):
                    st.text(label + "取证目标：" + _text(action.get("missing_information")))
                if action.get("query"):
                    st.text(label + "查询：" + _text(action.get("query")))
                for version in action.get("selected_versions") or []:
                    if isinstance(version, dict):
                        st.text(label + "论文 / 解析版本：" + _text(version.get("paper_id"))
                                + " / " + _text(version.get("parse_revision")))
                for call in step.get("tool_calls") or []:
                    observation = _mapping(call.get("tool_observation"))
                    if not observation:
                        continue
                    name = _text(_mapping(call.get("function")).get("name")) or "工具"
                    st.text(label + "工具观察（" + name + "）：")
                    st.json(observation, expanded=False)
                if step.get("tool_observation") is not None:
                    st.text(label + "工具观察：")
                    st.json(step["tool_observation"], expanded=False)
        qualification = _mapping(result.get("source_qualification"))
        if qualification:
            _show_qualification(qualification)
        else:
            requirement = _mapping(result.get("source_requirement"))
            if requirement:
                st.text("来源要求：" + _text(requirement.get("required_scope"))
                        + "；识别结果：" + _text(requirement.get("resolution")))
            st.info("本轮尚无来源资格记录。")
        rounds = result.get("search_rounds")
        if not isinstance(rounds, list):
            # 固定 RAG 只有一轮，沿用它保存的 search 与资格，不能创建补轮。
            search = _mapping(result.get("search"))
            rounds = [{"round": 1, "query": search.get("query"),
                       "status": search.get("status"), "search": search,
                       "statistics": search.get("statistics")}] if search else []
        for number, row in enumerate(rounds, start=1):
            if not isinstance(row, dict):
                continue
            search = _mapping(row.get("search"))
            rows = search.get("results")
            planned = row.get("kind") == "planned" or result.get("retrieval_strategy") == "planned_queries"
            adaptive = autonomous or row.get("kind") == "adaptive"
            label = (f"自适应取证 {number}" if adaptive else f"计划查询 {number}" if planned
                     else "初次" if row.get("round") == 1 else "补查")
            st.text(label + "实际查询：" + _text(row.get("query")))
            if adaptive:
                st.text(label + "自主步骤：" + _number(row.get("autonomous_step")))
                if row.get("observation") is not None:
                    st.text(label + "工具观察：")
                    st.json(row["observation"], expanded=False)
            for version in row.get("selected_versions") or search.get("selected_versions") or []:
                if isinstance(version, dict):
                    st.text(label + "实际论文 / 解析版本：" + _text(version.get("paper_id"))
                            + " / " + _text(version.get("parse_revision")))
            st.text(label + "状态：" + _text(row.get("status")))
            st.text(label + "召回数：" + (_number(len(rows)) if isinstance(rows, list) else "未知"))
            if isinstance(rows, list):
                st.text(label + "召回 ID：" + _ids([r.get("chunk_id") for r in rows if isinstance(r, dict)]))
            stats = _mapping(row.get("statistics"))
            st.text(label + " embedding 请求：" + _number(stats.get("embedding_requests")))
            rerank = _mapping(row.get("rerank_statistics") or search.get("rerank_statistics"))
            st.text(label + "重排请求：" + _number(rerank.get("requests", 0))
                    + "；重排耗时：" + str(rerank.get("elapsed_seconds", 0)) + " 秒")
            method = search.get("ranking_method")
            if method:
                st.text(label + "排序方式：" + ("模型重排" if method == "rerank" else "RRF 融合排序" if method == "rrf" else _text(method)))
        retry = _mapping(result.get("retry_decision"))
        if retry and not autonomous:
            st.text("补查缺失信息：" + _text(retry.get("missing_information")))
            st.text("拟补查查询：" + _text(retry.get("retry_query")))
            st.text("补查执行：" + ("是" if retry.get("executed") is True else "否"))
        merge = _mapping(result.get("merge_trace"))
        if merge:
            if "new_returned_ids" in merge:
                st.text("新增召回 ID：" + _ids(merge.get("new_returned_ids")))
            if "new_shown_ids" in merge:
                st.text("新增展示 ID：" + _ids(merge.get("new_shown_ids")))
            st.text("最终展示 ID：" + _ids(merge.get("final_shown_ids")))
        checks = result.get("source_scope_checks")
        if isinstance(checks, list) and checks:
            st.caption("逐引用来源检查（runtime 保存的记录）")
            st.json(checks, expanded=False)


def _render_downloads(report, *, key_prefix):
    """下载由已保存报告生成；导出失败也不重新运行模型。"""
    markdown_bytes = None
    try:
        json_bytes, markdown_bytes = d9_runtime.download_payloads(report, project_root=ROOT)
    except Exception:
        st.warning("Markdown 导出暂不可用；完整 JSON 记录仍可下载。")
        json_bytes = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    run_id = _text(report.get("run_id"))
    # 仅用于下载文件名，避免将任意内容带进文件名。
    safe_id = "".join(c for c in run_id if c.isascii() and (c.isalnum() or c in "_-"))[:100] or "latest"
    st.download_button("下载完整 JSON", json_bytes, file_name=f"answer_{safe_id}.json",
                       mime="application/json", key="download_json_" + key_prefix, on_click="ignore")
    if markdown_bytes is not None:
        st.download_button("下载 Markdown", markdown_bytes, file_name=f"answer_{safe_id}.md",
                           mime="text/markdown", key="download_markdown_" + key_prefix, on_click="ignore")


def render_report(report, *, key_prefix):
    """展示保存的正文；引用编号仅映射本轮实际使用的 citation_ids。"""
    status = report.get("status")
    if status not in STATUS_LABELS:
        status = "tool_error"
    label = STATUS_LABELS[status] + "（" + status + "）"
    answer = report.get("answer") or {}
    if not isinstance(answer, dict):
        answer = {}
    if status == "answered":
        evidence_status = EVIDENCE_STATUS_LABELS.get(answer.get("evidence_status"))
        if evidence_status:
            st.caption("回答依据：" + evidence_status)
        sources = answer.get("evidence_sources") or []
        lookup = {_text(source.get("chunk_id")): source for source in sources
                  if isinstance(source, dict)}
        if isinstance(answer.get("text"), str):
            citations = answer.get("citations") or []
            text, inline_refs, inline_scope = _inline_ref_links(answer, key_prefix, lookup)
            st.markdown(text)
            _mount_inline_refs(inline_scope, inline_refs, key_prefix)
            if citations:
                preview_request = st.session_state.get(PDF_PREVIEW_REQUEST_KEY)
                preview_token = (preview_request.get("token")
                                 if isinstance(preview_request, dict) else None)
                preview_suffix = str(preview_token) if type(preview_token) is int else "0"
                unique = []
                seen = set()
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    identifier = _text(citation.get("chunk_id"))
                    if identifier and identifier not in seen:
                        seen.add(identifier)
                        unique.append(citation)
                with st.popover("引用来源（" + str(len(citations)) + " 处 / "
                                + str(len(unique)) + " 个来源）", type="tertiary",
                                width="content",
                                key=f"prose_citations_{key_prefix}_{preview_suffix}",
                                on_change="ignore"):
                    st.markdown("**正文引用**")
                    for number, citation in enumerate(unique, start=1):
                        source = lookup.get(_text(citation.get("chunk_id")))
                        if source is None:
                            st.info("本次报告未保存引用原文：" + _text(citation.get("chunk_id")))
                            continue
                        if number > 1:
                            st.divider()
                        _show_source(source, citation.get("ref"),
                                     preview_key="pdf_preview_" + key_prefix + "_"
                                     + (_text(citation.get("chunk_id")) or _text(source.get("chunk_id"))))
            reason = _text(answer.get("reason"))
            if reason:
                st.caption(reason)
        else:
            citation_numbers = {}
            for number, claim in enumerate(answer.get("claims") or [], start=1):
                if not isinstance(claim, dict):
                    continue
                basis = claim.get("basis", "paper_evidence")
                ids = claim.get("citation_ids") or []
                with st.container(key=f"paragraph_{key_prefix}_{number}"):
                    st.markdown(_text(claim.get("claim")))
                    if basis != "paper_evidence":
                        st.caption(BASIS_LABELS.get(basis, "未标注依据"))
                    if not ids:
                        continue
                    for citation_id in ids:
                        if citation_id not in citation_numbers:
                            citation_numbers[citation_id] = len(citation_numbers) + 1
                    citation_label = " ".join(f"[{citation_numbers[citation_id]}]" for citation_id in ids)
                    with st.popover(citation_label, type="tertiary", width="content",
                                    key=f"citation_{key_prefix}_{number}", on_change="ignore"):
                        st.markdown("**本段引用**")
                        for quote in claim.get("evidence_quotes") or []:
                            st.caption("本段原文短引句 · " + _text(quote.get("chunk_id")))
                            st.code(_text(quote.get("quote")), language=None)
                        for source_number, citation_id in enumerate(ids, start=1):
                            source = lookup.get(citation_id)
                            if source is None:
                                st.info("本次报告未保存引用原文：" + _text(citation_id))
                                continue
                            if source_number > 1:
                                st.divider()
                            with st.container(key=f"source_{key_prefix}_{number}_{source_number}"):
                                _show_source(source, citation_numbers[citation_id])
            reason = _text(answer.get("reason"))
            if reason:
                st.caption(reason)
    elif status == "needs_clarification":
        st.info(_text(report.get("clarification_question")) or "请明确本轮追问的对象。")
    else:
        if status == "insufficient_evidence":
            st.warning(label)
            reason = _text(answer.get("reason"))
            if reason:
                st.text(reason)
            st.caption("这表示本轮展示证据无法回答完整问题，不代表原论文没有相关内容。")
        else:
            sources = _shown_sources(report)
            if sources:
                st.markdown("这次回答暂未完整生成，已找到的论文资料保存在下方。")
                st.caption("可以展开查看原文，或重新发送问题。")
            else:
                st.info("这次暂未取得可用回答，可以稍后重新发送，或先问其中一个具体问题。")
        with st.expander("查看本轮检索到的原文", expanded=False):
            sources = _shown_sources(report)
            if not sources:
                st.info("本轮没有可展示的证据。")
            for number, source in enumerate(sources, start=1):
                with st.container(key=f"source_{key_prefix}_shown_{number}"):
                    _show_source(source, source.get("ref", number), shown=True)
    with st.expander("回答详情与下载"):
        if status not in ("answered", "needs_clarification", "insufficient_evidence"):
            st.caption("运行状态：" + label)
            st.text(ERROR_SUMMARIES[status])
            error = _mapping(report.get("error"))
            code = _text(error.get("code"))
            if code:
                st.text("具体原因：" + code)
            if code == "export_error":
                st.warning("运行记录保存未完成；已发生的用量保留在本轮报告中。")
        _render_questions(report)
        versions = report.get("selected_versions") or []
        metadata = report.get("selected_version_metadata") or []
        titles = {(row.get("paper_id"), row.get("parse_revision")): _text(row.get("title"))
                  for row in metadata if isinstance(row, dict)}
        with st.expander("本次提交所选版本"):
            for pair in versions:
                if isinstance(pair, dict):
                    identity = (_text(pair.get("paper_id")), _text(pair.get("parse_revision")))
                    title = titles.get(identity)
                    if title:
                        st.text(title)
                    st.text(" / ".join(identity))
        _render_trajectory(report)
        _render_usage(report)
        with st.container(key="actions_" + key_prefix, horizontal=True):
            _render_downloads(report, key_prefix=key_prefix)


def _new_conversation():
    """开启所选论文的新对话，已有回答继续保留。"""
    _clear_pdf_preview()
    st.session_state[CONVERSATION_KEY] = str(uuid.uuid4())
    st.session_state[CONVERSATION_VERSIONS_KEY] = frozenset(
        tuple(pair) for pair in st.session_state.get("selected_versions", []))
    st.session_state.pop(REPORT_KEY, None)
    st.session_state.pop(NOTICE_KEY, None)


def _ensure_conversation():
    versions = frozenset(tuple(pair) for pair in st.session_state.get("selected_versions", []))
    if (not st.session_state.get(CONVERSATION_KEY)
            or st.session_state.get(CONVERSATION_VERSIONS_KEY) != versions):
        _new_conversation()
    return st.session_state[CONVERSATION_KEY]


def _select_conversation():
    conversation_id = st.session_state["conversation_picker"]
    _clear_pdf_preview()
    st.session_state[CONVERSATION_KEY] = conversation_id
    st.session_state.pop(REPORT_KEY, None)
    st.session_state.pop(NOTICE_KEY, None)
    for record in st.session_state.get(SUBMISSIONS_KEY, {}).values():
        if (record.get("conversation_id") or "legacy") != conversation_id:
            continue
        selected = deepcopy(record.get("selected_versions", []))
        st.session_state["selected_versions"] = selected
        st.session_state[CONVERSATION_VERSIONS_KEY] = frozenset(tuple(pair) for pair in selected)
        if isinstance(record.get("report"), dict):
            st.session_state[REPORT_KEY] = record["report"]


def _conversation_choices():
    current = st.session_state[CONVERSATION_KEY]
    labels = {}
    for record in st.session_state.get(SUBMISSIONS_KEY, {}).values():
        conversation_id = record.get("conversation_id") or "legacy"
        labels.setdefault(conversation_id, _text(record.get("query"))[:28] or "新对话")
    labels.setdefault(current, "新对话")
    return list(labels), {conversation_id: f"对话 {number} · {title}"
                          for number, (conversation_id, title) in enumerate(labels.items(), start=1)}


def _queue_submission():
    """发送事件固定本轮问题、所选版本与同会话历史。"""
    conversation_id = _ensure_conversation()
    st.session_state[PENDING_KEY] = {
        "token": str(uuid.uuid4()), "query": st.session_state.get("question", ""),
        "selected_versions": deepcopy(st.session_state.get("selected_versions", [])),
        "mode": "agent",
        "conversation_id": conversation_id,
        "conversation_history": select_conversation_history(
            st.session_state.get(SUBMISSIONS_KEY, {}), conversation_id),
    }


def _execute_submission(submission):
    """先保存用户消息与固定参数，再在后台运行本轮问答。"""
    token = submission["token"]
    records = st.session_state.setdefault(SUBMISSIONS_KEY, {})
    if token in records or _busy():
        return
    record = {**deepcopy(submission), "status": "reserved", "report": None}
    records[token] = record
    st.session_state[INFLIGHT_KEY] = token
    st.session_state.pop(NOTICE_KEY, None)
    st.session_state.pop(REPORT_KEY, None)
    try:
        selected, question = submission["selected_versions"], submission["query"]
        if not 1 <= len(selected) <= 3:
            record["status"] = "invalid_input"
            st.session_state[NOTICE_KEY] = "请选择 1–3 篇论文。"
            return
        if not question.strip():
            record["status"] = "invalid_input"
            st.session_state[NOTICE_KEY] = "请输入问题后再提交。"
            return
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            st.session_state[FUTURE_KEY] = executor.submit(
                d9_runtime.run_question, question, deepcopy(selected), mode=submission["mode"],
                project_root=ROOT, submission_id=token, conversation_id=submission.get("conversation_id"),
                conversation_history=deepcopy(submission.get("conversation_history", [])), library_mode=True)
        finally:
            executor.shutdown(wait=False)
    except Exception:
        record.update(status="runtime_error", error_code="report_unavailable", usage_known=False)
        st.session_state[NOTICE_KEY] = "本次提交未取得完整报告，实际用量未知；请检查本机运行记录。"
    finally:
        if FUTURE_KEY not in st.session_state:
            st.session_state[INFLIGHT_KEY] = None


def _collect_submission():
    """页面线程接收已完成结果；后台线程不访问页面或会话状态。"""
    future = st.session_state.get(FUTURE_KEY)
    if future is None or not future.done():
        return False
    token = st.session_state[INFLIGHT_KEY]
    record = st.session_state[SUBMISSIONS_KEY][token]
    active = (record.get("conversation_id") or "legacy") == st.session_state.get(CONVERSATION_KEY)
    try:
        report = future.result()
        if not isinstance(report, dict):
            raise RuntimeError("runtime returned no report")
        # 完整报告先进入会话；后续轨迹/导出渲染异常不能使此 token 再运行。
        record.update(status="completed", report=report)
        if active:
            st.session_state[REPORT_KEY] = report
    except d9_runtime.InvalidQuestion:
        record.update(status="invalid_input", error_code="invalid_question")
        if active:
            st.session_state[NOTICE_KEY] = "输入或所选论文版本无效，请重新选择论文并检查问题后提交。"
    except Exception:
        record.update(status="runtime_error", error_code="report_unavailable", usage_known=False)
        if active:
            st.session_state[NOTICE_KEY] = "本次提交未取得完整报告，实际用量未知；请检查本机运行记录。"
    finally:
        # 清 inflight 只允许另一新 token，原 token 始终保留在 records。
        st.session_state[INFLIGHT_KEY] = None
        st.session_state.pop(FUTURE_KEY, None)
    return True


def _render_inflight(show_loading):
    if _collect_submission():
        st.rerun()
    if show_loading:
        st.markdown('<div class="chat-loading" role="status"><span class="chat-loading-dot"></span>'
                    '正在阅读论文并整理回答…</div>', unsafe_allow_html=True)


def _busy():
    return bool(st.session_state.get(INFLIGHT_KEY) or st.session_state.get(IMPORT_FUTURE_KEY))


def _start_paper_import(retry=False):
    if _busy():
        return
    if not retry:
        uploaded = st.session_state.get("paper_upload")
        if uploaded is None:
            return
        st.session_state[IMPORT_INPUT_KEY] = {
            "pdf_bytes": uploaded.getvalue(), "filename": uploaded.name,
            "title": st.session_state.get("paper_upload_title", ""),
            "source_url": st.session_state.get("paper_upload_source", ""),
        }
    parameters = st.session_state.get(IMPORT_INPUT_KEY)
    if parameters is None:
        return
    queue = Queue()
    st.session_state[IMPORT_QUEUE_KEY] = queue
    st.session_state[IMPORT_PROGRESS_KEY] = {"stage": "parse"}
    st.session_state.pop(IMPORT_RESULT_KEY, None)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        st.session_state[IMPORT_FUTURE_KEY] = executor.submit(
            import_runtime.import_pdf, **deepcopy(parameters), project_root=ROOT, on_progress=queue.put)
    finally:
        executor.shutdown(wait=False)


def _collect_paper_import():
    queue = st.session_state.get(IMPORT_QUEUE_KEY)
    if queue is not None:
        while True:
            try:
                event = queue.get_nowait()
            except Empty:
                break
            previous = st.session_state.get(IMPORT_PROGRESS_KEY, {})
            st.session_state[IMPORT_PROGRESS_KEY] = {**previous, **event}
    future = st.session_state.get(IMPORT_FUTURE_KEY)
    if future is None or not future.done():
        return False
    try:
        st.session_state[IMPORT_RESULT_KEY] = future.result()
    except Exception:
        stage = st.session_state.get(IMPORT_PROGRESS_KEY, {}).get("stage", "parse")
        st.session_state[IMPORT_RESULT_KEY] = {
            "status": "failed", "stage": stage, "error": "入库未完成，请检查本机配置后重试。"}
    finally:
        st.session_state.pop(IMPORT_FUTURE_KEY, None)
        st.session_state.pop(IMPORT_QUEUE_KEY, None)
    return True


def _render_import_status():
    if _collect_paper_import():
        st.rerun()
    result = st.session_state.get(IMPORT_RESULT_KEY)
    if result:
        if result["status"] == "ready":
            st.success("已入库：" + result["title"])
            st.caption("在“本次阅读的论文”中选择它，即可提问。")
        else:
            stage = IMPORT_STAGE_LABELS.get(result.get("stage"), "入库")
            st.error(stage + "未完成：" + result.get("error", "请重试。"))
            st.button("重试入库", key="retry_paper_import", disabled=_busy(),
                      on_click=_start_paper_import, args=(True,))
    elif st.session_state.get(IMPORT_FUTURE_KEY):
        progress = st.session_state.get(IMPORT_PROGRESS_KEY, {})
        label = IMPORT_STAGE_LABELS.get(progress.get("stage"), "正在入库")
        completed = progress.get("completed_count", 0)
        total = progress.get("expected_count") or progress.get("chunk_count")
        if total:
            label += f" {completed}／{total}"
        st.markdown('<div class="chat-loading" role="status"><span class="chat-loading-dot"></span>'
                    + label + '…</div>', unsafe_allow_html=True)


def _render_import_controls():
    with st.expander("添加论文"):
        uploaded = st.file_uploader("上传 PDF", type=["pdf"], key="paper_upload", disabled=_busy())
        st.text_input("论文标题（可选）", key="paper_upload_title", disabled=_busy())
        st.text_input("来源链接（可选）", key="paper_upload_source", disabled=_busy())
        st.caption("支持可提取正文的 PDF，标题默认文件名。点击开始入库会使用 embedding 额度。")
        st.button("开始入库", key="start_paper_import", disabled=uploaded is None or _busy(),
                  on_click=_start_paper_import)
        if st.session_state.get(IMPORT_FUTURE_KEY):
            st.fragment(run_every=0.5)(_render_import_status)()
        else:
            _render_import_status()


def main():
    initial_preview = _active_pdf_preview()
    st.set_page_config(page_title="论文研究助手", page_icon="📚",
                       layout="wide" if initial_preview else "centered")
    st.html(CHAT_STYLE)
    if initial_preview:
        st.html(WIDE_CHAT_STYLE)
    _collect_paper_import()
    _collect_submission()
    pending = st.session_state.pop(PENDING_KEY, None)
    if isinstance(pending, dict):
        _execute_submission(pending)
    _collect_submission()
    try:
        rows = d9_runtime.list_ready_versions(project_root=ROOT)
    except Exception:
        rows = []
        st.error("论文列表暂时无法读取，请检查本机索引。")
    options = [(row["paper_id"], row["parse_revision"]) for row in rows]
    labels = {pair: _text(row.get("title")) or pair[0] for pair, row in zip(options, rows)}
    # 同名论文的两个解析版本也能在选择时辨认。
    counts = {title: list(labels.values()).count(title) for title in labels.values()}

    def label_for(pair):
        title = labels[pair]
        return title + (" · " + pair[1] if counts[title] > 1 else "")

    with st.sidebar:
        st.markdown("### 论文研究助手")
        st.caption("从原文出发，读懂每一个结论。")
        st.divider()
        st.session_state.setdefault("selected_versions", options[:1])
        if st.session_state.get(IMPORT_RESULT_KEY, {}).get("status") == "ready":
            # 新论文可能使同名标题增加版本后缀，同步原选择的显示值。
            st.session_state["selected_versions"] = list(st.session_state["selected_versions"])
        selected = st.multiselect("本次阅读的论文", options,
                                  format_func=label_for, max_selections=3, key="selected_versions")
        _ensure_conversation()
        _render_import_controls()
        st.button("新对话", key="new_conversation", on_click=_new_conversation)
        choices, conversation_labels = _conversation_choices()
        # 首问会改变显示标题，ID 不变时也要同步浏览器中的选中值。
        st.session_state["conversation_picker"] = st.session_state[CONVERSATION_KEY]
        st.selectbox("历史对话", choices, format_func=conversation_labels.get,
                     key="conversation_picker", on_change=_select_conversation)
        if selected:
            with st.expander("论文版本"):
                for paper_id, revision in selected:
                    st.text(paper_id + " / " + revision)
        st.divider()
        st.markdown("**悬停正文引用看原文，点击卡片中的按钮打开右侧原 PDF。**")
        st.caption("模型知识和分析会单独标注。")
        st.caption("下方「引用来源」仍保留完整列表；同一组论文支持继续追问，切换论文或版本会开启新对话。")
    preview_request = _active_pdf_preview()
    if initial_preview is not None and preview_request is None:
        st.rerun()

    def render_chat():
        st.html('<div class="chat-brand">论文研究助手</div>')
        st.chat_input("向论文提问…", key="question", disabled=not options or _busy(),
                      on_submit=_queue_submission)
        if not options:
            st.info("当前没有已入库的完整论文，请先导入论文。")
        notice = st.session_state.get(NOTICE_KEY)
        if isinstance(notice, str):
            st.warning(notice)
        records = st.session_state.get(SUBMISSIONS_KEY, {})
        visible = [(token, record) for token, record in records.items()
                   if (record.get("conversation_id") or "legacy") == st.session_state[CONVERSATION_KEY]
                   and (isinstance(record.get("report"), dict)
                        or record.get("status") in ("reserved", "runtime_error"))]
        if not visible:
            st.html('<div class="chat-welcome"><h1>今天想读懂什么？</h1>'
                    '<p>选择论文，提出问题。<br>悬停正文引用看原文，点击卡片按钮打开原 PDF。</p></div>')
        loading_shown = False
        for token, record in visible:
            report = record.get("report")
            query = ((_text(report.get("user_question")) or _text(report.get("query")))
                     if isinstance(report, dict) else _text(record.get("query")))
            with st.container(key="user_" + token):
                with st.chat_message("user"):
                    st.markdown(query)
            with st.container(key="reply_" + token):
                with st.chat_message("assistant"):
                    if isinstance(report, dict):
                        render_report(report, key_prefix=token)
                    elif record.get("status") == "reserved":
                        loading_shown = True
                        st.fragment(run_every=0.5)(_render_inflight)(True)
                    else:
                        st.error("本次提交未取得完整报告，实际用量未知；请检查本机运行记录。")
        if st.session_state.get(INFLIGHT_KEY) and not loading_shown:
            st.caption("另一段对话正在生成回答，完成后可继续发送。")
            st.fragment(run_every=0.5)(_render_inflight)(False)

    if preview_request is not None:
        left, right = st.columns([1, 1.25], gap="large")
        with left:
            render_chat()
        with right:
            with st.container(key="pdf_preview_pane_wrap"):
                _render_pdf_preview_pane(preview_request["source"])
    else:
        render_chat()


if __name__ == "__main__":
    main()
