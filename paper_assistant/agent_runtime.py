"""D8 E: standalone Agent resource ownership, bindings and safe run export."""

from contextlib import ExitStack, closing, contextmanager, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from qdrant_client import QdrantClient

from paper_assistant.agent_export import save_agent_run
from paper_assistant.agent_records import diagnostic_snapshot
from paper_assistant.config import EmbeddingSettings, load_embedding_settings, load_llm_settings, load_rerank_settings
from paper_assistant.indexing import digest, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM
from paper_assistant.retrieval import QdrantStore
from paper_assistant.search import EvidenceSearcher
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.deadline import DeadlineExceeded, commit_result, preserve_expired_failure, remaining
from paper_assistant.storage import PaperStore
from paper_assistant.rerank_statistics import empty_rerank_statistics

with redirect_stdout(sys.stderr):
    from paper_assistant.agent import AGENT_VERSION, answer_question_agent
    from paper_assistant.agent_actions import ACTION_SCHEMA_VERSION
    from paper_assistant.agent_context import AGENT_SELECTION_VERSION
    from paper_assistant.agent_prompt import AGENT_PROMPT_VERSION


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VERSION = "d8-standalone-agent-runtime-v1"
STRATEGY_PATH = "artifacts/d8/agent_config.json"
SOURCES = (
    "paper_assistant/agent.py", "paper_assistant/agent_actions.py",
    "paper_assistant/agent_context.py", "paper_assistant/agent_prompt.py",
    "paper_assistant/agent_records.py", "paper_assistant/agent_export.py",
    "paper_assistant/agent_runtime.py", "paper_assistant/answer_export.py",
    "paper_assistant/citations.py", "paper_assistant/config.py",
    "paper_assistant/context.py", "paper_assistant/embedding_client.py",
    "paper_assistant/indexing.py", "paper_assistant/llm_client.py",
    "paper_assistant/retrieval.py", "paper_assistant/schemas.py",
    "paper_assistant/search.py", "paper_assistant/storage.py", "paper_assistant/deadline.py",
    "scripts/answer_question_agent.py", "requirements.txt",
)
NORMAL = ("answered", "insufficient_evidence")
STATUSES = (*NORMAL, "tool_error", "invalid_output", "budget_exceeded")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class InvalidQuestion(ValueError):
    """Pure input rejection before configuration, resource or record creation."""


class FrozenConfigurationError(ValueError):
    """The public configuration no longer matches the frozen D8 A contract."""


def validate_agent_input(query, selected_versions, *, top_k=5, max_chars=8000):
    if not isinstance(query, str) or not query.strip():
        raise InvalidQuestion("问题必须为非空文本")
    if type(top_k) is not int or top_k != 5:
        raise InvalidQuestion("首轮和补轮 top-k 必须为 5")
    if type(max_chars) is not int or not 1 <= max_chars <= 8000:
        raise InvalidQuestion("max-chars 必须为 1–8000 的整数")
    if not isinstance(selected_versions, (list, tuple)) or not 1 <= len(selected_versions) <= 3:
        raise InvalidQuestion("必须选择 1–3 个完整论文与解析版本配对")
    pairs = []
    for pair in selected_versions:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in pair)):
            raise InvalidQuestion("论文与解析版本必须为完整安全标识符")
        if tuple(pair) in pairs:
            raise InvalidQuestion("不能重复选择同一完整版本")
        pairs.append(tuple(pair))
    return pairs


def load_current_profile(project_root) -> dict:
    root = Path(project_root).resolve()
    profile = json.loads((root / "data/index/current_profile.json").read_text(encoding="utf-8"))
    recipe = profile["recipe"]
    public = EmbeddingSettings(backend=recipe["backend"], model=recipe["model"], api_key=None,
                               base_url=recipe["base_url"], dimension=recipe["dimension"])
    if make_index_profile(public) != profile:
        raise ValueError("profile identity mismatch")
    saved = json.loads((root / "data/index/profiles" / (profile["index_profile_id"] + ".json"))
                       .read_text(encoding="utf-8"))
    if saved != profile:
        raise ValueError("profile pointer mismatch")
    return profile


def public_configuration(embedding, chat, profile, policy) -> dict:
    """Whitelist fields only; authentication-bearing endpoints are refused."""
    if make_index_profile(embedding) != profile:
        raise ValueError("embedding configuration mismatch")
    endpoint = urlsplit(chat.base_url)
    if (endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError("chat public endpoint is invalid")
    return {"chat": {"provider": chat.provider, "model_id": chat.model_id,
                     "base_url": chat.base_url, "configured_timeout": chat.timeout},
            "embedding": deepcopy(profile["recipe"]), "policy": asdict(policy)}


def validate_frozen_configuration(strategy, embedding, chat, profile, policy) -> dict:
    """Validate the actual index and execution limits, without historical hashes."""
    public = public_configuration(embedding, chat, profile, policy)
    if strategy["rules"]["budget"]["chat_policy"] != asdict(policy):
        raise FrozenConfigurationError("runtime budget mismatch")
    return public


@contextmanager
def open_retrieval_resources(project_root, embedding, profile):
    """Open only a persisted collection and read-only SQLite, never create one."""
    root = Path(project_root).resolve()
    if make_index_profile(embedding) != profile:
        raise ValueError("embedding configuration mismatch")
    if not (root / "data/index/qdrant/meta.json").is_file():
        raise ValueError("missing persisted Qdrant index")
    with ExitStack() as resources:
        store = resources.enter_context(PaperStore(root / "data/index/papers.sqlite3", read_only=True))
        qdrant = resources.enter_context(closing(QdrantClient(path=str(root / "data/index/qdrant"))))
        if not qdrant.collection_exists(profile["collection_name"]):
            raise ValueError("missing existing collection")
        vectors = resources.enter_context(QdrantStore(root / "data/index/qdrant", profile["collection_name"],
                         profile["index_profile_id"], profile["recipe"]["dimension"], client=qdrant))
        rerank_settings = load_rerank_settings()
        reranker = resources.enter_context(RerankClient(rerank_settings)) if rerank_settings else None
        yield store, HybridEvidenceSearcher(EvidenceSearcher(store, vectors, embedding, profile), store, reranker)


def _fail(report, status, code, message, stage):
    if preserve_expired_failure(report["result"], status, code, message, stage):
        return
    if report["result"].get("status") in NORMAL:
        report["pre_failure_result"] = deepcopy(report["result"])
    report["result"].update(status=status, answer=None, failure_stage=stage, stop_reason=code,
                            error={"code": code, "message": message})


def _final_deadline(report, budget, stage):
    if budget.remaining_seconds() > 0:
        return
    previous = report["result"]
    if previous.get("status") == "budget_exceeded" and (previous.get("error") or {}).get("code") == "deadline_exceeded":
        return
    if previous.get("error") and previous["error"].get("code") != "deadline_exceeded":
        failure = {"status": previous["status"], "failure_stage": previous.get("failure_stage"),
                   "error": deepcopy(previous["error"])}
        previous["interrupted_failure"] = deepcopy(failure)
        report["interrupted_failure"] = failure
    _fail(report, "budget_exceeded", "deadline_exceeded", "本轮截止预算已到，停止发布成功结果", stage)


def run_question_agent(query, selected_versions, *, project_root=ROOT, top_k=5, max_chars=8000, enforce_remaining_budget=False) -> dict:
    pairs = validate_agent_input(query, selected_versions, top_k=top_k, max_chars=max_chars)
    root = Path(project_root).resolve()
    now = datetime.now(timezone.utc)
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    versions = [{"paper_id": p, "parse_revision": r} for p, r in pairs]
    report = {"task": "D8", "mode": "agent", "run_id": now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12],
              "started_at_utc": now.isoformat(), "finished_at_utc": None,
              "runtime_version": RUNTIME_VERSION, "agent_version": AGENT_VERSION,
              "prompt_version": AGENT_PROMPT_VERSION, "action_schema_version": ACTION_SCHEMA_VERSION,
              "selection_version": AGENT_SELECTION_VERSION, "top_k": top_k, "max_chars": max_chars,
              "policy": asdict(policy), "configuration": None, "index_profile": None,
              "strategy_binding": None, "embedding_statistics": None,
              "embedding_requests": 0, "rerank_requests": 0,
              "rerank_statistics": empty_rerank_statistics(), "llm_requests": 0, "network_requests": 0,
              "chat_statistics": None, "chat_attempts": [], "semantic_support_status": "not_reviewed",
              "is_answer_accuracy": False, "deadline_enforcement":
              "phase_checks_and_remaining_chat_timeout; synchronous_hard_wall_clock_abort_not_verified",
              "result": {"status": "tool_error", "query": query, "selected_versions": versions,
                         "answer": None, "error": None, "failure_stage": "input_verification",
                         "stop_reason": None, "statistics": {
                             "embedding": None, "chat": None, "rerank": empty_rerank_statistics()}}}
    if enforce_remaining_budget:
        report["budget_implementation_version"] = "d9-remaining-budget-v1"
        report["deadline_enforcement"] = "remaining_embedding_and_chat_timeout_and_stage_checks; hard_process_abort_unverified"
    stage, pipeline_started = "configuration", False
    try:
        strategy = json.loads((root / STRATEGY_PATH).read_text(encoding="utf-8"))
        report["strategy_binding"] = {"path": STRATEGY_PATH,
                                      "schema_revision": strategy["schema_revision"],
                                      "public_configuration_verified": False}
        stage = "configuration"
        embedding, chat = load_embedding_settings(), load_llm_settings()
        profile = load_current_profile(root)
        report["configuration"] = public_configuration(embedding, chat, profile, policy)
        report["index_profile"] = deepcopy(profile)
        validate_frozen_configuration(strategy, embedding, chat, profile, policy)
        report["strategy_binding"].update(public_configuration_verified=True)
        if budget.remaining_seconds() <= 0:
            _fail(report, "budget_exceeded", "deadline_exceeded", "配置结束时截止预算已到", stage)
        else:
            stage = "resources"
            with ExitStack() as resources:
                store, searcher = resources.enter_context(open_retrieval_resources(root, embedding, profile))
                enforce_remaining_budget = enforce_remaining_budget or getattr(searcher, "reranker", None) is not None
                remaining(budget.remaining_seconds)
                client = resources.enter_context(RecordedLLM(chat, policy=policy, budget=budget))
                stage, pipeline_started = "pipeline", True
                result = answer_question_agent(query, pairs, searcher, store, client, project_root=root,
                                               top_k=top_k, max_chars=max_chars,
                                               **({"enforce_remaining_budget": True} if enforce_remaining_budget else {}))
                report["result"] = deepcopy(result)
                report["embedding_statistics"] = deepcopy(result["statistics"].get("embedding"))
                if result.get("status") not in STATUSES:
                    _fail(report, "tool_error", "unexpected_status", "Agent 核心返回未约定终态", stage)
                stage = "resource_cleanup"
    except FrozenConfigurationError:
        _fail(report, "tool_error", "configuration_mismatch", "实际公开配置与 D8 A 冻结策略不一致", stage)
    except DeadlineExceeded:
        _fail(report, "budget_exceeded", "deadline_exceeded", "资源准备结束时截止预算已到", stage)
    except Exception:
        _fail(report, "tool_error", "local_error", "本机配置、资源或清理步骤失败", stage)
    _final_deadline(report, budget, stage)
    stats = report["embedding_statistics"]
    report["embedding_requests"] = stats.get("embedding_requests") if isinstance(stats, dict) else (None if pipeline_started else 0)
    report["rerank_statistics"] = deepcopy(report["result"].setdefault("statistics", {}).get("rerank")
                                           or empty_rerank_statistics())
    report["rerank_requests"] = report["rerank_statistics"]["requests"]
    report["chat_statistics"] = deepcopy(budget.statistics())
    report["chat_attempts"] = deepcopy(budget.records)
    report["llm_requests"] = budget.http_requests
    report["sdk_request_attempts"] = budget.attempts
    report["network_requests"] = (report["embedding_requests"] + budget.http_requests + report["rerank_requests"]
                                  if type(report["embedding_requests"]) is int else None)
    report["result"].setdefault("statistics", {})["chat"] = deepcopy(report["chat_statistics"])
    if not pipeline_started:
        report["result"]["statistics"]["embedding"] = {"embedding_requests": 0, "failed_requests": 0,
                                                       "total_tokens": None}
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    commit_result(report["result"], budget, "resource_cleanup")
    report["business_commit"] = deepcopy(report["result"]["business_commit"])
    safe, replacements = diagnostic_snapshot(report)
    if replacements:
        safe["runtime_diagnostic_replacements"] = replacements
    try:
        return save_agent_run(safe, project_root=root)
    except Exception:
        # Even path/setup failure before the export helper's recovery block
        # must return the consumed attempts in memory for CLI JSON output.
        safe["pre_export_result"] = deepcopy(safe["result"])
        _fail(safe, "tool_error", "export_error", "D8 记录导出未完成，已发生的调用仍保留在本轮报告中", "export")
        # Export is an independent fault after the committed business result.
        # Its duration cannot retroactively expire the saved core result.
        # Attempts, usage and business elapsed time were frozen before export.
        safe["result"]["statistics"]["chat"] = deepcopy(safe["chat_statistics"])
        safe["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        safe.update({key: deepcopy(safe["result"].get(key)) for key in
                     ("status", "query", "selected_versions", "answer", "error", "failure_stage", "stop_reason")})
        safe["history_report"] = "archive/run_logs/d8/agent_" + safe["run_id"] + ".json"
        safe["export"] = {"status": "failed", "failed_step": "export_setup",
                          "recovery_history_report": None, "recovery_saved": False,
                          "latest_recovery_saved": False}
        return safe
