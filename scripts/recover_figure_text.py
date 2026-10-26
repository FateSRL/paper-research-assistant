"""只读源 PDF，保存 Figure 1 恢复结果，并同步整页可读文本预览。"""

import argparse
import json
from pathlib import Path

import pymupdf

from paper_assistant.figure_recovery import (
    FigureRecoveryError, recover_page_figure, preview_markdown, panels_sha256,
    recovered_page_preview,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """运行固定页恢复；退出码 0=库存内完整恢复，1=未解决项，2=前置失败。

    不导入 config，不读取 .env，不联网。派生文件独立保存，源 PDF 和
    data/parsed 中的正文 JSONL 都保持原样。AI 输出视觉核对需另行记录。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=PROJECT_ROOT / "data/papers/2210.03629v3.pdf")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "artifacts/d3/figure_recovery")
    args = parser.parse_args()
    try:
        result = recover_page_figure(args.pdf)
    except FigureRecoveryError as exc:
        print(f"恢复无法开始：{exc}")
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # AI 视觉核对是一次单独进行的工作，不由脚本凭“运行成功”推断。
    # 已有核对记录只有同时绑定相同 PDF、文件页和恢复分区哈希才可沿用；
    # 任意恢复内容/坐标变化后，状态自动回到 pending_output_comparison。
    review_path = args.output_dir / "ai-review.json"
    if review_path.is_file():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if (
                review.get("pdf_sha256") == result["pdf_sha256"]
                and review.get("paper_id") == result["paper_id"]
                and review.get("pdf_page") == result["pdf_page"]
                and review.get("recovered_panels_sha256") == panels_sha256(result)
                and review.get("reviewed_by") == "codex_ai"
                and review.get("status") == "completed"
            ):
                result["ai_visual_review"] = {
                    "status": "completed", "review_record": str(review_path),
                    "reviewed_by": review["reviewed_by"], "reviewed_at": review.get("reviewed_at"),
                    "output_comparison_panels": review.get("output_comparison_panels", []),
                    "record_source_and_panels_hash_verified": True,
                }
        except (OSError, ValueError, AttributeError) as exc:
            print(f"已有 AI 核对记录不可用，保持待核对状态：{exc}")
    stem = "arxiv_2210.03629v3.page_2"
    json_path = args.output_dir / f"{stem}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / f"{stem}.md").write_text(preview_markdown(result), encoding="utf-8")
    # 高分辨率原页图用于对照，图中文字未被覆盖或替换。
    with pymupdf.open(args.pdf) as doc:
        doc[1].get_pixmap(matrix=pymupdf.Matrix(3, 3)).save(args.output_dir / "page-2.png")
    # 最初的 page_previews/*.txt 是原生抽取快照，之前没有接入恢复结果。
    # 默认运行时同时更新用户常看的整页预览；自定义输出时所有新增文件
    # 留在自定义目录内，避免意外修改项目的默认预览。原始快照只备份一次。
    if not result["unresolved"]:
        if args.output_dir.resolve() == (PROJECT_ROOT / "artifacts/d3/figure_recovery").resolve():
            preview_path = PROJECT_ROOT / "artifacts/d3/page_previews/arxiv_2210.03629v3_page_2.txt"
            raw_backup = PROJECT_ROOT / "archive/artifacts/d3/page_previews/arxiv_2210.03629v3_page_2.raw.txt"
        else:
            preview_path = args.output_dir / "arxiv_2210.03629v3_page_2.txt"
            raw_backup = args.output_dir / "archive" / preview_path.with_suffix(".raw.txt").name
        try:
            # 原始乱码快照统一留在归档区，不再与当前可读预览并排显示。
            readable = recovered_page_preview(args.pdf, result, raw_backup_display_path=str(raw_backup))
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            raw_backup.parent.mkdir(parents=True, exist_ok=True)
            if not raw_backup.exists():
                if (preview_path.exists()
                        and b"preview_kind: recovered_display_preview_v1" not in preview_path.read_bytes()):
                    # 保存旧文件的精确字节，避免丢掉最初的乱码/顺序证据。
                    original = preview_path.read_bytes()
                else:
                    with pymupdf.open(args.pdf) as doc:
                        original = doc[1].get_text("text").encode("utf-8")
                raw_backup.write_bytes(original)
            preview_path.write_text(readable, encoding="utf-8")
        except (FigureRecoveryError, OSError) as exc:
            print(f"整页预览未更新：{exc}")
            return 2
        print(f"整页可读预览：{preview_path}")
    print(f"恢复状态：{result['status']}")
    print(f"逐字符统计：{result['statistics']}")
    print(f"派生结果：{json_path}")
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
