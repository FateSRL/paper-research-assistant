"""D8 D: actual immutable export, recovery and caller-owned SDK lifecycle."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from paper_assistant import agent_export as export
from paper_assistant.agent_export import AgentExportError, reserve_agent_batch, save_agent_run
from scripts.check_agent import (
    AgentFixture, SequencedSearcher, answer_action, insufficient_action, response, retry_action,
)
from scripts.check_llm import http_error


class RecordBoundaryChecks(AgentFixture):
    def report(self, result=None, identifier="offline-run-001"):
        if result is None:
            client, _ = self.client(response(answer_action()))
            with client:
                result = self.run_agent(client)
        return {"task": "D8", "mode": "agent", "run_id": identifier, "result": deepcopy(result)}

    def load(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def test_five_actual_terminal_results_save_complete_json_markdown_and_latest(self):
        for index, (status, outcomes) in enumerate((
                ("answered", [response(answer_action())]),
                ("insufficient_evidence", [response(insufficient_action())]),
                ("tool_error", [http_error(401)]),
                ("invalid_output", [response("bad"), response("still bad")]),
                ("budget_exceeded", [http_error(503), response("bad"), response(retry_action())]))):
            with self.subTest(status=status):
                client, requests = self.client(*outcomes)
                with client:
                    result = self.run_agent(client)
                    report = self.report(result, "five-" + str(index))
                    saved = save_agent_run(report, project_root=self.root)
                self.assertTrue(client._closed)
                self.assertEqual(saved["status"], status)
                self.assertEqual(saved["export"]["status"], "completed")
                self.assertEqual(self.load(saved["history_report"])["result"], result)
                self.assertEqual(self.load("artifacts/d8/agent_result.json"), saved)
                self.assertEqual(saved["result"]["statistics"]["chat"]["http_request_attempts"], len(requests))
                self.assertTrue((self.root / saved["history_markdown"]).exists())
                self.assertIn(status, (self.root / "artifacts/d8/agent_result.md").read_text(encoding="utf-8"))
                if status not in ("answered", "insufficient_evidence"):
                    self.assertIsNone(saved["answer"])
                    self.assertIsNone(saved["result"]["answer"])

    def test_duplicate_run_never_changes_history_or_latest_but_preserves_recovery(self):
        report = self.report()
        first = save_agent_run(report, project_root=self.root)
        paths = [first["history_report"], first["history_markdown"],
                 "artifacts/d8/agent_result.json", "artifacts/d8/agent_result.md"]
        before = {p: (self.root / p).read_bytes() for p in paths}
        second = save_agent_run(report, project_root=self.root)
        self.assertEqual(second["error"]["code"], "history_exists")
        self.assertEqual(second["status"], "tool_error")
        self.assertIsNone(second["answer"])
        self.assertEqual({p: (self.root / p).read_bytes() for p in paths}, before)
        self.assertTrue(second["export"]["recovery_saved"])
        self.assertEqual(second["pre_export_result"], report["result"])

    def test_exclusive_publication_race_does_not_replace_other_history_or_latest(self):
        old = save_agent_run(self.report(identifier="old"), project_root=self.root)
        latest = (self.root / "artifacts/d8/agent_result.json").read_bytes()
        actual = export.exclusive_json
        foreign = {"owner": "another writer"}

        def race(path, value):
            if path.name == "agent_raced.json":
                actual(path, foreign)
            actual(path, value)

        with patch.object(export, "exclusive_json", side_effect=race):
            saved = save_agent_run(self.report(identifier="raced"), project_root=self.root)
        self.assertEqual(saved["error"]["code"], "history_exists")
        self.assertEqual(self.load("archive/run_logs/d8/agent_raced.json"), foreign)
        self.assertEqual((self.root / "artifacts/d8/agent_result.json").read_bytes(), latest)
        self.assertTrue((self.root / old["history_report"]).exists())

    def test_duplicate_batch_refused_before_any_client_call_and_original_manifest_unchanged(self):
        manifest = {"frozen": "synthetic", "cases": ["offline-case"]}
        path = reserve_agent_batch(self.root, "offline-batch", manifest)
        old = (path / "manifest.json").read_bytes()
        client, requests = self.client()
        with client:
            with self.assertRaises(AgentExportError) as caught:
                reserve_agent_batch(self.root, "offline-batch", {"changed": True})
        self.assertEqual(caught.exception.code, "batch_exists")
        self.assertEqual(requests, [])
        self.assertEqual((path / "manifest.json").read_bytes(), old)

    def test_batch_manifest_failure_keeps_reserved_directory_and_refuses_reuse(self):
        with patch.object(export, "exclusive_json", side_effect=OSError("private disk fault")):
            with self.assertRaises(OSError):
                reserve_agent_batch(self.root, "partial-batch", {"frozen": "synthetic"})
        self.assertTrue((self.root / "artifacts/d8/comparison/partial-batch").is_dir())
        with self.assertRaises(AgentExportError) as caught:
            reserve_agent_batch(self.root, "partial-batch", {"frozen": "new"})
        self.assertEqual(caught.exception.code, "batch_exists")

    def test_unrecordable_batch_manifest_is_rejected_before_reservation(self):
        with self.assertRaises(ValueError):
            reserve_agent_batch(self.root, "bad-manifest", {"invalid": float("nan")})
        self.assertFalse((self.root / "artifacts/d8/comparison/bad-manifest").exists())

    def test_unsafe_or_windows_reserved_run_and_batch_ids_cannot_choose_paths(self):
        report = self.report()
        for identifier in ("", "../outside", "C:\\outside", "/outside", "folder/id", "CON", "nul.txt", "a.", "a" * 97):
            with self.subTest(identifier=identifier):
                with self.assertRaises(AgentExportError):
                    save_agent_run({**report, "run_id": identifier}, project_root=self.root)
                with self.assertRaises(AgentExportError):
                    reserve_agent_batch(self.root, identifier, {})

    def test_escaping_resolved_path_is_rejected(self):
        with self.assertRaises(AgentExportError) as caught:
            export._path(self.root.resolve(), "../outside.json")
        self.assertEqual(caught.exception.code, "record_path_outside_project")

    def test_export_input_is_not_mutated_and_spoofed_outer_terminal_is_replaced(self):
        report = self.report()
        report.update(status="budget_exceeded", history_report="artifacts/d5/answer_result.json")
        original = deepcopy(report)
        saved = save_agent_run(report, project_root=self.root)
        self.assertEqual(report, original)
        self.assertEqual(saved["status"], "answered")
        self.assertTrue(saved["history_report"].startswith("archive/run_logs/d8/"))
        self.assertFalse((self.root / "artifacts/d5/answer_result.json").exists())

    def test_failed_terminal_with_spurious_answer_is_cleared_and_kept_only_as_diagnostic(self):
        report = self.report()
        report["result"].update(status="tool_error", error={"code": "synthetic", "message": "safe"})
        saved = save_agent_run(report, project_root=self.root)
        self.assertEqual(saved["export"]["failed_step"], "record_validation")
        self.assertIsNone(saved["answer"])
        self.assertIsNone(saved["result"]["answer"])
        self.assertEqual(saved["pre_export_result"], report["result"])
        self.assertNotIn(report["result"]["answer"]["claims"][0]["claim"],
                         (self.root / "artifacts/d8/agent_result.md").read_text(encoding="utf-8"))

    def test_every_export_stage_fault_clears_publishable_answer_and_keeps_cost_recovery(self):
        for stage in ("history_json", "render", "history_markdown", "latest_markdown", "latest_json"):
            with self.subTest(stage=stage):
                report = self.report(identifier="fault-" + stage)
                original = deepcopy(report)
                function = {"history_json": "exclusive_json", "render": "render_agent_run",
                            "history_markdown": "_exclusive_text", "latest_markdown": "atomic_text",
                            "latest_json": "atomic_text"}[stage]
                actual = getattr(export, function)
                fired = False

                def inject(*args, **kwargs):
                    nonlocal fired
                    relevant = stage != "latest_json" or Path(args[0]).name == "agent_result.json"
                    if not fired and relevant:
                        fired = True
                        raise OSError("private-export-error-do-not-log")
                    return actual(*args, **kwargs)

                with patch.object(export, function, side_effect=inject):
                    saved = save_agent_run(report, project_root=self.root)
                self.assertEqual(saved["export"]["failed_step"], stage)
                self.assertEqual(saved["status"], "tool_error")
                self.assertIsNone(saved["answer"])
                self.assertIsNone(saved["result"]["answer"])
                self.assertEqual(saved["result"]["statistics"], original["result"]["statistics"])
                self.assertEqual(saved["pre_export_result"], original["result"])
                self.assertEqual(report, original)
                self.assertTrue(saved["export"]["recovery_saved"])
                self.assertTrue(saved["export"]["latest_recovery_saved"])
                self.assertEqual(self.load(saved["export"]["recovery_history_report"])["result"]["status"], "tool_error")
                self.assertEqual(self.load("artifacts/d8/agent_result.json"), saved)
                self.assertNotIn("private-export-error-do-not-log", json.dumps(saved))

    def test_unwritable_disk_retains_full_failure_in_memory_without_claiming_files_saved(self):
        report = self.report()
        with patch.object(export, "exclusive_json", side_effect=OSError("disk read only")), \
                patch.object(export, "atomic_text", side_effect=OSError("disk read only")):
            saved = save_agent_run(report, project_root=self.root)
        self.assertEqual(saved["status"], "tool_error")
        self.assertIsNone(saved["answer"])
        self.assertEqual(saved["pre_export_result"], report["result"])
        self.assertEqual(saved["result"]["statistics"], report["result"]["statistics"])
        self.assertFalse(saved["export"]["recovery_saved"])
        self.assertFalse(saved["export"]["latest_recovery_saved"])

    def test_markdown_fences_injected_paper_and_model_text_without_claiming_accuracy(self):
        text = "```\n# malicious outside fence\n``` and original evidence"
        row = self.add_chunk("fenced", text=text)
        action = answer_action(row["chunk_id"])
        action["answer"]["claims"][0]["claim"] = text
        client, _ = self.client(response(action))
        with client:
            result = self.run_agent(client, searcher=SequencedSearcher([row]))
            saved = save_agent_run(self.report(result), project_root=self.root)
        md = (self.root / saved["history_markdown"]).read_text(encoding="utf-8")
        self.assertIn("````text\n" + text + "\n````", md)
        self.assertIn("不代表答案语义准确", md)

    def test_actual_client_closes_after_export_failure_with_calls_still_preserved(self):
        client, requests = self.client(response(answer_action()))
        with client:
            result = self.run_agent(client)
            with patch.object(export, "_exclusive_text", side_effect=OSError("disk")):
                saved = save_agent_run(self.report(result), project_root=self.root)
        self.assertTrue(client._closed)
        self.assertTrue(client.client.is_closed())
        self.assertEqual(len(requests), 1)
        self.assertEqual(saved["result"]["statistics"]["chat"]["http_request_attempts"], 1)


RECORD_BOUNDARY_CASES = (RecordBoundaryChecks,)
