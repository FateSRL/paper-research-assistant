"""D4 分块边界检查：只用内存材料，不读取 PDF、密钥或调用网络。

这些检查关心分块后的证据是否可信：有没有漏字、有没有越过 D3 的
排除边界、能否按偏移回查原文，以及错误来源能否在入库前被拒绝。
运行：python -X utf8 -m scripts.check_chunking
"""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from paper_assistant.chunking import (
    ChunkingConfig,
    PreparedChunkVersion,
    build_chunks,
    canonical_json_bytes,
    save_chunk_version,
    split_text_ranges,
)
from paper_assistant.quality import FILTER_REVISION, filter_text_blocks


def filtered_fixture() -> tuple[list[dict], dict]:
    """模拟同一块中有一条损坏行：过滤器必须产生两个隔离的片段。

    使用现有过滤函数生成 segment_id、行号和矩形，避免测试偷偷假设
    另一种与 D3 不兼容的输入格式。页元数据随后在内存中补齐。
    """
    paper = {
        "paper_id": "arxiv_2005.11401v4",
        "arxiv_version": "v4",
        "title": "Synthetic chunk boundary fixture",
        "source_url": "https://arxiv.org/abs/2005.11401v4",
        "local_path": "data/papers/synthetic-test.pdf",
        "pdf_sha256": "a" * 64,
        "page_count": 1,
        "text_selectable": True,
    }
    texts = [
        "  Before the damaged line: 保留中文和标点。 ",
        "broken\x03line must never enter a chunk",
        "After the damaged line: separate source evidence. ",
    ]
    blocks = [{
        "type": 0,
        "lines": [
            {
                "bbox": [0.0, float(index * 12), 200.0, float(index * 12 + 10)],
                "spans": [{"text": text, "font": "NimbusRomNo9L-Regu"}],
            }
            for index, text in enumerate(texts)
        ],
    }]
    segments, excluded = filter_text_blocks(
        blocks, {}, [], paper["paper_id"], 1
    )
    for segment in segments:
        segment.update({
            "paper_id": paper["paper_id"],
            "pdf_sha256": paper["pdf_sha256"],
            "pdf_page": 1,
            "filter_revision": FILTER_REVISION,
        })
    page = {
        "paper_id": paper["paper_id"],
        "pdf_sha256": paper["pdf_sha256"],
        "pdf_page": 1,
        "filter_revision": FILTER_REVISION,
        "rules_revision": "d3-quality-rules-v1",
        "source_raw_text_sha256": hashlib.sha256(
            "\n".join(texts).encode("utf-8")
        ).hexdigest(),
        "coordinate_system": "PDF points, top-left origin",
        "text": "\n\n".join(segment["text"] for segment in segments),
        "segments": segments,
        "excluded_lines": excluded,
        "quality_filtered": True,
        "indexable": True,
        "quality_scope": "automatic_screening_plus_exact_hash_region_rules",
        "human_verified": False,
    }
    return [page], paper


class TextWindowChecks(unittest.TestCase):
    def test_windows_cover_every_original_character_and_respect_maximum(self):
        # 同时覆盖短文本、无空格长文本、换行、中文以及首尾空白。
        # 断言完整覆盖字符位置，而不绑定实现选择哪一个换行处分割。
        config = ChunkingConfig(max_chars=17, overlap_chars=4)
        for text in [
            "short",
            "abcdefghijklmnopqrstuvwxyz" * 4,
            "  中文行一。\nEnglish line two.\n\n第三段！  " * 4,
        ]:
            with self.subTest(text=text[:20]):
                ranges = split_text_ranges(text, config)
                covered = set()
                self.assertTrue(ranges)
                self.assertEqual(ranges[0][0], 0)
                self.assertEqual(ranges[-1][1], len(text))
                previous_start = -1
                previous_end = 0
                for start, end in ranges:
                    self.assertGreater(start, previous_start)
                    self.assertGreater(end, start)
                    self.assertLessEqual(end, len(text))
                    self.assertLessEqual(end - start, config.max_chars)
                    self.assertLessEqual(start, previous_end)
                    covered.update(range(start, end))
                    previous_start, previous_end = start, end
                self.assertEqual(covered, set(range(len(text))))

    def test_empty_text_cannot_create_an_evidence_chunk(self):
        with self.assertRaises(ValueError):
            split_text_ranges("", ChunkingConfig())

    def test_zero_overlap_still_covers_text_once(self):
        text = "abcdefghijklmno" * 5
        ranges = split_text_ranges(text, ChunkingConfig(max_chars=13, overlap_chars=0))
        self.assertEqual("".join(text[start:end] for start, end in ranges), text)
        self.assertTrue(all(end - start <= 13 for start, end in ranges))

    def test_invalid_configuration_is_rejected(self):
        # bool 在 Python 中是 int 的子类；作为长度仍应拒绝，避免隐式误配。
        for max_chars, overlap_chars in [
            (0, 0), (-1, 0), (8, -1), (8, 8), (8, 9),
            (8.5, 0), (8, 1.5), (True, 0), (8, False),
        ]:
            with self.subTest(max_chars=max_chars, overlap_chars=overlap_chars):
                with self.assertRaises(ValueError):
                    config = ChunkingConfig(
                        max_chars=max_chars, overlap_chars=overlap_chars
                    )
                    split_text_ranges("enough text for windows", config)


class SourceBoundaryChecks(unittest.TestCase):
    def setUp(self):
        self.pages, self.paper = filtered_fixture()
        self.config = ChunkingConfig(max_chars=19, overlap_chars=4)
        self.revision = "test-revision-v1"

    def chunks(self, pages=None, paper=None):
        return build_chunks(
            self.pages if pages is None else pages,
            self.paper if paper is None else paper,
            self.revision,
            self.config,
        )

    def test_excluded_line_keeps_both_sides_as_separate_sources(self):
        segments = self.pages[0]["segments"]
        self.assertEqual(len(segments), 2)
        chunks = self.chunks()
        self.assertEqual(
            {chunk["segment_id"] for chunk in chunks},
            {segment["segment_id"] for segment in segments},
        )
        for segment in segments:
            related = [c for c in chunks if c["segment_id"] == segment["segment_id"]]
            covered = set()
            for chunk in related:
                start, end = chunk["char_start"], chunk["char_end"]
                covered.update(range(start, end))
                self.assertEqual(chunk["text"], segment["text"][start:end])
                self.assertNotIn("broken", chunk["text"])
                self.assertEqual(chunk["source_line_indices"], segment["source_line_indices"])
            self.assertEqual(covered, set(range(len(segment["text"]))))

    def test_each_chunk_has_exact_slice_hash_and_source_metadata(self):
        sources = {segment["segment_id"]: segment for segment in self.pages[0]["segments"]}
        chunks = self.chunks()
        self.assertTrue(chunks)
        for chunk in chunks:
            source = sources[chunk["segment_id"]]
            expected = source["text"][chunk["char_start"]:chunk["char_end"]]
            self.assertEqual(chunk["text"], expected)
            self.assertEqual(chunk["text_sha256"], hashlib.sha256(expected.encode("utf-8")).hexdigest())
            self.assertEqual(chunk["paper_id"], self.paper["paper_id"])
            self.assertEqual(chunk["pdf_sha256"], self.paper["pdf_sha256"])
            self.assertEqual(chunk["pdf_page"], 1)
            self.assertEqual(chunk["parse_revision"], self.revision)
            self.assertEqual(chunk["filter_revision"], FILTER_REVISION)
            self.assertEqual(chunk["source_block_index"], source["source_block_index"])
            self.assertEqual(chunk["segment_bbox"], source["bbox"])
            self.assertLessEqual(len(chunk["text"]), self.config.max_chars)

        from paper_assistant.structured_chunking import build_structured_chunks

        def unit(identifier, text, *, page=1, kind="text", section="Method", **extra):
            return {"block_id": identifier, "pdf_page": page, "bbox": [0.1, 0.2, 0.45, 0.8],
                    "page_size": [600, 800], "coordinate_system": "normalized", "type": kind,
                    "section_path": [section] if section else [], "text": text, **extra}

        count_tokens = lambda text: len(text.split())
        formula = r"\[h_t = \sigma(Wx_t + Uh_{t-1})\] (2)"
        table_header = "<tr><th>Setting name</th><th>Measured score</th></tr>"
        table_rows = [f"<tr><td>configuration {index}</td><td>score {index}</td></tr>" for index in range(6)]
        list_items = ["- Accuracy uses the complete held out evaluation split.",
                      "- Latency measures the elapsed time for each request.",
                      "- Memory records the maximum usage during every run."]
        caption = "Figure 1. Controller and memory overview."
        caption_sources = [
            unit("figure-caption-label", "Figure 1.", kind="caption", bbox=[0.1, 0.81, 0.45, 0.84]),
            unit("figure-caption-text", "Controller and memory overview.", kind="caption", bbox=[0.1, 0.84, 0.45, 0.9]),
        ]
        caption_fields = [
            {**caption_sources[0], "source_field": "text", "field_start": 0, "field_end": len("Figure 1."),
             "source_char_available": True},
            {**caption_sources[1], "source_field": "text", "field_start": len("Figure 1. "), "field_end": len(caption),
             "source_char_available": False},
        ]
        structured_units = [
            unit("method-heading", "1 Method", kind="heading"),
            unit("body-left", "The neural controller reads the complete query and combines retrieved facts before producing an-"),
            unit("figure-region", "INPUT MEMORY OUTPUT", kind="image",
                 caption=caption, assets=["assets/figure-1.png"], field_sources={"caption": caption_fields}),
            unit("running-header", "Page header must stay outside retrieval", page=2, kind="header", section=""),
            unit("body-next-page", "swer tokens while preserving the supporting facts from the original document.",
                 page=2, continues_prev=True),
            unit("retained-formula", formula, page=2, kind="formula"),
            unit("evaluation-heading", "2 Evaluation", page=2, kind="heading", section="Evaluation"),
            unit("evaluation-table", "", page=2, kind="table", section="Evaluation",
                 table_html="<table>" + table_header + "".join(table_rows) + "</table>",
                 caption="Table 1: evaluation measurements"),
            unit("evaluation-list", "\n".join(list_items), page=2, kind="list", section="Evaluation"),
            unit("references", "Reference entry must stay outside retrieval", page=2,
                 kind="reference", section="References"),
        ]
        image_cases = []
        image_sources = []
        for identifier, fields in (("footnotes-only", ("footnotes",)),
                                   ("caption-and-footnotes", ("caption", "footnotes"))):
            field_sources, values = {}, {}
            for index, field in enumerate(fields):
                text = f"{identifier} {field} explanation."
                source = unit(f"{identifier}-{field}", text, page=2,
                              kind=f"image_{field}", bbox=[0.1, 0.81 + index * 0.04, 0.9, 0.84 + index * 0.04])
                image_sources.append(source)
                values[field] = text
                field_sources[field] = [{**source, "source_field": "text", "field_start": 0,
                    "field_end": len(text), "source_char_available": field == "caption"}]
            image_cases.append(unit(identifier, "", page=2, kind="image", section="References",
                field_sources=field_sources, assets=[f"assets/{identifier}.png"], **values))
        structured_units.extend(image_cases)
        original_units = copy.deepcopy(structured_units)
        structured = build_structured_chunks(structured_units, {**self.paper, "page_count": 2},
            "structured-test-revision", count_tokens=count_tokens, child_tokens=12, parent_tokens=64)
        parents = {parent["parent_id"]: parent for parent in structured["parents"]}
        by_id = {source["block_id"]: source for source in structured_units}
        by_id.update({source["block_id"]: source for source in [*caption_sources, *image_sources]})
        self.assertTrue(structured["chunks"])
        self.assertTrue(any("answer tokens" in parent["text"] for parent in parents.values()))
        self.assertTrue(any({span["pdf_page"] for span in parent["source_spans"]} == {1, 2}
                            for parent in parents.values() if parent["content_type"] == "body"))
        self.assertTrue(any(formula in child["text"] for child in structured["chunks"]))
        for child in structured["chunks"]:
            self.assertIn(child["chunk_id"], parents[child["parent_id"]]["child_ids"])
            self.assertNotIn("segment_id", child)
            self.assertEqual(child["parse_revision"], "structured-test-revision")
            self.assertEqual(child["pdf_sha256"], self.paper["pdf_sha256"])
            self.assertLessEqual(child["token_count"], 12)
            self.assertEqual({span["pdf_page"] for span in child["source_spans"]}, {child["pdf_page"]})
            self.assertNotIn("INPUT MEMORY OUTPUT", child["text"])
            self.assertNotIn("must stay outside retrieval", child["text"])
            for span in child["source_spans"]:
                source = by_id[span["block_id"]]
                self.assertEqual(span["bbox"], source["bbox"])
                self.assertEqual(span["page_size"], source["page_size"])
                self.assertEqual(span["coordinate_system"], "normalized")
                original = source
                for field in span["source_field"].split("."):
                    original = original[field]
                if span["source_char_start"] is None:
                    self.assertIsNone(span["source_char_end"])
                else:
                    self.assertEqual(child["text"][span["text_start"]:span["text_end"]],
                                     original[span["source_char_start"]:span["source_char_end"]])
        image = next(child for child in structured["chunks"] if child["content_type"] == "image")
        self.assertEqual(image["assets"], ["assets/figure-1.png"])
        self.assertIn("Figure 1.", image["text"])
        self.assertEqual({span["block_id"] for span in image["source_spans"]},
                         {"figure-caption-label", "figure-caption-text"})
        for span in image["source_spans"]:
            self.assertNotEqual(span["bbox"], by_id["figure-region"]["bbox"])
            self.assertEqual(image["text"][span["text_start"]:span["text_end"]], by_id[span["block_id"]]["text"])
        for case in image_cases:
            expected = "\n".join(case[field] for field in ("caption", "footnotes") if case.get(field))
            parent = next(row for row in parents.values() if row["text"] == expected)
            self.assertEqual(parent["section_path"], ["References"])
            self.assertEqual(parent["content_type"], "image")
            children = [row for row in structured["chunks"] if row["parent_id"] == parent["parent_id"]]
            self.assertEqual("\n".join(row["text"] for row in children), expected)
            for row in [parent, *children]:
                self.assertTrue(row["assets"])
                for span in row["source_spans"]:
                    source = by_id[span["block_id"]]
                    self.assertEqual(span["pdf_page"], 2)
                    self.assertEqual(span["bbox"], source["bbox"])
                    self.assertNotEqual(span["bbox"], case["bbox"])
                    self.assertEqual(span["source_field"], "text")
                    self.assertEqual(row["text"][span["text_start"]:span["text_end"]], source["text"])
                    if source["type"] == "image_footnotes":
                        self.assertIsNone(span["source_char_start"])
                        self.assertIsNone(span["source_char_end"])
        tables = [child for child in structured["chunks"] if child["content_type"] == "table"]
        self.assertGreater(len(tables), 1)
        self.assertTrue(all(table_header in child["text"] for child in tables))
        for row in table_rows:
            self.assertEqual(sum(row in child["text"] for child in tables), 1)
        for item in list_items:
            self.assertTrue(any(item in child["text"] for child in structured["chunks"]))
        self.assertEqual(structured_units, original_units)

        from paper_assistant.mineru_parser import structure_units

        for heading in (" 7. REFERENCES: ", "Bibliography", "参考文献"):
            with self.subTest(reference_heading=heading):
                middle = {"pages": [{"page_idx": 0, "blocks": [
                    {"type": "paragraph_title", "level": 2, "content": heading, "bbox": [0.1, 0.1, 0.9, 0.15]},
                    {"type": "text", "content": "Author. A referenced publication.", "bbox": [0.1, 0.2, 0.9, 0.25]},
                    {"type": "list", "content": [{"content": "Another referenced publication."}],
                     "bbox": [0.1, 0.3, 0.9, 0.35]},
                    {"type": "image", "bbox": [0.1, 0.4, 0.9, 0.6], "content": [
                        {"type": "image_body", "image_path": "images/result.png", "bbox": [0.1, 0.4, 0.9, 0.55]},
                        {"type": "image_caption", "content": "Figure 4. Actual results caption.",
                         "bbox": [0.1, 0.56, 0.9, 0.6]}]},
                    {"type": "table", "bbox": [0.1, 0.65, 0.9, 0.75], "content": [
                        {"type": "table_body", "content": "<table><tr><td>actual table</td></tr></table>",
                         "bbox": [0.1, 0.65, 0.9, 0.75]}]},
                    {"type": "paragraph_title", "level": 2, "content": "References and discussion",
                     "bbox": [0.1, 0.8, 0.9, 0.85]},
                    {"type": "text", "content": "This ordinary discussion stays indexed.", "bbox": [0.1, 0.86, 0.9, 0.9]},
                ]}], "extensions": {"docvortex_layout": {"pages": [
                    {"page_idx": 0, "width_pt": 600, "height_pt": 800}]}}}
                units = structure_units(middle)
                self.assertEqual([row["type"] for row in units],
                                 ["heading", "reference", "reference", "image", "table", "heading", "text"])
                built = build_structured_chunks(units, self.paper, "references-test", count_tokens=count_tokens,
                                                child_tokens=32, parent_tokens=64)
                indexed = "\n".join(child["text"] for child in built["chunks"])
                self.assertNotIn("referenced publication", indexed)
                self.assertIn("Figure 4. Actual results caption.", indexed)
                self.assertIn("actual table", indexed)
                self.assertIn("This ordinary discussion stays indexed.", indexed)
                self.assertTrue(any(child["content_type"] == "image" for child in built["chunks"]))
                self.assertTrue(any(child["content_type"] == "table" for child in built["chunks"]))

    def test_repeated_build_has_stable_unique_ids(self):
        first, second = self.chunks(), self.chunks()
        self.assertEqual(first, second)
        ids = [chunk["chunk_id"] for chunk in first]
        self.assertEqual(len(ids), len(set(ids)))

    def test_raw_pages_cannot_enter_build_chunks(self):
        raw = [{
            "paper_id": self.paper["paper_id"],
            "pdf_sha256": self.paper["pdf_sha256"],
            "pdf_page": 1,
            "text": "Unfiltered raw PDF extraction",
        }]
        with self.assertRaises(ValueError):
            self.chunks(pages=raw)

    def test_wrong_corpus_pdf_hash_is_rejected(self):
        wrong_paper = dict(self.paper, pdf_sha256="b" * 64)
        with self.assertRaises(ValueError):
            self.chunks(paper=wrong_paper)

    def test_duplicate_segment_id_is_rejected(self):
        duplicated = copy.deepcopy(self.pages)
        duplicated[0]["segments"].append(copy.deepcopy(duplicated[0]["segments"][0]))
        with self.assertRaises(ValueError):
            self.chunks(pages=duplicated)


class VersionPersistenceChecks(unittest.TestCase):
    def test_dictionary_order_does_not_change_recipe_fingerprint(self):
        # JSON 对象的键序只影响排版，不应把同一套处理参数变成新版本。
        first = {"paper_id": "fixture", "chunking": {"max_chars": 1600, "overlap_chars": 200}}
        reordered = {"chunking": {"overlap_chars": 200, "max_chars": 1600}, "paper_id": "fixture"}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(reordered))
        self.assertEqual(
            hashlib.sha256(canonical_json_bytes(first)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(reordered)).hexdigest(),
        )
        changed = {"paper_id": "fixture", "chunking": {"max_chars": 1800, "overlap_chars": 200}}
        self.assertNotEqual(canonical_json_bytes(first), canonical_json_bytes(changed))

    def test_version_reuse_keeps_bytes_and_time_and_refuses_tampering(self):
        # 保存逻辑与 PDF 核对逻辑分开验证；这里手工准备最小字节快照。
        # 临时目录明确放在系统临时根目录中，不接触项目的 data/chunks。
        temporary_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix="d4-chunk-check-", dir=temporary_root) as name:
            workspace = Path(name).resolve()
            self.assertTrue(workspace.is_relative_to(temporary_root))
            self.assertNotEqual(workspace, temporary_root)
            paper_id, revision = "fixture_paper", "r_fixture"
            target = workspace / "data" / "chunks" / paper_id / revision
            chunks = [{"chunk_id": "fixture_p1_c1", "text": "本地持久化边界检查。"}]
            manifest = {
                "schema_revision": "d4-chunk-version-v1",
                "paper_id": paper_id,
                "parse_revision": revision,
                "statistics": {"chunk_count": 1},
            }
            files = {
                "chunks.jsonl": canonical_json_bytes(chunks[0]) + b"\n",
                "version_manifest.json": canonical_json_bytes(manifest) + b"\n",
            }
            prepared = PreparedChunkVersion(
                paper_id=paper_id,
                parse_revision=revision,
                output_dir=target,
                manifest=manifest,
                chunks=chunks,
                files=files,
            )
            self.assertIs(save_chunk_version(prepared), False)
            before = {
                relative: (path.read_bytes(), path.stat().st_mtime_ns)
                for relative in files
                for path in [target / relative]
            }
            self.assertIs(save_chunk_version(prepared), True)
            after = {
                relative: (path.read_bytes(), path.stat().st_mtime_ns)
                for relative in files
                for path in [target / relative]
            }
            self.assertEqual(before, after)
            self.assertEqual({key: value[0] for key, value in after.items()}, files)

            # 篡改只发生在上述已确认的临时目录内。再次导入必须报错，
            # 不能悄悄覆盖旧版本，否则版本号将失去追溯意义。
            chunk_path = target / "chunks.jsonl"
            changed_bytes = files["chunks.jsonl"] + b"TAMPERED\n"
            chunk_path.write_bytes(changed_bytes)
            changed_time = chunk_path.stat().st_mtime_ns
            with self.assertRaises(ValueError):
                save_chunk_version(prepared)
            self.assertEqual(chunk_path.read_bytes(), changed_bytes)
            self.assertEqual(chunk_path.stat().st_mtime_ns, changed_time)
            manifest_path = target / "version_manifest.json"
            self.assertEqual(manifest_path.read_bytes(), files["version_manifest.json"])
            self.assertEqual(manifest_path.stat().st_mtime_ns, before["version_manifest.json"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
