"""恢复本语料中已经定位的六处数学内容，结果独立于原始/过滤正文。

RAG 五处使用作者发布的同版本 LaTeX；Reflexion 一处使用固定 PDF 的
视觉转写。这里的“恢复”是有明确来源的局部配置，不是通用数学 OCR。
PDF 中的 ∑ 可能被读成 X，且下标不在同一行；全局 replace 无法解决。
"""

from hashlib import sha256
import json
from pathlib import Path
import re

import pymupdf


REVISION = "d3-known-math-v1"
RESEARCH = Path("artifacts/d3/formula_recovery/source_research")
ARCHIVE_NAME = "arxiv_2005.11401v4_source.tar.gz"
ARCHIVE_SHA256 = "65626b55d875cd69478172dd3d9346de60ddf32f1d04cf8a9808a5668adf7b34"
METHODS_SHA256 = "bff98bd3bee3406762fd023a404054e1014c8dfe868f66adf335bac695af96c1"
PDF_HASHES = {
    "arxiv_2005.11401v4": "23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233",
    "arxiv_2303.11366v4": "6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd",
}

# 只展开这份 methods.tex 中真正用到的作者宏。原文和宏定义另行保留。
# \topk 宏虽然存在，但本次五条原公式均未调用它；不能误加 η 下标。
MACROS = {
    "peranswer": r"p_{\text{\tiny{RAG-Sequence}}}",
    "pertoken": r"p_{\text{\tiny{RAG-Token}}}",
    "retparam": r"\eta", "genparam": r"\theta",
    "doc": "z", "answer": "y", "query": "x",
    "denc": r"\mathbf{d}", "qenc": r"\mathbf{q}",
}

# bbox 单位为 PDF 点，原点是页面左上角；pdf_page 是从 1 开始的文件页序。
# display/inline 是来源式子的呈现方式；行内式恢复完整数学范围，不只取
# 被过滤的 θ(...)=P 或 i+1 片段。坐标不是字符的读取顺序。
PROFILES = (
    {"key": "rag_sequence", "title": "RAG-Sequence", "page": 3,
     "bbox": [140, 255, 473, 296], "display_index": 0,
     "context": "2.1 Models / RAG-Sequence Model", "presentation": "display",
     "meaning": "先在同一篇文档下计算整个输出序列的概率，再对候选文档求和。"},
    {"key": "rag_token", "title": "RAG-Token", "page": 3,
     "bbox": [176, 358, 435, 398], "display_index": 1,
     "context": "2.1 Models / RAG-Token Model", "presentation": "display",
     "meaning": "每个输出位置先对候选文档求和，再把各位置的概率连乘。"},
    {"key": "rag_dpr", "title": "DPR and the two encoders", "page": 3,
     "bbox": [151, 471, 460, 491], "display_index": 2,
     "context": "2.2 Retriever: DPR", "presentation": "display",
     "meaning": "检索概率与文档向量和查询向量内积的指数成正比；下标 d/q 区分两个编码器。"},
    {"key": "rag_training_loss", "title": "Training loss", "page": 4,
     "bbox": [361.4169921875, 73.86836242675781, 436.23345947265625, 86.47460174560547],
     "inline_prefix": r"\sum_j -\log p(",
     "context": "2.4 Training, continued at page 4", "presentation": "inline",
     "meaning": "对训练样本 j 的负对数概率求和。原文没有额外命名这个损失。"},
    {"key": "rag_token_transition", "title": "RAG-Token transition probability", "page": 4,
     # 旧区域上下边缘会混入邻行正文。这个窄区域仍包含完整的 ∑ 下限、
     # p 的撇号和各个下标；它只是证据坐标，数学表达式仍从作者源码读取。
     "bbox": [237.6, 196.8, 490.35, 210.4],
     "inline_prefix": r"p'_\genparam(y_i|\query, y_\history{i}) =",
     "context": "2.5 Decoding / RAG-Token", "presentation": "inline",
     "meaning": "给定输入和已生成前缀，得到下一个 token 的转移概率；原文求和变量 z 与项内 z_i 原样保留。"},
    {"key": "reflexion_action_next", "title": "Reflexion action subscript", "page": 4,
     "bbox": [485.3299865722656, 629.4673461914062, 503.5060729980469, 642.7405395507812],
     "paper_id": "arxiv_2303.11366v4", "latex": r"a'_{i+1}",
     "context": "3 Reflexion / Self-reflection, prose below Figure 2",
     "presentation": "inline_fragment",
     "meaning": "正文中的一个带撇号的动作变量，下标为 i+1；不是一条独立方程。"},
)


class FormulaRecoveryError(ValueError):
    """来源不符时拒绝沿用固定恢复配置，避免把其他版本的式子写进来。"""


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _verify_file(path: Path, expected: str) -> None:
    """先比较内容哈希；文件名相同并不保证 PDF/源码内容相同。"""
    if not path.is_file() or file_sha256(path) != expected:
        raise FormulaRecoveryError(f"来源文件缺失或内容与固定配置不符：{path}")


def expand_rag_macros(expression: str) -> str:
    r"""把作者的简写展开为可以独立排版的 LaTeX，不猜测数学含义。

    例如 \doc → z、\genparam → θ，\history{i} → {1:i-1}。
    TeX 命令名只含英文字母：\doc_i 应展开为 z_i；不能用 Python 的
    \b 边界，因为 Python 把下划线算作单词字符，会漏掉 \doc_i。
    \mathclap、\tiny 和间距命令保留，维持作者原本的数学排版设置。
    本函数只支持上述固定宏；来源变了应重新检查，不能悄悄换表达式。
    """
    expanded = expression.replace(r"\history{i}", "{1:i-1}")
    pattern = r"\\(" + "|".join(MACROS) + r")(?![A-Za-z])"
    expanded = re.sub(pattern, lambda match: MACROS[match.group(1)], expanded)
    if re.search(r"\\(?:history|topk|docs)(?![A-Za-z])", expanded):
        raise FormulaRecoveryError("出现本配置没有展开的作者宏")
    return expanded


def _source_expression(source: str, profile: dict) -> tuple[str, int]:
    r"""从已校验的源码取出完整数学环境，同时记录其起始行号。

    展示公式在 \[ ... \] 中；正文数学在 $ ... $ 中。这里不实现通用
    TeX 解析器，而是取这份固定文件中的三个展示环境或唯一的行内前缀。
    这样拿到的是原公式，输出不是从乱码字符顺序拼出来的一串猜测。
    """
    if "display_index" in profile:
        matches = list(re.finditer(r"\\\[\s*(.*?)\s*\\\]", source, re.S))
        if len(matches) != 3:
            raise FormulaRecoveryError("展示数学环境数量与已复核源码不符")
        match = matches[profile["display_index"]]
    else:
        matches = [m for m in re.finditer(r"(?<!\\)\$(.*?)(?<!\\)\$", source, re.S)
                   if m.group(1).startswith(profile["inline_prefix"])]
        if len(matches) != 1:
            raise FormulaRecoveryError("行内公式未唯一定位，不能自动选第一项")
        match = matches[0]
    return match.group(1).strip(), source.count("\n", 0, match.start(1)) + 1


def formula_payload_sha256(result: dict) -> str:
    """核对记录绑定具体恢复内容；修改式子/页码/来源后不能沿用旧结论。"""
    payload = json.dumps(result["formulas"], ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def recover_known_formulas(project_root: Path) -> dict:
    """读取固定来源，返回五组 RAG 数学表达式与一个 Reflexion 行内变量。

    输入是项目根目录，输出是派生字典。此函数不写源文件、不读取 .env、
    不联网、不调用模型，也不改变 corpus 或开发题。每项保留原数学源码、
    原 PDF 区域的损坏抽取文本和来源哈希，便于区分恢复稿与原始证据。
    """
    archive_path = project_root / RESEARCH / ARCHIVE_NAME
    methods_path = project_root / RESEARCH / "source_text/methods.tex"
    _verify_file(archive_path, ARCHIVE_SHA256)
    _verify_file(methods_path, METHODS_SHA256)
    source = methods_path.read_text(encoding="utf-8")
    corpus = json.loads((project_root / "eval/corpus.json").read_text(encoding="utf-8"))
    by_id = {paper["paper_id"]: paper for paper in corpus}
    paths = {}
    for paper_id, expected in PDF_HASHES.items():
        paper = by_id.get(paper_id)
        if not paper or paper.get("pdf_sha256") != expected or paper.get("arxiv_version") != "v4":
            raise FormulaRecoveryError(f"语料清单与已复核版本不符：{paper_id}")
        path = project_root / paper["local_path"]
        _verify_file(path, expected)
        paths[paper_id] = path

    formulas = []
    for profile in PROFILES:
        paper_id = profile.get("paper_id", "arxiv_2005.11401v4")
        is_source_latex = "latex" not in profile
        if is_source_latex:
            original, source_line = _source_expression(source, profile)
            latex = expand_rag_macros(original)
            provenance = {
                "method": "official_versioned_latex_source_plus_pdf_visual_cross_check",
                "source_url": "https://arxiv.org/src/2005.11401v4",
                "archive_path": (RESEARCH / ARCHIVE_NAME).as_posix(),
                "archive_sha256": ARCHIVE_SHA256, "source_member": "methods.tex",
                "source_member_sha256": METHODS_SHA256, "source_line": source_line,
                "source_latex_with_macros": original,
                "author_macro_definitions": source.splitlines()[:14],
            }
        else:
            latex = profile["latex"]
            provenance = {
                "method": "fixed_pdf_visual_transcription_with_coordinate_context",
                "source_url": by_id[paper_id]["source_url"],
                "independent_review": "archive/artifacts/d3/formula_recovery/independent/math_fragments.json",
                "source_latex_available_in_this_recovery": False,
            }
        with pymupdf.open(paths[paper_id]) as doc:
            if not 1 <= profile["page"] <= doc.page_count:
                raise FormulaRecoveryError("恢复页序超出实际 PDF 页数")
            page = doc[profile["page"] - 1]
            rect = pymupdf.Rect(profile["bbox"])
            if rect.is_empty or not page.rect.contains(rect):
                raise FormulaRecoveryError("恢复区域不在对应页面内")
            raw_clip = page.get_text("text", clip=rect)
        formula = {
            "formula_id": f"{paper_id}:p{profile['page']}:{profile['key']}",
            "key": profile["key"], "title": profile["title"],
            "paper_id": paper_id, "arxiv_version": "v4", "pdf_page": profile["page"],
            "pdf_sha256": PDF_HASHES[paper_id], "bbox": profile["bbox"],
            "coordinate_system": "PDF points, top-left origin",
            "context": profile["context"], "source_presentation": profile["presentation"],
            "latex": latex, "meaning_zh": profile["meaning"], "provenance": provenance,
            "raw_pdf_clip_text": raw_clip,
            "raw_pdf_clip_text_sha256": sha256(raw_clip.encode()).hexdigest(),
            "human_review_status": "pending", "automatically_indexable": False,
            "recovery_revision": REVISION,
        }
        formulas.append(formula)
    result = {
        "artifact_kind": "known_math_recovery", "recovery_revision": REVISION,
        "status": "recovered_for_declared_scope", "formulas": formulas,
        "statistics": {"rag_mathematical_expression_groups": 5, "reflexion_inline_fragments": 1,
                       "total_math_items": 6},
        "ai_visual_review": {"status": "pending_output_comparison"},
        "human_review_status": "pending", "automatically_added_to_prose_index": False,
        "limits": [
            "只覆盖固定版本的六个已定位数学项，不代表全部71页公式已恢复。",
            "Reflexion项为视觉转写，其余五项来自RAG v4作者源码。",
            "ReAct附录损坏方括号和其他图中文字不属于本次数学恢复范围。",
            "恢复结果是独立覆盖层，原始/过滤正文保持不变；精确公式引用应指向本项及原图。",
        ],
    }
    result["formula_payload_sha256"] = formula_payload_sha256(result)
    return result


def preview_markdown(result: dict) -> str:
    """生成便于读源码和核对原图的中文预览；JSON 保存完整溯源字段。"""
    lines = ["# 已定位数学内容恢复稿", "", "日期：2026-10-01。五组 RAG 表达式、一个 Reflexion 行内变量。",
             "", "AI 输出核对：" + result["ai_visual_review"]["status"] + "；人工复核：pending。",
             "原始 PDF、raw 和 filtered 均保留；本稿尚未自动进入正文检索。", ""]
    for item in result["formulas"]:
        lines += [f"## {item['title']}", "", f"来源：`{item['paper_id']}`，文件页 {item['pdf_page']}；{item['context']}。",
                  "", "$$", item["latex"], "$$", "", "```latex", item["latex"], "```", "",
                  "含义：" + item["meaning_zh"], ""]
        if "source_line" in item["provenance"]:
            lines += [f"作者源码：`methods.tex:{item['provenance']['source_line']}`，固定 v4；原始宏和哈希见 JSON。", ""]
        lines += [f"[原图区域](</D:/course/paper-research-assistant/artifacts/d3/formula_recovery/evidence/{item['key']}.png>)", ""]
    lines += ["## 必须保留的原文细节", "", "- Sequence 为外层求和、内层连乘；Token 为外层连乘、内层求和。",
              "- 乘积下限只写 i，不补 i=1；top-k 内的 p 没有 η 下标。",
              "- DPR 中 d/q 为粗体，转置是 ⊤；训练损失没有另造 L= 前缀。",
              "- 转移式的求和变量 z 与项内 z_i 原样保留；Reflexion 的撇号和 i+1 下标一起恢复。", ""]
    return "\n".join(lines)


def standalone_latex(result: dict) -> str:
    """生成无需原论文其他文件的排版稿，方便在 Codex 内置 LaTeX 预览中核对。

    只排版已展开的六条式子；不执行作者整个工程，也不访问网络。
    行内表达式在核对稿中单独展示，JSON 仍记录它们原来的呈现方式。
    """
    lines = [r"\documentclass[10pt,a4paper]{article}", r"\usepackage[T1]{fontenc}",
             r"\usepackage{amsmath,amssymb,mathtools}", r"\usepackage[margin=22mm]{geometry}",
             r"\setlength{\parindent}{0pt}", r"\begin{document}",
             r"\section*{Recovered mathematical expressions}",
             r"Fixed PDFs: RAG 2005.11401v4; Reflexion 2303.11366v4.\par",
             r"RAG: official v4 author source plus PDF comparison. Reflexion: PDF visual transcription.\par",
             r"Six known items only. Human review pending. Date: 2026-10-01."]
    for item in result["formulas"]:
        paper = "RAG" if item["paper_id"] == "arxiv_2005.11401v4" else "Reflexion"
        lines += [r"\subsection*{" + item["title"] + "}",
                  f"{paper}, PDF page {item['pdf_page']}. Original form: " + item["source_presentation"].replace("_", " ") + ".",
                  r"\[", item["latex"], r"\]"]
    lines += [r"\small Source notation retained: product lower limit $i$; $p$ in top-$k$ without $\eta$;",
              r"transition sum bound $z$ but terms $z_i$; DPR transpose $\top$.", r"\end{document}", ""]
    return "\n".join(lines)
