"""QASPER v0.3 selection, deterministic paragraph mapping and offline scoring.

Dataset: https://huggingface.co/datasets/allenai/qasper (CC BY 4.0).
Metrics follow https://github.com/allenai/qasper-led-baseline/blob/main/scripts/evaluator.py.
Annotations and paragraph mappings are post-hoc evaluation data only.
"""

from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import json
import random
import re
import string
import unicodedata


EVALUATION_PROTOCOL = "qasper-direct-answer-abstract-v1"


def _paragraph_text_positions(text):
    """Normalize presentation while retaining each expanded character's source span."""
    removed = set()
    for match in re.finditer(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", text):
        removed.update(range(match.start(), match.end()))
    expanded = []
    punctuation = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                "−": "-", "–": "-", "—": "-"})
    for index, character in enumerate(text):
        if index not in removed and character != "\u00ad":
            expanded.extend((part, (index, index + 1))
                            for part in unicodedata.normalize("NFKC", character).translate(punctuation))
    characters, positions = [], []
    whitespace_start = None
    for index, (character, span) in enumerate(expanded):
        if (character == "-" and index and index + 1 < len(expanded)
                and expanded[index - 1][0].isalpha() and expanded[index + 1][0].isalpha()):
            continue
        if character.isspace():
            if characters and whitespace_start is None:
                whitespace_start = span[0]
            continue
        if whitespace_start is not None:
            characters.append(" ")
            positions.append((whitespace_start, span[0]))
            whitespace_start = None
        characters.append(character)
        positions.append(span)
    adjacent_punctuation = set(".,;:!?()[]{}=+*/<>")
    retained = [index for index, character in enumerate(characters)
                if character != " " or not ((index and characters[index - 1] in adjacent_punctuation)
                    or (index + 1 < len(characters) and characters[index + 1] in adjacent_punctuation))]
    return "".join(characters[index] for index in retained), [positions[index] for index in retained]


_PARAGRAPH_DIFFERENCES = re.compile(
    r'BIBREF\d+|(?:Sec\.|Section)\s*"[^"]+"|(?:Sec\.|Section)\s*\d+(?:\.\d+)*'
    r"|(?<=Equation )\d+|(?<=Equation)\d+"
    r"|\$\$[\s\S]*?\$\$|\$(?:\\.|[^$])*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]")
_AUTHOR_NAME = r"[A-Z][^\W\d_]+(?:['-][^\W\d_]+)*"
_AUTHOR_GROUP = rf"{_AUTHOR_NAME}(?:\s+et\s+al\.|\s*(?:&|and)\s*{_AUTHOR_NAME})?"
_AUTHOR_YEAR = rf"{_AUTHOR_GROUP},?\s*(?:19|20)\d{{2}}[a-z]?"
_PDF_CITATIONS = re.compile(
    rf"\({_AUTHOR_YEAR}(?:;\s*{_AUTHOR_YEAR})*\)|{_AUTHOR_GROUP}\s*\((?:19|20)\d{{2}}[a-z]?\)"
    r"|(?:Sec\.|Section)\s*\d+(?:\.\d+)*|(?<=Equation )\d+|(?<=Equation)\d+")


def _mapping_words(text, omitted):
    return [(match.group(), match.start(), match.end()) for match in re.finditer(r"[^\W_]+", text)
            if not any(start <= match.start() < end for start, end in omitted)]


def _formula_representation(text):
    """Compare a small literal representation, without reconstructing lost mathematics."""
    text = re.sub(r"\\(?:left|right|mathbf|mathrm|text|operatorname)\b", "", text)
    text = re.sub(r"\\(?:h?dots|cdots)\b", "...", text)
    text = text.replace(r"\(", "").replace(r"\)", "").replace(r"\[", "").replace(r"\]", "")
    return re.sub(r"[\s${}_]", "", text)


def _complete_word_alignment(words, source_words, start, end):
    blocks = SequenceMatcher(None, words, [word[0] for word in source_words[start:end]],
                             autojunk=False).get_matching_blocks()
    if sum(block.size for block in blocks) != len(words):
        return None
    return [start + block.b + index for block in blocks for index in range(block.size)]


def _edge_prose(words, source_words, boundary, *, before):
    if not words:
        return []
    adjacent = boundary - 1 if before else boundary
    if not 0 <= adjacent < len(source_words):
        return None
    segment = source_words[boundary if before else boundary - 1][3]
    start, end = boundary, boundary
    if before:
        while start and source_words[start - 1][3] == segment:
            start -= 1
    else:
        while end < len(source_words) and source_words[end][3] == segment:
            end += 1
    matched = _complete_word_alignment(words, source_words, start, end)
    if matched is not None:
        return matched
    # A short continuation after a table must itself be a complete literal run.
    if len(words) < 2:
        return None
    matches = []
    indices = range(0, boundary - len(words) + 1) if before else range(boundary, len(source_words) - len(words) + 1)
    for index in indices:
        if [word[0] for word in source_words[index:index + len(words)]] != words:
            continue
        at_edge = (index + len(words) == len(source_words)
                   or source_words[index + len(words)][3] != source_words[index][3]) if before else (
                   index == 0 or source_words[index - 1][3] != source_words[index][3])
        if at_edge:
            matches.append(list(range(index, index + len(words))))
    return matches[0] if len(matches) == 1 else None


def _ordered_paragraph_spans(text, source, source_words, anchors, continuations):
    """Require all ordinary prose in order, anchored at both ends and uniquely located."""
    omitted = [(match.start(), match.end()) for match in _PARAGRAPH_DIFFERENCES.finditer(text)]
    words = _mapping_words(text, omitted)
    # Four literal words at each end exclude short headings and formula-only fragments.
    if len(words) < 8:
        return [], False
    math_ranges = [(match.start(), match.end()) for match in _PARAGRAPH_DIFFERENCES.finditer(text)
                   if match.group().startswith(("$", r"\(", r"\["))]
    available = [index for index in range(len(words) - 3)
                 if not any(start < words[index + 3][2] and end > words[index][1] for start, end in math_ranges)
                 and tuple(word[0] for word in words[index:index + 4]) in anchors]
    if not available or available[-1] < available[0] + 4:
        return [], False
    first_index = available[0]
    first = anchors[tuple(word[0] for word in words[first_index:first_index + 4])]
    found = []
    for left in first:
        possible_last = [index for index in available if index >= first_index + 4 and any(
            position >= left + 4 for position in anchors[tuple(word[0] for word in words[index:index + 4])])]
        if not possible_last:
            continue
        last_index = possible_last[-1]
        last = anchors[tuple(word[0] for word in words[last_index:last_index + 4])]
        middle = [word[0] for word in words[first_index + 4:last_index]]
        for right in last:
            if right < left + 4 or "\0" in source[source_words[left][1]:source_words[right + 3][2]]:
                continue
            matched_middle = _complete_word_alignment(middle, source_words, left + 4, right)
            prefix = _edge_prose([word[0] for word in words[:first_index]], source_words, left, before=True)
            suffix = _edge_prose([word[0] for word in words[last_index + 4:]], source_words, right + 4, before=False)
            if matched_middle is None or prefix is None or suffix is None:
                continue
            matched = [*prefix, *range(left, left + 4), *matched_middle, *range(right, right + 4), *suffix]
            if matched not in found:
                found.append(matched)
    # A window containing an already complete smaller alignment is not another occurrence.
    found = [match for match in found if not any(
        other[0] >= match[0] and other[-1] <= match[-1]
        and (other[0], other[-1]) != (match[0], match[-1]) for other in found)]
    if len(found) > 1:
        return [], True
    if not found:
        return [], False
    matched = found[0]
    runs, run_start = [], 0
    for index in matched:
        runs.extend(continuations.get(source_words[index][1], []))
    for index in range(1, len(matched) + 1):
        if index < len(matched) and matched[index] == matched[index - 1] + 1:
            query_gap = text[words[index - 1][2]:words[index][1]]
            if not any(marker in query_gap for marker in ("$", r"\(", r"\[")):
                continue
        start, end = source_words[matched[run_start]][1], source_words[matched[index - 1]][2]
        prefix = text[words[run_start - 1][2] if run_start else 0:words[run_start][1]].strip()
        suffix = text[words[index - 1][2]:words[index][1] if index < len(words) else len(text)].strip()
        if prefix and not re.search(r"\w", prefix) and source[max(0, start - len(prefix)):start] == prefix:
            start -= len(prefix)
        if suffix and not re.search(r"\w", suffix) and source[end:end + len(suffix)] == suffix:
            end += len(suffix)
        runs.append((start, end))
        run_start = index
    # Include a formula's source characters only when its actual representation agrees.
    for index in range(1, len(words)):
        query_gap = text[words[index - 1][2]:words[index][1]]
        if "$" not in query_gap and r"\(" not in query_gap and r"\[" not in query_gap:
            continue
        start, end = source_words[matched[index - 1]][2], source_words[matched[index]][1]
        if _formula_representation(query_gap) == _formula_representation(source[start:end]):
            runs.append((start, end))
    return sorted(runs), False


def _structured_source_characters(parts):
    """Reconstruct saved child slices; internal offsets are never PDF offsets."""
    characters, references, conflict, joined_offsets = {}, {}, False, set()
    assembled = ""
    previous = None
    for chunk, span in parts:
        left, right = span["text_start"], span["text_end"]
        text = chunk["text"][left:right]
        source_start = span.get("source_char_start")
        if type(source_start) is int:
            offset = source_start
            if (previous is not None and previous[0] == chunk["chunk_id"]
                    and previous[1]["text_end"] == left
                    and type(previous[1].get("source_char_end")) is int
                    and previous[1]["source_char_end"] < source_start):
                joined_offsets.add((previous[1]["source_char_end"] - 1, source_start))
        else:
            matches = [match.start() for match in re.finditer(re.escape(text), assembled)] if text else []
            if len(matches) == 1:
                offset = matches[0]
            else:
                overlap = next((size for size in range(min(len(assembled), len(text)), 0, -1)
                    if assembled.endswith(text[:size]) and (size >= 16 or len(text[:size].split()) >= 4)), 0)
                if overlap:
                    offset = len(assembled) - overlap
                else:
                    offset = len(assembled) + (1 if assembled else 0)
                    if assembled:
                        characters[len(assembled)] = "\n"
                        assembled += "\n"
                assembled += text[len(assembled) - offset:]
        for index, character in enumerate(text):
            position = offset + index
            if position in characters and characters[position] != character:
                conflict = True
            characters[position] = character
            references.setdefault(position, []).append({
                "chunk_id": chunk["chunk_id"], "text_start": left + index, "text_end": left + index + 1,
                "block_id": span["block_id"], "source_field": span.get("source_field", "text"),
                "pdf_page": span.get("pdf_page", chunk.get("pdf_page")),
                "bbox": deepcopy(span.get("bbox")), "page_size": deepcopy(span.get("page_size")),
                "coordinate_system": span.get("coordinate_system"),
                "content_type": span.get("content_type", chunk.get("content_type")),
                "source_char_start": source_start + index if type(source_start) is int else None,
                "source_char_end": source_start + index + 1 if type(source_start) is int else None,
            })
        previous = chunk["chunk_id"], span
    return characters, references, conflict, joined_offsets


def _parent_word_seams(parents, sources):
    """Only saved parent/source boundaries can prove a removed cross-page hyphen."""
    by_block = {source["block_id"]: source for source in sources}
    seams = []
    for parent in parents:
        spans = parent.get("source_spans", [])
        for left, right in zip(spans, spans[1:]):
            left_source, right_source = by_block.get(left["block_id"]), by_block.get(right["block_id"])
            end, start = left["text_end"], right["text_start"]
            if (left["pdf_page"] == right["pdf_page"] or end != start or not end
                    or start >= len(parent["text"]) or not parent["text"][end - 1:start + 1].isalpha()
                    or not left_source or not right_source or right_source.get("continues_prev") is not True
                    or left.get("source_field") != "text" or right.get("source_field") != "text"):
                continue
            source_end, source_start = left.get("source_char_end"), right.get("source_char_start")
            if (type(source_end) is not int or type(source_start) is not int
                    or left_source["text"][source_end:] != "-"
                    or parent["text"][left["text_start"]:end] != left_source["text"][left["source_char_start"]:source_end]
                    or parent["text"][start:right["text_end"]] != right_source["text"][source_start:right["source_char_end"]]):
                continue
            seams.append({"left": left, "right": right, "parent_id": parent["parent_id"],
                          "child_ids": set(parent.get("child_ids", []))})
    return seams


def _attribution_ranges(text, source, literal_ranges):
    """Attribute known presentation differences only inside a located prose boundary."""
    ranges = list(literal_ranges)
    if not ranges:
        return []
    left, right = min(start for start, _ in ranges), max(end for _, end in ranges)
    differences = list(_PARAGRAPH_DIFFERENCES.finditer(text))
    query_words = _mapping_words(text, [(match.start(), match.end()) for match in differences])
    if not query_words:
        return ranges
    citations = list(_PDF_CITATIONS.finditer(source))
    query_citations = any(match.group().startswith("BIBREF") for match in differences)
    query_math = any(match.group().startswith(("$", r"\(", r"\[")) for match in differences)
    accepted = []
    if query_citations:
        prefix_citation = "BIBREF" in text[:query_words[0][1]]
        suffix_citation = "BIBREF" in text[query_words[-1][2]:]
        for match in citations:
            if (left <= match.start() and match.end() <= right
                    or prefix_citation and match.end() <= left and not re.search(r"\w", source[match.end():left])
                    or suffix_citation and match.start() >= right and not re.search(r"\w", source[right:match.start()])):
                accepted.append((match.start(), match.end()))
    if query_math:
        accepted.extend((match.start(), match.end()) for match in _PARAGRAPH_DIFFERENCES.finditer(source)
                        if match.group().startswith(("$", r"\(", r"\["))
                        and left <= match.start() and match.end() <= right)
    ranges.extend(accepted)
    # Punctuation between established pieces belongs to those pieces; ordinary prose does not.
    ordered = sorted(ranges)
    for (_, end), (start, _) in zip(ordered, ordered[1:]):
        if end < start and not re.search(r"\w", source[end:start]):
            ranges.append((end, start))
    left, right = min(start for start, _ in ranges), max(end for _, end in ranges)
    prefix = _PARAGRAPH_DIFFERENCES.sub("", text[:query_words[0][1]]).strip()
    suffix = _PARAGRAPH_DIFFERENCES.sub("", text[query_words[-1][2]:]).strip()
    if prefix and not re.search(r"\w", prefix) and source[max(0, left - len(prefix)):left] == prefix:
        ranges.append((left - len(prefix), left))
    if suffix and not re.search(r"\w", suffix) and source[right:right + len(suffix)] == suffix:
        ranges.append((right, right + len(suffix)))
    return ranges


def _abstract_matching_view(text):
    """Fold presentation only, retaining offsets into the normalized source text."""
    characters, positions = [], []
    for index, character in enumerate(text):
        if character == "\\" and index + 1 < len(text) and text[index + 1].isalnum():
            continue
        folded = character.casefold()
        characters.extend(folded)
        positions.extend([(index, index + 1)] * len(folded))
    return "".join(characters), positions


def build_paragraph_mapping(full_text, chunks, *, parents=None, sources=None, abstract=None):
    """Match whole original paragraphs against position-backed PDF chunk text."""
    parents, sources = parents or [], sources or []
    seams = _parent_word_seams(parents, sources)
    paragraphs = [{"paragraph_id": f"s{section_index}:p{paragraph_index}", "text": text,
                   "section_index": section_index, "paragraph_index": paragraph_index,
                   "section_name": section.get("section_name", ""), "status": "unresolved",
                   "chunk_ids": [], "positions": []}
                  for section_index, section in enumerate(full_text)
                  for paragraph_index, text in enumerate(section.get("paragraphs", []))]
    normalized_paragraphs = [_paragraph_text_positions(row["text"])[0] for row in paragraphs]
    original_counts = Counter(normalized_paragraphs)
    chunk_records, segments = {}, {}
    for index, chunk in enumerate(chunks):
        identifier = chunk["chunk_id"]
        position = {name: deepcopy(chunk[name]) for name in
                    ("segment_id", "char_start", "char_end", "pdf_page", "source_block_index",
                     "source_line_indices", "segment_bbox") if name in chunk}
        chunk_records[identifier] = {"status": "unresolved", "paragraph_ids": [],
            "pdf_page": chunk.get("pdf_page"), "positions": [position], "reason": "unmapped_text"}
        if "source_spans" in chunk:
            record = chunk_records[identifier]
            record.update(positions=deepcopy(chunk["source_spans"]),
                          content_type=chunk.get("content_type"), section_path=deepcopy(chunk.get("section_path", [])),
                          source_roles=list(dict.fromkeys(span.get("content_type", chunk.get("content_type", "unknown"))
                              for span in chunk["source_spans"])))
            if not chunk["source_spans"]:
                record["reason"] = "missing_text_positions"
            for span in chunk["source_spans"]:
                known = type(span.get("source_char_start")) is int
                key = (span["block_id"], span.get("source_field", "text"),
                       span.get("pdf_page", chunk.get("pdf_page")), tuple(span.get("bbox") or []), known)
                segment = segments.setdefault(key, {"chunks": [], "parts": [], "structured": True,
                    "first_index": len(segments), "pdf_page": span.get("pdf_page", chunk.get("pdf_page")),
                    "source_block_index": index})
                segment["chunks"].append(chunk)
                segment["parts"].append((chunk, span))
            continue
        start, end = chunk.get("char_start"), chunk.get("char_end")
        if (not chunk.get("segment_id") or type(start) is not int or type(end) is not int
                or start < 0 or end - start != len(chunk["text"])):
            chunk_records[identifier]["reason"] = "missing_text_positions"
            continue
        segment = segments.setdefault(chunk["segment_id"], {"chunks": [], "first_index": index,
            "pdf_page": chunk.get("pdf_page"), "source_block_index": chunk.get("source_block_index", index)})
        segment["chunks"].append(chunk)

    document, origins = [], []
    ordered_segments = (list(segments.items()) if any(row.get("structured") for row in segments.values()) else
        sorted(segments.items(), key=lambda item:
            (item[1]["pdf_page"] or 0, item[1]["source_block_index"], item[1]["first_index"])))
    for segment_id, segment in ordered_segments:
        characters, conflict = {}, False
        if segment.get("structured"):
            characters, segment["references"], conflict, segment["joined_offsets"] = _structured_source_characters(segment["parts"])
        else:
            for chunk in segment["chunks"]:
                for offset, character in enumerate(chunk["text"], chunk["char_start"]):
                    if offset in characters and characters[offset] != character:
                        conflict = True
                    characters[offset] = character
        if document:
            # A layout boundary is whitespace, not proof of a continuous hyphenated word.
            document.append("\u2028")
            origins.append(None)
        if conflict:
            document.append("\0")
            origins.append(None)
            for chunk in segment["chunks"]:
                chunk_records[chunk["chunk_id"]]["reason"] = "overlap_text_conflict"
            continue
        previous = None
        for offset in sorted(characters):
            if (previous is not None and offset != previous + 1
                    and (previous, offset) not in segment.get("joined_offsets", set())):
                # Unknown intervening PDF characters cannot become a text match.
                document.append("\0")
                origins.append(None)
            document.append(characters[offset])
            origins.append((segment_id, offset))
            previous = offset
    normalized_document, normalized_positions = _paragraph_text_positions("".join(document))
    citations = [(match.start(), match.end()) for match in _PDF_CITATIONS.finditer(normalized_document)]
    source_words = _mapping_words(normalized_document, citations)
    source_words = [(*word, origins[normalized_positions[word[1]][0]][0]) for word in source_words]
    ordinary_words = {word[0] for text in normalized_paragraphs for word in _mapping_words(text,
        [(match.start(), match.end()) for match in _PARAGRAPH_DIFFERENCES.finditer(text)])}
    continuations, replaced, joined = {}, set(), {}
    for seam in seams:
        def boundary_word(span, *, at_end):
            matches = []
            source_offset = span["source_char_end"] if at_end else span["source_char_start"]
            for index, word in enumerate(source_words):
                raw_index = normalized_positions[word[2] - 1 if at_end else word[1]][0]
                origin = origins[raw_index]
                if origin is None or not segments[origin[0]].get("structured"):
                    continue
                references = segments[origin[0]]["references"].get(origin[1], [])
                if any(reference["block_id"] == span["block_id"]
                       and reference["source_field"] == span["source_field"]
                       and reference["pdf_page"] == span["pdf_page"]
                       and reference["chunk_id"] in seam["child_ids"]
                       and reference["source_char_end" if at_end else "source_char_start"] == source_offset
                       for reference in references):
                    matches.append(index)
            return matches[0] if len(matches) == 1 else None

        left, right = boundary_word(seam["left"], at_end=True), boundary_word(seam["right"], at_end=False)
        if left is not None and right is not None and left < right:
            word, continuation = source_words[left], source_words[right]
            joined[left] = (word[0] + continuation[0], word[1], word[2], word[3])
            continuations[word[1]] = [(continuation[1], continuation[2])]
            replaced.add(right)
    for index, word in enumerate(source_words):
        if index in joined or index in replaced:
            continue
        if normalized_document[word[2]:word[2] + 1] != "-":
            continue
        raw_end = normalized_positions[word[2]][1]
        if raw_end < len(document) and origins[raw_end] is not None and document[raw_end] != "\n":
            continue
        candidates = [next_index for next_index in range(index + 1, len(source_words))
            if source_words[next_index][3] != source_words[next_index - 1][3]
            and word[0] + source_words[next_index][0] in ordinary_words]
        if len(candidates) == 1:
            next_index = candidates[0]
            continuation = source_words[next_index]
            joined[index] = (word[0] + continuation[0], word[1], word[2] + 1, word[3])
            continuations[word[1]] = [(continuation[1], continuation[2])]
            replaced.add(next_index)
    source_words = [joined.get(index, word) for index, word in enumerate(source_words) if index not in replaced]
    anchors = {}
    for index in range(len(source_words) - 3):
        anchors.setdefault(tuple(word[0] for word in source_words[index:index + 4]), []).append(index)

    def source_positions(ranges, view_positions=None):
        if view_positions is not None:
            ranges = [(view_positions[start][0], view_positions[end - 1][1]) for start, end in ranges]
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        positions = []
        previous_structured = {}
        for start, end in merged:
            raw_start, raw_end = normalized_positions[start][0], normalized_positions[end - 1][1]
            for origin in origins[raw_start:raw_end]:
                if origin is None:
                    continue
                segment_id, offset = origin
                if segments[segment_id].get("structured"):
                    for reference in segments[segment_id]["references"].get(offset, []):
                        key = (reference["chunk_id"], segment_id)
                        previous = previous_structured.get(key)
                        source_contiguous = (previous is not None and (
                            previous["source_char_start"] is None and reference["source_char_start"] is None
                            or previous["source_char_start"] is not None and reference["source_char_start"] is not None
                            and previous["source_char_start"] <= reference["source_char_start"] <= previous["source_char_end"]))
                        if (previous is not None and previous["text_start"] <= reference["text_start"] <= previous["text_end"]
                                and source_contiguous):
                            previous["text_end"] = max(previous["text_end"], reference["text_end"])
                            if previous["source_char_start"] is not None:
                                previous["source_char_end"] = max(previous["source_char_end"], reference["source_char_end"])
                        else:
                            selected = deepcopy(reference)
                            positions.append(selected)
                            previous_structured[key] = selected
                    continue
                if (positions and positions[-1].get("segment_id") == segment_id
                        and positions[-1]["char_start"] <= offset <= positions[-1]["char_end"]):
                    positions[-1]["char_end"] = max(offset + 1, positions[-1]["char_end"])
                else:
                    positions.append({"segment_id": segment_id, "char_start": offset,
                        "char_end": offset + 1, "pdf_page": segments[segment_id]["pdf_page"],
                        "source_block_index": segments[segment_id]["source_block_index"]})
        return positions

    def locate(paragraph, text, source, words, source_anchors, continuation_ranges, *, view_positions=None):
        if not text:
            paragraph["reason"] = "empty_or_repeated_original_text"
            return
        matches, offset = [], 0
        while True:
            start = source.find(text, offset)
            if start < 0:
                break
            end = start + len(text)
            if ((not text[0].isalnum() or start == 0 or not source[start - 1].isalnum())
                    and (not text[-1].isalnum() or end == len(source)
                         or not source[end].isalnum())):
                matches.append((start, end))
            offset = start + 1
        if len(matches) > 1:
            paragraph["reason"] = "ambiguous_pdf_text"
            return
        ranges = matches
        if not ranges:
            ranges, ambiguous = _ordered_paragraph_spans(text, source, words, source_anchors, continuation_ranges)
            if not ranges:
                paragraph["reason"] = "ambiguous_pdf_text" if ambiguous else "not_found"
                return
        paragraph.update(status="mapped", positions=source_positions(ranges, view_positions),
                         attribution_positions=source_positions(_attribution_ranges(text, source, ranges), view_positions))
        for chunk in chunks:
            if chunk_records[chunk["chunk_id"]]["reason"] not in ("unmapped_text", "partial_text_coverage", None):
                continue
            if any(position.get("chunk_id") == chunk["chunk_id"] if "source_spans" in chunk else
                   position.get("segment_id") == chunk.get("segment_id")
                   and position["char_start"] < chunk.get("char_end", 0)
                   and chunk.get("char_start", 0) < position["char_end"] for position in paragraph["positions"]):
                paragraph["chunk_ids"].append(chunk["chunk_id"])
                chunk_records[chunk["chunk_id"]]["paragraph_ids"].append(paragraph["paragraph_id"])

    for paragraph, text in zip(paragraphs, normalized_paragraphs):
        if original_counts[text] != 1:
            paragraph["reason"] = "empty_or_repeated_original_text"
            continue
        locate(paragraph, text, normalized_document, source_words, anchors, continuations)

    # Headings absent from child.text retain their real source location and no invented child slice.
    source_order = {source["block_id"]: index for index, source in enumerate(sources)}
    for index, paragraph in enumerate(paragraphs):
        if paragraph.get("reason") != "not_found" or original_counts[normalized_paragraphs[index]] != 1:
            continue
        text = normalized_paragraphs[index]
        headings = [source for source in sources if source.get("type") == "heading"
                    and _paragraph_text_positions(source.get("text", ""))[0] == text]
        if len(headings) != 1:
            if len(headings) > 1:
                paragraph["reason"] = "ambiguous_pdf_text"
            continue
        heading = headings[0]
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
        if (following is None or following["section_index"] != paragraph["section_index"]
                or following["status"] != "mapped"):
            continue
        heading_index = source_order[heading["block_id"]]
        next_heading = next((position for position in range(heading_index + 1, len(sources))
                             if sources[position].get("type") == "heading"), len(sources))
        if not any(heading_index < source_order.get(position.get("block_id"), -1) < next_heading
                   for position in following["positions"]):
            continue
        position = {name: deepcopy(heading.get(name)) for name in
                    ("block_id", "pdf_page", "bbox", "page_size", "coordinate_system", "section_path")}
        position.update(content_type="heading", source_field="text", source_char_start=0,
                        source_char_end=len(heading["text"]), location_kind="heading_source")
        paragraph.update(status="mapped", reason=None, positions=[position],
                         attribution_positions=[], location_basis="heading_and_following_paragraph")

    paragraph_by_id = {row["paragraph_id"]: row for row in paragraphs}
    for chunk in chunks:
        record = chunk_records[chunk["chunk_id"]]
        if not record["paragraph_ids"] or record["reason"] != "unmapped_text":
            continue
        structured = "source_spans" in chunk
        ranges = [position for identifier in record["paragraph_ids"]
                  for position in paragraph_by_id[identifier]["positions"]
                  if (position.get("chunk_id") == chunk["chunk_id"] if structured else
                      position.get("segment_id") == chunk["segment_id"])]
        start_key, end_key = ("text_start", "text_end") if structured else ("char_start", "char_end")
        if all(character.isspace() or any(position[start_key] <= offset < position[end_key]
                                         for position in ranges)
               for offset, character in enumerate(chunk["text"], 0 if structured else chunk["char_start"])):
            record.update(status="mapped", reason=None)
        else:
            record["reason"] = "partial_text_coverage"

    # Literal coverage remains a body-only diagnostic. Abstract contributes only to
    # the separate evidence-ownership decision below and never changes the 83-body denominator.
    body_partial = sum(bool(row["paragraph_ids"]) and row["status"] != "mapped" for row in chunk_records.values())
    body_unassociated = sum(not row["paragraph_ids"] for row in chunk_records.values())
    abstract_evidence = []
    if isinstance(abstract, str):
        abstract_row = {"paragraph_id": "abstract:p0", "text": abstract, "status": "unresolved",
                        "chunk_ids": [], "positions": []}
        abstract_evidence.append(abstract_row)
        abstract_text = _abstract_matching_view(_paragraph_text_positions(abstract)[0])[0]
        abstract_source, abstract_positions = _abstract_matching_view(normalized_document)
        starts = {position[0]: index for index, position in reversed(list(enumerate(abstract_positions)))}
        ends = {position[1]: index + 1 for index, position in enumerate(abstract_positions)}
        abstract_words = [(word.casefold(), starts[start], ends[end], segment)
                          for word, start, end, segment in source_words]
        abstract_anchors = {}
        for index in range(len(abstract_words) - 3):
            abstract_anchors.setdefault(tuple(word[0] for word in abstract_words[index:index + 4]), []).append(index)
        abstract_continuations = {starts[start]: [(starts[left], ends[right]) for left, right in ranges]
                                  for start, ranges in continuations.items()}
        locate(abstract_row, abstract_text, abstract_source, abstract_words, abstract_anchors,
               abstract_continuations, view_positions=abstract_positions)
    paragraph_by_id.update({row["paragraph_id"]: row for row in abstract_evidence})
    for chunk in chunks:
        record = chunk_records[chunk["chunk_id"]]
        structured = "source_spans" in chunk
        start_key, end_key = ("text_start", "text_end") if structured else ("char_start", "char_end")
        offset_start = 0 if structured else chunk.get("char_start", 0)
        basis = []
        for identifier in record["paragraph_ids"]:
            paragraph = paragraph_by_id[identifier]
            literal = [position for position in paragraph["positions"] if (
                position.get("chunk_id") == chunk["chunk_id"] if structured else
                position.get("segment_id") == chunk.get("segment_id"))]
            attributed = [position for position in paragraph.get("attribution_positions", []) if (
                position.get("chunk_id") == chunk["chunk_id"] if structured else
                position.get("segment_id") == chunk.get("segment_id"))]
            for position in attributed:
                left, right = position[start_key], position[end_key]
                # An independently parsed formula/table/image cannot inherit adjacent prose identity.
                if (structured and position.get("content_type") not in
                        ("text", "heading", "list", "list_item", "body", "paragraph")
                        and not all(any(old[start_key] <= offset < old[end_key] for old in literal)
                                    for offset in range(left, right))):
                    continue
                clipped = deepcopy(position)
                clipped[start_key] = max(left, offset_start)
                clipped[end_key] = min(right, offset_start + len(chunk["text"]))
                if clipped[start_key] < clipped[end_key]:
                    basis.append({"paragraph_id": identifier, "position": clipped,
                                  "basis": "located_paragraph_presentation"})
        # A residue-only chunk has no ordinary prose that proves its paragraph ownership.
        has_prose = any(re.search(r"\w", chunk["text"][max(0, position[start_key] - offset_start):
                        min(len(chunk["text"]), position[end_key] - offset_start)])
                        for identifier in record["paragraph_ids"]
                        for position in paragraph_by_id[identifier]["positions"]
                        if (position.get("chunk_id") == chunk["chunk_id"] if structured else
                            position.get("segment_id") == chunk.get("segment_id"))
                        and position[start_key] < offset_start + len(chunk["text"])
                        and offset_start < position[end_key])
        if record["status"] != "mapped" and not has_prose:
            basis = []
        unresolved = []
        for offset, character in enumerate(chunk["text"], offset_start):
            if character.isspace() or any(row["position"][start_key] <= offset < row["position"][end_key]
                                          for row in basis):
                continue
            if unresolved and unresolved[-1][end_key] == offset:
                unresolved[-1][end_key] = offset + 1
            else:
                unresolved.append({start_key: offset, end_key: offset + 1})
        complete = bool(record["paragraph_ids"]) and not unresolved
        record["paragraph_attribution"] = {"status": "mapped" if complete else "unresolved",
            "paragraph_ids": list(record["paragraph_ids"]), "basis": basis, "unresolved_ranges": unresolved,
            "reason": None if complete else "unattributed_content" if record["paragraph_ids"] else record["reason"]}
    mapped_paragraphs = sum(row["status"] == "mapped" for row in paragraphs)
    mapped_chunks = sum(row["status"] == "mapped" for row in chunk_records.values())
    mapping = {"paragraphs": paragraphs, "chunks": chunk_records, "coverage": {
        "paragraphs_total": len(paragraphs), "mapped_paragraphs": mapped_paragraphs,
        "unresolved_paragraphs": len(paragraphs) - mapped_paragraphs,
        "paragraph_mapping_rate": mapped_paragraphs / len(paragraphs) if paragraphs else None,
        "chunks_total": len(chunk_records), "mapped_chunks": mapped_chunks,
        "unresolved_chunks": len(chunk_records) - mapped_chunks,
        "partial_coverage_chunks": body_partial,
        "unassociated_chunks": body_unassociated,
        "source_role_counts": dict(Counter(role for row in chunk_records.values() for role in row.get("source_roles", []))),
        "attributed_chunks": sum(row["paragraph_attribution"]["status"] == "mapped" for row in chunk_records.values()),
        "unresolved_attribution_chunks": sum(row["paragraph_attribution"]["status"] != "mapped" for row in chunk_records.values()),
        "chunk_attribution_rate": (sum(row["paragraph_attribution"]["status"] == "mapped"
                                       for row in chunk_records.values()) / len(chunk_records)) if chunk_records else None,
        "chunk_mapping_rate": mapped_chunks / len(chunk_records) if chunk_records else None}}
    if abstract_evidence:
        mapping["abstract_evidence"] = abstract_evidence
        mapping["coverage"]["attribution_scope"] = "body_and_abstract"
    return mapping


def map_evidence(mapping, cited_chunk_ids, references):
    """Keep every cited chunk and every reference in the mapping eligibility decision."""
    paragraphs = {row["paragraph_id"]: row for row in
                  [*mapping.get("paragraphs", []), *mapping.get("abstract_evidence", [])]}
    chunks = mapping.get("chunks", {})
    predicted, unresolved_chunks, unresolved_paragraphs, unresolved_references = [], [], [], []
    for identifier in dict.fromkeys(cited_chunk_ids):
        chunk = chunks.get(identifier)
        attributed = chunk.get("paragraph_attribution", chunk) if chunk else None
        if attributed is None or attributed["status"] != "mapped":
            unresolved_chunks.append(identifier)
        for paragraph_id in attributed.get("paragraph_ids", []) if attributed else []:
            paragraph = paragraphs.get(paragraph_id)
            if paragraph is None or paragraph["status"] != "mapped":
                unresolved_paragraphs.append(paragraph_id)
            elif paragraph["text"] not in predicted:
                predicted.append(paragraph["text"])
    for reference in references:
        answer = reference.get("answer")
        reference = answer if isinstance(answer, dict) else reference
        for text in reference.get("evidence", []):
            normalized = _paragraph_text_positions(text)[0]
            matches = [row for row in paragraphs.values() if _paragraph_text_positions(row["text"])[0] == normalized]
            if (not matches or len({row["text"] for row in matches}) != 1
                    or any(row["status"] != "mapped" for row in matches)):
                unresolved_references.append(text)
                unresolved_paragraphs.extend(row["paragraph_id"] for row in matches)
    return {"predicted_evidence": predicted,
            "status": "unresolved" if unresolved_chunks or unresolved_paragraphs or unresolved_references else "mapped",
            "unresolved_chunk_ids": list(dict.fromkeys(unresolved_chunks)),
            "unresolved_paragraph_ids": list(dict.fromkeys(unresolved_paragraphs)),
            "unresolved_reference_evidence": list(dict.fromkeys(unresolved_references))}


QASPER_SOURCE = {
    "dataset": "https://huggingface.co/datasets/allenai/qasper",
    "archive": "https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-train-dev-v0.3.tgz",
    "version": "v0.3", "license": "CC BY 4.0",
    "evaluator": "https://github.com/allenai/qasper-led-baseline/blob/main/scripts/evaluator.py",
}


def references_for_case(case):
    """Convert all references in the official evaluator's precedence order."""
    references = []
    for annotation in case["answers"]:
        answer = annotation["answer"]
        if answer["unanswerable"]:
            references.append({"answer": "Unanswerable", "evidence": [], "type": "none"})
            continue
        if answer["extractive_spans"]:
            text, answer_type = ", ".join(answer["extractive_spans"]), "extractive"
        elif answer["free_form_answer"]:
            text, answer_type = answer["free_form_answer"], "abstractive"
        elif answer["yes_no"]:
            text, answer_type = "Yes", "boolean"
        elif answer["yes_no"] is not None:
            text, answer_type = "No", "boolean"
        else:
            raise ValueError("QASPER annotation does not contain an answer")
        references.append({"answer": text, "evidence": deepcopy(answer["evidence"]), "type": answer_type})
    return references


def prepare_sample(data, *, split, count, seed):
    """Select questions before PDF availability or evaluation results are known."""
    if split not in ("train", "dev", "validation"):
        raise ValueError("QASPER preparation supports train and dev/validation only")
    official_split = "dev" if split == "validation" else split
    project_split = "validation" if official_split == "dev" else "train"
    eligible, excluded, total = [], 0, 0
    for paper_id, paper in data.items():
        for question in paper["qas"]:
            total += 1
            if any("FLOAT SELECTED" in evidence for annotation in question["answers"]
                   for evidence in annotation["answer"]["evidence"]):
                excluded += 1
                continue
            eligible.append({"paper_id": paper_id, "question_id": question["question_id"],
                "official_split": official_split, "split": project_split,
                "question": question["question"], "answers": deepcopy(question["answers"])})
    eligible.sort(key=lambda row: row["question_id"])
    selected = random.Random(seed).sample(eligible, count)
    paper_ids = sorted({case["paper_id"] for case in selected})
    references = [reference for case in selected for reference in references_for_case(case)]
    question_types = Counter(answer_type for case in selected
                             for answer_type in {reference["type"] for reference in references_for_case(case)})
    return {"source": deepcopy(QASPER_SOURCE), "split": project_split, "official_split": official_split,
        "cases": selected,
        "papers": {paper_id: {"title": data[paper_id]["title"], "abstract": data[paper_id]["abstract"],
                               "full_text": deepcopy(data[paper_id]["full_text"])} for paper_id in paper_ids},
        "selection": {"seed": seed, "count": count, "input_question_count": total,
            "eligible_question_count": len(eligible), "excluded_float_selected": excluded,
            "selected_question_count": len(selected), "selected_paper_count": len(paper_ids),
            "question_ids": [case["question_id"] for case in selected],
            "filter": "Exclude the whole question if any reference contains FLOAT SELECTED",
            "answer_types": dict(Counter(reference["type"] for reference in references)),
            "question_answer_types": dict(question_types)}}


def normalize_answer(text):
    """Official QASPER/SQuAD normalization: ASCII punctuation, articles, space."""
    text = "".join(character for character in text.lower() if character not in string.punctuation)
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", text).split())


def token_f1_score(prediction, ground_truth):
    prediction_tokens = normalize_answer(prediction).split()
    ground_truth_tokens = normalize_answer(ground_truth).split()
    common = sum((Counter(prediction_tokens) & Counter(ground_truth_tokens)).values())
    if not common:
        return 0.0
    precision, recall = common / len(prediction_tokens), common / len(ground_truth_tokens)
    return 2 * precision * recall / (precision + recall)


def paragraph_f1_score(prediction, ground_truth):
    if not prediction and not ground_truth:
        return 1.0
    common = len(set(prediction).intersection(set(ground_truth)))
    if not common:
        return 0.0
    precision, recall = common / len(prediction), common / len(ground_truth)
    return 2 * precision * recall / (precision + recall)


def extract_prediction(report, *, evaluation_protocol=None):
    """Read the published protocol's answer and all citations, without reference hints."""
    if not isinstance(report, dict):
        return None
    result = report.get("result") or {}
    status = report.get("status", result.get("status"))
    if status == "insufficient_evidence":
        return {"answer": "Unanswerable", "evidence_chunk_ids": []}
    if status != "answered":
        return None
    answer = report.get("answer", result.get("answer")) or {}
    claims = answer.get("claims") or []
    if not claims or any(not isinstance(claim.get("claim"), str) or not claim["claim"].strip() for claim in claims):
        return None
    if evaluation_protocol == EVALUATION_PROTOCOL:
        direct_answer = answer.get("direct_answer")
        if not isinstance(direct_answer, str) or not direct_answer.strip():
            return None
        prediction = direct_answer
    else:
        prediction = "\n\n".join(claim["claim"] for claim in claims)
    return {"answer": prediction,
            "evidence_chunk_ids": list(dict.fromkeys(identifier for claim in claims
                                                     for identifier in claim.get("citation_ids", [])))}


def score_qasper_case(case, report, mapping, *, attempted=True, evaluation_protocol=None):
    """Score both metrics independently across every retained reference."""
    result = (report.get("result") or {}) if isinstance(report, dict) else {}
    score = {"question_id": case["question_id"], "paper_id": case["paper_id"], "attempted": attempted,
        "success": False, "prediction": None, "answer_f1": None, "evidence_f1": None,
        "evidence_mapping_status": "unattempted", "mapping_gaps": {},
        "status": report.get("status", result.get("status")) if isinstance(report, dict) else None,
        "failure_reason": None}
    if not attempted:
        return score
    prediction = extract_prediction(report, evaluation_protocol=evaluation_protocol)
    if prediction is None:
        score.update(answer_f1=0.0, evidence_f1=0.0, evidence_mapping_status="missing_prediction",
                     failure_reason=(report.get("error") or result.get("error") or {}).get("code")
                         if isinstance(report, dict) else "missing_prediction")
        score["failure_reason"] = score["failure_reason"] or score["status"] or "missing_prediction"
        if evaluation_protocol == EVALUATION_PROTOCOL and score["status"] == "answered":
            answer = report.get("answer", result.get("answer")) or {}
            direct_answer = answer.get("direct_answer")
            if not isinstance(direct_answer, str) or not direct_answer.strip():
                score["failure_reason"] = "missing_direct_answer"
        return score
    references = references_for_case(case)
    answer_f1 = max(token_f1_score(prediction["answer"], reference["answer"]) for reference in references)
    mapped = map_evidence(mapping or {}, prediction["evidence_chunk_ids"], references)
    score.update(success=True, prediction={**prediction, "evidence": mapped["predicted_evidence"]},
        answer_f1=answer_f1, evidence_mapping_status=mapped["status"],
        mapping_gaps={name: deepcopy(mapped[name]) for name in
            ("unresolved_chunk_ids", "unresolved_paragraph_ids", "unresolved_reference_evidence")})
    if mapped["status"] == "mapped":
        score["evidence_f1"] = max(paragraph_f1_score(mapped["predicted_evidence"], reference["evidence"])
                                   for reference in references)
    return score


def summarize_qasper(sample, records, bindings, *, modes=None, evaluation_protocol=None):
    """Keep the fixed sample, attempted denominators and common evidence set."""
    from paper_assistant.agent_comparison import summarize_current_costs

    modes = tuple(modes) if modes is not None else ("fixed_rag", "agent")
    cases = sample["cases"]
    by_question = {record["question_id"]: record for record in records}
    papers = bindings.get("papers", {})
    scores = {mode: {} for mode in modes}
    reports = {mode: [] for mode in modes}
    pairs, issues = [], []
    for case in cases:
        record = by_question.get(case["question_id"], {})
        pair = record.get("pair") or {}
        if pair.get("modes"):
            pairs.append(pair)
        mapping = papers.get(case["paper_id"], {}).get("mapping")
        for mode in modes:
            if mode not in pair.get("modes", {}):
                continue
            report = pair["modes"][mode]
            scored = score_qasper_case(case, report, mapping, evaluation_protocol=evaluation_protocol)
            scores[mode][case["question_id"]] = scored
            reports[mode].append(report)
            if not scored["success"] or scored["evidence_f1"] is None:
                issues.append({"question_id": case["question_id"], "mode": mode,
                    "status": scored["status"], "failure_reason": scored["failure_reason"],
                    "evidence_mapping_status": scored["evidence_mapping_status"],
                    "mapping_gaps": scored["mapping_gaps"]})

    def mean(values):
        return sum(values) / len(values) if values else None

    summary_modes = {}
    for mode in modes:
        measured = list(scores[mode].values())
        evidence_scores = [score["evidence_f1"] for score in measured if score["evidence_f1"] is not None]
        mapping_count = sum(score["evidence_mapping_status"] == "mapped" for score in measured)
        complete = len(measured) == len(cases)
        steps = [(report.get("result") or {}).get("autonomous_steps_used") for report in reports[mode]]
        known_steps = [value for value in steps if type(value) is int]
        summary_modes[mode] = {
            "attempted_count": len(measured), "unattempted_count": len(cases) - len(measured),
            "success_count": sum(score["success"] for score in measured),
            "failed_count": sum(not score["success"] for score in measured),
            "answer_f1": mean([score["answer_f1"] for score in measured]),
            "answer_f1_count": len(measured), "answer_f1_scope": "fixed_sample" if complete else "attempted_subset",
            "evidence_f1": mean(evidence_scores) if complete and len(evidence_scores) == len(cases) else None,
            "evidence_f1_status": "complete" if complete and len(evidence_scores) == len(cases) else "incomplete",
            "evidence_f1_partial": {"mean": mean(evidence_scores), "denominator": len(evidence_scores)},
            "mapping_evaluable_count": mapping_count,
            "mapping_coverage": mapping_count / len(cases) if cases else None,
            "evidence_unscorable_count": sum(score["evidence_f1"] is None for score in measured),
            "autonomous_steps_used": {"total": sum(known_steps) if len(known_steps) == len(steps) else None,
                                      "known_total": sum(known_steps), "missing_records": len(steps) - len(known_steps)},
            "limit_finalize_count": sum(bool((report.get("result") or {}).get("limit_finalize")) for report in reports[mode]),
            "stop_reason_counts": dict(Counter(report.get("stop_reason", (report.get("result") or {}).get("stop_reason"))
                                               or "unspecified" for report in reports[mode])),
        }
    common = [case["question_id"] for case in cases if all(
        case["question_id"] in scores[mode] and scores[mode][case["question_id"]]["evidence_f1"] is not None
        for mode in modes)]
    selected_papers = {case["paper_id"] for case in cases}
    ready = sum(papers.get(paper_id, {}).get("status") == "ready" for paper_id in selected_papers)
    attempted = set().union(*(set(scores[mode]) for mode in modes))
    fully_attempted = set.intersection(*(set(scores[mode]) for mode in modes)) if modes else set()
    summary = {
        "dataset": "QASPER v0.3 text-evidence subset", "source": deepcopy(sample.get("source", QASPER_SOURCE)),
        "split": sample.get("split"), "official_split": sample.get("official_split"),
        "counts": {"fixed_sample_questions": len(cases), "selected_papers": len(selected_papers),
            "ready_papers": ready, "pending_papers": len(selected_papers) - ready,
            "attempted_questions": len(attempted), "unattempted_questions": len(cases) - len(attempted),
            "fully_attempted_questions": len(fully_attempted)},
        "selected_modes": list(modes),
        "modes": summary_modes,
        "common_evidence_question_ids": common,
        "common_evidence_count": len(common),
        "common_evidence_coverage": len(common) / len(cases) if cases else None,
        "common_evidence_f1": {mode: mean([scores[mode][question_id]["evidence_f1"] for question_id in common])
                               for mode in modes},
        "costs": summarize_current_costs(pairs, modes=modes), "representative_issues": issues[:10],
        "qa_accuracy": None,
        "interpretation": "Answer F1 is official token overlap, not semantic accuracy. Evidence F1 uses final cited paragraphs; null mappings remain unscorable. Common evidence scores include missing-prediction zeros. PDF-backed text-subset results do not reproduce full leaderboard conditions.",
    }
    if evaluation_protocol is not None:
        summary["evaluation_protocol"] = evaluation_protocol
    return summary

