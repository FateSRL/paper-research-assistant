"""Apply reviewed source ranges to retrieved chunks and actual citations.

The source table is loaded once per run. PDF identity and citation/store
checks belong to citations.py; runtime question answering does not repeat the
offline PDF structural review or hash its supporting screenshots and files.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from paper_assistant.agent_context import merge_planned_context, validate_search_round
from paper_assistant.context import build_messages, select_context, token_context_options
from paper_assistant.schemas import AnswerDraft
from paper_assistant.storage import CHUNK_FIELDS, STRUCTURED_CHUNK_FIELDS


RULE_VERSION = "d9-explicit-abstract-constraint-v1"
REGISTRY_VERSION = "d9-source-regions-v1"
QUALIFICATION_VERSION = "d9-source-qualification-v1"
_REQUIREMENT_FIELDS = {"rule_version", "resolution",
                       "required_scope", "matched_expression"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SourceScopeError(ValueError):
    def __init__(self, code, message="来源范围核验失败，请核对安全错误代码"):
        super().__init__(message)
        self.code = code


def _fail(code):
    raise SourceScopeError(code)


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: _fail("nonfinite_json"))
    except SourceScopeError:
        raise
    except Exception:
        _fail("invalid_source_json")


def _pairs(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 3:
        _fail("invalid_versions")
    result = []
    for row in values:
        if (not isinstance(row, (tuple, list)) or len(row) != 2
                or any(type(v) is not str or not v.strip() or v != v.strip() for v in row)
                or tuple(row) in result):
            _fail("invalid_versions")
        result.append(tuple(row))
    return tuple(result)


def identify_source_requirement(original_question):
    """Small conservative rule for explicit abstract constraints, derived once.

    Unrecognized uses of the abstract section word, quotes, negation and mixed
    source requests stop as ambiguous; this is not a general language parser.
    """
    if type(original_question) is not str or not original_question.strip():
        _fail("invalid_original_question")
    # Preserve character offsets and paired quote marks. Only a word-internal
    # apostrophe (paper’s) is normalized; ‘in the abstract’ stays quoted.
    text = original_question.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
    text = re.sub(r"(?<=\w)’(?=\w)", "'", text)
    tokens = list(re.finditer(r"\babstract\b|摘要", text))
    # These ordinary non-section phrases do not impose an evidence source.
    ordinary = re.sub(r"\babstract (?:class|classes|method|methods|reasoning|algebra|syntax|representation)\b",
                      "", text)
    if not re.search(r"\babstract\b|摘要", ordinary):
        tokens = []
    expression = re.search(
        r"\b(?:in|from|according to|within)\s+(?:the\s+)?(?:paper'?s\s+)?abstract\b"
        r"|\b(?:the\s+)?(?:paper'?s\s+)?abstract\s+(?:names?|mentions?|states?|says?|reports?|lists?)\b"
        r"|摘要(?:中|里|部分|提到|指出|说明|列出|报告|介绍)", text)
    quotations = re.findall(r'"([^"\n]*)"|“([^”\n]*)”|‘([^’\n]*)’|(?<!\w)\'([^\'\n]+)\'(?!\w)', text)
    quoted = any(re.search(r"\babstract\b|摘要", part)
                 for group in quotations for part in group if part)
    negated = bool(re.search(r"\b(?:not|except|excluding|without)\b.{0,45}\babstract\b"
                             r"|(?:不是|不在|不要|不限|除|排除).{0,16}摘要", text))
    conflicting = bool(tokens and re.search(r"\b(?:body|introduction|conclusion|conclusions)\b|正文|引言|结论", text))
    resolution = "none" if not tokens else (
        "explicit" if expression and not (quoted or negated or conflicting) else "ambiguous")
    return {"rule_version": RULE_VERSION,
            "resolution": resolution, "required_scope": "abstract" if resolution == "explicit" else None,
            "matched_expression": original_question[expression.start():expression.end()] if expression else None}


def _requirement(value, question=None):
    if (not isinstance(value, dict) or set(value) != _REQUIREMENT_FIELDS
            or value.get("rule_version") != RULE_VERSION
            or value.get("resolution") not in ("none", "explicit", "ambiguous")
            or value.get("required_scope") != ("abstract" if value.get("resolution") == "explicit" else None)
            or (value.get("matched_expression") is not None
                and (type(value["matched_expression"]) is not str or not value["matched_expression"].strip()))
            or (value.get("resolution") == "explicit" and not value.get("matched_expression"))):
        _fail("invalid_source_requirement")
    if question is not None and value != identify_source_requirement(question):
        _fail("source_requirement_mismatch")
    return deepcopy(value)


def attach_source_requirement(messages, original_question, requirement):
    """Add only the immutable requirement to the first existing user payload."""
    requirement = _requirement(requirement, original_question)
    checked = deepcopy(messages)
    if (not isinstance(checked, list) or len(checked) < 2
            or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                   or m["role"] not in ("system", "user", "assistant")
                   or type(m["content"]) is not str for m in checked)):
        _fail("invalid_source_messages")
    user = next((m for m in checked if m["role"] == "user"), None)
    if user is None:
        _fail("invalid_source_messages")
    payload = _json(user["content"])
    if not isinstance(payload, dict) or payload.get("question") != original_question:
        _fail("source_question_mismatch")
    allowed_payload_fields = {"question", "selected_versions", "allowed_citation_ids", "shown_evidence",
                              "source_requirement", "phase", "allowed_actions", "terminal_only",
                              "action_schema_version", "prompt_version", "action_contracts",
                              "selected_papers", "reading_origins", "evidence_limitation", "score_kind", "ranking_method",
                              "conversation_context", "context_budget"}
    if not set(payload).issubset(allowed_payload_fields):
        _fail("invalid_source_messages")
    if "source_requirement" in payload and payload["source_requirement"] != requirement:
        _fail("source_requirement_mismatch")
    # Revalidate the exact shown payload via the existing strict snapshot guard.
    shown, versions = payload.get("shown_evidence"), payload.get("selected_versions")
    if not isinstance(shown, list) or not isinstance(versions, list):
        _fail("invalid_source_messages")
    snapshot = {"question": original_question, "selected_versions": versions,
                "shown_evidence": shown, "allowed_citation_ids": payload.get("allowed_citation_ids"),
                "max_chars": None, "shown_chars": sum(len(m.get("shown_text", "")) for m in shown if isinstance(m, dict)),
                "candidate_count": len(shown), "omitted_evidence": [],
                "empty_selection_reason": None if shown else "no_hits"}
    if "context_budget" in payload:
        snapshot.update(deepcopy(payload["context_budget"]))
    try:
        build_messages(original_question, snapshot)
    except Exception:
        _fail("invalid_source_messages")
    if requirement["resolution"] != "none":
        payload["source_requirement"] = requirement
        user["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return checked


def _path(root, relative):
    if type(relative) is not str or not relative.strip():
        _fail("source_path_invalid")
    value, windows = Path(relative), PureWindowsPath(relative)
    if value.is_absolute() or windows.drive or windows.root or ".." in value.parts or ".." in windows.parts:
        _fail("source_path_invalid")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root:
        _fail("source_path_invalid")
    return path


def _lines(block, indices=None):
    lines = block.get("lines", [])
    if indices is None:
        indices = list(range(len(lines)))
    if (not isinstance(indices, list) or not indices
            or any(type(v) is not int or v < 0 or v >= len(lines) for v in indices)
            or indices != sorted(set(indices))):
        _fail("source_line_range_invalid")
    return "\n".join("".join(span["text"] for span in lines[i]["spans"]) for i in indices)


def detect_abstract_regions(filtered_pages):
    """Locate an explicit abstract heading and the following section boundary.

    Ranges use the existing filtered segment coordinates. Missing or ambiguous
    headings leave the abstract unknown; ordinary body retrieval still works.
    """
    segments, lines, headings = [], [], []
    standalone = re.compile(r"[ \t]*(?:abstract|摘[ \t]*要)[ \t]*[:：]?[ \t]*", re.I)
    inline = re.compile(r"[ \t]*(?:abstract|摘[ \t]*要)[ \t]*[:：—–-][ \t]*(?=\S)", re.I)
    section = re.compile(
        r"[ \t]*(?:(?:\d+(?:\.\d+)*[.)]?|[ivx]+[.)]?)[ \t]+)?"
        r"(?:introduction|background|related[ \t]+work|preliminaries|methods?|methodology|overview|"
        r"引言|绪论|前言|背景|相关工作|研究方法|方法|概述)[ \t]*[:：]?[ \t]*", re.I)
    keywords = re.compile(r"[ \t]*(?:keywords?|index[ \t]+terms|关键词|关键字)[ \t]*[:：—–-]", re.I)
    for page in filtered_pages:
        for segment in page["segments"]:
            index = len(segments)
            segments.append((page["pdf_page"], segment))
            offset = 0
            for line in segment["text"].splitlines(keepends=True):
                text = line.rstrip("\r\n")
                lines.append((index, offset, text))
                match = inline.match(text)
                if standalone.fullmatch(text):
                    headings.append((index, offset + len(line)))
                elif match:
                    headings.append((index, offset + match.end()))
                offset += len(line)
    if len(headings) != 1:
        return []
    start = headings[0]
    end = next(((index, offset) for index, offset, text in lines
                if (index, offset) >= start and (section.fullmatch(text) or keywords.match(text))), None)
    if end is None:
        return []
    regions = []
    for index in range(start[0], end[0] + 1):
        page, segment = segments[index]
        left = start[1] if index == start[0] else 0
        right = end[1] if index == end[0] else len(segment["text"])
        while left < right and segment["text"][left].isspace():
            left += 1
        while right > left and segment["text"][right - 1].isspace():
            right -= 1
        if left < right:
            regions.append({"scope": "abstract", "pdf_page": page, "segment_id": segment["segment_id"],
                "source_block_index": segment["source_block_index"],
                "source_line_indices": deepcopy(segment["source_line_indices"]),
                "segment_char_start": left, "segment_char_end": right,
                "verification_status": "verified", "verification_method": "parsed_section_boundaries",
                "human_review_status": "pending"})
    return regions


class Registry:
    """Load stored abstract ranges once; the caller owns the read-only store."""
    def __init__(self, project_root, store, selected_versions, *, registry_path="artifacts/d9/source_regions.json"):
        self.root = Path(project_root).resolve()
        self.store = store
        self.pairs = _pairs(selected_versions)
        self.path = _path(self.root, registry_path)
        self._chunks, self._regions = {}, {}
        self._structured_pairs = set()
        self.structured = False
        self.full_context_mode = False
        try:
            value = _json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = {"schema_revision": REGISTRY_VERSION, "documents": []}
        except OSError:
            _fail("source_registry_missing")
        if (not isinstance(value, dict) or value.get("schema_revision") != REGISTRY_VERSION
                or not isinstance(value.get("documents"), list)):
            _fail("source_registry_invalid")
        self.document = deepcopy(value)
        self.registry_sha256 = None  # Compatibility field for historical exports.
        documents = {}
        for doc in value["documents"]:
            if not isinstance(doc, dict):
                _fail("source_document_invalid")
            pair = (doc.get("paper_id"), doc.get("parse_revision"))
            if pair in documents:
                _fail("source_document_duplicate")
            documents[pair] = doc
        for pair in self.pairs:
            if pair not in documents:
                documents[pair] = self._local_document(pair)
            self._load_document(pair, documents[pair])

    def _local_document(self, pair):
        connection = getattr(self.store, "connection", None)
        if connection is None:
            _fail("source_document_missing")
        row = connection.execute(
            "SELECT p.paper_json, v.manifest_json FROM papers p JOIN parse_versions v ON p.paper_id=v.paper_id "
            "WHERE v.paper_id=? AND v.parse_revision=?", pair).fetchone()
        if row is None:
            _fail("source_document_missing")
        paper, manifest = _json(row["paper_json"]), _json(row["manifest_json"])
        if manifest.get("schema_revision") == "structured-pdf-v1":
            return {"paper_id": pair[0], "parse_revision": pair[1],
                    "pdf_sha256": paper["pdf_sha256"], "schema_revision": "structured-pdf-v1"}
        if paper.get("source_type") != "local":
            _fail("source_document_missing")
        paths = manifest["source_paths"]
        return {"paper_id": pair[0], "parse_revision": pair[1], "pdf_sha256": paper["pdf_sha256"],
                "files": {name: {"path": paths[name]} for name in ("filtered", "chunks")},
                "regions": manifest.get("source_regions", [])}

    def _load_document(self, pair, doc):
        if doc.get("schema_revision") == "structured-pdf-v1":
            self._structured_pairs.add(pair)
            self.structured = True
            self._regions[pair] = []
            for chunk in self.store.get_version_chunks(*pair):
                self._chunks[chunk["chunk_id"]] = deepcopy(chunk)
            return
        files = doc.get("files")
        if not isinstance(files, dict) or any(name not in files for name in ("filtered", "chunks")):
            _fail("source_document_bindings_missing")
        def rows(name):
            try:
                return [_json(line) for line in _path(self.root, files[name]["path"])
                        .read_text(encoding="utf-8").splitlines() if line.strip()]
            except OSError:
                _fail("source_bound_file_missing")
        filtered, chunks = rows("filtered"), rows("chunks")
        segments = {}
        for page in filtered:
            if (page.get("paper_id") != pair[0] or page.get("pdf_sha256") != doc.get("pdf_sha256")
                    or type(page.get("pdf_page")) is not int or page["pdf_page"] < 1):
                _fail("source_filtered_identity_invalid")
            for segment in page.get("segments", []):
                if segment.get("segment_id") in segments:
                    _fail("source_segment_duplicate")
                segments[segment["segment_id"]] = (page["pdf_page"], segment)
        regions = doc.get("regions")
        if not isinstance(regions, list):
            _fail("source_regions_invalid")
        for region in regions:
            state, human = region.get("verification_status"), region.get("human_review_status")
            if (state not in ("candidate", "verified", "rejected")
                    or human not in ("pending", "confirmed", "rejected")
                    or (human == "rejected" and state != "rejected")):
                _fail("source_verification_state_invalid")
            entry = segments.get(region.get("segment_id"))
            if entry is None:
                _fail("source_region_segment_missing")
            page, segment = entry
            start, end = region.get("segment_char_start"), region.get("segment_char_end")
            if (region.get("scope") != "abstract" or region.get("pdf_page") != page
                    or region.get("source_block_index") != segment["source_block_index"]
                    or region.get("source_line_indices") != segment["source_line_indices"]):
                _fail("source_region_identity_mismatch")
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(segment["text"])
                    or ("text_sha256" in region and region["text_sha256"] != _sha(segment["text"][start:end]))):
                _fail("source_region_range_mismatch")
        self._regions[pair] = deepcopy(regions)
        for chunk in chunks:
            if (not isinstance(chunk, dict) or any(field not in chunk for field in CHUNK_FIELDS)
                    or (chunk["paper_id"], chunk["parse_revision"]) != pair
                    or chunk["pdf_sha256"] != doc.get("pdf_sha256")
                    or chunk["chunk_id"] in self._chunks):
                _fail("source_chunk_snapshot_mismatch")
            entry = segments.get(chunk["segment_id"])
            if entry is None:
                _fail("source_chunk_segment_missing")
            page, segment = entry
            start, end = chunk["char_start"], chunk["char_end"]
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(segment["text"])
                    or chunk["pdf_page"] != page or segment["text"][start:end] != chunk["text"]
                    or chunk["source_block_index"] != segment["source_block_index"]
                    or chunk["source_line_indices"] != segment["source_line_indices"]):
                _fail("source_chunk_snapshot_mismatch")
            self._chunks[chunk["chunk_id"]] = deepcopy(chunk)

    def revalidate(self):
        """Historical API: an open run uses its already loaded source snapshot."""
        return self.registry_sha256

    def get_parent(self, parent_id):
        """Read a real parent through this run's already open store."""
        parent = self.store.get_parent(parent_id)
        if parent is not None and (parent["paper_id"], parent["parse_revision"]) not in self.pairs:
            _fail("source_versions_mismatch")
        return parent

    @staticmethod
    def _structured_coverage(chunk):
        """Classify the saved regions, without inventing legacy review states."""
        path = chunk.get("section_path", [])
        label = path[-1].strip() if path and isinstance(path[-1], str) else ""
        label = re.sub(r"^(?:\d+(?:\.\d+)*[.)]?\s*)", "", label).strip(" :：")
        abstract = label.lower() == "abstract" or label in ("摘要", "摘 要")
        body_types = {"text", "paragraph", "body", "list", "list_item", "formula", "equation", "display_formula", "abstract"}
        spans = chunk.get("source_spans", [])
        if not label or not spans:
            return "unknown"
        suitable = [span for span in spans if span.get("content_type") in body_types
                    and span.get("source_field", "text") in ("text", "content")]
        if len(suitable) != len(spans) or chunk.get("content_type") not in body_types:
            return "mixed" if abstract and suitable else "unknown"
        covered = [False] * len(chunk["text"])
        for span in suitable:
            covered[span["text_start"]:span["text_end"]] = [True] * (span["text_end"] - span["text_start"])
        if any(not present and not char.isspace() for char, present in zip(chunk["text"], covered)):
            return "mixed" if abstract else "unknown"
        return "abstract_full" if abstract else "body"

    def _coverage(self, chunk):
        pair = chunk["paper_id"], chunk["parse_revision"]
        if pair in self._structured_pairs:
            return self._structured_coverage(chunk)
        available = [r for r in self._regions[pair] if r["verification_status"] == "verified"
                     and r["human_review_status"] != "rejected"]
        for region in available:
            if region["segment_id"] == chunk["segment_id"]:
                start, end = region["segment_char_start"], region["segment_char_end"]
                if start <= chunk["char_start"] < chunk["char_end"] <= end:
                    return "abstract_full"
                if max(start, chunk["char_start"]) < min(end, chunk["char_end"]):
                    return "mixed"
        if not available or any(r["segment_id"] == chunk["segment_id"] and r["verification_status"] != "verified"
                                for r in self._regions[pair]):
            return "unknown"
        return "body"

    def qualify(self, candidate):
        if not isinstance(candidate, dict) or candidate.get("chunk_id") not in self._chunks:
            _fail("source_chunk_missing")
        chunk = self._chunks[candidate["chunk_id"]]
        for field in ("paper_id", "parse_revision", "pdf_page", "text", "text_sha256"):
            if candidate.get(field) != chunk[field]:
                _fail("source_candidate_snapshot_mismatch")
        fields = STRUCTURED_CHUNK_FIELDS if (chunk["paper_id"], chunk["parse_revision"]) in self._structured_pairs else CHUNK_FIELDS
        for field in fields:
            if field in candidate and candidate[field] != chunk[field]:
                _fail("source_candidate_snapshot_mismatch")
        try:
            stored = self.store.get_chunk(chunk["chunk_id"])
        except Exception:
            _fail("source_lookup_failed")
        if not isinstance(stored, dict) or any(stored.get(k) != chunk[k] for k in fields):
            _fail("source_store_snapshot_mismatch")
        coverage = self._coverage(chunk)
        return {"chunk_id": chunk["chunk_id"], "coverage": coverage,
                "eligible": coverage == "abstract_full", "reason": None if coverage == "abstract_full" else "source_scope_" + coverage,
                "registry_sha256": self.registry_sha256}

    def qualified_chunk_ids(self, pairs=None):
        selected = self.pairs if pairs is None else _pairs(pairs)
        if any(pair not in self.pairs for pair in selected):
            _fail("source_versions_mismatch")
        identifiers = [identifier for identifier, chunk in self._chunks.items()
                       if (chunk["paper_id"], chunk["parse_revision"]) in selected and self._coverage(chunk) == "abstract_full"]
        for identifier in identifiers:
            self.qualify(self._chunks[identifier])
        return identifiers

    def has_qualified_abstract(self, pairs=None):
        return bool(self.qualified_chunk_ids(pairs))

    def validate_for_question(self, requirement, selected_versions):
        req = _requirement(requirement)
        selected = _pairs(selected_versions)
        if any(pair not in self.pairs for pair in selected):
            _fail("source_versions_mismatch")
        available = req["resolution"] == "none" or (req["resolution"] == "explicit" and self.has_qualified_abstract(selected))
        return {"available": available, "registry_sha256": self.registry_sha256,
                "reason": None if available else ("source_constraint_ambiguous" if req["resolution"] == "ambiguous" else "source_scope_unavailable")}

    def abstract_point_ids(self, profile_id, pairs):
        if type(profile_id) is not str or not profile_id.strip() or profile_id != profile_id.strip():
            _fail("invalid_index_profile")
        from paper_assistant.retrieval import point_id
        return [point_id(profile_id, identifier) for identifier in self.qualified_chunk_ids(pairs)]


def _scope_rows(search, requirement, registry):
    rows, decisions = [], []
    for item in search["results"]:
        decision = registry.qualify(item)
        included = requirement["resolution"] == "none" or (requirement["resolution"] == "explicit" and decision["eligible"])
        decisions.append({**decision, "rank": item["rank"], "score": item["score"], "included": included})
        if included:
            rows.append(deepcopy(item))
    return rows, decisions


def _search_pairs(search, registry):
    versions = search.get("selected_versions") if isinstance(search, dict) else None
    if (not isinstance(versions, list) or any(not isinstance(v, dict) or set(v) != {"paper_id", "parse_revision"} for v in versions)):
        _fail("invalid_versions")
    pairs = _pairs([(v["paper_id"], v["parse_revision"]) for v in versions])
    if any(pair not in registry.pairs for pair in pairs):
        _fail("source_versions_mismatch")
    return pairs


def _qualification(context, requirement, registry, searches, decisions, kind, max_chunks=None):
    return {"qualification_version": QUALIFICATION_VERSION, "kind": kind,
            "requirement": deepcopy(requirement), "registry_sha256": registry.registry_sha256,
            "raw_searches": deepcopy(searches),
            "raw_candidate_count": sum(len(s["results"]) for s in searches),
            "decisions": deepcopy(decisions),
            "scope_excluded": [deepcopy(d) for d in decisions if not d["included"]],
            "eligible_ids": list(dict.fromkeys(d["chunk_id"] for d in decisions if d["included"])),
            "shown_ids": deepcopy(context["allowed_citation_ids"]),
            "max_chars": context["max_chars"], "max_chunks": max_chunks,
            **({"max_tokens": context["max_tokens"]} if context.get("max_tokens") is not None else {})}


def prepare_unavailable_source_context(question, selected_versions, requirement, registry, reason,
                                       *, max_chars=8000, max_tokens=None):
    """Keep an unavailable source scope empty while allowing a useful explanation."""
    options = token_context_options(registry=registry)
    if max_tokens is not None:
        options["max_tokens"] = max_tokens
    context = {**select_context([], selected_versions, max_chars=max_chars, **options),
               "question": question, "evidence_limitation": reason}
    return {"context": context,
            "qualification": _qualification(context, requirement, registry, [], [], "unavailable")}


def prepare_scoped_context(search_result, requirement, verified_registry, *, max_chars=8000, max_tokens=None):
    registry = verified_registry
    if not isinstance(registry, Registry):
        _fail("invalid_source_registry")
    search = deepcopy(search_result)
    question = search.get("query") if isinstance(search, dict) else None
    req = _requirement(requirement, question)
    pairs = _search_pairs(search, registry)
    options = token_context_options(registry=registry, candidates=search["results"])
    if max_tokens is not None:
        options["max_tokens"] = max_tokens
    validate_search_round(search, question, list(pairs), max_chars=max_chars, **options)
    rows, decisions = _scope_rows(search, req, registry)
    context = {**select_context(rows, list(pairs), max_chars=max_chars, **options), "question": question,
               "score_kind": search.get("score_kind", "cosine"),
               "ranking_method": search.get("ranking_method", search.get("score_kind", "cosine"))}
    build_messages(question, context)
    return {"context": context, "qualification": _qualification(context, req, registry, [search], decisions, "initial")}


def merge_planned_scoped_context(searches, original_question, selected_versions, registry,
                                 *, max_chars=8000, max_chunks=8, requirement=None,
                                 retry_first=False, query_indices=None, round_kind="planned", max_tokens=None):
    """Qualify plan results against the complete question, then merge their ranks."""
    pairs = _pairs(selected_versions)
    if not isinstance(registry, Registry) or any(pair not in registry.pairs for pair in pairs):
        _fail("source_versions_mismatch")
    req = _requirement(requirement if requirement is not None else identify_source_requirement(original_question),
                       original_question)
    if not isinstance(searches, list):
        _fail("invalid_search_result")
    options = token_context_options(registry=registry)
    if max_tokens is not None:
        options["max_tokens"] = max_tokens
    checked_searches = deepcopy(searches)
    query_indices = list(range(1, len(searches) + 1)) if query_indices is None else query_indices
    groups, decisions = [], []
    for index, search in enumerate(checked_searches):
        query_pairs = _search_pairs(search, registry)
        if any(pair not in pairs for pair in query_pairs):
            _fail("source_versions_mismatch")
        rows, qualified = _scope_rows(search, req, registry)
        groups.append(rows)
        label = ("initial" if index == 0 else "retry") if retry_first else round_kind
        decisions.extend({**decision, "round": label, "query_index": query_indices[index]}
                         for decision in qualified)
    merged = merge_planned_context(checked_searches, original_question, list(pairs),
                                   max_chars=max_chars, max_chunks=max_chunks, candidate_groups=groups,
                                   retry_first=retry_first, query_indices=query_indices, round_kind=round_kind,
                                   **options)
    return {**merged, "qualification": _qualification(
        merged["context"], req, registry, checked_searches, decisions,
        "merged" if retry_first else round_kind, max_chunks)}


def merge_scoped_context(initial, retry, original_question, selected_versions, registry,
                         *, max_chars=8000, max_chunks=8, requirement=None, max_tokens=None):
    pairs = _pairs(selected_versions)
    if not isinstance(registry, Registry) or any(pair not in registry.pairs for pair in pairs):
        _fail("source_versions_mismatch")
    req = _requirement(requirement if requirement is not None else identify_source_requirement(original_question), original_question)
    if max_chunks is not None and (type(max_chunks) is not int or not 1 <= max_chunks <= 8):
        _fail("invalid_agent_evidence_count")
    options = token_context_options(registry=registry)
    if max_tokens is not None:
        options["max_tokens"] = max_tokens
    searches = [deepcopy(initial), deepcopy(retry)]
    validate_search_round(searches[0], original_question, list(pairs), max_chars=max_chars, **options)
    validate_search_round(searches[1], searches[1].get("query"), list(pairs), max_chars=max_chars, **options)
    if searches[0]["index_profile_id"] != searches[1]["index_profile_id"]:
        _fail("search_profile_mismatch")
    qualified = [_scope_rows(s, req, registry) for s in searches]
    retained, duplicates, origins = [], [], {}
    for label, index in (("retry", 1), ("initial", 0)):
        for item in qualified[index][0]:
            identifier = item["chunk_id"]
            origin = {"round": label, "rank": item["rank"], "score": item["score"]}
            if identifier in origins:
                duplicates.append({"chunk_id": identifier, **origin, "kept_origin": deepcopy(origins[identifier]), "reason": "duplicate"})
                continue
            ordinal = len(retained) + 1
            origins[identifier] = {**origin, "selection_ordinal": ordinal}
            retained.append({**deepcopy(item), "rank": ordinal})
    capped = retained if max_chunks is None else retained[:max_chunks]
    context = {**select_context(capped, list(pairs), max_chars=max_chars, **options), "question": original_question,
               "score_kind": searches[0].get("score_kind", "cosine"),
               "ranking_method": "retry_then_initial"}
    build_messages(original_question, context)
    round_contexts = [{**select_context(rows, list(pairs), max_chars=max_chars, **options), "question": original_question,
                      "score_kind": searches[index].get("score_kind", "cosine"),
                      "ranking_method": searches[index].get("ranking_method", searches[index].get("score_kind", "cosine"))}
                      for index, (rows, _) in enumerate(qualified)]
    ids = lambda rows: list(dict.fromkeys(row["chunk_id"] for row in rows))
    initial_ids, retry_ids = ids(searches[0]["results"]), ids(searches[1]["results"])
    initial_shown, final_shown = round_contexts[0]["allowed_citation_ids"], context["allowed_citation_ids"]
    trace = {"merge_version": "d9-qualified-retry-first-full-chunks-v1", "merge_order": "retry_rank_then_initial_rank",
             "deduplicate_key": "chunk_id", "cross_query_score_sort": False, "max_chunks": max_chunks,
             "max_chars": max_chars, "index_profile_id": searches[0]["index_profile_id"],
             "original_question": original_question, "selected_versions": deepcopy(context["selected_versions"]),
             "rounds": [{"round": label, "search": searches[i], "context": round_contexts[i]}
                        for i, label in enumerate(("initial", "retry"))],
             "merged_candidates": deepcopy(retained), "selection_origins": origins, "duplicates": duplicates,
             "count_omitted": [{"chunk_id": row["chunk_id"], **origins[row["chunk_id"]], "reason": "count_limit"} for row in
                                ([] if max_chunks is None else retained[max_chunks:])],
             "character_omitted": deepcopy(context["omitted_evidence"]),
             "initial_returned_ids": initial_ids, "retry_returned_ids": retry_ids, "merged_ids": ids(retained),
             "count_capped_ids": ids(capped), "initial_shown_ids": initial_shown, "final_shown_ids": final_shown,
             "new_returned_ids": [v for v in retry_ids if v not in initial_ids],
             "new_merged_ids": [v for v in ids(retained) if v not in initial_ids],
             "new_count_capped_ids": [v for v in ids(capped) if v not in initial_ids],
             "new_shown_ids": [v for v in final_shown if v not in initial_shown],
             "new_recalled_shown_ids": [v for v in final_shown if v not in initial_ids],
             "initial_returned_unshown_now_shown_ids": [v for v in final_shown if v in initial_ids and v not in initial_shown]}
    decisions = [{**d, "round": label} for index, label in enumerate(("initial", "retry")) for d in qualified[index][1]]
    return {"context": context, "trace": trace,
            "qualification": _qualification(context, req, registry, searches, decisions, "merged", max_chunks)}


def validate_citation_scope(answer, context, qualification, verified_registry, *, requirement=None):
    """Check only citations that will be published, against the loaded source range."""
    result = {"status": "valid", "checks": [], "error": None}
    try:
        registry = verified_registry
        if not isinstance(registry, Registry) or not isinstance(qualification, dict):
            _fail("invalid_source_qualification")
        req = _requirement(requirement if requirement is not None else qualification.get("requirement"), context.get("question"))
        build_messages(context["question"], context)
    except Exception as error:
        result.update(status="tool_error", error={"code": getattr(error, "code", "invalid_source_qualification"),
                                                 "message": "来源范围或证据快照核验失败"})
        return result
    try:
        raw = answer.model_dump(mode="python", warnings=False) if isinstance(answer, AnswerDraft) else answer
        parsed = AnswerDraft.model_validate(raw)
        parsed = AnswerDraft.model_validate(parsed.model_dump(mode="python", warnings=False))
    except Exception:
        result.update(status="invalid_output", error={"code": "invalid_draft_schema", "message": "答案结构未通过"})
        return result
    shown = set(context["allowed_citation_ids"])
    eligible = set()
    if req["resolution"] == "explicit":
        sources = {row["chunk_id"]: row for row in context["shown_evidence"]}
        try:
            for identifier in {v for claim in parsed.claims for v in claim.citation_ids} & shown:
                source = sources[identifier]
                candidate = {**source, "text": source["shown_text"]}
                if registry.qualify(candidate)["eligible"]:
                    eligible.add(identifier)
        except Exception as error:
            result.update(status="tool_error", error={"code": getattr(error, "code", "invalid_source_qualification"),
                                                     "message": "来源范围或证据快照核验失败"})
            return result
    for claim_index, claim in enumerate(parsed.claims):
        for citation_index, identifier in enumerate(claim.citation_ids):
            code = ("citation_not_shown" if identifier not in shown else
                    "source_constraint_ambiguous" if req["resolution"] == "ambiguous" else
                    "citation_source_scope_mismatch" if req["resolution"] == "explicit" and identifier not in eligible else None)
            result["checks"].append({"claim_index": claim_index, "citation_index": citation_index,
                                     "chunk_id": identifier, "status": "valid" if code is None else "invalid_output", "code": code})
            if code is not None and result["error"] is None:
                result.update(status="invalid_output", error={"code": code, "message": "引用未满足原问题来源范围"})
    return result


def validate_prose_citation_scope(citations, context, qualification, verified_registry, *, requirement=None):
    """Check only the published prose citation occurrences against source range."""
    result = {"status": "valid", "checks": [], "error": None}
    try:
        registry = verified_registry
        if not isinstance(registry, Registry) or not isinstance(qualification, dict):
            _fail("invalid_source_qualification")
        req = _requirement(requirement if requirement is not None else qualification.get("requirement"), context.get("question"))
        build_messages(context["question"], context)
    except Exception as error:
        result.update(status="tool_error", error={"code": getattr(error, "code", "invalid_source_qualification"),
                                                 "message": "来源范围或证据快照核验失败"})
        return result
    shown = set(context["allowed_citation_ids"])
    sources = {row["chunk_id"]: row for row in context["shown_evidence"]}
    eligible = set()
    if req["resolution"] == "explicit":
        try:
            for identifier in {row.get("chunk_id") for row in citations} & shown:
                source = sources[identifier]
                candidate = {**source, "text": source["shown_text"]}
                if registry.qualify(candidate)["eligible"]:
                    eligible.add(identifier)
        except Exception as error:
            result.update(status="tool_error", error={"code": getattr(error, "code", "invalid_source_qualification"),
                                                     "message": "来源范围或证据快照核验失败"})
            return result
    for citation_index, row in enumerate(citations):
        identifier = row.get("chunk_id")
        code = ("citation_not_shown" if identifier not in shown else
                "source_constraint_ambiguous" if req["resolution"] == "ambiguous" else
                "citation_source_scope_mismatch" if req["resolution"] == "explicit" and identifier not in eligible else None)
        result["checks"].append({"claim_index": 0, "citation_index": citation_index,
                                 "chunk_id": identifier, "status": "valid" if code is None else "invalid_output", "code": code})
        if code is not None and result["error"] is None:
            result.update(status="invalid_output", error={"code": code, "message": "引用未满足原问题来源范围"})
    return result
