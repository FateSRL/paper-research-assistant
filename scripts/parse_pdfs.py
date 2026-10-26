"""D3 任务 A 的命令行入口：读取清单、解析 PDF、保存结果和报告。"""

import argparse
import json
from pathlib import Path

from paper_assistant.ingest import parse_pdf_pages, save_page_records


# __file__ 是当前脚本的位置。
# parents[0] 是 scripts 目录，parents[1] 是独立项目根目录。
# 因此路径定位不依赖启动时所在的终端目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """组织整个处理流程，返回程序退出码。"""

    # argparse 将命令行参数转换为 Python 中可以使用的值。
    parser = argparse.ArgumentParser(description="解析清单中的本地 PDF")

    parser.add_argument(
        "--corpus",
        default="eval/corpus.json",
        help="语料清单路径，相对项目根目录",
    )
    parser.add_argument(
        "--output-dir",
        default="data/parsed",
        help="逐页 JSONL 输出目录，相对项目根目录",
    )
    parser.add_argument(
        "--paper-id",
        default=None,
        help="只处理指定论文；不填写时处理清单中的全部论文",
    )

    args = parser.parse_args()

    corpus_path = PROJECT_ROOT / args.corpus
    output_dir = PROJECT_ROOT / args.output_dir

    # utf-8-sig 兼容普通 UTF-8 和 Windows 编辑器可能加入的 BOM。
    try:
        corpus = json.loads(corpus_path.read_text(encoding="utf-8-sig"))

        if not isinstance(corpus, list) or not corpus:
            raise ValueError("语料清单必须是非空 JSON 数组")

    except (OSError, ValueError) as error:
        print(f"[FAIL] 无法读取语料清单：{error}")
        return 1

    # 提供 --paper-id 时，从清单中选出对应论文。
    if args.paper_id is not None:
        corpus = [
            paper
            for paper in corpus
            if paper["paper_id"] == args.paper_id
        ]

        if not corpus:
            print(f"[FAIL] 清单中没有这篇论文：{args.paper_id}")
            return 1

    results = []
    failed_count = 0

    for paper in corpus:
        paper_id = paper["paper_id"]

        try:
            # 核心函数返回数据，本入口负责组织保存和报告。
            page_records = parse_pdf_pages(paper, PROJECT_ROOT)

            output_path = output_dir / f"{paper_id}.jsonl"
            save_page_records(page_records, output_path)

            # strip() 仅用于统计空文本页面，不改变保存的原文。
            empty_page_count = sum(
                not record["text"].strip()
                for record in page_records
            )

            results.append(
                {
                    "paper_id": paper_id,
                    "status": "success",
                    "page_count": len(page_records),
                    "empty_page_count": empty_page_count,
                    "output_file": str(output_path),
                }
            )

            print(
                f"[OK] {paper_id}："
                f"{len(page_records)} 页，"
                f"空文本页 {empty_page_count}，"
                f"输出 {output_path}"
            )

        except Exception as error:
            # 在单篇处理的边界捕获错误。
            # 记录这一篇失败，然后继续处理其他论文。
            failed_count += 1

            results.append(
                {
                    "paper_id": paper_id,
                    "status": "failed",
                    "error": str(error),
                }
            )

            print(f"[FAIL] {paper_id}：{error}")

    report = {
        "processed_count": len(results),
        "success_count": len(results) - failed_count,
        "failed_count": failed_count,
        "papers": results,
    }

    report_path = (
        PROJECT_ROOT / "artifacts" / "d3" / "pdf_parse_report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"处理报告：{report_path}")

    # 0 表示全部处理成功；1 表示至少有一篇失败。
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())