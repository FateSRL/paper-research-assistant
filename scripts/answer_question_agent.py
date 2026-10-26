"""D8 E: independently run an Agent question; real invocation uses API quota."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--paper-id")
    parser.add_argument("--parse-revision")
    parser.add_argument("--version", action="append", nargs=2, metavar=("PAPER_ID", "PARSE_REVISION"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--json", action="store_true", help="Print only the complete JSON report to stdout")
    args = parser.parse_args(argv)
    if not args.query.strip():
        parser.error("query 必须为非空文本")
    if (args.paper_id is None) != (args.parse_revision is None):
        parser.error("paper-id 与 parse-revision 必须一起提供")
    if args.version is not None and args.paper_id is not None:
        parser.error("version 与单篇参数不能混用")
    pairs = args.version if args.version is not None else ([(args.paper_id, args.parse_revision)] if args.paper_id is not None else [])
    if not 1 <= len(pairs) <= 3:
        parser.error("必须选择 1–3 个完整版本配对")
    if any(not _SAFE_ID.fullmatch(value) for pair in pairs for value in pair):
        parser.error("论文与解析版本必须为安全标识符")
    if len(set(tuple(pair) for pair in pairs)) != len(pairs):
        parser.error("不能重复选择同一完整版本")
    if args.top_k != 5:
        parser.error("top-k 必须为 5")
    if not 1 <= args.max_chars <= 8000:
        parser.error("max-chars 必须为 1–8000")
    args.pairs = [tuple(pair) for pair in pairs]
    return args


def main(argv=None):
    args = parse_args(argv)  # Invalid/help exits before runtime imports or work.
    with redirect_stdout(sys.stderr):
        from paper_assistant.agent_export import render_agent_run
        from paper_assistant.agent_runtime import run_question_agent
        report = run_question_agent(args.query, args.pairs, project_root=ROOT,
                                    top_k=args.top_k, max_chars=args.max_chars)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(render_agent_run(report))
    return 0 if report["status"] in ("answered", "insufficient_evidence") and report["export"]["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
