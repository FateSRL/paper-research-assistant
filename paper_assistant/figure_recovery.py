"""恢复固定 ReAct PDF 页 2 的 Figure 1；结果单独保存，不替换逐页正文。

此图的嵌入字体没有 Unicode cmap，不能对乱码统一加一个数字来“修复”。
这里将实际字形轮廓与本机 Courier New 的轮廓匹配，再查其真正的 cmap。
这是一份绑定 PDF/字体哈希、图区域和英语字符库存的局部恢复配置。
"""

from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pymupdf
import fontTools
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont


PAPER_ID = "arxiv_2210.03629v3"
PDF_SHA256 = "f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69"
PDF_PAGE = 2
FIGURE_BBOX = (112.0, 84.0, 505.0, 403.0)
FIGURE_FONT = "font0000000028ee1bae"
SOURCE_METHOD = "embedded_glyph_outline_match_to_verified_local_font_cmap"

# 所有字体来源都固定且有哈希；缺失或版本变化时明确报错，不默默换字体。
# flags 4 是等宽普通字体，20 是等宽粗体。它们只在这份固定 PDF 中用于
# 分配文字字体；后面的每个实际 glyph 仍须通过轮廓和字宽校验。
FONT_PROFILES = (
    {
        "xref": 193,
        "flags": 20,
        "embedded_sha256": "ebd40765f8e1b575732aec490929909a701f032a58805bfced40aab716143fcd",
        "source_path": "C:/Windows/Fonts/courbd.ttf",
        "source_sha256": "11e629cef937cd08f942aa1bd994a71302dbe2819c72c6d4c183a623acbb421a",
    },
    {
        "xref": 194,
        "flags": 4,
        "embedded_sha256": "1ccc1f6b39b40a320c2c41464c5fecf4229633c375473040354e57fcec3ab6db",
        "source_path": "C:/Windows/Fonts/cour.ttf",
        "source_sha256": "e4a66a0259718d0c8f4b6e14319b4803ced45afbddf3abba8b8c3e2006856206",
    },
)
GRAPHIC_FONT_XREF = 195
GRAPHIC_FONT_SHA256 = "f0d89337dcba1b3f589ac8713098c9b5859502ab1381cc38ca00c3f56b82913f"

# 这些分区来自完整原图的 AI 视觉对照。坐标是 PDF 点，原点在页左上角。
# 各 panel 独立按行排列，避免把左右两个不同 agent 的轨迹合成一段。
PANEL_PROFILES = (
    ("1_question", "(1) Hotspot QA — question", (112, 84, 307, 122)),
    ("1a_standard", "(1a) Standard", (112, 125, 202, 150)),
    ("1b_cot", "(1b) CoT (Reason Only)", (112, 153, 202, 248)),
    ("1c_act_only", "(1c) Act-Only", (203, 125, 307, 248)),
    ("1d_react", "(1d) ReAct (Reason + Act)", (310, 84, 505, 248)),
    ("2_environment", "(2) AlfWorld — environment and task", (112, 255, 307, 296)),
    ("2a_act_only", "(2a) Act-Only", (112, 297, 307, 403)),
    ("2b_react", "(2b) ReAct (Reason + Act)", (310, 255, 505, 403)),
)

# 完整原图是英语，使用可见 ASCII 和省略号。这个限制必须显式记录：
# 单靠轮廓无法区分 Latin A 与外形一样的 Greek/Cyrillic 字母，也无法
# 证明原始空格是不是 NBSP。全 Unicode 候选仍保留，不能声称恢复原编码。
REVIEWED_CODEPOINTS = frozenset(range(32, 127)) | {0x2026}


class FigureRecoveryError(ValueError):
    """源文件/依赖不符合固定配置，不能继续可靠恢复。"""


def file_sha256(path: Path) -> str:
    """计算文件内容哈希，用于绑定来源和检查原文件没有被改写。"""
    return sha256(path.read_bytes()).hexdigest()


def _outline(font: TTFont, glyph_name: str) -> tuple:
    """记录字形的实际轮廓，忽略只影响栅格显示的 hint 指令。

    DecomposingRecordingPen 会展开复合字形，再记录线段/二次曲线和点。
    比较这些记录可以发现相同形状；这比比较 glyph 数字或字体名字可靠。
    它不改点坐标，不做模糊匹配；只接受完全一致的轮廓。
    """
    glyph_set = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return tuple(pen.value)


def _build_mapping(doc, profile: dict, glyph_ids: set[int]) -> tuple[dict, dict]:
    """为本页真正用到的 glyph 建立可审计映射；未知/歧义项不猜测。

    先校验嵌入字体和本机字体哈希，再用本机字体真实 Unicode cmap 构建
    “轮廓 → Unicode 候选”。在已视觉核对的英语字符库存内恰好只有一个
    候选，且轮廓、unitsPerEm、字宽/左边距一致时，才接受一个字符。
    空轮廓也必须按同样规则验证，所以不会把任何空字形都当成空格。
    """
    embedded_data = doc.extract_font(profile["xref"])[3]
    embedded_hash = sha256(embedded_data).hexdigest()
    if embedded_hash != profile["embedded_sha256"]:
        raise FigureRecoveryError(f"嵌入字体 {profile['xref']} 的哈希与配置不符")
    source_path = Path(profile["source_path"])
    if not source_path.is_file():
        raise FigureRecoveryError(f"恢复依赖字体不存在：{source_path}")
    source_data = source_path.read_bytes()
    if sha256(source_data).hexdigest() != profile["source_sha256"]:
        raise FigureRecoveryError(f"恢复依赖字体版本/哈希变化：{source_path}")

    with TTFont(BytesIO(embedded_data)) as embedded, TTFont(BytesIO(source_data)) as source:
        if embedded["head"].unitsPerEm != source["head"].unitsPerEm:
            raise FigureRecoveryError("字体坐标尺度不一致，不能直接比较轮廓")
        cmap = source.getBestCmap()
        if not cmap:
            raise FigureRecoveryError("本机来源字体没有可用的 Unicode cmap")

        # 相同轮廓可能来自不同语言的同形字。保留全部候选，而不是取第一项。
        by_outline = defaultdict(list)
        outline_cache = {}
        for codepoint, glyph_name in cmap.items():
            if glyph_name not in outline_cache:
                outline_cache[glyph_name] = _outline(source, glyph_name)
            by_outline[outline_cache[glyph_name]].append((codepoint, glyph_name))

        glyph_order = embedded.getGlyphOrder()
        mappings = {}
        for glyph_id in sorted(glyph_ids):
            item = {"glyph_id": glyph_id, "status": "unmapped", "text": None}
            if glyph_id >= len(glyph_order) or glyph_id < 0:
                mappings[glyph_id] = item
                continue
            embedded_name = glyph_order[glyph_id]
            signature = _outline(embedded, embedded_name)
            candidates = by_outline[signature]
            item["all_unicode_candidates"] = sorted(cp for cp, _ in candidates)
            item["empty_outline"] = not signature
            allowed = [(cp, name) for cp, name in candidates if cp in REVIEWED_CODEPOINTS]
            item["inventory_candidates"] = [cp for cp, _ in allowed]
            if len(allowed) != 1:
                item["status"] = "ambiguous" if allowed else "unmapped"
            else:
                cp, source_name = allowed[0]
                # 字宽/边距进一步约束空格及其他轮廓候选，不能只检查形状。
                metric_match = embedded["hmtx"][embedded_name] == source["hmtx"][source_name]
                item.update({
                    "outline_sha256": sha256(repr(signature).encode()).hexdigest(),
                    "source_glyph_name": source_name,
                    "metric_match": metric_match,
                    "unicode_codepoint": cp,
                })
                if metric_match:
                    item["status"] = "matched_in_reviewed_inventory"
                    item["text"] = chr(cp)
                else:
                    item["status"] = "metric_mismatch"
            mappings[glyph_id] = item

        manifest = {
            **profile,
            "embedded_hash_verified": True,
            "source_hash_verified": True,
            "embedded_has_unicode_cmap": "cmap" in embedded and bool(embedded.getBestCmap()),
            "source_has_unicode_cmap": True,
            "units_per_em": embedded["head"].unitsPerEm,
            "glyph_mapping": list(mappings.values()),
        }
    return mappings, manifest


def _panel_for_bbox(bbox) -> str | None:
    """用中心点分配图分区；落在配置外的内容会被隔离。"""
    x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    hits = [pid for pid, _, rect in PANEL_PROFILES if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]]
    return hits[0] if len(hits) == 1 else None


def _lines_for_panel(spans: list[dict]) -> list[dict]:
    """在单独 panel 中按基线排序，把碎片组合成便于对照的行。

    PDF 的绘制顺序不等于阅读顺序：该图首先绘制了右下角的一部分。
    这里保留原始 spans/每字符坐标，再在一个 panel 内按 y、x 排列。
    不拼接不同 panel。样式切换造成明显位置空隙时只补一个显示用空格，
    同时记下补空格数量；不补词、不改动作编号，也不把省略步骤补回来。
    """
    groups = []
    for span in sorted(spans, key=lambda s: (s["baseline_y"], s["bbox"][0])):
        if not groups or abs(span["baseline_y"] - groups[-1][0]["baseline_y"]) > 0.7:
            groups.append([])
        groups[-1].append(span)
    lines = []
    for group in groups:
        chars = sorted((c for span in group for c in span["chars"]), key=lambda c: c["origin"][0])
        # 原图少数文本对象在最后一个字母的坐标上额外绘制了空格 glyph。
        # 空格没有可见轮廓；若照绘制对象排列，会把 device 变成 devic e。
        # 只在预览中忽略与可见字符明显重叠的空格，并记下数量。完整逐字符
        # 恢复仍保留在 recovered_spans，便于区分原 glyph 与派生排版。
        visible = [c for c in chars if c["text"] != " "]
        suppressed_spaces = 0
        kept = []
        for char in chars:
            overlap = any(
                min(char["bbox"][2], other["bbox"][2]) - max(char["bbox"][0], other["bbox"][0])
                > 0.2 * char["space_width"] for other in visible
            )
            if char["text"] == " " and overlap:
                suppressed_spaces += 1
            else:
                kept.append(char)
        chars = kept
        text = ""
        inserted_spaces = 0
        previous = None
        for char in chars:
            if previous and previous["text"] != " " and char["text"] != " ":
                gap = char["origin"][0] - previous["bbox"][2]
                if gap > 0.8 * char["space_width"]:
                    text += " "
                    inserted_spaces += 1
            text += char["text"]
            previous = char
        bboxes = [s["bbox"] for s in group]
        lines.append({
            "text": text.strip(),
            "bbox": [min(b[0] for b in bboxes), min(b[1] for b in bboxes), max(b[2] for b in bboxes), max(b[3] for b in bboxes)],
            "span_ids": [s["span_id"] for s in group],
            "inserted_layout_spaces": inserted_spaces,
            "suppressed_overlapping_space_glyphs": suppressed_spaces,
        })
    return lines


def recover_page_figure(
    pdf_path: str | Path,
    paper_id: str = PAPER_ID,
    pdf_page: int = PDF_PAGE,
    source_font_paths: dict[int, str | Path] | None = None,
) -> dict:
    """只恢复绑定哈希的 ReAct 图 1，返回派生数据，不写 PDF/正文。

    前置条件失败会抛 FigureRecoveryError。字形或区域不可唯一恢复时，
    返回 status='failed' 并保留 unresolved 记录和替代字符，供定位原因。
    成功表示在显式英语库存内恢复；它不是原始 Unicode 编码的证明，
    也不是人工验收。图形、颜色和不同 panel 的布局须结合原图阅读。
    """
    pdf_path = Path(pdf_path)
    if paper_id != PAPER_ID or pdf_page != PDF_PAGE:
        raise FigureRecoveryError("当前配置只支持固定 ReAct PDF 文件页 2")
    if not pdf_path.is_file() or file_sha256(pdf_path) != PDF_SHA256:
        raise FigureRecoveryError("PDF 不存在或哈希与已核对来源不符")

    with pymupdf.open(pdf_path) as doc:
        page = doc[pdf_page - 1]
        traces = [t for t in page.get_texttrace() if t["font"] == FIGURE_FONT]
        if not traces:
            raise FigureRecoveryError("本页未找到配置中的图内字体")
        if sha256(doc.extract_font(GRAPHIC_FONT_XREF)[3]).hexdigest() != GRAPHIC_FONT_SHA256:
            raise FigureRecoveryError("图形符号字体哈希与配置不符")
        mappings_by_flags = {}
        fonts = []
        for original_profile in FONT_PROFILES:
            profile = dict(original_profile)
            if source_font_paths and profile["xref"] in source_font_paths:
                profile["source_path"] = str(source_font_paths[profile["xref"]])
            glyph_ids = {
                c[1] for t in traces if t["flags"] == profile["flags"]
                for c in t["chars"] if c[1] != 1212
            }
            mapping, manifest = _build_mapping(doc, profile, glyph_ids)
            mappings_by_flags[profile["flags"]] = (mapping, profile["xref"])
            fonts.append(manifest)

        spans, graphics, unresolved = [], [], []
        for index, trace in enumerate(traces):
            if len(trace["chars"]) == 1 and trace["chars"][0][1] == 1212:
                # 两个绿色勾使用单独符号字体。它们没有 cmap，不硬塞成文字。
                graphics.append({
                    "glyph_id": 1212, "font_xref": GRAPHIC_FONT_XREF,
                    "embedded_font_sha256": GRAPHIC_FONT_SHA256,
                    "bbox": list(trace["bbox"]), "panel_id": _panel_for_bbox(trace["bbox"]),
                    "interpretation": "green success checkmark",
                    "interpretation_method": "AI visual review of fixed source figure",
                    "text_recovered": False,
                })
                continue
            pair = mappings_by_flags.get(trace["flags"])
            if pair is None:
                unresolved.append({"span_index": index, "reason": "unknown_font_flags"})
                continue
            mapping, xref = pair
            panel_id = _panel_for_bbox(trace["bbox"])
            if panel_id is None:
                unresolved.append({"span_index": index, "reason": "outside_reviewed_panels"})
            chars = []
            for raw_unicode, glyph_id, origin, bbox in trace["chars"]:
                item = mapping.get(glyph_id, {"status": "unmapped", "text": None})
                if item["text"] is None:
                    unresolved.append({"span_index": index, "glyph_id": glyph_id, "reason": item["status"]})
                chars.append({
                    "glyph_id": glyph_id, "raw_trace_unicode": raw_unicode,
                    "text": item["text"] or "\ufffd", "mapping_status": item["status"],
                    "origin": list(origin), "bbox": list(bbox), "space_width": trace["spacewidth"],
                })
            spans.append({
                "span_id": f"figure1_span_{index:03d}", "font_xref": xref,
                "font_assignment_basis": "fixed source hash, font flags, verified per-glyph outlines",
                "panel_id": panel_id, "bbox": list(trace["bbox"]),
                "baseline_y": chars[0]["origin"][1],
                "text": "".join(c["text"] for c in chars), "chars": chars,
            })
        panels = []
        for panel_id, label, bbox in PANEL_PROFILES:
            panel_spans = [s for s in spans if s["panel_id"] == panel_id]
            lines = _lines_for_panel(panel_spans)
            panels.append({"panel_id": panel_id, "label": label, "bbox": list(bbox), "lines": lines, "text": "\n".join(line["text"] for line in lines)})
        text = page.get_text("text", sort=False)
        result = {
            "paper_id": paper_id, "pdf_sha256": PDF_SHA256, "pdf_page": pdf_page,
            "source_method": SOURCE_METHOD,
            "runtime_versions": {"pymupdf": pymupdf.VersionBind, "fonttools": fontTools.__version__},
            "status": "failed" if unresolved else "recovered_in_reviewed_inventory",
            "coordinate_system": {"unit": "PDF point (1/72 inch)", "origin": "page top-left", "x_direction": "right", "y_direction": "down", "bbox_order": ["x0", "y0", "x1", "y1"]},
            "region": {"label": "Figure 1 excluding caption", "bbox": list(FIGURE_BBOX)},
            "fonts": fonts, "recovered_spans": spans, "panels": panels,
            "excluded_graphics": graphics, "unresolved": unresolved,
            "character_inventory": {"allowed": "visible ASCII U+0020–U+007E plus U+2026", "basis": "AI visual inspection of this fixed English figure", "unrestricted_unicode_ambiguity": True, "note": "All shape-equivalent Unicode candidates are retained; original homoglyph/space encoding cannot be established from missing cmap."},
            "statistics": {
                "original_page_control_chars": sum(ord(c) < 32 and c not in "\n\r\t" for c in text),
                "text_glyph_occurrences": sum(len(s["chars"]) for s in spans),
                "matched_text_glyph_occurrences": sum(c["mapping_status"] == "matched_in_reviewed_inventory" for s in spans for c in s["chars"]),
                "isolated_graphic_glyph_occurrences": len(graphics),
                "unresolved_count": len(unresolved),
            },
            "ai_visual_review": {"status": "pending_output_comparison", "reviewed_source_profile": "eight panel boundaries and Latin character inventory", "output_comparison_panels": []},
            "human_review_status": "pending",
            "limitations": [
                "This profile is bound to one PDF version/page and two exact local font files.",
                "Recovery is unique only within the reviewed English inventory, not across all Unicode.",
                "Green checks are isolated graphics; red crosses, highlights, boxes and connectors remain in the source image.",
                "Panel texts are separate derived material and must not be appended to ordinary body text automatically.",
            ],
        }
    # 本函数没有写源文件；结束后仍校验哈希，便于发现意外并行改动。
    if file_sha256(pdf_path) != PDF_SHA256:
        raise FigureRecoveryError("恢复过程中源 PDF 内容发生变化")
    return result


def preview_markdown(result: dict) -> str:
    """输出按 panel 分开的预览；读者可逐框对照原图和恢复文字。"""
    lines = [
        "# ReAct Figure 1 局部文字恢复预览", "",
        f"来源：`{result['paper_id']}`，文件页 {result['pdf_page']}。",
        f"PDF SHA-256：`{result['pdf_sha256']}`。", "",
        "方法：嵌入字形轮廓与固定本机字体 cmap 对照；没有 OCR，没有统一字符偏移。",
        "字符库存：此图经 AI 视觉对照的英语 ASCII 与省略号。完整 Unicode 同形候选保留在 JSON。",
        "坐标单位为 PDF 点，原点在页左上角。各框独立排列，跨框阅读以原图为准。",
        "两个绿色勾按图形元素隔离；红叉、底色、框线不作为文字恢复。人工验收状态：pending。", "",
        f"AI 输出视觉核对状态：`{result['ai_visual_review']['status']}`。", "",
    ]
    for panel in result["panels"]:
        lines.extend([f"## {panel['label']}", "", f"区域：`{panel['bbox']}`", "", "```text", panel["text"], "```", ""])
    lines.extend(["## 恢复统计", "", f"文字 glyph：{result['statistics']['matched_text_glyph_occurrences']}/{result['statistics']['text_glyph_occurrences']}。未解决项：{result['statistics']['unresolved_count']}。", ""])
    return "\n".join(lines)


def panels_sha256(result: dict) -> str:
    """绑定一次视觉核对的分区内容和坐标，重跑后内容变化就须重新核对。

    JSON 排序键并采用固定分隔符，避免仅缩进不同导致哈希不同。
    这个哈希不包含核对状态本身，防止记录核对状态时形成循环依赖。
    """
    encoded = json.dumps(result["panels"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def recovered_page_preview(
    pdf_path: str | Path, result: dict, *,
    raw_backup_display_path: str = "archive/artifacts/d3/page_previews/arxiv_2210.03629v3_page_2.raw.txt",
) -> str:
    """生成固定第 2 页的可读展示稿，不把恢复图文变成正文索引输入。

    输入是一份实际 PDF 和刚恢复的 Figure 1 结果；输出是 UTF-8 文本。
    图外仍使用原 PDF 的文字；图内使用八个独立 panel 的完整恢复文字。
    不能直接对整页按坐标排序，否则左右图框的不同轨迹会混在一起。
    此函数只组合显示内容，不改 PDF、parsed、filtered 或人工复核状态。
    """
    if (result.get("paper_id") != PAPER_ID
            or result.get("pdf_sha256") != PDF_SHA256
            or result.get("pdf_page") != PDF_PAGE
            or result.get("status") != "recovered_in_reviewed_inventory"
            or result.get("unresolved")):
        raise FigureRecoveryError("只有固定来源且完整恢复的图文才能生成可读页预览")
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file() or file_sha256(pdf_path) != PDF_SHA256:
        raise FigureRecoveryError("页预览的实际 PDF 与恢复结果不符")
    panels = result.get("panels", [])
    if [p.get("panel_id") for p in panels] != [p[0] for p in PANEL_PROFILES]:
        raise FigureRecoveryError("页预览的八个图框缺失、重复或顺序改变")
    for panel, profile in zip(panels, PANEL_PROFILES):
        if (panel.get("bbox") != list(profile[2])
                or not panel.get("lines")
                or panel.get("text") != "\n".join(line["text"] for line in panel["lines"])):
            raise FigureRecoveryError("图框的区域或显示文字与逐行记录不一致")

    # 此页图注在 y=415 之后，正文在 y=497 之后，均在图区域外。
    # 按原 block/line 保存断行和段落，不猜补正文开头承接上页的 answers。
    before, after = [], []
    region = pymupdf.Rect(FIGURE_BBOX)
    with pymupdf.open(pdf_path) as doc:
        page = doc[PDF_PAGE - 1]
        for block_index, block in enumerate(page.get_text("dict")["blocks"]):
            for line in block.get("lines", []):
                box = pymupdf.Rect(line["bbox"])
                center = pymupdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
                if region.contains(center):
                    continue  # 图内原始乱码由完整的八个恢复图框替代。
                if box.intersects(region):
                    raise FigureRecoveryError("出现跨图区域的文字行，不能自动拼接")
                text = "".join(span["text"] for span in line["spans"])
                if box.y1 <= region.y0:
                    before.append((block_index, text))
                elif box.y0 >= region.y1:
                    after.append((block_index, text))
                else:
                    raise FigureRecoveryError("图旁出现未核对文字，不能自动决定显示顺序")
    if not before or not after:
        raise FigureRecoveryError("页眉、图注或正文缺失，拒绝发布整页预览")

    lines = [
        f"paper_id: {PAPER_ID}", f"pdf_page: {PDF_PAGE}", f"pdf_sha256: {PDF_SHA256}",
        "preview_kind: recovered_display_preview_v1",
        f"recovered_panels_sha256: {panels_sha256(result)}",
        f"figure_ai_review_status: {result['ai_visual_review']['status']}",
        f"figure_human_review_status: {result['human_review_status']}",
        "automatically_indexable: false", "",
        "[预览说明，以下说明不是论文原文]",
        "图内文字采用独立恢复稿；页眉、图注、正文与页码来自同版本原 PDF。",
        "八个图框分别排列；颜色高亮、红叉、绿色勾和框线请对照原 PDF。",
        f"原始提取备份：{raw_backup_display_path}。此文件仅用于阅读预览。", "",
        "[页眉原文]",
    ]

    def append_original(entries: list[tuple[int, str]]) -> None:
        previous_block = None
        for block_index, text in entries:
            if previous_block is not None and block_index != previous_block:
                lines.append("")
            lines.append(text)
            previous_block = block_index

    append_original(before)
    lines += ["", "[Figure 1 图中文字恢复稿]"]
    for panel in panels:
        # panel.text 首行保留原图标题；panel_id 只是显示稿的定位标签。
        lines += ["", f"[图框定位: {panel['panel_id']}]", panel["text"]]
    lines += ["", "[原图注、正文与页码]"]
    append_original(after)
    preview = "\n".join(lines) + "\n"
    if any(ord(c) < 32 and c not in "\n\r\t" for c in preview) or "\ufffd" in preview:
        raise FigureRecoveryError("整页预览仍有异常字符，拒绝覆盖旧预览")
    return preview
