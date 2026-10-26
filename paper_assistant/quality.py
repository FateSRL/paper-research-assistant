"""D3：按来源坐标隔离不可靠文本，生成可供后续分块使用的派生记录。

原始 data/parsed 不修改。坐标仍对应固定版本 PDF。
过滤单位是“行”；只要行内有乱码/受限区域，就保留排除记录，
不通过删几个字符把损坏的句子伪装成完整正文。
"""

import hashlib
import re
from pathlib import Path

import pymupdf


FILTER_REVISION = "d3-quality-filter-v1"
MATH_FONT = re.compile(r"^CM(?:EX|MI|SY|R|BX|B|TI|TT|SS)\d", re.IGNORECASE)
MATH_SIGNAL_FONT = re.compile(r"^CM(?:EX|MI|SY)\d", re.IGNORECASE)
SUPPORTED_AUTOMATIC_RULES = {
    "reject_line_with_non_layout_c0": True,
    "reject_line_with_unicode_replacement": True,
    "reject_identity_h_font_with_no_actual_unicode_mapping": True,
    "reject_line_using_only_computer_modern_math_fonts": True,
}


class QualityError(ValueError):
    """来源或质量规则不一致，不能生成可信派生结果。"""


def count_bad_controls(text: str) -> int:
    """C0 中允许正常换行、回车和制表符，其余字符视为异常。"""
    return sum(ord(char) < 32 and char not in "\n\r\t" for char in text)


def _font_name(name: str) -> str:
    """PDF 子集字体名可能带 ABCDEF+ 前缀；去掉后与 span 字体名比较。"""
    return re.sub(r"^[A-Z]{6}\+", "", name).casefold()


def find_unmapped_fonts(document, page) -> dict[str, dict]:
    """识别 Identity-H 字体中没有实际 Unicode 映射的情况。

    标准 Type1 字体可以通过标准编码抽取，不能因为没有 ToUnicode 就拒绝。
    这里只针对本次发现的 Type0 + Identity-H 情形；
    有实际 bfchar/bfrange 条目或 usecmap 时，不在这里判为失效。
    """
    findings = {}
    for font in page.get_fonts(full=True):
        xref, _, font_type, base_name, _, encoding, *_ = font
        if font_type != "Type0" or encoding != "Identity-H":
            continue
        key_type, value = document.xref_get_key(xref, "ToUnicode")
        stream = b""
        if key_type == "xref":
            map_xref = int(value.split()[0])
            stream = document.xref_stream(map_xref) or b""
        counts = re.findall(rb"(\d+)\s+beginbf(?:char|range)", stream)
        has_mapping = any(int(count) > 0 for count in counts)
        if has_mapping or b"usecmap" in stream:
            continue
        findings[_font_name(base_name)] = {
            "font_xref": xref,
            "base_font": base_name,
            "reason": "identity_h_font_without_unicode_mapping",
        }
    return findings


def _overlaps(left: list, right: list) -> bool:
    """只有矩形实际相交才命中；仅接触边界不排除相邻正文。"""
    return (
        max(left[0], right[0]) < min(left[2], right[2])
        and max(left[1], right[1]) < min(left[3], right[3])
    )


def line_rejection_reasons(
    line: dict, unmapped_fonts: dict, region_rules: list[dict]
) -> list[str]:
    """合并一行中的所有质量原因，便于报告解释为什么被排除。"""
    spans = line["spans"]
    text = "".join(span["text"] for span in spans)
    reasons = []

    for rule in region_rules:
        if _overlaps(line["bbox"], rule["bbox"]):
            reasons.append(f"region:{rule['region_id']}:{rule['reason']}")

    if count_bad_controls(text):
        reasons.append("non_layout_c0_control_character")
    if "\ufffd" in text:
        reasons.append("unicode_replacement_character")
    if any(_font_name(span["font"]) in unmapped_fonts for span in spans):
        reasons.append("identity_h_font_without_unicode_mapping")

    # 独立公式常被拆成多个短行，普通文本中的 X/Y 也可能实际是数学符号。
    # 需要至少一个明确的数学字体信号（CMEX/CMMI/CMSY），其他 span
    # 可以是同族罗马字体的数字。CMR/CMBX 等本身也能用于正常正文，
    # 不能只因整句用了 CMR 就把它误判为公式。
    # 正文包含少量行内变量时仍保留；这不是完整的数学公式识别器。
    written_spans = [span for span in spans if span["text"].strip()]
    if (
        written_spans
        and any(MATH_SIGNAL_FONT.match(span["font"]) for span in written_spans)
        and all(MATH_FONT.match(span["font"]) for span in written_spans)
    ):
        reasons.append("math_font_only_line_requires_verified_math_extraction")

    return list(dict.fromkeys(reasons))


def _union_bbox(lines: list[tuple[int, dict]]) -> list[float]:
    boxes = [line["bbox"] for _, line in lines]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def filter_text_blocks(
    blocks: list[dict], unmapped_fonts: dict, region_rules: list[dict],
    paper_id: str, pdf_page: int,
) -> tuple[list[dict], list[dict]]:
    """返回可用片段与排除明细；不同块、被排除行两侧都保持边界。

    后续分块应读取 segments，而不是重新把原始页 text 全部拼回去。
    每个 segment 保留 block/line 索引和 bbox，方便引用回到原 PDF。
    """
    segments, excluded = [], []
    for block_index, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        pending = []

        def flush() -> None:
            if not pending:
                return
            text = "\n".join(
                "".join(span["text"] for span in line["spans"])
                for _, line in pending
            )
            if text.strip():
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                segments.append({
                    "segment_id": (
                        f"{paper_id}:p{pdf_page}:b{block_index}:"
                        f"l{pending[0][0]}-{pending[-1][0]}:{digest}"
                    ),
                    "source_block_index": block_index,
                    "source_line_indices": [index for index, _ in pending],
                    "bbox": _union_bbox(pending),
                    "text": text,
                    "indexable": True,
                })
            pending.clear()

        for line_index, line in enumerate(block.get("lines", [])):
            reasons = line_rejection_reasons(line, unmapped_fonts, region_rules)
            if reasons:
                # 先结束前面的片段，避免损坏区域两侧形成伪造的连续句子。
                flush()
                excluded.append({
                    "source_block_index": block_index,
                    "source_line_index": line_index,
                    "bbox": list(line["bbox"]),
                    "text": "".join(span["text"] for span in line["spans"]),
                    "fonts": sorted({span["font"] for span in line["spans"]}),
                    "reasons": reasons,
                    "indexable": False,
                })
            else:
                pending.append((line_index, line))
        flush()
    return segments, excluded


def filter_paper_pages(
    paper: dict, raw_pages: list[dict], project_root: Path, rules: dict
) -> list[dict]:
    """核对固定来源后筛查整篇；生成独立派生页，不重编号、不改原始记录。"""
    source_path = project_root / paper["local_path"]
    actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_hash != paper["pdf_sha256"]:
        raise QualityError("PDF 与语料清单的哈希不同")
    if rules.get("rules_revision") != "d3-quality-rules-v1":
        raise QualityError("不支持的质量规则版本")
    if rules.get("automatic_rules") != SUPPORTED_AUTOMATIC_RULES:
        raise QualityError("自动规则配置与当前实现不一致，不能静默忽略修改")
    if [row["pdf_page"] for row in raw_pages] != list(range(1, paper["page_count"] + 1)):
        raise QualityError("原始页记录不完整或页序错误")
    for row in raw_pages:
        if row["paper_id"] != paper["paper_id"] or row["pdf_sha256"] != actual_hash:
            raise QualityError("原始页记录的论文 ID 或哈希不同")

    applicable_rules = [
        rule for rule in rules["region_rules"] if rule["paper_id"] == paper["paper_id"]
    ]
    for rule in applicable_rules:
        if rule["pdf_sha256"] != actual_hash:
            raise QualityError("区域规则对应其他 PDF，拒绝套用旧坐标")
        if not (1 <= rule["pdf_page"] <= paper["page_count"]):
            raise QualityError("区域规则页序超出范围")
        box = rule["bbox"]
        if len(box) != 4 or not (box[0] < box[2] and box[1] < box[3]):
            raise QualityError("区域规则矩形无效")

    outputs = []
    with pymupdf.open(str(source_path)) as document:
        if document.page_count != paper["page_count"]:
            raise QualityError("实际 PDF 页数与清单不同")
        for raw in raw_pages:
            page = document[raw["pdf_page"] - 1]
            # 过滤使用 PDF 的坐标信息。如果保存的原始文本来自另一次解析，
            # 不能悄悄混用不同版本的 text 和坐标，应先重新核对来源。
            if raw["text"] != page.get_text("text"):
                raise QualityError(f"第 {raw['pdf_page']} 页原始文本与当前提取不一致")
            unmapped = find_unmapped_fonts(document, page)
            selected = [
                rule for rule in applicable_rules if rule["pdf_page"] == raw["pdf_page"]
            ]
            segments, excluded = filter_text_blocks(
                page.get_text("dict")["blocks"], unmapped, selected,
                raw["paper_id"], raw["pdf_page"],
            )
            for segment in segments:
                segment.update({
                    "paper_id": raw["paper_id"],
                    "pdf_sha256": actual_hash,
                    "pdf_page": raw["pdf_page"],
                    "filter_revision": FILTER_REVISION,
                })
            text = "\n\n".join(segment["text"] for segment in segments)
            if count_bad_controls(text) or "\ufffd" in text:
                raise QualityError("过滤后仍有异常字符，拒绝发布为可用输入")
            outputs.append({
                "paper_id": raw["paper_id"],
                "pdf_sha256": actual_hash,
                "pdf_page": raw["pdf_page"],
                "filter_revision": FILTER_REVISION,
                "rules_revision": rules["rules_revision"],
                "source_raw_text_sha256": hashlib.sha256(
                    raw["text"].encode("utf-8")
                ).hexdigest(),
                "coordinate_system": "PDF points, top-left origin",
                "text": text,
                "segments": segments,
                "excluded_lines": excluded,
                "quality_filtered": True,
                "indexable": bool(segments),
                "quality_scope": "automatic_screening_plus_exact_hash_region_rules",
                "human_verified": False,
            })
    return outputs


def iter_indexable_segments(filtered_pages: list[dict]):
    """后续分块入口：只接受本过滤器的派生记录，拒绝误传原始 parsed 页。"""
    for page in filtered_pages:
        if (
            page.get("filter_revision") != FILTER_REVISION
            or page.get("quality_filtered") is not True
        ):
            raise QualityError("请先运行质量过滤；不能直接将原始页送入此入口")
        if not page.get("indexable"):
            continue
        for segment in page["segments"]:
            if segment.get("indexable") is not True:
                continue
            if (
                segment.get("paper_id") != page["paper_id"]
                or segment.get("pdf_sha256") != page["pdf_sha256"]
                or segment.get("pdf_page") != page["pdf_page"]
                or segment.get("filter_revision") != FILTER_REVISION
                or count_bad_controls(segment["text"])
                or "\ufffd" in segment["text"]
            ):
                raise QualityError("片段来源或字符检查失败")
            yield segment

