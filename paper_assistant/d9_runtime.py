"""D9 E: owned two-mode runtime, explicit frozen policy and source bindings."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from paper_assistant import agent_runtime as legacy
from paper_assistant import web_runtime
from paper_assistant.agent import answer_question_agent
from paper_assistant.agent_export import _identifier, render_agent_run, save_agent_run
from paper_assistant.agent_records import diagnostic_snapshot
from paper_assistant.config import load_embedding_settings, load_llm_settings
from paper_assistant.conversation import prepare_conversation
from paper_assistant.deadline import DeadlineExceeded, commit_result, final_deadline, preserve_expired_failure, remaining
from paper_assistant.llm_client import ChatBudget, ChatPolicy, LLMCallError, RecordedLLM
from paper_assistant.paper_information import load_paper_information
from paper_assistant.rag import answer_question
from paper_assistant.rerank_statistics import empty_rerank_statistics
from paper_assistant.source_scope import Registry

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = "artifacts/d9/runtime_config.json"
CONTRACT_PATH = "artifacts/d9/agent_config.json"
REGISTRY_PATH = "artifacts/d9/source_regions.json"
SCHEMA_VERSION = "d9-runtime-policy-v1"
RUNTIME_VERSION = "d9-owned-two-mode-runtime-v1"
MODES = ("fixed_rag", "agent")
INTERACTIVE_CHAT_POLICY = ChatPolicy(max_tokens=4096, max_attempts=None, total_timeout=None)
STATUSES = ("answered", "insufficient_evidence", "tool_error", "invalid_output", "budget_exceeded", "needs_clarification")
InvalidQuestion = legacy.InvalidQuestion
load_current_profile = legacy.load_current_profile
open_retrieval_resources = legacy.open_retrieval_resources


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_configuration_key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_configuration")))


def build_runtime_configuration(contract, **_legacy_bindings):
    """Keep only configuration consumed by the current entry and batch runner."""
    return {"schema_revision": SCHEMA_VERSION, "task": "D9", "stage": "d9",
            "runtime_version": RUNTIME_VERSION,
            "chat": deepcopy(contract["chat"]), "index_profile": deepcopy(contract["index_profile"]),
            "ready_versions": deepcopy(contract["ready_versions"]),
            "rules": {"budget": {"chat_policy": deepcopy(contract["rules"]["budget"]["chat_policy"])}}}


def load_strategy(project_root=ROOT):
    root = Path(project_root).resolve()
    strategy = _read(root / STRATEGY_PATH)
    if strategy.get("schema_revision") != SCHEMA_VERSION:
        raise ValueError("D9_runtime_configuration_mismatch")
    if strategy["rules"]["budget"]["chat_policy"] != asdict(ChatPolicy()):
        raise ValueError("D9_runtime_budget_mismatch")
    return strategy


def validate_configuration(strategy, embedding, chat, profile, policy):
    public = legacy.public_configuration(embedding, chat, profile, policy)
    if strategy["rules"]["budget"]["chat_policy"] != asdict(policy):
        raise ValueError("D9_public_configuration_mismatch")
    return public


def load_registry(project_root=ROOT, pairs=None, *, store=None):
    root = Path(project_root).resolve()
    selected = pairs if pairs is not None else [(r["paper_id"], r["parse_revision"])
                                               for r in list_ready_versions(project_root=root)]
    return Registry(root, store, selected, registry_path=REGISTRY_PATH)


def list_ready_versions(*, project_root=ROOT):
    return web_runtime.list_ready_versions(project_root=project_root)


def _failure(report, status, code, stage):
    result = report["result"]
    if preserve_expired_failure(result, status, code, "D9 本轮步骤未完成，请检查安全记录", stage):
        return
    report["pre_failure_result"] = deepcopy(result)
    result.update(status=status, answer=None, failure_stage=stage, stop_reason=code,
                  error={"code": code, "message": "D9 本轮步骤未完成，请检查安全记录"})


def run_question(query, selected_versions, *, mode="fixed_rag", project_root=ROOT,
                 submission_id=None, top_k=5, max_chars=8000, conversation_id=None, conversation_history=None,
                 library_mode=False, answer_instructions=None):
    if mode not in MODES:
        raise InvalidQuestion("模式必须为固定 RAG 或 Agent")
    pairs = legacy.validate_agent_input(query, selected_versions, top_k=top_k, max_chars=max_chars)
    token = uuid4().hex if submission_id is None else submission_id
    try:
        _identifier(token)
    except ValueError:
        raise InvalidQuestion("提交标识不合法") from None
    root = Path(project_root).resolve()
    policy = INTERACTIVE_CHAT_POLICY if library_mode else ChatPolicy()
    budget = ChatBudget(policy)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12]
    zero = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
    report = {"task": "D9", "stage": "d9", "mode": mode, "run_id": run_id, "submission_id": token,
        "conversation_id": conversation_id, "conversation_history": deepcopy(conversation_history or []),
        "user_question": query, "standalone_question": None if conversation_history or library_mode else query,
        "clarification_question": None,
        "started_at_utc": now.isoformat(), "finished_at_utc": None, "runtime_version": RUNTIME_VERSION,
        "policy": asdict(policy), "configuration": None, "index_profile": None, "strategy_binding": None,
        "registry_binding": None, "selected_version_metadata": [],
        "semantic_support_status": "not_reviewed", "is_answer_accuracy": False,
        "deadline_enforcement": ("per_request_chat_and_embedding_timeout; bounded_network_retry_repair_and_retrieval"
                                 if library_mode else
                                 "remaining_embedding_and_chat_timeout_and_stage_checks; hard_process_abort_unverified"),
        "budget_implementation_version": "d9-remaining-budget-v1",
        "result": {"status": "tool_error", "query": query,
            "selected_versions": [{"paper_id": p, "parse_revision": r} for p,r in pairs],
            "answer": None, "error": None, "failure_stage": "submission_reservation", "stop_reason": None,
            "statistics": {"embedding": deepcopy(zero), "chat": None, "rerank": empty_rerank_statistics()}}}
    pipeline_started, stage = False, "submission_reservation"
    try:
        attempt = root / "archive/run_logs/d9/submissions" / (token + ".attempt.json")
        attempt.parent.mkdir(parents=True, exist_ok=True)
        try:
            with attempt.open("x", encoding="utf-8") as f:
                json.dump({"submission_id": token, "mode": mode, "run_id": run_id,
                           "query": query, "selected_versions": pairs,
                           "automatic_rerun_allowed": False}, f, ensure_ascii=False)
        except FileExistsError:
            raise InvalidQuestion("该提交已预占或尝试；再次明确提交才会建立新运行") from None
        stage = "input_verification"
        strategy = load_strategy(root)
        report["strategy_binding"] = {"path": STRATEGY_PATH, "schema_revision": strategy["schema_revision"]}
        if not library_mode:
            ready = {(r["paper_id"],r["parse_revision"]) for r in strategy["ready_versions"] if r["status"] == "ready"}
            if not set(pairs).issubset(ready):
                raise ValueError("selected_versions_outside_D9_scope")
        remaining(budget.remaining_seconds)
        stage = "configuration"
        embedding, chat = load_embedding_settings(), load_llm_settings()
        profile = load_current_profile(root)
        report["configuration"] = (legacy.public_configuration(embedding, chat, profile, policy) if library_mode else
                                   validate_configuration(strategy, embedding, chat, profile, policy))
        report["index_profile"] = deepcopy(profile)
        remaining(budget.remaining_seconds)
        stage = "resources"
        with ExitStack() as resources:
            store, searcher = resources.enter_context(open_retrieval_resources(root, embedding, profile))
            if library_mode:
                ready = {(row["paper_id"], row["parse_revision"]): row
                         for row in web_runtime._ready_versions(store, profile)}
                if any(pair not in ready for pair in pairs):
                    raise InvalidQuestion("所选论文与解析版本在当前索引下尚未完整入库")
                report["selected_version_metadata"] = [deepcopy(ready[pair]) for pair in pairs]
            registry = load_registry(root, pairs, store=store)
            report["registry_binding"] = {"path": REGISTRY_PATH}
            remaining(budget.remaining_seconds)
            client = resources.enter_context(RecordedLLM(chat, policy=policy, budget=budget))
            stage = "conversation_preparation"
            preparation = report["conversation_preparation"] = {}
            # 统一页面首问也规划；CLI／对照实验保留原有准备和调用次数。
            paper_information = load_paper_information(store, pairs, registry) if library_mode else None
            conversation = prepare_conversation(query, report["conversation_history"], client,
                conversation_id=conversation_id, selected_versions=report["result"]["selected_versions"],
                paper_information=paper_information, plan_queries=library_mode, record=preparation)
            if answer_instructions:
                conversation["answer_instructions"] = answer_instructions
            report["standalone_question"] = conversation["standalone_question"]
            report["clarification_question"] = conversation["clarification_question"]
            if library_mode:
                report["planned_queries"] = deepcopy(conversation["planned_queries"])
            if conversation["clarification_question"]:
                report["result"].update(status="needs_clarification", failure_stage=None,
                    stop_reason="clarification_required", clarification_question=conversation["clarification_question"])
            else:
                stage, pipeline_started = "pipeline", True
                report["result"]["statistics"]["embedding"] = None
                core = answer_question_agent if mode == "agent" else answer_question
                conversation_kwargs = {"conversation_context": conversation} if library_mode or report["conversation_history"] or answer_instructions else {}
                if library_mode and mode == "agent":
                    conversation_kwargs["autonomous_steps"] = 5
                report["result"] = deepcopy(core(conversation["standalone_question"], pairs, searcher, store, client,
                    project_root=root, top_k=top_k, max_chars=max_chars, source_registry=registry,
                    enforce_remaining_budget=True, **conversation_kwargs))
            if mode == "fixed_rag" and not report["result"].get("stop_reason"):
                status = report["result"].get("status")
                if status in ("answered", "insufficient_evidence"):
                    report["result"]["stop_reason"] = ("fixed_citations_valid" if status == "answered"
                                                        else "fixed_model_insufficient_evidence")
                elif isinstance(report["result"].get("error"), dict):
                    report["result"]["stop_reason"] = report["result"]["error"].get("code")
            if report["result"].get("status") not in STATUSES:
                _failure(report, "tool_error", "unexpected_status", stage)
            stage = "resource_cleanup"
    except InvalidQuestion:
        if stage == "submission_reservation":
            raise
        _failure(report, "tool_error", "runtime_input_error", stage)
    except DeadlineExceeded:
        _failure(report, "budget_exceeded", "deadline_exceeded", stage)
    except LLMCallError as error:
        _failure(report, error.status, error.code, stage)
    except Exception:
        _failure(report, "tool_error", "local_error", stage)
    final_deadline(report["result"], budget, stage)
    embedding_stats = report["result"].setdefault("statistics", {}).get("embedding")
    report["embedding_statistics"] = deepcopy(embedding_stats)
    report["embedding_requests"] = (embedding_stats.get("embedding_requests") if isinstance(embedding_stats, dict)
                                      else None if pipeline_started else 0)
    report["rerank_statistics"] = deepcopy(report["result"]["statistics"].get("rerank")
                                           or empty_rerank_statistics())
    report["rerank_requests"] = report["rerank_statistics"]["requests"]
    report["chat_statistics"] = deepcopy(budget.statistics())
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["sdk_request_attempts"] = budget.attempts
    report["network_requests"] = (report["embedding_requests"] + budget.http_requests + report["rerank_requests"]
                                   if type(report["embedding_requests"]) is int else None)
    report["result"]["statistics"]["chat"] = deepcopy(report["chat_statistics"])
    commit_result(report["result"], budget, "resource_cleanup")
    report["business_commit"] = deepcopy(report["result"]["business_commit"])
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report.update({key: deepcopy(report["result"].get(key)) for key in
                   ("status", "query", "selected_versions", "answer", "error", "failure_stage", "stop_reason")})
    safe, replacements = diagnostic_snapshot(report)
    if replacements:
        safe["diagnostic_replacements"] = replacements
    try:
        return save_agent_run(safe, project_root=root)
    except Exception:
        safe["pre_export_result"] = deepcopy(safe["result"])
        _failure(safe, "tool_error", "export_error", "export")
        safe.update(status="tool_error", answer=None, error=deepcopy(safe["result"]["error"]),
                    failure_stage="export", stop_reason=safe["result"]["stop_reason"])
        safe.setdefault("history_report", None)
        safe.setdefault("history_markdown", None)
        safe["export"] = {"status": "failed", "failed_step": "export_setup", "recovery_saved": False}
        return safe


def download_payloads(report, *, project_root=ROOT):
    if isinstance(report, dict) and report.get("task") == "D6-D-web-answer-question":
        return web_runtime.download_payloads(report, project_root=project_root)
    if (not isinstance(report, dict) or report.get("task") != "D9" or report.get("mode") not in MODES
            or report.get("status") not in STATUSES or not isinstance(report.get("result"), dict)):
        raise ValueError("invalid_D9_session_report")
    return ((json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
            render_agent_run(report).encode("utf-8"))
