"""D9 B offline source-scope regression; temporary PDFs, no env/store/API."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_assistant.context import build_messages
from paper_assistant.source_scope import (
    Registry, SourceScopeError, identify_source_requirement, attach_source_requirement,
    prepare_scoped_context, merge_scoped_context, validate_citation_scope, _lines,
)


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class MemoryStore:
    def __init__(self, chunks):
        self.chunks = deepcopy(chunks)
    def get_chunk(self, identifier):
        return deepcopy(self.chunks.get(identifier))
    def get_version_chunks(self, paper_id, parse_revision):
        return sorted((deepcopy(row) for row in self.chunks.values()
                       if (row["paper_id"], row["parse_revision"]) == (paper_id, parse_revision)),
                      key=lambda row: (row["pdf_page"], row["source_block_index"], row["char_start"], row["chunk_id"]))


class SourceScopeFixture:
    """Reusable real PDF fixture, abstract on page 2, body on page 1.

    .registry is the loaded Registry, .store is an independent memory store.
    .search(ids,query=None) creates a top5 envelope with full snapshot fields.
    .set_region(**changes) writes only the temporary registry and reloads it.
    IDs: body_id, abstract_id, mixed_id. The mixed chunk spans the end of the
    narrowly reviewed region, so it must never acquire abstract qualification.
    """
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="d9_source_scope_")
        self.root = Path(self.temp.name)
        self.project_root = self.root
        self.pairs = [("synthetic_paper", "synthetic_revision")]
        self.paper_id, self.parse_revision = self.pairs[0]
        self.question = "Which facts are named in the paper's abstract?"
        self.body_id, self.abstract_id, self.mixed_id = "body_chunk", "abstract_chunk", "mixed_chunk"
        folder = self.root / "data/papers"
        folder.mkdir(parents=True)
        pdf_path = folder / "fixture.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), "1 Introduction")
            page.insert_text((72, 140), "Body-only fact appears on page one.")
            page = pdf.new_page()
            page.insert_text((72, 72), "Abstract")
            page.insert_text((72, 140), "Verified abstract evidence identifies an offline structural source.\nThe reviewed range ends before this additional passage.")
            page.insert_text((72, 240), "1 Introduction")
            page.insert_text((72, 290), "The rest of the paper begins here.")
            pdf.save(pdf_path)
        pdf_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        parsed, filtered, chunks = [], [], []
        with fitz.open(pdf_path) as pdf:
            for number, page in enumerate(pdf, 1):
                raw = page.get_text("text")
                parsed.append({"paper_id": self.paper_id, "pdf_sha256": pdf_sha, "pdf_page": number, "text": raw})
                segments = []
                for index, block in enumerate(page.get_text("dict")["blocks"]):
                    if block.get("type") != 0:
                        continue
                    segment = {"segment_id": f"segment_{number}_{index}", "source_block_index": index,
                               "source_line_indices": list(range(len(block["lines"]))), "bbox": list(block["bbox"]),
                               "text": _lines(block), "indexable": True}
                    segments.append(segment)
                filtered.append({"paper_id": self.paper_id, "pdf_sha256": pdf_sha, "pdf_page": number,
                                 "filter_revision": "fixture_filter", "source_raw_text_sha256": text_sha(raw), "segments": segments})
            segment = filtered[1]["segments"][1]
            self.abstract_segment = deepcopy(segment)
            def chunk(identifier, number, segment, end=None):
                text = segment["text"][:end]
                return {"chunk_id": identifier, "paper_id": self.paper_id, "parse_revision": self.parse_revision,
                        "pdf_sha256": pdf_sha, "pdf_page": number, "segment_id": segment["segment_id"],
                        "char_start": 0, "char_end": len(text), "text": text, "text_sha256": text_sha(text),
                        "filter_revision": "fixture_filter", "source_block_index": segment["source_block_index"],
                        "source_line_indices": segment["source_line_indices"], "segment_bbox": segment["bbox"]}
            abstract_end = segment["text"].index("\n")
            chunks = [chunk(self.body_id, 1, filtered[0]["segments"][1]),
                      chunk(self.abstract_id, 2, segment, abstract_end), chunk(self.mixed_id, 2, segment)]
            image = self.root / "review.png"
            pdf[1].get_pixmap().save(image)
            blocks = pdf[1].get_text("dict")["blocks"]
            proof = {"review_basis": "original_pdf_visual_and_exact_parse_filter_comparison",
                     "heading_block_index": 0, "body_block_index": 1, "following_heading_block_index": 2,
                     "heading_text_sha256": text_sha(_lines(blocks[0])), "following_heading_text_sha256": text_sha(_lines(blocks[2])),
                     "visual_evidence": {"path": "review.png", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}}
        paths = {"pdf": pdf_path}
        for name, values in (("parsed", parsed), ("filtered", filtered), ("chunks", chunks)):
            paths[name] = self.root / (name + ".jsonl")
            paths[name].write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in values) + "\n", encoding="utf-8")
        files = {name: {"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                 for name, path in paths.items()}
        region = {"scope": "abstract", "pdf_page": 2, "segment_id": segment["segment_id"],
                  "source_block_index": 1, "source_line_indices": segment["source_line_indices"],
                  "segment_char_start": 0, "segment_char_end": abstract_end,
                  "text_sha256": text_sha(segment["text"][:abstract_end]), "verification_status": "verified",
                  "verification_method": "AI_structural_review", "human_review_status": "pending", "structural_evidence": proof}
        self.document = {"schema_revision": "d9-source-regions-v1", "documents": [
            {"paper_id": self.paper_id, "parse_revision": self.parse_revision, "pdf_sha256": pdf_sha,
             "parsed_input_sha256": files["parsed"]["sha256"], "filtered_input_sha256": files["filtered"]["sha256"],
             "chunk_snapshot_sha256": files["chunks"]["sha256"], "files": files, "regions": [region]}]}
        self.chunks = {c["chunk_id"]: deepcopy(c) for c in chunks}
        self.store = MemoryStore(self.chunks)
        self.registry_path = "artifacts/d9/source_regions.json"
        self._write_registry()
        self.registry = Registry(self.root, self.store, self.pairs)

    def _write_registry(self):
        path = self.root / self.registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.document, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_region(self, **changes):
        self.document["documents"][0]["regions"][0].update(changes)
        self._write_registry()
        self.registry = Registry(self.root, self.store, self.pairs)
        return self.registry

    def search(self, identifiers=None, query=None):
        identifiers = [self.body_id, self.abstract_id, self.mixed_id] if identifiers is None else identifiers
        return {"status": "success" if identifiers else "no_hits", "query": query or self.question,
                "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in self.pairs],
                "top_k": 5, "index_profile_id": "synthetic_profile", "returned_count": len(identifiers),
                "results": [{**deepcopy(self.chunks[identifier]), "rank": i, "score": 0.8 - 0.05 * i} for i, identifier in enumerate(identifiers, 1)]}

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.temp.cleanup()


class SourceScopeChecks(unittest.TestCase):
    def setUp(self):
        self.fixture = SourceScopeFixture()
        self.addCleanup(self.fixture.temp.cleanup)
        self.f = self.fixture
        self.req = identify_source_requirement(self.f.question)

    def scoped(self, ids=None, max_chars=8000):
        return prepare_scoped_context(self.f.search(ids), self.req, self.f.registry, max_chars=max_chars)

    def draft(self, identifiers):
        return {"status": "answered", "claims": [{"claim": "Synthetic supported fact", "citation_ids": identifiers}]}

    def test_requirement_explicit_english_and_chinese(self):
        for q in (self.f.question, "What appears in the abstract?", "摘要中提到了什么？", "摘要提到哪些事实？"):
            self.assertEqual(identify_source_requirement(q)["resolution"], "explicit")

    def test_requirement_ambiguous_negated_quoted_conflicting(self):
        for q in ('What is in "the abstract"?', "What is in 'the abstract'?", "What is ‘in the abstract’?", "What is not in the abstract?", "Compare the abstract and body", "摘要还是正文？"):
            self.assertEqual(identify_source_requirement(q)["resolution"], "ambiguous")

    def test_requirement_none_body_and_nonsection(self):
        for q in ("What are the experimental results?", "What is an abstract class?"):
            self.assertEqual(identify_source_requirement(q)["resolution"], "none")

    def test_later_page_qualifies_and_first_page_body_does_not(self):
        self.assertEqual(self.f.registry.qualify(self.f.search([self.f.abstract_id])["results"][0])["coverage"], "abstract_full")
        self.assertEqual(self.f.registry.qualify(self.f.search([self.f.body_id])["results"][0])["coverage"], "body")
        self.assertEqual(self.f.registry.qualify(self.f.search([self.f.mixed_id])["results"][0])["coverage"], "mixed")

    def test_qualification_filters_before_character_budget_and_preserves_raw(self):
        search = self.f.search()
        before = deepcopy(search)
        out = prepare_scoped_context(search, self.req, self.f.registry, max_chars=len(self.f.chunks[self.f.abstract_id]["text"]))
        self.assertEqual(out["context"]["allowed_citation_ids"], [self.f.abstract_id])
        self.assertEqual(out["qualification"]["raw_candidate_count"], 3)
        self.assertEqual(len(out["qualification"]["scope_excluded"]), 2)
        self.assertEqual(search, before)
        build_messages(self.f.question, out["context"])

    def test_body_only_is_qualified_empty_without_lying_about_raw_nohits(self):
        out = self.scoped([self.f.body_id])
        self.assertEqual(out["qualification"]["raw_searches"][0]["status"], "success")
        self.assertEqual(out["qualification"]["raw_candidate_count"], 1)
        self.assertEqual(out["context"]["allowed_citation_ids"], [])

    def test_none_keeps_old_body_context(self):
        question = "What is the body fact?"
        out = prepare_scoped_context(self.f.search([self.f.body_id], question), identify_source_requirement(question), self.f.registry)
        self.assertEqual(out["context"]["allowed_citation_ids"], [self.f.body_id])

    def test_unknown_valid_registry_is_normal_unavailable(self):
        self.f.set_region(verification_status="candidate")
        self.assertFalse(self.f.registry.has_qualified_abstract())
        self.assertEqual(self.f.registry.validate_for_question(self.req, self.f.pairs)["reason"], "source_scope_unavailable")
        self.assertEqual(self.scoped()["context"]["allowed_citation_ids"], [])

    def test_human_rejected_requires_rejected_state(self):
        with self.assertRaises(SourceScopeError):
            self.f.set_region(human_review_status="rejected")
        self.f.set_region(human_review_status="rejected", verification_status="rejected")
        self.assertFalse(self.f.registry.has_qualified_abstract())

    def test_registry_missing_required_document_is_error(self):
        self.f.document["documents"] = []
        self.f._write_registry()
        with self.assertRaisesRegex(SourceScopeError, "来源"):
            Registry(self.f.root, self.f.store, self.f.pairs)

    def test_corrupt_registry_duplicate_and_nonfinite_rejected(self):
        for text in ('{"schema_revision":"d9-source-regions-v1","documents":[],"documents":[]}', '{"x":NaN}'):
            (self.f.root / self.f.registry_path).write_text(text, encoding="utf-8")
            with self.assertRaises(SourceScopeError):
                Registry(self.f.root, self.f.store, self.f.pairs)

    def test_loaded_scope_does_not_rehash_files_or_offline_review_evidence(self):
        path = self.f.root / self.f.registry_path
        path.write_bytes(path.read_bytes() + b" ")
        self.assertTrue(self.f.registry.has_qualified_abstract())

    def test_ineligible_body_store_corruption_still_errors(self):
        self.f.store.chunks[self.f.body_id]["text"] = "bad"
        with self.assertRaises(SourceScopeError):
            self.scoped()

    def test_raw_candidate_corruption_in_omitted_candidate_errors(self):
        search = self.f.search()
        search["results"][0]["pdf_page"] = 2
        with self.assertRaises(SourceScopeError):
            prepare_scoped_context(search, self.req, self.f.registry, max_chars=1)

    def test_requirement_change_is_rejected(self):
        altered = {**self.req, "original_question_sha256": "0" * 64}
        with self.assertRaises(SourceScopeError):
            prepare_scoped_context(self.f.search(), altered, self.f.registry)

    def test_attachment_deepcopies_and_keeps_repair_messages(self):
        out = self.scoped()
        messages = build_messages(self.f.question, out["context"])
        messages.extend([{"role": "assistant", "content": "Previous untrusted text"}, {"role": "user", "content": '{"request":"repair"}'}])
        before = deepcopy(messages)
        attached = attach_source_requirement(messages, self.f.question, self.req)
        self.assertEqual(messages, before)
        self.assertEqual(attached[2:], before[2:])
        payload = json.loads(attached[1]["content"])
        self.assertEqual(payload["source_requirement"], self.req)
        self.assertEqual(payload["shown_evidence"], out["context"]["shown_evidence"])

    def test_attachment_rejects_forged_question_and_duplicate_keys(self):
        messages = build_messages(self.f.question, self.scoped()["context"])
        with self.assertRaises(SourceScopeError):
            attach_source_requirement(messages, "Changed question in the abstract", self.req)
        messages[1]["content"] = '{"question":"q","question":"q"}'
        with self.assertRaises(SourceScopeError):
            attach_source_requirement(messages, self.f.question, self.req)

    def test_attachment_forbids_unseen_text_and_evaluation_labels(self):
        messages = build_messages(self.f.question, self.scoped()["context"])
        for field in ("unseen_evidence", "expected_evidence", "case_id"):
            payload = json.loads(messages[1]["content"])
            payload[field] = "injected"
            changed = deepcopy(messages)
            changed[1]["content"] = json.dumps(payload)
            with self.assertRaises(SourceScopeError):
                attach_source_requirement(changed, self.f.question, self.req)

    def test_each_actual_citation_and_unshown_illegal_citation(self):
        out = self.scoped()
        self.assertEqual(validate_citation_scope(self.draft([self.f.abstract_id]), out["context"], out["qualification"], self.f.registry)["status"], "valid")
        result = validate_citation_scope(self.draft([self.f.abstract_id, self.f.body_id]), out["context"], out["qualification"], self.f.registry)
        self.assertEqual(result["status"], "invalid_output")
        self.assertEqual(len(result["checks"]), 2)

    def test_sidecar_eligible_flag_does_not_authorize_a_body_citation(self):
        out = self.scoped()
        out["qualification"]["decisions"][0]["eligible"] = True
        self.assertEqual(validate_citation_scope(self.draft([self.f.body_id]), out["context"], out["qualification"], self.f.registry)["status"], "invalid_output")

    def test_publication_checks_cited_source_without_rebuilding_raw_rounds(self):
        out = self.scoped()
        self.f.store.chunks[self.f.abstract_id]["text"] = "forged"
        self.assertEqual(validate_citation_scope(self.draft([self.f.abstract_id]), out["context"], out["qualification"], self.f.registry)["status"], "tool_error")

    def test_retry_query_does_not_replace_original_requirement(self):
        retry = self.f.search([self.f.abstract_id], "Find a missing source passage")
        out = merge_scoped_context(self.f.search([self.f.body_id]), retry, self.f.question, self.f.pairs, self.f.registry, requirement=self.req)
        self.assertEqual(out["context"]["question"], self.f.question)
        self.assertEqual(out["qualification"]["requirement"], self.req)
        self.assertEqual(out["context"]["allowed_citation_ids"], [self.f.abstract_id])
        self.assertEqual(validate_citation_scope(self.draft([self.f.abstract_id]), out["context"], out["qualification"], self.f.registry)["status"], "valid")

    def test_retry_first_dedup_keeps_original_ranks(self):
        out = merge_scoped_context(self.f.search([self.f.abstract_id]), self.f.search([self.f.abstract_id], "Other query"), self.f.question,
                                   self.f.pairs, self.f.registry, requirement=self.req)
        self.assertEqual(out["trace"]["selection_origins"][self.f.abstract_id]["round"], "retry")
        self.assertEqual(len(out["trace"]["duplicates"]), 1)
        self.assertEqual(out["qualification"]["raw_candidate_count"], 2)

    def test_point_ids_scope_pairs_and_profile(self):
        from paper_assistant.retrieval import point_id
        self.assertEqual(self.f.registry.abstract_point_ids("synthetic_profile", self.f.pairs), [point_id("synthetic_profile", self.f.abstract_id)])
        with self.assertRaises(SourceScopeError):
            self.f.registry.abstract_point_ids("synthetic_profile", [("other", "revision")])

    def test_missing_snapshot_cannot_qualify_a_candidate(self):
        self.f.registry._chunks.pop(self.f.abstract_id)
        with self.assertRaises(SourceScopeError):
            self.f.registry.qualify(self.f.search([self.f.abstract_id])["results"][0])

    def test_merge_checks_ineligible_raw_conflicting_revision_and_body_damage(self):
        initial = self.f.search([self.f.abstract_id, self.f.body_id])
        retry = self.f.search([self.f.body_id], "Other query")
        retry["results"][0]["parse_revision"] = "other_revision"
        with self.assertRaises(Exception):
            merge_scoped_context(initial, retry, self.f.question, self.f.pairs, self.f.registry, requirement=self.req)
        self.f.store.chunks[self.f.body_id]["text"] = "corrupt"
        with self.assertRaises(SourceScopeError):
            merge_scoped_context(initial, self.f.search([self.f.body_id], "Other query"), self.f.question,
                                 self.f.pairs, self.f.registry, max_chars=1, requirement=self.req)

    def test_count_cap_after_scope_filters_all_ten_raw_candidates(self):
        extra = []
        for index in range(10):
            chunk = deepcopy(self.f.chunks[self.f.abstract_id])
            chunk["chunk_id"] = f"abstract_{index}"
            extra.append(chunk)
            self.f.chunks[chunk["chunk_id"]] = chunk
        path = self.f.root / "chunks.jsonl"
        path.write_text("\n".join(json.dumps(c) for c in self.f.chunks.values()) + "\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        doc = self.f.document["documents"][0]
        doc["files"]["chunks"]["sha256"] = doc["chunk_snapshot_sha256"] = digest
        self.f._write_registry()
        self.f.store.chunks = deepcopy(self.f.chunks)
        self.f.registry = Registry(self.f.root, self.f.store, self.f.pairs)
        initial = self.f.search([c["chunk_id"] for c in extra[:5]])
        retry = self.f.search([c["chunk_id"] for c in extra[5:]], "Other query")
        out = merge_scoped_context(initial, retry, self.f.question, self.f.pairs, self.f.registry, requirement=self.req)
        self.assertEqual(len(out["context"]["shown_evidence"]), 8)
        self.assertEqual(out["qualification"]["raw_candidate_count"], 10)
        self.assertEqual(len(out["trace"]["count_omitted"]), 2)
        self.assertEqual(out["trace"]["merged_ids"][:5], [c["chunk_id"] for c in extra[5:]])
        self.f.store.chunks[extra[4]["chunk_id"]]["text"] = "damaged beyond final count cap"
        with self.assertRaises(SourceScopeError):
            merge_scoped_context(initial, retry, self.f.question, self.f.pairs, self.f.registry, requirement=self.req)

    def test_real_three_paper_registry_allows_strict_one_paper_context(self):
        document = json.loads((ROOT / "artifacts/d9/source_regions.json").read_text(encoding="utf-8"))
        chunks, pairs = {}, []
        for doc in document["documents"]:
            pairs.append((doc["paper_id"], doc["parse_revision"]))
            for line in (ROOT / doc["files"]["chunks"]["path"]).read_text(encoding="utf-8").splitlines():
                chunk = json.loads(line)
                chunks[chunk["chunk_id"]] = chunk
        registry = Registry(ROOT, MemoryStore(chunks), pairs)
        one_pair = [pairs[1]]
        self.assertTrue(registry.validate_for_question(self.req, one_pair)["available"])
        identifier = registry.qualified_chunk_ids(one_pair)[0]
        search = {"status": "success", "query": self.f.question, "selected_versions": [{"paper_id": one_pair[0][0], "parse_revision": one_pair[0][1]}],
                  "top_k": 5, "index_profile_id": "offline_profile", "returned_count": 1, "results": [{**chunks[identifier], "rank": 1, "score": 0.7}]}
        out = prepare_scoped_context(search, self.req, registry)
        self.assertEqual(len(out["context"]["selected_versions"]), 1)
        retry = {**deepcopy(search), "query": "Find another abstract source"}
        merged = merge_scoped_context(search, retry, self.f.question, one_pair, registry, requirement=self.req)
        self.assertEqual(validate_citation_scope(self.draft([identifier]), merged["context"], merged["qualification"], registry)["status"], "valid")
        retry["selected_versions"] = [{"paper_id": pairs[0][0], "parse_revision": pairs[0][1]}]
        with self.assertRaises(Exception):
            merge_scoped_context(search, retry, self.f.question, one_pair, registry, requirement=self.req)


if __name__ == "__main__":
    unittest.main()
