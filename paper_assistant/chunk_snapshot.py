"""D4 任务 C 的输入边界：读取并核对任务 B 的不可变分块快照。

SQLite 应存已经保存的处理版本，而不是入库时再生成一套新块。
本模块只读取版本目录与原 PDF，不会执行快照中的 Python 源码。
"""

from collections import Counter, defaultdict
import json
from pathlib import Path

from paper_assistant.chunking import SAFE_ID, canonical_json_bytes, sha256_bytes
from paper_assistant.quality import iter_indexable_segments
from paper_assistant.storage import StoredVersionInput


class SnapshotError(ValueError):
    """版本清单、文件字节或来源不一致，拒绝进入数据库。"""


def _file_inside(parent: Path, relative: str) -> Path:
    """解析相对路径并检查最终位置，防止错读其他目录的同名文件。"""
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise SnapshotError("快照路径必须是相对路径")
    path = (parent / relative).resolve()
    if not path.is_relative_to(parent) or not path.is_file():
        raise SnapshotError(f"文件缺失或路径超出预期目录：{relative}")
    return path


def _read_jsonl(value: bytes, description: str) -> list[dict]:
    try:
        rows = [json.loads(line) for line in value.decode("utf-8-sig").splitlines() if line.strip()]
    except (UnicodeError, ValueError) as error:
        raise SnapshotError(f"{description} 不是有效 JSONL") from error
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise SnapshotError(f"{description} 必须包含非空对象记录")
    return rows


def load_chunk_version(project_root: Path, paper_id: str, parse_revision: str) -> StoredVersionInput:
    """核对已保存版本，并返回存储层的入库材料。

    校验顺序是位置 → 清单身份 → 文件字节 → 来源 → chunk 内容与覆盖。
    任何一层不一致都在数据库事务开始前拒绝；不通过重新运行分块来
    修补旧版本，也不要求旧版本的派生文本等于当前最新过滤文件。
    """
    project_root = project_root.resolve()
    if any(not isinstance(value, str) or not SAFE_ID.fullmatch(value) for value in (paper_id, parse_revision)):
        raise SnapshotError("论文和版本必须是安全的非空标识符")
    base = (project_root / "data/chunks").resolve()
    folder = (base / paper_id / parse_revision).resolve()
    if not base.is_relative_to(project_root) or not folder.is_relative_to(base):
        raise SnapshotError("版本目录超出项目的 data/chunks")
    manifest_bytes = _file_inside(folder, "version_manifest.json").read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        if manifest["schema_revision"] == "structured-pdf-v1":
            if manifest["paper_id"] != paper_id or manifest["parse_revision"] != parse_revision:
                raise SnapshotError("目录与结构版本身份不同")
            paper = json.loads(_file_inside(folder, "paper.json").read_text(encoding="utf-8-sig"))
            parents = _read_jsonl(_file_inside(folder, "parents.jsonl").read_bytes(), "结构父内容")
            chunks = _read_jsonl(_file_inside(folder, "chunks.jsonl").read_bytes(), "结构检索子块")
            return StoredVersionInput(paper=paper, manifest=manifest, chunks=chunks, parents=parents,
                snapshot_path=folder.relative_to(project_root).as_posix(),
                manifest_sha256=sha256_bytes(manifest_bytes))
        if manifest["schema_revision"] != "d4-chunk-version-v1":
            raise SnapshotError("不支持的分块清单结构版本")
        recipe = manifest["recipe"]
        fingerprint = sha256_bytes(canonical_json_bytes(recipe))
        if (
            manifest["paper_id"] != paper_id or manifest["parse_revision"] != parse_revision
            or manifest["recipe_sha256"] != fingerprint or parse_revision != "r_" + fingerprint[:16]
        ):
            raise SnapshotError("目录、论文、版本和处理指纹不一致")

        required = {
            "chunks.jsonl", "raw.pages.jsonl", "filtered.pages.jsonl", "quality_rules.json", "paper.json",
            "pipeline/ingest.py", "pipeline/quality.py", "pipeline/chunking.py",
        }
        if not isinstance(manifest["files"], dict) or set(manifest["files"]) != required:
            raise SnapshotError("快照文件清单不完整或有未知项")
        file_bytes = {}
        for name, info in manifest["files"].items():
            value = _file_inside(folder, name).read_bytes()
            if len(value) != info["bytes"] or sha256_bytes(value) != info["sha256"]:
                raise SnapshotError(f"快照文件哈希/长度不一致：{name}")
            file_bytes[name] = value

        paper = json.loads(file_bytes["paper.json"].decode("utf-8-sig"))
        if paper["paper_id"] != paper_id or recipe["paper_id"] != paper_id:
            raise SnapshotError("论文元数据对应另一篇论文")
        if paper["pdf_sha256"] != recipe["pdf_sha256"]:
            raise SnapshotError("论文元数据与处理指纹的 PDF 哈希不同")
        hashes = {
            "paper_metadata_sha256": "paper.json", "raw_jsonl_sha256": "raw.pages.jsonl",
            "filtered_jsonl_sha256": "filtered.pages.jsonl", "quality_rules_sha256": "quality_rules.json",
        }
        for key, name in hashes.items():
            if recipe[key] != sha256_bytes(file_bytes[name]):
                raise SnapshotError(f"处理配置与快照的来源哈希不同：{name}")
        if (
            not isinstance(recipe["processing_source_sha256"], dict)
            or set(recipe["processing_source_sha256"]) != {"ingest.py", "quality.py", "chunking.py"}
        ):
            raise SnapshotError("处理代码来源清单不完整")
        for name, digest in recipe["processing_source_sha256"].items():
            if sha256_bytes(file_bytes[f"pipeline/{name}"]) != digest:
                raise SnapshotError(f"处理代码快照哈希不同：{name}")
        pdf_path = _file_inside(project_root, paper["local_path"])
        if sha256_bytes(pdf_path.read_bytes()) != paper["pdf_sha256"]:
            raise SnapshotError("原 PDF 与版本清单的固定来源不同")

        raw_pages = _read_jsonl(file_bytes["raw.pages.jsonl"], "原始页快照")
        filtered_pages = _read_jsonl(file_bytes["filtered.pages.jsonl"], "过滤页快照")
        rules = json.loads(file_bytes["quality_rules.json"].decode("utf-8-sig"))
        if rules["rules_revision"] != recipe["rules_revision"]:
            raise SnapshotError("质量规则快照与处理配置版本不同")
        page_count = paper["page_count"]
        if type(page_count) is not int or page_count <= 0:
            raise SnapshotError("页数必须是正整数")
        expected_pages = list(range(1, page_count + 1))
        for rows in (raw_pages, filtered_pages):
            if [row["pdf_page"] for row in rows] != expected_pages:
                raise SnapshotError("页快照不完整或页序不同")
            for row in rows:
                if (
                    type(row["pdf_page"]) is not int or row["paper_id"] != paper_id
                    or row["pdf_sha256"] != paper["pdf_sha256"]
                ):
                    raise SnapshotError("页快照来源不同")
        for raw, filtered in zip(raw_pages, filtered_pages):
            if not isinstance(raw.get("text"), str):
                raise SnapshotError("原始页快照 text 必须是字符串")
            if filtered["source_raw_text_sha256"] != sha256_bytes(raw["text"].encode("utf-8")):
                raise SnapshotError("过滤页引用了其他原始文本")
            if filtered["filter_revision"] != recipe["filter_revision"]:
                raise SnapshotError("过滤页与处理配置版本不同")
            if filtered["rules_revision"] != recipe["rules_revision"]:
                raise SnapshotError("过滤页与质量规则版本不同")

        segments_list = list(iter_indexable_segments(filtered_pages))
        segments = {segment["segment_id"]: segment for segment in segments_list}
        if len(segments) != len(segments_list):
            raise SnapshotError("父片段 ID 重复")
        chunks = _read_jsonl(file_bytes["chunks.jsonl"], "分块快照")
        by_segment = defaultdict(list)
        seen_ids = set()
        page_counts = Counter()
        config = recipe["chunking"]
        if (
            type(config["max_chars"]) is not int or config["max_chars"] <= 0
            or type(config["overlap_chars"]) is not int
            or not 0 <= config["overlap_chars"] < config["max_chars"]
        ):
            raise SnapshotError("快照分块配置无效")
        for chunk in chunks:
            source = segments[chunk["segment_id"]]
            start, end = chunk["char_start"], chunk["char_end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]):
                raise SnapshotError("chunk 来源区间无效")
            if chunk["text"] != source["text"][start:end]:
                raise SnapshotError("chunk 不等于父片段的准确原文切片")
            if chunk["text_sha256"] != sha256_bytes(chunk["text"].encode("utf-8")):
                raise SnapshotError("chunk 文本哈希不同")
            if len(chunk["text"]) > config["max_chars"]:
                raise SnapshotError("chunk 超过记录的字符上限")
            fields = ("paper_id", "pdf_sha256", "pdf_page", "filter_revision", "source_block_index", "source_line_indices")
            if any(chunk[key] != source[key] for key in fields) or chunk["segment_bbox"] != source["bbox"]:
                raise SnapshotError("chunk 与父片段的来源字段不同")
            page_counts[chunk["pdf_page"]] += 1
            expected_id = f"{paper_id}_{parse_revision}_p{chunk['pdf_page']}_c{page_counts[chunk['pdf_page']]}"
            if chunk["chunk_id"] != expected_id or chunk["chunk_id"] in seen_ids or chunk["parse_revision"] != parse_revision:
                raise SnapshotError("chunk ID、顺序或处理版本不同")
            seen_ids.add(chunk["chunk_id"])
            by_segment[chunk["segment_id"]].append(chunk)
        if set(by_segment) != set(segments):
            raise SnapshotError("不是所有保留父片段都已分块")
        for segment_id, group in by_segment.items():
            if group[0]["char_start"] != 0 or group[-1]["char_end"] != len(segments[segment_id]["text"]):
                raise SnapshotError("父片段开头或结尾缺失")
            rebuilt = group[0]["text"]
            for previous, current in zip(group, group[1:]):
                overlap = previous["char_end"] - current["char_start"]
                if overlap != config["overlap_chars"] or current["char_start"] <= previous["char_start"]:
                    raise SnapshotError("分块覆盖或重叠不符合记录配置")
                rebuilt += current["text"][overlap:]
            if rebuilt != segments[segment_id]["text"]:
                raise SnapshotError("分块不能完整还原父片段")
        actual_statistics = {
            "page_count": page_count, "segment_count": len(segments), "chunk_count": len(chunks),
            "split_segment_count": sum(len(group) > 1 for group in by_segment.values()),
            "max_chunk_chars": max(len(chunk["text"]) for chunk in chunks),
            "chunks_per_page": {str(page): page_counts[page] for page in expected_pages},
        }
        if manifest["statistics"] != actual_statistics:
            raise SnapshotError("分块统计与实际内容不同")
    except (KeyError, TypeError, UnicodeError, ValueError) as error:
        if isinstance(error, SnapshotError):
            raise
        raise SnapshotError(f"快照结构或来源核对失败：{error}") from error

    return StoredVersionInput(
        paper=paper, manifest=manifest, chunks=chunks,
        snapshot_path=folder.relative_to(project_root).as_posix(),
        manifest_sha256=sha256_bytes(manifest_bytes),
    )
