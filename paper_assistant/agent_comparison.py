"""D8 E: paired execution with one measured first retrieval and separate budgets."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import monotonic
from uuid import uuid4

from paper_assistant.agent import answer_question_agent
from paper_assistant.agent_context import validate_search_round
from paper_assistant.agent_records import diagnostic_snapshot
from paper_assistant.agent_runtime import validate_agent_input
from paper_assistant.llm_client import ChatBudget, ChatPolicy
from paper_assistant.rag import answer_question
from paper_assistant.rerank_statistics import empty_rerank_statistics, sum_rerank_statistics
from paper_assistant.search import SearchError, validate_allowed_point_ids
from paper_assistant.deadline import DeadlineExceeded, commit_result, preserve_expired_failure, remaining, search_with_budget


COMPARISON_VERSION = "d8-shared-first-paired-v1"
SCOPED_COMPARISON_VERSION = "d9-source-budget-paired-v1"
TIMED_COMPARISON_VERSION = "d9-budget-paired-v1"
CURRENT_COMPARISON_VERSION = "v2-current-independent-runtime-v1"
MODES = ("fixed_rag", "agent")
NORMAL = ("answered", "insufficient_evidence")


def _safe(value):
    return diagnostic_snapshot(value)[0]


def aggregate_usage(rows, fields):
    """Unknown components remain null, while known subtotals are explicit."""
    totals = {}
    for field in fields:
        values = [row.get(field) if isinstance(row, dict) else None for row in rows]
        valid = [type(v) is int and v >= 0 for v in values]
        totals[field] = sum(values) if all(valid) else None
        totals["known_" + field] = sum(v if ok else
            (row.get("known_" + field, 0) if isinstance(row, dict)
             and type(row.get("known_" + field, 0)) is int and row.get("known_" + field, 0) >= 0 else 0)
            for row, v, ok in zip(rows, values, valid))
    totals["components"] = len(rows)
    return totals


def _current_timing_totals(rows, fields):
    totals = {}
    for field in fields:
        values = [row.get(field) if isinstance(row, dict) else None for row in rows]
        valid = [type(value) in (int, float) and isfinite(value) and value >= 0 for value in values]
        totals[field] = round(sum(values), 6) if all(valid) else None
        totals["known_" + field] = round(sum(value if ok else
            (row["known_" + field] if isinstance(row, dict)
             and type(row.get("known_" + field)) in (int, float)
             and isfinite(row["known_" + field]) and row["known_" + field] >= 0 else 0)
            for row, value, ok in zip(rows, values, valid)), 6)
    return totals


def _current_rerank_tokens(statistics):
    """Runtime rerank totals retain provider usage on their actual leaf rounds."""
    if not isinstance(statistics, dict):
        return {"total_tokens": None, "known_total_tokens": 0}
    if "rounds" in statistics:
        rows = [_current_rerank_tokens(row) for row in statistics["rounds"]
                if row.get("requests") != 0]
        if rows:
            return aggregate_usage(rows, ("total_tokens",))
    usage = statistics.get("usage")
    return {"total_tokens": usage.get("total_tokens") if isinstance(usage, dict) else None}


def _current_report_costs(report):
    statistics = report.get("result", {}).get("statistics", {})
    embedding = report.get("embedding_statistics", statistics.get("embedding"))
    chat = report.get("chat_statistics", statistics.get("chat"))
    rerank = report.get("rerank_statistics", statistics.get("rerank"))
    return {"embedding": embedding, "chat": chat,
            "rerank": {**(rerank or {}), **_current_rerank_tokens(rerank)},
            "runtime": {"network_requests": report.get("network_requests"),
                        "measured_runtime_elapsed_seconds": report.get("measured_runtime_elapsed_seconds")}}


def _sum_current_report_costs(reports):
    costs = [_current_report_costs(report) for report in reports]
    groups = {name: [cost[name] for cost in costs] for name in ("embedding", "chat", "rerank", "runtime")}
    return {
        "embedding": {
            **aggregate_usage(groups["embedding"], ("embedding_requests", "failed_requests", "total_tokens")),
            **_current_timing_totals(groups["embedding"], ("provider_elapsed_seconds", "embedding_elapsed_seconds",
                                                          "query_elapsed_seconds", "total_elapsed_seconds"))},
        "chat": {
            **aggregate_usage(groups["chat"], ("sdk_request_attempts", "http_request_attempts", "network_retries",
                                               "repairs", "total_tokens")),
            **_current_timing_totals(groups["chat"], ("elapsed_seconds",))},
        "rerank": {
            **aggregate_usage(groups["rerank"], ("requests", "total_tokens")),
            **_current_timing_totals(groups["rerank"], ("elapsed_seconds",))},
        "runtime": {
            **aggregate_usage(groups["runtime"], ("network_requests",)),
            **_current_timing_totals(groups["runtime"], ("measured_runtime_elapsed_seconds",))},
    }


def summarize_current_costs(pairs, *, modes=None):
    """Add independent runtime ledgers, including failures and unknown usage."""
    selected_modes = MODES if modes is None else tuple(modes)
    by_mode = {mode: [pair["modes"][mode] for pair in pairs if mode in pair.get("modes", {})]
               for mode in selected_modes}
    return {"actual_batch": _sum_current_report_costs([report for rows in by_mode.values() for report in rows]),
            "per_mode": {mode: _sum_current_report_costs(rows) for mode, rows in by_mode.items()},
            "interpretation": "independent current runtime calls; no shared retrieval deduction; unknown usage remains null"}


def run_current_case(question, selected_versions, *, project_root, runtime_runner=None, on_mode_result=None,
                     modes=None, answer_instructions=None):
    """Run selected modes sequentially; each runtime owns and saves its run."""
    selected_modes = MODES if modes is None else tuple(modes)
    if runtime_runner is None:
        from paper_assistant.d9_runtime import run_question
        runtime_runner = run_question
    pair = {"pipeline": "current", "comparison_version": CURRENT_COMPARISON_VERSION,
            "pair_id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8],
            "status": "completed", "error": None, "selected_modes": list(selected_modes), "modes": {}}
    for mode in selected_modes:
        started = monotonic()
        try:
            report = runtime_runner(question, deepcopy(selected_versions), mode=mode,
                                    project_root=project_root, library_mode=True,
                                    **({"answer_instructions": answer_instructions} if answer_instructions else {}))
        except Exception:
            result = _failure(question, selected_versions, "tool_error", "current_runtime_error", "runtime", task="V2")
            result["statistics"]["rerank"] = None
            report = {"mode": mode, "status": result["status"], "result": result,
                      "error": deepcopy(result["error"]), "failure_stage": "runtime",
                      "stop_reason": result["stop_reason"]}
        report["measured_runtime_elapsed_seconds"] = round(max(0, monotonic() - started), 6)
        pair["modes"][mode] = report
        if on_mode_result is not None:
            on_mode_result(mode, report)
    failures = [pair["modes"][mode]["status"] for mode in selected_modes if pair["modes"][mode]["status"] not in NORMAL]
    pair["status"] = ("budget_exceeded" if "budget_exceeded" in failures else failures[0]) if failures else "completed"
    pair["costs"] = summarize_current_costs([pair], modes=selected_modes)
    return pair


class FrozenFirstSearcher:
    """Replay an isolated validated snapshot once; permit one Agent live retry."""

    supports_remaining_time = True

    def __init__(self, snapshot, query, selected_versions, live_searcher, *, allow_retry=False):
        validate_search_round(snapshot, query, selected_versions, top_k=5, max_chars=8000)
        if snapshot.get("allowed_point_ids") is not None:
            raise SearchError("Frozen first retrieval must use the original unfiltered scope", stage="scope")
        self.snapshot = deepcopy(snapshot)
        self.query, self.pairs = query, [tuple(pair) for pair in selected_versions]
        self.live_searcher, self.allow_retry = live_searcher, allow_retry
        self.calls = 0
        self.actual_retry_rounds = []

    def search_evidence(self, query, selected_versions, top_k=5, *, allowed_point_ids=None, remaining_seconds=None):
        remaining(remaining_seconds)
        pairs = [tuple(pair) for pair in selected_versions]
        error_statistics = {} if allowed_point_ids is None else None
        if pairs != self.pairs or type(top_k) is not int or top_k != 5:
            raise SearchError("Frozen retrieval scope differs", stage="scope", statistics=error_statistics)
        if self.calls == 0:
            if allowed_point_ids is not None:
                raise SearchError("Frozen first replay cannot apply a point filter", stage="scope")
            if query != self.query:
                raise SearchError("Frozen retrieval question differs", stage="scope", statistics={})
            self.calls += 1
            return deepcopy(self.snapshot)
        if not self.allow_retry or self.calls >= 2:
            raise SearchError("Frozen retrieval round limit", stage="scope", statistics=error_statistics)
        point_ids = validate_allowed_point_ids(allowed_point_ids)
        self.calls += 1
        row = {"query": query, "statistics": None, "rerank_statistics": empty_rerank_statistics(),
               "search": None, "error": None}
        if point_ids is not None:
            row["allowed_point_ids"] = deepcopy(point_ids)
        self.actual_retry_rounds.append(row)
        try:
            options = {} if point_ids is None else {"allowed_point_ids": deepcopy(point_ids)}
            raw = search_with_budget(self.live_searcher, query, self.pairs, top_k=5,
                                     remaining_seconds=remaining_seconds, **options)
            row["search"] = _safe(raw)
            row["statistics"] = _safe(raw.get("statistics")) if isinstance(raw, dict) else None
            row["rerank_statistics"] = deepcopy(raw.get("rerank_statistics") or empty_rerank_statistics()) if isinstance(raw, dict) else empty_rerank_statistics()
            return raw
        except Exception as error:
            row["statistics"] = _safe(error.statistics) if isinstance(error, SearchError) else None
            row["rerank_statistics"] = deepcopy(getattr(error, "rerank_statistics", empty_rerank_statistics()))
            row["error"] = {"code": "retrieval_error", "stage": "retry"}
            raise


def _failure(query, pairs, status, code, stage, *, embedding=None, rerank=None, task="D8"):
    return {"status": status, "query": query if isinstance(query, str) else None,
            "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in pairs],
            "answer": None, "search": None, "context": None, "failure_stage": stage,
            "stop_reason": code, "error": {"code": code, "message": task + " 成对运行在该步骤停止，请检查记录"},
            "statistics": {"embedding": deepcopy(embedding), "chat": None,
                           "rerank": deepcopy(rerank) if rerank is not None else empty_rerank_statistics()}}


def _replace_failure(report, status, code, stage):
    if preserve_expired_failure(report["result"], status, code, "成对收尾步骤失败", stage):
        return
    report["pre_failure_result"] = deepcopy(report["result"])
    result = report["result"]
    result.update(status=status, answer=None, stop_reason=code, failure_stage=stage,
                  error={"code": code, "message": report["task"] + " 成对运行在该步骤停止，请检查记录"})


def run_paired_case(question, selected_versions, searcher, store, client_factory, *,
                    project_root: Path, policy=None, clock=monotonic, source_registry=None, enforce_remaining_budget=False):
    """Caller owns retrieval resources; each created chat client closes here.

    Expected labels and case IDs are never accepted here.
    A source registry is passed explicitly to both cores; None preserves the
    original D8 call signature and evidence behavior.
    """
    timed = bool(enforce_remaining_budget or source_registry is not None)
    policy = policy or ChatPolicy()
    task = "D9" if timed else "D8"
    comparison_version = SCOPED_COMPARISON_VERSION if source_registry is not None else (TIMED_COMPARISON_VERSION if timed else COMPARISON_VERSION)
    registry_sha256, required_source_scope = None, None
    pair_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]
    pair = {"task": task, "comparison_version": comparison_version, "pair_id": pair_id,
            "status": "tool_error", "error": None, "modes": {},
            "shared_first_retrieval": {"search": None, "statistics": None, "elapsed_seconds": 0,
                                       "rerank_statistics": empty_rerank_statistics(),
                                       "error": None, "actual_search_calls": 0}, "costs": None}
    pairs, shared_failure = [], None
    source_requirement, source_stop = None, None
    shared = pair["shared_first_retrieval"]
    try:
        pairs = validate_agent_input(question, selected_versions)
        if policy.total_timeout > 120 or policy.request_timeout > 30:
            raise ValueError("D8 policy limit")
    except Exception:
        shared_failure = ("tool_error", "invalid_paired_input", "input")
        if timed:
            shared["statistics"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
    if shared_failure is None:
        first_started = clock()
        shared_budget = ChatBudget(policy, clock=clock, deadline=first_started + policy.total_timeout)
        try:
            if source_registry is not None:
                from paper_assistant.source_scope import Registry, identify_source_requirement

                if not isinstance(source_registry, Registry):
                    raise ValueError("source registry must be the validated concrete registry")
                source_requirement = identify_source_requirement(question)
                required_source_scope = source_requirement["required_scope"]
                shared["source_requirement"] = _safe(source_requirement)
                registry_sha256 = source_registry.registry_sha256
                if not set(pairs).issubset({tuple(pair) for pair in source_registry.pairs}):
                    raise ValueError("source registry does not cover the selected pairs")
                if source_requirement["resolution"] == "ambiguous":
                    source_stop = "source_constraint_ambiguous"
                elif (source_requirement["required_scope"] == "abstract"
                      and not source_registry.has_qualified_abstract(pairs=pairs)):
                    source_stop = "source_scope_unavailable"
                if source_stop:
                    shared["program_stop"] = source_stop
                    shared["statistics"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
            if shared_failure is None and source_stop is None:
                if timed:
                    remaining(shared_budget.remaining_seconds)
                shared["actual_search_calls"] = 1
                raw = search_with_budget(searcher, question, pairs, top_k=5,
                                         remaining_seconds=shared_budget.remaining_seconds if timed else None)
                shared["search"] = _safe(raw)
                shared["statistics"] = _safe(raw.get("statistics")) if isinstance(raw, dict) else None
                shared["rerank_statistics"] = deepcopy(raw.get("rerank_statistics") or empty_rerank_statistics()) if isinstance(raw, dict) else empty_rerank_statistics()
                validate_search_round(raw, question, pairs, top_k=5, max_chars=8000)
        except Exception as error:
            if isinstance(error, SearchError):
                shared["statistics"] = _safe(error.statistics)
                shared["rerank_statistics"] = deepcopy(getattr(error, "rerank_statistics", empty_rerank_statistics()))
            if timed and not shared["actual_search_calls"]:
                shared["statistics"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
            if isinstance(error, DeadlineExceeded):
                shared["statistics"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
                shared_failure = ("budget_exceeded", "shared_deadline_exceeded", "shared_retrieval")
            elif source_registry is not None and not shared["actual_search_calls"]:
                shared["statistics"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
                shared_failure = ("tool_error", "source_preflight_error", "source_scope")
            else:
                shared_failure = ("tool_error", "shared_retrieval_error", "shared_retrieval")
        shared["elapsed_seconds"] = max(0, clock() - first_started)
        if shared["elapsed_seconds"] >= policy.total_timeout:
            if shared_failure and shared_failure[0] != "budget_exceeded":
                shared["interrupted_failure"] = {"status": shared_failure[0], "code": shared_failure[1], "stage": shared_failure[2]}
            shared_failure = ("budget_exceeded", "shared_deadline_exceeded", "shared_retrieval")
    if shared_failure and shared_failure[0] != "insufficient_evidence":
        shared["error"] = {"code": shared_failure[1], "stage": shared_failure[2]}
    if source_registry is not None:
        pair.update(registry_sha256=registry_sha256, required_source_scope=required_source_scope)
    actual_retry = []
    for mode in MODES:
        started_utc = datetime.now(timezone.utc).isoformat()
        mode_started = clock()
        budget = ChatBudget(policy, clock=clock,
                            deadline=mode_started + policy.total_timeout - shared["elapsed_seconds"])
        report = {"task": task, "mode": mode, "run_id": pair_id + "_" + mode,
                  "started_at_utc": started_utc, "policy": asdict(policy),
                  "comparison_version": comparison_version,
                  "shared_first_retrieval_reference": pair_id,
                  "embedding_accounting": "standalone_logical_includes_borrowed_first_search",
                  "rerank_accounting": "standalone_logical_includes_borrowed_first_rerank",
                  "result": _failure(question, pairs, *(shared_failure or
                    ("tool_error", "mode_not_started", "client_setup")), embedding=shared["statistics"],
                    rerank=shared["rerank_statistics"], task=task)}
        if source_requirement is not None:
            report["result"]["source_requirement"] = deepcopy(source_requirement)
        if shared_failure is None:
            replay = (None if source_stop else FrozenFirstSearcher(shared["search"], question, pairs,
                      searcher, allow_retry=mode == "agent"))
            if source_stop:
                report["embedding_accounting"] = "no_search_unavailable_source_scope"
                report["rerank_accounting"] = "no_search_unavailable_source_scope"
            client, stage = None, "input_verification"
            try:
                stage = "client_setup"
                if timed:
                    remaining(budget.remaining_seconds)
                client = client_factory(mode, budget)
                if client.budget is not budget or client.policy != policy:
                    raise ValueError("client did not use paired budget")
                stage = "mode_execution"
                core = answer_question_agent if mode == "agent" else answer_question
                options = {} if source_registry is None else {"source_registry": source_registry}
                if timed:
                    options["enforce_remaining_budget"] = True
                report["result"] = core(question, pairs, replay if replay is not None else searcher, store, client,
                                        project_root=project_root, top_k=5, max_chars=8000, **options)
            except DeadlineExceeded:
                _replace_failure(report, "budget_exceeded", "deadline_exceeded", stage)
            except Exception:
                _replace_failure(report, "tool_error", "paired_mode_error", stage)
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        _replace_failure(report, "tool_error", "client_close_error", "client_close")
                if replay is not None:
                    actual_retry.extend(deepcopy(replay.actual_retry_rounds))
            if timed and replay is not None and replay.calls == 0:
                # The paid shared first result belongs to both logical ledgers,
                # even if this mode expires before it can replay the snapshot.
                report["result"].setdefault("statistics", {})["embedding"] = deepcopy(shared["statistics"])
                report["result"]["statistics"]["rerank"] = deepcopy(shared["rerank_statistics"])
            # Includes setup, citation checks, errors and client cleanup in every status.
            if not timed and budget.remaining_seconds() <= 0:
                _replace_failure(report, "budget_exceeded", "deadline_exceeded", "mode_finish")
        if timed:
            commit_result(report["result"], budget, "mode_commit")
            report["business_commit"] = deepcopy(report["result"]["business_commit"])
            report["budget_implementation_version"] = "d9-remaining-budget-v1"
        chat = budget.statistics()
        if source_registry is not None:
            report.update(registry_sha256=registry_sha256, required_source_scope=required_source_scope)
            report["result"].update(task=task, comparison_version=comparison_version,
                                    registry_sha256=registry_sha256, required_source_scope=required_source_scope)
        report["result"].setdefault("statistics", {})["chat"] = deepcopy(chat)
        report.update({key: deepcopy(report["result"].get(key)) for key in
                       ("status", "query", "selected_versions", "answer", "error", "failure_stage", "stop_reason")})
        report.update(chat_statistics=deepcopy(chat), chat_attempts=deepcopy(budget.records),
                      embedding_statistics=deepcopy(report["result"]["statistics"].get("embedding")),
                      rerank_statistics=deepcopy(report["result"]["statistics"].get("rerank") or empty_rerank_statistics()),
                      llm_requests=chat["http_request_attempts"], chat_sdk_requests=chat["sdk_request_attempts"],
                      measured_mode_elapsed_seconds=max(0, clock() - mode_started),
                      logical_elapsed_components={"shared_first_seconds": shared["elapsed_seconds"],
                                                  "own_mode_seconds": max(0, clock() - mode_started)},
                      elapsed_interpretation="shared component plus measured own mode; not two measured standalone wall times",
                      finished_at_utc=datetime.now(timezone.utc).isoformat(), semantic_support_status="not_reviewed",
                      is_answer_accuracy=False)
        embedding = report["embedding_statistics"]
        report["embedding_requests"] = embedding.get("embedding_requests") if isinstance(embedding, dict) else None
        report["rerank_requests"] = report["rerank_statistics"]["requests"]
        report["network_requests"] = (report["embedding_requests"] + chat["http_request_attempts"] + report["rerank_requests"]
                                      if type(report["embedding_requests"]) is int else None)
        pair["modes"][mode] = report
    actual_embeddings = ([shared["statistics"]] if shared["actual_search_calls"]
                         or (timed and shared["statistics"] is not None) else []) + [r["statistics"] for r in actual_retry]
    actual_reranks = ([shared["rerank_statistics"]] if shared["actual_search_calls"] else []) + [r["rerank_statistics"] for r in actual_retry]
    pair["actual_retry_rounds"] = actual_retry
    pair["costs"] = {
        "actual_batch": {"embedding": aggregate_usage(actual_embeddings, ("embedding_requests", "failed_requests", "total_tokens")),
                         "rerank": sum_rerank_statistics(actual_reranks),
                         "chat": aggregate_usage([pair["modes"][m]["chat_statistics"] for m in MODES],
                                    ("sdk_request_attempts", "http_request_attempts", "network_retries", "repairs", "total_tokens"))},
        "standalone_logical": {m: {"embedding": deepcopy(pair["modes"][m]["embedding_statistics"]),
                                    "rerank": deepcopy(pair["modes"][m]["rerank_statistics"]),
                                    "chat": deepcopy(pair["modes"][m]["chat_statistics"])} for m in MODES},
        "interpretation": "actual first embedding and rerank once; logical first retrieval attributed to each mode; unknown tokens remain null"}
    failures = [pair["modes"][m]["status"] for m in MODES if pair["modes"][m]["status"] not in NORMAL]
    pair["status"] = ("budget_exceeded" if "budget_exceeded" in failures else failures[0]) if failures else "completed"
    pair["error"] = shared["error"]
    return pair
