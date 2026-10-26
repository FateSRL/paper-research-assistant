"""D3：筛查原始逐页文本，另存质量过滤结果和排除报告。"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from paper_assistant.quality import (
    FILTER_REVISION, count_bad_controls, filter_paper_pages, iter_indexable_segments,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl_atomic(path: Path, records: list[dict]) -> None:
    """先完整写临时文件，再替换派生输出，避免中途失败留下半份成功文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        for row in records:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="按区域与字符质量筛查 PDF 文本")
    parser.add_argument("--corpus", default="eval/corpus.json")
    parser.add_argument("--input-dir", default="data/parsed")
    parser.add_argument("--output-dir", default="data/filtered")
    parser.add_argument("--rules", default="eval/quality_rules.json")
    args = parser.parse_args()

    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    protected = [
        (PROJECT_ROOT / args.input_dir).resolve(),
        (PROJECT_ROOT / "data/parsed").resolve(),
        (PROJECT_ROOT / "data/papers").resolve(),
    ]
    if any(output_dir == path or output_dir.is_relative_to(path) for path in protected):
        parser.error("派生输出必须使用独立目录，不能覆盖原始解析目录或 PDF 目录")

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "filter_revision": FILTER_REVISION,
        "status": "failed",
        "papers": [],
        "original_parsed_files_preserved": True,
        "recovered_figure_automatically_indexed": False,
        "limitation": "自动筛查不是全部页的人工准确性验证，数学/图形布局仍受限",
    }
    failed = 0
    try:
        corpus = json.loads((PROJECT_ROOT / args.corpus).read_text(encoding="utf-8-sig"))
        rules = json.loads((PROJECT_ROOT / args.rules).read_text(encoding="utf-8-sig"))
        if not isinstance(corpus, list) or not corpus:
            raise ValueError("语料清单必须是非空数组")
        for paper in corpus:
            entry = {"paper_id": paper["paper_id"], "status": "failed"}
            try:
                source = PROJECT_ROOT / args.input_dir / f"{paper['paper_id']}.jsonl"
                original_bytes = source.read_bytes()
                pages = [
                    json.loads(line) for line in original_bytes.decode("utf-8").splitlines()
                    if line.strip()
                ]
                filtered = filter_paper_pages(paper, pages, PROJECT_ROOT, rules)
                # 通过后续分块入口再次检查，确保 CLI 产物确实可以被该入口读取。
                eligible = list(iter_indexable_segments(filtered))
                destination = output_dir / f"{paper['paper_id']}.jsonl"
                _write_jsonl_atomic(destination, filtered)
                if source.read_bytes() != original_bytes:
                    raise RuntimeError("原始解析文件意外变化")
                affected = [
                    {
                        "pdf_page": row["pdf_page"],
                        "excluded_line_count": len(row["excluded_lines"]),
                        "reasons": sorted({
                            reason for item in row["excluded_lines"] for reason in item["reasons"]
                        }),
                    }
                    for row in filtered if row["excluded_lines"]
                ]
                entry.update({
                    "status": "success",
                    "pages": len(filtered),
                    "indexable_pages": sum(row["indexable"] for row in filtered),
                    "indexable_segments": len(eligible),
                    "excluded_line_count": sum(len(row["excluded_lines"]) for row in filtered),
                    "raw_non_layout_c0_count": sum(count_bad_controls(row["text"]) for row in pages),
                    "remaining_non_layout_c0_count": sum(count_bad_controls(row["text"]) for row in filtered),
                    "affected_pages": affected,
                    "source_jsonl_sha256": hashlib.sha256(original_bytes).hexdigest(),
                    "output_file": str(destination),
                })
                print(
                    f"[OK] {paper['paper_id']}：{len(filtered)} 页，"
                    f"{len(eligible)} 可用片段，排除 {entry['excluded_line_count']} 行"
                )
            except Exception as error:
                failed += 1
                entry["error"] = str(error)
                print(f"[FAIL] {paper['paper_id']}：{error}")
            report["papers"].append(entry)
        report["status"] = "success" if failed == 0 else "partial_failure"
    except Exception as error:
        failed += 1
        report["error"] = str(error)
        print(f"[FAIL] {error}")

    target = PROJECT_ROOT / "artifacts/d3/quality_filter_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"报告：{target}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

