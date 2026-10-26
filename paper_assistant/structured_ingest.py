"""Prepare one MinerU version for the existing SQLite and vector import flow."""

from collections import Counter
import json
from pathlib import Path
import shutil
from uuid import uuid4

import httpx

from paper_assistant.chunking import pretty_json_bytes, sha256_bytes
from paper_assistant.indexing import digest
from paper_assistant.ingest import save_page_records
from paper_assistant.mineru_parser import api_parser_profile, parse_structured_pdf, structure_units
from paper_assistant.storage import StoredVersionInput


PARSER = {"name": "mineru", "version": "4.0.12", "tier": "standard",
          "page_range": "all", "ocr_mode": "auto", "image_analysis": False,
          "adapter_revision": "structured-source-v3"}
TOKENIZER = "Qwen/Qwen3-Embedding-0.6B"
CHUNKING = {"child_tokens": 512, "parent_tokens": 1536, "tokenizer": TOKENIZER,
            "revision": "structured-pdf-v2"}


def load_token_counter(root):
    """Load Qwen's local tokenizer; only the first normal import downloads its data."""
    from tokenizers import Tokenizer
    path = Path(root) / "data/models/Qwen3-Embedding-0.6B/tokenizer.json"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get("https://modelscope.cn/models/Qwen/Qwen3-Embedding-0.6B/resolve/master/tokenizer.json")
            response.raise_for_status()
            path.write_bytes(response.content)
    tokenizer = Tokenizer.from_file(str(path))
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)


def prepare_structured_version(pdf_bytes, paper, result, root, store, progress, *,
                               source_url, page_count, pdf_sha256,
                               parser_profile=None, api_bundle=None, api_batch_id=None):
    from paper_assistant.structured_chunking import build_structured_chunks

    root = Path(root).resolve()
    api_dir = None
    if api_bundle is not None:
        api_dir = Path(api_bundle)
        if not api_dir.is_absolute():
            api_dir = (root / api_dir).resolve()
        if not api_dir.is_dir() or not api_dir.is_relative_to(root):
            raise ValueError("API 解析结果目录必须位于项目内。")
        if parser_profile is None:
            parser_profile = api_parser_profile(api_dir / "layout.json")
    parser = dict(parser_profile or PARSER)
    if paper is None:
        identifier = "local_" + uuid4().hex
        paper = {"paper_id": identifier, "source_type": "local", "arxiv_version": "",
                 "title": result["title"], "source_url": (source_url or "").strip(),
                 "local_path": "data/papers/" + identifier + ".pdf", "pdf_sha256": pdf_sha256,
                 "page_count": page_count, "text_selectable": True}
    result.update(paper_id=paper["paper_id"], title=paper["title"], parser=dict(parser))
    recipe = {"paper_id": paper["paper_id"], "pdf_sha256": paper["pdf_sha256"],
              "parser": dict(parser), "chunking": dict(CHUNKING)}
    # Reuse the existing recipe-based version identity, including this parsing scheme.
    recipe_sha256 = digest(recipe)
    revision = "r_" + recipe_sha256[:16]
    result["parse_revision"] = revision
    old = store.connection.execute(
        "SELECT parse_revision, chunk_count, statistics_json FROM parse_versions "
        "WHERE paper_id = ? AND parse_revision = ?", (paper["paper_id"], revision)).fetchone()
    if old is not None:
        result.update(json.loads(old["statistics_json"]))
        return paper, {**dict(old), "reused": True}

    pdf_path = root / paper["local_path"]
    if not pdf_path.is_file():
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pdf_bytes)
    folder_relative = f"data/chunks/{paper['paper_id']}/{revision}"
    folder = root / folder_relative
    # Source adaptation can change without rerunning the same complete MinerU parse.
    if not (folder / "mineru/middle_json.json").is_file() and api_dir is None:
        previous = store.connection.execute("SELECT manifest_json FROM parse_versions WHERE paper_id = ? ORDER BY rowid DESC",
                                            (paper["paper_id"],)).fetchall()
        for row in previous:
            metadata = json.loads(row["manifest_json"])
            deployed = metadata.get("recipe", {}).get("parser", {})
            if all(deployed.get(key) == value for key, value in parser.items() if key != "adapter_revision"):
                source = root / metadata["source_paths"]["structure"]
                if source.is_file():
                    shutil.copytree(source.parent, folder / "mineru", dirs_exist_ok=True)
                    result["reused_parse"] = True
                    break
    api_layout = api_dir / "layout.json" if api_dir is not None else None
    parse_options = {} if api_layout is None else {"api_layout": api_layout}
    middle = parse_structured_pdf(pdf_path, folder / "mineru", project_root=root, **parse_options)
    units = structure_units(middle)
    progress("chunk")
    built = build_structured_chunks(units, paper, revision, count_tokens=load_token_counter(root),
                                    child_tokens=CHUNKING["child_tokens"], parent_tokens=CHUNKING["parent_tokens"])
    parents, chunks = built["parents"], built["chunks"]
    if not chunks:
        raise ValueError("MinerU 结构结果没有可索引的正文或图表内容。")
    pages = Counter(chunk["pdf_page"] for chunk in chunks)
    statistics = {"page_count": page_count, "parent_count": len(parents), "source_block_count": len(units),
                  "chunk_count": len(chunks), "max_chunk_tokens": max(chunk["token_count"] for chunk in chunks),
                  "chunks_per_page": {str(page): pages[page] for page in range(1, page_count + 1)}}
    api_relative = api_dir.relative_to(root).as_posix() if api_dir is not None else None
    source_paths = {"pdf": paper["local_path"], "structure": folder_relative + "/mineru/middle_json.json",
                    "sources": folder_relative + "/sources.jsonl",
                    "parents": folder_relative + "/parents.jsonl", "chunks": folder_relative + "/chunks.jsonl",
                    "paper": folder_relative + "/paper.json"}
    if api_relative:
        source_paths.update({"api_bundle": api_relative, "api_layout": api_relative + "/layout.json",
                             "api_markdown": api_relative + "/full.md"})
    metadata = {"schema_revision": "structured-pdf-v1", "paper_id": paper["paper_id"],
                "parse_revision": revision, "recipe_sha256": recipe_sha256, "recipe": recipe,
                "source_paths": source_paths, "statistics": statistics}
    if api_relative:
        metadata["parse_source"] = {"kind": "mineru-api", "bundle": api_relative,
                                    "batch_id": api_batch_id, "markdown": api_relative + "/full.md",
                                    "layout": api_relative + "/layout.json"}
        result["parse_source"] = dict(metadata["parse_source"])
    metadata_bytes = pretty_json_bytes(metadata)
    progress("store")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "paper.json").write_bytes(pretty_json_bytes(paper))
    save_page_records(units, folder / "sources.jsonl")
    save_page_records(parents, folder / "parents.jsonl")
    save_page_records(chunks, folder / "chunks.jsonl")
    # This is the existing version record, not a separate asset/hash inventory.
    (folder / "version_manifest.json").write_bytes(metadata_bytes)
    stored = store.import_version(StoredVersionInput(
        paper, metadata, chunks, folder_relative, sha256_bytes(metadata_bytes), parents=parents))
    result.update(statistics)
    return paper, {"parse_revision": revision, "chunk_count": len(chunks), "reused": stored["reused"]}
