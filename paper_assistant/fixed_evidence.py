"""One fixed-evidence preparation and one independent final generation.

This is intentionally not a general replay system: it starts from the evidence
that one saved Agent preparation request actually displayed, performs no
retrieval, and keeps the existing action parsing and citation validation.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from paper_assistant.agent_actions import (
    ActionParseError, AnswerAction, PrepareAnswerAction, action_to_answer_draft,
    parse_agent_action,
)
from paper_assistant.agent_prompt import (
    NORMAL_ANSWER_INSTRUCTION, build_fixed_final_messages, build_fixed_prepare_messages,
)
from paper_assistant.agent_runtime import load_current_profile
from paper_assistant.agent_export import render_agent_run, save_agent_run
from paper_assistant.answer_export import atomic_text
from paper_assistant.citations import validate_citations
from paper_assistant.config import load_embedding_settings, load_llm_settings
from paper_assistant.context import select_context
from paper_assistant.d9_runtime import INTERACTIVE_CHAT_POLICY
from paper_assistant.deadline import DeadlineExceeded
from paper_assistant.llm_client import ChatBudget, LLMCallError, RecordedLLM
from paper_assistant.rerank_statistics import empty_rerank_statistics
from paper_assistant.schemas import answer_evidence_status
from paper_assistant.storage import PaperStore


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "fixed_evidence_two_stage"
RUNTIME_VERSION = "v2.16-fixed-evidence-two-stage-v1"
ZERO_EMBEDDING = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}


class FixedEvidenceError(ValueError):
    """The fixed material or the two-stage output could not be used."""


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative(root, path):
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def load_fixed_material(baseline_path, store, *, project_root=ROOT):
    """Read only the old prepare request, then recover its displayed originals."""
    root = Path(project_root).resolve()
    baseline_path = Path(baseline_path).resolve()
    baseline = _json(baseline_path)
    mode = (baseline.get("pair") or {}).get("modes", {}).get("agent")
    if not isinstance(mode, dict):
        raise FixedEvidenceError("基线没有 Agent 运行模式。")
    action_step = next((step for step in mode.get("result", {}).get("action_steps", [])
                        if (step.get("parsed_action") or {}).get("action") == "prepare_answer"), None)
    if action_step is None or not action_step.get("messages"):
        raise FixedEvidenceError("基线没有可复用的 prepare_answer 请求。")
    request = _json_text(action_step["messages"][-1].get("content"), "基线准备请求")
    question = request.get("question")
    if question != baseline.get("question"):
        raise FixedEvidenceError("基线问题与准备请求不一致。")
    selected = request.get("selected_versions")
    if (not isinstance(selected, list) or len(selected) != 1
            or set(selected[0]) != {"paper_id", "parse_revision"}):
        raise FixedEvidenceError("基线准备请求的版本范围无效。")
    pair = (selected[0]["paper_id"], selected[0]["parse_revision"])
    allowed = request.get("allowed_citation_ids")
    sections = request.get("evidence_sections")
    if not isinstance(allowed, list) or not allowed or not isinstance(sections, list) or not sections:
        raise FixedEvidenceError("基线没有完整可见证据。")

    by_id, section_by_id = {}, {}
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("chunks"), list):
            raise FixedEvidenceError("基线证据分区无效。")
        for chunk in section["chunks"]:
            if not isinstance(chunk, dict) or chunk.get("chunk_id") in by_id:
                raise FixedEvidenceError("基线证据块重复或无效。")
            by_id[chunk["chunk_id"]] = chunk
            section_by_id[chunk["chunk_id"]] = section
    if set(by_id) != set(allowed):
        raise FixedEvidenceError("基线可见证据与引用权限不一致。")

    candidates = []
    for identifier in allowed:
        old, section = by_id[identifier], section_by_id[identifier]
        stored = store.get_chunk(identifier)
        if not isinstance(stored, dict) or (stored.get("paper_id"), stored.get("parse_revision")) != pair:
            raise FixedEvidenceError("基线证据块不在保存版本中。")
        if stored.get("text") != old.get("shown_text"):
            raise FixedEvidenceError("基线请求文本与保存版本不一致。")
        candidates.append({**deepcopy(stored), "rank": old.get("rank"), "score": old.get("score"),
                           "reading_origins": deepcopy(old.get("reading_origins") or []),
                           "section_path": deepcopy(section.get("section_path") or []),
                           "title": section.get("title") or stored.get("title")})

    budget = request.get("context_budget")
    if not isinstance(budget, dict) or budget.get("max_tokens") != 8192:
        raise FixedEvidenceError("基线缺少 8192 token 证据预算。")
    context = select_context(candidates, [pair], max_chars=8000, max_tokens=budget["max_tokens"])
    if context["allowed_citation_ids"] != allowed:
        raise FixedEvidenceError("固定证据顺序或引用权限发生变化。")
    context = {**context, "question": question,
               "score_kind": request.get("score_kind", "cosine"),
               "ranking_method": request.get("ranking_method", request.get("score_kind", "cosine")),
               "reading_origins": deepcopy(request.get("reading_origins") or [])}

    normal_context = {
        "conversation_id": None, "user_question": question, "standalone_question": question,
        "history": [], "referenced_evidence_ids": [],
        "answer_instructions": NORMAL_ANSWER_INSTRUCTION,
    }
    source_requirement = (request.get("conversation_context") or {}).get("source_requirement")
    return {
        "baseline": baseline, "baseline_path": _relative(root, baseline_path),
        "baseline_run_id": mode.get("run_id"), "question": question,
        "selected_versions": deepcopy(selected), "pair": pair,
        "evidence_sections": deepcopy(sections), "allowed_citation_ids": list(allowed),
        "selected_papers": deepcopy(request.get("selected_papers") or []),
        "context": context, "context_budget": {"max_tokens": budget["max_tokens"],
            "shown_tokens": context["shown_tokens"], "tokenizer": budget.get("tokenizer")},
        "conversation_context": normal_context,
        "source_requirement": deepcopy(source_requirement) if source_requirement else None,
    }


def _json_text(value, description):
    if not isinstance(value, str):
        raise FixedEvidenceError(description + "不是 JSON 文本。")
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise FixedEvidenceError(description + "不是有效 JSON。") from error
    if not isinstance(parsed, dict):
        raise FixedEvidenceError(description + "不是 JSON 对象。")
    return parsed


def _record_step(steps, phase, messages, response=None, parsed_action=None, error=None):
    step = {"phase": phase, "messages": deepcopy(messages), "response": deepcopy(response),
            "parsed_action": deepcopy(parsed_action), "error": deepcopy(error)}
    steps.append(step)
    return step


def _failure(result, status, code, message, stage):
    result.update(status=status, answer=None, failure_stage=stage, stop_reason=code,
                  error={"code": code, "message": message})
    return result


def run_two_stage(material, client, store, *, project_root=ROOT):
    """Run exactly one prepare and one final generation over fixed material."""
    question = material["question"]
    context = deepcopy(material["context"])
    selected_versions = [{"paper_id": material["pair"][0], "parse_revision": material["pair"][1]}]
    steps, checks = [], []
    result = {"status": "tool_error", "query": question, "selected_versions": selected_versions,
              "retrieval_strategy": EXPERIMENT, "prepared_answer": None, "answer": None,
              "action_steps": steps, "citation_checks": checks, "context": context,
              "failure_stage": None, "stop_reason": None, "error": None,
              "statistics": {"embedding": deepcopy(ZERO_EMBEDDING), "chat": None,
                             "rerank": empty_rerank_statistics()}}
    stage = "preparation"
    try:
        prepare_messages = build_fixed_prepare_messages(
            question, material["evidence_sections"], material["allowed_citation_ids"],
            material["selected_papers"], selected_versions=selected_versions,
            context_budget=material["context_budget"], conversation_context=material["conversation_context"],
            reading_origins=context.get("reading_origins"),
            source_requirement=material.get("source_requirement"))
        response = client.invoke(prepare_messages, purpose="answer", require_json=True)
        _record_step(steps, "fixed_evidence_preparation", prepare_messages, response)
        if response.get("status") != "success":
            return _failure(result, "invalid_output", response.get("output_issue") or "preparation_invalid",
                            "事实准备未产生完整结果", stage)
        try:
            action = parse_agent_action(response.get("content"), phase="autonomous_decision",
                has_shown_evidence=True, terminal_only=True, selected_versions=selected_versions,
                prepare_answer=True)
        except ActionParseError as error:
            return _failure(result, "invalid_output", error.code, "事实准备结构未通过检查", stage)
        if not isinstance(action, PrepareAnswerAction):
            return _failure(result, "invalid_output", "preparation_action_invalid",
                            "事实准备动作类型不符合固定证据实验", stage)
        prepared = action.model_dump(mode="json")
        allowed = set(material["allowed_citation_ids"])
        if any(not set(fact.get("citation_ids") or []).issubset(allowed)
               or any(quote.get("chunk_id") not in allowed for quote in fact.get("evidence_quotes") or [])
               for fact in prepared["facts"]):
            return _failure(result, "invalid_output", "preparation_citation_scope",
                            "事实准备引用了本次不可用的来源", stage)
        result["prepared_answer"] = prepared
        steps[-1]["parsed_action"] = deepcopy(prepared)

        stage = "final"
        final_messages = build_fixed_final_messages(
            question, context, prepared,
            prepared_messages=prepare_messages, prepared_response=response.get("content"),
            conversation_context=material["conversation_context"],
            source_requirement=material.get("source_requirement"))
        response = client.invoke(final_messages, purpose="answer", require_json=True)
        _record_step(steps, "prepared_final_decision", final_messages, response)
        if response.get("status") != "success":
            return _failure(result, "invalid_output", response.get("output_issue") or "final_invalid",
                            "最终生成未产生完整结果", stage)
        try:
            action = parse_agent_action(response.get("content"), phase="prepared_final_decision",
                has_shown_evidence=True, terminal_only=True, selected_versions=selected_versions)
        except ActionParseError as error:
            return _failure(result, "invalid_output", error.code, "最终回答结构未通过检查", stage)
        if not isinstance(action, AnswerAction):
            return _failure(result, "invalid_output", "final_action_invalid",
                            "最终动作不是完整回答", stage)
        steps[-1]["parsed_action"] = deepcopy(action.model_dump(mode="json"))
        draft = action_to_answer_draft(action).model_dump(mode="json")
        checked = validate_citations(draft, context, store, project_root=project_root)
        checks.append(deepcopy(checked))
        if checked["status"] != "valid":
            return _failure(result, checked["status"], (checked.get("error") or {}).get("code", "citation_invalid"),
                            "最终回答的引用或来源未通过检查", "citations")
        answer = {**draft, "evidence_refs": deepcopy(checked["evidence_refs"]),
                  "evidence_sources": deepcopy(checked["evidence_sources"]),
                  "evidence_status": answer_evidence_status(draft),
                  "semantic_support_status": "not_reviewed"}
        result.update(status=draft["status"], answer=answer, failure_stage=None,
                      stop_reason="fixed_evidence_" + draft["status"], error=None)
        return result
    except DeadlineExceeded:
        return _failure(result, "budget_exceeded", "deadline_exceeded", "两阶段生成超出预算", stage)
    except LLMCallError as error:
        return _failure(result, error.status, error.code, "两阶段生成调用失败", stage)
    except Exception:
        return _failure(result, "tool_error", "local_error", "固定证据两阶段执行失败", stage)
    finally:
        try:
            stats = client.budget.statistics()
            result["statistics"]["chat"] = deepcopy(stats)
            result["chat_statistics"] = deepcopy(stats)
            result["chat_attempts"] = deepcopy(client.budget.records)
            result["llm_requests"] = client.budget.http_requests
            result["network_requests"] = client.budget.http_requests
        except Exception:
            result["statistics"]["chat"] = None


def run_experiment(baseline_path, output_dir, *, project_root=ROOT):
    """Prepare the fixed run once, save its report once, and stop."""
    root = Path(project_root).resolve()
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    if output.exists():
        raise FileExistsError("输出目录已存在；请使用新的后缀目录。")
    output.mkdir(parents=True)
    baseline_path = Path(baseline_path)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    baseline = _json(baseline_path)
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12]
    report = {"task": "D9", "stage": "d9", "mode": "agent", "run_id": run_id,
              "user_question": baseline.get("question"), "standalone_question": baseline.get("question"),
              "conversation_id": None, "conversation_history": [],
              "started_at_utc": started.isoformat(), "finished_at_utc": None,
              "runtime_version": RUNTIME_VERSION, "experiment": EXPERIMENT,
              "policy": asdict(INTERACTIVE_CHAT_POLICY),
              "configuration": None, "index_profile": None,
              "strategy_binding": {"path": None, "schema_revision": "v2.16-fixed-evidence-v1"},
              "fixed_evidence_binding": None, "selected_version_metadata": [],
              "semantic_support_status": "not_reviewed", "is_answer_accuracy": False,
              "embedding_requests": 0, "rerank_requests": 0, "llm_requests": 0,
              "network_requests": 0, "chat_statistics": None, "chat_attempts": [],
              "rerank_statistics": empty_rerank_statistics(),
              "result": {"status": "tool_error", "query": baseline.get("question"),
                         "selected_versions": [], "answer": None, "error": None,
                         "failure_stage": "setup", "stop_reason": None,
                         "statistics": {"embedding": deepcopy(ZERO_EMBEDDING),
                                        "chat": None, "rerank": empty_rerank_statistics()}}}
    client = None
    try:
        with PaperStore(root / "data/index/papers.sqlite3", read_only=True) as store:
            material = load_fixed_material(baseline_path, store, project_root=root)
            paper_row = store.connection.execute(
                "SELECT paper_json FROM papers WHERE paper_id = ?", (material["pair"][0],)).fetchone()
            if paper_row is None:
                raise FixedEvidenceError("固定证据版本对应论文不存在。")
            paper = json.loads(paper_row["paper_json"])
            versions = {row["parse_revision"] for row in store.list_versions()
                        if row["paper_id"] == material["pair"][0]}
            if paper.get("page_count") is None or material["pair"][1] not in versions:
                raise FixedEvidenceError("固定证据版本未登记。")
            settings = load_llm_settings()
            embedding = load_embedding_settings()
            profile = load_current_profile(root)
            budget = ChatBudget(INTERACTIVE_CHAT_POLICY)
            client = RecordedLLM(settings, policy=INTERACTIVE_CHAT_POLICY, budget=budget)
            report["configuration"] = {
                "chat": {"provider": settings.provider, "model_id": settings.model_id,
                         "base_url": settings.base_url, "configured_timeout": settings.timeout},
                "embedding": deepcopy(profile["recipe"]),
                "policy": asdict(INTERACTIVE_CHAT_POLICY)}
            report["index_profile"] = deepcopy(profile)
            report["selected_version_metadata"] = [{
                "paper_id": paper["paper_id"], "parse_revision": material["pair"][1],
                "title": paper["title"], "page_count": paper["page_count"]}]
            report["fixed_evidence_binding"] = {
                "baseline_record": material["baseline_path"], "baseline_run_id": material["baseline_run_id"],
                "paper_id": material["pair"][0], "parse_revision": material["pair"][1],
                "evidence_ids": material["allowed_citation_ids"],
                "evidence_sections": [section.get("section_path") for section in material["evidence_sections"]],
                "scope": "exactly the complete visible evidence of that prepare_answer request; no retrieval"}
            input_record = {
                "question": material["question"], "baseline_record": material["baseline_path"],
                "paper_id": material["pair"][0], "parse_revision": material["pair"][1],
                "evidence_ids": material["allowed_citation_ids"],
                "answer_instructions": NORMAL_ANSWER_INSTRUCTION,
                "experiment": "fixed evidence two-stage; no search/read_context/embedding/rerank"}
            atomic_text(output / "input.json",
                        json.dumps(input_record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            result = run_two_stage(material, client, store, project_root=root)
            result["fixed_evidence_binding"] = deepcopy(report["fixed_evidence_binding"])
            report["result"] = result
    except Exception as error:
        report["result"].update(status="tool_error", error={"code": "fixed_evidence_setup_failed",
            "message": str(error) if isinstance(error, FixedEvidenceError) else "固定证据实验准备失败"},
            failure_stage="setup", stop_reason="fixed_evidence_setup_failed")
    finally:
        if client is not None:
            client.close()
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        stats = report["result"].get("statistics", {}).get("chat") or {}
        report["chat_statistics"] = stats
        report["chat_attempts"] = deepcopy(report["result"].get("chat_attempts") or [])
        report["llm_requests"] = report["result"].get("llm_requests") or 0
        report["network_requests"] = report["llm_requests"]
        report["rerank_statistics"] = report["result"].get("statistics", {}).get("rerank") or empty_rerank_statistics()
        safe = save_agent_run(report, project_root=root)
        safe["fixed_evidence_binding"] = deepcopy(report["fixed_evidence_binding"])
        safe["selected_version_metadata"] = deepcopy(report["selected_version_metadata"])
        atomic_text(output / "run.json",
                    json.dumps(safe, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        atomic_text(output / "run.md", render_agent_run(safe))
    return safe
