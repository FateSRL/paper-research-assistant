"""Import a local PDF through the existing parser, fact store and vector index."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import pymupdf

from paper_assistant.agent_runtime import load_current_profile
from paper_assistant.chunking import ChunkingConfig, build_chunks, pretty_json_bytes, sha256_bytes
from paper_assistant.config import ConfigError, load_embedding_settings, load_mineru_api_settings
from paper_assistant.embedding_client import EmbeddingAPIError, embed_texts
from paper_assistant.indexing import EmbeddingCache, IndexBuilder, IndexingError, digest
from paper_assistant.ingest import parse_pdf_pages, save_page_records
from paper_assistant.mineru_api import parse_pdf_via_api
from paper_assistant.quality import FILTER_REVISION, filter_paper_pages, iter_indexable_segments
from paper_assistant.retrieval import QdrantStore, VectorStoreError
from paper_assistant.storage import PaperStore, StorageError, StoredVersionInput


ROOT = Path(__file__).resolve().parents[1]


def import_pdf(pdf_bytes, filename, *, title=None, source_url="", project_root=ROOT, on_progress=None,
               parser="mineru-api", api_bundle=None, api_batch_id=None):
    """Import a PDF with the selected parsing scheme; retain prior versions and caches."""
    started = phase_started = perf_counter()
    phase = "parse"
    stage_times = {name: 0.0 for name in ("parse", "filter", "chunk", "store", "index")}
    root = Path(project_root).resolve()
    filename = Path(str(filename).replace("\\", "/")).name
    result = {"status": "pending", "paper_id": None, "parse_revision": None,
              "title": (title or "").strip() or Path(filename).stem or "本地论文",
              "chunk_count": 0, "stage": "parse", "embedding_requests": 0,
              "cached_reused_count": 0, "generated_count": 0, "upserted_count": 0,
              "reused_ready": False, "requests": [], "request_statistics": None,
              "cache_statistics": None}
    builder = cache = None

    def update_timings(next_phase=None):
        nonlocal phase, phase_started
        now = perf_counter()
        if phase in stage_times:
            stage_times[phase] += now - phase_started
        phase_started = now
        if next_phase is not None:
            phase = next_phase
        result["elapsed_seconds"] = round(now - started, 6)
        result["stage_timings_seconds"] = {name: round(seconds, 6) for name, seconds in stage_times.items()}
        result["stage_timings_seconds"]["preparation"] = round(sum(
            stage_times[name] for name in ("parse", "filter", "chunk", "store")), 6)

    def update_statistics():
        if builder is not None:
            stats = builder.request_stats()
            stats["total_tokens"] = stats["known_total_tokens"] if not stats["usage_missing_requests"] else None
            result.update(embedding_requests=stats["embedding_requests"], request_statistics=stats,
                          requests=deepcopy(builder.requests),
                          generated_count=sum(row["chunk_count"] for row in builder.requests
                                              if row["status"] == "cached"))
        if cache is not None:
            result["cache_statistics"] = cache.stats()

    def progress(stage, **fields):
        update_timings(stage)
        update_statistics()
        result["stage"] = stage
        if on_progress:
            on_progress({**result, **fields})

    try:
        progress("parse")
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("暂不支持需要密码的 PDF，请先提供可直接打开的文件。")
            if document.page_count < 1:
                raise ValueError("PDF 没有可读取的页面。")
            page_count = document.page_count
        pdf_sha256 = sha256_bytes(pdf_bytes)
        index_root = root / "data/index"
        with PaperStore(index_root / "papers.sqlite3") as store:
            matches = store.connection.execute(
                "SELECT paper_json FROM papers WHERE pdf_sha256 = ?", (pdf_sha256,)).fetchall()
            paper = json.loads(matches[0]["paper_json"]) if matches else None
            if parser == "mineru-standard":
                from paper_assistant.structured_ingest import prepare_structured_version
                paper, version = prepare_structured_version(
                    pdf_bytes, paper, result, root, store, progress,
                    source_url=source_url, page_count=page_count, pdf_sha256=pdf_sha256)
            elif parser == "mineru-api":
                parser_profile = None
                # Reuse a previously imported API bundle for the same PDF before
                # uploading another task. Local Standard versions never qualify.
                if api_bundle is None and paper is not None:
                    previous = store.connection.execute(
                        "SELECT manifest_json FROM parse_versions WHERE paper_id = ? ORDER BY rowid DESC",
                        (paper["paper_id"],)).fetchall()
                    for row in previous:
                        metadata = json.loads(row["manifest_json"])
                        source = metadata.get("parse_source") or {}
                        if source.get("kind") != "mineru-api" or not source.get("bundle"):
                            continue
                        candidate = (root / source["bundle"]).resolve()
                        if candidate.is_dir() and (candidate / "layout.json").is_file():
                            api_bundle = candidate
                            api_batch_id = source.get("batch_id")
                            parser_profile = metadata.get("recipe", {}).get("parser")
                            break
                if api_bundle is None:
                    api_dir = root / "data/mineru_api" / pdf_sha256
                    if api_dir.exists():
                        if not (api_dir / "layout.json").is_file() or not (api_dir / "full.md").is_file():
                            raise ValueError("已有未完成的 MinerU API 结果目录，拒绝重复上传："
                                             + str(api_dir.relative_to(root)))
                        api_bundle = api_dir
                    else:
                        settings = load_mineru_api_settings()
                        api_input = root / "data/mineru_api" / (pdf_sha256 + ".pdf")
                        api_input.parent.mkdir(parents=True, exist_ok=True)
                        if not api_input.is_file():
                            api_input.write_bytes(pdf_bytes)
                        parsed = parse_pdf_via_api(
                            api_input, api_dir, settings,
                            on_progress=lambda message: progress("parse", parser_message=message))
                        api_bundle = parsed["output_dir"]
                        api_batch_id = parsed["batch_id"]
                from paper_assistant.mineru_parser import api_parser_profile
                from paper_assistant.structured_ingest import prepare_structured_version
                bundle = Path(api_bundle)
                if not bundle.is_absolute():
                    bundle = root / bundle
                if parser_profile is None:
                    profile = api_parser_profile(bundle / "layout.json")
                else:
                    profile = parser_profile
                paper, version = prepare_structured_version(
                    pdf_bytes, paper, result, root, store, progress,
                    source_url=source_url, page_count=page_count, pdf_sha256=pdf_sha256,
                    parser_profile=profile, api_bundle=bundle, api_batch_id=api_batch_id)
            elif parser == "legacy":
                candidates = [] if paper is None else store.connection.execute(
                    "SELECT parse_revision, chunk_count, manifest_json FROM parse_versions "
                    "WHERE paper_id = ? ORDER BY rowid DESC", (paper["paper_id"],)).fetchall()
                version = next((dict(row) for row in candidates
                                if json.loads(row["manifest_json"])["schema_revision"] == "d4-chunk-version-v1"), None)
            else:
                raise ValueError("未知 PDF 解析方案：" + str(parser))
            if version is not None:
                result.update(paper_id=paper["paper_id"], title=paper["title"], reused=version.get("reused", True),
                              parse_revision=version["parse_revision"], chunk_count=version["chunk_count"])
            else:
                paper_id = paper["paper_id"] if paper else "local_" + uuid4().hex
                paper = paper or {"paper_id": paper_id, "source_type": "local", "arxiv_version": "",
                         "title": result["title"], "source_url": (source_url or "").strip(),
                         "local_path": "data/papers/" + paper_id + ".pdf",
                         "pdf_sha256": pdf_sha256, "page_count": page_count,
                         "text_selectable": True}
                result.update(paper_id=paper_id)
                pdf_path = root / paper["local_path"]
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(pdf_bytes)
                raw_pages = parse_pdf_pages(paper, root)
                if not any(page["text"].strip() for page in raw_pages):
                    raise ValueError("PDF 没有可提取的正文；暂不支持纯扫描 PDF。")

                progress("filter")
                rules = json.loads((root / "eval/quality_rules.json").read_text(encoding="utf-8-sig"))
                filtered_pages = filter_paper_pages(paper, raw_pages, root, rules)
                if not any(iter_indexable_segments(filtered_pages)):
                    raise ValueError("PDF 过滤后没有可入库的正文。")

                progress("chunk")
                from paper_assistant.source_scope import detect_abstract_regions
                regions = detect_abstract_regions(filtered_pages)
                boundaries = {}
                for region in regions:
                    boundaries.setdefault(region["segment_id"], []).extend(
                        [region["segment_char_start"], region["segment_char_end"]])
                config = ChunkingConfig()
                recipe = {"paper_id": paper_id, "pdf_sha256": pdf_sha256,
                          "filter_revision": FILTER_REVISION, "chunking": asdict(config)}
                recipe_sha256 = digest(recipe)
                revision = "r_" + recipe_sha256[:16]
                chunks = build_chunks(filtered_pages, paper, revision, config, segment_boundaries=boundaries)
                result.update(parse_revision=revision, chunk_count=len(chunks))
                folder_relative = "data/chunks/" + paper_id + "/" + revision
                folder = root / folder_relative
                source_paths = {"pdf": paper["local_path"],
                                "raw": folder_relative + "/raw.pages.jsonl",
                                "filtered": folder_relative + "/filtered.pages.jsonl",
                                "chunks": folder_relative + "/chunks.jsonl"}
                pages = Counter(chunk["pdf_page"] for chunk in chunks)
                segments = Counter(chunk["segment_id"] for chunk in chunks)
                manifest = {"schema_revision": "d4-chunk-version-v1", "paper_id": paper_id,
                            "parse_revision": revision, "recipe_sha256": recipe_sha256, "recipe": recipe,
                            "source_paths": source_paths, "source_regions": regions,
                            "statistics": {"page_count": page_count, "segment_count": len(segments),
                                           "chunk_count": len(chunks),
                                           "split_segment_count": sum(count > 1 for count in segments.values()),
                                           "max_chunk_chars": max(len(chunk["text"]) for chunk in chunks),
                                           "chunks_per_page": {str(page): pages[page]
                                                               for page in range(1, page_count + 1)}}}
                manifest_bytes = pretty_json_bytes(manifest)
                bundle = StoredVersionInput(paper, manifest, chunks, folder_relative, sha256_bytes(manifest_bytes))

                progress("store")
                folder.mkdir(parents=True, exist_ok=True)
                save_page_records(raw_pages, root / source_paths["raw"])
                save_page_records(filtered_pages, root / source_paths["filtered"])
                save_page_records(chunks, root / source_paths["chunks"])
                (folder / "version_manifest.json").write_bytes(manifest_bytes)
                stored = store.import_version(bundle)
                result["reused"] = stored["reused"]

            progress("index")
            profile = load_current_profile(root)
            settings = load_embedding_settings()
            result["index_profile_id"] = profile["index_profile_id"]
            with QdrantStore(index_root / "qdrant", profile["collection_name"],
                             profile["index_profile_id"], settings.dimension) as vectors, \
                    httpx.Client(timeout=30.0, follow_redirects=False) as http_client:
                cache = EmbeddingCache(index_root / "embeddings", profile)

                def index_progress(event):
                    paper_progress = event.get("paper", {})
                    for name in ("cached_reused_count", "upserted_count", "completed_count", "reused_ready"):
                        if name in paper_progress:
                            result[name] = paper_progress[name]
                    update_timings()
                    update_statistics()
                    if on_progress:
                        on_progress({**result, **event})

                builder = IndexBuilder(store, vectors, cache, settings, profile,
                                       embedder=partial(embed_texts, http_client=http_client), on_progress=index_progress)
                imported = builder.import_version(paper["paper_id"], result["parse_revision"])
                result.update(embedding_requests=imported["embedding_requests"],
                              completed_count=imported["completed_count"],
                              reused_ready=imported["reused_ready"], status="ready")
        progress("ready")
        return result
    except Exception as error:
        safe_types = (ConfigError, EmbeddingAPIError, IndexingError, StorageError, VectorStoreError, ValueError)
        result.update(status="failed", error=str(error) if isinstance(error, safe_types)
                      else "入库未完成：" + type(error).__name__)
        return result
    finally:
        update_statistics()
        update_timings()
