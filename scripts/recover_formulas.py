"""离线生成已定位数学内容的 JSON、中文预览、LaTeX 核对稿和原图证据。"""

import json
from pathlib import Path

import pymupdf

from paper_assistant.formula_recovery import (
    FormulaRecoveryError, recover_known_formulas, preview_markdown, standalone_latex,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "artifacts/d3/formula_recovery"


def main() -> int:
    """真正执行恢复和保存，退出码 0=本配置处理完成，2=来源不符合要求。

    main 是命令行入口，不是只用来测试。人工复核不由退出码推断。
    固定输出目录避开 data/papers、data/parsed 和 data/filtered。
    下载作者源码已单独完成；重复运行这个命令不会再次联网。
    """
    try:
        result = recover_known_formulas(PROJECT_ROOT)
        review_path = OUTPUT / "ai-review.json"
        if review_path.is_file():
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if (review.get("formula_payload_sha256") == result["formula_payload_sha256"]
                    and review.get("status") == "completed"
                    and review.get("reviewed_by") == "codex_ai"):
                result["ai_visual_review"] = {
                    "status": "completed", "review_record": "artifacts/d3/formula_recovery/ai-review.json",
                    "reviewed_by": "codex_ai", "reviewed_at": review.get("reviewed_at"),
                    "content_hash_verified": True,
                }
        OUTPUT.mkdir(parents=True, exist_ok=True)
        evidence = OUTPUT / "evidence"
        evidence.mkdir(exist_ok=True)
        corpus = json.loads((PROJECT_ROOT / "eval/corpus.json").read_text(encoding="utf-8"))
        paths = {row["paper_id"]: PROJECT_ROOT / row["local_path"] for row in corpus}
        for item in result["formulas"]:
            with pymupdf.open(paths[item["paper_id"]]) as doc:
                page = doc[item["pdf_page"] - 1]
                page.get_pixmap(matrix=pymupdf.Matrix(6, 6), clip=pymupdf.Rect(item["bbox"])).save(
                    evidence / f"{item['key']}.png")
        (OUTPUT / "recovered_formulas.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUTPUT / "recovered_formulas.md").write_text(preview_markdown(result), encoding="utf-8")
        (OUTPUT / "recovered_formulas.tex").write_text(standalone_latex(result), encoding="utf-8")
    except (FormulaRecoveryError, OSError, ValueError) as exc:
        print(f"数学恢复失败：{exc}")
        return 2
    print("已生成：5 组 RAG 数学表达式 + 1 个 Reflexion 行内变量")
    print(f"AI 输出核对：{result['ai_visual_review']['status']}；人工复核：pending")
    print(f"恢复稿：{OUTPUT / 'recovered_formulas.md'}")
    print(f"LaTeX：{OUTPUT / 'recovered_formulas.tex'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
