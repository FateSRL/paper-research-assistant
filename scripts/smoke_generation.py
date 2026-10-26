"""D5 C：固定 RAG 首题的新检索与真实草稿生成；必须显式传 --live。

此脚本只验证 C 的草稿路径，尚无 D 引用回查，也不作为 F 问答评分。
"""

import argparse
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from qdrant_client import QdrantClient

from paper_assistant.config import load_embedding_settings, load_llm_settings
from paper_assistant.context import ContextError, prepare_context
from paper_assistant.generation import generate_draft
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, LLMCallError, RecordedLLM
from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher, SearchError
from paper_assistant.storage import PaperStore
from scripts.search_evidence import load_current_profile


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "What forms of parametric and non-parametric memory are combined in the RAG model?"
PAIRS = [("arxiv_2005.11401v4", "r_269ac0cb1263292d")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True,
                        help="请求一次问题 embedding 并执行有界聊天生成，使用真实服务额度")
    parser.parse_args()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    report = {"task": "D5-C-live-draft-generation", "run_id": stamp, "started_at_utc": now.isoformat(),
              "status": "tool_error", "case_id": "D2-001", "question": QUESTION,
              "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in PAIRS],
              "policy": asdict(policy), "context_max_chars": 8000, "top_k": 5,
              "search": None, "context": None, "generation": None, "error": None,
              "provider": None, "model_id": None, "embedding_requests": 0, "llm_requests": 0,
              "citation_validation_status": "not_performed", "is_answer_accuracy": False,
              "scope": "fresh retrieval to structure-valid draft; citation business checks pending D",
              "history_report": f"archive/run_logs/d5/generation_smoke_{stamp}.json"}
    stage = "configuration"
    try:
        settings = load_embedding_settings()
        chat_settings = load_llm_settings()
        report.update(provider=chat_settings.provider, model_id=chat_settings.model_id)
        profile = load_current_profile()
        if make_index_profile(settings) != profile:
            raise ContextError("embedding_profile_mismatch", "本机向量配置与正式索引不一致")
        stage = "retrieval"
        if budget.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "检索前截止预算已到")
        with PaperStore(ROOT / "data/index/papers.sqlite3", read_only=True) as store:
            with closing(QdrantClient(path=str(ROOT / "data/index/qdrant"))) as qdrant:
                if not qdrant.collection_exists(profile["collection_name"]):
                    raise ContextError("missing_collection", "正式索引 collection 不存在")
                with QdrantStore(ROOT / "data/index/qdrant", profile["collection_name"],
                                 profile["index_profile_id"], profile["recipe"]["dimension"], client=qdrant) as vectors:
                    search = EvidenceSearcher(store, vectors, settings, profile).search_evidence(QUESTION, PAIRS, top_k=5)
                    report["search"] = search
                    report["embedding_requests"] = search["statistics"]["embedding_requests"]
        if budget.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "检索结束时截止预算已到")
        stage = "context"
        report["context"] = prepare_context(search)
        stage = "generation"
        with RecordedLLM(chat_settings, policy=policy, budget=budget) as client:
            result = generate_draft(report["context"], client)
            report.update(generation=result, status=result["status"], error=result["error"],
                          citation_validation_status=result["citation_validation_status"])
    except SearchError as error:
        report["embedding_requests"] = error.statistics["embedding_requests"]
        report["search_error_statistics"] = error.statistics
        report["error"] = {"code": "search_error", "message": str(error), "stage": error.stage}
    except (ContextError, LLMCallError) as error:
        report["status"] = getattr(error, "status", "tool_error")
        report["error"] = {"code": error.code, "message": str(error)}
    except Exception:
        report.update(status="tool_error", citation_validation_status="not_performed",
                      error={"code": "local_error", "message": "草稿验证未完成，请核对本机配置或数据"})
    report["failure_stage"] = None if report["status"] == "draft_valid" else stage
    report["chat_statistics"] = budget.statistics()
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["network_requests"] = report["embedding_requests"] + budget.http_requests
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(ROOT / report["history_report"], report)
    atomic_json(ROOT / "artifacts/d5/generation_smoke.json", report)
    lines = ["# D5 C：新检索与真实草稿生成", "", f"状态：`{report['status']}`；引用业务检查：`{report['citation_validation_status']}`。", "",
             "本次是新问题向量请求及聊天生成；结构通过的草稿仍待 D 检查，未计算答案正确率。", "",
             f"问题：{QUESTION}", f"问题 embedding 请求：{report['embedding_requests']}；聊天 HTTP 尝试：{report['llm_requests']}。", "",
             "草稿（JSON 字符串转义展示）：", "", json.dumps(report["generation"]["draft"] if report["generation"] else None, ensure_ascii=False), "",
             "实际消息、候选、展示快照、原始响应和 usage 见 [generation_smoke.json](/D:/course/paper-research-assistant/artifacts/d5/generation_smoke.json)。", "",
             f"历史记录：`{report['history_report']}`。", ""]
    (ROOT / "artifacts/d5/generation_smoke.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "embedding_requests": report["embedding_requests"],
                      "chat_statistics": report["chat_statistics"], "protected_changes": len(changed),
                      "report": "artifacts/d5/generation_smoke.json"}, ensure_ascii=False))
    return 0 if report["status"] == "draft_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
