"""D5 E：问答记录的可读副本与不可覆盖的历史文件。

这里不生成或校验答案。原文只放在足够长的代码围栏中；定位事实来自
固定 RAG 的程序结果。最近记录允许原子替换，历史记录只允许独占新建。
"""

import json
import os
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4


BASIS_LABELS = {
    "paper_evidence": "论文原文",
    "model_knowledge": "模型知识",
    "analysis": "分析",
}
EVIDENCE_STATUS_LABELS = {
    "paper_only": "论文原文",
    "mixed": "含补充或分析",
    "none": "未引用论文原文",
}


def fenced(text: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(r"`+", text)), default=0)
    marker = "`" * max(3, longest + 1)
    return marker + "text\n" + text + "\n" + marker


def code_span(text: str) -> str:
    text = str(text).replace("\r", "\\r").replace("\n", "\\n")
    longest = max((len(match.group()) for match in re.finditer(r"`+", text)), default=0)
    marker = "`" * (longest + 1)
    return marker + " " + text + " " + marker


def escape_markdown(text: str) -> str:
    text = str(text).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", text)


def file_link(path: Path | str, label: str) -> str:
    value = Path(path).as_posix()
    if not value.startswith("/"):
        value = "/" + value
    return "[" + escape_markdown(label) + "](<" + quote(value, safe="/: ") + ">)"


def source_location_lines(source: dict) -> list[str]:
    """Keep each stored source region and its coordinate system in the download."""
    location = {key: source[key] for key in (
        "parent_id", "section_path", "content_type", "content_types", "source_spans",
        "assets", "reading_origins", "segment_id", "char_start", "char_end",
        "source_block_index", "source_line_indices", "segment_bbox",
    ) if key in source}
    if not location:
        return []
    lines = ["来源定位：", ""]
    if source.get("source_spans"):
        lines += ["各区域保留各自的 PDF 文件页序和 bbox；normalized 坐标为相对页面宽高的 0–1 值。", ""]
    elif source.get("segment_bbox") is not None:
        lines += ["segment_bbox 使用原 PDF 的 point 坐标。", ""]
    return lines + [fenced(json.dumps(location, ensure_ascii=False, indent=2, allow_nan=False)), ""]


def render(report: dict, *, project_root: Path) -> str:
    lines = ["# 最近一次论文问答", "", "状态：" + code_span(report["status"]) + "。", "",
             "引用检查通过只表示来源可以定位；语义支持尚未评分。", "", "问题：", "",
             fenced(report["query"]), "", "所选论文与解析版本：", ""]
    for pair in report["selected_versions"]:
        lines += ["- " + code_span(pair["paper_id"]) + " / " + code_span(pair["parse_revision"])]
    lines += ["", "## 答案", ""]
    answer = report.get("answer")
    if answer:
        evidence_status = EVIDENCE_STATUS_LABELS.get(answer.get("evidence_status"))
        if evidence_status:
            lines += ["回答依据：" + evidence_status + "。", ""]
        if isinstance(answer.get("text"), str):
            lines += [answer["text"], ""]
            citations = answer.get("citations") or []
            if citations:
                lines += ["引用出现序：" + ", ".join(
                    f"[{row.get('ref')}] {code_span(row.get('chunk_id'))}" for row in citations
                    if isinstance(row, dict)), ""]
        else:
            for number, claim in enumerate(answer.get("claims", []), start=1):
                basis = claim.get("basis", "paper_evidence")
                lines += [f"结论 {number}（{BASIS_LABELS.get(basis, '未标注依据')}）：", "", fenced(claim["claim"]), ""]
                for quote in claim.get("evidence_quotes") or []:
                    lines += ["本项原文短引句（" + code_span(quote["chunk_id"]) + "）：", "", fenced(quote["quote"]), ""]
                ids = claim.get("citation_ids") or []
                if ids:
                    label = "分析前提引用：" if basis == "analysis" else "引用："
                    lines += [label + ", ".join(code_span(value) for value in ids), ""]
        if answer.get("reason"):
            lines += ["回答说明：", "", fenced(answer["reason"]), ""]
        if answer.get("evidence_sources"):
            lines += ["## 引用原文", ""]
        for source in answer.get("evidence_sources", []):
            version = ("；版本：" + code_span(source["arxiv_version"])) if source.get("arxiv_version") else ""
            lines += ["chunk：" + code_span(source["chunk_id"]) + "；PDF 文件页序：" + str(source["pdf_page"]) + "。", "",
                      "论文：" + escape_markdown(source.get("title", "")) + version + "。", "",
                      file_link(source["pdf_absolute_path"], "打开原 PDF") + "。", "", fenced(source["text"]), ""]
            lines += source_location_lines(source)
    else:
        lines += ["本轮没有可发布答案。", "", fenced(json.dumps(report.get("error"), ensure_ascii=False, indent=2)), ""]
    embedding = report.get("embedding_statistics") or {}
    chat = report["chat_statistics"]
    rerank = report.get("rerank_statistics") or {}
    lines += ["## 本轮用量与记录", "",
              f"问题 embedding 请求：{report['embedding_requests']}；重排请求：{report.get('rerank_requests', 0)}；聊天 HTTP 尝试：{report['llm_requests']}。", "",
              "重排耗时：" + str(rerank.get("elapsed_seconds", 0)) + " 秒。", "",
              "实际 embedding tokens：" + str(embedding.get("total_tokens")) + "；聊天 tokens：" + str(chat.get("total_tokens"))
              + "；已知聊天 tokens：" + str(chat.get("known_total_tokens")) + "。null 表示未取得完整用量。", "",
              "聊天重试：" + str(chat.get("network_retries")) + "；修复：" + str(chat.get("repairs")) + "。", "",
              "完整候选、展示证据、实际消息、原始响应、引用检查及调用记录："
              + file_link(project_root / "artifacts/d5/answer_result.json", "完整 JSON") + "。", "",
              "本轮历史：" + file_link(project_root / report["history_report"], "不可覆盖的运行 JSON") + "。", "",
              "运行 ID：" + code_span(report["run_id"]) + "。", ""]
    exported = report.get("export", {})
    if exported.get("status") == "failed":
        lines += ["导出失败步骤：" + code_span(exported.get("failed_step", "")) + "。", "",
                  "前一份历史是导出前的流程快照；导出失败终态保存在单独恢复事件中。", ""]
        if exported.get("recovery_history_report"):
            lines += ["恢复事件目标：" + file_link(project_root / exported["recovery_history_report"], "导出失败 JSON")
                      + "。若磁盘不可写，该文件可能未生成，完整失败记录以终端 JSON 为准。", ""]
    return "\n".join(lines)


def exclusive_json(path: Path, value: dict) -> None:
    """先完成临时文件，再用独占硬链接发布完整历史；已有目标永不覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
