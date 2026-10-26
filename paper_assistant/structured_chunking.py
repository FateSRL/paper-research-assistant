"""Structure-aware parent contexts and page-local, source-backed children."""

from copy import deepcopy
import re

from paper_assistant.chunking import sha256_bytes


STRUCTURED_CHUNKER_REVISION = "structured-pdf-v2"
_BODY = {"text", "paragraph", "body", "list", "list_item", "formula", "equation", "display_formula"}
_SKIP = {"header", "footer", "page_header", "page_footer", "reference", "references", "bibliography"}
_HEADINGS = {"heading", "title", "section_header", "section_title"}
_SENTENCE_END = re.compile(r"(?<=[.!?。！？;；])\s+")
_MATH = re.compile(r"\$\$[\s\S]*?\$\$|(?<!\\)\$(?:\\.|[^$])*?(?<!\\)\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]")


def _source(unit, start, end, *, field="text"):
    field_sources = unit.get("field_sources", {})
    if field in field_sources:
        spans = []
        for source in field_sources[field]:
            left, right = max(start, source["field_start"]), min(end, source["field_end"])
            if left >= right:
                continue
            base = source.get("source_char_start", 0)
            available = source.get("source_char_available", unit.get("source_char_available", True)) and base is not None
            spans.append({"block_id": source["block_id"], "pdf_page": source.get("pdf_page", unit["pdf_page"]),
                "bbox": deepcopy(source.get("bbox")), "page_size": deepcopy(source.get("page_size", unit.get("page_size"))),
                "coordinate_system": source.get("coordinate_system", unit.get("coordinate_system")),
                "content_type": source.get("content_type", source.get("type", unit.get("type", "text"))),
                "source_field": source.get("source_field", field),
                "source_char_start": base + left - source["field_start"] if available else None,
                "source_char_end": base + right - source["field_start"] if available else None,
                "text_start": left - start, "text_end": right - start})
        return spans
    available = unit.get("source_char_available", True)
    return [{"block_id": unit["block_id"], "pdf_page": unit["pdf_page"],
            "bbox": deepcopy(unit.get("bbox")), "page_size": deepcopy(unit.get("page_size")),
            "coordinate_system": unit.get("coordinate_system"), "content_type": unit.get("type", "text"),
            "source_field": field, "source_char_start": start if available else None,
            "source_char_end": end if available else None, "text_start": 0, "text_end": end - start}]


def _part(unit, text, start=0, end=None, *, field="text", separator=""):
    end = len(text) if end is None else end
    return {"text": text[start:end], "source_spans": _source(unit, start, end, field=field),
            "pdf_page": unit["pdf_page"], "separator": separator,
            "assets": deepcopy(unit.get("assets", []))}


def _join(parts):
    text, spans = "", []
    for part in parts:
        if text:
            text += part["separator"]
        offset = len(text)
        text += part["text"]
        spans.extend({**deepcopy(span), "text_start": span["text_start"] + offset,
                      "text_end": span["text_end"] + offset} for span in part["source_spans"])
    return text, spans


def _slice(part, start, end, *, separator=""):
    spans = []
    for span in part["source_spans"]:
        left, right = max(start, span["text_start"]), min(end, span["text_end"])
        if left >= right:
            continue
        selected = {**deepcopy(span), "text_start": left - start, "text_end": right - start}
        if span["source_char_start"] is not None:
            selected["source_char_start"] = span["source_char_start"] + left - span["text_start"]
            selected["source_char_end"] = span["source_char_start"] + right - span["text_start"]
        spans.append(selected)
    return {**part, "text": part["text"][start:end], "source_spans": spans, "separator": separator}


def _transcription(unit, *, separator=""):
    """Remove line-break hyphens while preserving the surviving parser ranges."""
    text, parts, start = unit.get("text", ""), [], 0
    math_ranges = [(match.start(), match.end()) for match in _MATH.finditer(text)]
    for match in re.finditer(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", text):
        if any(left <= match.start() < right for left, right in math_ranges):
            continue
        if start < match.start():
            parts.append(_part(unit, text, start, match.start()))
        start = match.end()
    if start < len(text):
        parts.append(_part(unit, text, start))
    joined, spans = _join(parts)
    return {"text": joined, "source_spans": spans, "pdf_page": unit["pdf_page"],
            "separator": separator, "assets": deepcopy(unit.get("assets", []))}


def _text_parts(part, count_tokens, limit):
    """Prefer sentence ends, then word boundaries, for oversized prose."""
    text, start, parts = part["text"], 0, []
    math_ranges = [(match.start(), match.end()) for match in _MATH.finditer(text)]
    while start < len(text):
        if count_tokens(text[start:]) <= limit:
            end = len(text)
        else:
            low, high = start + 1, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if count_tokens(text[start:middle]) <= limit:
                    low = middle
                else:
                    high = middle - 1
            end = low
            sentences = [match.end() for match in _SENTENCE_END.finditer(text, start, end)]
            words = [match.end() for match in re.finditer(r"\s+", text[start:end])]
            if sentences:
                end = sentences[-1]
            elif words:
                end = start + words[-1]
            for left, right in math_ranges:
                if left < end < right:
                    end = left if left > start else right
                    break
        parts.append(_slice(part, start, end, separator=part["separator"] if not parts else ""))
        start = end
    return parts


def _list_parts(part, count_tokens, limit):
    starts = [match.start() for match in re.finditer(r"(?m)^[ \t]*(?:[-*•]|\d+[.)])[ \t]+", part["text"])]
    boundaries = [0, *[start for start in starts if start], len(part["text"])]
    return [fragment for start, end in zip(boundaries, boundaries[1:])
            for fragment in _text_parts(_slice(part, start, end,
                separator=part["separator"] if start == 0 else ""), count_tokens, limit)]


def _table_parts(unit, count_tokens, child_tokens):
    table = unit.get("table")
    html = (table.get("html") if isinstance(table, dict) else table) or unit.get("table_html") or unit.get("text", "")
    field = ("table.html" if isinstance(table, dict) and table.get("html") else "table" if table
             else "table_html" if unit.get("table_html") else "text")
    rows = list(re.finditer(r"<tr\b[^>]*>.*?</tr\s*>", html, re.I | re.S))
    if not rows:
        return [[_part(unit, html, field=field)]], [_part(unit, html, field=field)]
    headers = []
    for row in rows:
        if re.search(r"<th\b", row.group(), re.I) or not headers and row is rows[0]:
            headers.append(row)
        else:
            break
    prefix = []
    caption = unit.get("caption") or (table.get("caption") if isinstance(table, dict) else None)
    if isinstance(caption, str) and caption.strip():
        prefix.append(_part(unit, caption, field="caption" if unit.get("caption") else "table.caption"))
    footnotes = unit.get("footnotes") or (table.get("footnotes") if isinstance(table, dict) else None)
    suffix = ([_part(unit, footnotes, field="footnotes" if unit.get("footnotes") else "table.footnotes", separator="\n")]
              if isinstance(footnotes, str) and footnotes.strip() else [])
    header_parts = [_part(unit, html, row.start(), row.end(), field=field, separator="\n") for row in headers]
    chunks, current = [], [*prefix, *header_parts]
    for row in rows[len(headers):]:
        part = _part(unit, html, row.start(), row.end(), field=field, separator="\n")
        if len(current) > len(prefix) + len(header_parts) and count_tokens(_join([*current, part, *suffix])[0]) > child_tokens:
            chunks.append([*current, *suffix])
            current = [*prefix, *header_parts]
        current.append(part)
    if current:
        chunks.append([*current, *suffix])
    all_parts = [*prefix, *[_part(unit, html, row.start(), row.end(), field=field, separator="\n") for row in rows], *suffix]
    return chunks, all_parts


def build_structured_chunks(units, paper, parse_revision, *, count_tokens, child_tokens=512, parent_tokens=1536):
    """Keep real parser blocks, source ranges and page boundaries separate."""
    groups, pending, pending_section, interrupted = [], [], None, False

    def body_group():
        nonlocal pending
        current = []
        for part in pending:
            if current and count_tokens(_join([*current, part])[0]) > parent_tokens:
                groups.append({"parts": current, "section_path": pending_section,
                               "content_type": "body", "order": current[0]["order"]})
                current = []
            current.append(part)
        if current:
            groups.append({"parts": current, "section_path": pending_section,
                           "content_type": "body", "order": current[0]["order"]})
        pending = []

    for order, unit in enumerate(units):
        kind = unit.get("type", "text").lower()
        section = deepcopy(unit.get("section_path", []))
        if kind in _SKIP:
            continue
        if pending and section != pending_section:
            body_group()
        if kind in _HEADINGS:
            continue
        if kind in _BODY:
            raw = unit.get("text", "")
            if not raw.strip():
                continue
            continues = unit.get("continues_prev")
            if continues is None:
                continues = bool(pending and not re.search(r"[.!?。！？:]\s*$", pending[-1]["text"])
                                 and raw.lstrip()[:1].islower())
            if interrupted and pending and not continues:
                body_group()
            separator = " " if continues else "\n\n"
            if pending and continues and pending[-1]["text"].endswith("-"):
                pending[-1] = _slice(pending[-1], 0, len(pending[-1]["text"]) - 1,
                                     separator=pending[-1]["separator"])
                separator = ""
            atomic = kind in {"formula", "equation", "display_formula"}
            part = _part(unit, raw, separator=separator) if atomic else _transcription(unit, separator=separator)
            part["order"] = order
            parts = ([part] if atomic else _list_parts(part, count_tokens, child_tokens)
                     if kind in {"list", "list_item"} else _text_parts(part, count_tokens, child_tokens))
            pending.extend(parts)
            pending_section, interrupted = section, False
            continue
        if kind == "table":
            table_chunks, table_parts = _table_parts(unit, count_tokens, child_tokens)
            groups.append({"parts": table_parts, "child_parts": table_chunks, "section_path": section,
                           "content_type": "table", "order": order, "table": deepcopy(unit.get("table")),
                           "table_html": unit.get("table_html")})
        elif kind in {"image", "figure", "caption", "figure_caption"}:
            fields = ("caption", "footnotes") if kind in {"image", "figure"} else ("text",)
            parts = [_part(unit, unit[field], field=field, separator="\n" if index else "")
                     for index, field in enumerate(fields)
                     if isinstance(unit.get(field), str) and unit[field].strip()]
            if parts:
                groups.append({"parts": parts, "section_path": section,
                               "content_type": "image", "order": order})
        interrupted = bool(pending)
    body_group()

    parents, chunks, page_counts = [], [], {}
    identity = {key: deepcopy(paper[key]) for key in
                ("paper_id", "pdf_sha256", "title", "arxiv_version", "source_url", "local_path") if key in paper}
    for index, group in enumerate(sorted(groups, key=lambda row: row["order"]), 1):
        parent_id = f"{paper['paper_id']}_{parse_revision}_parent{index}"
        text, spans = _join(group["parts"])
        parent = {"parent_id": parent_id, "paper_id": paper["paper_id"], "parse_revision": parse_revision,
                  "section_path": deepcopy(group["section_path"]), "content_type": group["content_type"],
                  "text": text, "source_spans": spans, "child_ids": [], "token_count": count_tokens(text)}
        parent["content_types"] = list(dict.fromkeys(span["content_type"] for span in spans))
        if "table" in group:
            parent["table"] = group["table"]
        if group.get("table_html"):
            parent["table_html"] = group["table_html"]
        if spans and spans[0]["content_type"] in {"formula", "equation", "display_formula"}:
            previous = next((row for row in reversed(parents) if row["content_type"] == "body"
                             and row["section_path"] == parent["section_path"]), None)
            if previous is not None:
                parent["related_parent_ids"] = [previous["parent_id"]]
                previous.setdefault("related_parent_ids", []).append(parent_id)
        assets = [asset for part in group["parts"] for asset in part.get("assets", [])]
        if assets:
            parent["assets"] = assets
        child_groups, current = group.get("child_parts", []), []
        if "child_parts" not in group:
            for part in group["parts"]:
                if current and (part["pdf_page"] != current[0]["pdf_page"]
                        or count_tokens(_join([*current, part])[0]) > child_tokens):
                    child_groups.append(current)
                    current = []
                current.append(part)
            if current:
                child_groups.append(current)
        for parts in child_groups:
            child_text, child_spans = _join(parts)
            page = parts[0]["pdf_page"]
            page_counts[page] = page_counts.get(page, 0) + 1
            identifier = f"{paper['paper_id']}_{parse_revision}_p{page}_c{page_counts[page]}"
            assets = [asset for part in parts for asset in part.get("assets", [])]
            child = {**identity, "chunk_id": identifier, "parse_revision": parse_revision,
                "pdf_page": page, "parent_id": parent_id, "section_path": deepcopy(group["section_path"]),
                "content_type": group["content_type"], "source_spans": child_spans, "text": child_text,
                "text_sha256": sha256_bytes(child_text.encode("utf-8")), "filter_revision": STRUCTURED_CHUNKER_REVISION,
                "token_count": count_tokens(child_text)}
            if assets:
                child["assets"] = deepcopy(assets)
            child["content_types"] = list(dict.fromkeys(span["content_type"] for span in child_spans))
            if group["content_type"] == "body" and all(kind in {"formula", "equation", "display_formula"}
                    for kind in child["content_types"]):
                child["content_type"] = "formula"
            if child["token_count"] > child_tokens:
                child["oversized_structure"] = True
            chunks.append(child)
            parent["child_ids"].append(identifier)
        parents.append(parent)
    return {"parents": parents, "chunks": chunks}
