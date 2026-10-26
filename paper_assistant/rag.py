"""D5 D：固定一轮检索、结构化生成、引用回查与共享预算修复。

调用者持有 SQLite、Qdrant 和聊天客户端；本模块不再打开或关闭它们。
answered 表示结构与定位检查通过，语义支持仍须另外评阅。
"""

from copy import deepcopy
import json
from pathlib import Path

from paper_assistant.citations import validate_citations
from paper_assistant.context import ContextError, build_messages, prepare_context, restore_conversation_evidence, token_context_options
from paper_assistant.evidence_reading import read_evidence_context
from paper_assistant.generation import DraftParseError, generate_draft, parse_answer_draft
from paper_assistant.llm_client import LLMCallError
from paper_assistant.search import SearchError
from paper_assistant.rerank_statistics import empty_rerank_statistics
from paper_assistant.deadline import DeadlineExceeded, final_deadline, search_with_budget
from paper_assistant.schemas import answer_evidence_status
from paper_assistant.source_scope import (
    Registry, SourceScopeError, attach_source_requirement, identify_source_requirement,
    prepare_scoped_context, prepare_unavailable_source_context, validate_citation_scope,
)


RAG_VERSION = "d12-basis-aware-fixed-rag-v1"
SCOPED_RAG_VERSION = "d12-basis-aware-fixed-rag-source-budget-v1"
TIMED_RAG_VERSION = "d12-basis-aware-fixed-rag-budget-v1"


def answer_question(query, selected_versions, searcher, store, client, *, project_root: Path,
                    top_k=5, max_chars=8000, source_registry=None, enforce_remaining_budget=False,
                    conversation_context=None) -> dict:
    """执行一轮，保留步骤；仅引用全部通过时产生可发布的 answer。"""
    timed = bool(enforce_remaining_budget or source_registry is not None)
    result = {"status": "tool_error", "query": query if isinstance(query, str) else None,
              "selected_versions": [], "top_k": top_k if type(top_k) is int else None,
              "max_chars": max_chars if type(max_chars) is int else None,
              "rag_version": SCOPED_RAG_VERSION if source_registry is not None else (TIMED_RAG_VERSION if timed else RAG_VERSION),
              "search": None, "context": None, "generation": None, "citation_checks": [],
              "citation_repairs": [], "answer": None, "error": None, "failure_stage": "input",
              "semantic_support_status": "not_reviewed", "statistics": {
                  "embedding": None, "chat": None, "rerank": empty_rerank_statistics()}}
    stage = "input"
    requirement, qualification, source_issue = None, None, None
    if source_registry is not None:
        result.update(source_requirement=None, source_qualification=None, source_scope_checks=[])

    if timed:
        result["budget_implementation_version"] = "d9-remaining-budget-v1"
        result["deadline_enforcement"] = "remaining_chat_timeout_and_retrieval_budget_adapter_and_stage_checks; hard_process_abort_unverified"

    def finish():
        final_deadline(result, client.budget, stage)
        result["statistics"]["chat"] = deepcopy(client.budget.statistics())
        return result

    def deadline():
        if client.budget.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "本轮截止预算已到，停止后续步骤")

    def fail(status, code, message):
        result.update(status=status, answer=None, failure_stage=stage, error={"code": code, "message": message})
        return finish()

    try:
        if not isinstance(query, str) or not query.strip():
            raise ContextError("invalid_question", "问题必须为非空字符串")
        if type(top_k) is not int or top_k != 5:
            raise ContextError("invalid_top_k", "D5 固定流程 top_k 必须为 5")
        if type(max_chars) is not int or not 1 <= max_chars <= 8000:
            raise ContextError("invalid_character_budget", "正文字符预算必须为 1–8000 的整数")
        if not isinstance(selected_versions, list) or not 1 <= len(selected_versions) <= 3:
            raise ContextError("invalid_versions", "必须选择 1–3 个完整论文/处理版本配对")
        pairs = []
        for pair in selected_versions:
            if (not isinstance(pair, (tuple, list)) or len(pair) != 2
                    or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in pair)
                    or tuple(pair) in pairs):
                raise ContextError("invalid_versions", "论文/处理版本配对非法或重复")
            pairs.append(tuple(pair))
        result["selected_versions"] = [{"paper_id": p, "parse_revision": r} for p, r in pairs]
        if source_registry is not None:
            stage = "source_scope"
            if not isinstance(source_registry, Registry) or not set(pairs).issubset(set(source_registry.pairs)):
                raise SourceScopeError("source_registry_scope_mismatch", "来源表与所选完整版本不一致")
            source_registry.revalidate()
            requirement = identify_source_requirement(query)
            result["source_requirement"] = deepcopy(requirement)
            deadline()
            if requirement["resolution"] == "ambiguous":
                source_issue = ("source_constraint_ambiguous", "原问题的摘要限定存在歧义，当前没有可用于该限定的论文证据。")
            elif requirement["required_scope"] == "abstract" and not source_registry.has_qualified_abstract(pairs):
                source_issue = ("source_scope_unavailable", "所选版本尚无核定且完整可用的摘要证据范围。")
        version_chunks = {pair: store.get_version_chunks(*pair) for pair in pairs}
        context_options = token_context_options(registry=source_registry,
            candidates=[row for chunks in version_chunks.values() for row in chunks])
        if source_issue:
            scoped = prepare_unavailable_source_context(query, pairs, requirement, source_registry,
                                                       source_issue[1], max_chars=max_chars, **context_options)
            context, qualification = scoped["context"], scoped["qualification"]
            result["stop_reason"] = source_issue[0]
            result["statistics"]["embedding"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
        else:
            stage = "retrieval"
            deadline()
            search = search_with_budget(searcher, query, pairs, top_k=top_k,
                                        remaining_seconds=client.budget.remaining_seconds if timed else None)
            result["search"] = deepcopy(search)
            if isinstance(search, dict):
                result["statistics"]["embedding"] = deepcopy(search.get("statistics"))
                result["statistics"]["rerank"] = deepcopy(search.get("rerank_statistics") or empty_rerank_statistics())
            deadline()
            stage = "context"
            if (not isinstance(search, dict) or search.get("query") != query
                    or search.get("selected_versions") != result["selected_versions"]
                    or type(search.get("top_k")) is not int or search["top_k"] != top_k
                    or not isinstance(search.get("results"), list) or len(search["results"]) > top_k):
                raise ContextError("search_scope_mismatch", "检索结果的问题、版本配对或候选范围与本轮不同")
            context = prepare_context(search, max_chars=max_chars, **context_options)
            if source_registry is not None:
                scoped = prepare_scoped_context(search, requirement, source_registry, max_chars=max_chars, **context_options)
                context, qualification = scoped["context"], scoped["qualification"]
        if not source_issue and ((conversation_context or {}).get("referenced_evidence_ids")
                                 or context.get("max_tokens") is not None):
            context = restore_conversation_evidence(context, conversation_context, version_chunks,
                max_chunks=5, source_registry=source_registry, source_requirement=requirement)
            if context.get("max_tokens") is not None:
                context = read_evidence_context(context, version_chunks, store=store, max_chunks=5,
                    source_registry=source_registry, source_requirement=requirement)
            if qualification is not None:
                qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
        if source_registry is not None:
            result["source_qualification"] = deepcopy(qualification)
        if not context["shown_evidence"] and "evidence_limitation" not in context:
            context["evidence_limitation"] = ("本轮没有可展示的核定摘要证据。" if requirement is not None
                and requirement["required_scope"] == "abstract" else "本轮没有可展示的论文证据。")
        result["context"] = deepcopy(context)
        deadline()
        stage = "generation"
        generated = generate_draft(context, client,
                                   **({"conversation_context": conversation_context} if conversation_context is not None else {}),
                                   **({"source_requirement": requirement} if requirement is not None else {}))
        result["generation"] = deepcopy(generated)
        if generated["status"] != "draft_valid" and client.budget.remaining_seconds() <= 0:
            result["interrupted_failure"] = {"status": generated["status"], "failure_stage": stage,
                                             "error": deepcopy(generated.get("error"))}
        deadline()
        if generated["status"] != "draft_valid":
            error = generated["error"] or {"code": "generation_failed", "message": "草稿生成失败"}
            return fail(generated["status"], error["code"], error["message"])
        draft = generated["draft"]
        deadline()
        for turn in range(2):
            stage = "citations" if turn == 0 else "citation_recheck"
            deadline()
            validated = validate_citations(draft, context, store, project_root=project_root)
            result["citation_checks"].append(deepcopy(validated))
            source_invalid = False
            if source_registry is not None:
                scoped_check = validate_citation_scope(draft, context, qualification, source_registry,
                                                       requirement=requirement)
                result["source_scope_checks"].append(deepcopy(scoped_check))
                if scoped_check["status"] == "tool_error" or (validated["status"] == "valid" and scoped_check["status"] != "valid"):
                    validated = scoped_check
                    source_invalid = True
            if validated["status"] != "valid" and client.budget.remaining_seconds() <= 0:
                result["interrupted_failure"] = {"status": validated["status"], "failure_stage": stage,
                                                 "error": deepcopy(validated.get("error"))}
            deadline()
            if validated["status"] == "valid":
                if not draft.get("reason") and context.get("evidence_limitation"):
                    draft["reason"] = context["evidence_limitation"]
                result.update(status=draft["status"], error=None, failure_stage=None,
                              answer={**deepcopy(draft), "evidence_refs": deepcopy(validated["evidence_refs"]),
                                      "evidence_sources": deepcopy(validated["evidence_sources"]),
                                      "evidence_status": answer_evidence_status(draft),
                                      "semantic_support_status": "not_reviewed"})
                return finish()
            if validated["status"] == "tool_error":
                error = validated["error"]
                return fail("tool_error", error["code"], error["message"])
            if turn or client.budget.repairs >= client.budget.policy.max_repairs:
                return fail("invalid_output", "source_scope_invalid" if source_invalid else "citation_invalid",
                            "引用或来源检查未通过，且本轮没有剩余修复额度")
            stage = "citation_repair"
            deadline()
            # 重新构建原 system/user 数据，不扩充证据。C 若已修复就不会走这里。
            base = build_messages(query, context, conversation_context=conversation_context)
            if requirement is not None:
                base = attach_source_requirement(base, query, requirement)
            last_response = generated["generation_attempts"][-1]["response"]
            messages = [*base, {"role": "assistant", "content": last_response["content"]},
                        {"role": "user", "content": json.dumps({"action": "repair_citations",
                         "errors": [{"claim_index": check["claim_index"], "citation_index": check["citation_index"],
                                     "code": check["code"]} for check in validated["checks"] if check["status"] != "valid"],
                         "instruction": "Return a complete answered AnswerDraft. Use the original shown evidence and allowed IDs for paper_evidence. When evidence is missing, give useful model_knowledge or analysis with the correct basis and explain limitations. Model knowledge has no paper citations. Do not add sources or invent IDs."}, ensure_ascii=False)}]
            repair = {"messages": deepcopy(messages), "response": None, "draft": None, "parse_error_code": None}
            result["citation_repairs"].append(repair)
            try:
                response = client.invoke(messages, purpose="repair", require_json=True)
            except LLMCallError as error:
                repair["error"] = {"code": error.code, "message": str(error), "attempts": deepcopy(error.attempts)}
                raise
            repair["response"] = deepcopy(response)
            deadline()
            if response["status"] != "success":
                repair["parse_error_code"] = response.get("output_issue") or "invalid_output"
                return fail("invalid_output", repair["parse_error_code"], "引用修复响应无效")
            try:
                draft = parse_answer_draft(response["content"]).model_dump(mode="json")
                if draft["status"] != "answered":
                    raise DraftParseError("answer_required")
            except DraftParseError as error:
                repair["parse_error_code"] = error.code
                deadline()
                return fail("invalid_output", error.code, "引用修复草稿未通过结构检查")
            repair["draft"] = deepcopy(draft)
            deadline()
        return fail("invalid_output", "citation_invalid", "引用检查未通过")
    except SearchError as error:
        result["statistics"]["embedding"] = deepcopy(error.statistics)
        result["statistics"]["rerank"] = deepcopy(getattr(error, "rerank_statistics", empty_rerank_statistics()))
        result["search_error"] = {"stage": error.stage if error.stage in
                                  ("input", "configuration", "ready", "embedding", "query", "evidence") else "retrieval"}
        return fail(error.status, error.code, "本轮证据检索失败")
    except DeadlineExceeded:
        result["statistics"]["embedding"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
        return fail("budget_exceeded", "deadline_exceeded", "本轮检索前截止预算已到")
    except ContextError as error:
        return fail("tool_error", error.code, str(error))
    except SourceScopeError as error:
        if result["search"] is None and stage == "source_scope":
            result["statistics"]["embedding"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
        return fail("tool_error", error.code, str(error))
    except LLMCallError as error:
        if timed and result["search"] is None and stage in ("retrieval", "source_scope"):
            result["statistics"]["embedding"] = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None}
        return fail(error.status, error.code, str(error))
    except Exception:
        return fail("tool_error", "local_error", "本轮固定问答步骤未完成，详情见安全阶段记录")
