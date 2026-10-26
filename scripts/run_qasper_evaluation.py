"""Prepare QASPER locally; PDF import and current-runtime runs are explicit actions."""

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from paper_assistant.agent_comparison import MODES, run_current_case
from paper_assistant.agent_export import _identifier
from paper_assistant.answer_export import atomic_text
from paper_assistant.context import DIRECT_ANSWER_RULES
from paper_assistant import qasper_evaluation as qasper


ROOT = Path(__file__).resolve().parents[1]
SEED = 20261020
ENGLISH_INSTRUCTION = (
    "Please answer in English. Provide direct_answer in the same answer object, "
    "and keep the explanation and all actual supporting citations in claims.\n"
    + DIRECT_ANSWER_RULES
)
DATA_SOURCE = "https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-train-dev-v0.3.tgz"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    atomic_text(Path(path), json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _sample_path(root, sample_id):
    return Path(root).resolve() / "eval/qasper" / _identifier(sample_id)


def _batch_path(root, batch_id):
    return Path(root).resolve() / "artifacts/v2/qasper" / _identifier(batch_id)


def prepare(sample_id, raw_path, *, split, count, seed=SEED, project_root=ROOT):
    """Select fixed questions from a local official JSON; make no service calls."""
    root = Path(project_root).resolve()
    sample = qasper.prepare_sample(_read(raw_path), split=split, count=count, seed=seed)
    sample.update(sample_id=sample_id, source={"dataset": "AllenAI QASPER", "version": "0.3",
        "url": DATA_SOURCE, "dataset_card": "https://huggingface.co/datasets/allenai/qasper",
        "license": "CC BY 4.0", "raw_path": str(Path(raw_path).resolve())},
        experiment_scope="QASPER text subset on explicitly identified local PDFs; not a full official leaderboard reproduction.")
    path = _sample_path(root, sample_id)
    path.mkdir(parents=True, exist_ok=False)
    _write(path / "sample.json", sample)
    papers = {identifier: {"qasper_paper_id": identifier, "title": paper.get("title"),
        "status": "pending_pdf", "source_url": "https://arxiv.org/abs/" + identifier,
        "candidate_pdf_url": "https://arxiv.org/pdf/" + identifier,
        "pdf_path": None, "pdf_version": None, "paper_id": None, "parse_revision": None,
        "mapping": None} for identifier, paper in sample["papers"].items()}
    _write(path / "papers.json", {"papers": papers,
        "note": "Supply the actual PDF source and explicit version. Candidate URLs do not establish a version match. No PDF has been downloaded or imported."})
    return {"status": "prepared", "sample_id": sample_id, "path": path.relative_to(root).as_posix(),
            "question_count": len(sample["cases"]), "paper_count": len(papers),
            "selection": sample["selection"], "pending_paper_count": len(papers), "real_api_calls": 0}


def import_papers(sample_id, papers_path, *, project_root=ROOT, importer=None, store_factory=None):
    """Explicitly import supplied real PDFs, or reuse explicitly named ready versions."""
    from paper_assistant import d9_runtime, import_runtime
    from paper_assistant.storage import PaperStore

    root = Path(project_root).resolve()
    folder = _sample_path(root, sample_id)
    sample, bindings = _read(folder / "sample.json"), _read(folder / "papers.json")
    supplied = _read(papers_path)["papers"]
    ready_pairs = {(row["paper_id"], row["parse_revision"])
                   for row in d9_runtime.list_ready_versions(project_root=root)}
    import_pdf = importer or import_runtime.import_pdf
    open_store = store_factory or (lambda project: PaperStore(project / "data/index/papers.sqlite3", read_only=True))
    for identifier, paper in sample["papers"].items():
        if identifier not in supplied:
            continue
        entry = {**bindings["papers"][identifier], **supplied[identifier]}
        bindings["papers"][identifier] = entry
        if not entry.get("pdf_version") or not entry.get("source_url"):
            entry["status"] = "pending_version"
            _write(folder / "papers.json", bindings)
            continue
        pair = entry.get("paper_id"), entry.get("parse_revision")
        if all(pair):
            if pair not in ready_pairs:
                entry["status"] = "not_ready"
                _write(folder / "papers.json", bindings)
                continue
            entry["status"] = "ready"
        elif entry.get("pdf_path"):
            pdf = Path(entry["pdf_path"])
            if not pdf.is_absolute():
                pdf = Path(papers_path).resolve().parent / pdf
            if not pdf.is_file():
                entry["status"] = "pending_pdf"
                _write(folder / "papers.json", bindings)
                continue
            imported = import_pdf(pdf.read_bytes(), pdf.name, title=paper.get("title"),
                                  source_url=entry["source_url"], project_root=root)
            entry["import_result"] = imported
            entry["status"] = imported["status"]
            if imported["status"] != "ready":
                _write(folder / "papers.json", bindings)
                continue
            entry.update(paper_id=imported["paper_id"], parse_revision=imported["parse_revision"], pdf_path=str(pdf))
        else:
            entry["status"] = "pending_pdf"
            _write(folder / "papers.json", bindings)
            continue
        # Read only this selected version. The existing store owns source
        # identity; QASPER mapping adds no hash or PDF revalidation mechanism.
        _write(folder / "papers.json", bindings)
        try:
            with open_store(root) as store:
                chunks = store.get_version_chunks(entry["paper_id"], entry["parse_revision"])
                parents, sources = [], []
                if any(chunk.get("source_spans") for chunk in chunks):
                    parents = store.get_version_parents(entry["paper_id"], entry["parse_revision"])
                    row = store.connection.execute(
                        "SELECT manifest_json FROM parse_versions WHERE paper_id = ? AND parse_revision = ?",
                        (entry["paper_id"], entry["parse_revision"])).fetchone()
                    metadata = json.loads(row["manifest_json"])
                    source_path = metadata.get("source_paths", {}).get("sources")
                    sources = ([json.loads(line) for line in (root / source_path).read_text(encoding="utf-8").splitlines()]
                               if source_path else [])
            entry["mapping"] = qasper.build_paragraph_mapping(
                paper["full_text"], chunks, parents=parents, sources=sources, abstract=paper.get("abstract"))
        except Exception:
            entry["mapping"] = qasper.build_paragraph_mapping(paper["full_text"], [], abstract=paper.get("abstract"))
            entry["mapping_error"] = "selected_version_text_unavailable"
        _write(folder / "papers.json", bindings)
    return {"sample_id": sample_id, "ready_papers": sum(entry["status"] == "ready" for entry in bindings["papers"].values()),
            "pending_papers": [identifier for identifier, entry in bindings["papers"].items() if entry["status"] != "ready"],
            "path": (folder / "papers.json").relative_to(root).as_posix()}


def run(sample_id, batch_id, *, project_root=ROOT, runtime_runner=None, modes=None):
    """Explicit current-runtime execution. Gold data never enters the runner."""
    from paper_assistant import d9_runtime

    root = Path(project_root).resolve()
    selected_modes = MODES if modes is None else tuple(modes)
    folder = _sample_path(root, sample_id)
    sample, bindings = _read(folder / "sample.json"), _read(folder / "papers.json")
    path = _batch_path(root, batch_id)
    path.mkdir(parents=True, exist_ok=False)
    _write(path / "input.json", {"batch_id": batch_id, "sample_id": sample_id,
        "question_ids": [case["question_id"] for case in sample["cases"]],
        "modes": list(selected_modes), "evaluation_protocol": qasper.EVALUATION_PROTOCOL,
        "english_instruction": ENGLISH_INSTRUCTION, "created_at_utc": datetime.now(timezone.utc).isoformat()})
    state = {"status": "running", "attempted_question_ids": [], "completed_question_ids": [],
             "remaining_question_ids": [case["question_id"] for case in sample["cases"]], "not_ready": {}}
    _write(path / "state.json", state)
    call_runtime = runtime_runner or d9_runtime.run_question
    try:
        for case in sample["cases"]:
            identifier = case["question_id"]
            binding = bindings["papers"][case["paper_id"]]
            if binding["status"] != "ready":
                state["not_ready"][identifier] = binding["status"]
                continue
            record = {"question_id": identifier, "question": case["question"],
                "actual_question": case["question"], "answer_instructions": ENGLISH_INSTRUCTION,
                "evaluation_protocol": qasper.EVALUATION_PROTOCOL,
                "pair": {"pipeline": "current", "selected_modes": list(selected_modes), "modes": {}}}
            state["attempted_question_ids"].append(identifier)
            state["remaining_question_ids"].remove(identifier)
            _write(path / "state.json", state)

            def save_mode(mode, report):
                record["pair"]["modes"][mode] = deepcopy(report)
                _write(path / (identifier + ".json"), record)

            def invoke(question, versions, *, mode, **options):
                save_mode(mode, {"mode": mode, "status": "tool_error", "stop_reason": "runtime_incomplete",
                    "result": {"status": "tool_error", "answer": None}})
                return call_runtime(question, versions, mode=mode, **options)

            record["pair"] = run_current_case(record["actual_question"],
                [(binding["paper_id"], binding["parse_revision"])], project_root=root,
                runtime_runner=invoke, on_mode_result=save_mode, modes=selected_modes,
                answer_instructions=record["answer_instructions"])
            record["predictions"] = {mode: qasper.extract_prediction(report,
                                        evaluation_protocol=qasper.EVALUATION_PROTOCOL)
                                     for mode, report in record["pair"]["modes"].items()}
            _write(path / (identifier + ".json"), record)
            state["completed_question_ids"].append(identifier)
            _write(path / "state.json", state)
            if record["pair"]["status"] != "completed":
                state["status"] = "attention_required"
                break
        if state["status"] == "running":
            state["status"] = "partial" if state["remaining_question_ids"] else "completed"
    except (Exception, KeyboardInterrupt):
        state.update(status="attention_required", error="qasper_run_interrupted")
    _write(path / "state.json", state)
    return score(batch_id, project_root=root)


def score(batch_id, *, project_root=ROOT):
    """Score saved final outputs and mappings without opening any runtime or PDF."""
    root = Path(project_root).resolve()
    path = _batch_path(root, batch_id)
    inputs, state = _read(path / "input.json"), _read(path / "state.json")
    selected_modes = tuple(inputs.get("modes", MODES))
    evaluation_protocol = inputs.get("evaluation_protocol")
    folder = _sample_path(root, inputs["sample_id"])
    sample, bindings = _read(folder / "sample.json"), _read(folder / "papers.json")
    cases = {case["question_id"]: case for case in sample["cases"]}
    records = []
    for identifier in inputs["question_ids"]:
        record_path = path / (identifier + ".json")
        if not record_path.exists():
            continue
        record = _read(record_path)
        case = cases[identifier]
        mapping = bindings["papers"][case["paper_id"]].get("mapping")
        record["scores"] = {mode: qasper.score_qasper_case(case, report, mapping,
                                evaluation_protocol=evaluation_protocol)
                            for mode, report in record["pair"]["modes"].items() if mode in selected_modes}
        _write(record_path, record)
        records.append(record)
    summary = qasper.summarize_qasper(sample, records, bindings,
                                    modes=selected_modes, evaluation_protocol=evaluation_protocol)
    summary.update(batch_id=batch_id, sample_id=inputs["sample_id"], status=state["status"], state=state)
    _write(path / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="QASPER：默认 prepare；import-papers／run 显式发起入库／真实问答，score 纯离线")
    parser.add_argument("action", choices=("prepare", "import-papers", "run", "score"), nargs="?", default="prepare")
    parser.add_argument("--sample-id")
    parser.add_argument("--raw", type=Path, help="本地官方 qasper-train-v0.3.json 或 qasper-dev-v0.3.json")
    parser.add_argument("--split", choices=("train", "dev", "validation"), default="train")
    parser.add_argument("--count", type=int)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--papers", type=Path, help="真实 PDF 或已有 ready 配对的普通 JSON 对应表")
    parser.add_argument("--batch-id")
    parser.add_argument("--modes", nargs="+", choices=MODES,
                        help="run 实际执行的模式；省略时兼容双模式，score 从保存的 input 恢复")
    args = parser.parse_args(argv)
    if args.action != "score" and not args.sample_id:
        parser.error("需要 --sample-id；prepare 还需 --raw 本地官方 JSON，不会隐式下载论文或调用模型")
    if args.action == "prepare" and not args.raw:
        parser.error("prepare 需要 --raw 本地官方 JSON；官方数据来源：" + DATA_SOURCE)
    if args.action == "import-papers" and not args.papers:
        parser.error("import-papers 需要 --papers，明确实际 PDF 来源与版本或已有 ready 配对")
    if args.action in ("run", "score") and not args.batch_id:
        parser.error(args.action + " 需要 --batch-id")
    try:
        with redirect_stdout(sys.stderr):
            if args.action == "prepare":
                count = args.count if args.count is not None else (20 if args.split == "train" else 100)
                report = prepare(args.sample_id, args.raw, split=args.split, count=count, seed=args.seed, project_root=ROOT)
            elif args.action == "import-papers":
                report = import_papers(args.sample_id, args.papers, project_root=ROOT)
            elif args.action == "run":
                report = run(args.sample_id, args.batch_id, project_root=ROOT, modes=args.modes)
            else:
                report = score(args.batch_id, project_root=ROOT)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report.get("status") not in ("attention_required", "failed") else 1
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "failed", "action": args.action,
                          "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
