"""D3 任务 C 的查询入口：少量候选元数据，不自动下载全文。"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from paper_assistant.arxiv_client import ArxivClient, ArxivError, LOCAL_FALLBACK


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "artifacts" / "d3" / "arxiv"
LOG_DIR = PROJECT_ROOT / "archive" / "run_logs" / "arxiv"


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索 arXiv 候选论文或查询指定版本")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--query", help='arXiv 查询式，例如 all:"retrieval augmented generation"')
    choice.add_argument("--id-list", help="逗号分隔的编号，例如 2210.03629v3")
    parser.add_argument("--max-results", type=int, default=3, help="返回 1–10 条候选，默认 3")
    parser.add_argument("--timeout", type=float, default=20, help="单次网络读/连接超时秒数，默认 20")
    args = parser.parse_args()
    # 上海当前使用 UTC+08:00；标准库固定偏移避免 Windows 依赖 tzdata。
    timestamp = datetime.now(timezone(timedelta(hours=8)))
    report = {"operation": "search", "ran_at": timestamp.isoformat(),
              "query": args.query, "id_list": args.id_list, "max_results": args.max_results}
    started = time.monotonic()
    client = None
    try:
        with ArxivClient(rate_dir=REPORT_DIR, cache_dir=REPORT_DIR / "cache",
                         timeout_seconds=args.timeout) as client:
            identifiers = [value.strip() for value in args.id_list.split(",")] if args.id_list else None
            report.update(client.search(query=args.query, id_list=identifiers, max_results=args.max_results))
        print(f"[OK] {report['status']}：{len(report['papers'])} 条候选；缓存={report['cache_hit']}")
        for paper in report["papers"]:
            print(f"  {paper['paper_id']} | {paper['title']}\n  {paper['source_url']}")
        exit_code = 0
    except (ArxivError, OSError, ValueError) as error:
        report.update({"status": getattr(error, "status", "io_error"), "error": str(error),
                       "network_request_count": client.request_count if client else 0,
                       "local_fallback": LOCAL_FALLBACK})
        print(f"[FAIL] {report['status']}：{error}\n{LOCAL_FALLBACK}")
        exit_code = 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"search_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"运行记录：{path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
