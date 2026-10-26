"""D9 shared remaining-time checks and the business-result commit boundary."""
from copy import deepcopy
from math import isfinite


class DeadlineExceeded(ValueError):
    code = "deadline_exceeded"


def remaining(callback):
    if callback is None:
        return None
    if not callable(callback):
        raise ValueError("remaining_seconds must be a callable")
    value = callback()
    if type(value) not in (int, float) or (not isfinite(value) and value != float("inf")):
        raise ValueError("remaining_seconds must return a number or positive infinity")
    if value <= 0:
        raise DeadlineExceeded("本轮剩余时限已耗尽")
    return float(value)


def search_with_budget(searcher, query, pairs, *, top_k=5, remaining_seconds=None,
                       allowed_point_ids=None):
    """Explicit legacy adapter: one call, never TypeError-and-resend fallback.

    A custom legacy searcher keeps its three-argument call and receives stage
    checks. Only a declared deadline-aware searcher receives the callback.
    Legacy stage checks cannot shorten a hidden legacy network request.
    """
    remaining(remaining_seconds)
    options = {} if allowed_point_ids is None else {"allowed_point_ids": allowed_point_ids}
    if remaining_seconds is not None and getattr(searcher, "supports_remaining_time", False) is True:
        options["remaining_seconds"] = remaining_seconds
    # The core records returned candidates/usage before its post-call check.
    return searcher.search_evidence(query, pairs, top_k=top_k, **options)


def final_deadline(result, budget, stage, *, now=None):
    """All terminal statuses expire; preserve an earlier observed failure."""
    sampled = budget.clock() if now is None else now
    if budget.deadline - sampled > 0:
        return False
    if (result.get("status") == "budget_exceeded"
            and (result.get("error") or {}).get("code") == "deadline_exceeded"):
        # A later verification must retain the first observed expiry location.
        return True
    error = result.get("error")
    if error and error.get("code") != "deadline_exceeded":
        result["interrupted_failure"] = {
            "status": result.get("status"), "failure_stage": result.get("failure_stage"),
            "error": deepcopy(error),
        }
    result.update(status="budget_exceeded", answer=None, failure_stage=stage,
                  stop_reason="deadline_exceeded",
                  error={"code": "deadline_exceeded", "message": "业务终态提交前截止预算已到"})
    nested = result.get("result")
    if isinstance(nested, dict):
        result.setdefault("pre_failure_result", deepcopy(nested))
        nested.update(status="budget_exceeded", answer=None, failure_stage=stage,
                      stop_reason="deadline_exceeded", error=deepcopy(result["error"]))
    return True


def commit_result(result, budget, stage):
    sampled = budget.clock()
    final_deadline(result, budget, stage, now=sampled)
    result["business_commit"] = {
        "version": "d9-business-commit-v1", "stage": stage,
        "elapsed_seconds": max(0.0, sampled - budget.started),
        "status": result.get("status"),
        "deadline_checked": isfinite(budget.deadline),
    }


def preserve_expired_failure(result, status, code, message, stage):
    """Retain first expiry while still recording faults found by final guards."""
    if (stage != "export" and result.get("status") == "budget_exceeded"
            and (result.get("error") or {}).get("code") == "deadline_exceeded"):
        result.setdefault("post_deadline_failures", []).append({
            "status": status, "failure_stage": stage, "error": {"code": code, "message": message}})
        return True
    return False
