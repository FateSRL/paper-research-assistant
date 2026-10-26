"""Create D9's three structurally reviewed ranges; never touch PDFs or indexes.

The explicit block choices below were visually checked against original PDFs.
They are document structure selections, independent of question sets/answers.
New source bytes require a new review; the existing registry is not overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_assistant.source_scope import REGISTRY_VERSION, Registry, _lines

POPLER = Path("C:/Users/ggy/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")
REVIEWED = (
    ("arxiv_2005.11401v4", "r_269ac0cb1263292d", 7, 8, 9, "23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233"),
    ("arxiv_2210.03629v3", "r_22af23d03fcb87a8", 4, 5, 6, "f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69"),
    ("arxiv_2303.11366v4", "r_d7736b29a2d8b39e", 10, 11, 12, "6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd"),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_source_regions(project_root=ROOT):
    root = Path(project_root).resolve()
    destination = root / "artifacts/d9/source_regions.json"
    if destination.exists():
        raise FileExistsError("Existing registry requires a separately reviewed version; no overwrite")
    documents = []
    evidence_dir = root / "artifacts/d9/source_region_review"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    chunks_by_id = {}
    for paper, revision, heading, body, following, reviewed_sha in REVIEWED:
        base = root / "data/chunks" / paper / revision
        metadata = json.loads((base / "paper.json").read_text(encoding="utf-8"))
        paths = {"pdf": root / metadata["local_path"], "parsed": root / "data/parsed" / (paper + ".jsonl"),
                 "filtered": root / "data/filtered" / (paper + ".jsonl"), "chunks": base / "chunks.jsonl",
                 "snapshot_raw": base / "raw.pages.jsonl", "snapshot_filtered": base / "filtered.pages.jsonl",
                 "manifest": base / "version_manifest.json", "paper": base / "paper.json"}
        if sha(paths["pdf"]) != reviewed_sha:
            raise ValueError("PDF differs from the visually reviewed structural source")
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        for name in ("chunks.jsonl", "filtered.pages.jsonl", "raw.pages.jsonl", "paper.json"):
            if sha(base / name) != manifest["files"][name]["sha256"]:
                raise ValueError("Immutable snapshot differs from its manifest")
        filtered = [json.loads(line) for line in paths["filtered"].read_text(encoding="utf-8").splitlines()]
        segment = next(s for p in filtered if p["pdf_page"] == 1 for s in p["segments"] if s["source_block_index"] == body)
        image = evidence_dir / (paper + "_page1.png")
        if not image.exists():
            if not POPLER.is_file():
                raise FileNotFoundError("Reviewed Poppler renderer is unavailable")
            subprocess.run([str(POPLER), "-f", "1", "-l", "1", "-singlefile", "-scale-to", "1600", "-png",
                            str(paths["pdf"]), str(image.with_suffix(""))], check=True, capture_output=True)
        with fitz.open(paths["pdf"]) as pdf:
            blocks = pdf[0].get_text("dict")["blocks"]
            if (_lines(blocks[heading]).strip().casefold() != "abstract"
                    or _lines(blocks[body], segment["source_line_indices"]) != segment["text"]):
                raise ValueError("Reviewed structure differs from current extraction")
            proof = {"review_basis": "original_pdf_visual_and_exact_parse_filter_comparison",
                     "reviewer": "AI structural review; not an independent human review",
                     "heading_block_index": heading, "body_block_index": body,
                     "following_heading_block_index": following,
                     "heading_text_sha256": hashlib.sha256(_lines(blocks[heading]).encode()).hexdigest(),
                     "following_heading_text_sha256": hashlib.sha256(_lines(blocks[following]).encode()).hexdigest(),
                     "visual_evidence": {"path": image.relative_to(root).as_posix(), "sha256": sha(image)},
                     "renderer": "Poppler pdftoppm; page selection is for review, not qualification",
                     "segment_bbox_is_exact_chunk_box": False}
        files = {name: {"path": path.relative_to(root).as_posix(), "sha256": sha(path)} for name, path in paths.items()}
        region = {"scope": "abstract", "pdf_page": 1, "segment_id": segment["segment_id"],
                  "source_block_index": body, "source_line_indices": segment["source_line_indices"],
                  "segment_char_start": 0, "segment_char_end": len(segment["text"]),
                  "text_sha256": hashlib.sha256(segment["text"].encode()).hexdigest(),
                  "verification_status": "verified", "verification_method": "AI_structural_review",
                  "human_review_status": "pending", "structural_evidence": proof}
        documents.append({"paper_id": paper, "parse_revision": revision, "pdf_sha256": reviewed_sha,
                          "parsed_input_sha256": files["parsed"]["sha256"], "filtered_input_sha256": files["filtered"]["sha256"],
                          "chunk_snapshot_sha256": files["chunks"]["sha256"], "files": files, "regions": [region]})
        for line in paths["chunks"].read_text(encoding="utf-8").splitlines():
            chunk = json.loads(line)
            chunks_by_id[chunk["chunk_id"]] = chunk
    payload = {"schema_revision": REGISTRY_VERSION, "document_scope": "three_existing_full_paper_revision_pairs",
               "coordinate_system": "Python Unicode code points within immutable filtered segment",
               "review_scope": "PDF structure and exact source ranges; no QA semantic accuracy claim",
               "AI_structural_review_completed": True, "independent_human_review": "pending",
               "online_question_labels_used": False, "API_requests": 0, "documents": documents}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    class SnapshotStore:
        def get_chunk(self, identifier):
            return chunks_by_id.get(identifier)
    registry = Registry(root, SnapshotStore(), [(r[0], r[1]) for r in REVIEWED])
    lines = ["# D9 B 来源范围核定表", "", "三篇原始 PDF 已进行 AI 结构核定，人审仍 pending。范围表证明摘要位置，不能证明答案语义支持。", "",
             f"Registry SHA256：`{registry.registry_sha256}`。", "", "|论文/解析版本|PDF页序|block/行|segment字符范围|完整合格chunks|结构证据|", "|---|---:|---|---|---:|---|"]
    for document in documents:
        region = document["regions"][0]
        eligible = registry.qualified_chunk_ids([(document["paper_id"], document["parse_revision"])])
        image = region["structural_evidence"]["visual_evidence"]["path"]
        lines.append(f"|{document['paper_id']} / {document['parse_revision']}|1|{region['source_block_index']} / {region['source_line_indices'][0]}–{region['source_line_indices'][-1]}|[0,{region['segment_char_end']})|{len(eligible)}|[首页核定图]({image.removeprefix('artifacts/d9/')})|")
    lines += ["", "资格按固定版本、PDF/解析/过滤/chunk SHA、segment及完整字符范围核验；第1页、Abstract词、相似度、模型自标签均不构成资格。",
              "", "chunk 横跨已核范围为 mixed；表存在但范围未 verified 为 unknown/正常范围不足。表缺失、身份或哈希损坏为 tool_error。人审 rejected 必须令 verification_status 同为 rejected。",
              "", "本轮只读取原 PDF 和不可变快照，并生成新核定文件。未运行 embedding/chat、正式题集或验收；原 PDF、解析、过滤、分块、SQLite、Qdrant 均未修改。"]
    with destination.with_suffix(".md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return payload


def verify_source_regions(project_root=ROOT):
    """Repeat current bindings/qualification checks read-only, without rebuild."""
    root = Path(project_root).resolve()
    document = json.loads((root / "artifacts/d9/source_regions.json").read_text(encoding="utf-8"))
    chunks = {}
    pairs = [(d["paper_id"], d["parse_revision"]) for d in document["documents"]]
    for doc in document["documents"]:
        for line in (root / doc["files"]["chunks"]["path"]).read_text(encoding="utf-8").splitlines():
            chunk = json.loads(line)
            chunks[chunk["chunk_id"]] = chunk
    class SnapshotStore:
        def get_chunk(self, identifier):
            return chunks.get(identifier)
    registry = Registry(root, SnapshotStore(), pairs)
    counts = []
    for pair in pairs:
        row = {"paper_id": pair[0], "parse_revision": pair[1], "abstract_full": 0, "body": 0, "mixed": 0, "unknown": 0}
        for chunk in chunks.values():
            if (chunk["paper_id"], chunk["parse_revision"]) == pair:
                row[registry._coverage(chunk)] += 1
        row["total_chunks"] = sum(row[k] for k in ("abstract_full", "body", "mixed", "unknown"))
        counts.append(row)
    return {"status": "valid", "registry_sha256": registry.registry_sha256,
            "API_requests": 0, "database_opened": False, "counts": counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Read-only bindings/coverage check; does not recreate the registry")
    arguments = parser.parse_args()
    if arguments.verify:
        print(json.dumps(verify_source_regions(), ensure_ascii=False, indent=2))
    else:
        build_source_regions()
        print("Created source_regions.json/.md; offline structural verification only")
