"""D4 任务 B 的单篇命令入口：只做分块和快照，不进行向量入库。"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from paper_assistant.chunking import (
    ChunkingConfig, SAFE_ID, prepare_chunk_version, pretty_json_bytes, save_chunk_version,
    sha256_bytes,
)
from paper_assistant.human_review import REVIEW_RECORD, review_for_chunk_samples


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def select_preview_samples(prepared) -> list[dict]:
    """选择最多十个有代表性的块，预览和人审核对共用同一份顺序。"""
    chunks = prepared.chunks
    sample_ids = set()
    samples = []

    def add(chunk: dict) -> None:
        if chunk["chunk_id"] not in sample_ids and len(samples) < 10:
            samples.append(chunk)
            sample_ids.add(chunk["chunk_id"])

    # 摘要的长片段最能展示窗口切分，先同时展示它的全部子块。
    counts = {}
    for chunk in chunks:
        counts[chunk["segment_id"]] = counts.get(chunk["segment_id"], 0) + 1
    for chunk in chunks:
        if counts[chunk["segment_id"]] > 1:
            add(chunk)
    # 再选取不同页的较长正文块，避免十个样本全是第一页的标题。
    for page in (1, 3, 4, 8, 12, 19):
        candidates = [chunk for chunk in chunks if chunk["pdf_page"] == page]
        if candidates:
            add(max(candidates, key=lambda item: len(item["text"])))
    for chunk in chunks:
        add(chunk)

    return samples


def chunk_preview(prepared) -> str:
    """展示样本，并且只复用与当前版本、来源和样本完全匹配的人审。"""
    samples = select_preview_samples(prepared)
    review = review_for_chunk_samples(prepared, PROJECT_ROOT, samples=samples)
    if review["human_review_status"] == "human_verified":
        review_note = (
            f"用户已于 {review['human_reviewed_at']} 核对以下十条样本，状态 human_verified。"
            "确认范围是这十条抽样，不表示全部 chunk 逐条人工检查。"
        )
    else:
        review_note = (
            f"以下样本由程序抽取，人工对照状态 {review['human_review_status']}。"
            "新版本、不同样本或无效确认记录需要重新核对。"
        )

    stats = prepared.manifest["statistics"]
    lines = [
        f"# D4 单篇分块预览：{prepared.paper_id}", "",
        f"处理版本：`{prepared.parse_revision}`。{stats['page_count']} 页、"
        f"{stats['segment_count']} 个父片段、{stats['chunk_count']} 个 chunk。", "",
        review_note + "文本保留原换行和断词；长度单位是字符。"
        "bbox 与行索引表示父片段来源，不是精确句子区域。", "",
        f"[人工确认记录](/{(PROJECT_ROOT / REVIEW_RECORD).as_posix()})", "",
        f"[完整版本清单](/{prepared.output_dir.as_posix()}/version_manifest.json)", "",
    ]
    for number, chunk in enumerate(samples, 1):
        lines += [
            f"## 样本 {number}：PDF 文件页 {chunk['pdf_page']}", "",
            f"- chunk：`{chunk['chunk_id']}`",
            f"- 父片段：`{chunk['segment_id']}`",
            f"- 字符范围：`[{chunk['char_start']}, {chunk['char_end']})`，长度 {len(chunk['text'])}",
            f"- 文本 SHA-256：`{chunk['text_sha256']}`", "",
            "```text", chunk["text"], "```", "",
        ]
    return "\n".join(lines) + "\n"


def write_current_reports(report: dict) -> Path:
    """按论文保存执行记录，总入口汇总全部论文，避免后跑的覆盖先跑的。

    旧的单篇总报告会先迁入对应论文记录，旧预览也保留为单篇文件。
    后续单篇命令只更新自己的记录，再重新生成总表和预览目录。
    """
    target = PROJECT_ROOT / "artifacts/d4"
    reports_dir = target / "chunk_reports"
    previews_dir = target / "chunk_previews"
    reports_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)
    report_path = target / "chunking_report.json"
    preview_path = target / "chunk_preview.md"
    if report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8-sig"))
        previous_id = previous.get("paper_id")
        if isinstance(previous_id, str) and SAFE_ID.fullmatch(previous_id):
            old_record = reports_dir / f"{previous_id}.json"
            if not old_record.exists():
                old_record.write_bytes(report_path.read_bytes())
            old_preview = previews_dir / f"{previous_id}.md"
            if preview_path.is_file() and not old_preview.exists():
                old_preview.write_bytes(preview_path.read_bytes())

    paper_id = report["paper_id"]
    # 非法参数的失败也要留记录，但不能把任意命令行字符串拼成路径。
    file_key = paper_id if SAFE_ID.fullmatch(paper_id) else "invalid_" + sha256_bytes(paper_id.encode("utf-8"))[:16]
    (reports_dir / f"{file_key}.json").write_bytes(pretty_json_bytes(report))
    papers = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(reports_dir.glob("*.json"))]
    successful = [paper for paper in papers if paper["status"] == "success"]
    corpus = json.loads((PROJECT_ROOT / "eval/corpus.json").read_text(encoding="utf-8-sig"))
    expected_ids = {paper["paper_id"] for paper in corpus}
    complete = expected_ids <= {paper["paper_id"] for paper in successful}
    # 总状态只覆盖成功输出的各篇抽样；缺少论文或任一篇未确认都不能宣称全通过。
    reviewed = [paper for paper in successful if paper.get("human_review_status") == "human_verified"]
    human_status = (
        "human_verified" if complete and len(reviewed) == len(successful)
        else "outdated" if any(paper.get("human_review_status") == "outdated" for paper in successful)
        else "pending"
    )
    summary = {
        "task": "D4-B-corpus-chunking",
        "status": "success" if complete and all(paper["status"] == "success" for paper in papers) else "partial_success" if successful else "failed",
        "last_run_paper_id": paper_id,
        "target_paper_count": len(expected_ids),
        "successful_paper_count": len(successful),
        "totals": {key: sum(paper["statistics"][key] for paper in successful) for key in (
            "page_count", "segment_count", "chunk_count", "split_segment_count",
        )},
        "papers": papers,
        "human_review_status": human_status,
        "human_review_record": REVIEW_RECORD,
        "human_review_scope": "B: ten preview samples per paper only; not all chunks",
        "human_reviewed_paper_count": len(reviewed),
        "index_status": "chunks_only",
        "network_requests": 0,
        "embedding_requests": 0,
    }
    report_path.write_bytes(pretty_json_bytes(summary))
    lines = [
        "# D4 分块预览目录", "",
        f"每篇保留独立的十条抽样。当前汇总人工状态为 {human_status}，"
        f"已确认 {len(reviewed)} 篇抽样；确认范围不是全部 chunk。", "",
        f"[人工确认记录](/{(PROJECT_ROOT / REVIEW_RECORD).as_posix()})", "",
        "| 论文 | 页数 | 父片段 | chunk | 处理版本 | 人工状态 | 预览 |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for paper in successful:
        stats = paper["statistics"]
        link = "/" + (previews_dir / f"{paper['paper_id']}.md").as_posix()
        lines.append(
            f"| {paper['paper_id']} | {stats['page_count']} | {stats['segment_count']} | "
            f"{stats['chunk_count']} | `{paper['parse_revision']}` | "
            f"{paper.get('human_review_status', 'pending')} | [十条样本]({link}) |"
        )
    lines += ["", f"已成功生成 {len(successful)} 篇，共 {summary['totals']['chunk_count']} 个 chunk。", ""]
    preview_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report_path


def main() -> int:
    """读取参数、调用核心函数、保存当前报告，并返回退出码。

    main 是实际命令流程：它不是仅用于测试的函数。没有通过来源核对
    就返回 1；成功写入或成功复用版本返回 0，终端可以检查 LASTEXITCODE。
    """
    parser = argparse.ArgumentParser(description="从已过滤片段生成单篇版本化 chunks")
    parser.add_argument("--paper-id", required=True, help="与 eval/corpus.json 一致的论文 ID")
    parser.add_argument("--max-chars", type=int, default=1600, help="每块的字符上限，不是 token")
    parser.add_argument("--overlap-chars", type=int, default=200, help="同一父片段内的重叠字符数")
    parser.add_argument("--dry-run", action="store_true", help="完成核对并展示统计，不生成文件")
    args = parser.parse_args()

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "D4-B-single-paper-chunking",
        "paper_id": args.paper_id,
        "status": "failed",
        "network_requests": 0,
        "embedding_requests": 0,
        "human_review_status": "pending",
    }
    try:
        config = ChunkingConfig(args.max_chars, args.overlap_chars)
        corpus = json.loads((PROJECT_ROOT / "eval/corpus.json").read_text(encoding="utf-8-sig"))
        if not isinstance(corpus, list) or any(not isinstance(paper, dict) for paper in corpus):
            raise ValueError("corpus.json 必须是论文对象数组")
        matches = [paper for paper in corpus if paper.get("paper_id") == args.paper_id]
        if len(matches) != 1:
            raise ValueError("指定 paper_id 必须在清单中出现且仅出现一次")
        prepared = prepare_chunk_version(matches[0], PROJECT_ROOT, config)
        if args.dry_run:
            print(f"[DRY RUN] {prepared.paper_id}：{prepared.parse_revision}")
            print(json.dumps(prepared.manifest["statistics"], ensure_ascii=False, indent=2))
            print(f"计划输出：{prepared.output_dir}（未写入文件）")
            return 0

        reused = save_chunk_version(prepared)
        report.update({
            "status": "success",
            "parse_revision": prepared.parse_revision,
            "recipe_sha256": prepared.manifest["recipe_sha256"],
            "reused_existing_version": reused,
            "output_dir": str(prepared.output_dir),
            "statistics": prepared.manifest["statistics"],
            "snapshot_files": list(prepared.files),
            "length_unit": "characters, not tokens",
            "source_validation": "fixed PDF/raw text/filtered pages/current quality rules agree",
            "index_status": "chunks_only",
        })
        report.update(review_for_chunk_samples(
            prepared, PROJECT_ROOT, samples=select_preview_samples(prepared),
        ))
        target = PROJECT_ROOT / "artifacts/d4"
        previews = target / "chunk_previews"
        previews.mkdir(parents=True, exist_ok=True)
        (previews / f"{prepared.paper_id}.md").write_text(chunk_preview(prepared), encoding="utf-8", newline="\n")
        print(
            f"[OK] {prepared.paper_id}：{report['statistics']['page_count']} 页，"
            f"{report['statistics']['segment_count']} 个片段 → {len(prepared.chunks)} 个 chunk"
        )
        print(f"处理版本：{prepared.parse_revision}；{'复用已有版本' if reused else '首次保存'}")
        print(f"输出：{prepared.output_dir}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        print(f"[FAIL] {error}")

    # dry-run 包括失败路径都不写结果；普通模式保存当前执行结果。
    if not args.dry_run:
        report_path = write_current_reports(report)
        report_bytes = pretty_json_bytes(report)
        # 当前目录只有最新报告；重复试验记录进入之前约定的统一归档。
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        history = PROJECT_ROOT / "archive/run_logs/d4" / f"chunking_{stamp}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_bytes(report_bytes)
        print(f"报告：{report_path}")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
