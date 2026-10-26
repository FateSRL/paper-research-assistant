"""D4 任务 D 的离线边界检查，只在系统临时目录中创建数据。

运行：python -X utf8 -m scripts.check_index

这里的 embedding 是固定的假函数，不读取 .env，不向供应商发请求。
SQLite 和 Qdrant 都使用临时目录，因此可以故意制造中断、错误来源和
坏向量，检查恢复行为，而不会影响正式论文、正式索引或消耗 API 额度。
"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from uuid import UUID, uuid4

from qdrant_client import models

from paper_assistant.config import EmbeddingSettings
from paper_assistant.embedding_client import EmbeddingAPIError, EmbeddingBatch
from paper_assistant.indexing import EmbeddingCache, IndexBuilder, IndexingError, digest, make_index_profile
from paper_assistant.retrieval import QdrantStore, VectorStoreError, point_id
from paper_assistant.storage import PaperStore, StorageError
from scripts.check_storage import storage_fixture


class FakeEmbedding:
    """可计数的假服务：相同文本总产生相同的有限、非零向量。

    用调用次数判断重跑是否重复生成文档向量，比只检查点数更可靠：
    Qdrant 的 upsert 即使重复收到向量也不会增加点数，但重复 API 请求
    仍会消耗额度。这个函数完全在本机计算，不调用正式 embedding 客户端。
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts, settings: EmbeddingSettings) -> EmbeddingBatch:
        self.calls.append(list(texts))
        dimension = settings.dimension
        if type(dimension) is not int or dimension <= 0:
            raise AssertionError("离线测试必须指定正整数维度")
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([1.0 + digest[index % len(digest)] / 255 for index in range(dimension)])
        return EmbeddingBatch(vectors=vectors, elapsed_seconds=0.01, total_tokens=len(texts) * 7)


class FailOnceAfterPartialUpsert:
    """第一次先写入一个点再报错，模拟向量库已经部分写入时进程中断。

    真实系统的 SQLite、缓存文件和 Qdrant 没有一个共享事务；不能假设
    报错就代表三处都没写入。第二次调用委托给真实临时 QdrantStore。
    """

    def __init__(self, wrapped: QdrantStore) -> None:
        self.wrapped = wrapped
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def upsert(self, chunks, vectors):
        if not self.failed:
            self.failed = True
            self.wrapped.upsert(chunks[:1], vectors[:1])
            raise RuntimeError("离线注入故障：部分 upsert 后中断")
        return self.wrapped.upsert(chunks, vectors)


class IndexChecks(unittest.TestCase):
    """每个检查使用独立的两块测试正文，不依赖正式索引当前状态。"""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="paper-index-check-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.resources = []
        # Windows 不允许删除仍打开的本地数据库文件；先关闭所有客户端，
        # 再让 TemporaryDirectory 删除它自己创建的目录。
        self.addCleanup(self._close_resources)
        self.settings = EmbeddingSettings(
            backend="dashscope", model="offline-embedding-test", api_key="offline-test-key",
            base_url="https://example.invalid/compatible-mode/v1", dimension=2,
        )
        self.profile = make_index_profile(self.settings)
        self.bundle = storage_fixture()
        self.paper_id = self.bundle.paper["paper_id"]
        self.revision = self.bundle.manifest["parse_revision"]
        self.store = PaperStore(self.root / "papers.sqlite3")
        self.resources.append(self.store)
        self.store.import_version(self.bundle)
        self.chunks = self.store.get_version_chunks(self.paper_id, self.revision)
        self.cache = EmbeddingCache(self.root / "embeddings", self.profile)
        self.fake = FakeEmbedding()

    def _close_resources(self) -> None:
        while self.resources:
            resource = self.resources.pop()
            if isinstance(resource, PaperStore):
                resource.connection.close()
            else:
                resource.close()

    def open_vectors(self, *, profile=None, path=None) -> QdrantStore:
        profile = profile or self.profile
        dimension = profile["recipe"]["dimension"]
        vectors = QdrantStore(
            path or self.root / "qdrant", profile["collection_name"],
            profile["index_profile_id"], dimension,
        )
        self.resources.append(vectors)
        return vectors

    def close_vectors(self, vectors: QdrantStore) -> None:
        vectors.close()
        self.resources.remove(vectors)

    def builder(self, vectors, *, embedder=None, cache=None, profile=None, settings=None):
        return IndexBuilder(
            self.store, vectors, cache or self.cache, settings or self.settings,
            profile or self.profile, embedder=embedder or self.fake,
        )

    def import_record(self) -> dict:
        return self.store.get_index_import(self.paper_id, self.revision, self.profile["index_profile_id"])

    def test_point_ids_are_stable_uuid5_and_isolate_index_profiles(self) -> None:
        chunk_id = self.chunks[0]["chunk_id"]
        first = point_id(self.profile["index_profile_id"], chunk_id)
        self.assertEqual(UUID(first).version, 5)
        self.assertEqual(first, point_id(self.profile["index_profile_id"], chunk_id))
        self.assertNotEqual(first, point_id("another-profile", chunk_id))
        self.assertNotEqual(first, point_id(self.profile["index_profile_id"], self.chunks[1]["chunk_id"]))
        # 不能用简单冒号拼接身份，否则含冒号的合法字符串可能碰撞。
        self.assertNotEqual(point_id("a:b", "c"), point_id("a", "b:c"))

    def test_profile_identity_ignores_secret_but_changes_with_model_or_dimension(self) -> None:
        other_key = make_index_profile(replace(self.settings, api_key="a-different-secret"))
        self.assertEqual(self.profile["index_profile_id"], other_key["index_profile_id"])
        self.assertEqual(self.profile["collection_name"], other_key["collection_name"])
        self.assertNotIn("offline-test-key", repr(self.profile))
        for changed in [replace(self.settings, model="another-model"), replace(self.settings, dimension=3)]:
            with self.subTest(settings=changed):
                profile = make_index_profile(changed)
                self.assertNotEqual(self.profile["index_profile_id"], profile["index_profile_id"])
                self.assertNotEqual(self.profile["collection_name"], profile["collection_name"])

    def test_upsert_rejects_mismatched_count_dimension_nonfinite_and_zero_before_write(self) -> None:
        vectors = self.open_vectors()
        invalid = [
            [[1.0, 2.0]],  # 只有一个向量，却有两个 chunk。
            [[1.0], [1.0, 2.0]],
            [[float("nan"), 1.0], [1.0, 2.0]],
            [[1.0, float("inf")], [1.0, 2.0]],
            [[0.0, 0.0], [1.0, 2.0]],
            [[True, 1.0], [1.0, 2.0]],
        ]
        for batch in invalid:
            with self.subTest(batch=batch):
                with self.assertRaises(VectorStoreError):
                    vectors.upsert(self.chunks, batch)
                self.assertEqual(vectors.collection_count(), 0)

    def test_local_qdrant_persists_and_repeated_upsert_does_not_duplicate(self) -> None:
        vectors = self.open_vectors()
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        vectors.upsert(self.chunks, batch.vectors)
        vectors.upsert(self.chunks, batch.vectors)
        self.assertEqual(vectors.collection_count(), len(self.chunks))
        self.close_vectors(vectors)
        reopened = self.open_vectors()
        checked = reopened.validate(self.chunks)
        self.assertEqual(checked["verified_count"], len(self.chunks))
        self.assertEqual(reopened.completed_chunk_ids(self.chunks), {chunk["chunk_id"] for chunk in self.chunks})

    def test_existing_collection_rejects_another_dimension(self) -> None:
        vectors = self.open_vectors()
        self.close_vectors(vectors)
        with self.assertRaises(VectorStoreError):
            QdrantStore(self.root / "qdrant", self.profile["collection_name"], self.profile["index_profile_id"], 3)

    def test_full_validation_rejects_missing_point(self) -> None:
        vectors = self.open_vectors()
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        vectors.upsert(self.chunks[:1], batch.vectors[:1])
        self.assertEqual(vectors.completed_chunk_ids(self.chunks), {self.chunks[0]["chunk_id"]})
        with self.assertRaises(VectorStoreError):
            vectors.validate(self.chunks)

    def test_full_validation_rejects_extra_point_in_same_paper_version(self) -> None:
        vectors = self.open_vectors()
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        vectors.upsert(self.chunks, batch.vectors)
        original = vectors.client.retrieve(
            vectors.collection_name, [point_id(self.profile["index_profile_id"], self.chunks[0]["chunk_id"])],
            with_payload=True, with_vectors=True,
        )[0]
        # 同一论文版本混入任意额外 ID，即使 payload 声称属于其它 profile，
        # 也应使完整性检查失败，而不是被过滤条件悄悄隐藏。
        payload = dict(original.payload)
        payload["index_profile_id"] = "wrong-profile"
        vectors.client.upsert(
            collection_name=vectors.collection_name,
            points=[models.PointStruct(id=str(uuid4()), vector=original.vector, payload=payload)], wait=True,
        )
        with self.assertRaises(VectorStoreError):
            vectors.validate(self.chunks)

    def test_existing_point_with_wrong_source_hash_is_not_completed(self) -> None:
        vectors = self.open_vectors()
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        vectors.upsert(self.chunks, batch.vectors)
        identifier = point_id(self.profile["index_profile_id"], self.chunks[0]["chunk_id"])
        record = vectors.client.retrieve(vectors.collection_name, [identifier], with_payload=True, with_vectors=True)[0]
        payload = dict(record.payload)
        payload["text_sha256"] = "9" * 64
        vectors.client.upsert(
            collection_name=vectors.collection_name,
            points=[models.PointStruct(id=identifier, vector=record.vector, payload=payload)], wait=True,
        )
        with self.assertRaises(VectorStoreError):
            vectors.completed_chunk_ids(self.chunks)
        with self.assertRaises(VectorStoreError):
            vectors.validate(self.chunks)

    def test_correct_payload_with_wrong_vector_direction_is_rejected(self) -> None:
        vectors = self.open_vectors()
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        vectors.upsert(self.chunks, batch.vectors)
        vectors.validate(self.chunks, vectors=batch.vectors)
        identifier = point_id(self.profile["index_profile_id"], self.chunks[0]["chunk_id"])
        record = vectors.client.retrieve(vectors.collection_name, [identifier], with_payload=True, with_vectors=True)[0]
        # 字段和点数都正确，只有向量被误换成相反方向。完整性核对要能
        # 与缓存中的服务原始响应比较，不能仅证明向量长度是正确的。
        vectors.client.upsert(
            collection_name=vectors.collection_name,
            points=[models.PointStruct(id=identifier, vector=[-value for value in record.vector], payload=record.payload)],
            wait=True,
        )
        with self.assertRaises(VectorStoreError):
            vectors.validate(self.chunks, vectors=batch.vectors)

    def test_cache_roundtrip_preserves_vectors_without_exposing_secrets(self) -> None:
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        self.cache.save_batch(self.chunks, batch)
        reopened = EmbeddingCache(self.root / "embeddings", self.profile)
        for chunk, vector in zip(self.chunks, batch.vectors, strict=True):
            self.assertEqual(reopened.load(chunk), vector)
        for path in (self.root / "embeddings").rglob("*.json"):
            self.assertNotIn("offline-test-key", path.read_text(encoding="utf-8"))

    def test_cache_isolated_by_model_and_dimension(self) -> None:
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        self.cache.save_batch(self.chunks, batch)
        changed = make_index_profile(replace(self.settings, model="another-model"))
        another_cache = EmbeddingCache(self.root / "embeddings", changed)
        self.assertIsNone(another_cache.load(self.chunks[0]))

    def test_corrupted_cache_hash_is_rejected_without_new_embedding_request(self) -> None:
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        self.cache.save_batch(self.chunks, batch)
        path = next((self.root / "embeddings").rglob("b_*.json"))
        wrapped = json.loads(path.read_text(encoding="utf-8"))
        wrapped["batch"]["records"][0]["vector"][0] += 1.0
        # 故意只改内容、不改原始校验和，模拟文件损坏。检测损坏后应明确
        # 失败；不能把它当“缓存不存在”，接着重新请求一批付费向量。
        path.write_text(json.dumps(wrapped, ensure_ascii=False), encoding="utf-8")
        calls_before = len(self.fake.calls)
        with self.assertRaises(IndexingError):
            reopened = EmbeddingCache(self.root / "embeddings", self.profile)
            self.builder(self.open_vectors(), cache=reopened).import_version(self.paper_id, self.revision)
        self.assertEqual(len(self.fake.calls), calls_before)
        self.assertEqual(self.store.list_index_imports(), [])

    def test_cache_rejects_zero_vector_even_if_file_hash_was_recomputed(self) -> None:
        batch = self.fake([chunk["text"] for chunk in self.chunks], self.settings)
        self.cache.save_batch(self.chunks, batch)
        path = next((self.root / "embeddings").rglob("b_*.json"))
        wrapped = json.loads(path.read_text(encoding="utf-8"))
        wrapped["batch"]["records"][0]["vector"] = [0.0, 0.0]
        wrapped["sha256"] = digest(wrapped["batch"])
        path.write_text(json.dumps(wrapped, ensure_ascii=False), encoding="utf-8")
        calls_before = len(self.fake.calls)
        # SHA 只能证明文件内部一致，不能证明内容适合做 cosine 索引。
        # 因此读取缓存仍需要检查数值本身，防止全零向量进入正式库。
        with self.assertRaises(IndexingError):
            EmbeddingCache(self.root / "embeddings", self.profile)
        self.assertEqual(len(self.fake.calls), calls_before)

    def test_cache_rejects_invalid_batch_and_does_not_save_any_entry(self) -> None:
        for invalid in [
            [[1.0, 2.0]],
            [[1.0], [1.0, 2.0]],
            [[float("nan"), 1.0], [1.0, 2.0]],
            [[0.0, 0.0], [1.0, 2.0]],
        ]:
            with self.subTest(vectors=invalid):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.cache.save_batch(self.chunks, EmbeddingBatch(invalid, 0.01, 7))
                self.assertTrue(all(self.cache.load(chunk) is None for chunk in self.chunks))

    def test_cache_rejects_empty_or_duplicate_inputs_before_writing_a_file(self) -> None:
        # 一个无效调用不能留下“本次报错、以后每次读缓存都报错”的坏文件。
        # 所以不仅要抛异常，还要证明缓存目录中没有新增批次文件。
        for chunks, batch in [
            ([], EmbeddingBatch([], 0.01, 0)),
            ([self.chunks[0], self.chunks[0]], EmbeddingBatch([[1.0, 2.0], [1.0, 2.0]], 0.01, 14)),
        ]:
            with self.subTest(chunk_count=len(chunks)):
                with self.assertRaises(IndexingError):
                    self.cache.save_batch(chunks, batch)
                self.assertEqual(list((self.root / "embeddings").rglob("b_*.json")), [])

    def test_successful_import_and_repeat_make_no_second_embedding_request(self) -> None:
        vectors = self.open_vectors()
        self.builder(vectors).import_version(self.paper_id, self.revision, batch_size=10)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.import_record()["status"], "ready")
        self.assertEqual(self.import_record()["completed_count"], len(self.chunks))
        vectors.validate(self.chunks)
        # 关闭再新建客户端和缓存对象，排除“仅保存在当前 Python 对象中”
        # 的假幂等；新实例仍应直接复用磁盘中已经完成的文档向量。
        self.close_vectors(vectors)
        vectors = self.open_vectors()
        reopened_cache = EmbeddingCache(self.root / "embeddings", self.profile)
        self.builder(vectors, cache=reopened_cache).import_version(self.paper_id, self.revision, batch_size=10)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(vectors.collection_count(), len(self.chunks))
        self.assertEqual(len(self.store.list_index_imports()), 1)

        # 上传路径使用真实临时 PDF，embedding 仍为离线假服务。
        import httpx
        import pymupdf
        from paper_assistant import import_runtime
        from paper_assistant.citations import _checked_source
        from paper_assistant.quality import SUPPORTED_AUTOMATIC_RULES
        from paper_assistant.source_scope import Registry

        upload_root = self.root / "local-upload"
        (upload_root / "eval").mkdir(parents=True)
        rules = {"rules_revision": "d3-quality-rules-v1", "automatic_rules": SUPPORTED_AUTOMATIC_RULES,
                 "region_rules": []}
        (upload_root / "eval/quality_rules.json").write_text(json.dumps(rules), encoding="utf-8")
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Abstract\nA local PDF preserves its evidence and import identity.\n"
                             "1 Introduction\nIts body remains separate from the abstract.")
            for number in range(12):
                page = document.new_page()
                page.insert_text((72, 160), "Independent body passage " + str(number)
                                 + " describes a separate local research observation.")
            pdf_bytes = document.tobytes()
        attempts = []
        fake = FakeEmbedding()
        events = []
        clients, request_clients = [], []
        actual_client = httpx.Client

        def unexpected_http(request):
            self.fail("离线假 embedding 不应发送 HTTP 请求")

        def create_client(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            self.assertFalse(kwargs["follow_redirects"])
            client = actual_client(*args, **kwargs, transport=httpx.MockTransport(unexpected_http))
            clients.append(client)
            return client

        def fail_once(texts, settings, *, http_client):
            self.assertIsInstance(http_client, actual_client)
            self.assertFalse(http_client.is_closed)
            request_clients.append(http_client)
            attempts.append(list(texts))
            if len(attempts) == 2:
                raise EmbeddingAPIError("离线模拟第二批 embedding 失败")
            return fake(texts, settings)

        with mock.patch.object(import_runtime, "load_current_profile", return_value=self.profile), \
                mock.patch.object(import_runtime, "load_embedding_settings", return_value=self.settings), \
                mock.patch.object(import_runtime, "embed_texts", side_effect=fail_once), \
                mock.patch.object(import_runtime.httpx, "Client", side_effect=create_client):
            failed = import_runtime.import_pdf(pdf_bytes, "Local paper.pdf", project_root=upload_root,
                                               on_progress=events.append, parser="legacy")
            self.assertEqual(failed["status"], "failed", failed)
            self.assertEqual(failed["stage"], "index")
            self.assertGreater(failed["chunk_count"], 10)
            self.assertLessEqual(failed["chunk_count"], 20)
            self.assertEqual(failed["embedding_requests"], 2)
            self.assertEqual(len(clients), 1)
            self.assertIs(request_clients[0], clients[0])
            self.assertIs(request_clients[1], clients[0])
            self.assertTrue(clients[0].is_closed)
            self.assertEqual(failed["completed_count"], 10)
            self.assertEqual(failed["upserted_count"], 10)
            self.assertEqual(failed["generated_count"], 10)
            self.assertEqual(failed["cached_reused_count"], 0)
            self.assertEqual(failed["cache_statistics"]["vector_count"], 10)
            self.assertEqual(failed["request_statistics"]["cached_response_requests"], 1)
            self.assertEqual(failed["request_statistics"]["failed_requests"], 1)
            self.assertEqual(failed["request_statistics"]["known_total_tokens"], 70)
            self.assertEqual(failed["request_statistics"]["usage_missing_requests"], 1)
            self.assertIsNone(failed["request_statistics"]["total_tokens"])
            folder = upload_root / "data/chunks" / failed["paper_id"] / failed["parse_revision"]
            original_manifest = (folder / "version_manifest.json").read_bytes()
            manifest = json.loads(original_manifest)
            self.assertNotIn("files", manifest)
            self.assertNotIn("processing_source_sha256", manifest["recipe"])
            self.assertFalse((folder / "pipeline").exists())
            with PaperStore(upload_root / "data/index/papers.sqlite3", read_only=True) as stored:
                state = stored.get_index_import(failed["paper_id"], failed["parse_revision"], self.profile["index_profile_id"])
                self.assertEqual(state["status"], "failed")
                self.assertEqual(state["completed_count"], 10)

            with mock.patch.object(import_runtime, "parse_pdf_pages", side_effect=AssertionError("重复上传不重解析")):
                ready = import_runtime.import_pdf(pdf_bytes, "Renamed paper.pdf", title="Changed title",
                                                  project_root=upload_root, on_progress=events.append, parser="legacy")
                repeated = import_runtime.import_pdf(pdf_bytes, "Renamed again.pdf", project_root=upload_root,
                                                     parser="legacy")
            self.assertEqual(ready["status"], "ready", ready)
            self.assertEqual(repeated["status"], "ready", repeated)
            self.assertEqual(ready["paper_id"], failed["paper_id"])
            self.assertEqual(repeated["parse_revision"], failed["parse_revision"])
            self.assertEqual(ready["title"], "Local paper")
            remaining = ready["chunk_count"] - 10
            self.assertEqual(ready["embedding_requests"], 1)
            self.assertEqual(ready["generated_count"], remaining)
            self.assertEqual(ready["upserted_count"], remaining)
            self.assertEqual(ready["completed_count"], ready["chunk_count"])
            self.assertEqual(ready["cached_reused_count"], 0)
            self.assertFalse(ready["reused_ready"])
            self.assertEqual(ready["request_statistics"]["total_tokens"], remaining * 7)
            self.assertEqual(ready["request_statistics"]["usage_missing_requests"], 0)
            self.assertEqual(repeated["embedding_requests"], 0)
            self.assertEqual(repeated["generated_count"], 0)
            self.assertEqual(repeated["upserted_count"], 0)
            self.assertTrue(repeated["reused_ready"])
            self.assertEqual(repeated["request_statistics"]["request_elapsed_seconds"], 0)
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(len(clients), 3)
            self.assertIs(request_clients[2], clients[1])
            self.assertEqual(len(request_clients), 3)
            self.assertTrue(all(client.is_closed for client in clients))
            self.assertEqual(len(attempts[0]), 10)
            self.assertEqual(attempts[1], attempts[2])
            self.assertEqual(fake.calls[0], attempts[0])
            self.assertEqual(fake.calls[1], attempts[2])
            for imported in (failed, ready, repeated):
                timings = imported["stage_timings_seconds"]
                self.assertEqual(set(timings), {"parse", "filter", "chunk", "store", "index", "preparation"})
                self.assertTrue(all(seconds >= 0 for seconds in timings.values()))
                self.assertGreaterEqual(imported["elapsed_seconds"], timings["index"])
                self.assertGreaterEqual(imported["elapsed_seconds"], timings["preparation"])
                self.assertAlmostEqual(timings["preparation"],
                    sum(timings[stage] for stage in ("parse", "filter", "chunk", "store")), places=5)
            self.assertEqual(ready["stage_timings_seconds"]["filter"], 0)
            self.assertEqual(ready["stage_timings_seconds"]["chunk"], 0)
            self.assertEqual(ready["stage_timings_seconds"]["store"], 0)
            self.assertEqual(repeated["cache_statistics"]["vector_count"], ready["chunk_count"])
            self.assertEqual((folder / "version_manifest.json").read_bytes(), original_manifest)
            self.assertTrue(any(event["stage"] == "batch_upserted" for event in events))
            self.assertEqual(events[-1]["stage"], "ready")
            self.assertEqual(events[-1]["embedding_requests"], 1)
            self.assertEqual(events[-1]["generated_count"], remaining)
            self.assertIn("elapsed_seconds", events[-1])
            self.assertIn("stage_timings_seconds", events[-1])
            self.assertEqual(len([event for event in events if event["stage"] == "request_finished"]), 3)
            with PaperStore(upload_root / "data/index/papers.sqlite3", read_only=True) as stored:
                registry = Registry(upload_root, stored, [(ready["paper_id"], ready["parse_revision"])])
                abstract_ids = registry.qualified_chunk_ids()
                self.assertEqual(len(abstract_ids), 1)
                chunk = stored.get_chunk(abstract_ids[0])
                self.assertEqual(chunk["text"], "A local PDF preserves its evidence and import identity.")
                shown = {**chunk, "shown_text": chunk["text"], "shown_text_sha256": chunk["text_sha256"]}
                source = _checked_source(chunk, shown, upload_root, {})
                self.assertEqual(source["arxiv_version"], "")
                self.assertEqual(source["source_url"], "")
                self.assertEqual(source["text"], chunk["text"])

        from paper_assistant import structured_ingest
        from paper_assistant.chunk_snapshot import load_chunk_version
        parsed = {"schema": "docvortex.middle", "schema_version": "2.0", "extensions": {
            "docvortex_layout": {"pages": [{"page_idx": 0, "width_pt": 600, "height_pt": 800},
                                             {"page_idx": 1, "width_pt": 600, "height_pt": 800}]}},
            "pages": [{"page_idx": 0, "blocks": [
                {"type": "paragraph_title", "level": 2, "bbox": [0.1, 0.1, 0.4, 0.15],
                 "content": [{"type": "text", "content": "Abstract"}]},
                {"type": "text", "bbox": [0.1, 0.2, 0.45, 0.4],
                 "content": [{"type": "text", "content": "A structured paragraph preserves its first physical source."}]},
                {"type": "text", "bbox": [0.55, 0.03, 0.9, 0.06],
                 "content": [{"type": "text", "content": "AUTHOR_EMAIL_ONLY@example.invalid"}]},
                {"type": "equation", "bbox": [0.1, 0.41, 0.45, 0.5], "content": r"h_t=Wx_t"}]},
                {"page_idx": 1, "blocks": [{"type": "text", "continues_prev": True,
                 "bbox": [0.55, 0.1, 0.9, 0.3], "content": [{"type": "text", "content":
                 "The continuation retains a separate page and a separate source rectangle."}]}]}]}

        def saved_parse(pdf_path, output_dir, *, project_root):
            self.assertEqual(project_root, upload_root)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "middle_json.json").write_text(json.dumps(parsed), encoding="utf-8")
            return deepcopy(parsed)

        with mock.patch.object(import_runtime, "load_current_profile", return_value=self.profile), \
                mock.patch.object(import_runtime, "load_embedding_settings", return_value=self.settings), \
                mock.patch.object(import_runtime, "embed_texts", side_effect=fail_once), \
                mock.patch.object(import_runtime.httpx, "Client", side_effect=create_client), \
                mock.patch.object(structured_ingest, "parse_structured_pdf", side_effect=saved_parse) as parser_call, \
                mock.patch.object(structured_ingest, "load_token_counter", return_value=lambda text: len(text.split())):
            # A prior Advanced version must not supply the new Standard parse or ready state.
            advanced_parser = {**structured_ingest.PARSER, "tier": "advanced", "image_analysis": True}
            with mock.patch.object(structured_ingest, "PARSER", advanced_parser):
                advanced = import_runtime.import_pdf(pdf_bytes, "Prior Advanced.pdf", project_root=upload_root)
            self.assertEqual(advanced["status"], "ready", advanced)
            structured = import_runtime.import_pdf(pdf_bytes, "Same PDF.pdf", project_root=upload_root)
            self.assertEqual(structured["status"], "ready", structured)
            self.assertEqual(structured["paper_id"], ready["paper_id"])
            self.assertNotEqual(structured["parse_revision"], ready["parse_revision"])
            self.assertNotEqual(structured["parse_revision"], advanced["parse_revision"])
            self.assertEqual(structured["parser"]["tier"], "standard")
            self.assertFalse(structured["parser"]["image_analysis"])
            self.assertFalse(structured.get("reused_parse", False))
            self.assertFalse(structured["reused_ready"])
            self.assertGreater(structured["embedding_requests"], 0)
            same_scheme = import_runtime.import_pdf(pdf_bytes, "Same again.pdf", project_root=upload_root,
                                                   parser="mineru-standard")
            self.assertEqual(same_scheme["status"], "ready", same_scheme)
            self.assertEqual(same_scheme["parse_revision"], structured["parse_revision"])
            self.assertTrue(same_scheme["reused_ready"])
            self.assertEqual(same_scheme["embedding_requests"], 0)
            self.assertEqual(parser_call.call_count, 2)
        with PaperStore(upload_root / "data/index/papers.sqlite3", read_only=True) as stored:
            self.assertTrue(stored.get_version_chunks(ready["paper_id"], ready["parse_revision"]))
            self.assertTrue(stored.get_version_chunks(advanced["paper_id"], advanced["parse_revision"]))
            children = stored.get_version_chunks(structured["paper_id"], structured["parse_revision"])
            self.assertTrue(all(child["source_spans"] for child in children))
            self.assertTrue(all("segment_id" not in child for child in children))
            self.assertFalse(any("AUTHOR_EMAIL_ONLY" in child["text"] for child in children))
            parents = stored.get_version_parents(structured["paper_id"], structured["parse_revision"])
            self.assertTrue(parents)
        loaded = load_chunk_version(upload_root, structured["paper_id"], structured["parse_revision"])
        self.assertEqual(loaded.parents, parents)
        self.assertEqual([row["chunk_id"] for row in loaded.chunks], [row["chunk_id"] for row in children])

    def test_builder_rejects_settings_for_another_model_before_request(self) -> None:
        vectors = self.open_vectors()
        with self.assertRaises((ValueError, RuntimeError)):
            self.builder(vectors, settings=replace(self.settings, model="another-model")).import_version(
                self.paper_id, self.revision,
            )
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(vectors.collection_count(), 0)

    def test_smoke_uses_separate_collection_and_never_marks_formal_import_ready(self) -> None:
        vectors = self.open_vectors()
        builder = self.builder(vectors)
        chunks = (
            self.chunks
            + storage_fixture(max_chars=1700).chunks
            + storage_fixture(max_chars=1800).chunks
        )
        result = builder.smoke(chunks)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_count"], 6)
        self.assertFalse(result["formal_import_marked_ready"])
        self.assertNotEqual(result["temporary_collection"], vectors.collection_name)
        self.assertFalse(vectors.client.collection_exists(result["temporary_collection"]))
        self.assertEqual(vectors.collection_count(), 0)
        self.assertEqual(self.store.list_index_imports(), [])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertTrue(all(self.cache.load(chunk) is not None for chunk in chunks))
        # smoke 成功的六条响应可以被再次复用；正式 collection 的 owner
        # 客户端必须仍然可用，不能因关闭借用它的试验 collection 而被关闭。
        builder.smoke(chunks)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(vectors.collection_count(), 0)

    def test_smoke_rejects_too_small_input_before_any_embedding_request(self) -> None:
        vectors = self.open_vectors()
        with self.assertRaises(IndexingError):
            self.builder(vectors).smoke(self.chunks)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(vectors.collection_count(), 0)
        self.assertEqual(self.store.list_index_imports(), [])

    def test_upsert_failure_retains_cache_and_retry_reuses_same_import_key(self) -> None:
        vectors = self.open_vectors()
        failing = FailOnceAfterPartialUpsert(vectors)
        try:
            self.builder(failing).import_version(self.paper_id, self.revision, batch_size=10)
        except (RuntimeError, ValueError):
            pass
        failed = self.import_record()
        self.assertIsNotNone(failed)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(vectors.collection_count(), 1)
        # API 已经返回的一整批必须先落盘。即使向量库只写入一块，重试
        # 剩余块也直接读取缓存，不再次调用 paid embedding。
        self.assertTrue(all(self.cache.load(chunk) is not None for chunk in self.chunks))
        self.builder(vectors).import_version(self.paper_id, self.revision, batch_size=10)
        ready = self.import_record()
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["import_key"], failed["import_key"])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(len(self.store.list_index_imports()), 1)
        vectors.validate(self.chunks)

    def test_embedding_failure_is_failed_and_never_claims_ready(self) -> None:
        vectors = self.open_vectors()

        def unavailable(_texts, _settings):
            raise EmbeddingAPIError("离线注入故障：供应商不可用")

        try:
            self.builder(vectors, embedder=unavailable).import_version(self.paper_id, self.revision)
        except (RuntimeError, ValueError):
            pass
        record = self.import_record()
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["completed_count"], 0)
        self.assertEqual(vectors.collection_count(), 0)
        self.assertEqual(self.store.list_index_imports(status="ready"), [])

    def test_ready_record_does_not_hide_lost_qdrant_points(self) -> None:
        vectors = self.open_vectors()
        builder = self.builder(vectors)
        builder.import_version(self.paper_id, self.revision)
        identifier = point_id(self.profile["index_profile_id"], self.chunks[1]["chunk_id"])
        vectors.client.delete(
            collection_name=vectors.collection_name,
            points_selector=models.PointIdsList(points=[identifier]), wait=True,
        )
        # ready 是过去的成功状态，重跑仍须核对现有库。已知丢失一个点
        # 时应先明确失败并取消 ready，后续再从缓存恢复正式入库。
        with self.assertRaises((RuntimeError, ValueError)):
            builder.import_version(self.paper_id, self.revision)
        self.assertEqual(self.import_record()["status"], "failed")
        self.assertEqual(len(self.fake.calls), 1)
        builder.import_version(self.paper_id, self.revision)
        vectors.validate(self.chunks)
        self.assertEqual(self.import_record()["status"], "ready")
        self.assertEqual(len(self.fake.calls), 1)

    def test_ready_wrong_vector_direction_becomes_failed_without_new_request(self) -> None:
        vectors = self.open_vectors()
        builder = self.builder(vectors)
        builder.import_version(self.paper_id, self.revision)
        identifier = point_id(self.profile["index_profile_id"], self.chunks[1]["chunk_id"])
        record = vectors.client.retrieve(vectors.collection_name, [identifier], with_payload=True, with_vectors=True)[0]
        vectors.client.upsert(
            collection_name=vectors.collection_name,
            points=[models.PointStruct(id=identifier, vector=[-value for value in record.vector], payload=record.payload)],
            wait=True,
        )
        with self.assertRaises(VectorStoreError):
            builder.import_version(self.paper_id, self.revision)
        self.assertEqual(self.import_record()["status"], "failed")
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(len(self.store.list_index_imports()), 1)

    def test_count_constraints_and_state_transitions(self) -> None:
        profile_id = self.profile["index_profile_id"]
        row = self.store.begin_index_import(self.paper_id, self.revision, profile_id)
        key = row["import_key"]
        self.assertEqual(row["status"], "pending")
        for bad_count in [-1, 3, True, 1.5]:
            with self.subTest(count=bad_count):
                with self.assertRaises(StorageError):
                    self.store.set_index_import_progress(key, bad_count)
        self.store.set_index_import_progress(key, 1)
        with self.assertRaises(StorageError):
            self.store.set_index_import_progress(key, 0)
        with self.assertRaises(StorageError):
            self.store.finish_index_import(key, 1)
        self.assertEqual(self.import_record()["status"], "pending")
        self.store.fail_index_import(key, "离线检查失败", completed_count=1)
        self.assertEqual(self.import_record()["status"], "failed")
        retry = self.store.begin_index_import(self.paper_id, self.revision, profile_id, completed_count=1)
        self.assertEqual(retry["import_key"], key)
        self.store.set_index_import_progress(key, 2)
        self.store.finish_index_import(key, 2)
        self.assertEqual(self.import_record()["status"], "ready")
        self.assertEqual(self.import_record()["completed_count"], 2)

    def test_unknown_processing_version_cannot_create_import_state(self) -> None:
        with self.assertRaises(StorageError):
            self.store.begin_index_import(self.paper_id, "r_0123456789abcdef", self.profile["index_profile_id"])
        self.assertEqual(self.store.counts()["index_imports"], 0)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
