"""Read real parent children or nearby legacy chunks after retrieval.

This is local document reading, not another search. Retrieval snapshots stay
unchanged; the returned context records which retrieved chunk led to each read.
"""

from copy import deepcopy
import re

from paper_assistant.context import select_context, token_context_options


_HEADING = re.compile(
    r"(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(?:abstract|introduction|background|related work|methods?|methodology|"
    r"approach|experiments?|experimental setup|results|discussion|conclusions?|"
    r"limitations|摘要|引言|方法|实验|结果|讨论|结论)", re.IGNORECASE,
)
_TABLE_CAPTION = re.compile(r"^(?:table\s*[A-Za-z]?\d+|表\s*\d+)\b", re.IGNORECASE)


def _heading(text):
    label = " ".join(text.split()).strip(" :：")
    return bool(_HEADING.fullmatch(label) or (
        len(label) <= 120 and not label.endswith((".", "。", "?", "!", ";"))
        and re.fullmatch(r"\d+(?:\.\d+)*[.)]?\s+[A-Za-z\u4e00-\u9fff].*", label)))


def parent_children(parent_id, version_chunks, parent_store, *, parent=None):
    """Expand only saved child relationships within the selected versions."""
    parent = parent if parent is not None else parent_store.get_parent(parent_id) if parent_store is not None else None
    if parent is None or (parent["paper_id"], parent["parse_revision"]) not in version_chunks:
        raise ValueError("unavailable_parent")
    children = {row["chunk_id"]: row for row in version_chunks[(parent["paper_id"], parent["parse_revision"])]}
    return parent, [deepcopy(children[identifier]) for identifier in parent["child_ids"]]


def _table_caption(parent):
    """Return the saved leading table title, or empty when it is not a caption."""
    first = (parent.get("text") or "").split("\n", 1)[0].strip()
    return first if first and "<" not in first and _TABLE_CAPTION.match(first) else ""


def reading_directory(store, pairs):
    """Keep saved body and table locations, types, captions and parent order."""
    directory = {}
    for pair in pairs:
        entries = []
        for parent in (store.get_version_parents(*pair) if hasattr(store, "get_version_parents") else []):
            content_type = parent.get("content_type")
            if content_type not in ("body", "table"):
                continue
            entry = {"section_path": deepcopy(parent.get("section_path", [])), "parent_id": parent["parent_id"],
                     "pdf_pages": list(dict.fromkeys(s["pdf_page"] for s in parent.get("source_spans", []))),
                     "content_type": content_type}
            if content_type == "table":
                entry["caption"] = _table_caption(parent)
            entries.append(entry)
        directory[pair] = entries
    return directory


def retain_explicit_context(context, rows, *, source_registry=None, target_ids=(), required_rows=()):
    """Current targets, prepared-fact originals, then earlier reads/background."""
    by_id = {row["chunk_id"]: row for row in rows}
    ordered = [by_id[identifier] for identifier in target_ids if identifier in by_id]
    ordered += list(required_rows)
    ordered += list(reversed(rows))
    ordered += [{**row, "text": row["shown_text"]} for row in context["shown_evidence"]]
    candidates, seen = [], set()
    for row in ordered:
        if row["chunk_id"] in seen:
            continue
        seen.add(row["chunk_id"])
        candidates.append({**row, "score": row.get("score", None if row.get("parent_id") else 0.0)})
    candidates = [{**row, "rank": index} for index, row in enumerate(candidates, 1)]
    pairs = [(v["paper_id"], v["parse_revision"]) for v in context["selected_versions"]]
    selected = select_context(candidates, pairs, max_chars=context["max_chars"],
                             **token_context_options(context=context, registry=source_registry, candidates=candidates))
    selected.update(question=context["question"], score_kind=context.get("score_kind", "cosine"),
                    ranking_method=context.get("ranking_method", "cosine"))
    selected["reading_origins"] = [origin for row in selected["shown_evidence"] for origin in row.get("reading_origins", [])]
    return selected


def read_evidence_context(context, version_chunks, *, max_chunks=5,
                          source_registry=None, source_requirement=None, anchors_first=False,
                          store=None):
    """Keep anchors, then read saved parent children within the shared budget.

    Legacy chunks retain the existing small adjacent-chunk reading window.
    """
    anchors = [{**row, "text": row["shown_text"]} for row in context["shown_evidence"]]
    if not anchors:
        return {**deepcopy(context), "reading_origins": []}
    retrieved = {row["chunk_id"]: row for row in anchors}
    retained, origins, seen = [], deepcopy(context.get("reading_origins", [])), set()
    pairs = [(v["paper_id"], v["parse_revision"]) for v in context["selected_versions"]]
    abstract_only = source_requirement is not None and source_requirement["required_scope"] == "abstract"
    options = token_context_options(registry=source_registry, context=context, candidates=anchors)
    structured = bool(options)
    parent_store = source_registry if source_registry is not None else store
    read_parents = set()

    def append(row, anchor=None, parent_id=None):
        if row["chunk_id"] in seen:
            return
        seen.add(row["chunk_id"])
        retained.append({**row, "rank": len(retained) + 1})
        if anchor is not None and row["chunk_id"] not in retrieved:
            if parent_id is not None:
                origin = {"chunk_id": row["chunk_id"], "anchor_chunk_id": anchor["chunk_id"],
                          "parent_id": parent_id, "anchor_score": anchor["score"],
                          "kind": "parent_context_read"}
                origins.append(origin)
                retained[-1]["reading_origins"] = [deepcopy(origin)]
            else:
                origins.append({"chunk_id": row["chunk_id"], "anchor_chunk_id": anchor["chunk_id"],
                                "score_basis": "anchor_retrieval_score", "kind": "adjacent_body_read"})

    if anchors_first or structured:
        for anchor in anchors:
            append(anchor)

    for anchor in anchors:
        append(anchor)
        chunks = version_chunks[(anchor["paper_id"], anchor["parse_revision"])]
        if anchor.get("parent_id"):
            parent_id = anchor["parent_id"]
            if parent_id in read_parents:
                continue
            read_parents.add(parent_id)
            parent = parent_store.get_parent(parent_id) if parent_store is not None else None
            if parent is None:
                continue
            _, children = parent_children(parent_id, version_chunks, parent_store, parent=parent)
            for row in children:
                identifier = row["chunk_id"]
                if abstract_only and not source_registry.qualify(row)["eligible"]:
                    continue
                append(retrieved.get(identifier, {**row, "score": None}), anchor, parent_id)
            continue
        index = next(i for i, row in enumerate(chunks) if row["chunk_id"] == anchor["chunk_id"])
        heading, previous, added = _heading(anchor["text"]), chunks[index], 0
        # The window stays on the same page and stops at a new section heading.
        for row in chunks[index + 1:index + 4]:
            if row["pdf_page"] != anchor["pdf_page"] or _heading(row["text"]):
                break
            continuation = (row["segment_id"] == previous["segment_id"]
                            and previous["char_start"] < row["char_start"] <= previous["char_end"]
                            and row["char_end"] > previous["char_end"])
            if not heading and not continuation:
                break
            if len(row["text"].strip()) < 80:
                continue
            if abstract_only and not source_registry.qualify(row)["eligible"]:
                break
            candidate = retrieved.get(row["chunk_id"], {**row, "score": anchor["score"]})
            append(candidate, anchor)
            previous, added = row, added + 1
            if added == 2:
                break
    selected = {**select_context(retained if structured else retained[:max_chunks], pairs,
                                max_chars=context["max_chars"], **options),
                "question": context["question"],
                "score_kind": context.get("score_kind", "cosine"),
                "ranking_method": context.get("ranking_method", context.get("score_kind", "cosine"))}
    selected["reading_origins"], origin_ids = [], set()
    for origin in origins:
        identifier = origin["chunk_id"]
        if identifier in selected["allowed_citation_ids"] and identifier not in origin_ids:
            selected["reading_origins"].append(deepcopy(origin))
            origin_ids.add(identifier)
    return selected
