"""D6 D：页面的一次提交对应一次独立的固定 RAG 运行。

本模块没有 Streamlit 依赖、资源缓存或自动重试入口。页面只保存返回的
普通 JSON 记录；下载从该记录生成，不会读最近文件或再次调用模型。
"""

from contextlib import ExitStack, closing, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version as package_version
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from qdrant_client import QdrantClient

from paper_assistant.answer_export import atomic_text, exclusive_json, file_link, render
from paper_assistant.config import EmbeddingSettings, load_embedding_settings, load_llm_settings, load_rerank_settings
from paper_assistant.context import PROMPT_VERSION, SELECTION_VERSION
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM
from paper_assistant.deadline import DeadlineExceeded, commit_result, final_deadline, preserve_expired_failure, remaining

with redirect_stdout(sys.stderr):
    from paper_assistant.rag import RAG_VERSION, answer_question

from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.storage import PaperStore
from paper_assistant.rerank_statistics import empty_rerank_statistics


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "paper_assistant/answer_export.py", "paper_assistant/citations.py",
    "paper_assistant/config.py", "paper_assistant/context.py",
    "paper_assistant/embedding_client.py", "paper_assistant/generation.py",
    "paper_assistant/indexing.py", "paper_assistant/llm_client.py",
    "paper_assistant/rag.py", "paper_assistant/retrieval.py",
    "paper_assistant/schemas.py", "paper_assistant/search.py",
    "paper_assistant/storage.py", "paper_assistant/web_runtime.py",
    "app.py", "requirements.txt", "paper_assistant/deadline.py",
)
NORMAL = ("answered", "insufficient_evidence")
STATUSES = (*NORMAL, "tool_error", "invalid_output", "budget_exceeded")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
LATEST_JSON = "artifacts/d6/web_answer_result.json"
LATEST_MARKDOWN = "artifacts/d6/web_answer_result.md"


class InvalidQuestion(ValueError):
    """收费和写盘前拒绝不合法的问题或版本选择，不回显原输入。"""


def _load_current_profile(project_root: Path) -> dict:
    index_root = project_root / "data/index"
    profile = json.loads((index_root / "current_profile.json").read_text(encoding="utf-8"))
    recipe = profile["recipe"]
    public = EmbeddingSettings(backend=recipe["backend"], model=recipe["model"], api_key=None,
                               base_url=recipe["base_url"], dimension=recipe["dimension"])
    # make_index_profile 同时排除认证、query、fragment 等不能公开的地址。
    if make_index_profile(public) != profile:
        raise ValueError("profile identity mismatch")
    saved = json.loads((index_root / "profiles" / (profile["index_profile_id"] + ".json"))
                       .read_text(encoding="utf-8"))
    if saved != profile:
        raise ValueError("profile pointer mismatch")
    return profile


def _ready_versions(store: PaperStore, profile: dict) -> list[dict]:
    versions = {(row["paper_id"], row["parse_revision"]): row for row in store.list_versions()}
    papers = {}
    for row in store.connection.execute("SELECT paper_id, title, arxiv_version, pdf_sha256, paper_json FROM papers"):
        paper = json.loads(row["paper_json"])
        if (not isinstance(paper, dict)
                or any(paper.get(field) != row[field] for field in ("paper_id", "title", "arxiv_version", "pdf_sha256"))
                or not isinstance(paper.get("title"), str) or not paper["title"].strip()
                or not isinstance(paper.get("arxiv_version"), str)
                or (paper.get("source_type") != "local" and not re.fullmatch(r"v[1-9][0-9]*", paper["arxiv_version"]))):
            raise ValueError("paper metadata mismatch")
        papers[row["paper_id"]] = paper
    result = []
    for state in store.list_index_imports(status="ready", index_profile_id=profile["index_profile_id"]):
        pair = (state["paper_id"], state["parse_revision"])
        version = versions.get(pair)
        paper = papers.get(pair[0])
        if (version is None or paper is None or type(version["chunk_count"]) is not int
                or version["chunk_count"] <= 0 or state["completed_count"] != version["chunk_count"]
                or version["pdf_sha256"] != paper["pdf_sha256"]):
            raise ValueError("ready version metadata mismatch")
        result.append({"paper_id": pair[0], "parse_revision": pair[1],
                       "title": paper["title"], "arxiv_version": paper["arxiv_version"],
                       "source_type": paper.get("source_type", "arxiv"),
                       "chunk_count": version["chunk_count"]})
    return result


def list_ready_versions(*, project_root: Path = ROOT) -> list[dict]:
    """只读当前配置与 SQLite，不加载 .env，不打开 Qdrant，不发请求。"""
    try:
        root = Path(project_root).resolve()
        profile = _load_current_profile(root)
        with PaperStore(root / "data/index/papers.sqlite3", read_only=True) as store:
            return _ready_versions(store, profile)
    except Exception:
        raise RuntimeError("无法读取已入库版本，请核对本机索引和数据库") from None


def _validate_input(query, selected_versions) -> list[tuple[str, str]]:
    if not isinstance(query, str) or not query.strip():
        raise InvalidQuestion("请输入非空问题")
    if not isinstance(selected_versions, (list, tuple)) or not 1 <= len(selected_versions) <= 3:
        raise InvalidQuestion("请选择 1–3 个完整的论文与解析版本配对")
    pairs = []
    for value in selected_versions:
        if isinstance(value, dict):
            value = (value.get("paper_id"), value.get("parse_revision"))
        if (not isinstance(value, (tuple, list)) or len(value) != 2
                or any(not isinstance(item, str) or item != item.strip()
                       or not SAFE_ID.fullmatch(item) for item in value)):
            raise InvalidQuestion("论文与解析版本配对无效")
        pair = tuple(value)
        if pair in pairs:
            raise InvalidQuestion("不能重复选择同一论文与解析版本配对")
        pairs.append(pair)
    return pairs


def _fail(report: dict, status: str, code: str, message: str, stage: str) -> None:
    if preserve_expired_failure(report, status, code, message, stage):
        return
    # result 是核心的原始记录，外围失败不删除已发生调用、响应或引用检查。
    report.update(status=status, answer=None, error={"code": code, "message": message}, failure_stage=stage)


def _render(report: dict, project_root: Path) -> str:
    text = render(report, project_root=project_root)
    old_link = file_link(project_root / "artifacts/d5/answer_result.json", "完整 JSON")
    target = report.get("export", {}).get("recovery_history_report") or report["history_report"]
    return text.replace(old_link, file_link(project_root / target, "完整 JSON"))


def _save_report(report: dict, project_root: Path) -> bool:
    committed = deepcopy(report)
    report["export"] = {"status": "prepared", "failed_step": None, "recovery_history_report": None}
    step = "history_json"
    try:
        exclusive_json(project_root / report["history_report"], report)
        step = "latest_json"
        atomic_json(project_root / LATEST_JSON, report)
        step = "latest_markdown"
        atomic_text(project_root / LATEST_MARKDOWN, _render(report, project_root))
        return True
    except Exception:
        report["pre_export_result"] = committed
        _fail(report, "tool_error", "export_error", "运行记录导出未完成；已发生的调用仍保留在当前记录中", "export")
        recovery = ("archive/run_logs/d6/web_answer_" + report["run_id"]
                    + "_export_failure_" + uuid4().hex[:12] + ".json")
        report["export"] = {"status": "failed", "failed_step": step, "recovery_history_report": recovery}
        for operation in (
            lambda: exclusive_json(project_root / recovery, report),
            lambda: atomic_json(project_root / LATEST_JSON, report),
            lambda: atomic_text(project_root / LATEST_MARKDOWN, _render(report, project_root)),
        ):
            try:
                operation()
            except Exception:
                pass
        return False


def download_payloads(report: dict, *, project_root: Path = ROOT) -> tuple[bytes, bytes]:
    """从当前会话记录生成下载；不写文件，不检查配置，不创建模型客户端。"""
    try:
        if not isinstance(report, dict) or report.get("task") != "D6-D-web-answer-question":
            raise ValueError("invalid report")
        payload = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        markdown = _render(report, Path(project_root).resolve()).encode("utf-8")
        return payload, markdown
    except Exception:
        raise ValueError("当前记录无法生成下载文件；已发生的调用仍保留在会话记录中") from None


def run_question(query, selected_versions, *, project_root: Path = ROOT, enforce_remaining_budget=False) -> dict:
    """一次显式提交。输入非法时抛 InvalidQuestion，其余故障返回完整记录。"""
    pairs = _validate_input(query, selected_versions)
    root = Path(project_root).resolve()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12]
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    report = {
        "task": "D6-D-web-answer-question", "run_id": run_id, "started_at_utc": now.isoformat(),
        "finished_at_utc": None, "query": query,
        "selected_versions": [{"paper_id": paper, "parse_revision": revision} for paper, revision in pairs],
        "selected_version_metadata": [],
        "top_k": 5, "max_chars": 8000, "policy": asdict(policy), "configuration": None,
        "index_profile": None, "rag_version": RAG_VERSION, "prompt_version": PROMPT_VERSION,
        "selection_version": SELECTION_VERSION, "status": "tool_error", "answer": None,
        "web_runtime_revision": "d6-d-web-runtime-v1", "streamlit_version": None,
        "result": None, "error": None, "failure_stage": "input_verification",
        "semantic_support_status": "not_reviewed", "is_answer_accuracy": False,
        "embedding_statistics": None,
        "rerank_statistics": empty_rerank_statistics(),
        "embedding_requests": 0, "rerank_requests": 0, "llm_requests": 0, "network_requests": 0,
        "chat_attempts": [], "chat_statistics": None,
        "deadline_enforcement": "phase_checks_and_remaining_chat_timeout; synchronous_hard_wall_clock_abort_not_verified",
        "history_report": "archive/run_logs/d6/web_answer_" + run_id + ".json",
    }
    if enforce_remaining_budget:
        report["budget_implementation_version"] = "d9-remaining-budget-v1"
        report["deadline_enforcement"] = "remaining_embedding_and_chat_timeout_and_stage_checks; hard_process_abort_unverified"
    stage = "input_verification"
    pipeline_started = False
    try:
        report["streamlit_version"] = package_version("streamlit")
        # 第一条收费请求之前完成完整配对检查；无效选择不会导出运行记录。
        profile = _load_current_profile(root)
        with ExitStack() as resources:
            store = resources.enter_context(PaperStore(root / "data/index/papers.sqlite3", read_only=True))
            ready = _ready_versions(store, profile)
            by_pair = {(row["paper_id"], row["parse_revision"]): row for row in ready}
            if any(pair not in by_pair for pair in pairs):
                raise InvalidQuestion("所选论文与解析版本在当前索引下尚未完整入库")
            report["selected_version_metadata"] = [deepcopy(by_pair[pair]) for pair in pairs]
            stage = "configuration"
            embedding = load_embedding_settings()
            chat = load_llm_settings()
            if make_index_profile(embedding) != profile:
                raise ValueError("embedding configuration mismatch")
            report["index_profile"] = deepcopy(profile)
            report["configuration"] = {
                "chat": {"provider": chat.provider, "model_id": chat.model_id, "configured_timeout": chat.timeout},
                "embedding": deepcopy(profile["recipe"]), "policy": asdict(policy),
            }
            if not (root / "data/index/qdrant/meta.json").is_file():
                raise ValueError("missing persisted index")
            if budget.remaining_seconds() <= 0:
                _fail(report, "budget_exceeded", "deadline_exceeded", "配置步骤结束时截止预算已到", stage)
            else:
                stage = "resources"
                qdrant = resources.enter_context(closing(QdrantClient(path=str(root / "data/index/qdrant"))))
                if not qdrant.collection_exists(profile["collection_name"]):
                    raise ValueError("missing collection")
                vectors = resources.enter_context(QdrantStore(
                    root / "data/index/qdrant", profile["collection_name"], profile["index_profile_id"],
                    profile["recipe"]["dimension"], client=qdrant,
                ))
                rerank_settings = load_rerank_settings()
                reranker = resources.enter_context(RerankClient(rerank_settings)) if rerank_settings else None
                searcher = HybridEvidenceSearcher(EvidenceSearcher(store, vectors, embedding, profile), store, reranker)
                enforce_remaining_budget = enforce_remaining_budget or reranker is not None
                remaining(budget.remaining_seconds)
                client = resources.enter_context(RecordedLLM(chat, policy=policy, budget=budget))
                stage = "pipeline"
                pipeline_started = True
                result = answer_question(query, pairs, searcher, store, client,
                                         project_root=root, top_k=5, max_chars=8000,
                                         **({"enforce_remaining_budget": True} if enforce_remaining_budget else {}))
                # 费用、原始响应和全部步骤先保存到内存，再开始关闭资源。
                report["result"] = deepcopy(result)
                report.update(status=result["status"], answer=deepcopy(result["answer"]),
                              error=deepcopy(result["error"]), failure_stage=result.get("failure_stage"))
                report["embedding_statistics"] = deepcopy(result["statistics"].get("embedding"))
                if result["status"] not in STATUSES:
                    _fail(report, "tool_error", "unexpected_status", "固定问答核心返回未约定终态", "pipeline")
            stage = "resource_cleanup"
    except InvalidQuestion:
        raise
    except DeadlineExceeded:
        _fail(report, "budget_exceeded", "deadline_exceeded", "资源准备结束时截止预算已到", stage)
    except Exception:
        _fail(report, "tool_error", "local_error", "本机输入、配置、资源或清理步骤失败", stage)
    final_deadline(report, budget, "resource_cleanup")
    stats = report["embedding_statistics"]
    report["embedding_requests"] = (stats.get("embedding_requests") if isinstance(stats, dict)
                                    else (None if pipeline_started else 0))
    report["rerank_statistics"] = deepcopy((report.get("result") or {}).get("statistics", {}).get("rerank")
                                           or empty_rerank_statistics())
    report["rerank_requests"] = report["rerank_statistics"]["requests"]
    report["chat_statistics"] = deepcopy(budget.statistics())
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["network_requests"] = (report["embedding_requests"] + report["llm_requests"] + report["rerank_requests"]
                                  if type(report["embedding_requests"]) is int else None)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    commit_result(report, budget, "resource_cleanup")
    _save_report(report, root)
    return report
