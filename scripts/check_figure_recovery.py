"""验证固定 Figure 1 恢复的来源、全字符覆盖、关键内容和各框轨迹顺序。"""

import json
import re
from pathlib import Path

from paper_assistant.figure_recovery import (
    FigureRecoveryError, PAPER_ID, PDF_SHA256, file_sha256, recover_page_figure,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """运行独立于恢复结果的语义锚点与负例检查，不把 AI 检查记成人工。

    对照锚点和动作编号来自原图，而不是由结果反推。特别保留右下角
    Act 2 到 Act 6 的跳号：原图省略了中间步骤，恢复不能自行补齐。
    负例必须明确失败；检查源 PDF/parsed 的哈希，确认恢复没有覆盖它们。
    """
    pdf = PROJECT_ROOT / "data/papers/2210.03629v3.pdf"
    parsed = PROJECT_ROOT / "data/parsed/arxiv_2210.03629v3.jsonl"
    before = (file_sha256(pdf), file_sha256(parsed))
    result = recover_page_figure(pdf)
    panels = {p["panel_id"]: p["text"] for p in result["panels"]}
    checks = []
    check_records = []

    def check(label: str, passed: bool) -> None:
        checks.append(passed)
        check_records.append({"check": label, "passed": passed})
        print(f"{'PASS' if passed else 'FAIL'}：{label}")

    check("来源 paper_id / PDF 哈希 / 文件页 2", result["paper_id"] == PAPER_ID and result["pdf_sha256"] == PDF_SHA256 and result["pdf_page"] == 2)
    check("文字每次出现都经过轮廓/cmap 校验", result["statistics"]["matched_text_glyph_occurrences"] == result["statistics"]["text_glyph_occurrences"] and not result["unresolved"])
    check("字体来源哈希和真实 cmap 已校验", all(f["source_hash_verified"] and f["embedded_hash_verified"] and f["source_has_unicode_cmap"] for f in result["fonts"]))
    check("没有偷偷加入绿色勾文字", len(result["excluded_graphics"]) == 2 and all(not g["text_recovered"] for g in result["excluded_graphics"]))
    check("省略号经轮廓匹配恢复为 U+2026，不能按 gid 加偏移", next(m for f in result["fonts"] if f["xref"] == 194 for m in f["glyph_mapping"] if m["glyph_id"] == 170)["unicode_codepoint"] == 0x2026)
    check("原始 Unicode 同形歧义被明示保留", result["character_inventory"]["unrestricted_unicode_ambiguity"] and any(len(m.get("all_unicode_candidates", [])) > 1 for f in result["fonts"] for m in f["glyph_mapping"]))
    check("空格也须匹配来源轮廓/字宽/cmap，不能把所有空轮廓当空格", all(next(m for m in f["glyph_mapping"] if m["glyph_id"] == 3)["metric_match"] and next(m for m in f["glyph_mapping"] if m["glyph_id"] == 3)["unicode_codepoint"] == 32 for f in result["fonts"]))
    anchors = {
        "1_question": ["Aside from the Apple Remote, what other device", "designed to interact with?"],
        "1a_standard": ["Answer: iPod"],
        "1b_cot": ["Apple Remote was", "Apple TV", "iPhone, iPad, iPod"],
        "1c_act_only": ["Search[Apple Remote]", "Finish[yes]"],
        "1d_react": ["Search[Front Row (software)]", "Finish[keyboard function keys]"],
        "2_environment": ["Looking quickly around", "Put some pepper shaker on a drawer."],
        "2a_act_only": ["Take peppershaker 1 from sinkbasin 1", "Nothing happens."],
        "2b_react": ["Think[First I need to find a pepper shaker", "You put pepper shaker 1 in/on the drawer 1."],
    }
    for panel_id, expected in anchors.items():
        normalized = re.sub(r"\s+", " ", panels.get(panel_id, ""))
        check(f"原图分区语义锚点 {panel_id}", all(anchor in normalized for anchor in expected))
    expected_events = {
        "1c_act_only": ["Act1", "Obs1", "Act2", "Obs2", "Act3", "Obs3", "Act4"],
        "1d_react": ["Thought1", "Act1", "Obs1", "Thought2", "Act2", "Obs2", "Thought3", "Act3", "Obs3", "Thought4", "Act4"],
        "2a_act_only": ["Act1", "Obs1", "Act2", "Obs2", "Act3", "Obs3", "Act4", "Obs4", "Act5", "Obs5"],
        "2b_react": ["Act1", "Act2", "Obs2", "Act6", "Obs6", "Act7", "Obs7", "Act8", "Act9", "Obs9", "Act10", "Obs10", "Act11", "Obs11"],
    }
    for panel_id, expected in expected_events.items():
        events = [word + number for word, number in re.findall(r"\b(Thought|Act|Obs)\s*(\d+)\s*:", panels[panel_id])]
        check(f"原图轨迹步骤顺序 {panel_id}", events == expected)
    for label, kwargs in (
        ("错误页序被拒绝", {"pdf_page": 1}),
        ("错误 paper_id 被拒绝", {"paper_id": "unknown_paper"}),
        ("本机来源字体缺失被明确拒绝", {"source_font_paths": {193: PROJECT_ROOT / "artifacts/d3/figure_recovery/missing-font.ttf"}}),
        ("字体版本/哈希不符被明确拒绝", {"source_font_paths": {193: "C:/Windows/Fonts/cour.ttf"}}),
    ):
        try:
            recover_page_figure(pdf, **kwargs)
        except FigureRecoveryError:
            check(label, True)
        else:
            check(label, False)
    try:
        # 使用已有 JSONL 路径作为错误来源，不新建/改写任何源文件。
        recover_page_figure(parsed)
    except FigureRecoveryError:
        check("来源文件哈希不符被明确拒绝", True)
    else:
        check("来源文件哈希不符被明确拒绝", False)
    check("源 PDF 和逐页 JSONL 未被改写", before == (file_sha256(pdf), file_sha256(parsed)))
    check("人工验收仍为 pending", result["human_review_status"] == "pending")
    print(f"\n汇总：{sum(checks)}/{len(checks)}")
    # 保存可读检查结果供复盘。这里记录的是程序检查，不把它提升为人工
    # 验收或刚执行的视觉核对；实际 AI 视觉核对单独保存在 ai-review.json。
    report_path = PROJECT_ROOT / "archive/run_logs/figure_recovery/check-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "paper_id": result["paper_id"], "pdf_sha256": result["pdf_sha256"],
        "pdf_page": result["pdf_page"], "runtime_versions": result["runtime_versions"],
        "source_pdf_sha256_before_after": [before[0], file_sha256(pdf)],
        "source_parsed_sha256_before_after": [before[1], file_sha256(parsed)],
        "statistics": result["statistics"], "checks": check_records,
        "passed": sum(checks), "total": len(checks), "all_passed": all(checks),
        "ai_visual_review_record": "artifacts/d3/figure_recovery/ai-review.json",
        "human_review_status": "pending",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"检查记录：{report_path}")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
