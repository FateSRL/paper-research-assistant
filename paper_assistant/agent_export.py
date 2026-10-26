"""D8/D9: immutable mode records and export failure recovery.

No retrieval, model call, environment loading or resource ownership here.
The history JSON is a pre-export snapshot; a failed export creates a separate
recovery event. Stages and modes have separate history/latest paths.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from paper_assistant.answer_export import BASIS_LABELS, EVIDENCE_STATUS_LABELS, atomic_text, code_span, exclusive_json, fenced, source_location_lines


AGENT_EXPORT_VERSION = "d8-immutable-mode-records-v2"
D9_AGENT_EXPORT_VERSION = "d9-immutable-mode-records-v1"
_STATUSES = {"answered", "insufficient_evidence", "tool_error", "invalid_output", "budget_exceeded", "needs_clarification"}


class AgentExportError(ValueError):
    def __init__(self, code):
        super().__init__("运行记录参数或目录不合法，请核对安全错误代码")
        self.code = code


def _identifier(value):
    if (type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value)
            or value.endswith(".") or value.split(".")[0].casefold() in
            {"con", "prn", "aux", "nul", *("com" + str(n) for n in range(1, 10)),
             *("lpt" + str(n) for n in range(1, 10))}):
        raise AgentExportError("invalid_record_id")
    return value


def _path(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise AgentExportError("record_path_outside_project")
    return path


def _exclusive_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _terminal_fields(report):
    result = report["result"]
    report.update({key: deepcopy(result.get(key)) for key in
                   ("status", "query", "selected_versions", "answer", "error", "failure_stage", "stop_reason")})


def validate_stage(stage):
    if type(stage) is not str or stage not in ("d8", "d9"):
        raise AgentExportError("invalid_stage")
    return stage


def reserve_agent_batch(project_root: Path, batch_id: str, manifest: dict, *, stage="d8") -> Path:
    """Reserve once before any paid work; partial failures remain for inspection."""
    root = Path(project_root).resolve()
    stage = validate_stage(stage)
    identifier = _identifier(batch_id)
    if not isinstance(manifest, dict):
        raise AgentExportError("invalid_batch_manifest")
    _json(manifest)  # Reject unrecordable input before creating a directory.
    path = _path(root, "artifacts/" + stage + "/comparison/" + identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        raise AgentExportError("batch_exists") from None
    exclusive_json(path / "manifest.json", deepcopy(manifest))
    return path


def render_agent_run(report: dict) -> str:
    """Render only the program result; paper text and model text stay in fences."""
    result = report["result"]
    if report["task"] == "D9" and report.get("status", result["status"]) not in ("answered", "insufficient_evidence"):
        # Render a safe view without rewriting nested results or diagnostic JSON.
        result = deepcopy(result)
        result.update(status=report.get("status", result["status"]), answer=None,
                      error=deepcopy(report.get("error", result.get("error"))),
                      stop_reason=report.get("stop_reason", result.get("stop_reason")))
    lines = ["# " + report["task"] + " 问答运行记录", "", "模式：" + code_span(report["mode"]) + "。", "",
             "运行 ID：" + code_span(report["run_id"]) + "。", "",
             "状态：" + code_span(result["status"]) + "；停止原因：" + code_span(result.get("stop_reason")) + "。", "",
             "引用定位通过不代表答案语义准确；语义支持尚未评分。", ""]
    if "user_question" in report or "standalone_question" in report:
        if report.get("conversation_id"):
            lines += ["会话 ID：" + code_span(report["conversation_id"]) + "。", ""]
        unresolved = ("尚待澄清，未形成完整问题。" if result["status"] == "needs_clarification"
                      else "本轮未形成完整问题。")
        standalone = (report["standalone_question"] if "standalone_question" in report else result.get("query"))
        lines += ["用户原问题：", "", fenced(report.get("user_question") or result.get("query") or "[invalid question]"), "",
                  "本轮完整问题：", "", fenced(standalone or unresolved), ""]
        if report.get("conversation_history"):
            lines += ["本轮使用的近期历史：", "", fenced(_json(report["conversation_history"])), ""]
    else:
        lines += ["问题：", "", fenced(result.get("query") or "[invalid question]"), ""]
    lines += ["## 答案", ""]
    answer = result.get("answer")
    if result["status"] in ("answered", "insufficient_evidence") and isinstance(answer, dict):
        evidence_status = EVIDENCE_STATUS_LABELS.get(answer.get("evidence_status"))
        if evidence_status:
            lines += ["回答依据：" + evidence_status + "。", ""]
        for number, claim in enumerate(answer.get("claims", []), 1):
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
        for source in answer.get("evidence_sources", []):
            if source.get("title"):
                lines += ["论文标题：", "", fenced(source["title"]), ""]
            if source.get("paper_id") or source.get("parse_revision"):
                lines += ["论文 / 解析版本：" + code_span(source.get("paper_id")) + " / "
                          + code_span(source.get("parse_revision")) + "。", ""]
            if source.get("arxiv_version"):
                lines += ["arXiv 版本：" + code_span(source["arxiv_version"]) + "。", ""]
            lines += ["chunk：" + code_span(source["chunk_id"]) + "；PDF 文件页序：" + str(source["pdf_page"]) + "。", "",
                      fenced(source["text"]), ""]
            lines += source_location_lines(source)
    elif result["status"] == "needs_clarification":
        lines += ["请补充说明：", "", fenced(result.get("clarification_question") or report.get("clarification_question")), ""]
    else:
        lines += ["本轮没有可发布答案。", "", fenced(_json(result.get("error"))), ""]
    lines += ["## 配置与版本", "", fenced(_json({
        "selected_versions": result.get("selected_versions"),
        "configuration": report.get("configuration"), "policy": report.get("policy"),
        "index_profile": report.get("index_profile"), "strategy_binding": report.get("strategy_binding"),
        "source_registry_binding": report.get("source_registry_binding"),
        "initial_contract_binding": report.get("initial_contract_binding"),
        "versions": {key: report.get(key, result.get(key)) for key in
                     ("agent_version", "rag_version", "prompt_version", "selection_version", "action_schema_version")},
        "source_sha256": report.get("source_sha256"),
    })), ""]
    if report["task"] == "D9":
        lines += ["## 来源范围与提交", "", fenced(_json({
            "source_requirement": result.get("source_requirement"),
            "required_source_scope": report.get("required_source_scope", result.get("required_source_scope")),
            "registry_sha256": report.get("registry_sha256", result.get("registry_sha256")),
            "source_qualification": result.get("source_qualification"),
            "initial_source_qualification": result.get("initial_source_qualification"),
            "source_scope_checks": result.get("source_scope_checks"),
            "business_commit": report.get("business_commit", result.get("business_commit")),
        })), ""]
    autonomous = result.get("retrieval_strategy") == "autonomous"
    fixed = result.get("retrieval_strategy") == "fixed_evidence_two_stage"
    if fixed:
        lines += ["## 固定证据两阶段", "",
                  "本实验从基线准备请求实际展示的证据开始；未运行检索、embedding、重排或审核。", ""]
        for number, step in enumerate(result.get("action_steps") or [], 1):
            label = "事实准备" if step.get("phase") == "fixed_evidence_preparation" else "独立最终生成"
            lines += [f"### 阶段 {number}：{label}", "", fenced(_json({
                key: step.get(key) for key in ("phase", "messages", "response", "parsed_action", "error")
            })), ""]
    if autonomous:
        lines += ["## 自主决策", "",
                  "自主步数：" + str(result.get("autonomous_steps_used")) + " / "
                  + str(result.get("autonomous_step_limit")) + "。", "",
                  "触顶收尾：" + ("是" if result.get("limit_finalize") is True else "否") + "。", ""]
        for step in result.get("action_steps") or []:
            if not isinstance(step, dict):
                continue
            label = ("触顶收尾" if step.get("limit_finalize") is True else
                     "自主步骤 " + str(step.get("autonomous_step")))
            if step.get("repair_kind"):
                label += "（修复）"
            lines += ["### " + label, "", fenced(_json({
                key: step.get(key) for key in ("autonomous_step", "remaining_steps", "limit_finalize",
                                               "repair_kind", "parsed_action", "tool_observation", "tool_calls")
            })), ""]
    plan = result.get("planned_queries", report.get("planned_queries"))
    if isinstance(plan, list) and plan:
        lines += ["## 建议查询（模型可调整或跳过）" if autonomous else "## 检索计划",
                  "", fenced(_json(plan)), ""]
    rounds = result.get("search_rounds")
    planned = result.get("retrieval_strategy") == "planned_queries"
    if isinstance(rounds, list) and rounds:
        lines += ["## 检索过程", ""]
        for number, row in enumerate(rounds, 1):
            if not isinstance(row, dict):
                continue
            search = row.get("search") or {}
            adaptive = autonomous or row.get("kind") == "adaptive"
            label = (f"自适应取证 {number}" if adaptive else
                     f"计划查询 {number}" if planned or row.get("kind") == "planned"
                     else "初次查询" if row.get("round") == 1 else "补查查询")
            trajectory = {
                "query": row.get("query"),
                "selected_versions": row.get("selected_versions", search.get("selected_versions")),
                "status": row.get("status"),
                "results": search.get("results"),
                "statistics": row.get("statistics", search.get("statistics")),
                "rerank_statistics": row.get("rerank_statistics", search.get("rerank_statistics")),
                "ranking_method": search.get("ranking_method"),
                "error": row.get("error", search.get("error")),
            }
            if adaptive:
                trajectory.update(autonomous_step=row.get("autonomous_step"), observation=row.get("observation"))
            lines += ["### " + label, "", fenced(_json(trajectory)), ""]
    if planned or autonomous:
        context = result.get("context") or {}
        lines += ["## 合并后的最终来源", "", fenced(_json(context.get("shown_evidence") or [])), "",
                  "## 停止与合并", "", "停止原因：" + code_span(result.get("stop_reason")) + "。", ""]
    else:
        retry = result.get("retry_decision")
        lines += ["## 补查与停止", "", fenced(_json(retry)), ""]
    trace = result.get("merge_trace") or {}
    trace_keys = (("final_shown_ids",) if planned else
                  ("new_returned_ids", "new_shown_ids", "initial_returned_unshown_now_shown_ids", "final_shown_ids"))
    for key in trace_keys:
        lines += [code_span(key) + "：" + code_span(trace.get(key, [])), ""]
    rerank = report.get("rerank_statistics") or (result.get("statistics") or {}).get("rerank") or {}
    lines += ["## 用量", "",
              "重排请求：" + str(report.get("rerank_requests", rerank.get("requests", 0)))
              + "；重排耗时：" + str(rerank.get("elapsed_seconds", 0)) + " 秒。", "",
              fenced(_json(result.get("statistics"))), "",
              "null 表示未取得完整用量；SDK 尝试、HTTP 尝试、重试和修复分别记录。", "",
              "完整消息、响应、检索证据及引用检查保存在 JSON。", "",
              "历史 JSON：" + code_span(report["history_report"]) + "。", ""]
    if report.get("export", {}).get("status") == "failed":
        lines += ["导出失败步骤：" + code_span(report["export"].get("failed_step")) + "。", "",
                  "原历史为导出前快照；原结果和费用保留在独立恢复事件中。", ""]
    return "\n".join(lines)


def save_agent_run(report: dict, *, project_root: Path) -> dict:
    """Save stage-specific history/latest with explicit export outcome.

    Expected input: {task: D8|D9, mode: agent|fixed_rag, run_id: safe ID, result: core result}.
    Duplicate history is never overwritten. All consumed calls remain in the
    returned record even if the disk is completely unwritable.
    """
    if (not isinstance(report, dict) or report.get("task") not in ("D8", "D9") or report.get("mode") not in ("agent", "fixed_rag")
            or not isinstance(report.get("result"), dict) or report["result"].get("status") not in _STATUSES):
        raise AgentExportError("invalid_agent_report")
    saved = deepcopy(report)
    _terminal_fields(saved)
    identifier = _identifier(saved.get("run_id"))
    root = Path(project_root).resolve()
    mode = saved["mode"]
    record_stage = saved["task"].lower()
    history_rel = "archive/run_logs/" + record_stage + "/" + mode + "_" + identifier + ".json"
    history = _path(root, history_rel)
    markdown = _path(root, history_rel[:-5] + ".md")
    latest_json = _path(root, "artifacts/" + record_stage + "/" + mode + "_result.json")
    latest_md = _path(root, "artifacts/" + record_stage + "/" + mode + "_result.md")
    saved.update(history_report=history_rel, history_markdown=history_rel[:-5] + ".md",
                 export_version=D9_AGENT_EXPORT_VERSION if record_stage == "d9" else AGENT_EXPORT_VERSION,
                 export={"status": "prepared", "failed_step": None, "recovery_history_report": None})
    stage, collision = "record_validation", False
    try:
        result = saved["result"]
        if result["status"] not in ("answered", "insufficient_evidence") and result.get("answer") is not None:
            raise AgentExportError("failure_has_answer")
        if history.exists() or markdown.exists():
            collision = True
            stage = "history_reservation"
            raise FileExistsError("immutable history exists")
        stage = "history_json"
        exclusive_json(history, saved)
        stage = "render"
        text = render_agent_run(saved)
        stage = "history_markdown"
        _exclusive_text(markdown, text)
        stage = "latest_markdown"
        atomic_text(latest_md, text)
        saved["export"]["status"] = "completed"
        stage = "latest_json"
        atomic_text(latest_json, _json(saved))
        return saved
    except Exception as exception:
        if isinstance(exception, FileExistsError) and stage in ("history_json", "history_markdown", "history_reservation"):
            collision = True
        original = deepcopy(saved["result"])
        saved["pre_export_result"] = original
        error = {"code": "history_exists" if collision else "export_error",
                 "message": saved["task"] + " 运行记录导出未完成，原调用与用量保留在失败记录中"}
        saved["result"].update(status="tool_error", answer=None, error=error,
                               failure_stage="export", stop_reason=error["code"])
        _terminal_fields(saved)
        recovery_rel = "archive/run_logs/" + record_stage + "/" + mode + "_" + identifier + "_export_failure_" + uuid4().hex + ".json"
        saved["export"] = {"status": "failed", "failed_step": stage,
                           "recovery_history_report": recovery_rel, "recovery_saved": False,
                           "latest_recovery_saved": False}
        try:
            recovery = _path(root, recovery_rel)
            event = deepcopy(saved)
            event["export"]["recovery_saved"] = True
            exclusive_json(recovery, event)
            saved["export"]["recovery_saved"] = True
        except Exception:
            pass
        # A duplicate run must not replace the previous latest record either.
        if not collision:
            try:
                atomic_text(latest_md, render_agent_run(saved))
                saved["export"]["latest_recovery_saved"] = True
                atomic_text(latest_json, _json(saved))
            except Exception:
                saved["export"]["latest_recovery_saved"] = False
        return saved
