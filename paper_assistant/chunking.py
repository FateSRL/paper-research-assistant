"""D4 任务 B：把质量过滤后的片段切成可回查、可复现的 chunks。

分块是本地文本处理，不需要 embedding 或聊天模型。这里分成三层：
split_text_ranges 只算字符区间；build_chunks 把区间与来源组合；
prepare_chunk_version / save_chunk_version 核对输入并保存不可变版本。
导入模块不会读取 .env、发起网络请求或者自动生成文件。
"""

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import version
import json
from math import isfinite
from pathlib import Path
import platform
import re
import tempfile

from paper_assistant.quality import FILTER_REVISION, filter_paper_pages, iter_indexable_segments
from paper_assistant.schemas import EvidenceRef


CHUNKER_REVISION = "d4-segment-character-window-v1"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ChunkingError(ValueError):
    """输入来源、配置或已有版本不一致，不能安全发布分块结果。"""


@dataclass(frozen=True)
class ChunkingConfig:
    """按 Python 字符串中的字符计量；这两个数字都不是 token 数。

    frozen=True 防止处理中途修改配置，导致同一批 chunk 使用不同参数。
    例如 max_chars=1600、overlap_chars=200，表示一块最长 1600 字符，
    前后两块共用前块最后 200 个字符；短片段不需要分割或补齐。
    """

    max_chars: int = 1600
    overlap_chars: int = 200

    def __post_init__(self) -> None:
        # bool 是 int 的子类，但 True 不是这里想接受的长度配置。
        if type(self.max_chars) is not int or self.max_chars <= 0:
            raise ChunkingError("max_chars 必须是正整数")
        if type(self.overlap_chars) is not int or not 0 <= self.overlap_chars < self.max_chars:
            raise ChunkingError("overlap_chars 必须是整数，且 0 <= overlap_chars < max_chars")


@dataclass(frozen=True)
class PreparedChunkVersion:
    """已经通过来源核对的结果；files 保存待写入的准确字节。"""

    paper_id: str
    parse_revision: str
    output_dir: Path
    manifest: dict
    chunks: list[dict]
    files: dict[str, bytes]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """字典键排序、固定分隔符，使相同内容的身份不受键的排列顺序影响。"""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _jsonl_records(value: bytes, description: str) -> list[dict]:
    try:
        records = [json.loads(line) for line in value.decode("utf-8-sig").splitlines() if line.strip()]
    except (UnicodeError, ValueError) as error:
        raise ChunkingError(f"{description} 不是有效 UTF-8 JSONL") from error
    if not records or any(not isinstance(row, dict) for row in records):
        raise ChunkingError(f"{description} 必须包含非空对象记录")
    return records


def _validate_paper(paper: dict) -> None:
    if not isinstance(paper, dict):
        raise ChunkingError("paper 必须是论文清单中的对象")
    paper_id = paper.get("paper_id")
    if not isinstance(paper_id, str) or not SAFE_ID.fullmatch(paper_id):
        raise ChunkingError("paper_id 必须是非空安全标识符")
    digest = paper.get("pdf_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ChunkingError("pdf_sha256 必须是完整小写 SHA-256")
    if type(paper.get("page_count")) is not int or paper["page_count"] <= 0:
        raise ChunkingError("page_count 必须是正整数")


def split_text_ranges(text: str, config: ChunkingConfig) -> list[tuple[int, int]]:
    """返回不丢字的 [start, end) 区间，不修改传入的字符串。

    end 是切片右侧的边界，不包含在当前片段内。例如 (0, 5) 对应
    text[0:5]。最后一块必须到达 len(text)，相邻块之间只能重叠，
    不能有间隙；这样逐字符核对时，不会把换行或空格悄悄丢掉。
    """
    if not isinstance(text, str) or not text.strip():
        raise ChunkingError("待切分文本必须是非空字符串")
    if not isinstance(config, ChunkingConfig):
        raise ChunkingError("config 必须是 ChunkingConfig")

    ranges = []
    start = 0
    while start < len(text):
        end = min(start + config.max_chars, len(text))
        if end < len(text):
            # 在窗口后半段寻找边界，避免遇到早期换行就切出很短的块。
            # cut > overlap 保证下一块的 start 严格增加，不会无限循环。
            minimum_end = start + max(config.max_chars // 2, config.overlap_chars + 1)
            newline = text.rfind("\n", minimum_end - 1, end)
            if newline >= 0:
                end = newline + 1  # 把换行也留在原文切片中。
            else:
                for index in range(end - 1, minimum_end - 2, -1):
                    if text[index].isspace():
                        end = index + 1
                        break
            # 找不到词间边界（例如一长串连续字符）时，保留硬字符上限。

        ranges.append((start, end))
        if end == len(text):
            break
        start = end - config.overlap_chars
    return ranges


def build_chunks(
    filtered_pages: list[dict], paper: dict, parse_revision: str, config: ChunkingConfig,
    *, segment_boundaries: dict[str, list[int]] | None = None,
) -> list[dict]:
    """从单篇完整派生页生成 chunks，不负责写文件或调用 API。

    本函数只能读取 iter_indexable_segments 认可的片段。循环在一个
    segment 内完成后，才进入下一个 segment，任何重叠都不会跨越
    D3 隔离出的坏行、被排除的公式或者页面边界。
    """
    _validate_paper(paper)
    if not isinstance(parse_revision, str) or not SAFE_ID.fullmatch(parse_revision):
        raise ChunkingError("parse_revision 必须是非空安全标识符")
    if not isinstance(config, ChunkingConfig):
        raise ChunkingError("config 必须是 ChunkingConfig")
    if not isinstance(filtered_pages, list) or not filtered_pages:
        raise ChunkingError("必须提供完整的过滤后页列表")
    if any(not isinstance(page, dict) for page in filtered_pages):
        raise ChunkingError("页记录必须是对象")
    if (
        [page.get("pdf_page") for page in filtered_pages] != list(range(1, paper["page_count"] + 1))
        or any(type(page.get("pdf_page")) is not int for page in filtered_pages)
    ):
        raise ChunkingError("派生页必须完整，页序从 1 开始且不可重复")
    for page in filtered_pages:
        if page.get("paper_id") != paper["paper_id"] or page.get("pdf_sha256") != paper["pdf_sha256"]:
            raise ChunkingError("派生页与指定论文的 ID 或 PDF 哈希不一致")
        if not isinstance(page.get("segments"), list):
            raise ChunkingError("必须读取过滤后的 segments，不能传入原始 parsed 页")
        if type(page.get("indexable")) is not bool or page["indexable"] != bool(page["segments"]):
            raise ChunkingError("页 indexable 与保留片段数量不一致")

    try:
        segments = list(iter_indexable_segments(filtered_pages))
    except (ValueError, KeyError, TypeError) as error:
        raise ChunkingError(f"过滤片段入口拒绝输入：{error}") from error

    chunks = []
    seen_segments = set()
    page_chunk_counts = Counter()
    for segment in segments:
        segment_id = segment.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip() or segment_id in seen_segments:
            raise ChunkingError("segment_id 必须非空且在本篇论文中唯一")
        seen_segments.add(segment_id)
        block_index = segment.get("source_block_index")
        lines = segment.get("source_line_indices")
        box = segment.get("bbox")
        if type(block_index) is not int or block_index < 0:
            raise ChunkingError("父片段 block 索引无效")
        if (
            not isinstance(lines, list) or not lines
            or any(type(index) is not int or index < 0 for index in lines)
            or lines != list(range(lines[0], lines[-1] + 1))
        ):
            raise ChunkingError("父片段 line 索引必须是连续非负整数")
        if (
            not isinstance(box, list) or len(box) != 4
            or any(type(value) not in (int, float) or not isfinite(value) for value in box)
            or not (box[0] < box[2] and box[1] < box[3])
        ):
            raise ChunkingError("父片段 bbox 必须是有效区域")

        cuts = (segment_boundaries or {}).get(segment_id)
        if cuts:
            segment_text = segment.get("text")
            boundaries = sorted({0, len(segment_text), *cuts})
            ranges = []
            for left, right in zip(boundaries, boundaries[1:]):
                if not segment_text[left:right].strip():
                    continue
                ranges.extend((left + start, left + end)
                              for start, end in split_text_ranges(segment_text[left:right], config))
        else:
            ranges = split_text_ranges(segment.get("text"), config)
        for start, end in ranges:
            page = segment["pdf_page"]
            page_chunk_counts[page] += 1
            text = segment["text"][start:end]
            chunk = {
                "chunk_id": f"{paper['paper_id']}_{parse_revision}_p{page}_c{page_chunk_counts[page]}",
                "paper_id": paper["paper_id"],
                "parse_revision": parse_revision,
                "pdf_sha256": paper["pdf_sha256"],
                "pdf_page": page,
                "segment_id": segment_id,
                "char_start": start,
                "char_end": end,
                "text": text,
                "text_sha256": sha256_bytes(text.encode("utf-8")),
                "filter_revision": segment["filter_revision"],
                "source_block_index": block_index,
                "source_line_indices": list(lines),
                "segment_bbox": list(box),
            }
            # 复用已有引用位置结构，保证 D5 不需要再换一套定位字段。
            EvidenceRef.model_validate({key: chunk[key] for key in (
                "chunk_id", "paper_id", "parse_revision", "pdf_page",
            )})
            chunks.append(chunk)
    if not chunks:
        raise ChunkingError("本篇没有可用于分块的保留片段")
    return chunks


def _input_path(project_root: Path, relative: str) -> Path:
    """解析清单相对路径，并拒绝意外读到另一个项目或目录外的文件。"""
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ChunkingError("输入路径必须相对项目根目录")
    path = (project_root / relative).resolve()
    if not path.is_relative_to(project_root):
        raise ChunkingError("输入路径超出项目目录")
    if not path.is_file():
        raise ChunkingError(f"输入文件不存在：{path}")
    return path


def prepare_chunk_version(
    paper: dict, project_root: Path, config: ChunkingConfig,
) -> PreparedChunkVersion:
    """核对固定来源，在内存中准备完整不可变快照；尚不写入文件。

    处理版本由输入和处理规则共同决定，不是每次运行都把 r1 加成 r2。
    相同输入和规则得到相同指纹；改变分块长度、过滤规则或解析输入，
    则自然得到另一个版本。完整指纹可检测短版本名的意外碰撞。
    """
    _validate_paper(paper)
    project_root = project_root.resolve()
    paper_id = paper["paper_id"]
    source_paths = {
        "pdf": _input_path(project_root, paper.get("local_path")),
        "raw": _input_path(project_root, f"data/parsed/{paper_id}.jsonl"),
        "filtered": _input_path(project_root, f"data/filtered/{paper_id}.jsonl"),
        "rules": _input_path(project_root, "eval/quality_rules.json"),
    }
    # 一次读入准确字节，既用于身份计算，也用于保存同一份输入快照。
    source_bytes = {key: path.read_bytes() for key, path in source_paths.items()}
    if sha256_bytes(source_bytes["pdf"]) != paper["pdf_sha256"]:
        raise ChunkingError("实际 PDF 与清单的 SHA-256 不同")
    raw_pages = _jsonl_records(source_bytes["raw"], "原始解析")
    filtered_pages = _jsonl_records(source_bytes["filtered"], "过滤后页记录")
    try:
        rules = json.loads(source_bytes["rules"].decode("utf-8-sig"))
        # 只读重算过滤结果，确认正文、排除边界与当前固定 PDF/规则一致。
        # 不保存重算结果，不改 D3 文件；避免给修改过的文本套上旧来源。
        expected_filtered = filter_paper_pages(paper, raw_pages, project_root, rules)
    except (ValueError, KeyError, TypeError) as error:
        raise ChunkingError(f"PDF/原始解析/质量规则核对失败：{error}") from error
    if expected_filtered != filtered_pages:
        raise ChunkingError("过滤结果与固定 PDF/质量规则不一致，请先检查 D3 输入")

    processing_paths = {
        "ingest.py": _input_path(project_root, "paper_assistant/ingest.py"),
        "quality.py": _input_path(project_root, "paper_assistant/quality.py"),
        "chunking.py": _input_path(project_root, "paper_assistant/chunking.py"),
    }
    processing_bytes = {name: path.read_bytes() for name, path in processing_paths.items()}
    paper_snapshot = pretty_json_bytes(paper)
    recipe = {
        "paper_id": paper_id,
        "pdf_sha256": paper["pdf_sha256"],
        "paper_metadata_sha256": sha256_bytes(paper_snapshot),
        "raw_jsonl_sha256": sha256_bytes(source_bytes["raw"]),
        "filtered_jsonl_sha256": sha256_bytes(source_bytes["filtered"]),
        "quality_rules_sha256": sha256_bytes(source_bytes["rules"]),
        "python_version": platform.python_version(),
        "parser": {"name": "PyMuPDF", "version": version("pymupdf"), "extraction": "page.get_text('text')"},
        "filter_revision": FILTER_REVISION,
        "rules_revision": rules["rules_revision"],
        "chunker_revision": CHUNKER_REVISION,
        "processing_source_sha256": {name: sha256_bytes(value) for name, value in processing_bytes.items()},
        "chunking": asdict(config),
        "length_unit": "Python Unicode code points; not embedding tokens",
        "boundary_policy": "within_single_segment; prefer_tail_newline_then_whitespace",
        "text_preprocessing": "none; exact source slice",
        "chunk_id_format": "{paper_id}_{parse_revision}_p{pdf_page}_c{one_based_page_chunk_index}",
    }
    fingerprint = sha256_bytes(canonical_json_bytes(recipe))
    parse_revision = "r_" + fingerprint[:16]
    chunks = build_chunks(filtered_pages, paper, parse_revision, config)
    output_base = (project_root / "data/chunks").resolve()
    if not output_base.is_relative_to(project_root):
        raise ChunkingError("分块输出目录超出项目，拒绝写入")
    output_dir = (output_base / paper_id / parse_revision).resolve()
    if not output_dir.is_relative_to(output_base):
        raise ChunkingError("分块版本路径超出 data/chunks")

    files = {
        "chunks.jsonl": b"".join(
            (json.dumps(chunk, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            for chunk in chunks
        ),
        "raw.pages.jsonl": source_bytes["raw"],
        "filtered.pages.jsonl": source_bytes["filtered"],
        "quality_rules.json": source_bytes["rules"],
        "paper.json": paper_snapshot,
        **{f"pipeline/{name}": value for name, value in processing_bytes.items()},
    }
    segment_counts = Counter(chunk["segment_id"] for chunk in chunks)
    page_counts = Counter(chunk["pdf_page"] for chunk in chunks)
    manifest = {
        "schema_revision": "d4-chunk-version-v1",
        "paper_id": paper_id,
        "parse_revision": parse_revision,
        "recipe_sha256": fingerprint,
        "recipe": recipe,
        "source_paths": {key: path.relative_to(project_root).as_posix() for key, path in source_paths.items()},
        "statistics": {
            "page_count": len(filtered_pages),
            "segment_count": len(segment_counts),
            "chunk_count": len(chunks),
            "split_segment_count": sum(count > 1 for count in segment_counts.values()),
            "max_chunk_chars": max(len(chunk["text"]) for chunk in chunks),
            "chunks_per_page": {str(page): page_counts[page] for page in range(1, paper["page_count"] + 1)},
        },
        "files": {name: {"sha256": sha256_bytes(value), "bytes": len(value)} for name, value in files.items()},
        "source_scope": "D3 indexable segments only; recovered figure/math not included",
        "human_review_status": "pending",
        "segment_bbox_scope": "parent segment region; not an exact chunk rectangle",
        "index_status": "chunks_only; SQLite and vector import not yet performed",
    }
    # 时间戳只适合运行报告，不进入不可变清单；二次运行可逐字节核对。
    files["version_manifest.json"] = pretty_json_bytes(manifest)
    return PreparedChunkVersion(paper_id, parse_revision, output_dir, manifest, chunks, files)


def save_chunk_version(prepared: PreparedChunkVersion) -> bool:
    """完整发布版本，返回 True 表示复用，False 表示首次创建。

    已存在的版本必须逐文件、逐字节相同；缺失或被修改都报错，不能
    默默修补旧版本。首次写到同级暂存目录，所有文件完成后才重命名
    成正式版本目录，减少中断时留下半份正式产物的可能。
    """
    target = prepared.output_dir.resolve()
    # output_dir 来自 prepare，但保存入口仍检查最终绝对路径和标识。
    if target.name != prepared.parse_revision or target.parent.name != prepared.paper_id:
        raise ChunkingError("目标目录与论文或版本标识不一致")
    if target.parent.parent.name != "chunks" or target.parent.parent.parent.name != "data":
        raise ChunkingError("只允许保存到 data/chunks/<paper_id>/<parse_revision>")

    def check_existing() -> None:
        if not target.is_dir():
            raise ChunkingError("版本目标不是目录")
        for relative, expected_bytes in prepared.files.items():
            path = (target / relative).resolve()
            if not path.is_relative_to(target) or not path.is_file() or path.read_bytes() != expected_bytes:
                raise ChunkingError(f"已有版本文件缺失或内容变化，拒绝覆盖：{relative}")

    if target.exists():
        check_existing()
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{prepared.parse_revision}.pending-", dir=target.parent)).resolve()
    if not staging.is_relative_to(target.parent):
        raise ChunkingError("暂存路径不在预期输出目录内")
    try:
        for relative, value in prepared.files.items():
            path = (staging / relative).resolve()
            if not path.is_relative_to(staging):
                raise ChunkingError("快照文件路径超出暂存目录")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(value)
        # 两个绝对路径都已确认在同一个论文输出目录中，不覆盖正式文件。
        if target.exists():
            raise ChunkingError("另一个进程已经创建该版本，请核对后重试")
        staging.rename(target)
    except Exception as error:
        # 失败时保留暂存材料方便排查；正式目录尚未发布，不假装成功。
        raise ChunkingError(f"发布版本失败；暂存位置 {staging}：{error}") from error
    return False
