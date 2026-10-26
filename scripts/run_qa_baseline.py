"""D5 F：顺序初跑正式开发集，每题真实调用一次已有 CLI，保留失败且不重发。

默认只准备批次与冻结评分规则；--live 才会启动真实 CLI。先用 --case-id
选四题，再 --resume --live 继续余题。中断后的预占题须人工检查，绝不自动重跑。
"""

import argparse
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from uuid import uuid4

from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.config import load_embedding_settings, load_llm_settings
from paper_assistant.evaluation import MACHINE_RUBRIC, score_case, summarize_case_scores
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.llm_client import ChatPolicy


ROOT = Path(__file__).resolve().parents[1]
READY_PAIRS = {"arxiv_2005.11401v4": "r_269ac0cb1263292d", "arxiv_2210.03629v3": "r_22af23d03fcb87a8",
               "arxiv_2303.11366v4": "r_d7736b29a2d8b39e"}
FIRST_FOUR = ["D2-001", "D2-005", "D2-003", "D2-006"]
SOURCES = ["paper_assistant/answer_export.py", "paper_assistant/citations.py", "paper_assistant/config.py",
           "paper_assistant/context.py", "paper_assistant/embedding_client.py", "paper_assistant/generation.py",
           "paper_assistant/indexing.py", "paper_assistant/llm_client.py", "paper_assistant/rag.py",
           "paper_assistant/retrieval.py", "paper_assistant/schemas.py", "paper_assistant/search.py",
           "paper_assistant/storage.py", "scripts/answer_question.py", "paper_assistant/evaluation.py",
           "scripts/run_qa_baseline.py"]
RUNNER_VERSION = "d5-qa-baseline-v1"
CLI_STATUSES = {"answered", "insufficient_evidence", "invalid_output", "tool_error", "budget_exceeded"}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def binding(root=ROOT):
    """Read-only binding. Secrets are neither serialized nor hashed."""
    raw = (root / "eval/dev.jsonl").read_text(encoding="utf-8")
    cases = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("duplicate_case_id")
    for case in cases:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case["case_id"]):
            raise ValueError("unsafe_case_id")
        if case.get("review_status") != "human_verified" or type(case.get("answerable")) is not bool:
            raise ValueError("unconfirmed_case")
        if not case.get("question", "").strip() or not 1 <= len(case["paper_ids"]) <= 3:
            raise ValueError("invalid_case")
        if len(set(case["paper_ids"])) != len(case["paper_ids"]) or any(p not in READY_PAIRS for p in case["paper_ids"]):
            raise ValueError("invalid_scope")
    ids = [c["case_id"] for c in cases]
    if not all(c in ids for c in FIRST_FOUR):
        raise ValueError("missing_representatives")
    order = FIRST_FOUR + [c for c in ids if c not in FIRST_FOUR]
    cases = sorted(cases, key=lambda c: order.index(c["case_id"]))
    profile = read_json(root / "data/index/current_profile.json")
    if profile != read_json(root / "data/index/profiles" / (profile["index_profile_id"] + ".json")):
        raise ValueError("profile_pointer_mismatch")
    embedding = load_embedding_settings()
    if make_index_profile(embedding) != profile:
        raise ValueError("embedding_profile_mismatch")
    settings = load_llm_settings()
    public_chat = {"provider": settings.provider, "model_id": settings.model_id,
                   "base_url": settings.base_url, "configured_timeout": settings.timeout}
    with closing(sqlite3.connect((root / "data/index/papers.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT paper_id,parse_revision,completed_count FROM index_imports WHERE status='ready' AND index_profile_id=?", (profile["index_profile_id"],)).fetchall()
    ready = {(p, r): count for p, r, count in rows}
    if any((p, r) not in ready or ready[(p, r)] <= 0 for p, r in READY_PAIRS.items()):
        raise ValueError("version_not_ready")
    return {"runner_version": RUNNER_VERSION, "input_binding_version": "question-parameters-v1",
            "cases": cases, "case_order": order,
            "selected_versions": [{"paper_id": p, "parse_revision": r, "ready_chunk_count": ready[(p, r)]} for p, r in READY_PAIRS.items()],
            "index_profile": profile, "chat_configuration": public_chat, "policy": asdict(ChatPolicy()),
            "top_k": 5, "max_chars": 8000,
            "rubric": deepcopy(MACHINE_RUBRIC),
            "input_isolation": "Only original question and explicit fixed ready pairs enter answer_question CLI; annotations are post-hoc only."}


def cli_command(case, *, python=sys.executable):
    command = [python, "-X", "utf8", "-m", "scripts.answer_question", "--query", case["question"],
               "--top-k", "5", "--max-chars", "8000", "--json"]
    for paper in case["paper_ids"]:
        command += ["--version", paper, READY_PAIRS[paper]]
    return command


def _safe_capture(value):
    value = value if isinstance(value, str) else ""
    return {"characters": len(value),
            "content": None, "reason": "Unparsed process output is not persisted to avoid unsafe exception text."}


def capture_case(case, frozen, *, run_process=subprocess.run, root=ROOT):
    """Invoke once, including nonzero exits; unknown usage stays unknown."""
    started = now()
    entry = {"case_id": case["case_id"], "attempt_status": "runner_failure", "started_at_utc": started,
             "finished_at_utc": None, "exit_code": None, "run_id": None, "report": None,
             "stdout": None, "stderr_capture": None, "source_history_report": None,
             "source_history_verified": False, "runner_error": None}
    try:
        completed = run_process(cli_command(case), cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        entry["exit_code"] = completed.returncode
        entry["stderr_capture"] = _safe_capture(completed.stderr)
        try:
            report = json.loads(completed.stdout)
            if not isinstance(report, dict) or report.get("status") not in CLI_STATUSES or not isinstance(report.get("run_id"), str):
                raise ValueError("not_cli_record")
        except (ValueError, TypeError, AttributeError):
            entry["stdout_capture"] = _safe_capture(completed.stdout)
            entry["runner_error"] = {"code": "cli_json_or_binding_failure", "message": "CLI 未提供与本题输入一致的合法机器记录；请求和用量未知，禁止自动重跑"}
        else:
            entry.update(attempt_status="completed", stdout=completed.stdout, report=report, run_id=report["run_id"])
            expected_pairs = [{"paper_id": p, "parse_revision": READY_PAIRS[p]} for p in case["paper_ids"]]
            configuration = report.get("configuration") or {}
            chat = configuration.get("chat") or {}
            chat_expected = frozen["chat_configuration"]
            mismatches = []
            if report.get("query") != case["question"] or report.get("selected_versions") != expected_pairs:
                mismatches.append("input")
            if report.get("top_k") != frozen["top_k"] or report.get("max_chars") != frozen["max_chars"] or report.get("policy") != frozen["policy"]:
                mismatches.append("policy")
            # Early tool failures can lack configuration/profile; keep their paid evidence but require inspection.
            if report.get("index_profile") != frozen["index_profile"]:
                mismatches.append("profile")
            if any(chat.get(k) != chat_expected[k] for k in ("provider", "model_id", "configured_timeout")):
                mismatches.append("chat_configuration")
            if mismatches:
                entry["attempt_status"] = "needs_attention"
                entry["runner_error"] = {"code": "cli_record_binding_mismatch", "mismatches": mismatches,
                                         "message": "已保留完整原始记录与已发生用量；本题运行绑定不一致，禁止自动重跑"}
            history = report.get("history_report")
            if isinstance(history, str) and history.startswith("archive/run_logs/d5/answer_") and ".." not in Path(history).parts:
                entry["source_history_report"] = history
                try:
                    entry["source_history_verified"] = read_json(root / history) == report
                except (OSError, ValueError):
                    pass
            if not entry["source_history_verified"]:
                entry["attempt_status"] = "needs_attention"
                entry.setdefault("runner_warnings", []).append("source_history_not_verified")
    except Exception:
        entry["attempt_status"] = "needs_attention" if entry["report"] is not None else "runner_failure"
        entry["runner_error"] = {"code": "process_failure", "message": "CLI 子进程运行或读取失败；是否已请求及实际用量未知，禁止自动重跑"}
    entry["finished_at_utc"] = now()
    entry["machine_score"] = score_case(case, entry["report"])
    return entry


def refresh(batch_dir, manifest):
    scores = []
    completed = []
    attention = []
    for case in manifest["binding"]["cases"]:
        case_id = case["case_id"]
        result_file = batch_dir / "results" / (case_id + ".json")
        reservation = batch_dir / "reservations" / (case_id + ".json")
        if result_file.exists():
            entry = read_json(result_file)
            report = entry.get("report")
            if (entry.get("case_id") != case_id or (report is not None and
                    (report.get("status") not in CLI_STATUSES or report.get("query") != case["question"]))):
                raise ValueError("case_record_mismatch")
            completed.append(case_id)
            if entry["attempt_status"] != "completed":
                attention.append(case_id)
            scores.append(entry["machine_score"])
            manifest["results"][case_id] = {"attempt_status": entry["attempt_status"], "exit_code": entry["exit_code"],
                                            "run_id": entry["run_id"], "result_path": result_file.relative_to(batch_dir).as_posix(),
                                            "source_history_report": entry["source_history_report"],
                                            "source_history_verified": entry["source_history_verified"]}
        elif reservation.exists():
            attention.append(case_id)
    manifest.update(completed_case_ids=completed, unattempted_case_ids=[c for c in manifest["binding"]["case_order"] if c not in completed and c not in attention],
                    needs_attention_case_ids=attention, updated_at_utc=now())
    manifest["status"] = "needs_attention" if attention else ("completed_first_attempts" if len(completed) == len(manifest["binding"]["cases"]) else "prepared_or_partial")
    summary = summarize_case_scores(scores, manifest["binding"]["cases"])
    summary.update(batch_id=manifest["batch_id"], needs_attention_case_ids=attention,
                   per_case=scores, binding_sha256=manifest["binding_sha256"])
    atomic_json(batch_dir / "manifest.json", manifest)
    atomic_json(batch_dir / "summary.json", summary)
    rows = ["# D5 F 开发集初跑机器观察", "", "机器指标不是问答准确率；引用定位不等于语义支持，人工评分待完成。", "",
            f"批次：{manifest['batch_id']}；已尝试 {len(scores)}/{len(manifest['binding']['cases'])}。", "",
            "| 题目 | 程序终态 | 返回/展示全部精确标注引文 | 合法/输出引用 |", "|---|---|---|---|"]
    for s in scores:
        c = s["citation_location"]
        rows.append(f"| {s['case_id']} | {s['status']} | {s['exact_all_targets_hit_returned']} / {s['exact_all_targets_hit_shown']} | {c['numerator']}/{c['denominator']} |")
    rows += ["", "精确引文只规范空白；未命中不等于没有语义依据。无答案题不进入引文命中分母。",
             "", "用量、各题命中与失败完整统计见 summary.json；原始运行见 results/。",
             "", "需要人工处理的已预占/中断题：" + (", ".join(attention) or "无") + "。", ""]
    atomic_text(batch_dir / "summary.md", "\n".join(rows))
    return manifest


def run_batch(batch_id, *, live=False, resume=False, case_ids=None, root=ROOT,
              make_binding=binding, run_process=subprocess.run):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", batch_id):
        raise ValueError("unsafe_batch_id")
    frozen = make_binding(root)
    chosen = case_ids or frozen["case_order"]
    if len(set(chosen)) != len(chosen) or any(c not in frozen["case_order"] for c in chosen):
        raise ValueError("invalid_case_selection")
    parent = root / "artifacts/d5/qa_baseline"
    parent.mkdir(parents=True, exist_ok=True)
    batch_dir = parent / batch_id
    if resume:
        manifest = read_json(batch_dir / "manifest.json")
        if manifest.get("binding") != frozen or manifest.get("binding_sha256") != digest(frozen):
            raise ValueError("resume_binding_changed")
        initial = read_json(batch_dir / "manifest.initial.json")
        if initial["binding"] != frozen or initial["binding_sha256"] != digest(frozen) or read_json(batch_dir / "rubric.json") != frozen["rubric"]:
            raise ValueError("frozen_files_changed")
    else:
        batch_dir.mkdir()  # Existing batches are never reset or reused implicitly.
        manifest = {"task": "D5-F-QA-baseline", "batch_id": batch_id, "created_at_utc": now(),
                    "binding": frozen, "binding_sha256": digest(frozen), "results": {}, "status": "prepared",
                    "completed_case_ids": [], "unattempted_case_ids": frozen["case_order"], "needs_attention_case_ids": []}
        exclusive_json(batch_dir / "manifest.initial.json", manifest)
        exclusive_json(batch_dir / "rubric.json", frozen["rubric"])
        atomic_json(batch_dir / "manifest.json", manifest)
    lock = parent / ".runner.lock"
    exclusive_json(lock, {"batch_id": batch_id, "started_at_utc": now(), "owner": uuid4().hex,
                          "interruption_rule": "Stale lock requires inspection; no automatic paid rerun."})
    try:
        manifest = refresh(batch_dir, manifest)
        if manifest["needs_attention_case_ids"]:
            return manifest
        if not live:
            return manifest
        chosen = sorted(chosen, key=frozen["case_order"].index)
        for case_id in chosen:
            if case_id in manifest["completed_case_ids"]:
                continue
            # Check current binding before every paid call, including changed model/profile/source.
            if make_binding(root) != frozen:
                raise ValueError("binding_changed_before_case")
            case = next(c for c in frozen["cases"] if c["case_id"] == case_id)
            exclusive_json(batch_dir / "reservations" / (case_id + ".json"),
                           {"case_id": case_id, "reserved_at_utc": now(), "status": "may_have_requested",
                            "binding_sha256": manifest["binding_sha256"], "rule": "If no result exists, needs_attention; never retry automatically."})
            manifest = refresh(batch_dir, manifest)
            entry = capture_case(case, frozen, run_process=run_process, root=root)
            exclusive_json(batch_dir / "results" / (case_id + ".json"), entry)
            manifest = refresh(batch_dir, manifest)
            print(json.dumps({"case_id": case_id, "exit_code": entry["exit_code"], "status": entry["machine_score"]["status"],
                              "run_id": entry["run_id"], "completed": len(manifest["completed_case_ids"])}, ensure_ascii=False), flush=True)
            if entry["attempt_status"] != "completed":
                break  # Unknown service costs deserve inspection before any more paid calls.
        return manifest
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True, help="安全批次名，新建或显式恢复同批")
    parser.add_argument("--live", action="store_true", help="启动真实问答 CLI，会使用模型额度")
    parser.add_argument("--resume", action="store_true", help="校验绑定后继续未尝试题；已尝试失败也不重跑")
    parser.add_argument("--case-id", action="append", help="可重复，仅选择正式题目；按冻结题序运行")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.batch_id):
        parser.error("batch-id 仅允许字母、数字、下划线和连字符，最多 64 字符")
    try:
        result = run_batch(args.batch_id, live=args.live, resume=args.resume, case_ids=args.case_id)
    except Exception:
        print(json.dumps({"status": "runner_error", "message": "批次目录、冻结绑定、占用或记录异常；没有自动重发。检查已有 manifest/reservations/results 后再处理。"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"batch_id": result["batch_id"], "status": result["status"],
                      "completed_case_ids": result["completed_case_ids"], "unattempted_case_ids": result["unattempted_case_ids"],
                      "needs_attention_case_ids": result["needs_attention_case_ids"]}, ensure_ascii=False, indent=2))
    return 1 if result["needs_attention_case_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
