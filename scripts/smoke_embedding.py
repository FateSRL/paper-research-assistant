"""D2 第 8 节：六条输入、一次调用、三文档余弦排序。"""

import json
from datetime import datetime, timezone
from math import isfinite, sqrt

from paper_assistant.config import ConfigError, PROJECT_ROOT, load_embedding_settings
from paper_assistant.embedding_client import EmbeddingAPIError, embed_texts


DOCUMENTS = {
    "D1": "Retrieval-augmented generation retrieves relevant documents before generating an answer.",
    "D2": "ReAct agents can use external tools while solving a task.",
    "D3": "Tomato plants require sunlight and water to grow.",
}
QUERIES = {
    "Q1": "Which approach retrieves documents before generating an answer?",
    "Q2": "哪种方法会先检索文档，再生成答案？",
    "Q3": "How much electricity did the experiment consume?",
}
RESULT_FILE = PROJECT_ROOT / "archive" / "run_logs" / "d2" / "embedding_smoke.json"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """余弦相似度 = 点积 / (左向量范数 × 右向量范数)。"""
    if len(left) != len(right):
        raise ValueError("两个向量维度不同")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if not isfinite(left_norm) or not isfinite(right_norm) or left_norm == 0 or right_norm == 0:
        raise ValueError("向量范数为零或非有限数")
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def main() -> int:
    report: dict[str, object] = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "hello-agents-study/log/d2.md section 8",
        "connectivity": "failed",
        "ranking_check": "not_run",
        "input_mode": "OpenAI-compatible dense embedding; default text type for documents and queries",
        "normalized_by_client": False,
        "document_texts": DOCUMENTS,
        "query_texts": QUERIES,
    }
    try:
        settings = load_embedding_settings()
        report.update(
            backend=settings.backend,
            model=settings.model,
            requested_dimension=settings.dimension,
            base_url=settings.base_url,
        )
        labels = list(DOCUMENTS) + list(QUERIES)
        batch = embed_texts(list(DOCUMENTS.values()) + list(QUERIES.values()), settings)
        vectors = dict(zip(labels, batch.vectors))
        norms = {
            label: sqrt(sum(value * value for value in vector))
            for label, vector in vectors.items()
        }
        if any(not isfinite(norm) or norm == 0 for norm in norms.values()):
            raise ValueError("向量范数为零或非有限数")
        report.update(
            connectivity="passed",
            returned_vectors=len(batch.vectors),
            returned_dimension=len(batch.vectors[0]),
            norm_min=min(norms.values()),
            norm_max=max(norms.values()),
            elapsed_seconds=round(batch.elapsed_seconds, 3),
            total_tokens=batch.total_tokens,
        )
        rankings = {}
        for query_id in QUERIES:
            scores = [
                {"document_id": document_id, "cosine_similarity": round(cosine_similarity(vectors[query_id], vectors[document_id]), 6)}
                for document_id in DOCUMENTS
            ]
            rankings[query_id] = sorted(scores, key=lambda item: item["cosine_similarity"], reverse=True)
        report["rankings"] = rankings
        report["ranking_check"] = "passed" if all(rankings[q][0]["document_id"] == "D1" for q in ("Q1", "Q2")) else "failed"
        report["q3_note"] = "Q3 没有可回答的证据；第一名仅表示相对最接近。"
    except (ConfigError, EmbeddingAPIError, ValueError) as exc:
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)

    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"结果已保存：{RESULT_FILE}")
    print(f"接口连通：{report['connectivity']}；排序验收：{report['ranking_check']}")
    if report["connectivity"] == "passed":
        for query_id, ranking in report["rankings"].items():
            print(query_id + ": " + ", ".join(f"{item['document_id']}={item['cosine_similarity']:.6f}" for item in ranking))
    else:
        print(f"错误：{report['error']}")
    return 0 if report["connectivity"] == "passed" and report["ranking_check"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
