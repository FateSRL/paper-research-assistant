"""Two offline QASPER integration checks; no PDF imports or model requests."""

from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from paper_assistant import d9_runtime, import_runtime, qasper_evaluation as metrics


def annotation(*, answer="GOLD_ONLY_REFERENCE", evidence=(), spans=(), yes_no=None, unanswerable=False):
    return {"worker_id": "offline-reviewer", "answer": {
        "unanswerable": unanswerable, "extractive_spans": list(spans),
        "free_form_answer": answer, "yes_no": yes_no, "evidence": list(evidence),
        "highlighted_evidence": []}}


def official_fixture():
    first = "GOLD_ONLY_EVIDENCE explains the first component with a complete textual paragraph."
    second = "GOLD_ONLY_SECOND describes a different component with another complete paragraph."
    return {
        "offline-paper-one": {"title": "First offline paper", "abstract": first,
            "full_text": [{"section_name": "Method", "paragraphs": [first, second]}],
            "qas": [
                {"question_id": "q-a", "question": "What does the first component do?", "answers": [
                    annotation(spans=["GOLD_ONLY_SPAN_ONE", "GOLD_ONLY_SPAN_TWO"], evidence=[first]),
                    annotation(answer="GOLD_ONLY_ALTERNATIVE", evidence=[second])]},
                {"question_id": "q-b", "question": "Does the first component stop?", "answers": [
                    annotation(answer="", yes_no=False, evidence=[first])]},
                {"question_id": "q-c", "question": "Which unavailable number is reported?", "answers": [
                    annotation(answer="", unanswerable=True)]},
                {"question_id": "q-float", "question": "Which diagram contains the component?", "answers": [
                    annotation(evidence=[first]), annotation(evidence=["FLOAT SELECTED: Figure 1"])]}]},
        "offline-paper-two": {"title": "Second offline paper", "abstract": second,
            "full_text": [{"section_name": "Results", "paragraphs": [second]}],
            "qas": [{"question_id": "q-d", "question": "What does the second component report?",
                     "answers": [annotation(evidence=[second])]}]},
    }


def chunk(identifier, text, *, start=0, segment="segment", page=2):
    return {"chunk_id": identifier, "text": text, "segment_id": segment,
            "char_start": start, "char_end": start + len(text), "pdf_page": page,
            "source_block_index": 0}


def published(answer="Amber", citations=(), *, status="answered"):
    content = ({"status": "answered", "claims": [{"claim": answer, "citation_ids": list(citations)}]}
               if status == "answered" else None)
    return {"status": status, "answer": content,
            "error": {"code": "offline_failure"} if status == "tool_error" else None,
            "result": {"status": status, "answer": deepcopy(content), "search_rounds": [],
                       "context": {"shown_evidence": []}, "statistics": {}}}


class QasperChecks(unittest.TestCase):
    def test_prepare_and_run_keep_annotations_out_of_runtime(self):
        from scripts import run_qasper_evaluation as runner

        with tempfile.TemporaryDirectory(prefix="qasper-offline-") as directory:
            root = Path(directory)
            raw = official_fixture()
            raw_path = root / "official-train.json"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            actual_prepare = runner.prepare

            def prepare(*args, **kwargs):
                return actual_prepare(*args, **{**kwargs, "project_root": root})

            output = io.StringIO()
            with patch.object(runner, "prepare", side_effect=prepare), \
                    patch.object(d9_runtime, "run_question", side_effect=AssertionError("prepare must not run QA")), \
                    patch.object(d9_runtime, "RecordedLLM", side_effect=AssertionError("prepare must not create clients")), \
                    patch.object(import_runtime, "import_pdf", side_effect=AssertionError("prepare must not import PDFs")), \
                    redirect_stdout(output):
                result = runner.main(["--raw", str(raw_path), "--sample-id", "offline-sample",
                                      "--split", "train", "--count", "4", "--seed", "20261020"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "prepared")
            sample_path = root / "eval/qasper/offline-sample/sample.json"
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            self.assertEqual(sample["selection"]["input_question_count"], 5)
            self.assertEqual(sample["selection"]["excluded_float_selected"], 1)
            self.assertEqual(sample["selection"]["selected_question_count"], 4)
            self.assertEqual(sample["selection"]["selected_paper_count"], 2)
            self.assertEqual({case["question_id"] for case in sample["cases"]}, {"q-a", "q-b", "q-c", "q-d"})
            self.assertEqual(next(case for case in sample["cases"] if case["question_id"] == "q-a")["answers"],
                             raw["offline-paper-one"]["qas"][0]["answers"])
            reversed_raw = dict(reversed(list(raw.items())))
            for paper in reversed_raw.values():
                paper["qas"] = list(reversed(paper["qas"]))
            same = metrics.prepare_sample(reversed_raw, split="train", count=4, seed=20261020)
            self.assertEqual(sample["cases"], same["cases"])
            validation = metrics.prepare_sample(raw, split="dev", count=4, seed=20261020)
            self.assertEqual((validation["split"], validation["official_split"]), ("validation", "dev"))
            self.assertTrue(all(case["official_split"] == "dev" for case in validation["cases"]))
            self.assertFalse((root / "artifacts/v2/qasper").exists())
            self.assertFalse((root / "eval/dev.jsonl").exists())

            local_pairs = {paper_id: ("local-" + str(index), "revision-1")
                           for index, paper_id in enumerate(sample["papers"], 1)}
            supplied = {"papers": {paper_id: {"paper_id": pair[0], "parse_revision": pair[1],
                        "pdf_version": "arXiv:0000.00000v1", "source_url": "https://example.invalid/paper.pdf"}
                        for paper_id, pair in local_pairs.items()}}
            papers_path = root / "provided-papers.json"
            papers_path.write_text(json.dumps(supplied), encoding="utf-8")
            stored = {}
            for paper_id, paper in sample["papers"].items():
                pair = local_pairs[paper_id]
                stored[pair] = [chunk(pair[0] + "-c" + str(index), paragraph, segment="segment-" + str(index))
                                for index, paragraph in enumerate(
                                    text for section in paper["full_text"] for text in section["paragraphs"])]

            class Store:
                def get_version_chunks(self, paper_id, parse_revision):
                    return deepcopy(stored[(paper_id, parse_revision)])

            @contextmanager
            def store_factory(project_root):
                self.assertEqual(project_root, root)
                yield Store()

            ready = [{"paper_id": pair[0], "parse_revision": pair[1]} for pair in local_pairs.values()]
            with patch.object(d9_runtime, "list_ready_versions", return_value=ready), \
                    patch.object(import_runtime, "import_pdf", side_effect=AssertionError("reuse must not import")):
                runner.import_papers("offline-sample", papers_path, project_root=root, store_factory=store_factory)
            bindings = json.loads((sample_path.parent / "papers.json").read_text(encoding="utf-8"))
            self.assertTrue(all(row["status"] == "ready" for row in bindings["papers"].values()))
            calls = []
            question_pairs = {case["question"]: local_pairs[case["paper_id"]] for case in sample["cases"]}

            def runtime(question, selected_versions, *, mode, project_root, library_mode, answer_instructions):
                original = question
                self.assertEqual(list(selected_versions), [question_pairs[original]])
                self.assertEqual(project_root, root)
                self.assertTrue(library_mode)
                self.assertNotIn("GOLD_ONLY", question)
                self.assertEqual(question, original)
                self.assertEqual(answer_instructions, runner.ENGLISH_INSTRUCTION)
                self.assertNotIn("GOLD_ONLY", answer_instructions)
                calls.append({"question": question, "original": original, "mode": mode,
                              "pairs": deepcopy(selected_versions), "answer_instructions": answer_instructions})
                report = published("Offline published prediction.")
                report.update(mode=mode, embedding_requests=1, llm_requests=2, network_requests=3,
                    embedding_statistics={"embedding_requests": 1, "failed_requests": 0, "total_tokens": 7},
                    chat_statistics={"sdk_request_attempts": 2, "http_request_attempts": 2,
                        "network_retries": 0, "repairs": 0, "total_tokens": 25, "known_total_tokens": 25},
                    rerank_statistics={"requests": 0, "failed_requests": 0, "total_tokens": 0, "elapsed_seconds": 0})
                return report

            runner.run("offline-sample", "offline-batch", project_root=root, runtime_runner=runtime)
            self.assertEqual(len(calls), 8)
            self.assertEqual([call["mode"] for call in calls], ["fixed_rag", "agent"] * 4)
            self.assertTrue(all(call["question"] == call["original"] for call in calls))
            from paper_assistant.context import DIRECT_ANSWER_RULES
            self.assertTrue(all("English" in call["answer_instructions"] and
                                DIRECT_ANSWER_RULES in call["answer_instructions"] for call in calls))
            with patch.object(d9_runtime, "run_question", side_effect=AssertionError("score must be local")), \
                    patch.object(import_runtime, "import_pdf", side_effect=AssertionError("score must not import")):
                summary = runner.score("offline-batch", project_root=root)
            self.assertEqual(summary["counts"]["fixed_sample_questions"], 4)
            self.assertEqual(summary["counts"]["ready_papers"], 2)
            self.assertEqual(summary["modes"]["agent"]["attempted_count"], 4)
            self.assertEqual(summary["costs"]["actual_batch"]["embedding"]["embedding_requests"], 8)
            batch_path = root / "artifacts/v2/qasper/offline-batch"
            self.assertTrue((batch_path / "summary.json").is_file())
            for case in sample["cases"]:
                record = json.loads((batch_path / (case["question_id"] + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(set(record["pair"]["modes"]), {"fixed_rag", "agent"})

            calls.clear()
            runner.run("offline-sample", "offline-agent-only", project_root=root, runtime_runner=runtime, modes=["agent"])
            self.assertEqual(len(calls), 4)
            self.assertTrue(all(call["mode"] == "agent" for call in calls))
            for case in sample["cases"]:
                row = json.loads((root / "artifacts/v2/qasper/offline-agent-only" / (case["question_id"] + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(row["actual_question"], case["question"])
                self.assertEqual(row["answer_instructions"], runner.ENGLISH_INSTRUCTION)
                self.assertEqual(set(row["pair"]["modes"]), {"agent"})
                old = json.loads((batch_path / (case["question_id"] + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(set(old["pair"]["modes"]), {"fixed_rag", "agent"})

    def test_scoring_matches_official_rules_and_preserves_mapping_gaps(self):
        p0 = "The copper network transmits complete packets through the shared research router."
        p1 = "An amber endpoint retries a delayed message after the socket timeout expires."
        p2 = "Cobalt telemetry records unrelated hardware temperatures during the evening."
        pdf_p1 = p1.replace("endpoint", "end-\npoint")
        segment = p0 + "\n" + pdf_p1
        cut0, cut1 = len(p0) // 2, len(p0) + 1 + len(pdf_p1) // 2
        chunks = [chunk("c0", segment[:cut0 + 12]),
                  chunk("c1", segment[cut0:cut1], start=cut0),
                  chunk("c2", segment[cut1 - 12:], start=cut1 - 12),
                  chunk("unrelated", p2, segment="unrelated", page=3)]
        mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [p0, p1]},
             {"section_name": "Other", "paragraphs": [p2]}], chunks)
        paragraphs = {row["paragraph_id"]: row for row in mapping["paragraphs"]}
        self.assertTrue(all(row["status"] == "mapped" for row in paragraphs.values()))
        self.assertEqual(set(paragraphs["s0:p0"]["chunk_ids"]), {"c0", "c1"})
        self.assertEqual(set(paragraphs["s0:p1"]["chunk_ids"]), {"c1", "c2"})
        self.assertEqual(set(mapping["chunks"]["c1"]["paragraph_ids"]), {"s0:p0", "s0:p1"})
        self.assertEqual(mapping["chunks"]["unrelated"]["pdf_page"], 3)
        self.assertTrue(paragraphs["s0:p0"]["positions"])
        self.assertEqual(metrics.normalize_answer(" The AMBER,  network! "), "amber network")
        self.assertAlmostEqual(metrics.token_f1_score("The amber, amber network.", "amber network"), 0.8)
        self.assertEqual(metrics.token_f1_score("", ""), 0)
        self.assertEqual(metrics.paragraph_f1_score([], []), 1)

        def case(identifier, annotations):
            return {"paper_id": "official-paper", "question_id": identifier, "question": "An original question?",
                    "answers": annotations}

        priority = case("priority", [
            annotation(answer="ignored", spans=["ignored"], yes_no=True, unanswerable=True, evidence=[p0]),
            annotation(answer="ignored", spans=["The Amber", "Cobalt"], yes_no=False, evidence=[p0]),
            annotation(answer="A free answer", yes_no=False, evidence=[p1]),
            annotation(answer="", yes_no=False), annotation(answer="", yes_no=True)])
        self.assertEqual([reference["answer"] for reference in metrics.references_for_case(priority)],
                         ["Unanswerable", "The Amber, Cobalt", "A free answer", "No", "Yes"])
        self.assertEqual(metrics.references_for_case(priority)[0]["evidence"], [])
        multiple = case("multi", [annotation(answer="Amber", evidence=[p0]),
                                  annotation(answer="Cobalt", evidence=[p1])])
        best = metrics.score_qasper_case(multiple, published("Amber", ["c2", "c2"]), mapping)
        self.assertEqual((best["answer_f1"], best["evidence_f1"]), (1, 1))
        self.assertEqual(best["prediction"]["evidence_chunk_ids"], ["c2"])
        self.assertEqual(best["prediction"]["evidence"], [p1])
        single = case("single", [annotation(answer="Amber", evidence=[p0])])
        false_positive = metrics.score_qasper_case(single, published("Amber", ["c0", "unrelated"]), mapping)
        self.assertAlmostEqual(false_positive["evidence_f1"], 2 / 3)
        ordered = published()
        ordered["answer"]["claims"] = [{"claim": "First sentence.", "citation_ids": ["c0"]},
                                         {"claim": "Second sentence.", "citation_ids": ["c0", "c1"]}]
        ordered["result"]["action_steps"] = [{"draft": "GOLD_ONLY_INTERMEDIATE_DRAFT"}]
        ordered["result"]["context"]["shown_evidence"] = chunks
        self.assertEqual(metrics.extract_prediction(ordered),
                         {"answer": "First sentence.\n\nSecond sentence.", "evidence_chunk_ids": ["c0", "c1"]})
        no = case("no", [annotation(answer="", yes_no=False)])
        absent = case("unanswerable", [annotation(answer="", unanswerable=True)])
        missing = case("missing", [annotation(answer="Amber", evidence=[p0])])
        gap = case("gap", [annotation(answer="Amber", evidence=[p0]),
                           annotation(answer="Amber", evidence=["Official paragraph absent from the PDF."])])
        pending = case("pending", [annotation(answer="Amber", evidence=[p0])])
        refused = published(status="insufficient_evidence")
        failed = published(status="tool_error")
        for row, report in ((no, published("No")), (absent, refused)):
            score = metrics.score_qasper_case(row, report, mapping)
            self.assertEqual((score["answer_f1"], score["evidence_f1"]), (1, 1))
        failed_score = metrics.score_qasper_case(missing, failed, {})
        self.assertEqual((failed_score["answer_f1"], failed_score["evidence_f1"]), (0, 0))
        self.assertIsNone(metrics.extract_prediction(failed))
        unknown = metrics.score_qasper_case(multiple, published("Amber", ["unmapped-chunk"]), mapping)
        self.assertEqual(unknown["answer_f1"], 1)
        self.assertIsNone(unknown["evidence_f1"])
        self.assertIn("unmapped-chunk", unknown["mapping_gaps"]["unresolved_chunk_ids"])
        unmapped_gold = metrics.score_qasper_case(gap, published("Amber", ["c0"]), mapping)
        self.assertIsNone(unmapped_gold["evidence_f1"])
        self.assertIn("Official paragraph absent from the PDF.",
                      unmapped_gold["mapping_gaps"]["unresolved_reference_evidence"])
        not_attempted = metrics.score_qasper_case(pending, None, mapping, attempted=False)
        self.assertIsNone(not_attempted["answer_f1"])
        self.assertIsNone(not_attempted["evidence_f1"])
        cases = [multiple, no, absent, missing, gap, pending]
        sample = {"cases": cases, "papers": {"official-paper": {}}, "selection": {}}
        reports = [(multiple, published("Amber", ["c2"]), published("Amber", ["unmapped-chunk"])),
                   (no, published("No"), published("No")), (absent, refused, refused),
                   (missing, failed, failed), (gap, published("Amber", ["c0"]), published("Amber", ["c0"]))]
        records = [{"question_id": row["question_id"], "pair": {"modes": {"fixed_rag": fixed, "agent": agent}}}
                   for row, fixed, agent in reports]
        bindings = {"papers": {"official-paper": {"status": "ready", "paper_id": "local-paper",
                                                     "parse_revision": "r1", "mapping": mapping}}}
        summary = metrics.summarize_qasper(sample, records, bindings)
        self.assertEqual(summary["counts"]["fixed_sample_questions"], 6)
        self.assertEqual(summary["common_evidence_count"], 3)
        self.assertEqual(set(summary["common_evidence_question_ids"]), {"no", "unanswerable", "missing"})
        self.assertEqual(summary["common_evidence_coverage"], 0.5)
        for mode in ("fixed_rag", "agent"):
            totals = summary["modes"][mode]
            self.assertEqual((totals["attempted_count"], totals["success_count"], totals["failed_count"],
                              totals["unattempted_count"]), (5, 4, 1, 1))
            self.assertAlmostEqual(totals["answer_f1"], 0.8)
            self.assertIsNone(totals["evidence_f1"])
            self.assertEqual(totals["evidence_f1_status"], "incomplete")
            self.assertAlmostEqual(summary["common_evidence_f1"][mode], 2 / 3)
        self.assertEqual(summary["modes"]["fixed_rag"]["evidence_f1_partial"]["denominator"], 4)
        self.assertAlmostEqual(summary["modes"]["fixed_rag"]["evidence_f1_partial"]["mean"], 0.75)
        self.assertEqual(summary["modes"]["agent"]["evidence_f1_partial"]["denominator"], 3)

        normalized, source_positions = metrics._paragraph_text_positions("ﬁﬂ")
        self.assertEqual(normalized, "fifl")
        self.assertEqual(source_positions, [(0, 1), (0, 1), (1, 2), (1, 2)])
        ligature_original = "The bi-directional filtering workflow preserves useful evidence before producing the final scientific answer."
        ligature_pdf = ligature_original.replace("bi-directional", "bi-\ndirectional").replace(
            "filtering", "ﬁltering").replace("workflow", "workﬂow")
        ligature_chunk = chunk("ligatures", ligature_pdf, start=19, segment="ligatures", page=4)
        ligature_map = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [ligature_original]}], [ligature_chunk])
        ligature_paragraph = ligature_map["paragraphs"][0]
        self.assertEqual(ligature_paragraph["status"], "mapped")
        self.assertEqual(ligature_paragraph["text"], ligature_original)
        self.assertEqual(ligature_paragraph["chunk_ids"], ["ligatures"])
        self.assertEqual(min(position["char_start"] for position in ligature_paragraph["positions"]), 19)
        self.assertEqual(max(position["char_end"] for position in ligature_paragraph["positions"]),
                         19 + len(ligature_pdf))
        self.assertEqual({position["pdf_page"] for position in ligature_paragraph["positions"]}, {4})
        self.assertEqual(ligature_chunk["text"], ligature_pdf)

        represented = ("We follow BIBREF6 for memory updates and use $h_t = f(x_t)$ to encode the current query. "
                       'We discuss this update in Sec. "Model Analysis" before analyzing the complete memory behavior. '
                       "Fig. 1. illustrates the complete mechanism while the controller reads the stored context.")
        rendered = represented.replace("BIBREF6", "(Kumar et al., 2015)").replace(
            "$h_t = f(x_t)$", "ht = f(xt)").replace('Sec. "Model Analysis"', "Sec.6.1").replace("Fig. 1.", "Fig. 1 .")
        represented_map = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [represented]}],
            [chunk("represented", rendered, segment="represented")])
        self.assertEqual(represented_map["paragraphs"][0]["status"], "mapped")
        self.assertEqual(represented_map["paragraphs"][0]["text"], represented)
        self.assertEqual(represented_map["paragraphs"][0]["chunk_ids"], ["represented"])

        lost_inline = rendered.replace("ht = f(xt)", "=")
        residue_start = lost_inline.index("=")
        lost_inline_map = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [represented]}],
            [chunk("inline-body", lost_inline, segment="inline"),
             chunk("formula-residue", "=", start=residue_start, segment="inline")])
        self.assertEqual(lost_inline_map["paragraphs"][0]["status"], "mapped")
        self.assertEqual(lost_inline_map["chunks"]["formula-residue"]["status"], "unresolved")

        before_diagram = ("We analyze each incoming question by encoding its words through the input module and memory module, "
                          "which preserve the retrieved supporting facts. The controller combines both states to produce")
        after_diagram = "the final answer."
        interrupted_original = before_diagram + " " + after_diagram
        diagram_text = "Figure 1: Question Input Memory Answer diagram annotation only."
        diagram_start = len(before_diagram) + 1
        diagram_end = diagram_start + len(diagram_text)
        after_start = diagram_end + 1
        after_cut = len(after_diagram) // 2
        for same_segment in (False, True):
            with self.subTest(interrupted_same_segment=same_segment):
                before_start = 0 if same_segment else 17
                body_after_start = after_start if same_segment else 29
                before_segment = "interrupted" if same_segment else "body-before"
                after_segment = "interrupted" if same_segment else "body-after"
                interrupted_chunks = [
                    chunk("body-before", before_diagram, start=before_start, segment=before_segment),
                    chunk("diagram", diagram_text, start=diagram_start if same_segment else 0,
                          segment="interrupted" if same_segment else "diagram"),
                    chunk("body-after-left", after_diagram[:after_cut + 10],
                          start=body_after_start, segment=after_segment),
                    chunk("body-after-right", after_diagram[after_cut:],
                          start=body_after_start + after_cut, segment=after_segment),
                ]
                if same_segment:
                    interrupted_chunks.append(chunk("mixed", before_diagram + "\n" + diagram_text + "\n" + after_diagram,
                                                    segment="interrupted"))
                original_chunks = deepcopy(interrupted_chunks)
                interrupted = metrics.build_paragraph_mapping(
                    [{"section_name": "Method", "paragraphs": [interrupted_original]}], interrupted_chunks)
                paragraph = interrupted["paragraphs"][0]
                self.assertEqual(paragraph["status"], "mapped")
                self.assertTrue({"body-before", "body-after-left", "body-after-right"}.issubset(paragraph["chunk_ids"]))
                self.assertNotIn("diagram", paragraph["chunk_ids"])
                self.assertEqual(interrupted["chunks"]["diagram"]["status"], "unresolved")
                if same_segment:
                    self.assertTrue(all(position["char_end"] <= diagram_start or position["char_start"] >= diagram_end
                                        for position in paragraph["positions"]))
                    self.assertEqual(interrupted["chunks"]["mixed"]["status"], "unresolved")
                else:
                    self.assertEqual({position["segment_id"] for position in paragraph["positions"]},
                                     {"body-before", "body-after"})
                self.assertEqual(interrupted_chunks, original_chunks)

        ordinary_parenthesis = ("The controller uses the gated update (without sharing parameters) to preserve "
                                "the query representation before selecting the final supporting evidence for every answer.")
        changed_parenthesis = ordinary_parenthesis.replace("without sharing parameters", "with shared parameters")
        ordinary_map = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [ordinary_parenthesis]}],
            [chunk("ordinary-parenthesis", changed_parenthesis, segment="ordinary-parenthesis")])
        self.assertEqual(ordinary_map["paragraphs"][0]["status"], "unresolved")
        self.assertEqual(ordinary_map["chunks"]["ordinary-parenthesis"]["status"], "unresolved")

        ambiguous = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": ["Attention Mechanism", r"$h_t = \sigma(Wx_t)$"]}],
            [chunk("figure-title", "Attention Mechanism", segment="figure-title"),
             chunk("body-title", "Attention Mechanism", segment="body-title"),
             chunk("lost-formula", "= (2)", segment="lost-formula")])
        self.assertEqual(ambiguous["paragraphs"][0]["status"], "unresolved")
        self.assertEqual(ambiguous["paragraphs"][0]["reason"], "ambiguous_pdf_text")
        self.assertEqual(ambiguous["paragraphs"][1]["status"], "unresolved")
        self.assertEqual(ambiguous["chunks"]["lost-formula"]["status"], "unresolved")

        def structured_child(identifier, pieces, *, kind="body"):
            text, spans = "", []
            for literal, block_id, source_start, bbox, role in pieces:
                if text:
                    text += " "
                start = len(text)
                text += literal
                spans.append({"block_id": block_id, "source_field": "content" if source_start is None else "text",
                    "pdf_page": 2, "bbox": bbox, "page_size": [600, 800], "coordinate_system": "normalized",
                    "content_type": role, "text_start": start, "text_end": len(text),
                    "source_char_start": source_start,
                    "source_char_end": source_start + len(literal) if source_start is not None else None})
            return {"chunk_id": identifier, "pdf_page": 2, "text": text, "source_spans": spans,
                    "content_type": kind, "section_path": ["Method"]}

        left_text, right_text = p0.split(" through ")
        right_text = "through " + right_text
        left_box, right_box = [0.1, 0.1, 0.45, 0.3], [0.55, 0.1, 0.9, 0.3]
        nullable_box = [0.1, 0.4, 0.9, 0.6]
        overlap_start = left_text.index("complete")
        structured_chunks = [
            structured_child("z-first", [(left_text, "block-z", 0, left_box, "text"),
                                         (right_text, "block-a", 0, right_box, "text")]),
            structured_child("a-overlap", [(left_text[overlap_start:], "block-z", overlap_start + 2, left_box, "text"),
                                           (right_text, "block-a", 0, right_box, "text")]),
            structured_child("mixed-null", [(p1 + " Additional unmatched measurements remain.",
                                              "region-null", None, nullable_box, "text")]),
            structured_child("null-overlap", [(p1, "region-null", None, nullable_box, "text")]),
            structured_child("image-caption", [(p2, "image/content/1", None, [0.1, 0.7, 0.9, 0.75], "image_caption")],
                             kind="image"),
            structured_child("unassociated-formula", [(r"\[m = 7\]", "equation", None,
                                                        [0.2, 0.8, 0.8, 0.85], "formula")], kind="formula"),
            structured_child("short-title-one", [("Attention Mechanism", "title-one", 0, left_box, "text")]),
            structured_child("short-title-two", [("Attention Mechanism", "title-two", 0, right_box, "text")]),
        ]
        # A's stored word is already joined; its parser ranges still skip '-\n'.
        joined_word = left_text.index("network") + 3
        original_span = structured_chunks[0]["source_spans"][0]
        structured_chunks[0]["source_spans"][:1] = [
            {**original_span, "text_end": joined_word, "source_char_end": joined_word},
            {**original_span, "text_start": joined_word, "source_char_start": joined_word + 2,
             "source_char_end": len(left_text) + 2},
        ]
        before_structured = deepcopy(structured_chunks)
        structured_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [p0, p1, p2, "Attention Mechanism"]}], structured_chunks)
        structured_paragraphs = structured_mapping["paragraphs"]
        self.assertEqual([row["status"] for row in structured_paragraphs], ["mapped", "mapped", "mapped", "unresolved"])
        self.assertEqual(structured_paragraphs[0]["chunk_ids"], ["z-first", "a-overlap"])
        self.assertEqual(structured_paragraphs[-1]["reason"], "ambiguous_pdf_text")
        self.assertEqual({tuple(position["bbox"]) for position in structured_paragraphs[0]["positions"]},
                         {tuple(left_box), tuple(right_box)})
        for position in structured_paragraphs[0]["positions"]:
            self.assertIn(position["chunk_id"], {"z-first", "a-overlap"})
            self.assertEqual(position["pdf_page"], 2)
            self.assertEqual(position["coordinate_system"], "normalized")
            self.assertNotIn("segment_id", position)
        overlap_positions = [position for position in structured_paragraphs[0]["positions"]
                             if position["chunk_id"] == "a-overlap" and position["block_id"] == "block-z"]
        self.assertEqual(min(position["source_char_start"] for position in overlap_positions), overlap_start + 2)
        original_positions = [position for position in structured_paragraphs[0]["positions"]
                              if position["chunk_id"] == "z-first" and position["block_id"] == "block-z"]
        self.assertTrue(any(position["source_char_end"] == joined_word for position in original_positions))
        self.assertTrue(any(position["source_char_start"] == joined_word + 2 for position in original_positions))
        self.assertEqual(structured_mapping["chunks"]["mixed-null"]["status"], "unresolved")
        self.assertEqual(structured_mapping["chunks"]["mixed-null"]["reason"], "partial_text_coverage")
        self.assertEqual(structured_mapping["chunks"]["null-overlap"]["status"], "mapped")
        for position in structured_paragraphs[1]["positions"]:
            self.assertIsNone(position["source_char_start"])
            self.assertIsNone(position["source_char_end"])
            self.assertEqual(position["bbox"], nullable_box)
        self.assertEqual(structured_mapping["chunks"]["image-caption"]["status"], "mapped")
        self.assertEqual(structured_mapping["chunks"]["image-caption"]["source_roles"], ["image_caption"])
        self.assertEqual(structured_mapping["coverage"]["chunks_total"], 8)
        self.assertEqual(structured_mapping["coverage"]["partial_coverage_chunks"], 1)
        self.assertEqual(structured_mapping["coverage"]["unassociated_chunks"], 3)
        partial_score = metrics.score_qasper_case(case("structured-gap", [annotation(answer="Amber", evidence=[p1])]),
                                                published("Amber", ["mixed-null"]), structured_mapping)
        self.assertEqual(partial_score["answer_f1"], 1)
        self.assertIsNone(partial_score["evidence_f1"])
        self.assertIn("mixed-null", partial_score["mapping_gaps"]["unresolved_chunk_ids"])
        self.assertEqual(structured_chunks, before_structured)

        # The saved parent proves this cross-page boundary; child texts never contain a hyphen.
        seam_original = ("The training controller reads complete examples and updates the learned answer module "
                         "while preserving the hidden memory states for every remaining training task.")
        seam_cut = seam_original.index("answer") + 2
        seam_left, seam_right = seam_original[:seam_cut], seam_original[seam_cut:]
        seam_children = [
            structured_child("seam-left", [(seam_left, "left-source", 0, left_box, "text")]),
            structured_child("interrupting-table", [("unrecognized table values 71 83", "table-source", None,
                                                     nullable_box, "table")], kind="table"),
            structured_child("seam-right", [(seam_right, "right-source", 0, right_box, "text")]),
        ]
        for child in seam_children:
            child["parent_id"] = "training-parent" if child["chunk_id"] != "interrupting-table" else "table-parent"
        seam_children[-1]["pdf_page"] = 3
        seam_children[-1]["source_spans"][0]["pdf_page"] = 3
        parent_spans = [deepcopy(seam_children[0]["source_spans"][0]),
                        deepcopy(seam_children[-1]["source_spans"][0])]
        parent_spans[1].update(text_start=seam_cut, text_end=len(seam_original))
        parent = {"parent_id": "training-parent", "text": seam_original, "source_spans": parent_spans,
                  "child_ids": ["seam-left", "seam-right"]}
        seam_sources = [
            {"block_id": "heading-source", "type": "heading", "text": "Model Details", "pdf_page": 2,
             "bbox": left_box, "page_size": [600, 800], "coordinate_system": "normalized"},
            {"block_id": "left-source", "type": "text", "text": seam_left + "-", "pdf_page": 2},
            {"block_id": "table-source", "type": "table", "text": "unrecognized table values 71 83", "pdf_page": 3},
            {"block_id": "right-source", "type": "text", "text": seam_right, "pdf_page": 3,
             "continues_prev": True},
        ]
        seam_full_text = [{"section_name": "Method", "paragraphs": ["Model Details", seam_original]}]
        before_seam = deepcopy(seam_children)
        seam_mapping = metrics.build_paragraph_mapping(seam_full_text, seam_children,
                                                        parents=[parent], sources=seam_sources)
        title, body = seam_mapping["paragraphs"]
        self.assertEqual((title["status"], body["status"]), ("mapped", "mapped"))
        self.assertEqual(title["chunk_ids"], [])
        self.assertEqual(title["positions"][0]["block_id"], "heading-source")
        self.assertEqual(title["positions"][0]["location_kind"], "heading_source")
        self.assertNotIn("chunk_id", title["positions"][0])
        self.assertNotIn("text_start", title["positions"][0])
        self.assertEqual(set(body["chunk_ids"]), {"seam-left", "seam-right"})
        self.assertEqual({position["pdf_page"] for position in body["positions"]}, {2, 3})
        self.assertEqual(seam_mapping["chunks"]["interrupting-table"]["paragraph_attribution"]["status"], "unresolved")
        for identifier in ("seam-left", "seam-right"):
            self.assertEqual(seam_mapping["chunks"][identifier]["paragraph_attribution"]["status"], "mapped")
            self.assertNotIn("s0:p0", seam_mapping["chunks"][identifier]["paragraph_attribution"]["paragraph_ids"])
        self.assertEqual(seam_children, before_seam)
        unproven_seam = metrics.build_paragraph_mapping(seam_full_text, seam_children)
        self.assertEqual(unproven_seam["paragraphs"][1]["status"], "unresolved")
        repeated_headings = metrics.build_paragraph_mapping(seam_full_text, seam_children,
            parents=[parent], sources=[*seam_sources, {**seam_sources[0], "block_id": "second-heading"}])
        self.assertEqual(repeated_headings["paragraphs"][0]["status"], "unresolved")
        self.assertEqual(repeated_headings["paragraphs"][0]["reason"], "ambiguous_pdf_text")

        attribution_original = ("The controller preserves the complete training sequence before selecting useful "
                                "memory states and producing the final answer BIBREF9.")
        attribution_pdf = attribution_original.replace("BIBREF9", "(Xu et al., 2015)")
        attribution_children = [
            structured_child("citation-tail", [(attribution_pdf, "citation-source", 0, left_box, "text")]),
            structured_child("known-plus-unknown", [(attribution_pdf + " New.", "mixed-source", 0,
                                                     right_box, "text")]),
        ]
        # Repeated PDF occurrences would be ambiguous, so locate each independent case separately.
        citation_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [attribution_original]}], attribution_children[:1])
        citation_record = citation_mapping["chunks"]["citation-tail"]
        self.assertEqual(citation_record["status"], "unresolved")
        self.assertEqual(citation_record["reason"], "partial_text_coverage")
        self.assertEqual(citation_record["paragraph_attribution"]["status"], "mapped")
        self.assertTrue(citation_record["paragraph_attribution"]["basis"])
        citation_score = metrics.score_qasper_case(case("citation-attribution", [
            annotation(answer="Amber", evidence=[attribution_original])]),
            published("Amber", ["citation-tail"]), citation_mapping)
        self.assertEqual(citation_score["evidence_f1"], 1)
        self.assertEqual(citation_mapping["coverage"]["mapped_chunks"], 0)
        self.assertEqual(citation_mapping["coverage"]["attributed_chunks"], 1)
        unknown_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [attribution_original]}], attribution_children[1:])
        unknown_record = unknown_mapping["chunks"]["known-plus-unknown"]
        self.assertGreater(len(attribution_pdf) / len(attribution_children[1]["text"]), 0.95)
        self.assertEqual(unknown_record["paragraph_attribution"]["status"], "unresolved")
        self.assertTrue(unknown_record["paragraph_attribution"]["unresolved_ranges"])
        self.assertEqual(lost_inline_map["chunks"]["formula-residue"]["paragraph_attribution"]["status"], "unresolved")
        self.assertEqual(structured_mapping["chunks"]["unassociated-formula"]["paragraph_attribution"]["status"], "unresolved")
        self.assertEqual(represented_map["chunks"]["represented"]["paragraph_attribution"]["status"], "mapped")
        legacy_mapping = deepcopy(mapping)
        for record in legacy_mapping["chunks"].values():
            record.pop("paragraph_attribution")
        self.assertEqual(metrics.map_evidence(legacy_mapping, ["c0", "unrelated"], [{"evidence": [p0]}]),
                         metrics.map_evidence(mapping, ["c0", "unrelated"], [{"evidence": [p0]}]))

        protocol = metrics.EVALUATION_PROTOCOL
        direct = published("An explanation of the supporting evidence.", ["c0"])
        direct["answer"]["direct_answer"] = "Amber"
        direct["answer"]["claims"].append({"claim": "A second explanation.",
                                             "citation_ids": ["unrelated", "c0"]})
        direct["result"]["answer"] = deepcopy(direct["answer"])
        prediction = metrics.extract_prediction(direct, evaluation_protocol=protocol)
        self.assertEqual(prediction, {"answer": "Amber", "evidence_chunk_ids": ["c0", "unrelated"]})
        direct_score = metrics.score_qasper_case(single, direct, mapping, evaluation_protocol=protocol)
        self.assertEqual(direct_score["answer_f1"], 1)
        self.assertAlmostEqual(direct_score["evidence_f1"], 2 / 3)
        self.assertEqual(direct_score["prediction"]["evidence_chunk_ids"], ["c0", "unrelated"])
        self.assertEqual(metrics.extract_prediction(direct)["answer"],
                         "An explanation of the supporting evidence.\n\nA second explanation.")
        historical = published("Amber", ["c0"])
        self.assertEqual(metrics.score_qasper_case(single, historical, mapping)["answer_f1"], 1)
        self.assertIsNone(metrics.extract_prediction(historical, evaluation_protocol=protocol))
        missing_direct = metrics.score_qasper_case(single, historical, mapping, evaluation_protocol=protocol)
        self.assertEqual((missing_direct["success"], missing_direct["answer_f1"], missing_direct["evidence_f1"]),
                         (False, 0, 0))
        self.assertEqual(missing_direct["failure_reason"], "missing_direct_answer")
        self.assertEqual(metrics.score_qasper_case(absent, refused, mapping,
                                                   evaluation_protocol=protocol)["answer_f1"], 1)

        abstract = (r"The \Copper-10K benchmark measures memory reasoning with complete questions "
                    "and supporting facts.")
        abstract_pdf = abstract.replace(r"\Copper-10K", "cOpPeR-10k")
        abstract_chunks = [chunk("body-only", p0, segment="body-only", page=2),
                           chunk("abstract-only", abstract_pdf, segment="abstract-only", page=1)]
        abstract_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [p0]}], abstract_chunks, abstract=abstract)
        abstract_row = abstract_mapping["abstract_evidence"][0]
        self.assertEqual((abstract_row["paragraph_id"], abstract_row["text"], abstract_row["status"]),
                         ("abstract:p0", abstract, "mapped"))
        self.assertEqual(abstract_row["chunk_ids"], ["abstract-only"])
        self.assertEqual({position["pdf_page"] for position in abstract_row["positions"]}, {1})
        self.assertEqual(abstract_mapping["coverage"]["paragraphs_total"], 1)
        self.assertEqual(abstract_mapping["coverage"]["mapped_paragraphs"], 1)
        self.assertEqual([row["paragraph_id"] for row in abstract_mapping["paragraphs"]], ["s0:p0"])
        self.assertEqual(abstract_mapping["coverage"]["attribution_scope"], "body_and_abstract")
        self.assertEqual(abstract_mapping["chunks"]["abstract-only"]["paragraph_attribution"]["paragraph_ids"],
                         ["abstract:p0"])
        abstract_prediction = published("The explanation still cites both actual sources.",
                                       ["body-only", "abstract-only"])
        abstract_prediction["answer"]["direct_answer"] = "Amber"
        abstract_prediction["result"]["answer"] = deepcopy(abstract_prediction["answer"])
        abstract_case = case("abstract-extra", [annotation(answer="Amber", evidence=[p0])])
        abstract_score = metrics.score_qasper_case(abstract_case, abstract_prediction, abstract_mapping,
                                                   evaluation_protocol=protocol)
        self.assertEqual(abstract_score["answer_f1"], 1)
        self.assertEqual(abstract_score["prediction"]["evidence"], [p0, abstract])
        self.assertAlmostEqual(abstract_score["evidence_f1"], 2 / 3)
        abstract_gold_case = case("abstract-gold", [annotation(answer="Amber", evidence=[abstract])])
        self.assertEqual(metrics.map_evidence(abstract_mapping, ["abstract-only"],
                         metrics.references_for_case(abstract_gold_case))["predicted_evidence"], [abstract])
        mixed_abstract_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [p0]}],
            [chunk("known-mixed", p0 + "\n" + abstract_pdf, segment="known-mixed", page=1)], abstract=abstract)
        self.assertEqual(mixed_abstract_mapping["chunks"]["known-mixed"]["paragraph_attribution"]["status"],
                         "mapped")
        self.assertEqual(set(mixed_abstract_mapping["chunks"]["known-mixed"]["paragraph_attribution"]["paragraph_ids"]),
                         {"s0:p0", "abstract:p0"})
        unknown_abstract_mapping = metrics.build_paragraph_mapping(
            [{"section_name": "Method", "paragraphs": [p0]}],
            [abstract_chunks[0], chunk("unknown-mixed", abstract_pdf + " Unexplained auxiliary content.",
                                       segment="unknown-mixed", page=1)], abstract=abstract)
        self.assertEqual(unknown_abstract_mapping["abstract_evidence"][0]["status"], "mapped")
        self.assertEqual(unknown_abstract_mapping["chunks"]["unknown-mixed"]["paragraph_attribution"]["status"],
                         "unresolved")
        unknown_abstract_prediction = published("Explanation.", ["unknown-mixed"])
        unknown_abstract_prediction["answer"]["direct_answer"] = "Amber"
        unknown_abstract_prediction["result"]["answer"] = deepcopy(unknown_abstract_prediction["answer"])
        unknown_abstract_score = metrics.score_qasper_case(abstract_case, unknown_abstract_prediction,
            unknown_abstract_mapping, evaluation_protocol=protocol)
        self.assertIsNone(unknown_abstract_score["evidence_f1"])
        self.assertIn("unknown-mixed", unknown_abstract_score["mapping_gaps"]["unresolved_chunk_ids"])

        # The selected mode reaches the runtime itself, and saved input governs offline scoring.
        from paper_assistant.agent_comparison import run_current_case
        from scripts import run_qasper_evaluation as runner

        with tempfile.TemporaryDirectory(prefix="qasper-agent-only-") as directory:
            root = Path(directory)
            calls = []

            def agent_only_runtime(question, selected_versions, *, mode, project_root, library_mode):
                self.assertEqual(mode, "agent")
                self.assertEqual(list(selected_versions), [("local-paper", "revision-1")])
                self.assertEqual(project_root, root)
                self.assertTrue(library_mode)
                self.assertNotIn("GOLD_ONLY", question)
                calls.append(mode)
                report = deepcopy(abstract_prediction)
                report.update(mode=mode, network_requests=3,
                    embedding_statistics={"embedding_requests": 1, "failed_requests": 0, "total_tokens": 7},
                    chat_statistics={"sdk_request_attempts": 1, "http_request_attempts": 1,
                        "network_retries": 0, "repairs": 0, "total_tokens": 25},
                    rerank_statistics={"requests": 1, "total_tokens": 8, "elapsed_seconds": 0})
                return report

            pair = run_current_case("Which color is reported?", [("local-paper", "revision-1")],
                project_root=root, runtime_runner=agent_only_runtime, modes=["agent"])
            self.assertEqual(calls, ["agent"])
            self.assertEqual(pair["selected_modes"], ["agent"])
            self.assertEqual(set(pair["modes"]), {"agent"})
            self.assertEqual(pair["status"], "completed")
            self.assertEqual(set(pair["costs"]["per_mode"]), {"agent"})
            pending_case = {**deepcopy(abstract_case), "paper_id": "pending-paper", "question_id": "pending-only"}
            adapted_sample = {"cases": [abstract_case, pending_case],
                "papers": {"official-paper": {}, "pending-paper": {}}, "selection": {}}
            adapted_bindings = {"papers": {
                "official-paper": {"status": "ready", "paper_id": "local-paper",
                                   "parse_revision": "revision-1", "mapping": abstract_mapping},
                "pending-paper": {"status": "pending_pdf", "mapping": None}}}
            sample_dir = root / "eval/qasper/agent-only"
            sample_dir.mkdir(parents=True)
            (sample_dir / "sample.json").write_text(json.dumps(adapted_sample), encoding="utf-8")
            (sample_dir / "papers.json").write_text(json.dumps(adapted_bindings), encoding="utf-8")
            calls.clear()
            run_summary = runner.run("agent-only", "agent-batch", project_root=root,
                                     runtime_runner=agent_only_runtime, modes=["agent"])
            self.assertEqual(calls, ["agent"])
            batch_dir = root / "artifacts/v2/qasper/agent-batch"
            inputs = json.loads((batch_dir / "input.json").read_text(encoding="utf-8"))
            self.assertEqual(inputs["modes"], ["agent"])
            self.assertEqual(inputs["evaluation_protocol"], protocol)
            record = json.loads((batch_dir / "abstract-extra.json").read_text(encoding="utf-8"))
            self.assertEqual(set(record["pair"]["modes"]), {"agent"})
            self.assertEqual(set(record["scores"]), {"agent"})
            self.assertEqual(record["predictions"]["agent"]["answer"], "Amber")
            self.assertEqual(record["scores"]["agent"]["answer_f1"], 1)
            self.assertAlmostEqual(record["scores"]["agent"]["evidence_f1"], 2 / 3)
            with patch.object(d9_runtime, "run_question", side_effect=AssertionError("score must be local")):
                offline_summary = runner.score("agent-batch", project_root=root)
            self.assertEqual(offline_summary, run_summary)
            self.assertEqual(set(offline_summary["modes"]), {"agent"})
            self.assertEqual(offline_summary["selected_modes"], ["agent"])
            self.assertEqual(offline_summary["evaluation_protocol"], protocol)
            self.assertEqual(offline_summary["counts"]["fully_attempted_questions"], 1)
            self.assertEqual(offline_summary["counts"]["unattempted_questions"], 1)
            self.assertEqual(offline_summary["modes"]["agent"]["failed_count"], 0)
            self.assertEqual(offline_summary["common_evidence_question_ids"], ["abstract-extra"])
            self.assertEqual(set(offline_summary["common_evidence_f1"]), {"agent"})
            self.assertEqual(set(offline_summary["costs"]["per_mode"]), {"agent"})
            self.assertEqual(offline_summary["costs"]["actual_batch"]["embedding"]["embedding_requests"], 1)
            with patch.object(runner, "run", return_value=run_summary) as selected_run, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["run", "--sample-id", "agent-only", "--batch-id", "cli-batch",
                                              "--modes", "agent"]), 0)
            self.assertEqual(selected_run.call_args.kwargs["modes"], ["agent"])


if __name__ == "__main__":
    unittest.main()
