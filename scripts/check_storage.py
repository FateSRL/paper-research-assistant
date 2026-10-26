"""D4 任务 C 的存储边界检查：只在系统临时目录中创建 SQLite 数据库。

运行：python -X utf8 -m scripts.check_storage

这里不读取 .env，不调用网络、模型或向量服务，也不修改正式论文和
chunks。测试关心可观察的行为：原文是否完整保存、同一版本是否重复
入库、旧版本是否被覆盖，以及导入失败后有没有留下半篇数据。
"""

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from paper_assistant.storage import (
    PaperStore,
    StoredVersionInput,
    StorageConflict,
    StorageError,
)


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    """固定 JSON 序列化方式，生成与数据对应的真实 SHA-256。

    recipe 用键排序、紧凑分隔符计算身份；清单和论文快照则使用可读
    JSON 加末尾换行。这两个不同用途的字节序列不能混用。
    """
    options = {"ensure_ascii": False, "sort_keys": True, "allow_nan": False}
    if pretty:
        return (json.dumps(value, indent=2, **options) + "\n").encode("utf-8")
    return json.dumps(value, separators=(",", ":"), **options).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def storage_fixture(
    *, max_chars: int = 1600, pdf_sha256: str = "a" * 64,
    source_url: str = "https://arxiv.org/abs/2005.11401v4",
) -> StoredVersionInput:
    """造一篇两页、两个完整片段的论文，保持正式数据的字段约定。

    不照搬正式题集或读取项目文件，因此即使正式库有内容，测试结果
    仍然独立。中文、换行和首尾空白是刻意放入的：原文回查不应偷偷
    strip 文本、改换行，或者只保存另一份与原文不同的摘要。
    """
    paper = {
        "paper_id": "arxiv_2005.11401v4",
        "arxiv_version": "v4",
        "title": "SQLite 原文回查测试论文",
        "source_url": source_url,
        "local_path": "data/papers/2005.11401v4.pdf",
        "pdf_sha256": pdf_sha256,
        "page_count": 2,
        "text_selectable": True,
    }
    recipe = {
        "paper_id": paper["paper_id"],
        "pdf_sha256": paper["pdf_sha256"],
        "paper_metadata_sha256": _sha256(_json_bytes(paper, pretty=True)),
        "raw_jsonl_sha256": "b" * 64,
        "filtered_jsonl_sha256": "c" * 64,
        "quality_rules_sha256": "d" * 64,
        "python_version": "3.11.5",
        "parser": {"name": "PyMuPDF", "version": "1.28.2", "extraction": "page.get_text('text')"},
        "filter_revision": "d3-quality-filter-v1",
        "rules_revision": "d3-quality-rules-v1",
        "chunker_revision": "d4-segment-character-window-v1",
        "processing_source_sha256": {
            "ingest.py": "e" * 64, "quality.py": "f" * 64, "chunking.py": "0" * 64,
        },
        "chunking": {"max_chars": max_chars, "overlap_chars": 200},
        "length_unit": "Python Unicode code points; not embedding tokens",
        "boundary_policy": "within_single_segment; prefer_tail_newline_then_whitespace",
        "text_preprocessing": "none; exact source slice",
        "chunk_id_format": "{paper_id}_{parse_revision}_p{pdf_page}_c{one_based_page_chunk_index}",
    }
    recipe_sha256 = _sha256(_json_bytes(recipe))
    revision = "r_" + recipe_sha256[:16]
    texts = [
        "  第一块正文。\n保留换行与末尾空格。  ",
        "\n第二块正文，含中文、ASCII 和前后空白。\n",
    ]
    chunks = []
    for page, text in enumerate(texts, start=1):
        digest = _sha256(text.encode("utf-8"))
        chunks.append({
            "chunk_id": f"{paper['paper_id']}_{revision}_p{page}_c1",
            "paper_id": paper["paper_id"],
            "parse_revision": revision,
            "pdf_sha256": paper["pdf_sha256"],
            "pdf_page": page,
            "segment_id": f"{paper['paper_id']}:p{page}:b0:l0-1:{digest[:12]}",
            "char_start": 0,
            "char_end": len(text),
            "text": text,
            "text_sha256": digest,
            "filter_revision": recipe["filter_revision"],
            "source_block_index": 0,
            "source_line_indices": [0, 1],
            "segment_bbox": [0.0, 10.0, 200.0, 40.0],
        })
    manifest = {
        "schema_revision": "d4-chunk-version-v1",
        "paper_id": paper["paper_id"],
        "parse_revision": revision,
        "recipe_sha256": recipe_sha256,
        "recipe": recipe,
        "source_paths": {
            "pdf": paper["local_path"],
            "raw": f"data/parsed/{paper['paper_id']}.jsonl",
            "filtered": f"data/filtered/{paper['paper_id']}.jsonl",
            "rules": "eval/quality_rules.json",
        },
        "source_scope": "D3 indexable segments only; recovered figure/math not included",
        "human_review_status": "pending",
        "segment_bbox_scope": "parent segment region; not an exact chunk rectangle",
        "index_status": "chunks_only; SQLite and vector import not yet performed",
        "files": {
            "paper.json": {
                "sha256": recipe["paper_metadata_sha256"],
                "bytes": len(_json_bytes(paper, pretty=True)),
            },
        },
    }
    _update_chunk_manifest(manifest, chunks, paper)
    return _bundle(paper, manifest, chunks)


def _update_chunk_manifest(manifest: dict, chunks: list[dict], paper: dict) -> None:
    """只整理测试材料的清单，避免冲突测试因无关的计数错误而提前失败。"""
    payload = b"".join((json.dumps(chunk, ensure_ascii=False) + "\n").encode("utf-8") for chunk in chunks)
    pages = Counter(chunk["pdf_page"] for chunk in chunks)
    segments = Counter(chunk["segment_id"] for chunk in chunks)
    manifest["files"]["chunks.jsonl"] = {"sha256": _sha256(payload), "bytes": len(payload)}
    manifest["statistics"] = {
        "page_count": paper["page_count"],
        "segment_count": len(segments),
        "chunk_count": len(chunks),
        "split_segment_count": sum(count > 1 for count in segments.values()),
        "max_chunk_chars": max(len(chunk["text"]) for chunk in chunks),
        "chunks_per_page": {str(page): pages[page] for page in range(1, paper["page_count"] + 1)},
    }


def _bundle(paper: dict, manifest: dict, chunks: list[dict]) -> StoredVersionInput:
    return StoredVersionInput(
        paper=paper, manifest=manifest, chunks=chunks,
        snapshot_path=f"data/chunks/{paper['paper_id']}/{manifest['parse_revision']}",
        manifest_sha256=_sha256(_json_bytes(manifest, pretty=True)),
    )


class SQLiteStorageChecks(unittest.TestCase):
    """每项测试拥有独立数据库，不依赖其它测试先执行。"""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="paper-storage-check-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        self.stores = []
        # Windows 不允许删除仍被打开的 SQLite 文件，清理时先关闭连接，
        # 再由 TemporaryDirectory 清理自己的目录，不处理工作区文件。
        self.addCleanup(self._close_connections)
        self.bundle = storage_fixture()

    def _close_connections(self) -> None:
        for store in self.stores:
            store.connection.close()

    def open_store(self, *, read_only: bool = False) -> PaperStore:
        store = PaperStore(self.database_path, read_only=read_only)
        self.stores.append(store)
        return store

    def assert_counts(self, store: PaperStore, *, papers: int, versions: int, chunks: int) -> None:
        self.assertEqual(store.counts(), {
            "papers": papers, "parse_versions": versions, "chunks": chunks,
            # C 只入 SQLite；尚未向量化，不能顺便伪造向量导入完成记录。
            "index_imports": 0,
        })

    def test_first_import_preserves_text_and_all_source_fields(self) -> None:
        store = self.open_store()
        result = store.import_version(self.bundle)
        self.assertFalse(result["reused"])
        self.assertEqual(result["inserted_chunks"], 2)
        self.assertEqual(result["chunk_count"], 2)
        self.assert_counts(store, papers=1, versions=1, chunks=2)
        for expected in self.bundle.chunks:
            actual = store.get_chunk(expected["chunk_id"])
            self.assertIsNotNone(actual)
            for key, value in expected.items():
                with self.subTest(chunk_id=expected["chunk_id"], field=key):
                    self.assertEqual(actual[key], value)

        # 本地论文没有 arXiv 版本或远程链接，仍使用同一事实存储和回查。
        paper = {**self.bundle.paper, "paper_id": "local_offline", "source_type": "local",
                 "arxiv_version": "", "source_url": "", "local_path": "data/papers/local_offline.pdf"}
        recipe = {"paper_id": paper["paper_id"], "pdf_sha256": paper["pdf_sha256"],
                  "filter_revision": self.bundle.manifest["recipe"]["filter_revision"],
                  "chunking": self.bundle.manifest["recipe"]["chunking"]}
        recipe_sha256 = _sha256(_json_bytes(recipe))
        revision = "r_" + recipe_sha256[:16]
        chunks = [{**chunk, "paper_id": paper["paper_id"], "parse_revision": revision,
                   "chunk_id": f"{paper['paper_id']}_{revision}_p{chunk['pdf_page']}_c1"}
                  for chunk in self.bundle.chunks]
        manifest = {"schema_revision": "d4-chunk-version-v1", "paper_id": paper["paper_id"],
                    "parse_revision": revision, "recipe": recipe, "recipe_sha256": recipe_sha256,
                    "source_paths": {"pdf": paper["local_path"]},
                    "statistics": self.bundle.manifest["statistics"]}
        imported = store.import_version(_bundle(paper, manifest, chunks))
        self.assertEqual(imported["chunk_count"], 2)
        source = store.get_chunk(chunks[0]["chunk_id"])
        self.assertEqual(source["arxiv_version"], "")
        self.assertEqual(source["source_url"], "")
        self.assertEqual(source["text"], chunks[0]["text"])

        from paper_assistant import storage
        from paper_assistant.chunk_snapshot import load_chunk_version

        # A structured parent spans pages; each child keeps its actual page-local regions.
        paper = self.bundle.paper
        recipe = {"paper_id": paper["paper_id"], "pdf_sha256": paper["pdf_sha256"],
                  "parser": {"name": "mineru", "version": "4.0.12", "tier": "standard", "page_range": "all"},
                  "chunking": {"child_tokens": 512, "parent_tokens": 1536,
                               "tokenizer": "offline-tokenizer", "revision": "structured-pdf-v1"}}
        recipe_sha256 = _sha256(_json_bytes(recipe))
        revision = "r_" + recipe_sha256[:16]
        parent_id = f"{paper['paper_id']}_{revision}_parent1"
        first = "Recovered body "
        formula = "with $h_t=f(x_t)$."
        continuation = "Second page continuation."
        first_spans = [
            {"block_id": "body-1", "pdf_page": 1, "bbox": [0.1, 0.2, 0.45, 0.3], "page_size": [600, 800],
             "source_char_start": 0, "source_char_end": len(first), "text_start": 0, "text_end": len(first)},
            {"block_id": "formula-2", "pdf_page": 1, "bbox": [0.55, 0.2, 0.9, 0.3], "page_size": [600, 800],
             "source_char_start": None, "source_char_end": None,
             "text_start": len(first), "text_end": len(first + formula)}]
        second_span = {"block_id": "body-3", "pdf_page": 2, "bbox": [0.1, 0.1, 0.8, 0.2],
                       "page_size": [600, 800], "source_char_start": 0,
                       "source_char_end": len(continuation), "text_start": 0, "text_end": len(continuation)}
        structured_chunks = []
        for page, text, spans in ((1, first + formula, first_spans), (2, continuation, [second_span])):
            structured_chunks.append({"chunk_id": f"{paper['paper_id']}_{revision}_p{page}_c1",
                "paper_id": paper["paper_id"], "parse_revision": revision, "pdf_sha256": paper["pdf_sha256"],
                "pdf_page": page, "text": text, "text_sha256": _sha256(text.encode("utf-8")),
                "parent_id": parent_id, "section_path": ["Introduction", "Method"],
                "content_type": "paragraph", "source_spans": copy.deepcopy(spans), "token_count": len(text.split())})
        parent_offset = len(first + formula) + 2
        parent = {"parent_id": parent_id, "paper_id": paper["paper_id"], "parse_revision": revision,
                  "section_path": ["Introduction", "Method"], "content_type": "paragraph",
                  "text": first + formula + "\n\n" + continuation,
                  "child_ids": [chunk["chunk_id"] for chunk in structured_chunks],
                  "source_spans": [*copy.deepcopy(first_spans), {**second_span,
                      "text_start": parent_offset, "text_end": parent_offset + len(continuation)}]}
        project_root = Path(self.temporary_directory.name)
        relative = f"data/chunks/{paper['paper_id']}/{revision}"
        folder = project_root / relative
        folder.mkdir(parents=True)
        manifest = {"schema_revision": "structured-pdf-v1", "paper_id": paper["paper_id"],
                    "parse_revision": revision, "recipe": recipe, "recipe_sha256": recipe_sha256,
                    "source_paths": {"pdf": paper["local_path"], "paper": relative + "/paper.json",
                        "parents": relative + "/parents.jsonl", "chunks": relative + "/chunks.jsonl",
                        "structure": relative + "/mineru/middle_json.json"},
                    "statistics": {"page_count": 2, "parent_count": 1, "source_block_count": 3,
                        "chunk_count": 2, "chunks_per_page": {"1": 1, "2": 1},
                        "max_chunk_tokens": max(chunk["token_count"] for chunk in structured_chunks)}}
        (folder / "paper.json").write_bytes(_json_bytes(paper, pretty=True))
        (folder / "version_manifest.json").write_bytes(_json_bytes(manifest, pretty=True))
        (folder / "parents.jsonl").write_text(json.dumps(parent) + "\n", encoding="utf-8")
        (folder / "chunks.jsonl").write_text("\n".join(json.dumps(chunk) for chunk in structured_chunks) + "\n", encoding="utf-8")
        structured = load_chunk_version(project_root, paper["paper_id"], revision)
        self.assertEqual(structured.parents, [parent])
        self.assertEqual(structured.chunks, structured_chunks)
        self.assertFalse(store.import_version(structured)["reused"])
        self.assertTrue(store.import_version(structured)["reused"])
        self.assertEqual(store.get_parent(parent_id), parent)
        self.assertEqual(store.get_version_parents(paper["paper_id"], revision), [parent])
        self.assertEqual(store.get_version_parents(paper["paper_id"], self.bundle.manifest["parse_revision"]), [])
        for expected in structured_chunks:
            actual = store.get_chunk(expected["chunk_id"])
            for key, value in expected.items():
                self.assertEqual(actual[key], value)
            self.assertTrue(all(key not in actual for key in
                ("segment_id", "char_start", "char_end", "source_line_indices", "segment_bbox")))
            row = store.connection.execute("SELECT segment_id, char_start, char_end, segment_bbox_json FROM chunks WHERE chunk_id = ?",
                                           (expected["chunk_id"],)).fetchone()
            self.assertEqual(tuple(row), (None, None, None, None))

        # Existing v1 data stays readable, and writable open upgrades without rewriting its records.
        legacy_path = project_root / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as legacy:
            for sql in storage.LEGACY_TABLE_SQL.values():
                legacy.execute(sql)
            legacy.execute(storage.INDEX_SQL)
            for sql in storage.LEGACY_TRIGGER_SQL.values():
                legacy.execute(sql)
            records = {"papers": [storage._paper_columns(self.bundle.paper)],
                       "parse_versions": [storage._version_columns(self.bundle, self.bundle.manifest)],
                       "chunks": [storage._chunk_columns(chunk) for chunk in self.bundle.chunks]}
            for table, rows in records.items():
                for values in rows:
                    columns = ", ".join(values)
                    parameters = ", ".join("?" for _ in values)
                    legacy.execute(f"INSERT INTO {table} ({columns}) VALUES ({parameters})", tuple(values.values()))
            legacy.execute("PRAGMA user_version = 1")
        legacy.close()
        with PaperStore(legacy_path, read_only=True) as legacy:
            self.assertEqual(legacy.get_chunk(self.bundle.chunks[0]["chunk_id"])["text"], self.bundle.chunks[0]["text"])
            self.assertEqual(legacy.get_version_parents(paper["paper_id"], self.bundle.manifest["parse_revision"]), [])
        with PaperStore(legacy_path) as upgraded:
            self.assertEqual(upgraded.connection.execute("PRAGMA user_version").fetchone()[0], storage.SCHEMA_VERSION)
            upgraded.import_version(structured)
            self.assertEqual(upgraded.get_parent(parent_id), parent)
            for expected in self.bundle.chunks:
                actual = upgraded.get_chunk(expected["chunk_id"])
                self.assertTrue(all(actual[key] == value for key, value in expected.items()))

    def test_repeated_import_reuses_version_without_growing_any_table(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        before = store.counts()
        for _ in range(3):
            result = store.import_version(self.bundle)
            self.assertTrue(result["reused"])
            self.assertEqual(result["inserted_chunks"], 0)
            self.assertEqual(result["chunk_count"], 2)
            self.assertEqual(store.counts(), before)

    def test_new_processing_version_keeps_old_ids_and_original_text(self) -> None:
        store = self.open_store()
        first = self.bundle
        second = storage_fixture(max_chars=1700)
        self.assertNotEqual(first.manifest["parse_revision"], second.manifest["parse_revision"])
        store.import_version(first)
        store.import_version(second)
        self.assert_counts(store, papers=1, versions=2, chunks=4)
        revisions = {row["parse_revision"] for row in store.list_versions()}
        self.assertEqual(revisions, {first.manifest["parse_revision"], second.manifest["parse_revision"]})
        for bundle in [first, second]:
            for expected in bundle.chunks:
                self.assertEqual(store.get_chunk(expected["chunk_id"])["text"], expected["text"])

    def test_same_paper_id_with_another_pdf_is_rejected(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        before = store.counts()
        with self.assertRaises(StorageConflict):
            store.import_version(storage_fixture(pdf_sha256="1" * 64))
        self.assertEqual(store.counts(), before)
        self.assertEqual(store.get_chunk(self.bundle.chunks[0]["chunk_id"])["pdf_sha256"], "a" * 64)

    def test_same_paper_id_with_another_source_is_rejected(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        before = store.counts()
        with self.assertRaises(StorageConflict):
            store.import_version(storage_fixture(source_url="https://arxiv.org/pdf/2005.11401v4"))
        self.assertEqual(store.counts(), before)

    def test_changed_content_cannot_overwrite_an_existing_version(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        paper = copy.deepcopy(self.bundle.paper)
        manifest = copy.deepcopy(self.bundle.manifest)
        chunks = copy.deepcopy(self.bundle.chunks)
        chunks[0]["text"] = "改写后的正文，不能冒充已保存的同一个版本。"
        chunks[0]["char_end"] = len(chunks[0]["text"])
        chunks[0]["text_sha256"] = _sha256(chunks[0]["text"].encode("utf-8"))
        _update_chunk_manifest(manifest, chunks, paper)
        changed = _bundle(paper, manifest, chunks)
        before = store.counts()
        with self.assertRaises((StorageConflict, StorageError)):
            store.import_version(changed)
        self.assertEqual(store.counts(), before)
        self.assertEqual(store.get_chunk(self.bundle.chunks[0]["chunk_id"])["text"], self.bundle.chunks[0]["text"])

    def test_failure_during_second_chunk_insert_rolls_back_the_whole_paper(self) -> None:
        store = self.open_store()
        second_id = self.bundle.chunks[1]["chunk_id"]
        # 故障发生在 SQL 写入过程，而不是输入检查阶段。第一块、论文、
        # 处理版本即使已经暂时写入，也必须随整个事务一起撤回。
        store.connection.execute(
            "CREATE TRIGGER test_fail_second_chunk BEFORE INSERT ON chunks "
            f"WHEN NEW.chunk_id = '{second_id}' "
            "BEGIN SELECT RAISE(ABORT, 'injected second chunk failure'); END"
        )
        store.connection.commit()
        with self.assertRaises((StorageError, sqlite3.DatabaseError)):
            store.import_version(self.bundle)
        self.assert_counts(store, papers=0, versions=0, chunks=0)
        self.assertIsNone(store.get_chunk(self.bundle.chunks[0]["chunk_id"]))
        # 去掉测试故障后能够重新完整导入，证明失败没有占用旧身份。
        store.connection.execute("DROP TRIGGER test_fail_second_chunk")
        store.connection.commit()
        self.assertEqual(store.import_version(self.bundle)["inserted_chunks"], 2)
        self.assert_counts(store, papers=1, versions=1, chunks=2)

    def test_foreign_key_rejects_chunk_without_a_paper_and_version(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        self.assertEqual(store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        cursor = store.connection.execute("SELECT * FROM chunks LIMIT 1")
        columns = [description[0] for description in cursor.description]
        record = dict(zip(columns, cursor.fetchone()))
        record["paper_id"] = "arxiv_9999.99999v4"
        record["chunk_id"] = f"{record['paper_id']}_{record['parse_revision']}_p1_c1"
        # 直接使用 SQL 绕过 Python 导入入口，检查数据库约束本身存在。
        # 列名来自本测试库的 schema；引号用于兼容合法的 SQLite 列名。
        names = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            with store.connection:
                store.connection.execute(
                    f"INSERT INTO chunks ({names}) VALUES ({placeholders})",
                    [record[column] for column in columns],
                )
        self.assert_counts(store, papers=1, versions=1, chunks=2)

    def test_sql_update_and_delete_cannot_destroy_saved_evidence(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        chunk_id = self.bundle.chunks[0]["chunk_id"]
        for statement, arguments in [
            ("UPDATE chunks SET text = ? WHERE chunk_id = ?", ("偷偷修改", chunk_id)),
            ("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,)),
        ]:
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    with store.connection:
                        store.connection.execute(statement, arguments)
        self.assertEqual(store.get_chunk(chunk_id)["text"], self.bundle.chunks[0]["text"])
        self.assert_counts(store, papers=1, versions=1, chunks=2)

    def test_read_only_open_of_a_missing_database_does_not_create_one(self) -> None:
        self.assertFalse(self.database_path.exists())
        with self.assertRaises((StorageError, sqlite3.DatabaseError)):
            self.open_store(read_only=True)
        self.assertFalse(self.database_path.exists())

    def test_closing_and_reopening_reads_persisted_text(self) -> None:
        store = self.open_store()
        store.import_version(self.bundle)
        store.connection.close()
        reopened = self.open_store(read_only=True)
        self.assert_counts(reopened, papers=1, versions=1, chunks=2)
        for expected in self.bundle.chunks:
            self.assertEqual(reopened.get_chunk(expected["chunk_id"])["text"], expected["text"])
        with self.assertRaises((StorageError, sqlite3.DatabaseError)):
            reopened.import_version(storage_fixture(max_chars=1700))
        self.assert_counts(reopened, papers=1, versions=1, chunks=2)

    def test_unknown_schema_is_rejected_without_rewriting_existing_data(self) -> None:
        connection = sqlite3.connect(self.database_path)
        connection.execute("CREATE TABLE unrelated (message TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated VALUES ('已有的其它程序数据')")
        connection.execute("PRAGMA user_version = 999")
        connection.commit()
        connection.close()
        before = self.database_path.read_bytes()
        with self.assertRaises((StorageError, sqlite3.DatabaseError)):
            self.open_store()
        self.assertEqual(self.database_path.read_bytes(), before)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT message FROM unrelated").fetchone()[0], "已有的其它程序数据")
        finally:
            connection.close()

    def test_unknown_chunk_id_returns_none(self) -> None:
        store = self.open_store()
        self.assertIsNone(store.get_chunk("not_a_saved_chunk"))
        store.import_version(self.bundle)
        self.assertIsNone(store.get_chunk("not_a_saved_chunk"))
        self.assert_counts(store, papers=1, versions=1, chunks=2)

    def test_incorrect_text_hash_is_rejected_before_any_rows_are_written(self) -> None:
        store = self.open_store()
        chunks = copy.deepcopy(self.bundle.chunks)
        chunks[1]["text_sha256"] = "2" * 64
        manifest = copy.deepcopy(self.bundle.manifest)
        _update_chunk_manifest(manifest, chunks, self.bundle.paper)
        with self.assertRaises((StorageError, StorageConflict)):
            store.import_version(_bundle(self.bundle.paper, manifest, chunks))
        self.assert_counts(store, papers=0, versions=0, chunks=0)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
