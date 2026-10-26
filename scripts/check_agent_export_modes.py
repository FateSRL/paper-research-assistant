"""D8 E: isolated replay of D record checks and fixed-mode export compatibility.

Run only these classes, never the D unified runner. All fixtures use temporary
PDFs, synthetic stores/searchers and real SDK calls through MockTransport.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from paper_assistant import agent_export as export
from paper_assistant.agent_export import save_agent_run
from paper_assistant.rag import answer_question
from scripts import check_agent as fixture_module
from scripts.agent_boundary_records import RECORD_BOUNDARY_CASES
from scripts.check_agent import AgentFixture, QUESTION, SequencedSearcher, answer_action, response


ROOT = Path(__file__).resolve().parents[1]


class FixedModeExportChecks(AgentFixture):
    def fixed_result(self):
        client, requests = self.client(response(answer_action()["answer"]))
        with client:
            result = answer_question(QUESTION, [("p1", "r1")], SequencedSearcher([self.row]), self.store,
                                     client, project_root=self.root)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(requests), 1)
        return result

    def agent_report(self, identifier="same-run"):
        client, _ = self.client(response(answer_action()))
        with client:
            result = self.run_agent(client)
        return {"task": "D8", "mode": "agent", "run_id": identifier, "result": result}

    def test_same_run_id_keeps_fixed_and_agent_history_latest_and_d5_separate(self):
        d5 = self.root / "artifacts/d5/answer_result.json"
        d5.parent.mkdir(parents=True)
        d5.write_bytes(b"previous-D5-result")
        fixed = {"task": "D8", "mode": "fixed_rag", "run_id": "same-run", "result": self.fixed_result()}
        before = deepcopy(fixed)
        fixed_saved = save_agent_run(fixed, project_root=self.root)
        fixed_paths = [fixed_saved["history_report"], fixed_saved["history_markdown"],
                       "artifacts/d8/fixed_rag_result.json", "artifacts/d8/fixed_rag_result.md"]
        fixed_bytes = {name: (self.root / name).read_bytes() for name in fixed_paths}
        agent_saved = save_agent_run(self.agent_report(), project_root=self.root)
        self.assertNotEqual(fixed_saved["history_report"], agent_saved["history_report"])
        self.assertTrue(fixed_saved["history_report"].startswith("archive/run_logs/d8/fixed_rag_"))
        self.assertEqual({name: (self.root / name).read_bytes() for name in fixed_paths}, fixed_bytes)
        agent_latest = (self.root / "artifacts/d8/agent_result.json").read_bytes()
        duplicate = save_agent_run(fixed, project_root=self.root)
        self.assertEqual(duplicate["error"]["code"], "history_exists")
        self.assertEqual({name: (self.root / name).read_bytes() for name in fixed_paths}, fixed_bytes)
        self.assertEqual((self.root / "artifacts/d8/agent_result.json").read_bytes(), agent_latest)
        self.assertEqual(d5.read_bytes(), b"previous-D5-result")
        self.assertEqual(fixed, before)

    def test_fixed_export_failure_keeps_cost_and_recovers_only_fixed_mode(self):
        agent_saved = save_agent_run(self.agent_report("already-agent"), project_root=self.root)
        agent_paths = [agent_saved["history_report"], agent_saved["history_markdown"],
                       "artifacts/d8/agent_result.json", "artifacts/d8/agent_result.md"]
        agent_bytes = {name: (self.root / name).read_bytes() for name in agent_paths}
        report = {"task": "D8", "mode": "fixed_rag", "run_id": "fixed-failure", "result": self.fixed_result()}
        with patch.object(export, "_exclusive_text", side_effect=OSError("private-fault-do-not-log")):
            failed = save_agent_run(report, project_root=self.root)
        self.assertEqual(failed["status"], "tool_error")
        self.assertIsNone(failed["answer"])
        self.assertIsNone(failed["result"]["answer"])
        self.assertEqual(failed["pre_export_result"], report["result"])
        self.assertEqual(failed["result"]["statistics"], report["result"]["statistics"])
        self.assertTrue(failed["export"]["recovery_saved"])
        self.assertTrue(failed["export"]["latest_recovery_saved"])
        self.assertTrue(failed["export"]["recovery_history_report"].startswith("archive/run_logs/d8/fixed_rag_"))
        self.assertEqual({name: (self.root / name).read_bytes() for name in agent_paths}, agent_bytes)
        latest = json.loads((self.root / "artifacts/d8/fixed_rag_result.json").read_text(encoding="utf-8"))
        self.assertEqual(latest, failed)
        self.assertNotIn("private-fault-do-not-log", json.dumps(failed))


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
