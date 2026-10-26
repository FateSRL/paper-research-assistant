"""D6 C 的独立检索实验入口；新增入口不表示 C 的真实对照已完成。

--from-first-runs 离线汇总已保存的十题和六题首次 top-5 记录，无请求。
--live 对开发集每题只检索一次 top-20，用相同排序的 5/10/20 前缀比较
Returned 与 Shown 标注引文命中；不会调用聊天模型或读取验收候选题。
两种模式都必须使用新的 batch-id，已有批次、中断或失败不会自动重跑。
"""

import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.context import prepare_context
from paper_assistant.evaluation import score_case
from paper_assistant.indexing import atomic_json


ROOT = Path(__file__).resolve().parents[1]
VERSION = "d6-retrieval-comparison-v1"
FIRST_BATCHES = ("d5_f_dev10_20261004", "d6_f_dev16_20261004")
OLD_IDS = ("D2-001", "D2-005", "D2-003", "D2-006", "D2-002", "D2-004",
           "D3-001", "D3-002", "D3-003", "D3-004")
NEW_IDS = tuple(f"D5-{i:03d}" for i in range(1, 7))
SOURCES = ("paper_assistant/answer_export.py", "paper_assistant/config.py",
           "paper_assistant/context.py", "paper_assistant/embedding_client.py",
           "paper_assistant/evaluation.py", "paper_assistant/indexing.py",
           "paper_assistant/retrieval.py", "paper_assistant/schemas.py",
           "paper_assistant/search.py", "paper_assistant/storage.py",
           "scripts/run_retrieval_comparison.py")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
PAPER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
RUBRIC = {"version": VERSION, "is_qa_accuracy": False,
          "input_isolation": "Only original question and complete selected paper/revision pairs enter search_evidence. Expected fields are post-hoc scoring only.",
          "comparison": "One validated top-20 search per case; use ranked prefixes of 5, 10 and 20, each with the same complete-chunk selection and 8000-character limit.",
          "metrics": "Reuse exact target quote matching with whitespace normalization only, selected complete pairs, annotated PDF SHA and file page. Count Returned and Shown separately, per quote and all-target case. Negatives have no target-hit denominator. A miss is not proof of absent semantic support.",
          "scope": "Development retrieval proxy only, not answer accuracy or frozen acceptance evaluation.",
          "failure": "Persist attempted usage; unknown values stay null. No automatic retry/resume or chat requests."}


class BatchExportError(RuntimeError):
    """Keep safe full in-memory records if final disk export fails."""

    def __init__(self, payload):
        super().__init__("batch_export_failure")
        self.payload = payload


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def relative_file(root, name):
    """Only resolve recorded project-relative paths within this checkout."""
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError("invalid_relative_path")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("unsafe_or_missing_record_path")
    return path


def dev_cases(root=ROOT):
    cases = [json.loads(line) for line in (root / "eval/dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("empty_or_duplicate_dev_cases")
    for case in cases:
        if (not SAFE_ID.fullmatch(case["case_id"]) or case.get("split") != "dev"
                or case.get("review_status") != "human_verified"
                or type(case.get("answerable")) is not bool
                or not isinstance(case.get("question"), str) or not case["question"].strip()
                or not isinstance(case.get("paper_ids"), list) or not 1 <= len(case["paper_ids"]) <= 3
                or len(set(case["paper_ids"])) != len(case["paper_ids"])
                or any(not isinstance(p, str) or not PAPER_ID.fullmatch(p) for p in case["paper_ids"])):
            raise ValueError("invalid_or_unconfirmed_dev_case")
        targets = case.get("expected_evidence")
        if (not isinstance(targets, list) or bool(targets) != case["answerable"]
                or any(not isinstance(t, dict) or t.get("paper_id") not in case["paper_ids"]
                       or not isinstance(t.get("pdf_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", t["pdf_sha256"])
                       or type(t.get("pdf_page")) is not int or t["pdf_page"] < 1
                       or not isinstance(t.get("quote"), str) or not t["quote"].strip() for t in targets)):
            raise ValueError("invalid_dev_target_annotation")
    return cases


def target_score(case, search, context):
    report = {"selected_versions": deepcopy(search["selected_versions"]),
              "result": {"search": search, "context": context}}
    scored = score_case(case, report)
    return {key: scored[key] for key in ("case_id", "answerable", "targets", "exact_targets_available",
                                        "exact_all_targets_hit_returned", "exact_all_targets_hit_shown")}


def ratio(values):
    return {"numerator": sum(values), "denominator": len(values),
            "ratio": sum(values) / len(values) if values else None}


def summarize(records, top_k):
    """Attempted failures remain in target denominators, with zero hits."""
    for record in records:
        if (type(record.get("answerable")) is not bool
                or type(record.get("expected_target_count")) is not int
                or record["expected_target_count"] < 0):
            raise ValueError("attempted_record_missing_target_metadata")
    scored = {r["case_id"]: r["comparisons"][str(top_k)]["score"] for r in records
              if r.get("status") == "completed" and str(top_k) in r.get("comparisons", {})}
    target_cases = [r for r in records if r["answerable"] and r["expected_target_count"] > 0]
    case_hits = {"returned": [], "shown": []}
    quote_hits = {"returned": [], "shown": []}
    for record in target_cases:
        score = scored.get(record["case_id"])
        if score is not None and len(score["targets"]) != record["expected_target_count"]:
            raise ValueError("attempted_target_count_mismatch")
        for scope in ("returned", "shown"):
            case_hits[scope].append(bool(score and score[f"exact_all_targets_hit_{scope}"]))
            quote_hits[scope].extend([t[f"exact_target_hit_{scope}"] for t in score["targets"]]
                                     if score else [False] * record["expected_target_count"])
    return {"attempted_count": len(records), "scored_count": len(scored),
            "failed_attempted_count": len(records) - len(scored),
            "failure_denominator_policy": "Every attempted answerable case with annotations remains in all-target and quote denominators; tool/scoring failures count as zero hits.",
            "answerable_target_case_count": len(target_cases),
            "negative_case_count": sum(not r["answerable"] for r in records),
            "exact_all_targets_hit_returned": ratio(case_hits["returned"]),
            "exact_all_targets_hit_shown": ratio(case_hits["shown"]),
            "exact_quote_hit_returned": ratio(quote_hits["returned"]),
            "exact_quote_hit_shown": ratio(quote_hits["shown"]),
            "is_qa_accuracy": False, "qa_accuracy": None}


def verified_first_runs(root=ROOT, cases=None):
    """Verify historical snapshots; current annotations must match the old 16."""
    cases = dev_cases(root) if cases is None else cases
    current = {c["case_id"]: c for c in cases}
    records, bindings, run_ids = [], {}, set()
    file_hashes = {}
    def current_sha(path):
        key = path.resolve()
        if key not in file_hashes:
            file_hashes[key] = sha(path)
        return file_hashes[key]
    for batch_id, wanted in zip(FIRST_BATCHES, (OLD_IDS, NEW_IDS)):
        batch = root / "artifacts/d5/qa_baseline" / batch_id
        manifest = read_json(batch / "manifest.json")
        initial = read_json(batch / "manifest.initial.json")
        frozen = manifest["binding"]
        if (manifest["batch_id"] != batch_id or initial["batch_id"] != batch_id
                or initial["binding"] != frozen or initial["binding_sha256"] != digest(frozen)
                or manifest["binding_sha256"] != digest(frozen)
                or read_json(batch / "rubric.json") != frozen["rubric"]):
            raise ValueError("first_manifest_binding_changed")
        old = {c["case_id"]: c for c in frozen["cases"]}
        if len(old) != len(frozen["cases"]):
            raise ValueError("first_manifest_duplicate_cases")
        if frozen["index_profile"] != read_json(root / "data/index/current_profile.json"):
            raise ValueError("first_index_profile_changed")
        if frozen["top_k"] != 5 or frozen["max_chars"] != 8000:
            raise ValueError("first_selection_policy_changed")
        bindings[batch_id] = {"historical_binding_sha256": manifest["binding_sha256"],
                              "historical_eval_sha256": frozen["eval_sha256"],
                              "manifest_sha256": sha(batch / "manifest.json"),
                              "initial_manifest_sha256": sha(batch / "manifest.initial.json"),
                              "case_ids": list(wanted)}
        for case_id in wanted:
            if current.get(case_id) != old.get(case_id) or case_id not in old:
                raise ValueError("first_annotation_changed")
            info = manifest["results"][case_id]
            path = relative_file(batch, info["result_path"])
            entry = read_json(path)
            report = entry["report"]
            history = relative_file(root, entry["source_history_report"])
            pairs = [{"paper_id": p, "parse_revision": next(v["parse_revision"] for v in frozen["selected_versions"] if v["paper_id"] == p)} for p in current[case_id]["paper_ids"]]
            if (sha(path) != info["result_sha256"] or entry["case_id"] != case_id
                    or entry["attempt_status"] != "completed" or entry["exit_code"] != 0
                    or info.get("source_history_verified") is not True
                    or entry.get("source_history_verified") is not True
                    or sha(history) != info.get("source_history_sha256")
                    or sha(history) != entry.get("source_history_sha256")
                    or read_json(history) != report or json.loads(entry["stdout"]) != report
                    or entry["run_id"] != report["run_id"] or info["run_id"] != report["run_id"]
                    or report["run_id"] in run_ids or report["query"] != current[case_id]["question"]
                    or report["selected_versions"] != pairs
                    or report["eval_sha256"].get("eval/dev.jsonl") != frozen["eval_sha256"]
                    or report["source_unchanged_during_run"] is not True
                    or report["index_profile"] != frozen["index_profile"]
                    or report["top_k"] != 5 or report["max_chars"] != 8000):
                raise ValueError("first_result_or_history_binding_changed")
            search, context = report["result"]["search"], report["result"]["context"]
            if (search["query"] != report["query"] or search["selected_versions"] != pairs
                    or search["top_k"] != 5 or prepare_context(search, max_chars=8000) != context
                    or score_case(current[case_id], report) != entry["machine_score"]):
                raise ValueError("first_search_context_or_score_changed")
            run_ids.add(report["run_id"])
            records.append({"case_id": case_id, "status": "completed", "source_batch_id": batch_id,
                            "answerable": current[case_id]["answerable"],
                            "expected_target_count": len(current[case_id]["expected_evidence"]),
                            "source_result_path": path.relative_to(root).as_posix(), "source_result_sha256": sha(path),
                            "source_history_report": entry["source_history_report"], "source_history_sha256": sha(history),
                            "source_run_id": report["run_id"], "embedding_requests": 0,
                            "embedding_statistics": {"embedding_requests": 0, "total_tokens": 0}, "llm_requests": 0,
                            "comparisons": {"5": {"search": deepcopy(search), "context": deepcopy(context),
                                                  "score": target_score(current[case_id], search, context)}}})
    if len(records) != 16 or len({r["case_id"] for r in records}) != 16:
        raise ValueError("first_sixteen_not_unique")
    return records, bindings


def compare_search(case, search):
    """Score fixed prefixes after search; never feed annotations to retrieval."""
    if search.get("top_k") != 20 or search.get("query") != case["question"]:
        raise ValueError("top_twenty_search_binding_changed")
    results = search.get("results")
    if (not isinstance(results, list) or len(results) > 20
            or [r.get("rank") for r in results] != list(range(1, len(results) + 1))):
        raise ValueError("invalid_ranked_top_twenty")
    # Validate all top-20 candidates once before taking any prefixes.
    prepare_context(search, max_chars=8000)
    comparisons = {}
    for k in (5, 10, 20):
        prefix = deepcopy(search)
        prefix.update(top_k=k, results=deepcopy(results[:k]), returned_count=len(results[:k]),
                      statistics_scope="shared_single_top20_request_do_not_sum_across_prefixes")
        context = prepare_context(prefix, max_chars=8000)
        comparisons[str(k)] = {"search": prefix, "context": context,
                                "score": target_score(case, prefix, context)}
    return comparisons


def _live_factory(root, chosen):
    """Lazy imports: offline mode does not read settings or open Qdrant."""
    from qdrant_client import QdrantClient
    from paper_assistant.config import EmbeddingSettings, load_embedding_settings
    from paper_assistant.indexing import make_index_profile
    from paper_assistant.retrieval import QdrantStore
    from paper_assistant.search import EvidenceSearcher
    from paper_assistant.storage import PaperStore
    profile = read_json(root / "data/index/current_profile.json")
    public = EmbeddingSettings(backend=profile["recipe"]["backend"], model=profile["recipe"]["model"],
                               api_key=None, base_url=profile["recipe"]["base_url"], dimension=profile["recipe"]["dimension"])
    if (make_index_profile(public) != profile or profile != read_json(root / "data/index/profiles" / (profile["index_profile_id"] + ".json"))):
        raise ValueError("index_profile_identity_mismatch")
    settings = load_embedding_settings()
    if make_index_profile(settings) != profile or not (root / "data/index/qdrant/meta.json").is_file():
        raise ValueError("embedding_profile_or_index_missing")
    stack = ExitStack()
    try:
        store = stack.enter_context(PaperStore(root / "data/index/papers.sqlite3", read_only=True))
        qdrant = stack.enter_context(closing(QdrantClient(path=str(root / "data/index/qdrant"))))
        if not qdrant.collection_exists(profile["collection_name"]):
            raise ValueError("missing_collection")
        vectors = stack.enter_context(QdrantStore(root / "data/index/qdrant", profile["collection_name"],
                                                profile["index_profile_id"], profile["recipe"]["dimension"], client=qdrant))
        searcher = EvidenceSearcher(store, vectors, settings, profile)
        ready = {v["paper_id"]: [] for v in store.list_versions()}
        for v in store.list_versions():
            state = store.get_index_import(v["paper_id"], v["parse_revision"], profile["index_profile_id"])
            if state and state["status"] == "ready" and state["completed_count"] == v["chunk_count"] and v["chunk_count"] > 0:
                ready[v["paper_id"]].append(v["parse_revision"])
        if any(len(ready.get(p, [])) != 1 for c in chosen for p in c["paper_ids"]):
            raise ValueError("selected_paper_ready_version_not_unique")
        pairs = {p: revisions[0] for p, revisions in ready.items() if len(revisions) == 1}
        # Preflight every selected complete range before any embedding request.
        for case in chosen:
            searcher._ready_filter([(p, pairs[p]) for p in case["paper_ids"]])
        return stack, searcher, pairs, profile
    except Exception:
        stack.close()
        raise


def _usage(records):
    values = [r.get("embedding_requests") for r in records]
    known = [v for v in values if type(v) is int and v >= 0]
    tokens = [(r.get("embedding_statistics") or {}).get("total_tokens") for r in records]
    known_tokens = [v for v in tokens if type(v) is int and v >= 0]
    return {"embedding_requests": sum(known) if len(known) == len(values) else None,
            "known_embedding_requests": sum(known), "unknown_request_records": len(values) - len(known),
            "embedding_tokens": sum(known_tokens) if len(known_tokens) == len(tokens) else None,
            "known_embedding_tokens": sum(known_tokens), "unknown_token_records": len(tokens) - len(known_tokens),
            "llm_requests": 0, "automatic_retries": 0}


def _save_summary(batch, manifest, records):
    metrics = {str(k): summarize(records, k) for k in manifest["reported_top_k"]}
    scored_count = sum(r.get("status") == "completed"
                       and all(str(k) in r.get("comparisons", {}) for k in manifest["reported_top_k"])
                       for r in records)
    entire_dev = set(manifest["planned_case_ids"]) == set(manifest["input_binding"]["current_dev_case_ids"])
    summary = {"batch_id": manifest["batch_id"], "mode": manifest["mode"], "status": manifest["status"],
               "attempted_count": len(records), "scored_count": scored_count,
               "failed_attempted_count": len(records) - scored_count,
               "is_qa_accuracy": False, "qa_accuracy": None,
               "task_c_live_comparison_completed": manifest["mode"] == "live" and manifest["status"] == "completed" and entire_dev,
               "task_c_completed": False, "completed_batch_covers_entire_current_dev": entire_dev and manifest["status"] == "completed",
               "historical_first_run_aggregation": manifest["mode"] == "from_first_runs",
               "input_binding_sha256": manifest["input_binding_sha256"],
               "case_ids": [r["case_id"] for r in records], "metrics": metrics, "new_usage": _usage(records)}
    atomic_json(batch / "manifest.json", manifest)
    atomic_json(batch / "summary.json", summary)
    lines = ["# D6 开发集检索观察", "", "这些是检索标注代理指标，不是问答准确率。", "",
             "模式：" + manifest["mode"] + "；状态：" + manifest["status"] + "。", "",
             "离线模式汇总两个已保存首次批次的 top-5，不构成新的统一批次或真实 top-10/top-20 实验。" if manifest["mode"] == "from_first_runs" else "同一题仅一次 top-20 检索，比较固定排序的 5/10/20 前缀；不生成答案。", "",
             "| top-k | Returned 全部标注命中 | Shown 全部标注命中 | Returned 引文命中 | Shown 引文命中 |",
             "|---|---|---|---|---|"]
    for k, m in metrics.items():
        pairs = [m[n] for n in ("exact_all_targets_hit_returned", "exact_all_targets_hit_shown", "exact_quote_hit_returned", "exact_quote_hit_shown")]
        lines.append("| " + k + " | " + " | ".join(f"{p['numerator']}/{p['denominator']}" for p in pairs) + " |")
    lines += ["", "完整候选、展示正文、标注命中和失败状态保存在 results/。无标注的负例不进入命中率分母。",
              "", "已尝试但检索或评分失败的可答题仍进入题目和引文命中分母，按未命中计算；未尝试题另列。",
              "", "本次调用与未知用量见 summary.json 的 new_usage；原首次批次的旧费用不计为本次调用。", ""]
    atomic_text(batch / "summary.md", "\n".join(lines))
    return summary


def run_batch(batch_id, *, live=False, case_ids=None, root=ROOT, live_factory=_live_factory):
    if not isinstance(batch_id, str) or not SAFE_ID.fullmatch(batch_id):
        raise ValueError("invalid_batch_id")
    cases = dev_cases(root)
    if case_ids is not None and (not live or not case_ids or len(set(case_ids)) != len(case_ids) or any(c not in {x["case_id"] for x in cases} for c in case_ids)):
        raise ValueError("invalid_case_selection")
    selected = [c for c in cases if case_ids is None or c["case_id"] in case_ids]
    # Offline verification completes before creating any output folder.
    offline_records, historical = ([], {}) if live else verified_first_runs(root, cases)
    binding = {"version": VERSION, "mode": "live" if live else "from_first_runs", 
               "current_dev_case_ids": [c["case_id"] for c in cases],
               "selected_case_ids": [c["case_id"] for c in selected] if live else list(OLD_IDS + NEW_IDS),
               "current_dev_cases": deepcopy(cases), "historical_first_batches": historical,
               "rubric": deepcopy(RUBRIC)}
    parent = root / "artifacts/d6/retrieval_comparison"
    parent.mkdir(parents=True, exist_ok=True)
    batch = parent / batch_id
    batch.mkdir()  # Never reuse or delete an existing paid/offline batch.
    (batch / "results").mkdir()
    (batch / "reservations").mkdir()
    manifest = {"task": "D6-C-retrieval-comparison", "batch_id": batch_id, "created_at_utc": now(),
                "mode": binding["mode"], "input_binding": binding, "input_binding_sha256": digest(binding),
                "reported_top_k": [5, 10, 20] if live else [5], "status": "prepared", "results": {},
                "planned_case_ids": binding["selected_case_ids"], "completed_case_ids": [],
                "unattempted_case_ids": binding["selected_case_ids"], "changed_inputs": [],
                "error": None, "live_authorized_by_flag": live}
    exclusive_json(batch / "manifest.initial.json", manifest)
    exclusive_json(batch / "rubric.json", RUBRIC)
    records, resource_stack = [], None
    try:
        if not live:
            records = offline_records
        else:
            resource_stack, searcher, pair_map, profile = live_factory(root, selected)
            manifest["index_profile"] = deepcopy(profile)
            for case in selected:
                case_id = case["case_id"]
                pairs = [(p, pair_map[p]) for p in case["paper_ids"]]
                exclusive_json(batch / "reservations" / (case_id + ".json"),
                               {"case_id": case_id, "reserved_at_utc": now(), "question_sha256": digest(case["question"]),
                                "selected_versions": pairs, "top_k": 20,
                                "interruption_rule": "Request may have occurred. Do not auto-resume or rerun."})
                record = {"case_id": case_id, "status": "tool_error", "started_at_utc": now(),
                          "answerable": case["answerable"], "expected_target_count": len(case["expected_evidence"]),
                          "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in pairs],
                          "embedding_requests": None, "embedding_statistics": None, "llm_requests": 0,
                          "error": None, "comparisons": {}}
                try:
                    search = searcher.search_evidence(case["question"], pairs, top_k=20)
                    record["search_top_twenty"] = deepcopy(search)
                    record["embedding_statistics"] = deepcopy(search["statistics"])
                    record["embedding_requests"] = search["statistics"].get("embedding_requests")
                    if search["selected_versions"] != record["selected_versions"]:
                        raise ValueError("selected_version_mismatch")
                    record["comparisons"] = compare_search(case, search)
                    record["status"] = "completed"
                except Exception as error:
                    from paper_assistant.search import SearchError
                    if isinstance(error, SearchError):
                        record["embedding_statistics"] = deepcopy(error.statistics)
                        record["embedding_requests"] = error.statistics.get("embedding_requests")
                        record["failure_stage"] = error.stage
                    record["error"] = {"code": "retrieval_or_scoring_failure", "message": "本题失败；已发生统计保留，未知统计为 null，不自动重跑。"}
                record["finished_at_utc"] = now()
                records.append(record)
                exclusive_json(batch / "results" / (case_id + ".json"), record)
                manifest["status"] = "running" if record["status"] == "completed" else "needs_attention"
                manifest["completed_case_ids"] = [r["case_id"] for r in records if r["status"] == "completed"]
                manifest["unattempted_case_ids"] = [c["case_id"] for c in selected if c["case_id"] not in {r["case_id"] for r in records}]
                _save_summary(batch, manifest, records)
                if record["status"] != "completed":
                    break
        if resource_stack is not None:
            resource_stack.close()
            resource_stack = None
        manifest["status"] = "completed" if len(records) == len(binding["selected_case_ids"]) and all(r["status"] == "completed" for r in records) else "needs_attention"
    except Exception:
        manifest["status"] = "needs_attention"
        manifest["error"] = {"code": "resources_inputs_or_export_failure", "message": "批次失败或中断风险；保存现有记录，不自动重跑。"}
    finally:
        if resource_stack is not None:
            try:
                resource_stack.close()
            except Exception:
                manifest["status"] = "needs_attention"
                manifest["error"] = {"code": "cleanup_failure", "message": "资源清理失败，已发生调用统计保留。"}
    try:
        for record in records:
            path = batch / "results" / (record["case_id"] + ".json")
            if not path.is_file():
                exclusive_json(path, record)
            if read_json(path) != record:
                raise ValueError("saved_result_changed")
            manifest["results"][record["case_id"]] = {"path": path.relative_to(batch).as_posix(), "sha256": sha(path), "status": record["status"]}
        manifest["completed_case_ids"] = [r["case_id"] for r in records if r["status"] == "completed"]
        manifest["unattempted_case_ids"] = [c for c in binding["selected_case_ids"] if c not in {r["case_id"] for r in records}]
        manifest["finished_at_utc"] = now()
        return _save_summary(batch, manifest, records)
    except Exception as error:
        raise BatchExportError({"status": "needs_attention", "code": "final_export_failure",
                                "message": "导出失败；终端保留本轮完整记录和实际/未知用量，不自动重跑。",
                                "batch_id": batch_id, "new_usage": _usage(records),
                                "manifest": manifest, "records": records}) from error


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--from-first-runs", action="store_true", help="离线汇总固定旧十题及新六题首次 top-5；不会完成 C 的真实 top-k 对照")
    mode.add_argument("--live", action="store_true", help="使用额度：每道开发题一次 embedding/top-20，无聊天、自动重试或验收题调优")
    parser.add_argument("--batch-id", required=True, help="新的安全批次名；已有目录一律拒绝，无 --resume")
    parser.add_argument("--case-id", action="append", help="仅 live 可重复选择开发题，默认全部 dev；不得重复")
    args = parser.parse_args(argv)
    if not SAFE_ID.fullmatch(args.batch_id):
        parser.error("batch-id 必须是 1–64 位安全字母数字、下划线或短横线")
    if args.case_id and (not args.live or len(set(args.case_id)) != len(args.case_id)):
        parser.error("case-id 只用于 live 且不能重复")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = run_batch(args.batch_id, live=args.live, case_ids=args.case_id)
    except BatchExportError as error:
        print(json.dumps(error.payload, ensure_ascii=False, indent=2, allow_nan=False))
        return 1
    except Exception:
        print(json.dumps({"status": "needs_attention", "code": "preflight_or_export_failure",
                          "message": "输入校验、批次已存在或写盘失败；请检查已有记录，不自动重跑。"}, ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
