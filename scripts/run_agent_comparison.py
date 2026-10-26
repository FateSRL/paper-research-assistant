"""D8/D9 development-only paired runner. Default prepares; --live makes calls.

Prepared manifests and attempted cases are immutable. --resume explicitly
continues only unattempted cases under identical bindings; never reruns a case.
"""

import argparse
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

with redirect_stdout(sys.stderr):
    from paper_assistant.agent_comparison import MODES, aggregate_usage, run_paired_case
    from paper_assistant.agent_evaluation import MACHINE_RUBRIC, score_agent_case, summarize_agent_cases
    from paper_assistant.agent_export import AgentExportError, _identifier, _path, reserve_agent_batch, save_agent_run, validate_stage
    from paper_assistant.agent_runtime import load_current_profile, open_retrieval_resources, validate_frozen_configuration
    from paper_assistant.answer_export import atomic_text, exclusive_json
    from paper_assistant.config import load_embedding_settings, load_llm_settings
    from paper_assistant.evaluation import score_case, summarize_case_scores
    from paper_assistant.llm_client import ChatPolicy, RecordedLLM
    from scripts.run_retrieval_comparison import dev_cases


ROOT = Path(__file__).resolve().parents[1]
RUNNER_VERSION = "d8-frozen-dev-paired-runner-v1"
D9_RUNNER_VERSION = "d9-frozen-dev-paired-runner-v1"
DEFAULT_CASES = ("D2-001", "D2-002", "D2-003", "D5-006")
INPUT_BINDING_VERSION = "question-parameters-source-ranges-v1"
CURRENT_RUNNER_VERSION = "v2.2-current-dev-comparison-v1"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _batch_path(root, batch_id, stage="d8"):
    return _path(Path(root).resolve(), "artifacts/" + validate_stage(stage) + "/comparison/" + _identifier(batch_id))


def _source_ranges(root, ready_pairs):
    """Bind reviewed answer-source ranges, excluding offline review attachments."""
    from paper_assistant.d9_runtime import REGISTRY_PATH
    fields = ("scope", "pdf_page", "segment_id", "segment_char_start", "segment_char_end",
              "text_sha256", "verification_status", "human_review_status")
    return [{"paper_id": doc["paper_id"], "parse_revision": doc["parse_revision"],
             "pdf_sha256": doc["pdf_sha256"],
             "regions": [{key: region[key] for key in fields} for region in doc["regions"]]}
            for doc in _read(root / REGISTRY_PATH)["documents"]
            if ready_pairs.get(doc["paper_id"]) == doc["parse_revision"]]


def prepare_batch(batch_id, case_ids=DEFAULT_CASES, *, project_root=ROOT, stage="d8"):
    """Prepare the selected dev questions and execution parameters without paid calls."""
    root = Path(project_root).resolve()
    stage = validate_stage(stage)
    _identifier(batch_id)
    selected = list(case_ids)
    all_cases = {case["case_id"]: case for case in dev_cases(root)}
    if not selected or len(set(selected)) != len(selected) or any(c not in all_cases for c in selected):
        raise ValueError("invalid_dev_case_selection")
    cases = [deepcopy(all_cases[c]) for c in selected]
    if stage == "d9":
        from paper_assistant import d9_runtime
        strategy = d9_runtime.load_strategy(root)
        strategy_path = d9_runtime.STRATEGY_PATH
    else:
        strategy = _read(root / "artifacts/d8/agent_config.json")
        strategy_path = "artifacts/d8/agent_config.json"
    profile = load_current_profile(root)
    if strategy["index_profile"] != profile:
        raise ValueError("strategy_index_mismatch")
    ready = {row["paper_id"]: row["parse_revision"] for row in strategy["ready_versions"] if row["status"] == "ready"}
    for case in cases:
        if any(paper not in ready for paper in case["paper_ids"]):
            raise ValueError("case_not_in_ready_scope")
    policy = ChatPolicy(**strategy["rules"]["budget"]["chat_policy"]) if stage == "d9" else ChatPolicy()
    public = {"chat": {"provider": strategy["chat"]["provider"], "model_id": strategy["chat"]["model_id"],
                       "base_url": strategy["chat"]["base_url"],
                       "configured_timeout": strategy["chat"]["configured_timeout_seconds"]},
              "embedding": deepcopy(profile["recipe"]), "policy": asdict(policy)}
    manifest = {"task": stage.upper() + "-E", "runner_version": D9_RUNNER_VERSION if stage == "d9" else RUNNER_VERSION, "batch_id": batch_id,
                "created_at_utc": _now(), "case_ids": selected, "split": "dev",
                "input_binding_version": INPUT_BINDING_VERSION,
                "cases": cases, "ready_pairs": ready, "configuration": public,
                "index_profile": profile, "modes": list(MODES),
                "strategy_binding": {"path": strategy_path,
                                     "schema_revision": strategy["schema_revision"]},
                "rubric": deepcopy(MACHINE_RUBRIC), "is_answer_accuracy": False,
                "is_f_paid_validation": False, "real_api_calls_during_preparation": 0,
                "input_isolation": "Only question and complete selected pairs enter core/model; annotations are posthoc only",
                "continuation": "explicit --resume, same bindings; immutable reservations forbid attempted case replay"}
    if stage == "d9":
        manifest.update(stage=stage, source_ranges=_source_ranges(root, ready))
    manifest["freeze_sha256"] = _digest(manifest)
    path = reserve_agent_batch(root, batch_id, manifest, stage=stage)
    state = {"status": "prepared", "batch_id": batch_id, "attempted_case_ids": [],
             "completed_case_ids": [], "remaining_case_ids": selected, "records": [],
             "freeze_sha256": manifest["freeze_sha256"], "real_api_calls": 0}
    atomic_text(path / "state.json", _json(state))
    return {"status": "prepared", "batch_id": batch_id, "path": path.relative_to(root).as_posix(),
            "case_ids": selected, "freeze_sha256": manifest["freeze_sha256"], "real_api_calls": 0}


@contextmanager
def _batch_lock(path):
    lock = path / ".execution.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(_now())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _summary(manifest, records, state, uncommitted_pair=None):
    scores = {mode: [] for mode in MODES}
    for record in records:
        for mode in MODES:
            scores[mode].append(record["scores"][mode])
    if uncommitted_pair:
        case = next(c for c in manifest["cases"] if c["case_id"] == uncommitted_pair["case_id"])
        # A scoring/export failure cannot remove an attempted question from the
        # denominator. Its uncommitted evidence is retained, but scores are misses.
        for mode in MODES:
            report = deepcopy(uncommitted_pair["modes"][mode])
            report.update(status="tool_error", answer=None)
            report["result"] = {"status": "tool_error", "answer": None,
                                "statistics": report["result"].get("statistics")}
            scorer = score_agent_case if mode == "agent" else score_case
            scores[mode].append(scorer(case, report))
    all_pairs = [r["pair"] for r in records] + ([uncommitted_pair] if uncommitted_pair else [])
    costs = {"embedding": aggregate_usage([p["costs"]["actual_batch"]["embedding"] for p in all_pairs],
                                           ("embedding_requests", "failed_requests", "total_tokens")),
             "chat": aggregate_usage([p["costs"]["actual_batch"]["chat"] for p in all_pairs],
                                      ("sdk_request_attempts", "http_request_attempts", "network_retries", "repairs", "total_tokens"))}
    return {"task": manifest["task"], "batch_id": manifest["batch_id"], "status": state["status"],
            "freeze_sha256": manifest["freeze_sha256"], "updated_at_utc": _now(),
            "planned_case_ids": manifest["case_ids"], "attempted_case_ids": state["attempted_case_ids"],
            "remaining_case_ids": state["remaining_case_ids"], "records": records,
            "actual_batch_cost": costs, "uncommitted_pair": uncommitted_pair, "mode_summaries": {
                "fixed_rag": summarize_case_scores(scores["fixed_rag"], planned_cases=manifest["cases"]),
                "agent": summarize_agent_cases(scores["agent"], planned_cases=manifest["cases"])},
            "elapsed_interpretation": "mode score UTC elapsed includes own setup/execution/close only; shared retrieval separately measured; logical components are not two measured standalone wall times",
            "qa_accuracy": None, "semantic_support_status": "not_reviewed", "is_answer_accuracy": False}


def execute_batch(batch_id, *, project_root=ROOT, resume=False, stage="d8",
                  configuration_loader=None, resources_factory=None, client_factory=None):
    """Execute a prepared batch with explicit ownership and immutable case events."""
    root = Path(project_root).resolve()
    run_stage = validate_stage(stage)
    path = _batch_path(root, batch_id, run_stage)
    manifest = _read(path / "manifest.json")
    frozen = deepcopy(manifest)
    digest = frozen.pop("freeze_sha256")
    expected_version = D9_RUNNER_VERSION if run_stage == "d9" else RUNNER_VERSION
    if (manifest.get("input_binding_version") != INPUT_BINDING_VERSION
            or digest != _digest(frozen) or manifest["runner_version"] != expected_version
            or manifest["batch_id"] != batch_id or manifest.get("stage", "d8") != run_stage
            or manifest["task"] != run_stage.upper() + "-E"):
        raise ValueError("manifest_binding_mismatch")
    if run_stage == "d9" and manifest["source_ranges"] != _source_ranges(root, manifest["ready_pairs"]):
        raise ValueError("batch_source_ranges_changed")
    policy = ChatPolicy(**manifest["configuration"]["policy"])
    if run_stage == "d9":
        from paper_assistant import d9_runtime
    if tuple(manifest.get("modes", MODES)) != MODES:
        raise ValueError("batch_modes_mismatch")
    embedding, chat = (configuration_loader or (lambda: (load_embedding_settings(), load_llm_settings())))()
    strategy = d9_runtime.load_strategy(root) if run_stage == "d9" else _read(root / "artifacts/d8/agent_config.json")
    validator = d9_runtime.validate_configuration if run_stage == "d9" else validate_frozen_configuration
    if validator(strategy, embedding, chat, manifest["index_profile"], policy) != manifest["configuration"]:
        raise ValueError("frozen_public_configuration_changed")
    with _batch_lock(path):
        # Existing reservations, rather than mutable state, decide attempted work.
        reservations = {case_id for case_id in manifest["case_ids"] if (path / (case_id + ".attempt.json")).exists()}
        for case_id in reservations:
            attempt = _read(path / (case_id + ".attempt.json"))
            if attempt.get("freeze_sha256") != digest or attempt.get("case_id") != case_id:
                raise ValueError("reservation_binding_mismatch")
        records = []
        for case_id in manifest["case_ids"]:
            report_path = path / (case_id + ".json")
            if report_path.exists():
                if case_id not in reservations:
                    raise ValueError("orphan_case_record_requires_inspection")
                record = _read(report_path)
                if record.get("freeze_sha256") != digest or record.get("case_id") != case_id:
                    raise ValueError("saved_case_binding_mismatch")
                records.append(record)
            elif case_id in reservations:
                raise ValueError("attempted_case_has_no_final_record_requires_inspection")
        if reservations and not resume:
            raise ValueError("explicit_resume_required_for_unattempted_cases")
        state = {"status": "running", "batch_id": batch_id, "attempted_case_ids": sorted(reservations),
                 "completed_case_ids": [r["case_id"] for r in records],
                 "remaining_case_ids": [c for c in manifest["case_ids"] if c not in reservations],
                 "records": [r["case_id"] + ".json" for r in records], "freeze_sha256": digest}
        latest_pair = None
        stage = "resource_setup"
        try:
            open_resources = resources_factory or open_retrieval_resources
            with open_resources(root, embedding, manifest["index_profile"]) as (store, searcher):
                registry = None
                if run_stage == "d9":
                    registry = d9_runtime.load_registry(root, list(manifest["ready_pairs"].items()), store=store)
                for case in manifest["cases"]:
                    case_id = case["case_id"]
                    if case_id in reservations:
                        continue
                    stage = "case_preflight"
                    exclusive_json(path / (case_id + ".attempt.json"), {
                        "case_id": case_id, "started_at_utc": _now(), "freeze_sha256": digest,
                        "automatic_rerun_allowed": False})
                    reservations.add(case_id)
                    state["attempted_case_ids"].append(case_id)
                    state["remaining_case_ids"].remove(case_id)
                    atomic_text(path / "state.json", _json(state))
                    pairs = [(p, manifest["ready_pairs"][p]) for p in case["paper_ids"]]

                    def clients(mode, budget):
                        if client_factory:
                            return client_factory(mode, budget)
                        return RecordedLLM(chat, policy=policy, budget=budget)

                    stage = "paired_execution"
                    options = {"source_registry": registry, "enforce_remaining_budget": True} if run_stage == "d9" else {}
                    latest_pair = run_paired_case(case["question"], pairs, searcher, store, clients,
                                                  project_root=root, policy=policy, **options)
                    latest_pair["case_id"] = case_id  # Added after all model calls; labels stay posthoc.
                    stage = "mode_export"
                    for mode in MODES:
                        report = latest_pair["modes"][mode]
                        report.update(batch_id=batch_id, configuration=deepcopy(manifest["configuration"]),
                                      index_profile=deepcopy(manifest["index_profile"]),
                                      strategy_binding=deepcopy(manifest["strategy_binding"]))
                        latest_pair["modes"][mode] = save_agent_run(report, project_root=root)
                    failed_modes = [latest_pair["modes"][m] for m in MODES
                                    if latest_pair["modes"][m]["status"] not in ("answered", "insufficient_evidence")]
                    if failed_modes:
                        latest_pair["pre_export_pair_status"] = latest_pair["status"]
                        latest_pair["status"] = ("budget_exceeded" if any(r["status"] == "budget_exceeded" for r in failed_modes)
                                                 else failed_modes[0]["status"])
                        latest_pair["error"] = deepcopy(failed_modes[0].get("error"))
                    stage = "posthoc_scoring"
                    scores = {"fixed_rag": score_case(case, latest_pair["modes"]["fixed_rag"]),
                              "agent": score_agent_case(case, latest_pair["modes"]["agent"])}
                    record = {"case_id": case_id, "freeze_sha256": digest, "pair": latest_pair, "scores": scores}
                    stage = "case_export"
                    exclusive_json(path / (case_id + ".json"), record)
                    records.append(record)
                    latest_pair = None  # All consumed work is now in an immutable case record.
                    state["completed_case_ids"].append(case_id)
                    state["records"].append(case_id + ".json")
                    if any(record["pair"]["modes"][m]["status"] not in ("answered", "insufficient_evidence") for m in MODES):
                        state["status"] = "attention_required"
                        break
            if state["status"] == "running":
                any_failed = any(r["pair"]["modes"][m]["status"] not in ("answered", "insufficient_evidence")
                                 for r in records for m in MODES)
                state["status"] = ("attention_required" if any_failed else
                                   "completed" if not state["remaining_case_ids"] else "partial")
        except Exception:
            state.update(status="attention_required", error={"code": "batch_execution_error", "stage": stage})
            # Separate recovery event retains consumed calls even after scoring/export/cleanup failure.
            recovery = {"task": manifest["task"], "batch_id": batch_id, "error": state["error"],
                        "state": deepcopy(state), "latest_pair": latest_pair, "records": records}
            try:
                recovery_name = "failure_" + uuid4().hex + ".json"
                exclusive_json(path / recovery_name, recovery)
                state["recovery_report"] = recovery_name
            except Exception:
                state["unsaved_recovery"] = recovery
        summary = _summary(manifest, records, state, latest_pair)
        summary["state"] = deepcopy(state)
        summary["export"] = {"status": "prepared", "failed_step": None}
        try:
            stage = "batch_summary_export"
            event = "summary_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]
            exclusive_json(path / (event + ".json"), summary)
            stage = "batch_markdown_export"
            atomic_text(path / "summary.md", "# " + run_stage.upper() + " 开发集成对比较\n\n状态：" + state["status"] +
                        "。\n\n已记录 " + str(len(records)) + " / " + str(len(manifest["cases"])) +
                        " 题；详细两模式、各层证据命中和实际/逻辑费用见 JSON。\n\nQA accuracy 尚未测定；语义支持待评阅。\n")
            stage = "batch_state_export"
            atomic_text(path / "state.json", _json(state))
            summary["export"]["status"] = "completed"
            stage = "batch_latest_export"
            atomic_text(path / "summary.json", _json(summary))
        except Exception:
            failure = {"code": "batch_export_error", "stage": stage}
            state.update(status="attention_required", error=deepcopy(failure))
            summary.update(status="attention_required", error=failure, state=deepcopy(state),
                           export={"status": "failed", "failed_step": stage,
                                   "recovery_saved": False, "latest_recovery_saved": False})
            recovery_name = "batch_export_failure_" + uuid4().hex + ".json"
            summary["export"]["recovery_report"] = recovery_name
            try:
                recovery = deepcopy(summary)
                recovery["export"]["recovery_saved"] = True
                exclusive_json(path / recovery_name, recovery)
                summary["export"]["recovery_saved"] = True
            except Exception:
                pass
            try:
                atomic_text(path / "state.json", _json(state))
                atomic_text(path / "summary.md", "# " + run_stage.upper() + " 批次导出未完成\n\n状态：attention_required。\n\n"
                            "已发生的调用、费用和题记录保留在 JSON 与独立恢复事件。\n")
                summary["export"]["latest_recovery_saved"] = True
                atomic_text(path / "summary.json", _json(summary))
            except Exception:
                summary["export"]["latest_recovery_saved"] = False
        return summary


def _current_batch_path(root, batch_id):
    return _path(Path(root).resolve(), "artifacts/v2/comparison/" + _identifier(batch_id))


def prepare_current_batch(batch_id, case_ids=DEFAULT_CASES, *, project_root=ROOT):
    """Prepare dev inputs and complete version pairs without opening clients."""
    from paper_assistant import d9_runtime

    root = Path(project_root).resolve()
    path = _current_batch_path(root, batch_id)
    selected = list(case_ids)
    available_cases = {case["case_id"]: case for case in dev_cases(root)}
    if not selected or len(set(selected)) != len(selected) or any(c not in available_cases for c in selected):
        raise ValueError("invalid_dev_case_selection")
    strategy = d9_runtime.load_strategy(root)
    ready = d9_runtime.list_ready_versions(project_root=root)
    ready_pairs = {(row["paper_id"], row["parse_revision"]) for row in ready}
    preferred = {row["paper_id"]: row["parse_revision"] for row in strategy["ready_versions"]
                 if row["status"] == "ready" and (row["paper_id"], row["parse_revision"]) in ready_pairs}
    cases = []
    for case_id in selected:
        case = deepcopy(available_cases[case_id])
        versions = []
        for paper_id in case["paper_ids"]:
            revisions = [revision for paper, revision in ready_pairs if paper == paper_id]
            revision = preferred.get(paper_id)
            if revision is None:
                if len(revisions) != 1:
                    raise ValueError("dev_paper_requires_one_selected_ready_version")
                revision = revisions[0]
            versions.append({"paper_id": paper_id, "parse_revision": revision})
        case["selected_versions"] = versions
        cases.append(case)
    profile = _read(root / "data/index/current_profile.json")
    batch = {"pipeline": "current", "runner_version": CURRENT_RUNNER_VERSION,
             "batch_id": batch_id, "created_at_utc": _now(), "split": "dev",
             "case_ids": selected, "cases": cases, "modes": list(MODES),
             "configuration": {"chat": {key: strategy["chat"][key] for key in
                               ("provider", "model_id", "base_url", "configured_timeout_seconds")},
                               "embedding": deepcopy(profile["recipe"]),
                               "policy": asdict(d9_runtime.INTERACTIVE_CHAT_POLICY),
                               "top_k": 5, "max_chars": 8000, "autonomous_step_limit": 5},
             "configuration_note": "Saved runtime defaults for preparation; each runtime result retains its actual configuration and rerank settings.",
             "comparison": "Independent end-to-end page flows; no equal total-token or retrieval-count budget.",
             "input_isolation": "Only question and complete selected pairs enter runtime; annotations are posthoc only.",
             "real_api_calls_during_preparation": 0, "qa_accuracy": None}
    path.mkdir(parents=True, exist_ok=False)
    exclusive_json(path / "input.json", batch)
    state = {"status": "prepared", "batch_id": batch_id, "attempted_case_ids": [],
             "completed_case_ids": [], "remaining_case_ids": selected, "records": []}
    atomic_text(path / "state.json", _json(state))
    return {"pipeline": "current", "status": "prepared", "batch_id": batch_id,
            "path": path.relative_to(root).as_posix(), "case_ids": selected, "real_api_calls": 0}


def _current_summary(batch, records, state):
    from paper_assistant.agent_comparison import summarize_current_costs
    from paper_assistant.agent_evaluation import score_current_case, summarize_current_cases

    cases = {case["case_id"]: case for case in batch["cases"]}
    scores = {mode: [] for mode in MODES}
    for record in records:
        for mode, report in record["pair"]["modes"].items():
            score = record["scores"].get(mode)
            scores[mode].append(score if score is not None else score_current_case(cases[record["case_id"]], report))
    costs = summarize_current_costs([record["pair"] for record in records])
    return {"pipeline": "current", "runner_version": CURRENT_RUNNER_VERSION,
            "batch_id": batch["batch_id"], "status": state["status"], "updated_at_utc": _now(),
            "planned_case_ids": batch["case_ids"], "attempted_case_ids": state["attempted_case_ids"],
            "remaining_case_ids": state["remaining_case_ids"], "state": deepcopy(state),
            "records": [{"case_id": record["case_id"], "path": record["case_id"] + ".json"}
                        for record in records],
            "actual_batch_cost": costs["actual_batch"], "per_mode_cost": costs["per_mode"],
            "mode_summaries": {mode: summarize_current_cases(scores[mode], planned_cases=batch["cases"])
                               for mode in MODES},
            "comparison": batch["comparison"], "qa_accuracy": None,
            "semantic_support_status": "not_reviewed", "is_answer_accuracy": False}


def execute_current_batch(batch_id, *, project_root=ROOT, runtime_runner=None):
    """Run each mode through the page runtime, saving each returned run once."""
    from paper_assistant import d9_runtime
    from paper_assistant.agent_comparison import run_current_case
    from paper_assistant.agent_evaluation import score_current_case

    root = Path(project_root).resolve()
    path = _current_batch_path(root, batch_id)
    batch, state = _read(path / "input.json"), _read(path / "state.json")
    if state["status"] != "prepared" or state["attempted_case_ids"]:
        raise ValueError("current_batch_already_started; create a new batch for a new explicit run")
    state["status"] = "running"
    atomic_text(path / "state.json", _json(state))
    records, stage = [], "case_start"
    run_runtime = runtime_runner or d9_runtime.run_question
    try:
        for case in batch["cases"]:
            case_id = case["case_id"]
            pairs = [(row["paper_id"], row["parse_revision"]) for row in case["selected_versions"]]
            state["attempted_case_ids"].append(case_id)
            state["remaining_case_ids"].remove(case_id)
            atomic_text(path / "state.json", _json(state))
            record = {"case_id": case_id, "pair": {"pipeline": "current", "modes": {}}, "scores": {}}
            records.append(record)

            def save_mode(mode, report):
                record["pair"]["modes"][mode] = deepcopy(report)
                atomic_text(path / (case_id + ".json"), _json(record))

            def invoke_runtime(question, versions, *, mode, **options):
                # An interrupted call has unknown usage; its attempted status
                # must survive without inventing zero requests or replaying it.
                save_mode(mode, {"mode": mode, "status": "tool_error", "started_at_utc": _now(),
                    "selected_versions": deepcopy(case["selected_versions"]),
                    "failure_stage": "runtime", "stop_reason": "runtime_incomplete",
                    "result": {"status": "tool_error", "answer": None,
                               "selected_versions": deepcopy(case["selected_versions"])}})
                return run_runtime(question, versions, mode=mode, **options)

            stage = "runtime"
            record["pair"] = run_current_case(case["question"], pairs, project_root=root,
                runtime_runner=invoke_runtime, on_mode_result=save_mode)
            atomic_text(path / (case_id + ".json"), _json(record))
            stage = "posthoc_scoring"
            record["scores"] = {mode: score_current_case(case, record["pair"]["modes"][mode]) for mode in MODES}
            atomic_text(path / (case_id + ".json"), _json(record))
            state["completed_case_ids"].append(case_id)
            state["records"].append(case_id + ".json")
            atomic_text(path / "state.json", _json(state))
            if record["pair"]["status"] != "completed":
                state["status"] = "attention_required"
                break
        if state["status"] == "running":
            state["status"] = "completed"
    except (Exception, KeyboardInterrupt):
        state.update(status="attention_required", error={"code": "current_batch_interrupted", "stage": stage})
    atomic_text(path / "state.json", _json(state))
    summary = _current_summary(batch, records, state)
    atomic_text(path / "summary.json", _json(summary))
    lines = ["# 当前页面流程开发集对照", "", "状态：" + state["status"] + "。", "",
             "固定 RAG 与 Agent 独立执行前置准备和问答；实际配置、证据、用量及历史路径见逐题 JSON。", "",
             "指定引文命中是检索代理；引用定位通过不等于语义支持。QA accuracy 尚未评价。", "",
             "| 模式 | 已尝试 | 完成 | 失败 | 未尝试 | Returned 全命中 | Final shown 全命中 |", "",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for mode, mode_summary in summary["mode_summaries"].items():
        def ratio_text(key):
            metric = mode_summary[key]
            return str(metric["numerator"]) + " / " + str(metric["denominator"])
        lines.append("| " + mode + " | " + " | ".join(str(mode_summary[key]) for key in
            ("attempted_count", "completed_count", "failed_count", "unattempted_count")) + " | "
            + ratio_text("exact_all_targets_hit_returned") + " | " + ratio_text("exact_all_targets_hit_shown") + " |")
    atomic_text(path / "summary.md", "\n".join(lines) + "\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="D8/D9 成对开发集实验；默认只准备，--live 才发请求")
    parser.add_argument("--stage", choices=("d8", "d9"), default="d8", help="显式选择策略与独立记录目录；默认 d8")
    parser.add_argument("--pipeline", choices=("legacy", "current"), default="legacy",
                        help="current 使用页面当前独立固定 RAG／五步 Agent；默认保留旧流程")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--case-ids", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--live", action="store_true", help="新建批次后执行真实调用")
    parser.add_argument("--execute-prepared", action="store_true", help="执行已准备且未尝试的同名批次")
    parser.add_argument("--resume", action="store_true", help="明确续跑同名批次未尝试题；不重跑已尝试题")
    args = parser.parse_args(argv)
    if sum((args.live, args.execute_prepared, args.resume)) > 1:
        parser.error("执行标志只能选择一个")
    if args.pipeline == "current" and args.resume:
        parser.error("当前流程不支持 --resume；已尝试批次不会自动重跑，请用新 batch-id 明确建立新运行")
    try:
        with redirect_stdout(sys.stderr):
            if args.pipeline == "current":
                if not args.execute_prepared:
                    prepared = prepare_current_batch(args.batch_id, args.case_ids)
                report = execute_current_batch(args.batch_id) if args.live or args.execute_prepared else prepared
            else:
                if not (args.execute_prepared or args.resume):
                    prepared = prepare_batch(args.batch_id, args.case_ids, stage=args.stage)
                report = execute_batch(args.batch_id, resume=args.resume, stage=args.stage) if (args.live or args.execute_prepared or args.resume) else prepared
        print(_json(report), end="")
        return 0 if report["status"] in ("prepared", "completed") else 1
    except Exception:
        if args.pipeline == "current":
            print(_json({"pipeline": "current", "status": "tool_error", "error": {"code": "current_batch_input_error",
                         "message": "请核对开发题、已入库版本和批次目录；已有批次不覆盖，已尝试批次不自动重跑"}}), end="")
            return 2
        print(_json({"task": args.stage.upper() + "-E", "status": "tool_error", "error": {"code": "batch_preflight_error",
                    "message": "批次输入、冻结绑定或记录目录不合法，请核对参数与现有记录"}}), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
