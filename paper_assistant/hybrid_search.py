"""BM25 and dense recall over the same selected versions, fused by rank."""

from copy import deepcopy
from time import perf_counter

from paper_assistant.deadline import DeadlineExceeded, remaining
from paper_assistant.lexical_retrieval import BM25Index, reciprocal_rank_fusion
from paper_assistant.retrieval import point_id
from paper_assistant.rerank_client import RerankError
from paper_assistant.rerank_statistics import empty_rerank_statistics
from paper_assistant.search import EvidenceSearcher, SearchError


RETRIEVAL_METHOD = "bm25_dense_rrf"
RECALL_K = 20
RRF_RANK_CONSTANT = 60


class HybridEvidenceSearcher:
    """Borrow the existing dense searcher/store; keep local indexes per run.

    The dense route owns ready checks, query embedding and point-scope checks.
    BM25 reads the same selected SQLite chunks and uses the same point whitelist.
    An optional reranker sorts the complete fused pool before the top-k cut.
    """

    supports_remaining_time = True

    def __init__(self, dense_searcher, store, reranker=None):
        self.dense_searcher, self.store = dense_searcher, store
        self.reranker = reranker
        self._indexes = {}

    def search_evidence(self, query, selected_versions, top_k=5, *,
                        allowed_point_ids=None, remaining_seconds=None):
        pairs = EvidenceSearcher._check_input(query, selected_versions, top_k)
        remaining(remaining_seconds)
        started = perf_counter()
        options = {}
        if allowed_point_ids is not None:
            options["allowed_point_ids"] = allowed_point_ids
        if remaining_seconds is not None:
            options["remaining_seconds"] = remaining_seconds
        dense = self.dense_searcher.search_evidence(query, pairs, top_k=RECALL_K, **options)
        statistics = deepcopy(dense["statistics"])
        rerank_statistics = empty_rerank_statistics()
        rerank_trace = {**rerank_statistics, "candidates": [], "error": None}
        ranking_method = "rrf"
        stage = "bm25"
        try:
            remaining(remaining_seconds)
            key = tuple(pairs)
            lexical_started = perf_counter()
            if key not in self._indexes:
                chunks = []
                for pair in pairs:
                    chunks.extend(self.store.get_version_chunks(*pair))
                    remaining(remaining_seconds)
                self._indexes[key] = ({row["chunk_id"]: row for row in chunks}, BM25Index(chunks))
            rows, lexical = self._indexes[key]
            allowed_chunks = None
            # Use the dense route's checked, independent whitelist snapshot.
            if dense.get("allowed_point_ids") is not None:
                allowed_points = set(dense["allowed_point_ids"])
                allowed_chunks = {identifier for identifier in rows
                    if point_id(dense["index_profile_id"], identifier) in allowed_points}
            bm25 = lexical.score(query, top_k=RECALL_K, allowed_chunk_ids=allowed_chunks)
            statistics["bm25_elapsed_seconds"] = round(perf_counter() - lexical_started, 6)
            remaining(remaining_seconds)
            stage = "fusion"
            fused = reciprocal_rank_fusion(dense["results"], bm25, top_k=RECALL_K * 2,
                rank_constant=RRF_RANK_CONSTANT, candidate_limit=RECALL_K)
            dense_rows = {row["chunk_id"]: row for row in dense["results"]}
            ordered = fused
            if self.reranker is not None:
                stage = "rerank"
                rerank_statistics.update(status="empty", model=self.reranker.settings.model)
                if fused:
                    documents = [(dense_rows.get(row["chunk_id"]) or rows[row["chunk_id"]])["text"]
                                 for row in fused]
                    try:
                        batch = self.reranker.rerank(query, documents, remaining_seconds=remaining_seconds)
                    except RerankError as error:
                        rerank_statistics.update(status="failed", requests=error.requests,
                            elapsed_seconds=error.elapsed_seconds, usage=deepcopy(error.usage))
                        rerank_trace["error"] = {"code": error.code, "message": "重排未完成，沿用 RRF 顺序"}
                    else:
                        rerank_statistics.update(status="success", requests=batch.requests,
                            elapsed_seconds=batch.elapsed_seconds, usage=deepcopy(batch.usage))
                        ordered = [{**fused[row["index"]], "rank": rank}
                                   for rank, row in enumerate(batch.results, 1)]
                        rerank_trace["candidates"] = [
                            {"chunk_id": fused[row["index"]]["chunk_id"], "rank": rank,
                             "rrf_rank": fused[row["index"]]["rank"],
                             "relevance_score": row["relevance_score"]}
                            for rank, row in enumerate(batch.results, 1)]
                        ranking_method = "rerank"
                rerank_trace.update(deepcopy(rerank_statistics))
                remaining(remaining_seconds)
            results = []
            for candidate in ordered[:top_k]:
                identifier = candidate["chunk_id"]
                source = dense_rows[identifier] if identifier in dense_rows else rows[identifier]
                results.append({**deepcopy(source), "rank": candidate["rank"], "score": candidate["score"],
                    "point_id": point_id(dense["index_profile_id"], identifier),
                    "index_profile_id": dense["index_profile_id"]})
            remaining(remaining_seconds)
            statistics["total_elapsed_seconds"] = round(perf_counter() - started, 6)
            return {**deepcopy(dense), "status": "success" if results else "no_hits", "top_k": top_k,
                    "results": results, "returned_count": len(results), "statistics": statistics,
                    "retrieval_method": RETRIEVAL_METHOD + ("_rerank" if ranking_method == "rerank" else ""),
                    "score_kind": "rrf", "ranking_method": ranking_method,
                    "rerank_statistics": rerank_statistics,
                    "retrieval_trace": {"recall_k": RECALL_K, "rank_constant": RRF_RANK_CONSTANT,
                        "dense_candidates": [{"chunk_id": row["chunk_id"], "rank": row["rank"], "score": row["score"]}
                                             for row in dense["results"]],
                        "bm25_candidates": deepcopy(bm25), "fused_candidates": fused,
                        "rerank": rerank_trace}}
        except DeadlineExceeded:
            statistics["total_elapsed_seconds"] = round(perf_counter() - started, 6)
            error = SearchError("本轮混合检索截止预算已到", stage=stage, statistics=statistics,
                                status="budget_exceeded", code="deadline_exceeded")
            error.rerank_statistics = deepcopy(rerank_statistics)
            raise error from None
        except Exception as error:
            statistics["total_elapsed_seconds"] = round(perf_counter() - started, 6)
            failure = SearchError("本地混合检索失败：" + type(error).__name__, stage=stage,
                                  statistics=statistics, code="hybrid_search_error")
            failure.rerank_statistics = deepcopy(rerank_statistics)
            raise failure from error
