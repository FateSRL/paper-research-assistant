"""质量过滤边界与真实证据保留检查；不调用模型或网络。"""

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from paper_assistant.quality import (
    FILTER_REVISION, QualityError, count_bad_controls, filter_paper_pages,
    filter_text_blocks, iter_indexable_segments,
)

ROOT = Path(__file__).resolve().parents[1]


def line(text: str, bbox=(0, 0, 100, 10), font="NimbusRomNo9L-Regu") -> dict:
    return {"bbox": list(bbox), "spans": [{"text": text, "font": font}]}


class QualityBoundaryChecks(unittest.TestCase):
    def test_damaged_line_is_removed_without_joining_a_fake_sentence(self):
        blocks = [{
            "type": 0,
            "lines": [
                line("The agent", (0, 0, 100, 10)),
                line("does not\x03update weights", (0, 11, 100, 21)),
                line("updates its memory.", (0, 22, 100, 32)),
            ],
        }]
        segments, excluded = filter_text_blocks(blocks, {}, [], "paper", 1)
        self.assertEqual(len(segments), 2)
        self.assertEqual(len(excluded), 1)
        self.assertNotIn("does", "\n".join(row["text"] for row in segments))
        self.assertEqual(segments[0]["source_line_indices"], [0])
        self.assertEqual(segments[1]["source_line_indices"], [2])

    def test_ascii_garbage_is_blocked_by_the_unmapped_font(self):
        blocks = [{"type": 0, "lines": [line("$FW", font="BrokenFont")]}]
        segments, excluded = filter_text_blocks(
            blocks, {"brokenfont": {}}, [], "paper", 1
        )
        self.assertEqual(segments, [])
        self.assertIn("identity_h_font_without_unicode_mapping", excluded[0]["reasons"])

    def test_formula_region_does_not_remove_adjacent_prose(self):
        blocks = [{
            "type": 0,
            "lines": [
                line("same retrieved document", (0, 0, 100, 10)),
                line("X Y", (20, 20, 80, 30)),
                line("different latent document", (0, 40, 100, 50)),
            ],
        }]
        rules = [{"region_id": "formula", "bbox": [0, 15, 100, 35], "reason": "math"}]
        segments, excluded = filter_text_blocks(blocks, {}, rules, "paper", 3)
        self.assertEqual([row["text"] for row in segments], [
            "same retrieved document", "different latent document"
        ])
        self.assertEqual(len(excluded), 1)

    def test_inline_variable_does_not_trigger_math_only_rejection(self):
        block = {"type": 0, "lines": [{
            "bbox": [0, 0, 100, 10],
            "spans": [
                {"text": "The input is ", "font": "NimbusRomNo9L-Regu"},
                {"text": "x", "font": "CMMI10"},
            ],
        }]}
        segments, excluded = filter_text_blocks([block], {}, [], "paper", 1)
        self.assertEqual(segments[0]["text"], "The input is x")
        self.assertEqual(excluded, [])

    def test_ordinary_computer_modern_roman_sentence_is_kept(self):
        sentence = "Reflexion does not update model weights."
        blocks = [{"type": 0, "lines": [line(sentence, font="CMR10")]}]
        segments, excluded = filter_text_blocks(blocks, {}, [], "paper", 1)
        self.assertEqual(segments[0]["text"], sentence)
        self.assertEqual(excluded, [])

    def test_raw_pages_cannot_enter_the_filtered_segment_iterator(self):
        with self.assertRaises(QualityError):
            list(iter_indexable_segments([{
                "paper_id": "paper", "pdf_page": 1, "text": "raw"
            }]))

    def test_cli_cannot_overwrite_raw_pages_even_with_another_input_directory(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "scripts.filter_pdf_text",
             "--input-dir", "data/some-copy", "--output-dir", "data/parsed"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("不能覆盖原始解析目录", result.stderr)

    def test_segment_source_mismatch_is_rejected(self):
        page = {
            "paper_id": "paper", "pdf_sha256": "hash", "pdf_page": 1,
            "filter_revision": FILTER_REVISION, "quality_filtered": True,
            "indexable": True, "segments": [{
                "paper_id": "other", "pdf_sha256": "hash", "pdf_page": 1,
                "filter_revision": FILTER_REVISION, "indexable": True, "text": "valid prose",
            }],
        }
        with self.assertRaises(QualityError):
            list(iter_indexable_segments([page]))


class ActualCorpusChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "eval/corpus.json").read_text(encoding="utf-8-sig"))
        cls.rules = json.loads((ROOT / "eval/quality_rules.json").read_text(encoding="utf-8"))
        cls.filtered = {}
        for paper in cls.corpus:
            path = ROOT / "data/filtered" / f"{paper['paper_id']}.jsonl"
            cls.filtered[paper["paper_id"]] = [
                json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()
            ]

    def test_all_71_pages_keep_sources_and_have_no_bad_controls(self):
        self.assertEqual(sum(len(rows) for rows in self.filtered.values()), 71)
        for paper in self.corpus:
            actual_hash = hashlib.sha256((ROOT / paper["local_path"]).read_bytes()).hexdigest()
            rows = self.filtered[paper["paper_id"]]
            self.assertEqual([row["pdf_page"] for row in rows], list(range(1, paper["page_count"] + 1)))
            for row in rows:
                self.assertEqual(row["pdf_sha256"], actual_hash)
                self.assertEqual(row["paper_id"], paper["paper_id"])
                self.assertEqual(count_bad_controls(row["text"]), 0)
            self.assertTrue(list(iter_indexable_segments(rows)))

    def test_all_seven_expected_quotes_remain_inside_individual_segments(self):
        cases = [
            json.loads(line)
            for line in (ROOT / "eval/dev.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checked = 0
        for case in cases:
            for evidence in case.get("expected_evidence", []):
                row = self.filtered[evidence["paper_id"]][evidence["pdf_page"] - 1]
                quote = " ".join(evidence["quote"].split())
                self.assertTrue(
                    any(quote in " ".join(segment["text"].split()) for segment in row["segments"]),
                    f"{case['case_id']} evidence lost or split across excluded content",
                )
                checked += 1
        self.assertEqual(checked, 7)

    def test_figure_exclusion_keeps_caption_and_prose(self):
        row = self.filtered["arxiv_2210.03629v3"][1]
        self.assertNotIn("$FW", row["text"])
        self.assertNotIn("7KRXJKW", row["text"])
        self.assertIn("Figure 1:", row["text"])
        self.assertIn("In this work, we present ReAct", row["text"])
        self.assertTrue(row["excluded_lines"])

    def test_math_exclusion_keeps_the_method_description(self):
        row = self.filtered["arxiv_2005.11401v4"][2]
        self.assertIn("RAG-Sequence Model", row["text"])
        self.assertIn("RAG-Token Model", row["text"])
        self.assertTrue(any(
            any("rag_sequence_display_equation" in reason for reason in entry["reasons"])
            for entry in row["excluded_lines"]
        ))

    def test_stale_region_hash_is_rejected(self):
        paper = self.corpus[0]
        raw = [
            json.loads(line)
            for line in (ROOT / "data/parsed" / f"{paper['paper_id']}.jsonl")
                .read_text(encoding="utf-8").splitlines()
        ]
        rules = copy.deepcopy(self.rules)
        rules["region_rules"][0]["pdf_sha256"] = "0" * 64
        with self.assertRaises(QualityError):
            filter_paper_pages(paper, raw, ROOT, rules)

    def test_unsupported_automatic_rule_change_is_rejected(self):
        paper = self.corpus[0]
        raw = [
            json.loads(line)
            for line in (ROOT / "data/parsed" / f"{paper['paper_id']}.jsonl")
                .read_text(encoding="utf-8").splitlines()
        ]
        rules = copy.deepcopy(self.rules)
        rules["automatic_rules"]["reject_line_with_non_layout_c0"] = False
        with self.assertRaises(QualityError):
            filter_paper_pages(paper, raw, ROOT, rules)

    def test_tampered_raw_source_is_rejected(self):
        paper = self.corpus[0]
        raw = [
            json.loads(line)
            for line in (ROOT / "data/parsed" / f"{paper['paper_id']}.jsonl")
                .read_text(encoding="utf-8").splitlines()
        ]
        raw[0]["text"] = "replaced content"
        with self.assertRaises(QualityError):
            filter_paper_pages(paper, raw, ROOT, self.rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)

