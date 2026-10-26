"""D3 任务 C 的下载入口：明确选择一个固定版本，保留本地固定语料。"""

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
    parser = argparse.ArgumentParser(description="下载一篇明确版本的 arXiv PDF 并验证")
    parser.add_argument("--arxiv-id", required=True, help="必须带版本，例如 2210.03629v3")
    parser.add_argument("--output-dir", default="archive/run_outputs/download_checks", help="相对项目根目录；默认归档测试下载，不能写入 data/papers")
    parser.add_argument("--timeout", type=float, default=20, help="单次网络读/连接超时秒数，默认 20")
    parser.add_argument("--max-mib", type=int, default=20, help="流式下载大小上限，默认 20 MiB，最多 50")
    args = parser.parse_args()
    # 上海当前使用 UTC+08:00，无需为 Windows 额外安装时区数据包。
    timestamp = datetime.now(timezone(timedelta(hours=8)))
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    report = {"operation": "download", "ran_at": timestamp.isoformat(), "selected_id": args.arxiv_id,
              "output_dir": str(output_dir), "max_mib": args.max_mib}
    started = time.monotonic()
    client = None
    try:
        with ArxivClient(rate_dir=REPORT_DIR, timeout_seconds=args.timeout) as client:
            report.update(client.download_pdf(args.arxiv_id, output_dir,
                                              max_bytes=args.max_mib * 1024 * 1024))
        print(f"[OK] {report['status']}：{report['paper_id']}，{report['page_count']} 页")
        print(f"SHA-256：{report['pdf_sha256']}\nPDF：{report['local_path']}")
        print("检查仅说明所选版本文件可打开；阅读顺序、公式和图表仍需质量核对。")
        exit_code = 0
    except (ArxivError, OSError, ValueError) as error:
        report.update({"status": getattr(error, "status", "io_error"), "error": str(error),
                       "network_request_count": client.request_count if client else 0,
                       "local_fallback": LOCAL_FALLBACK})
        print(f"[FAIL] {report['status']}：{error}\n{LOCAL_FALLBACK}")
        exit_code = 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"download_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"运行记录：{path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
