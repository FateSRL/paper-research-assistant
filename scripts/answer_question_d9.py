"""D9 两模式独立问答入口；真实运行使用 API 额度。"""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixed_rag", "agent"), default="fixed_rag")
    parser.add_argument("--query", required=True)
    parser.add_argument("--version", nargs=2, action="append", metavar=("PAPER_ID", "PARSE_REVISION"), required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    with redirect_stdout(sys.stderr):
        from paper_assistant.d9_runtime import InvalidQuestion, legacy
    try:
        args.pairs = legacy.validate_agent_input(args.query, args.version)
    except InvalidQuestion as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    args = parse_args(argv)
    with redirect_stdout(sys.stderr):
        from paper_assistant.d9_runtime import run_question
        from paper_assistant.agent_export import render_agent_run
        report = run_question(args.query, args.pairs, mode=args.mode, project_root=ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) if args.json else render_agent_run(report))
    return 0 if report["status"] in ("answered", "insufficient_evidence") and report.get("export", {}).get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
