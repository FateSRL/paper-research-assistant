"""D3 任务 A：读取本地 PDF，并保存逐页文本。

本模块负责两件事：
1. 根据 corpus.json 中的一项配置，解析对应 PDF。
2. 把页记录保存成 JSONL 文件。

导入本模块不会自动解析 PDF。
"""

import hashlib
import json
from pathlib import Path

import pymupdf


def parse_pdf_pages(paper: dict, project_root: Path) -> list[dict]:
    """解析一篇 PDF，返回包含所有页面的记录列表。

    paper：
        corpus.json 中的一项，例如 RAG 论文的那一个字典。
        里面包含 paper_id、local_path、pdf_sha256、page_count 等字段。

    project_root：
        独立项目的根目录，用来解释 local_path 中的相对路径。

    返回值：
        一个列表。列表中的每个字典对应 PDF 的一页。
        本函数只读取 PDF、返回数据，不负责保存文件。
    """

    # 清单中的 local_path 相对项目根目录。
    # 例如：
    # project_root = D:/course/paper-research-assistant
    # local_path = data/papers/2005.11401v4.pdf
    # 两者拼接后得到 PDF 的完整位置。
    pdf_path = project_root / paper["local_path"]

    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到 PDF 文件：{pdf_path}")

    # read_bytes() 读取原始文件字节。
    # SHA-256 用于确认当前读取的 PDF 与清单中的固定文件一致。
    actual_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    if actual_sha256 != paper["pdf_sha256"]:
        raise ValueError(
            f"PDF 哈希与清单不一致：{paper['paper_id']}。"
            "请检查是否读取了其他版本或替换过文件。"
        )

    page_records = []

    # with 管理文档资源，正常结束或发生异常时都会关闭文档。
    with pymupdf.open(str(pdf_path)) as document:
        # 实际页数必须与清单一致。
        if document.page_count != paper["page_count"]:
            raise ValueError(
                f"PDF 页数与清单不一致：{paper['paper_id']}，"
                f"实际 {document.page_count} 页，"
                f"清单记录 {paper['page_count']} 页"
            )

        # document 可以遍历，每次得到一个页面对象。
        # start=1 让保存的文件页序从 1 开始，便于对照 PDF 阅读器。
        for pdf_page, page in enumerate(document, start=1):
            text = page.get_text("text")

            # 保留完整提取文本。
            # 即使这一页没有文字，也保存 text=""，避免页序发生变化。
            page_records.append(
                {
                    "paper_id": paper["paper_id"],
                    "pdf_sha256": actual_sha256,
                    "pdf_page": pdf_page,
                    "text": text,
                }
            )

    # 把结果交给调用者，调用者决定如何保存或进一步处理。
    return page_records


def save_page_records(page_records: list[dict], output_path: Path) -> None:
    """把页记录保存为 UTF-8 JSONL，一行对应 PDF 的一页。"""

    # 如果输出目录还不存在，就创建它。
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # "w" 表示写入；再次运行时会重新生成同名输出文件。
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in page_records:
            # 把 Python 字典转换成 JSON 字符串。
            # ensure_ascii=False 让中文直接保存为可读字符。
            json_line = json.dumps(record, ensure_ascii=False)

            # 每条 JSON 后添加一个真正的换行，形成 JSONL。
            # text 内部的换行会被 json.dumps 转义，
            # 所以一页记录仍然只占文件中的一行。
            file.write(json_line + "\n")