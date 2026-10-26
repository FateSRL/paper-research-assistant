"""D5 E：指定 1–3 个论文/解析版本，执行一次检索、回答与引用回查。

真实运行会使用问题 embedding 与有界聊天服务额度；默认沿用 ChatPolicy。
例如：python -X utf8 -m scripts.answer_question --query '你的问题' \
    --paper-id arxiv_2005.11401v4 --parse-revision r_269ac0cb1263292d
"""

import argparse
from contextlib import ExitStack, closing, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from qdrant_client import QdrantClient

from paper_assistant.answer_export import atomic_text, exclusive_json, render
from paper_assistant.config import EmbeddingSettings, load_embedding_settings, load_llm_settings, load_rerank_settings
from paper_assistant.context import PROMPT_VERSION, SELECTION_VERSION
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM
from paper_assistant.deadline import DeadlineExceeded, commit_result, final_deadline, preserve_expired_failure, remaining
# 依赖的 fitz 导入目前会向 stdout 打印弃用信息；移到 stderr 保持 --json 可直接解析。
with redirect_stdout(sys.stderr):
    from paper_assistant.rag import RAG_VERSION, answer_question
from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.rerank_statistics import empty_rerank_statistics
from paper_assistant.storage import PaperStore


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["paper_assistant/answer_export.py", "paper_assistant/citations.py", "paper_assistant/config.py",
           "paper_assistant/context.py", "paper_assistant/deadline.py", "paper_assistant/embedding_client.py", "paper_assistant/generation.py",
           "paper_assistant/indexing.py", "paper_assistant/llm_client.py", "paper_assistant/rag.py",
           "paper_assistant/retrieval.py", "paper_assistant/schemas.py", "paper_assistant/search.py",
           "paper_assistant/storage.py", "scripts/answer_question.py"]
NORMAL = ("answered", "insufficient_evidence")
STATUSES = (*NORMAL, "tool_error", "invalid_output", "budget_exceeded")


def load_current_profile() -> dict:
    """只读取固定清单，按 ROOT 定位，复用已有配置指纹规则。"""
    index_root = ROOT / "data/index"
    profile = json.loads((index_root / "current_profile.json").read_text(encoding="utf-8"))
    recipe = profile["recipe"]
    public = EmbeddingSettings(backend=recipe["backend"], model=recipe["model"], api_key=None,
                               base_url=recipe["base_url"], dimension=recipe["dimension"])
    if make_index_profile(public) != profile:
        raise ValueError("profile identity mismatch")
    saved = json.loads((index_root / "profiles" / (profile["index_profile_id"] + ".json")).read_text(encoding="utf-8"))
    if saved != profile:
        raise ValueError("profile pointer mismatch")
    return profile


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="非空问题原文；真实运行会使用模型额度")
    parser.add_argument("--paper-id", help="单篇论文 ID，必须同时给 parse-revision")
    parser.add_argument("--parse-revision", help="单篇明确解析版本，必须同时给 paper-id")
    parser.add_argument("--version", action="append", nargs=2, metavar=("PAPER_ID", "PARSE_REVISION"),
                        help="完整配对，可重复选择 1–3 对；不能与单篇参数混用")
    parser.add_argument("--top-k", type=int, default=5, help="D5 固定一轮检索，仅允许 5")
    parser.add_argument("--max-chars", type=int, default=8000, help="展示证据正文字符上限，1–8000")
    parser.add_argument("--json", action="store_true", help="标准输出打印完整机器记录")
    args = parser.parse_args(argv)
    if not args.query.strip():
        parser.error("query 必须是非空问题")
    if (args.paper_id is None) != (args.parse_revision is None):
        parser.error("paper-id 与 parse-revision 必须一起提供")
    if args.version is not None and args.paper_id is not None:
        parser.error("version 与 paper-id/parse-revision 不能混用")
    pairs = args.version if args.version is not None else ([(args.paper_id, args.parse_revision)] if args.paper_id is not None else [])
    if not 1 <= len(pairs) <= 3:
        parser.error("必须选择 1–3 个完整论文/解析版本配对")
    if any(not value.strip() or value != value.strip() for pair in pairs for value in pair):
        parser.error("论文 ID 和解析版本必须非空且不能带首尾空白")
    if len(set(tuple(pair) for pair in pairs)) != len(pairs):
        parser.error("不能重复选择同一论文/解析版本配对")
    if args.top_k != 5:
        parser.error("D5 固定流程 top-k 必须为 5")
    if not 1 <= args.max_chars <= 8000:
        parser.error("max-chars 必须为 1–8000")
    args.pairs = [tuple(pair) for pair in pairs]
    return args


def fail(report, status, code, message, stage):
    if preserve_expired_failure(report, status, code, message, stage):
        return
    error = {"code": code, "message": message}
    report.update(status=status, answer=None, error=error, failure_stage=stage)
    if report.get("result") is not None:
        report["result"].update(status=status, answer=None, error=deepcopy(error), failure_stage=stage)


def save_report(report: dict) -> bool:
    """先保存完整历史。后续导出故障另存失败事件，绝不修改旧历史。"""
    committed = deepcopy(report)
    # 历史先于最近文件写入；快照只声称导出已准备，不提前声称后续写盘成功。
    report["export"] = {"status": "prepared", "failed_step": None, "recovery_history_report": None}
    stage = "history_json"
    try:
        exclusive_json(ROOT / report["history_report"], report)
        stage = "latest_json"
        atomic_json(ROOT / "artifacts/d5/answer_result.json", report)
        stage = "latest_markdown"
        atomic_text(ROOT / "artifacts/d5/answer_result.md", render(report, project_root=ROOT))
        return True
    except Exception:
        report["pre_export_result"] = committed
        fail(report, "tool_error", "export_error", "运行记录导出未完成；已发生的调用仍保留在本轮记录中", "export")
        recovery = "archive/run_logs/d5/answer_" + report["run_id"] + "_export_failure_" + uuid4().hex[:12] + ".json"
        report["export"] = {"status": "failed", "failed_step": stage, "recovery_history_report": recovery}
        # 写盘故障不会变成模型重跑。每个兜底独立尝试，stdout 仍保留完整结果。
        for operation in (lambda: exclusive_json(ROOT / recovery, report),
                          lambda: atomic_json(ROOT / "artifacts/d5/answer_result.json", report),
                          lambda: atomic_text(ROOT / "artifacts/d5/answer_result.md", render(report, project_root=ROOT))):
            try:
                operation()
            except Exception:
                pass
        return False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)  # 参数错误到此结束，不读取配置、不建资源、不写记录。
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12]
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    report = {"task": "D5-E-answer-question", "run_id": run_id, "started_at_utc": now.isoformat(),
              "finished_at_utc": None, "query": args.query,
              "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in args.pairs],
              "top_k": args.top_k, "max_chars": args.max_chars, "policy": asdict(policy),
              "configuration": None, "index_profile": None, "rag_version": RAG_VERSION,
              "prompt_version": PROMPT_VERSION, "selection_version": SELECTION_VERSION,
              "status": "tool_error", "answer": None, "result": None, "error": None, "failure_stage": "input_verification",
              "semantic_support_status": "not_reviewed", "is_answer_accuracy": False,
              "embedding_statistics": None, "embedding_requests": 0,
              "llm_requests": 0, "network_requests": 0, "chat_attempts": [], "chat_statistics": None,
              "deadline_enforcement": "phase_checks_and_remaining_chat_timeout; synchronous_hard_wall_clock_abort_not_verified",
              "history_report": "archive/run_logs/d5/answer_" + run_id + ".json"}
    stage = "input_verification"
    pipeline_started = False
    try:
        stage = "configuration"
        embedding = load_embedding_settings()
        chat = load_llm_settings()
        profile = load_current_profile()
        if make_index_profile(embedding) != profile:
            raise ValueError("embedding configuration mismatch")
        # 仅记录固定公开字段；配置对象及密钥从不序列化。
        report["index_profile"] = deepcopy(profile)
        report["configuration"] = {"chat": {"provider": chat.provider, "model_id": chat.model_id,
                                 "configured_timeout": chat.timeout},
                                   "embedding": deepcopy(profile["recipe"]), "policy": asdict(policy)}
        if not (ROOT / "data/index/qdrant/meta.json").is_file():
            raise ValueError("missing persisted index")
        if budget.remaining_seconds() <= 0:
            fail(report, "budget_exceeded", "deadline_exceeded", "配置步骤结束时截止预算已到", stage)
        else:
            stage = "resources"
            with ExitStack() as resources:
                store = resources.enter_context(PaperStore(ROOT / "data/index/papers.sqlite3", read_only=True))
                qdrant = resources.enter_context(closing(QdrantClient(path=str(ROOT / "data/index/qdrant"))))
                if not qdrant.collection_exists(profile["collection_name"]):
                    raise ValueError("missing collection")
                vectors = resources.enter_context(QdrantStore(ROOT / "data/index/qdrant", profile["collection_name"],
                                                           profile["index_profile_id"], profile["recipe"]["dimension"], client=qdrant))
                rerank_settings = load_rerank_settings()
                reranker = resources.enter_context(RerankClient(rerank_settings)) if rerank_settings else None
                searcher = HybridEvidenceSearcher(EvidenceSearcher(store, vectors, embedding, profile), store, reranker)
                remaining(budget.remaining_seconds)
                client = resources.enter_context(RecordedLLM(chat, policy=policy, budget=budget))
                stage = "pipeline"
                pipeline_started = True
                result = answer_question(args.query, args.pairs, searcher, store, client, project_root=ROOT,
                                         top_k=args.top_k, max_chars=args.max_chars, enforce_remaining_budget=True)
                # 核心步骤和费用必须在关闭资源之前进入报告，关闭失败不能丢失。
                report["result"] = deepcopy(result)
                report.update(status=result["status"], answer=deepcopy(result["answer"]), error=deepcopy(result["error"]),
                              failure_stage=result.get("failure_stage"))
                report["embedding_statistics"] = deepcopy(result["statistics"].get("embedding"))
                if result["status"] not in STATUSES:
                    fail(report, "tool_error", "unexpected_status", "固定问答核心返回未约定终态", "pipeline")
                stage = "resource_cleanup"
    except DeadlineExceeded:
        fail(report, "budget_exceeded", "deadline_exceeded", "资源准备结束时截止预算已到", stage)
    except Exception:
        fail(report, "tool_error", "local_error", "本机输入、配置、资源或清理步骤失败", stage)
    final_deadline(report, budget, "resource_cleanup")
    # 正常核心返回明确统计。若核心意外抛异常，外围无法证明 embedding 未发生。
    stats = report["embedding_statistics"]
    report["embedding_requests"] = stats.get("embedding_requests") if isinstance(stats, dict) else (None if pipeline_started else 0)
    report["rerank_statistics"] = deepcopy((report.get("result") or {}).get("statistics", {}).get("rerank", empty_rerank_statistics()))
    report["rerank_requests"] = report["rerank_statistics"]["requests"]
    report["chat_statistics"] = deepcopy(budget.statistics())
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["network_requests"] = (report["embedding_requests"] + report["llm_requests"] + report["rerank_requests"]
                                  if type(report["embedding_requests"]) is int else None)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    commit_result(report, budget, "resource_cleanup")
    saved = save_report(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    elif saved:
        print(render(report, project_root=ROOT))
    else:
        # 磁盘可能全部不可写；终端保留完整机器结果，尤其失败响应的实际用量。
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), file=sys.stderr)
    return 0 if saved and report["status"] in NORMAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
