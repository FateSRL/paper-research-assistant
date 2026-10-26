"""D5 D：只回查本轮展示过的引用，程序填来源；不判断结论的语义支持。"""

from copy import deepcopy
import hashlib
from pathlib import Path, PureWindowsPath
import re

import fitz

from paper_assistant.context import build_messages
from paper_assistant.schemas import AnswerDraft, EvidenceRef


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FIELDS = (
    "chunk_id", "paper_id", "parse_revision", "pdf_page", "text", "text_sha256",
    "pdf_sha256", "title", "arxiv_version", "source_url", "local_path",
)
_SOURCE_LOCATION_FIELDS = (
    "parent_id", "source_spans", "section_path", "content_type", "content_types",
    "assets", "reading_origins", "segment_id", "char_start", "char_end",
    "source_block_index", "source_line_indices", "segment_bbox",
)
_REF_FIELDS = ("chunk_id", "paper_id", "parse_revision", "pdf_page")
_ERROR_MESSAGE = "引用回查未通过，请核对安全错误代码"


class _SourceError(ValueError):
    def __init__(self, code):
        super().__init__(_ERROR_MESSAGE)
        self.code = code


def _pdf_path(project_root: Path, local_path: str) -> Path:
    """只允许项目 data/papers 内的相对文件；拒绝盘符、父目录与符号链接逃逸。"""
    try:
        relative = Path(local_path)
        windows = PureWindowsPath(local_path)
        if (relative.is_absolute() or relative.anchor or windows.drive or windows.root
                or ".." in relative.parts or ".." in windows.parts):
            raise _SourceError("pdf_path_invalid")
        root = Path(project_root).resolve()
        papers = (root / "data" / "papers").resolve()
        path = (root / relative).resolve()
        if not papers.is_relative_to(root) or not path.is_relative_to(papers) or path == papers:
            raise _SourceError("pdf_path_invalid")
        return path
    except _SourceError:
        raise
    except Exception:
        raise _SourceError("pdf_path_invalid") from None


def _pdf_info(path: Path, expected_sha256: str, cache: dict) -> dict:
    """每次校验同一实际 PDF 只读一次字节、最多打开一次；不返回文件正文。"""
    if path not in cache:
        entry = {"error": None, "contents": None, "actual_pdf_sha256": None,
                 "actual_page_count": None, "opened": False}
        cache[path] = entry
        try:
            entry["contents"] = path.read_bytes()
            entry["actual_pdf_sha256"] = hashlib.sha256(entry["contents"]).hexdigest()
        except FileNotFoundError:
            entry["error"] = "pdf_missing"
        except IsADirectoryError:
            entry["error"] = "pdf_path_invalid"
        except Exception:
            entry["error"] = "pdf_read_failed"
    entry = cache[path]
    if entry["error"]:
        raise _SourceError(entry["error"])
    if entry["actual_pdf_sha256"] != expected_sha256:
        raise _SourceError("pdf_hash_mismatch")
    if not entry["opened"]:
        entry["opened"] = True
        try:
            with fitz.open(stream=entry["contents"], filetype="pdf") as document:
                if document.needs_pass or document.page_count < 1:
                    raise ValueError("unreadable PDF")
                entry["actual_page_count"] = document.page_count
        except Exception:
            entry["error"] = "pdf_invalid"
        finally:
            # 页数已取得或打开已失败，此后无需继续保留整份 PDF 字节。
            entry["contents"] = None
    if entry["error"]:
        raise _SourceError(entry["error"])
    return {key: entry[key] for key in ("actual_pdf_sha256", "actual_page_count")}


def _checked_source(stored: dict, shown: dict, project_root: Path, pdf_cache: dict) -> dict:
    """重验完整身份、页码和全文快照，再核当前 PDF；不接受模型给出的来源元数据。"""
    if not isinstance(stored, dict) or any(field not in stored for field in _SOURCE_FIELDS):
        raise _SourceError("source_record_invalid")
    source = {field: stored[field] for field in _SOURCE_FIELDS}
    if (any(not isinstance(source[field], str)
            or (field not in ("arxiv_version", "source_url") and not source[field].strip())
            for field in _SOURCE_FIELDS if field != "pdf_page")
            or type(source["pdf_page"]) is not int or source["pdf_page"] < 1
            or not _SHA256.fullmatch(source["text_sha256"])
            or not _SHA256.fullmatch(source["pdf_sha256"])):
        raise _SourceError("source_record_invalid")
    if (any(source[field] != shown[field] for field in _REF_FIELDS)
            or source["text"] != shown["shown_text"]
            or source["text_sha256"] != shown["text_sha256"]
            or source["text_sha256"] != shown["shown_text_sha256"]):
        raise _SourceError("source_snapshot_mismatch")
    # EvidenceRef 的四字段仅从经过回查的库记录产生，严格页码检查不依赖类型注解。
    EvidenceRef.model_validate({field: source[field] for field in _REF_FIELDS})
    path = _pdf_path(project_root, source["local_path"])
    info = _pdf_info(path, source["pdf_sha256"], pdf_cache)
    if source["pdf_page"] > info["actual_page_count"]:
        raise _SourceError("pdf_page_out_of_bounds")
    source.update({field: deepcopy(stored[field]) for field in _SOURCE_LOCATION_FIELDS if field in stored})
    return {**source, "pdf_absolute_path": str(path), **info}


def validate_citations(draft: AnswerDraft | dict, context: dict, store, *, project_root: Path) -> dict:
    """返回整份草稿的来源校验结果，不查询展示集合以外的 ID。

    checks 使用从 0 开始的 claim_index/citation_index，逐次记录重复引用；
    通过后 evidence_refs/sources 按首次引用顺序去重。任何失败均不发布来源。
    未展示的 ID 是 invalid_output；展示证据或库/PDF 损坏是 tool_error，
    后者优先且不应通过模型修复。合法 insufficient_evidence 不回查库。
    """
    result = {"status": "valid", "checks": [], "evidence_refs": [],
              "evidence_sources": [], "error": None}
    try:
        # 冻结到本次函数的独立副本，store 回查期间外部修改不能扩大展示集合。
        checked_context = deepcopy(context)
        build_messages(checked_context.get("question") if isinstance(checked_context, dict) else None,
                       checked_context)
    except Exception:
        result.update(status="tool_error", error={"code": "invalid_context", "message": _ERROR_MESSAGE})
        return result
    try:
        # 模型对象可能来自 model_construct 或被调用者修改，不能因 isinstance 而跳过重验。
        value = draft.model_dump(mode="python", warnings=False) if isinstance(draft, AnswerDraft) else draft
        parsed = AnswerDraft.model_validate(value)
        # dict 里也可能嵌入未经重验的 Claim 对象，转回纯字段后再次严格验证。
        checked = AnswerDraft.model_validate(parsed.model_dump(mode="python", warnings=False))
    except Exception:
        result.update(status="invalid_output", error={"code": "invalid_draft_schema", "message": _ERROR_MESSAGE})
        return result
    if checked.status == "insufficient_evidence":
        return result

    snapshots = {item["chunk_id"]: item for item in checked_context["shown_evidence"]}
    chunk_cache, pdf_cache, sources = {}, {}, {}
    failures = []
    for claim_index, claim in enumerate(checked.claims):
        for citation_index, chunk_id in enumerate(claim.citation_ids):
            status, code = "valid", None
            if chunk_id not in snapshots:
                status, code = "invalid_output", "citation_not_shown"
            else:
                if chunk_id not in chunk_cache:
                    try:
                        stored = store.get_chunk(chunk_id)
                    except Exception:
                        chunk_cache[chunk_id] = ("tool_error", "source_lookup_failed", None)
                    else:
                        if stored is None:
                            chunk_cache[chunk_id] = ("tool_error", "source_missing", None)
                        else:
                            try:
                                source = _checked_source(stored, snapshots[chunk_id], project_root, pdf_cache)
                            except _SourceError as error:
                                chunk_cache[chunk_id] = ("tool_error", error.code, None)
                            except Exception:
                                chunk_cache[chunk_id] = ("tool_error", "source_record_invalid", None)
                            else:
                                chunk_cache[chunk_id] = ("valid", None, source)
                status, code, source = chunk_cache[chunk_id]
                if status == "valid" and chunk_id not in sources:
                    origins = [deepcopy(row) for row in checked_context.get("reading_origins", [])
                               if row.get("chunk_id") == chunk_id]
                    if origins:
                        source["reading_origins"] = origins
                    sources[chunk_id] = source
            result["checks"].append({"claim_index": claim_index, "citation_index": citation_index,
                                     "chunk_id": chunk_id, "status": status, "code": code})
            if status != "valid":
                failures.append((status, code))
    if failures:
        status, code = next((item for item in failures if item[0] == "tool_error"), failures[0])
        result.update(status=status, error={"code": code, "message": _ERROR_MESSAGE})
        return result
    result["evidence_sources"] = deepcopy(list(sources.values()))
    result["evidence_refs"] = [EvidenceRef.model_validate({field: source[field] for field in _REF_FIELDS})
                               .model_dump(mode="json") for source in sources.values()]
    return result
