"""Stable source handles and the single parsing pass for prose citations."""

import re

from copy import deepcopy


MARKER = re.compile(r"\[ID:(\d+)\]")

# Adapted from RAGFlow agentic_rag/evidence_registry.go and citations.go,
# service/agentic_reference.go and citation.go. Explicit IDs only, 1-based here;
# identity is the saved paper/version/chunk, without served-text hashing.
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ID = r"\*{0,2}ID\s*[:：]\s*([0-9٠-٩۰-۹]+)\*{0,2}"
COMPAT_MARKER = re.compile(r"[\[（(【]\s*(" + _ID + r"(?:\s*[,，]\s*" + _ID + r")*)\s*[\]）)】]")
ID_NUMBER = re.compile(_ID)


def normalize_citation_markers(text):
    """Normalize explicit ID variants/combined handles before strict scanning."""
    return COMPAT_MARKER.sub(lambda match: "".join(
        "[ID:" + number.translate(ARABIC_DIGITS) + "]"
        for number in ID_NUMBER.findall(match.group(1))), text)


class EvidenceRegistry:
    """One question's stable handles; visibility remains owned by its context."""

    def __init__(self):
        self._refs = {}
        self._rows = {}

    @staticmethod
    def key(row):
        return (row["paper_id"], row["parse_revision"], row["chunk_id"])

    def stamp(self, context):
        for row in context.get("shown_evidence") or []:
            key = self.key(row)
            if key not in self._refs:
                number = len(self._refs) + 1
                self._refs[key] = number
                self._rows[number] = dict(zip(("paper_id", "parse_revision", "chunk_id"), key))
            row["ref"] = self._refs[key]
        context["allowed_refs"] = [row["ref"] for row in context.get("shown_evidence") or []]
        return context

    def sources(self, context):
        return [{"ref": self._refs[self.key(row)], "chunk_id": row["chunk_id"],
                 "text": row["shown_text"], "paper_id": row["paper_id"],
                 "parse_revision": row["parse_revision"], "pdf_page": row.get("pdf_page"),
                 "section_path": deepcopy(row.get("section_path", [])),
                 "content_type": row.get("content_type")}
                for row in context.get("shown_evidence") or []]

    def resolve(self, number, context):
        row = self._rows.get(number)
        if row is None:
            raise ValueError("citation_unknown_ref")
        if not any(self.key(visible) == self.key(row) for visible in context.get("shown_evidence") or []):
            raise ValueError("citation_not_shown")
        return row["chunk_id"]

    def snapshot(self):
        return [{"ref": number, **deepcopy(row)} for number, row in self._rows.items()]


def source_refs(context, registry):
    """Use registered handles for currently visible originals, never list indices."""
    return registry.sources(context)


def prompt_sources(refs):
    """The model-facing source list with the stable handle and source text."""
    return [deepcopy(row) for row in refs]


def parse_markers(text):
    """Return every [ID:n] occurrence once, including repeated references."""
    if not isinstance(text, str):
        return []
    return [{"index": index, "position": match.start(), "ref": int(match.group(1))}
            for index, match in enumerate(MARKER.finditer(text))]
