"""Local BM25 recall and rank fusion over the selected paper chunks."""

from collections import Counter
from collections.abc import Sequence
from math import log
import re


_TOKEN_SPANS = re.compile(r"[A-Za-z0-9]+|[\u3400-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """Casefold English words/numbers and split Chinese spans into bigrams.

    A one-character Chinese span remains a token. This tokenizer neither
    translates the query nor adds words that were absent from the original text.
    """
    tokens: list[str] = []
    for match in _TOKEN_SPANS.finditer(text):
        span = match.group()
        if "\u3400" <= span[0] <= "\u9fff":
            tokens.extend(span[index:index + 2] for index in range(len(span) - 1))
            if len(span) == 1:
                tokens.append(span)
        else:
            tokens.append(span.casefold())
    return tokens


class BM25Index:
    """In-memory term statistics built from original chunk text.

    When allowed_chunk_ids is supplied, document count, document frequency and
    average length are calculated within that subset. Repeated query tokens do
    not multiply a term's score. Only positive lexical matches are returned.
    """

    def __init__(self, chunks: Sequence[dict], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.term_frequencies = {
            chunk["chunk_id"]: Counter(tokenize(chunk["text"])) for chunk in chunks
        }
        self.document_lengths = {
            chunk_id: sum(terms.values())
            for chunk_id, terms in self.term_frequencies.items()
        }
        self.document_frequencies: Counter = Counter()
        for terms in self.term_frequencies.values():
            self.document_frequencies.update(terms.keys())

    def score(
        self, query: str, top_k: int = 20,
        allowed_chunk_ids: set[str] | None = None,
    ) -> list[dict]:
        """Return real chunk IDs with one-based rank and their BM25 score."""
        query_terms = sorted(set(tokenize(query)))
        if not query_terms or top_k <= 0:
            return []
        documents = self.term_frequencies
        frequencies = self.document_frequencies
        if allowed_chunk_ids is not None:
            documents = {
                chunk_id: terms for chunk_id, terms in documents.items()
                if chunk_id in allowed_chunk_ids
            }
            frequencies = Counter()
            for terms in documents.values():
                frequencies.update(terms.keys())
        document_count = len(documents)
        if not document_count:
            return []
        average_length = sum(self.document_lengths[chunk_id] for chunk_id in documents) / document_count
        if not average_length:
            return []
        inverse_frequencies = {
            term: log(1 + (document_count - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            for term in query_terms
        }
        scores: list[tuple[str, float]] = []
        for chunk_id, terms in documents.items():
            length_factor = self.k1 * (
                1 - self.b + self.b * self.document_lengths[chunk_id] / average_length
            )
            score = sum(
                inverse_frequencies[term] * count * (self.k1 + 1) / (count + length_factor)
                for term in query_terms if (count := terms.get(term, 0))
            )
            if score > 0:
                scores.append((chunk_id, score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        return [
            {"chunk_id": chunk_id, "rank": rank, "score": score}
            for rank, (chunk_id, score) in enumerate(scores[:top_k], start=1)
        ]


def reciprocal_rank_fusion(
    dense_results: Sequence[dict], bm25_results: Sequence[dict], *,
    top_k: int = 5, rank_constant: int = 60, candidate_limit: int = 20,
) -> list[dict]:
    """Fuse two ordered candidate lists without comparing unlike raw scores.

    Each route contributes 1 / (rank_constant + its one-based list position).
    Duplicate chunk IDs contribute once per route, at their first occurrence.
    Equal fused scores sort by dense rank, then BM25 rank, then chunk ID.
    """
    fused: dict[str, dict] = {}
    for route, results in (("dense", dense_results), ("bm25", bm25_results)):
        for rank, result in enumerate(results[:candidate_limit], start=1):
            chunk_id = result["chunk_id"]
            row = fused.setdefault(chunk_id, {
                "chunk_id": chunk_id, "score": 0.0,
                "dense_rank": None, "bm25_rank": None,
                "dense_score": None, "bm25_score": None,
            })
            if row[f"{route}_rank"] is not None:
                continue
            row[f"{route}_rank"] = rank
            row[f"{route}_score"] = result["score"]
            row["score"] += 1 / (rank_constant + rank)
    ranked = sorted(fused.values(), key=lambda row: (
        -row["score"], row["dense_rank"] or float("inf"),
        row["bm25_rank"] or float("inf"), row["chunk_id"],
    ))
    return [{**row, "rank": rank} for rank, row in enumerate(ranked[:top_k], start=1)]
