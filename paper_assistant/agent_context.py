"""Select full chunks from retry rounds or planned retrieval queries.

No store or service access occurs here; structured selection uses the saved local tokenizer. Original retrieval envelopes and
their rank/score fields remain in the outer trace; the compatible context uses
continuous selection ordinals so the existing selector retains the merge order
instead of comparing unrelated retrieval ranks.
"""

from copy import deepcopy

from paper_assistant.context import ContextError, build_messages, prepare_context, select_context


AGENT_SELECTION_VERSION = "d8-retry-first-full-chunks-v1"
PLANNED_SELECTION_VERSION = "d13-planned-round-robin-full-chunks-v1"
_IDENTITY_FIELDS = ("paper_id", "parse_revision", "pdf_page", "text_sha256", "text")


def _fail(code: str) -> None:
    raise ContextError(code, "Agent retrieval context failed its fixed contract")


def _versions(selected_versions) -> list[tuple[str, str]]:
    if not isinstance(selected_versions, list) or not 1 <= len(selected_versions) <= 3:
        _fail("invalid_versions")
    pairs = []
    for pair in selected_versions:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                       for value in pair)):
            _fail("invalid_versions")
        checked = tuple(pair)
        if checked in pairs:
            _fail("duplicate_version")
        pairs.append(checked)
    return pairs


def _parameters(top_k, max_chars) -> None:
    if type(top_k) is not int or top_k != 5:
        _fail("invalid_top_k")
    if max_chars is not None and (type(max_chars) is not int or not 1 <= max_chars <= 8000):
        _fail("invalid_character_budget")


def validate_search_round(search, query, selected_versions, top_k=5, max_chars=8000, max_tokens=None) -> dict:
    """Validate one complete top-5 envelope and return the old context format.

All candidates are checked even if the character selector subsequently omits
them. The supplied query is compared exactly; normalization is solely the
orchestrator's pre-request duplicate-query check.
"""
    _parameters(top_k, max_chars)
    pairs = _versions(selected_versions)
    if not isinstance(query, str) or not query.strip():
        _fail("invalid_question")
    checked = deepcopy(search)
    expected_versions = [{"paper_id": paper, "parse_revision": revision} for paper, revision in pairs]
    if (not isinstance(checked, dict) or checked.get("query") != query
            or checked.get("selected_versions") != expected_versions
            or type(checked.get("top_k")) is not int or checked["top_k"] != top_k):
        _fail("search_scope_mismatch")
    profile = checked.get("index_profile_id")
    if not isinstance(profile, str) or not profile.strip() or profile != profile.strip():
        _fail("invalid_index_profile")
    candidates = checked.get("results")
    if (not isinstance(candidates, list) or len(candidates) > top_k
            or type(checked.get("returned_count")) is not int
            or checked["returned_count"] != len(candidates)
            or checked.get("status") not in ("success", "no_hits")
            or (checked["status"] == "no_hits") != (not candidates)):
        _fail("inconsistent_search_result")
    if any(not isinstance(item, dict) or type(item.get("rank")) is not int or item["rank"] != rank
           for rank, item in enumerate(candidates, start=1)):
        _fail("invalid_search_rank")
    if any("index_profile_id" in item and item["index_profile_id"] != profile for item in candidates):
        _fail("search_profile_mismatch")
    # prepare_context validates every candidate's identity, page, finite score,
    # original text SHA and same-ID conflicts before applying character limits.
    context = prepare_context(checked, max_chars=max_chars, max_tokens=max_tokens)
    build_messages(query, context)
    return context


def _unique_ids(candidates) -> list[str]:
    return list(dict.fromkeys(item["chunk_id"] for item in candidates))


def merge_planned_context(searches, original_question, selected_versions,
                          *, max_chars=8000, max_chunks=8, candidate_groups=None,
                          retry_first=False, query_indices=None, round_kind="planned", max_tokens=None) -> dict:
    """Merge real plan queries by within-query rank, preserving complete text.

    Each envelope keeps its own query and version subset. ``candidate_groups``
    allows the source-scope caller to filter those same validated candidates
    before selection; raw retrieval records remain unchanged. ``retry_first``
    keeps the existing retry-first order for one planned query plus a retry.
    """
    _parameters(5, max_chars)
    pairs = _versions(selected_versions)
    if max_chunks is not None and (type(max_chunks) is not int or not 1 <= max_chunks <= 8):
        _fail("invalid_agent_evidence_count")
    if not isinstance(searches, list):
        _fail("invalid_search_result")
    if retry_first and len(searches) != 2:
        _fail("invalid_search_result")
    checked_searches = deepcopy(searches)
    query_indices = list(range(1, len(searches) + 1)) if query_indices is None else query_indices
    round_contexts, identities, profile = [], {}, None
    for search in checked_searches:
        versions = search.get("selected_versions") if isinstance(search, dict) else None
        if (not isinstance(versions, list)
                or any(not isinstance(row, dict) or set(row) != {"paper_id", "parse_revision"}
                       for row in versions)):
            _fail("invalid_versions")
        query_pairs = _versions([(row["paper_id"], row["parse_revision"]) for row in versions])
        if any(pair not in pairs for pair in query_pairs):
            _fail("search_scope_mismatch")
        round_contexts.append(validate_search_round(
            search, search.get("query"), query_pairs, max_chars=max_chars, max_tokens=max_tokens))
        if profile is not None and profile != search["index_profile_id"]:
            _fail("search_profile_mismatch")
        profile = search["index_profile_id"]
        for item in search["results"]:
            identity = tuple(item[field] for field in _IDENTITY_FIELDS)
            if item["chunk_id"] in identities and identities[item["chunk_id"]] != identity:
                _fail("conflicting_duplicate")
            identities[item["chunk_id"]] = identity

    groups = ([search["results"] for search in checked_searches]
              if candidate_groups is None else deepcopy(candidate_groups))
    if (not isinstance(groups, list) or len(groups) != len(checked_searches)
            or any(not isinstance(rows, list) for rows in groups)):
        _fail("invalid_candidates")
    if candidate_groups is not None:
        round_contexts = [{**select_context(rows, [(v["paper_id"], v["parse_revision"])
                                                   for v in search["selected_versions"]], max_chars=max_chars, max_tokens=max_tokens),
                           "question": search["query"], "score_kind": search.get("score_kind", "cosine"),
                           "ranking_method": search.get("ranking_method", search.get("score_kind", "cosine"))}
                          for search, rows in zip(checked_searches, groups)]
    labels = ["initial", "retry"] if retry_first else [round_kind] * len(groups)
    ordered = ([(index, item) for index in (1, 0) for item in groups[index]] if retry_first else
               [(index, rows[position])
                for position in range(max((len(rows) for rows in groups), default=0))
                for index, rows in enumerate(groups) if position < len(rows)])
    retained, duplicates, origins = [], [], {}
    for index, item in ordered:
        identifier = item["chunk_id"]
        origin = {"round": labels[index], "query_index": query_indices[index],
                  "rank": item["rank"], "score": item["score"]}
        if identifier in origins:
            duplicates.append({"chunk_id": identifier, **origin,
                               "kept_origin": deepcopy(origins[identifier]), "reason": "duplicate"})
            continue
        ordinal = len(retained) + 1
        origins[identifier] = {**origin, "selection_ordinal": ordinal}
        retained.append({**deepcopy(item), "rank": ordinal})

    capped = retained if max_chunks is None else retained[:max_chunks]
    context = {**select_context(capped, pairs, max_chars=max_chars, max_tokens=max_tokens),
               "question": original_question,
               "score_kind": checked_searches[0].get("score_kind", "cosine") if checked_searches else "cosine",
               "ranking_method": "retry_then_initial" if retry_first else round_kind + "_round_robin"}
    build_messages(original_question, context)
    trace = {
        "merge_version": "d13-planned-retry-first-full-chunks-v1" if retry_first else PLANNED_SELECTION_VERSION,
        "merge_order": "retry_rank_then_initial_rank" if retry_first else round_kind + "_round_robin_rank",
        "deduplicate_key": "chunk_id",
        "cross_query_score_sort": False, "max_chunks": max_chunks, "max_chars": max_chars,
        "index_profile_id": profile, "original_question": original_question,
        "selected_versions": deepcopy(context["selected_versions"]),
        "rounds": [{"round": labels[index], "query_index": query_indices[index],
                    "search": search, "context": round_contexts[index]}
                   for index, search in enumerate(checked_searches)],
        "merged_candidates": deepcopy(retained), "selection_origins": deepcopy(origins),
        "duplicates": duplicates,
        "count_omitted": [{"chunk_id": item["chunk_id"], **deepcopy(origins[item["chunk_id"]]),
                           "reason": "count_limit"} for item in
                          ([] if max_chunks is None else retained[max_chunks:])],
        "character_omitted": [{**deepcopy(item), "origin": deepcopy(origins[item["chunk_id"]])}
                              for item in context["omitted_evidence"]],
        "merged_ids": _unique_ids(retained), "count_capped_ids": _unique_ids(capped),
        "final_shown_ids": deepcopy(context["allowed_citation_ids"]),
    }
    if retry_first:
        initial_ids = _unique_ids(checked_searches[0]["results"])
        retry_ids = _unique_ids(checked_searches[1]["results"])
        initial_shown = round_contexts[0]["allowed_citation_ids"]
        final_shown = context["allowed_citation_ids"]
        trace.update(
            initial_returned_ids=initial_ids, retry_returned_ids=retry_ids,
            initial_shown_ids=deepcopy(initial_shown),
            new_returned_ids=[value for value in retry_ids if value not in initial_ids],
            new_merged_ids=[value for value in trace["merged_ids"] if value not in initial_ids],
            new_count_capped_ids=[value for value in trace["count_capped_ids"] if value not in initial_ids],
            new_shown_ids=[value for value in final_shown if value not in initial_shown],
            new_recalled_shown_ids=[value for value in final_shown if value not in initial_ids],
            initial_returned_unshown_now_shown_ids=[value for value in final_shown
                                                   if value in initial_ids and value not in initial_shown])
    return {"context": context, "trace": trace}


def merge_agent_context(initial_search, retry_search, original_question, selected_versions,
                        *, max_chars=8000, max_chunks=8, max_tokens=None) -> dict:
    """Validate both rounds, deduplicate retry first, cap count, select chunks.

The returned ``context`` is accepted by the existing message/citation checks.
``trace`` contains all retrieval candidates plus count and character omissions.
No same-query stop or no-new-evidence stop executes here; the orchestrator owns
those decisions and uses the recorded final shown ID changes.
"""
    _parameters(5, max_chars)
    pairs = _versions(selected_versions)
    if max_chunks is not None and (type(max_chunks) is not int or not 1 <= max_chunks <= 8):
        _fail("invalid_agent_evidence_count")
    initial = deepcopy(initial_search)
    retry = deepcopy(retry_search)
    initial_context = validate_search_round(initial, original_question, pairs, max_chars=max_chars, max_tokens=max_tokens)
    if not isinstance(retry, dict):
        _fail("invalid_search_result")
    retry_context = validate_search_round(retry, retry.get("query"), pairs, max_chars=max_chars, max_tokens=max_tokens)
    if initial["index_profile_id"] != retry["index_profile_id"]:
        _fail("search_profile_mismatch")

    # Conflict detection deliberately covers the full ten-or-fewer candidates,
    # including duplicates and candidates beyond the final count/character cap.
    identities = {}
    for search in (initial, retry):
        for item in search["results"]:
            identity = tuple(item[field] for field in _IDENTITY_FIELDS)
            if item["chunk_id"] in identities and identities[item["chunk_id"]] != identity:
                _fail("conflicting_duplicate")
            identities[item["chunk_id"]] = identity

    retained, duplicates, origins = [], [], {}
    for round_name, search in (("retry", retry), ("initial", initial)):
        for item in search["results"]:
            chunk_id = item["chunk_id"]
            origin = {"round": round_name, "rank": item["rank"], "score": item["score"]}
            if chunk_id in origins:
                duplicates.append({"chunk_id": chunk_id, **origin,
                                   "kept_origin": deepcopy(origins[chunk_id]), "reason": "duplicate"})
                continue
            ordinal = len(retained) + 1
            origins[chunk_id] = {**origin, "selection_ordinal": ordinal}
            retained.append({**deepcopy(item), "rank": ordinal})

    capped = retained if max_chunks is None else retained[:max_chunks]
    count_omitted = [{"chunk_id": item["chunk_id"], **deepcopy(origins[item["chunk_id"]]),
                      "reason": "count_limit"} for item in ([] if max_chunks is None else retained[max_chunks:])]
    context = {**select_context(capped, pairs, max_chars=max_chars, max_tokens=max_tokens), "question": original_question,
               "score_kind": initial.get("score_kind", "cosine"),
               "ranking_method": "retry_then_initial"}
    build_messages(original_question, context)

    initial_ids = _unique_ids(initial["results"])
    retry_ids = _unique_ids(retry["results"])
    merged_ids = _unique_ids(retained)
    capped_ids = _unique_ids(capped)
    initial_shown = initial_context["allowed_citation_ids"]
    final_shown = context["allowed_citation_ids"]
    initial_set, initially_shown_set = set(initial_ids), set(initial_shown)
    trace = {
        "merge_version": AGENT_SELECTION_VERSION,
        "merge_order": "retry_rank_then_initial_rank", "deduplicate_key": "chunk_id",
        "cross_query_score_sort": False, "max_chunks": max_chunks, "max_chars": max_chars,
        "index_profile_id": initial["index_profile_id"],
        "original_question": original_question,
        "selected_versions": deepcopy(context["selected_versions"]),
        "rounds": [{"round": "initial", "search": initial, "context": initial_context},
                   {"round": "retry", "search": retry, "context": retry_context}],
        "merged_candidates": deepcopy(retained), "selection_origins": deepcopy(origins),
        "duplicates": duplicates, "count_omitted": count_omitted,
        "character_omitted": [{**deepcopy(item), "origin": deepcopy(origins[item["chunk_id"]])}
                              for item in context["omitted_evidence"]],
        "initial_returned_ids": initial_ids, "retry_returned_ids": retry_ids,
        "merged_ids": merged_ids, "count_capped_ids": capped_ids,
        "initial_shown_ids": deepcopy(initial_shown), "final_shown_ids": deepcopy(final_shown),
        "new_returned_ids": [value for value in retry_ids if value not in initial_set],
        "new_merged_ids": [value for value in merged_ids if value not in initial_set],
        "new_count_capped_ids": [value for value in capped_ids if value not in initial_set],
        "new_shown_ids": [value for value in final_shown if value not in initially_shown_set],
        "new_recalled_shown_ids": [value for value in final_shown if value not in initial_set],
        "initial_returned_unshown_now_shown_ids": [value for value in final_shown
                                                 if value in initial_set and value not in initially_shown_set],
    }
    return {"context": context, "trace": trace}
