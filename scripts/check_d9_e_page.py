"""D9 E offline Streamlit AppTest checks; runtime calls are mocked.

Run: .venv/Scripts/python.exe -X utf8 -m scripts.check_d9_e_page
Synthetic questions/evidence only. No .env, corpus, ready store or evaluation
questions are read. External HTTP/socket sends are blocked; AppTest's local
asyncio socketpair transport is allowed. This is not browser/answer validation.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import streamlit
from streamlit.testing.v1 import AppTest

from paper_assistant import d9_runtime as target, import_runtime


ROOT = Path(__file__).resolve().parents[1]
MODES = ("fixed_rag", "agent")
STATUSES = ("answered", "insufficient_evidence", "tool_error", "invalid_output", "budget_exceeded")
PAIR = ("offline-paper", "offline-revision")
READY = [{"paper_id": PAIR[0], "parse_revision": PAIR[1], "title": "Offline paper"},
         {"paper_id": "offline-two", "parse_revision": "offline-r2", "title": "Offline two"}]
SECRET = "offline-runtime-secret-must-not-appear"
EVIDENCE = "Exact full original evidence with `backticks` and <tags>.\nD9-E-ORIGINAL-MARKER"
CLAIM = "Supported offline claim."
SECOND_EVIDENCE = "Separate original evidence for the second claim.\nD9-E-SECOND-SOURCE-MARKER"
SECOND_CLAIM = "A second supported offline claim."
MERGED_CLAIM = "**Connecting the evidence.** Both passages explain related parts of the same mechanism."
EXAMPLES = {}
COUNTS = {"mock_runtime_submissions": 0}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(identifier="offline-c1"):
    return {"chunk_id": identifier, "paper_id": PAIR[0], "parse_revision": PAIR[1],
            "title": "Offline paper", "arxiv_version": "v1", "pdf_page": 2,
            "text": EVIDENCE, "shown_text": EVIDENCE, "rank": 1, "score": 0.8}


def report(status="answered", mode="fixed_rag", query="Offline question?", submission_id="offline-token",
           two_claims=False, evidence_text=EVIDENCE):
    evidence = source()
    evidence.update(text=evidence_text, shown_text=evidence_text)
    sources = [evidence]
    if status == "answered" and two_claims:
        second = source("offline-c2")
        second.update(text=SECOND_EVIDENCE, shown_text=SECOND_EVIDENCE, pdf_page=3)
        sources.append(second)
    answer = ({"claims": [{"claim": CLAIM, "citation_ids": [evidence["chunk_id"]]}],
               "evidence_sources": sources} if status == "answered" else
              {"claims": [], "evidence_sources": [], "reason": "Offline evidence lacks the requested quantity."}
              if status == "insufficient_evidence" else None)
    if status == "answered" and two_claims:
        answer["claims"].append({"claim": SECOND_CLAIM, "basis": "analysis", "citation_ids": ["offline-c2"]})
        answer["claims"].append({"claim": MERGED_CLAIM, "basis": "paper_evidence",
                                 "citation_ids": ["offline-c2", "offline-c1"]})
        answer["claims"].extend([
            {"claim": "通用概念补充。", "basis": "model_knowledge", "citation_ids": []},
            {"claim": "不引用原文的问题分析。", "basis": "analysis", "citation_ids": []}])
        answer.update(evidence_status="mixed", reason="论文证据覆盖部分问题，其余内容按依据标注。")
    search = {"query": query, "status": "success", "results": [*sources, source("offline-body")],
              "statistics": {"embedding_requests": 1, "total_tokens": 7}}
    qualification = {"requirement": {"required_scope": "abstract", "resolution": "explicit"},
                     "registry_sha256": "offline-source-table-sha", "raw_candidate_count": len(sources) + 1,
                     "eligible_ids": [row["chunk_id"] for row in sources],
                     "shown_ids": [row["chunk_id"] for row in sources],
                     "decisions": [{"chunk_id": row["chunk_id"], "round": "initial", "coverage": "abstract_full",
                                    "eligible": True, "included": True, "reason": None} for row in sources]
                                   + [{"chunk_id": "offline-body", "round": "initial", "coverage": "body",
                                       "eligible": False, "included": False, "reason": "source_scope_body"}]}
    core = {"status": status, "answer": deepcopy(answer), "query": query, "search": search,
            "context": {"shown_evidence": sources}, "source_qualification": qualification,
            "initial_source_qualification": deepcopy(qualification),
            "source_scope_checks": [{"status": "valid", "offline_fixture": True}],
            "stop_reason": "answer_validated" if status == "answered" else "offline_" + status}
    if mode == "agent":
        retry = {"query": "Offline retry query", "status": "success",
                 "results": [source("offline-c2"), source("offline-body")],
                 "statistics": {"embedding_requests": 1, "total_tokens": 9}}
        core.update(search_rounds=[{"round": 1, "query": query, "status": "success", "search": search,
                                   "statistics": deepcopy(search["statistics"])},
                                  {"round": 2, "query": retry["query"], "status": "success", "search": retry,
                                   "statistics": deepcopy(retry["statistics"])}],
                    retry_decision={"missing_information": "Offline missing fact", "retry_query": retry["query"],
                                    "executed": True},
                    merge_trace={"new_returned_ids": ["offline-c2", "offline-not-shown"],
                                 "new_shown_ids": ["offline-c2"], "final_shown_ids": ["offline-c1", "offline-c2"]})
    return {"task": "D9", "run_id": "offline-" + submission_id, "submission_id": submission_id,
            "mode": mode, "status": status, "query": query,
            "selected_versions": [{"paper_id": PAIR[0], "parse_revision": PAIR[1]}],
            "answer": answer, "error": None if answer else {"code": "offline_failure"}, "result": core,
            "embedding_requests": 2 if mode == "agent" else 1, "llm_requests": 2 if mode == "agent" else 1,
            "network_requests": 4 if mode == "agent" else 2,
            "embedding_statistics": {"total_tokens": 16 if mode == "agent" else 7},
            "chat_statistics": {"total_tokens": None, "known_total_tokens": 0, "network_retries": 0, "repairs": 0},
            "history_report": "archive/run_logs/d9/offline-page-report.json", "export": {"status": "saved"},
            "is_answer_accuracy": False}


class PageChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(target, "list_ready_versions", return_value=deepcopy(READY)))
        self.status = "answered"
        self.two_claims = False
        self.expected_pairs = [PAIR]
        self.standalone_questions = {}
        self.evidence_text = EVIDENCE
        self.saved_mode = "agent"

        def submitted(query, selected_versions, *, mode, project_root, submission_id,
                      conversation_id=None, conversation_history=None, library_mode=False):
            self.assertEqual(mode, "agent")
            self.assertTrue(library_mode)
            self.assertEqual(selected_versions, self.expected_pairs)
            self.assertEqual(project_root, ROOT)
            self.assertIsInstance(submission_id, str)
            self.assertTrue(submission_id)
            standalone = self.standalone_questions.get(query, query)
            saved = report(self.status, self.saved_mode, standalone, submission_id, two_claims=self.two_claims,
                           evidence_text=self.evidence_text)
            saved.update(conversation_id=conversation_id, conversation_history=deepcopy(conversation_history),
                         user_question=query, standalone_question=standalone)
            if self.status == "needs_clarification":
                saved["standalone_question"] = None
                saved["clarification_question"] = "你是指第一个方法还是第二个方法？"
            return saved

        self.runtime = self.stack.enter_context(patch.object(target, "run_question", side_effect=submitted))
        self.addCleanup(lambda: COUNTS.update(
            mock_runtime_submissions=COUNTS["mock_runtime_submissions"] + self.runtime.call_count))
        self.download = self.stack.enter_context(patch.object(target, "download_payloads", side_effect=
            lambda saved, *, project_root: (json.dumps(saved, ensure_ascii=False).encode("utf-8"), b"Offline Markdown")))

    def app(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        self.assertFalse(app.exception)
        return app

    def text(self, app):
        values = [str(item.value) for kind in ("text", "caption", "code", "markdown", "error", "warning", "info", "success")
                  for item in getattr(app, kind)]
        values.extend(str(item.label) for item in app.get("button"))
        values.extend(str(item.proto.popover.label) for item in app.get("popover"))
        return "\n".join(values)

    def submit(self, app, saved_mode="agent", query="Offline question?"):
        # Both saved report formats remain renderable; fresh runtime inputs are
        # always agent, even when an old session still has question_mode.
        self.saved_mode = saved_mode
        app.session_state["question_mode"] = saved_mode
        self.assertFalse(app.radio)
        app.multiselect(key="selected_versions").set_value([PAIR])
        app.chat_input(key="question").set_value(query).run()
        self.assertFalse(app.exception)
        if "d9_submission_future" in app.session_state:
            future = app.session_state["d9_submission_future"]
            if future is not None:
                try:
                    future.result(timeout=2)
                except Exception:
                    # UI collects and renders the runtime failure on its next redraw.
                    pass
                app.run()
                self.assertFalse(app.exception)
        self.assertFalse(app.radio)
        for label in ("问答模式", "固定 RAG", "一次补检索 Agent", "自动模式"):
            self.assertNotIn(label, self.text(app))
        return app

    def capture(self, app, mode, status):
        EXAMPLES[mode + ":" + status] = {
            "mode": mode, "status": status, "capture_source": "actual AppTest element tree",
            "elements": {kind: [str(item.value) for item in getattr(app, kind)]
                         for kind in ("text", "caption", "code", "warning", "error", "info", "success")},
            "expander_labels": [str(item.label) for item in app.get("expander")],
            "runtime_report": deepcopy(app.session_state["current_report"]),
            "exception_count": len(app.exception)}

    def test_two_modes_five_terminal_states_and_full_citations(self):
        legacy_report = report
        first_quote, second_quote = EVIDENCE.split("\n")[0], SECOND_EVIDENCE.split("\n")[0]

        def quoted_report(*args, **kwargs):
            saved = legacy_report(*args, **kwargs)
            if saved["status"] == "answered" and saved["mode"] == "agent":
                claims = saved["answer"]["claims"]
                claims[0]["evidence_quotes"] = [{"chunk_id": "offline-c1", "quote": first_quote}]
                claims[1]["evidence_quotes"] = [{"chunk_id": "offline-c2", "quote": second_quote}]
                claims[2]["evidence_quotes"] = [*claims[1]["evidence_quotes"], *claims[0]["evidence_quotes"]]
                saved["result"]["answer"] = deepcopy(saved["answer"])
            return saved

        self.stack.enter_context(patch(__name__ + ".report", side_effect=quoted_report))
        for mode in MODES:
            for status in STATUSES:
                with self.subTest(mode=mode, status=status):
                    self.status = status
                    self.two_claims = status == "answered"
                    before = self.runtime.call_count
                    app = self.submit(self.app(), mode)
                    self.assertEqual(self.runtime.call_count - before, 1)
                    saved = app.session_state["current_report"]
                    self.assertEqual((saved["mode"], saved["status"]), (mode, status))
                    text = self.text(app)
                    if status != "answered":
                        self.assertIn(status, text)
                    if status in ("tool_error", "invalid_output", "budget_exceeded"):
                        self.assertFalse(app.error)
                        self.assertIn("这次回答暂未完整生成，已找到的论文资料保存在下方。", text)
                        evidence_panel = next(item for item in app.get("expander")
                                              if item.label == "查看本轮检索到的原文")
                        self.assertFalse(evidence_panel.proto.expanded)
                        self.assertIn(EVIDENCE, self.text(evidence_panel))
                        details = next(item for item in app.get("expander") if item.label == "回答详情与下载")
                        self.assertIn(status, self.text(details))
                        self.assertEqual(saved["status"], status)
                    self.assertIn(EVIDENCE, text)
                    source_locations = text + "\n" + "\n".join(str(item.label) for item in app.get("expander"))
                    self.assertIn("PDF 文件页序 2", source_locations)
                    self.assertIn("source_scope_body", text)
                    if status == "answered":
                        self.assertIn(CLAIM, text)
                        self.assertIn(SECOND_CLAIM, text)
                        for paragraph in (CLAIM, SECOND_CLAIM, MERGED_CLAIM,
                                          "通用概念补充。", "不引用原文的问题分析。"):
                            self.assertIn(paragraph, [item.value for item in app.markdown])
                        popovers = app.get("popover")
                        self.assertEqual([item.proto.popover.label for item in popovers],
                                         ["[1]", "[2]", "[2] [1]"])
                        self.assertIn("模型知识", text)
                        self.assertIn("分析", text)
                        self.assertIn("通用概念补充。", text)
                        self.assertIn("不引用原文的问题分析。", text)
                        self.assertIn(saved["answer"]["reason"], text)
                        from paper_assistant.agent_export import render_agent_run
                        from paper_assistant.answer_export import render
                        export_report = deepcopy(saved)
                        for row in export_report["answer"]["evidence_sources"]:
                            row["pdf_absolute_path"] = str(ROOT / "data/papers/offline.pdf")
                        for markdown in (render_agent_run(export_report), render(export_report, project_root=ROOT)):
                            self.assertIn("模型知识", markdown)
                            self.assertIn("分析前提引用", markdown)
                            self.assertIn("通用概念补充。", markdown)
                            self.assertIn(saved["answer"]["reason"], markdown)
                            self.assertNotIn("引用：\n", markdown)
                            if mode == "agent":
                                self.assertIn("本项原文短引句", markdown)
                                self.assertIn(first_quote, markdown)
                                self.assertIn(second_quote, markdown)
                            else:
                                self.assertNotIn("本项原文短引句", markdown)
                        for number, (claim_text, citation_id, original, other_id, other_original, page) in enumerate(
                                ((CLAIM, "offline-c1", EVIDENCE, "offline-c2", SECOND_EVIDENCE, 2),
                                 (SECOND_CLAIM, "offline-c2", SECOND_EVIDENCE, "offline-c1", EVIDENCE, 3)), start=1):
                            popover = next(item for item in popovers if item.proto.popover.label == f"[{number}]")
                            self.assertIn(popover.key, (f"citation_{saved['submission_id']}_{number}",
                                                        f"citation_{saved['run_id']}_{number}"))
                            citation_text = self.text(popover)
                            self.assertIn("本段引用", citation_text)
                            if mode == "agent":
                                self.assertIn("本段原文短引句", citation_text)
                                self.assertIn(first_quote if number == 1 else second_quote, [item.value for item in popover.code])
                            else:
                                self.assertNotIn("本段原文短引句", citation_text)
                            self.assertNotIn("分析前提引用", citation_text)
                            self.assertNotIn("用户原问题：", citation_text)
                            self.assertNotIn("补全后的完整问题：", citation_text)
                            self.assertNotIn(claim_text, citation_text)
                            self.assertIn(citation_id, citation_text)
                            self.assertIn(original, citation_text)
                            self.assertNotIn(other_id, citation_text)
                            self.assertNotIn(other_original, citation_text)
                            source_locations = citation_text + "\n" + "\n".join(
                                str(item.label) for item in popover.get("expander"))
                            self.assertIn(f"PDF 文件页序 {page}", source_locations)
                        merged_text = self.text(popovers[2])
                        self.assertNotIn(MERGED_CLAIM, merged_text)
                        self.assertNotIn("用户原问题：", merged_text)
                        self.assertNotIn("补全后的完整问题：", merged_text)
                        self.assertIn(EVIDENCE, merged_text)
                        self.assertIn(SECOND_EVIDENCE, merged_text)
                        self.assertIn("引用 2 · PDF 文件页序 3", merged_text)
                        self.assertIn("引用 1 · PDF 文件页序 2", merged_text)
                    else:
                        self.assertNotIn(CLAIM, text)
                    if status == "insufficient_evidence":
                        self.assertIn("Offline evidence lacks", text)
                    self.capture(app, mode, status)

    def test_initial_reruns_selection_and_mode_changes_never_run(self):
        app = self.app()
        app.run()
        app.run()
        app.session_state["question_mode"] = "fixed_rag"
        app.run()
        app.multiselect[0].set_value([(READY[1]["paper_id"], READY[1]["parse_revision"])]).run()
        self.assertEqual(self.runtime.call_count, 0)

    def test_saved_mode_query_pairs_survive_control_changes_and_reruns(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                original = "Saved question " + mode
                standalone = "Complete saved question " + mode
                self.standalone_questions = {original: standalone}
                self.evidence_text = EVIDENCE
                app = self.submit(self.app(), mode, original)
                before = self.runtime.call_count
                frozen = deepcopy(app.session_state["current_report"])
                first_conversation = frozen["conversation_id"]
                self.assertEqual(frozen["conversation_history"], [])
                app.session_state["question_mode"] = "agent" if mode == "fixed_rag" else "fixed_rag"
                app.run()
                self.assertEqual(app.session_state["d9_conversation_id"], first_conversation)
                app.multiselect[0].set_value([(READY[1]["paper_id"], READY[1]["parse_revision"])]).run()
                changed_conversation = app.session_state["d9_conversation_id"]
                self.assertNotEqual(changed_conversation, first_conversation)
                app.run()
                app.run()
                self.assertEqual(self.runtime.call_count, before)
                self.assertNotIn("current_report", app.session_state)
                self.assertFalse(app.get("chat_message"))
                self.assertNotIn(original, self.text(app))
                app.selectbox(key="conversation_picker").set_value(first_conversation).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["selected_versions"], [PAIR])
                self.assertEqual(app.session_state["current_report"], frozen)
                self.assertEqual((frozen["query"], frozen["mode"]), (standalone, mode))
                messages = app.get("chat_message")
                user_text = self.text(next(item for item in messages if item.name == "user"))
                self.assertIn(original, user_text)
                self.assertNotIn(standalone, user_text)
                detail = next(item for item in app.get("expander") if item.label == "回答详情与下载")
                self.assertIn("用户原问题：" + original, self.text(detail))
                self.assertIn("补全后的完整问题：" + standalone, self.text(detail))
                for label in ("固定 RAG", "一次补检索 Agent", "自动模式"):
                    self.assertNotIn(label, self.text(next(item for item in messages if item.name == "assistant")))
                second_original = "Second question " + mode
                second_standalone = "Complete second question " + mode
                self.standalone_questions[second_original] = second_standalone
                newer_evidence = "Newer round original evidence marker " + mode
                self.evidence_text = newer_evidence
                app.button(key="new_conversation").click().run()
                self.assertFalse(app.get("chat_message"))
                self.assertNotIn("current_report", app.session_state)
                app = self.submit(app, query=second_original)
                self.assertEqual(self.runtime.call_count, before + 1)
                second = deepcopy(app.session_state["current_report"])
                self.assertEqual(second["mode"], "agent")
                self.assertNotEqual(second["conversation_id"], first_conversation)
                self.assertEqual(second["conversation_history"], [])
                self.assertNotEqual(second["submission_id"], frozen["submission_id"])
                self.assertEqual(app.session_state["d9_submission_records"][frozen["submission_id"]]["report"], frozen)
                self.assertEqual(app.session_state["d9_submission_records"][second["submission_id"]]["report"], second)
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(self.runtime.call_count, before + 1)
                self.assertEqual(app.session_state["current_report"], second)
                self.assertNotIn("Saved question " + mode, self.text(app))
                self.assertIn("Second question " + mode, self.text(app))
                self.assertEqual(len(app.get("chat_message")), 2)
                users = [item for item in app.get("chat_message") if item.name == "user"]
                self.assertIn(second_original, self.text(users[0]))
                self.assertNotIn(second_standalone, self.text(users[0]))
                popovers = app.get("popover")
                self.assertEqual(len(popovers), 1)
                # AppTest exposes popover contents, but has no open/close interaction API.
                # The browser checks that client-side interaction separately.
                for saved, expected_evidence in ((frozen, EVIDENCE), (second, newer_evidence)):
                    app.selectbox(key="conversation_picker").set_value(saved["conversation_id"]).run()
                    self.assertFalse(app.exception)
                    popover = app.get_by_key("citation_" + saved["submission_id"] + "_1")
                    citation_text = self.text(popover)
                    self.assertIn("本段引用", citation_text)
                    self.assertNotIn("用户原问题：", citation_text)
                    self.assertNotIn("补全后的完整问题：", citation_text)
                    self.assertNotIn("结论：", citation_text)
                    self.assertNotIn(CLAIM, citation_text)
                    self.assertIn(CLAIM, [item.value for item in app.markdown])
                    detail = next(item for item in app.get("expander") if item.label == "回答详情与下载")
                    self.assertIn("用户原问题：" + saved["user_question"], self.text(detail))
                    self.assertIn("补全后的完整问题：" + saved["standalone_question"], self.text(detail))
                    self.assertIn(expected_evidence, citation_text)
                    self.assertIn(PAIR[0], citation_text)
                    self.assertIn("解析版本：" + PAIR[1], citation_text)
                    self.assertIn("PDF 文件页序 2", citation_text)

                followup_question = "它的停止条件是什么？"
                followup_standalone = "Offline second method 的停止条件是什么？"
                self.standalone_questions[followup_question] = followup_standalone
                self.submit(app, query="它的停止条件是什么？")
                followup = deepcopy(app.session_state["current_report"])
                self.assertEqual(followup["mode"], "agent")
                self.assertEqual(followup["conversation_id"], second["conversation_id"])
                history = followup["conversation_history"]
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]["user_question"], second["user_question"])
                self.assertEqual(history[0]["claims"], [
                    {"claim": CLAIM, "basis": "paper_evidence", "citation_ids": ["offline-c1"]}])
                self.assertNotIn(EVIDENCE, json.dumps(history, ensure_ascii=False))
                self.assertNotIn("search_rounds", json.dumps(history, ensure_ascii=False))
                record = app.session_state["d9_submission_records"][followup["submission_id"]]
                self.assertEqual(record["conversation_history"], history)
                before = self.runtime.call_count
                app.run()
                self.assertEqual(len(app.get("chat_message")), 4)
                app.selectbox(key="conversation_picker").set_value(first_conversation).run()
                app.get_by_key("download_json_" + frozen["submission_id"]).click().run()
                self.assertEqual(self.runtime.call_count, before)
                self.assertEqual(record["conversation_history"], history)
                old_popover = app.get_by_key("citation_" + frozen["submission_id"] + "_1")
                old_text = self.text(old_popover)
                self.assertIn(EVIDENCE, old_text)
                self.assertNotIn(newer_evidence, old_text)
                self.assertNotIn("用户原问题：", old_text)
                self.assertNotIn("补全后的完整问题：", old_text)
                self.assertNotIn("结论：", old_text)
                self.assertNotIn(CLAIM, old_text)
                self.assertNotIn(followup_standalone, old_text)
                self.assertEqual(app.session_state["d9_submission_records"][frozen["submission_id"]]["report"], frozen)

                app.button(key="new_conversation").click().run()
                self.assertNotEqual(app.session_state["d9_conversation_id"], second["conversation_id"])
                self.assertFalse(app.get("chat_message"))
                self.assertNotIn("current_report", app.session_state)
                self.assertEqual(app.session_state["d9_submission_records"][frozen["submission_id"]]["report"], frozen)
                self.submit(app, mode, "New conversation " + mode)
                self.assertEqual(app.session_state["current_report"]["conversation_history"], [])

        # 同组论文只调整顺序仍属于同会话，切换解析版本则新建。
        pair_two = (READY[1]["paper_id"], READY[1]["parse_revision"])
        app = self.app()
        app.multiselect(key="selected_versions").set_value([PAIR, pair_two]).run()
        ordered_conversation = app.session_state["d9_conversation_id"]
        app.multiselect(key="selected_versions").set_value([pair_two, PAIR]).run()
        self.assertEqual(app.session_state["d9_conversation_id"], ordered_conversation)
        versions = deepcopy(READY)
        newer_pair = (PAIR[0], "offline-new-revision")
        versions.append({"paper_id": newer_pair[0], "parse_revision": newer_pair[1], "title": "Offline paper"})
        with patch.object(target, "list_ready_versions", return_value=versions):
            app.run()
            app.multiselect(key="selected_versions").set_value([newer_pair, pair_two]).run()
            self.assertNotEqual(app.session_state["d9_conversation_id"], ordered_conversation)

        # 澄清是有效历史交互；故障不作为知识回答，超限丢弃旧轮。
        from paper_assistant.conversation import select_conversation_history
        synthetic_records = {}
        for turn, status in enumerate(("answered", "tool_error", "needs_clarification", "answered", "answered"), start=1):
            saved = report(status, query=f"question-{turn}")
            saved["clarification_question"] = "请明确方法。"
            synthetic_records[str(turn)] = {"conversation_id": "offline-conversation", "report": saved}
        limited = select_conversation_history(synthetic_records, "offline-conversation")
        self.assertEqual([row["user_question"] for row in limited], ["question-3", "question-4", "question-5"])
        self.assertEqual([row["turn"] for row in limited], [2, 3, 4])
        self.assertEqual(limited[0]["clarification_question"], "请明确方法。")
        synthetic_records["5"]["report"]["answer"]["claims"][0]["claim"] = "长回答" * 2000
        self.assertEqual(select_conversation_history(synthetic_records, "offline-conversation"), [])

        self.status = "needs_clarification"
        app = self.submit(self.app(), query="它呢？")
        self.assertIn("你是指第一个方法还是第二个方法？", self.text(app))
        detail = next(item for item in app.get("expander") if item.label == "回答详情与下载")
        self.assertIn("用户原问题：它呢？", self.text(detail))
        self.assertIn("尚待澄清，未形成完整问题。", self.text(detail))
        self.assertFalse(app.error)
        self.status = "answered"
        self.submit(app, query="第一个方法")
        continued = app.session_state["current_report"]
        self.assertEqual(continued["conversation_history"][0]["status"], "needs_clarification")
        self.assertEqual(continued["conversation_history"][0]["user_question"], "它呢？")

        # 旧报告缺少会话字段时，由 query 展示原问题和完整问题。
        legacy_question = "Legacy saved question?"
        self.runtime.side_effect = lambda query, pairs, **kw: report(
            query=query, mode=kw["mode"], submission_id=kw["submission_id"])
        app = self.submit(self.app(), query=legacy_question)
        before = self.runtime.call_count
        app.run()
        legacy_popover = app.get_by_key("citation_" + app.session_state["current_report"]["submission_id"] + "_1")
        self.assertNotIn("用户原问题：", self.text(legacy_popover))
        self.assertNotIn("补全后的完整问题：", self.text(legacy_popover))
        self.assertNotIn("结论：", self.text(legacy_popover))
        self.assertNotIn(CLAIM, self.text(legacy_popover))
        legacy_detail = next(item for item in app.get("expander") if item.label == "回答详情与下载")
        self.assertIn("用户原问题：" + legacy_question, self.text(legacy_detail))
        self.assertIn("补全后的完整问题：" + legacy_question, self.text(legacy_detail))
        self.assertEqual(self.runtime.call_count, before)

    def test_trajectory_keeps_new_recall_and_new_display_distinct(self):
        from paper_assistant.agent_export import render_agent_run

        app = self.submit(self.app(), "agent")
        labels = [str(item.value) for item in app.text]
        self.assertIn("初次实际查询：Offline question?", labels)
        self.assertIn("补查实际查询：Offline retry query", labels)
        self.assertIn("新增召回 ID：offline-c2、offline-not-shown", labels)
        self.assertIn("新增展示 ID：offline-c2", labels)
        self.assertIn("停止原因：answer_validated", labels)
        self.assertIn("问题 embedding 请求：2", labels)
        self.assertIn("聊天请求尝试：2", labels)
        self.assertIn("聊天 tokens：未知", labels)
        self.assertNotIn("聊天 tokens：0", labels)
        legacy_markdown = render_agent_run(app.session_state["current_report"])
        self.assertIn("### 初次查询", legacy_markdown)
        self.assertIn("### 补查查询", legacy_markdown)
        self.assertIn("## 补查与停止", legacy_markdown)
        self.assertIn("Offline retry query", legacy_markdown)

        original_submit = self.runtime.side_effect
        plan = [{"query": query, "selected_versions": [{"paper_id": PAIR[0], "parse_revision": PAIR[1]}]}
                for query in ("Offline mechanism question", "Offline evaluation question")]

        def planned_submission(query, pairs, **kwargs):
            saved = original_submit(query, pairs, **kwargs)
            core = saved["result"]
            core.pop("retry_decision")
            core["merge_trace"].pop("new_returned_ids")
            core["merge_trace"].pop("new_shown_ids")
            core.update(planned_queries=deepcopy(plan), retrieval_strategy="planned_queries")
            saved["planned_queries"] = deepcopy(plan)
            for number, row in enumerate(core["search_rounds"]):
                row.update(kind="planned", query=plan[number]["query"],
                           selected_versions=deepcopy(plan[number]["selected_versions"]),
                           rerank_statistics={"requests": 1, "elapsed_seconds": 0.2})
                row["search"].update(query=plan[number]["query"],
                                     selected_versions=deepcopy(plan[number]["selected_versions"]),
                                     results=[deepcopy(saved["answer"]["evidence_sources"][number])],
                                     ranking_method="rerank")
            return saved

        self.two_claims = True
        self.runtime.side_effect = planned_submission
        self.download.side_effect = lambda saved, *, project_root: (
            json.dumps(saved, ensure_ascii=False).encode("utf-8"), render_agent_run(saved).encode("utf-8"))
        app = self.submit(self.app(), "agent")
        saved = app.session_state["current_report"]
        labels = [str(item.value) for item in app.text]
        self.assertEqual(saved["result"]["query"], "Offline question?")
        for number, query in enumerate(plan, 1):
            self.assertIn(f"计划查询 {number}：" + query["query"], labels)
            self.assertIn(f"计划查询 {number}实际查询：" + query["query"], labels)
            self.assertIn(f"计划查询 {number}实际论文 / 解析版本：" + PAIR[0] + " / " + PAIR[1], labels)
            self.assertIn(f"计划查询 {number} embedding 请求：1", labels)
            self.assertIn(f"计划查询 {number}重排请求：1；重排耗时：0.2 秒", labels)
        self.assertIn("计划查询 1召回 ID：offline-c1", labels)
        self.assertIn("计划查询 2召回 ID：offline-c2", labels)
        self.assertIn("最终展示 ID：offline-c1、offline-c2", labels)
        self.assertFalse(any(label.startswith(("新增召回 ID：", "新增展示 ID：")) for label in labels))
        self.assertFalse(any("补查" in label or "补轮" in label for label in labels))
        markdown = render_agent_run(saved)
        self.assertIn("## 检索计划", markdown)
        self.assertIn("### 计划查询 1", markdown)
        self.assertIn("### 计划查询 2", markdown)
        self.assertIn("Offline mechanism question", markdown)
        self.assertIn("Offline evaluation question", markdown)
        self.assertIn('"selected_versions"', markdown)
        self.assertIn('"embedding_requests": 1', markdown)
        self.assertIn('"requests": 1', markdown)
        final_sources = markdown.split("## 合并后的最终来源", 1)[1].split("## 停止与合并", 1)[0]
        self.assertIn(EVIDENCE.replace("\n", "\\n"), final_sources)
        self.assertIn(SECOND_EVIDENCE.replace("\n", "\\n"), final_sources)
        self.assertNotIn("## 补查与停止", markdown)
        self.assertNotIn("### 补查查询", markdown)
        self.assertFalse(app.exception)

        def autonomous_submission(query, pairs, *, finalize=False, **kwargs):
            saved = original_submit(query, pairs, **kwargs)
            core = saved["result"]
            core.pop("retry_decision")
            versions = [{"paper_id": row["paper_id"], "parse_revision": row["parse_revision"]} for row in READY]
            saved["selected_versions"] = deepcopy(versions)
            rounds = []
            steps = []
            for number in range(1, 6 if finalize else 4):
                actual_query = "Adaptive actual query " + str(number)
                selected = [versions[(number - 1) % 2]]
                evidence = source("offline-c" + str(number))
                search = {"query": actual_query, "status": "success", "results": [evidence],
                          "selected_versions": deepcopy(selected), "statistics": {"embedding_requests": 1}}
                observation = {"status": "no_new_shown_evidence" if number == 2 else "success",
                               "returned_ids": [evidence["chunk_id"]],
                               "new_returned_ids": [evidence["chunk_id"]],
                               "shown_ids": ["offline-c1"] if number == 2 else [evidence["chunk_id"]],
                               "new_shown_ids": [] if number == 2 else [evidence["chunk_id"]]}
                rounds.append({"round": number, "kind": "adaptive", "autonomous_step": number,
                               "query": actual_query, "selected_versions": deepcopy(selected),
                               "status": "success", "search": search, "statistics": search["statistics"],
                               "observation": deepcopy(observation)})
                steps.append({"autonomous_step": number, "remaining_steps": 5 - number,
                              "limit_finalize": False,
                              "parsed_action": {"action": "search", "query": actual_query,
                                                "selected_versions": deepcopy(selected),
                                                "missing_information": "Adaptive missing fact " + str(number)},
                              "tool_observation": deepcopy(observation)})
            steps.append({"autonomous_step": 5 if finalize else 4,
                          "remaining_steps": 0 if finalize else 1, "limit_finalize": finalize,
                          "parsed_action": {"action": "answer", "answer": deepcopy(saved["answer"])}})
            core.update(retrieval_strategy="autonomous", planned_queries=deepcopy(plan),
                        selected_versions=deepcopy(versions), search_rounds=rounds, action_steps=steps,
                        autonomous_step_limit=5, autonomous_steps_used=5 if finalize else 4,
                        limit_finalize=finalize, stop_reason="step_limit_answered" if finalize else "answered")
            return saved

        for finalize in (False, True):
            with self.subTest(limit_finalize=finalize):
                self.runtime.side_effect = lambda query, pairs, **kwargs: autonomous_submission(
                    query, pairs, finalize=finalize, **kwargs)
                app = self.submit(self.app(), "agent")
                saved = app.session_state["current_report"]
                labels = [str(item.value) for item in app.text]
                used = 5 if finalize else 4
                reason = "step_limit_answered" if finalize else "answered"
                self.assertIn(f"自主步数：{used} / 5", labels)
                self.assertIn("触顶收尾：" + ("是" if finalize else "否"), labels)
                self.assertIn("停止原因：" + reason, labels)
                self.assertIn("建议查询（模型可调整或跳过）", self.text(app))
                self.assertIn("建议查询 1：" + plan[0]["query"], labels)
                for number, row in enumerate(saved["result"]["search_rounds"], 1):
                    selected = row["selected_versions"][0]
                    self.assertIn(f"自适应取证 {number}实际查询：Adaptive actual query {number}", labels)
                    self.assertIn(f"自适应取证 {number}自主步骤：{number}", labels)
                    self.assertIn(f"自适应取证 {number}实际论文 / 解析版本："
                                  + selected["paper_id"] + " / " + selected["parse_revision"], labels)
                    self.assertIn(f"自主步骤 {number}模型动作：search", labels)
                    self.assertIn(f"自主步骤 {number}剩余步数：{5 - number}", labels)
                    self.assertIn(f"自主步骤 {number}工具观察：", labels)
                answer_label = "触顶收尾" if finalize else "自主步骤 4"
                self.assertIn(answer_label + "模型动作：answer", labels)
                self.assertIn("no_new_shown_evidence", "\n".join(str(item.value) for item in app.json))
                self.assertIn("新增召回 ID：offline-c2、offline-not-shown", labels)
                self.assertIn("新增展示 ID：offline-c2", labels)
                self.assertFalse(any("补查" in label or "计划查询" in label for label in labels))
                markdown = render_agent_run(saved)
                self.assertIn("## 自主决策", markdown)
                self.assertIn(f"自主步数：{used} / 5", markdown)
                self.assertIn("## 建议查询（模型可调整或跳过）", markdown)
                self.assertIn('"action": "answer"', markdown)
                self.assertIn('"remaining_steps": 0' if finalize else '"remaining_steps": 1', markdown)
                self.assertIn("### " + answer_label, markdown)
                self.assertIn("停止原因：` " + reason + " `", markdown)
                for number in range(1, 6 if finalize else 4):
                    self.assertIn(f"### 自适应取证 {number}", markdown)
                    self.assertIn(f"Adaptive actual query {number}", markdown)
                for value in ("offline-two", "offline-r2", "tool_observation", "no_new_shown_evidence",
                              "new_returned_ids", "offline-not-shown", "new_shown_ids", "final_shown_ids"):
                    self.assertIn(value, markdown)
                self.assertNotIn("## 补查与停止", markdown)
                self.assertNotIn("### 补查查询", markdown)
                self.assertFalse(app.exception)

    def test_same_submission_token_is_consumed_once(self):
        with patch("uuid.uuid4", return_value="same-offline-token"):
            app = self.submit(self.app())
            self.submit(app, "agent", "Different controls same token")
        self.assertEqual(self.runtime.call_count, 1)
        records = app.session_state["d9_submission_records"]
        self.assertEqual(list(records), ["same-offline-token"])
        self.assertEqual(records["same-offline-token"]["status"], "completed")
        self.assertEqual(app.session_state["current_report"]["mode"], "agent")

    def test_explicit_resubmit_same_question_gets_new_token_and_run(self):
        app = self.app()
        initial_conversation = app.session_state["d9_conversation_id"]
        self.assertEqual(app.selectbox(key="conversation_picker").options, ["对话 1 · 新对话"])
        self.submit(app)
        picker = app.selectbox(key="conversation_picker")
        self.assertEqual(app.session_state["d9_conversation_id"], initial_conversation)
        self.assertEqual(picker.options, ["对话 1 · Offline question?"])
        # The browser receives formatted labels, so a changed title must also
        # update its selected wire value even when the conversation UUID stays.
        self.assertTrue(picker.proto.set_value)
        self.assertEqual(picker.proto.raw_value, "对话 1 · Offline question?")
        first = app.session_state["current_report"]["submission_id"]
        self.submit(app)
        second = app.session_state["current_report"]["submission_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.runtime.call_count, 2)
        self.assertEqual(len(app.session_state["d9_submission_records"]), 2)

        first_saved = deepcopy(app.session_state["current_report"])
        first_conversation = first_saved["conversation_id"]
        app.button(key="new_conversation").click().run()
        empty_conversation = app.session_state["d9_conversation_id"]
        picker = app.selectbox(key="conversation_picker")
        self.assertEqual(picker.options, ["对话 1 · Offline question?", "对话 2 · 新对话"])
        self.assertTrue(picker.proto.set_value)
        self.assertEqual(picker.proto.raw_value, "对话 2 · 新对话")
        self.evidence_text = "Original evidence belonging to the second conversation."
        self.submit(app)
        second_saved = deepcopy(app.session_state["current_report"])
        second_conversation = second_saved["conversation_id"]
        picker = app.selectbox(key="conversation_picker")
        self.assertEqual(second_conversation, empty_conversation)
        self.assertTrue(picker.proto.set_value)
        self.assertEqual(picker.proto.raw_value, "对话 2 · Offline question?")
        self.assertNotEqual(first_conversation, second_conversation)
        self.assertEqual(second_saved["conversation_history"], [])
        self.assertEqual(self.runtime.call_count, 3)

        labels = list(app.selectbox(key="conversation_picker").options)
        self.assertEqual(labels, ["对话 1 · Offline question?", "对话 2 · Offline question?"])
        self.assertEqual(len(set(labels)), len(labels))
        for conversation, saved, original, other_original in (
                (first_conversation, first_saved, EVIDENCE, self.evidence_text),
                (second_conversation, second_saved, self.evidence_text, EVIDENCE)):
            app.selectbox(key="conversation_picker").set_value(conversation).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["d9_conversation_id"], conversation)
            self.assertEqual(app.session_state["conversation_picker"], conversation)
            self.assertEqual(app.session_state["current_report"], saved)
            self.assertEqual(app.selectbox(key="conversation_picker").options, labels)
            citation = self.text(app.get_by_key("citation_" + saved["submission_id"] + "_1"))
            self.assertIn(original, citation)
            self.assertNotIn(other_original, citation)

        app.selectbox(key="conversation_picker").set_value(first_conversation).run()
        first_followup = "Explain the first conversation answer."
        self.submit(app, "agent", first_followup)
        followed = deepcopy(app.session_state["current_report"])
        self.assertEqual(followed["conversation_id"], first_conversation)
        self.assertEqual([row["user_question"] for row in followed["conversation_history"]],
                         ["Offline question?", "Offline question?"])
        self.assertEqual([row["turn"] for row in followed["conversation_history"]], [1, 2])
        before = self.runtime.call_count
        app.run()
        app.session_state["question_mode"] = "fixed_rag"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["d9_conversation_id"], first_conversation)
        self.assertEqual(app.session_state["conversation_picker"], first_conversation)
        self.assertEqual(app.session_state["current_report"], followed)
        self.assertEqual(app.selectbox(key="conversation_picker").options, labels)
        self.assertEqual(self.runtime.call_count, before)

        app.selectbox(key="conversation_picker").set_value(second_conversation).run()
        self.assertEqual(app.session_state["d9_conversation_id"], second_conversation)
        self.assertEqual(app.session_state["conversation_picker"], second_conversation)
        self.assertEqual(app.session_state["current_report"], second_saved)
        self.assertNotIn(first_followup, self.text(app))
        self.submit(app, query="Explain the second conversation answer.")
        followed_second = deepcopy(app.session_state["current_report"])
        self.assertEqual(followed_second["conversation_id"], second_conversation)
        self.assertEqual([row["user_question"] for row in followed_second["conversation_history"]],
                         ["Offline question?"])
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["d9_conversation_id"], second_conversation)
        self.assertEqual(app.session_state["conversation_picker"], second_conversation)
        self.assertEqual(app.selectbox(key="conversation_picker").options, labels)
        self.assertEqual(self.runtime.call_count, before + 1)
        records = app.session_state["d9_submission_records"]
        self.assertEqual(records[first_saved["submission_id"]]["report"], first_saved)
        self.assertEqual(records[second_saved["submission_id"]]["report"], second_saved)
        self.assertEqual(records[followed["submission_id"]]["conversation_history"],
                         followed["conversation_history"])
        self.assertEqual(records[followed_second["submission_id"]]["conversation_history"],
                         followed_second["conversation_history"])

    def test_inflight_blocks_another_execution(self):
        upload_bytes = b"offline uploaded PDF bytes"
        uploaded = SimpleNamespace(name="offline-upload.pdf", getvalue=lambda: upload_bytes)

        def upload_widget(*args, **kwargs):
            streamlit.session_state[kwargs["key"]] = uploaded
            return uploaded

        self.stack.enter_context(patch.object(streamlit, "file_uploader", side_effect=upload_widget))
        ready_rows = deepcopy(READY)
        self.stack.enter_context(patch.object(target, "list_ready_versions", side_effect=lambda **kwargs: deepcopy(ready_rows)))
        import_started, import_release = Event(), Event()
        imported_inputs = []
        new_pair = ("local-uploaded-paper", "local-uploaded-revision")

        def imported(pdf_bytes, filename, *, title=None, source_url="", project_root, on_progress=None):
            self.assertEqual(project_root, ROOT)
            imported_inputs.append({"pdf_bytes": pdf_bytes, "filename": filename, "title": title, "source_url": source_url})
            progress = {"status": "pending", "paper_id": new_pair[0], "parse_revision": new_pair[1],
                        "title": title, "stage": "embedding", "chunk_count": 3, "completed_count": 1,
                        "embedding_requests": 1}
            if on_progress:
                on_progress(progress)
            if len(imported_inputs) == 1:
                import_started.set()
                self.assertTrue(import_release.wait(timeout=20))
                return {**progress, "status": "failed", "error": "Offline embedding failure"}
            ready_rows.append({"paper_id": new_pair[0], "parse_revision": new_pair[1],
                               "title": title, "source_type": "local", "arxiv_version": "", "chunk_count": 3})
            return {**progress, "status": "ready", "stage": "ready", "completed_count": 3}

        importer = self.stack.enter_context(patch.object(import_runtime, "import_pdf", side_effect=imported))
        app = self.app()
        app.session_state["d9_submission_inflight"] = "occupied-token"
        self.submit(app)
        self.assertEqual(self.runtime.call_count, 0)
        self.assertEqual(app.session_state["d9_submission_inflight"], "occupied-token")

        started, release = Event(), Event()
        submitted = self.runtime.side_effect

        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=10))
            return submitted(*args, **kwargs)

        self.runtime.side_effect = blocked
        app = self.app()
        future = None
        question = "Question rendered before its answer"
        try:
            app.chat_input(key="question").set_value(question).run()
            self.assertFalse(app.exception)
            self.assertTrue(started.wait(timeout=2))
            future = app.session_state["d9_submission_future"]
            self.assertFalse(future.done())
            token = app.session_state["d9_submission_inflight"]
            conversation = app.session_state["d9_conversation_id"]
            self.assertEqual(self.runtime.call_count, 1)
            messages = app.get("chat_message")
            self.assertEqual(len(messages), 2)
            self.assertIn(question, self.text(next(item for item in messages if item.name == "user")))
            self.assertIn("正在阅读论文并整理回答", self.text(next(item for item in messages if item.name == "assistant")))
            self.assertTrue(app.chat_input(key="question").disabled)
            self.assertTrue(app.button(key="start_paper_import").disabled)

            app.run()
            app.session_state["question_mode"] = "fixed_rag"
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(future.done())
            self.assertEqual(self.runtime.call_count, 1)
            self.assertEqual(app.session_state["d9_submission_records"][token]["mode"], "agent")
            app.button(key="new_conversation").click().run()
            self.assertFalse(app.exception)
            self.assertNotEqual(app.session_state["d9_conversation_id"], conversation)
            self.assertFalse(app.get("chat_message"))
            self.assertNotIn("current_report", app.session_state)
            self.assertFalse(future.done())
            self.assertEqual(self.runtime.call_count, 1)
            app.selectbox(key="conversation_picker").set_value(conversation).run()
            self.assertIn(question, self.text(app))
            self.assertIn("正在阅读论文并整理回答", self.text(app))
            app.button(key="new_conversation").click().run()
        finally:
            release.set()
            if future is None and "d9_submission_future" in app.session_state:
                future = app.session_state["d9_submission_future"]
            if future is not None:
                future.result(timeout=2)

        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.get("chat_message"))
        self.assertNotIn("current_report", app.session_state)
        self.assertIsNone(app.session_state["d9_submission_inflight"])
        self.assertEqual(app.session_state["d9_submission_records"][token]["status"], "completed")
        app.selectbox(key="conversation_picker").set_value(conversation).run()
        self.assertFalse(app.exception)
        self.assertIn(question, self.text(app))
        self.assertIn(CLAIM, self.text(app))
        self.assertNotIn("正在阅读论文并整理回答", self.text(app))
        self.assertEqual(app.session_state["current_report"]["query"], question)
        self.assertEqual(app.session_state["current_report"]["mode"], "agent")
        self.assertEqual(self.runtime.call_count, 1)

        old_report = deepcopy(app.session_state["current_report"])
        old_conversation = app.session_state["d9_conversation_id"]
        app.text_input(key="paper_upload_title").set_value("Uploaded offline paper")
        app.text_input(key="paper_upload_source").set_value("https://example.invalid/upload-source")
        import_future = None
        try:
            app.button(key="start_paper_import").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(import_started.wait(timeout=2))
            import_future = app.session_state["paper_import_future"]
            self.assertFalse(import_future.done())
            frozen_input = deepcopy(app.session_state["paper_import_input"])
            app.run()
            self.assertEqual(app.session_state["paper_import_progress"]["stage"], "embedding")
            self.assertTrue(app.chat_input(key="question").disabled)
            self.assertTrue(app.button(key="start_paper_import").disabled)
            self.assertEqual(app.session_state["current_report"], old_report)
            old_citation = self.text(app.get_by_key("citation_" + old_report["submission_id"] + "_1"))
            self.assertIn(EVIDENCE, old_citation)
            app.run()
            app.session_state["question_mode"] = "fixed_rag"
            app.run()
            app.button(key="new_conversation").click().run()
            self.assertFalse(app.get("chat_message"))
            app.selectbox(key="conversation_picker").set_value(old_conversation).run()
            self.assertEqual(app.session_state["current_report"], old_report)
            self.assertEqual(importer.call_count, 1)
            self.assertEqual(self.runtime.call_count, 1)
            self.assertFalse(import_future.done())
        finally:
            import_release.set()
            if import_future is None and "paper_import_future" in app.session_state:
                import_future = app.session_state["paper_import_future"]
            if import_future is not None:
                import_future.result(timeout=2)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["paper_import_result"]["status"], "failed")
        self.assertIn("Offline embedding failure", self.text(app))
        self.assertEqual(app.session_state["paper_import_input"], frozen_input)

        # Retry uses the failed submission's bytes and metadata, even after edits.
        uploaded = SimpleNamespace(name="replacement.pdf", getvalue=lambda: b"replacement PDF")
        app.text_input(key="paper_upload_title").set_value("Changed title")
        app.text_input(key="paper_upload_source").set_value("https://example.invalid/changed-source").run()
        app.button(key="retry_paper_import").click().run()
        if "paper_import_future" in app.session_state and app.session_state["paper_import_future"] is not None:
            app.session_state["paper_import_future"].result(timeout=2)
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(importer.call_count, 2)
        self.assertEqual(imported_inputs, [frozen_input, frozen_input])
        self.assertEqual(app.session_state["paper_import_result"]["status"], "ready")
        self.assertIn("Uploaded offline paper", app.multiselect(key="selected_versions").options)
        self.assertEqual(app.session_state["selected_versions"], [PAIR])
        self.assertEqual(app.session_state["d9_conversation_id"], old_conversation)
        self.assertEqual(app.session_state["current_report"], old_report)

        new_original = "Original text from the uploaded paper."
        def uploaded_answer(query, selected_versions, **kwargs):
            self.assertEqual(selected_versions, [new_pair])
            self.assertTrue(kwargs["library_mode"])
            saved = report(query=query, mode=kwargs["mode"], submission_id=kwargs["submission_id"], evidence_text=new_original)
            saved.update(conversation_id=kwargs["conversation_id"], conversation_history=kwargs["conversation_history"],
                         selected_versions=[{"paper_id": new_pair[0], "parse_revision": new_pair[1]}])
            for source in saved["answer"]["evidence_sources"]:
                source.update(paper_id=new_pair[0], parse_revision=new_pair[1], title="Uploaded offline paper", arxiv_version="")
            return saved

        self.runtime.side_effect = uploaded_answer
        app.multiselect(key="selected_versions").set_value([new_pair]).run()
        app.chat_input(key="question").set_value("What does the uploaded paper report?").run()
        if "d9_submission_future" in app.session_state:
            future = app.session_state["d9_submission_future"]
            if future is not None:
                future.result(timeout=2)
                app.run()
        self.assertFalse(app.exception)
        new_report = app.session_state["current_report"]
        new_citation = self.text(app.get_by_key("citation_" + new_report["submission_id"] + "_1"))
        self.assertIn(new_original, new_citation)
        self.assertNotIn(EVIDENCE, new_citation)
        self.assertEqual(self.runtime.call_count, 2)
        app.selectbox(key="conversation_picker").set_value(old_conversation).run()
        self.assertEqual(app.session_state["current_report"], old_report)
        self.assertIn(EVIDENCE, self.text(app.get_by_key("citation_" + old_report["submission_id"] + "_1")))
        self.assertEqual(importer.call_count, 2)

    def test_runtime_exception_is_saved_safe_and_same_token_never_replays(self):
        self.runtime.side_effect = RuntimeError(SECRET)
        with patch("uuid.uuid4", return_value="failed-offline-token"):
            app = self.submit(self.app(), "agent")
            saved = deepcopy(app.session_state["d9_submission_records"]["failed-offline-token"])
            self.assertEqual(saved["status"], "runtime_error")
            self.assertEqual(saved["error_code"], "report_unavailable")
            self.assertFalse(saved["usage_known"])
            self.assertEqual(saved["mode"], "agent")
            self.assertIsNone(app.session_state["d9_submission_inflight"])
            self.assertNotIn("current_report", app.session_state)
            self.assertNotIn(SECRET, self.text(app))
            app.run()
            self.submit(app)
            app.session_state["question_mode"] = "fixed_rag"
            app.run()
            self.assertEqual(self.runtime.call_count, 1)
            self.assertEqual(app.session_state["d9_submission_records"]["failed-offline-token"], saved)
        self.runtime.side_effect = lambda query, pairs, **kw: report(mode=kw["mode"], query=query, submission_id=kw["submission_id"])
        self.submit(app)
        self.assertEqual(self.runtime.call_count, 2)
        self.assertEqual(len(app.session_state["d9_submission_records"]), 2)

    def test_invalid_inputs_do_not_run_or_create_runtime_report(self):
        app = self.app()
        # Empty chat input has no browser submit event; a redraw stays idle.
        app.run()
        self.assertFalse(app.exception)
        app.multiselect(key="selected_versions").set_value([]).run()
        app.chat_input(key="question").set_value("Offline question?").run()
        self.assertFalse(app.exception)
        self.assertEqual(self.runtime.call_count, 0)
        self.assertNotIn("current_report", app.session_state)
        self.assertEqual(len(app.get("download_button")), 0)

    def test_runtime_input_rejection_has_no_fake_report_or_unknown_usage(self):
        self.runtime.side_effect = target.InvalidQuestion(SECRET)
        app = self.submit(self.app())
        app.run()
        self.assertEqual(self.runtime.call_count, 1)
        text = self.text(app)
        self.assertIn("输入", text)
        self.assertIn("无效", text)
        self.assertNotIn("实际用量未知", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("current_report", app.session_state)

    def test_downloads_and_download_failure_only_use_saved_report(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                app = self.submit(self.app(), mode)
                first = deepcopy(app.session_state["current_report"])
                app = self.submit(app, mode, "Second download question " + mode)
                before = self.runtime.call_count
                frozen = deepcopy(app.session_state["current_report"])
                self.assertEqual(len(app.get("download_button")), 4)
                download_keys = [button.key for button in app.get("download_button")]
                self.assertEqual(len(set(download_keys)), 4)
                for key in download_keys:
                    app.get_by_key(key).click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(self.runtime.call_count, before)
                    self.assertEqual(app.session_state["current_report"], frozen)
                    self.assertEqual([call.args[0] for call in self.download.call_args_list[-2:]], [first, frozen])
                self.assertEqual(self.download.call_args.args[0], frozen)
                self.download.side_effect = RuntimeError(SECRET)
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.get("download_button")), 2)
                for key in [button.key for button in app.get("download_button")]:
                    app.get_by_key(key).click().run()
                    self.assertFalse(app.exception)
                self.assertEqual(self.runtime.call_count, before)
                self.assertEqual(app.session_state["current_report"], frozen)
                self.assertNotIn(SECRET, self.text(app))
                self.download.side_effect = lambda saved, **kw: (json.dumps(saved).encode("utf-8"), b"Offline Markdown")

    def test_pre_export_answer_is_diagnostic_not_published(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                failed = report("tool_error", mode)
                failed["pre_export_result"] = report("answered", mode)["result"]
                failed["result"]["answer"] = report("answered", mode)["answer"]
                failed["result"]["status"] = "answered"
                failed["error"] = {"code": "export_error"}
                self.runtime.side_effect = lambda *args, **kw: deepcopy(failed)
                app = self.submit(self.app(), mode)
                self.assertFalse(app.success)
                self.assertNotIn(CLAIM, self.text(app))
                self.assertIn("运行记录保存未完成", self.text(app))

    def test_report_saved_before_render_exception_and_rerun_does_not_run(self):
        app = self.app()
        with patch("streamlit.json", side_effect=RuntimeError("offline-render-failure")):
            app.session_state["question_mode"] = "fixed_rag"
            app.chat_input(key="question").set_value("Offline question?").run()
        self.assertTrue(app.exception)
        self.assertEqual(self.runtime.call_count, 1)
        saved = deepcopy(app.session_state["current_report"])
        self.assertEqual(app.session_state["d9_submission_records"][saved["submission_id"]]["status"], "completed")
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.runtime.call_count, 1)
        self.assertEqual(app.session_state["current_report"], saved)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
