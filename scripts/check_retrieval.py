"""D4 任务 E 的离线检索边界检查。

运行：python -X utf8 -m scripts.check_retrieval

所有论文、SQLite 和 Qdrant 数据都在 TemporaryDirectory 内创建。向量服务
使用可计数的本地假函数，不读取 .env，不请求网络，不打开正式索引。
这里检查的是可观察的检索行为，而不是让假模型回答真实题集。
"""

import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from qdrant_client import models

from paper_assistant import config
from paper_assistant.config import EmbeddingSettings, RerankSettings
from paper_assistant.embedding_client import EmbeddingAPIError, EmbeddingBatch, LegacyEmbedderAdapter
from paper_assistant.indexing import atomic_json, make_index_profile
from paper_assistant.retrieval import QdrantStore, point_id
from paper_assistant.search import EvidenceSearcher, SearchError
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.storage import PaperStore, StoredVersionInput
from scripts.check_storage import (
    _bundle, _json_bytes, _sha256, _update_chunk_manifest, storage_fixture,
)


def another_paper_fixture() -> StoredVersionInput:
    """沿用已通过存储检查的格式，造第二篇论文并重新计算全部身份。

    不能只替换 paper_id：它参与 recipe 哈希、处理版本、块 ID 和来源字段。
    测试中的修改也遵守正式快照约定，避免在不相关的存储检查处提前失败。
    """
    source = storage_fixture()
    paper = copy.deepcopy(source.paper)
    manifest = copy.deepcopy(source.manifest)
    chunks = copy.deepcopy(source.chunks)
    paper.update(
        paper_id="arxiv_2210.03629v3", arxiv_version="v3", title="第二篇离线检索论文",
        source_url="https://arxiv.org/abs/2210.03629v3",
        local_path="data/papers/2210.03629v3.pdf", pdf_sha256="2" * 64,
    )
    recipe = manifest["recipe"]
    recipe.update(paper_id=paper["paper_id"], pdf_sha256=paper["pdf_sha256"],
                  paper_metadata_sha256=_sha256(_json_bytes(paper, pretty=True)))
    recipe_hash = _sha256(_json_bytes(recipe))
    revision = "r_" + recipe_hash[:16]
    manifest.update(paper_id=paper["paper_id"], parse_revision=revision,
                    recipe_sha256=recipe_hash)
    manifest["source_paths"].update(
        pdf=paper["local_path"], raw=f"data/parsed/{paper['paper_id']}.jsonl",
        filtered=f"data/filtered/{paper['paper_id']}.jsonl",
    )
    manifest["files"]["paper.json"] = {
        "sha256": recipe["paper_metadata_sha256"], "bytes": len(_json_bytes(paper, pretty=True)),
    }
    for chunk in chunks:
        chunk.update(
            chunk_id=f"{paper['paper_id']}_{revision}_p{chunk['pdf_page']}_c1",
            paper_id=paper["paper_id"], parse_revision=revision, pdf_sha256=paper["pdf_sha256"],
            segment_id=f"{paper['paper_id']}:p{chunk['pdf_page']}:b0:l0-1:{chunk['text_sha256'][:12]}",
        )
    _update_chunk_manifest(manifest, chunks, paper)
    return _bundle(paper, manifest, chunks)


class DirectionEmbedding:
    """固定两个方向，使检索排序能独立于远程模型重复验证。

    问题和第一页都指向 [1, 0]，第二页指向 [0, 1]；因此第一页必须更相似。
    calls 记录每次传入文本，能证明问题只请求一次、正文没有重新生成向量。
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts, _settings) -> EmbeddingBatch:
        self.calls.append(list(texts))
        vectors = [[0.0, 1.0] if "第二块" in text else [1.0, 0.0] for text in texts]
        return EmbeddingBatch(vectors, 0.01, len(texts) * 7)


class RetrievalChecks(unittest.TestCase):
    """每项检查都建立三份独立、完整、ready 的小型索引版本。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-retrieval-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.resources = []
        self.addCleanup(self.close_resources)
        self.settings = EmbeddingSettings(
            backend="dashscope", model="offline-search-test", api_key="offline-test-key",
            base_url="https://example.invalid/compatible-mode/v1", dimension=2,
        )
        self.profile = make_index_profile(self.settings)
        self.database_path = self.root / "papers.sqlite3"
        self.writer = PaperStore(self.database_path)
        self.resources.append(self.writer)
        self.vectors = QdrantStore(
            self.root / "qdrant", self.profile["collection_name"],
            self.profile["index_profile_id"], 2,
        )
        self.resources.append(self.vectors)
        self.bundles = [storage_fixture(), storage_fixture(max_chars=1700), another_paper_fixture()]
        self.pairs = [(bundle.paper["paper_id"], bundle.manifest["parse_revision"])
                      for bundle in self.bundles]
        self.all_chunks = []
        fixture_embedding = DirectionEmbedding()
        for bundle, pair in zip(self.bundles, self.pairs, strict=True):
            self.writer.import_version(bundle)
            chunks = self.writer.get_version_chunks(*pair)
            self.all_chunks.extend(chunks)
            self.vectors.upsert(chunks, fixture_embedding([c["text"] for c in chunks], self.settings).vectors)
            # 只有实际完成向量核对后才将临时状态写成 ready。
            self.vectors.validate(chunks)
            row = self.writer.begin_index_import(*pair, self.profile["index_profile_id"])
            self.writer.finish_index_import(row["import_key"], len(chunks))
        self.reader = PaperStore(self.database_path, read_only=True)
        self.resources.append(self.reader)
        self.embedding = DirectionEmbedding()

    def close_resources(self) -> None:
        while self.resources:
            self.resources.pop().close()

    def searcher(self, *, embedder=None, settings=None, profile=None) -> EvidenceSearcher:
        return EvidenceSearcher(
            self.reader, self.vectors, settings or self.settings, profile or self.profile,
            embedder=embedder or self.embedding,
        )

    def search(self, pairs=None, **kwargs) -> dict:
        return self.searcher().search_evidence("检索第一块", pairs or [self.pairs[0]], **kwargs)

    def actual_hits(self) -> list:
        """取真实临时 Qdrant 的结果作为故障注入素材，不接触正式库。"""
        from paper_assistant.retrieval import filter_for_versions
        return self.vectors.client.query_points(
            collection_name=self.vectors.collection_name, query=[1.0, 0.0],
            query_filter=filter_for_versions([self.pairs[0]], index_profile_id=self.profile["index_profile_id"]),
            limit=5, with_payload=True, with_vectors=False,
        ).points

    def assert_rejected_without_request(self, callback) -> SearchError:
        before = len(self.embedding.calls)
        with self.assertRaises(SearchError) as caught:
            callback()
        self.assertEqual(len(self.embedding.calls), before)
        self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
        return caught.exception

    def test_query_requests_one_vector_and_returns_complete_sqlite_evidence(self) -> None:
        searcher = HybridEvidenceSearcher(self.searcher(), self.reader)
        with patch.object(self.reader, "get_version_chunks", wraps=self.reader.get_version_chunks) as read_chunks:
            result = searcher.search_evidence("第二", [self.pairs[0]])
            self.assertEqual(read_chunks.call_count, 1)
            repeated = searcher.search_evidence("ASCII", [self.pairs[0]], top_k=1)
            self.assertEqual(read_chunks.call_count, 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["statistics"]["embedding_requests"], 1)
        self.assertEqual(result["statistics"]["total_tokens"], 7)
        self.assertEqual(self.embedding.calls, [["第二"], ["ASCII"]])
        self.assertEqual(repeated["statistics"]["embedding_requests"], 1)
        self.assertEqual(repeated["returned_count"], 1)
        self.assertEqual(repeated["results"][0]["pdf_page"], 2)
        self.assertEqual(result["score_kind"], "rrf")
        self.assertEqual(result["retrieval_method"], "bm25_dense_rrf")
        trace = result["retrieval_trace"]
        self.assertEqual(trace["dense_candidates"][0]["chunk_id"], self.bundles[0].chunks[0]["chunk_id"])
        self.assertEqual(trace["bm25_candidates"][0]["chunk_id"], self.bundles[0].chunks[1]["chunk_id"])
        self.assertEqual(trace["recall_k"], 20)
        self.assertEqual(trace["rank_constant"], 60)
        self.assertEqual(len({row["chunk_id"] for row in result["results"]}), result["returned_count"])
        expected = {c["chunk_id"]: c for c in self.all_chunks}
        for rank, hit in enumerate(result["results"], 1):
            self.assertEqual(hit["rank"], rank)
            self.assertEqual(hit["index_profile_id"], self.profile["index_profile_id"])
            self.assertEqual(hit["point_id"], point_id(self.profile["index_profile_id"], hit["chunk_id"]))
            for field, value in expected[hit["chunk_id"]].items():
                with self.subTest(field=field):
                    self.assertEqual(hit[field], value)
        self.assertEqual(result["results"][0]["pdf_page"], 2)
        self.assertGreater(result["results"][0]["score"], result["results"][1]["score"])

        # Exercise the real HTTP adapter on the complete pool before top-k,
        # including failure fallback and consumed usage at the deadline.
        settings = RerankSettings("qwen3-rerank", "offline-rerank-key", "https://example.invalid/compatible-api/v1")
        with patch.object(config, "_read_env", return_value={
            "RERANK_MODEL": settings.model, "RERANK_BASE_URL": settings.base_url,
            "EMBEDDING_API_KEY": settings.api_key,
        }):
            self.assertEqual(config.load_rerank_settings(), settings)
        requests = []
        state = {"http_status": 200, "expire": False, "remaining": 7.0}

        def rerank_response(request):
            requests.append(request)
            body = json.loads(request.content)
            self.assertEqual(request.url.path, "/compatible-api/v1/reranks")
            self.assertEqual(body["query"], "第二")
            self.assertEqual(body["top_n"], len(body["documents"]))
            self.assertEqual(request.extensions["timeout"]["read"], 7.0)
            if state["expire"]:
                state["remaining"] = 0.0
            return httpx.Response(state["http_status"], json={
                "results": [{"index": index, "relevance_score": 0.9 - rank * 0.1}
                            for rank, index in enumerate(reversed(range(len(body["documents"]))))],
                "usage": {"total_tokens": 23},
            })

        with RerankClient(settings, transport=httpx.MockTransport(rerank_response)) as reranker:
            hybrid = HybridEvidenceSearcher(self.searcher(embedder=LegacyEmbedderAdapter(self.embedding)), self.reader, reranker)
            ranked = hybrid.search_evidence("第二", [self.pairs[0]], top_k=1,
                remaining_seconds=lambda: state["remaining"])
            self.assertEqual(len(json.loads(requests[0].content)["documents"]), 2)
            self.assertEqual(ranked["results"][0]["pdf_page"], 1)
            self.assertEqual(ranked["results"][0]["text"], self.bundles[0].chunks[0]["text"])
            self.assertEqual(ranked["results"][0]["score"], result["results"][1]["score"])
            self.assertEqual(ranked["ranking_method"], "rerank")
            self.assertEqual(ranked["rerank_statistics"]["requests"], 1)
            self.assertEqual(ranked["rerank_statistics"]["usage"], {"total_tokens": 23})

            allowed = [point_id(self.profile["index_profile_id"], self.bundles[0].chunks[0]["chunk_id"])]
            scoped = hybrid.search_evidence("第二", [self.pairs[0]], top_k=1,
                allowed_point_ids=allowed, remaining_seconds=lambda: state["remaining"])
            self.assertEqual(json.loads(requests[-1].content)["documents"], [self.bundles[0].chunks[0]["text"]])
            self.assertEqual(scoped["results"][0]["point_id"], allowed[0])

            state["http_status"] = 503
            fallback = hybrid.search_evidence("第二", [self.pairs[0]], top_k=1,
                remaining_seconds=lambda: state["remaining"])
            self.assertEqual(fallback["results"][0]["pdf_page"], 2)
            self.assertEqual(fallback["ranking_method"], "rrf")
            self.assertEqual(fallback["rerank_statistics"]["status"], "failed")
            self.assertEqual(fallback["rerank_statistics"]["requests"], 1)

            state.update(http_status=200, expire=True)
            with self.assertRaises(SearchError) as caught:
                hybrid.search_evidence("第二", [self.pairs[0]],
                    remaining_seconds=lambda: state["remaining"])
            self.assertEqual(caught.exception.status, "budget_exceeded")
            self.assertEqual(caught.exception.rerank_statistics["requests"], 1)
            self.assertEqual(caught.exception.rerank_statistics["usage"], {"total_tokens": 23})
            self.assertEqual(len(requests), 4)
        self.assertTrue(reranker._client.is_closed)

    def test_filter_preserves_exact_paper_revision_pairs_and_excludes_old_version(self) -> None:
        selected = [self.pairs[0], self.pairs[2]]
        # 这两个点拥有允许的 paper 和允许的 revision，但“配对”不被允许。
        # 分别做 paper IN (...) 和 revision IN (...) 会错误地放行它们。
        cross_chunks = []
        for number, (paper, revision) in enumerate([
            (self.pairs[0][0], self.pairs[2][1]), (self.pairs[2][0], self.pairs[0][1]),
        ]):
            fake = copy.deepcopy(self.all_chunks[number])
            fake.update(paper_id=paper, parse_revision=revision,
                        chunk_id=f"{paper}_{revision}_p{fake['pdf_page']}_c1")
            cross_chunks.append(fake)
        self.vectors.upsert(cross_chunks, [[1.0, 0.0], [1.0, 0.0]])
        result = self.search(selected, top_k=10)
        self.assertEqual(result["returned_count"], 4)
        self.assertEqual({(hit["paper_id"], hit["parse_revision"]) for hit in result["results"]}, set(selected))
        self.assertTrue({hit["chunk_id"] for hit in result["results"]}.isdisjoint(
            {chunk["chunk_id"] for chunk in cross_chunks + self.bundles[1].chunks}))

    def test_pending_and_failed_versions_are_rejected_before_request(self) -> None:
        for status in ["pending", "failed"]:
            with self.subTest(status=status):
                row = self.writer.begin_index_import(*self.pairs[0], self.profile["index_profile_id"])
                if status == "failed":
                    self.writer.fail_index_import(row["import_key"], "离线注入未完成状态")
                error = self.assert_rejected_without_request(lambda: self.search())
                self.assertEqual(error.stage, "ready")

    def test_unknown_paper_and_revision_are_rejected_before_request(self) -> None:
        for pair in [("arxiv_9999.99999v1", self.pairs[0][1]),
                     (self.pairs[0][0], "r_0000000000000000")]:
            with self.subTest(pair=pair):
                self.assert_rejected_without_request(lambda: self.search([pair]))

    def test_missing_import_record_cannot_become_implicitly_ready(self) -> None:
        additional = storage_fixture(max_chars=1800)
        self.writer.import_version(additional)
        pair = (additional.paper["paper_id"], additional.manifest["parse_revision"])
        self.assert_rejected_without_request(lambda: self.search([pair]))

    def test_settings_or_profile_mismatch_is_rejected_before_request(self) -> None:
        for settings in [replace(self.settings, model="another-model"), replace(self.settings, dimension=3)]:
            with self.subTest(model=settings.model, dimension=settings.dimension):
                self.assert_rejected_without_request(lambda: self.searcher(settings=settings))
        changed = copy.deepcopy(self.profile)
        changed["recipe"]["preprocessing"] = "unapproved-rewrite"
        self.assert_rejected_without_request(lambda: self.searcher(profile=changed))

    def test_ready_flag_does_not_hide_missing_qdrant_point(self) -> None:
        chunk = self.bundles[0].chunks[0]
        self.vectors.client.delete(
            collection_name=self.vectors.collection_name,
            points_selector=models.PointIdsList(points=[point_id(self.profile["index_profile_id"], chunk["chunk_id"])]),
            wait=True,
        )
        self.assert_rejected_without_request(lambda: self.search())

    def test_empty_or_non_string_query_is_rejected_before_request(self) -> None:
        for query in ["", " \n\t", None, 5, True]:
            with self.subTest(query=query):
                self.assert_rejected_without_request(
                    lambda: self.searcher().search_evidence(query, [self.pairs[0]]))

    def test_invalid_top_k_is_rejected_before_request(self) -> None:
        for top_k in [0, -1, True, 1.5, None, "5", 21, 100]:
            with self.subTest(top_k=top_k):
                self.assert_rejected_without_request(lambda: self.search(top_k=top_k))

    def test_invalid_or_empty_version_scope_is_rejected_before_request(self) -> None:
        for scope in [[], None, "all", [self.pairs[0][0]], [(self.pairs[0][0],)],
                      [(self.pairs[0][0], self.pairs[0][1], "extra")]]:
            with self.subTest(scope=scope):
                self.assert_rejected_without_request(
                    lambda: self.searcher().search_evidence("检索第一块", scope))

    def test_top_k_limits_results_and_unselected_pending_version_does_not_block(self) -> None:
        # 只选择第一版时，另一处理版本未完成不应把第一版一起禁止查询。
        self.writer.begin_index_import(*self.pairs[1], self.profile["index_profile_id"])
        result = self.search(top_k=1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["results"][0]["pdf_page"], 1)
        self.assertEqual(result["statistics"]["embedding_requests"], 1)

    def test_question_text_is_passed_without_unrecorded_rewriting(self) -> None:
        query = "  检索第一块\n请保留输入。  "
        self.searcher().search_evidence(query, [self.pairs[0]])
        self.assertEqual(self.embedding.calls, [[query]])

    def test_invalid_query_vectors_fail_after_single_attempt(self) -> None:
        for vectors in [[], [[1.0]], [[0.0, 0.0]], [[float("nan"), 1.0]],
                        [[1.0, float("inf")]], [[True, 1.0]], [[1.0, 0.0], [0.0, 1.0]]]:
            with self.subTest(vectors=vectors):
                calls = []

                def invalid(texts, _settings):
                    calls.append(list(texts))
                    return EmbeddingBatch(vectors, 0.01, 7)

                with self.assertRaises(SearchError) as caught:
                    self.searcher(embedder=invalid).search_evidence("检索第一块", [self.pairs[0]])
                self.assertEqual(calls, [["检索第一块"]])
                self.assertEqual(caught.exception.stage, "embedding")
                self.assertEqual(caught.exception.statistics["embedding_requests"], 1)

    def test_no_hits_is_distinct_from_a_service_error(self) -> None:
        with patch.object(self.vectors.client, "query_points", return_value=SimpleNamespace(points=[])):
            result = self.search()
        self.assertEqual(result["status"], "no_hits")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["returned_count"], 0)
        self.assertEqual(result["statistics"]["embedding_requests"], 1)
        self.assertEqual(result["statistics"]["failed_requests"], 0)

    def test_embedding_error_is_not_reported_as_no_hits(self) -> None:
        calls = []

        def unavailable(texts, _settings):
            calls.append(list(texts))
            raise EmbeddingAPIError("离线注入供应商错误")

        with self.assertRaises(SearchError) as caught:
            self.searcher(embedder=unavailable).search_evidence("检索第一块", [self.pairs[0]])
        self.assertEqual(calls, [["检索第一块"]])
        self.assertEqual(caught.exception.stage, "embedding")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 1)
        self.assertEqual(caught.exception.statistics["failed_requests"], 1)

    def test_qdrant_error_is_not_reported_as_no_hits(self) -> None:
        with patch.object(self.vectors.client, "query_points", side_effect=RuntimeError("离线注入查询故障")):
            with self.assertRaises(SearchError) as caught:
                self.search()
        self.assertEqual(caught.exception.stage, "query")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 1)

    def test_wrong_source_payload_fails_without_returning_partial_evidence(self) -> None:
        original = self.actual_hits()
        for field, changed in [
            ("text_sha256", "9" * 64), ("pdf_sha256", "8" * 64),
            ("pdf_page", 1), ("pdf_page", True), ("index_profile_id", "another-profile"),
            ("paper_id", self.pairs[2][0]), ("parse_revision", self.pairs[1][1]),
            ("chunk_id", "unknown-sqlite-chunk"),
        ]:
            with self.subTest(field=field, value=changed):
                hits = copy.deepcopy(original)
                # 第二条坏点很关键：第一条即使已经核对成功也不能半成功返回。
                hits[1].payload[field] = changed
                with patch.object(self.vectors.client, "query_points", return_value=SimpleNamespace(points=hits)):
                    with self.assertRaises(SearchError) as caught:
                        self.search()
                self.assertEqual(caught.exception.stage, "evidence")

    def test_wrong_point_uuid_and_duplicate_hit_are_rejected(self) -> None:
        hits = self.actual_hits()
        invalid = copy.deepcopy(hits)
        invalid[1].id = str(uuid4())
        for points in [invalid, [hits[0], hits[0]]]:
            with self.subTest(point_ids=[str(hit.id) for hit in points]):
                with patch.object(self.vectors.client, "query_points", return_value=SimpleNamespace(points=points)):
                    with self.assertRaises(SearchError) as caught:
                        self.search()
                self.assertEqual(caught.exception.stage, "evidence")

    def test_nonfinite_boolean_or_out_of_range_cosine_score_is_rejected(self) -> None:
        for score in [float("nan"), float("inf"), True, 2.0, -2.0]:
            with self.subTest(score=score):
                hits = self.actual_hits()
                # SimpleNamespace 避免 Pydantic 在测试注入阶段先拒绝坏值；
                # 这里需要验证应用面对不合法的服务结果也会主动核对。
                hits[1] = SimpleNamespace(id=hits[1].id, payload=hits[1].payload, score=score)
                with patch.object(self.vectors.client, "query_points", return_value=SimpleNamespace(points=hits)):
                    with self.assertRaises(SearchError) as caught:
                        self.search()
                self.assertEqual(caught.exception.stage, "evidence")

    def test_read_only_search_survives_restart_without_changing_sqlite_bytes(self) -> None:
        before = self.database_path.read_bytes()
        first = self.search()
        self.assertEqual(self.database_path.read_bytes(), before)
        self.reader.close()
        self.resources.remove(self.reader)
        self.vectors.close()
        self.resources.remove(self.vectors)
        self.reader = PaperStore(self.database_path, read_only=True)
        self.resources.append(self.reader)
        self.vectors = QdrantStore(
            self.root / "qdrant", self.profile["collection_name"], self.profile["index_profile_id"], 2,
        )
        self.resources.append(self.vectors)
        second = self.search()
        self.assertEqual(first["results"], second["results"])
        self.assertEqual(self.database_path.read_bytes(), before)
        self.assertEqual(len(self.embedding.calls), 2)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
