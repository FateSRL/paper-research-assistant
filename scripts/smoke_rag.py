"""D5 D：固定首题的新检索、生成、引用回查。显式 --live 使用真实额度。

通用问答 CLI 留给 E。本脚本是固定核心验收，不是批量问答评分。
"""

import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from qdrant_client import QdrantClient

from paper_assistant.config import load_embedding_settings, load_llm_settings
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM
from paper_assistant.rag import answer_question
from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher
from paper_assistant.storage import PaperStore
from scripts.search_evidence import load_current_profile


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "What forms of parametric and non-parametric memory are combined in the RAG model?"
PAIRS = [("arxiv_2005.11401v4", "r_269ac0cb1263292d")]


def fenced(text):
    # 片段可能包含反引号，沿用 E 将实现的导出原则保留完整原文。
    import re
    length = max((len(m.group()) for m in re.finditer(r"`+", text)), default=0)
    marker = "`" * max(3, length + 1)
    return marker + "text\n" + text + "\n" + marker


def render(report):
    lines = ["# D5 D：固定 RAG 首题核心验收", "", f"状态：`{report['status']}`。", "",
             "结构与引用定位通过才发布答案；语义支持尚未评分，不是开发集问答准确率。", "",
             f"问题：{QUESTION}", "", f"embedding 请求：{report['embedding_requests']}；聊天 HTTP 尝试：{report['llm_requests']}。", ""]
    if report.get("answer"):
        for claim in report["answer"]["claims"]:
            lines += [fenced(claim["claim"]), "", "引用：" + ", ".join(claim["citation_ids"]), ""]
        if report["answer"].get("reason"):
            lines += [report["answer"]["reason"], ""]
        for source in report["answer"]["evidence_sources"]:
            pdf_link = "/" + Path(source["pdf_absolute_path"]).as_posix()
            lines += [f"原文 `{source['chunk_id']}`；PDF 文件页序 {source['pdf_page']}。", "",
                      f"来源：[{source['title']}](<{pdf_link}>)；版本 `{source['arxiv_version']}`。", "",
                      fenced(source["text"]), ""]
    else:
        lines += ["本轮没有可发布答案。安全错误：" + json.dumps(report.get("error"), ensure_ascii=False), ""]
    lines += ["完整候选、消息、原始响应、引用检查与实际用量见 [rag_smoke.json](/D:/course/paper-research-assistant/artifacts/d5/rag_smoke.json)。",
              "", f"历史记录：`{report['history_report']}`。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True,
                        help="请求一次问题 embedding 并执行有界聊天生成/引用回查")
    parser.parse_args()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    report = {"task": "D5-D-live-fixed-rag", "run_id": stamp, "started_at_utc": now.isoformat(),
              "status": "tool_error", "case_id": "D2-001", "query": QUESTION, "policy": asdict(policy),
              "provider": None, "model_id": None, "result": None, "answer": None, "error": None,
              "embedding_requests": 0, "llm_requests": 0, "semantic_support_status": "not_reviewed",
              "is_answer_accuracy": False,
              "history_report": f"archive/run_logs/d5/rag_smoke_{stamp}.json"}
    stage = "configuration"
    try:
        embedding, chat = load_embedding_settings(), load_llm_settings()
        report.update(provider=chat.provider, model_id=chat.model_id)
        profile = load_current_profile()
        if make_index_profile(embedding) != profile:
            raise ValueError("configuration mismatch")
        stage = "resources"
        with ExitStack() as resources:
            store = resources.enter_context(PaperStore(ROOT / "data/index/papers.sqlite3", read_only=True))
            qdrant = resources.enter_context(closing(QdrantClient(path=str(ROOT / "data/index/qdrant"))))
            if not qdrant.collection_exists(profile["collection_name"]):
                raise ValueError("missing collection")
            vectors = resources.enter_context(QdrantStore(ROOT / "data/index/qdrant", profile["collection_name"],
                                                       profile["index_profile_id"], profile["recipe"]["dimension"], client=qdrant))
            searcher = EvidenceSearcher(store, vectors, embedding, profile)
            client = resources.enter_context(RecordedLLM(chat, policy=policy, budget=budget))
            stage = "pipeline"
            result = answer_question(QUESTION, PAIRS, searcher, store, client, project_root=ROOT)
            # 在资源关闭前保存已发生的请求和所有原始步骤，异常不能抹去费用。
            report.update(result=result, status=result["status"], answer=deepcopy(result["answer"]), error=deepcopy(result["error"]))
            stats = result["statistics"]["embedding"] or {}
            report["embedding_requests"] = stats.get("embedding_requests", 0)
            stage = "resource_cleanup"
    except Exception:
        report.update(status="tool_error", answer=None, error={"code": "local_error", "message": "本机配置、资源或清理步骤失败"})
        if report["result"] is not None:
            report["result"].update(status="tool_error", answer=None, error=deepcopy(report["error"]), failure_stage=stage)
    if report["status"] in ("answered", "insufficient_evidence") and budget.remaining_seconds() <= 0:
        report.update(status="budget_exceeded", answer=None,
                      error={"code": "deadline_exceeded", "message": "资源清理结束时截止预算已到"})
        report["result"].update(status="budget_exceeded", answer=None, error=deepcopy(report["error"]), failure_stage=stage)
    report["chat_statistics"] = budget.statistics()
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["network_requests"] = report["embedding_requests"] + report["llm_requests"]
    report["failure_stage"] = (None if report["status"] in ("answered", "insufficient_evidence") else
                               (report["result"].get("failure_stage") if report["result"] else stage))
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(ROOT / report["history_report"], report)
    atomic_json(ROOT / "artifacts/d5/rag_smoke.json", report)
    (ROOT / "artifacts/d5/rag_smoke.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "embedding_requests": report["embedding_requests"],
                      "chat_statistics": report["chat_statistics"],
                      "report": "artifacts/d5/rag_smoke.json"}, ensure_ascii=False))
    return 0 if report["status"] in ("answered", "insufficient_evidence") else 1


if __name__ == "__main__":
    raise SystemExit(main())
