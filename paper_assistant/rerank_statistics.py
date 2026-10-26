"""Keep rerank requests separate from embedding and chat accounting."""

from copy import deepcopy


def empty_rerank_statistics():
    return {"status": "disabled", "model": None, "requests": 0,
            "elapsed_seconds": 0.0, "usage": None}


def sum_rerank_statistics(rows):
    """Sum actual rounds; retain provider usage per round without inventing totals."""
    rounds = [deepcopy(row) if isinstance(row, dict) else empty_rerank_statistics() for row in rows]
    statuses = {row["status"] for row in rounds}
    models = {row.get("model") for row in rounds if row.get("model") is not None}
    return {"status": next(iter(statuses)) if len(statuses) == 1 else ("mixed" if statuses else "disabled"),
            "model": next(iter(models)) if len(models) == 1 else None,
            "requests": sum(row["requests"] for row in rounds),
            "elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rounds), 6),
            "rounds": rounds}
