"""MinerU 4 complete-document parsing and its ordered physical source units."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata


def _normalized_page_sizes(layout):
    pages = []
    for index, page in enumerate(layout.get("pdf_info") or []):
        if not isinstance(page, dict):
            raise ValueError("API layout page must be an object")
        page_idx = page.get("page_idx", index)
        size = page.get("page_size")
        if (type(page_idx) is not int or page_idx < 0
                or not isinstance(size, list) or len(size) != 2
                or any(type(value) not in (int, float) or not value > 0 for value in size)):
            raise ValueError("API layout page_idx/page_size is invalid")
        pages.append({"page_idx": page_idx, "width_pt": size[0], "height_pt": size[1]})
    if len(pages) != len({page["page_idx"] for page in pages}):
        raise ValueError("API layout page indices must be unique")
    return pages


def add_page_dimensions(middle, layout):
    """Add the page sizes required by the existing source projection.

    The SDK conversion already normalizes every block bbox to 0–1. This helper
    deliberately only copies page identity and physical dimensions.
    """
    if not isinstance(middle, dict) or not isinstance(middle.get("pages"), list):
        raise ValueError("converted MiddleJson pages are missing")
    pages = _normalized_page_sizes(layout)
    if [page.get("page_idx") for page in middle["pages"]] != [page["page_idx"] for page in pages]:
        raise ValueError("converted MiddleJson page indices differ from API layout")
    extensions = middle.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("converted MiddleJson extensions must be an object")
    layout_extension = extensions.setdefault("docvortex_layout", {})
    if not isinstance(layout_extension, dict):
        raise ValueError("docvortex_layout extension must be an object")
    layout_extension["pages"] = pages
    return middle


def _prefix_image_paths(middle, image_dir):
    """Make converted asset paths relative to the stored mineru directory."""
    def visit(value):
        if isinstance(value, dict):
            path = value.get("image_path")
            if isinstance(path, str) and path and not path.replace("\\", "/").startswith("images/"):
                if (image_dir / path).is_file():
                    value["image_path"] = "images/" + Path(path).name
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(middle)
    return middle


def _write_api_middle(layout_path, middle_path):
    from mineru.backend.postprocess.legacy_middle_json import read_legacy_middle_json

    layout_path, middle_path = Path(layout_path), Path(middle_path)
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    middle = read_legacy_middle_json(layout).to_dict()
    add_page_dimensions(middle, layout)
    _prefix_image_paths(middle, layout_path.parent / "images")
    middle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = middle_path.with_name(middle_path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(middle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, middle_path)
    finally:
        temporary.unlink(missing_ok=True)


def install_api_bundle(api_dir, output_dir, *, project_root):
    """Convert one preserved official-API bundle into the existing middle format."""
    api_dir, output_dir = Path(api_dir).resolve(), Path(output_dir).resolve()
    layout_path = api_dir / "layout.json"
    if not layout_path.is_file():
        raise ValueError("API 解析目录缺少 layout.json。")
    output_dir.mkdir(parents=True, exist_ok=True)
    middle_path = output_dir / "middle_json.json"
    if not middle_path.is_file():
        python = os.environ.get("MINERU_PYTHON") or str(Path(project_root) / ".venv-mineru/Scripts/python.exe")
        if not Path(python).is_file():
            raise ValueError("请在 .venv-mineru 安装 requirements-mineru.txt，或设置 MINERU_PYTHON。")
        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "utf-8"
        subprocess.run([python, "-X", "utf8", str(Path(__file__).resolve()),
                        "--api-layout", str(layout_path), str(middle_path)],
                       cwd=project_root, env=environment, check=True)
    images = api_dir / "images"
    if images.is_dir():
        shutil.copytree(images, output_dir / "images", dirs_exist_ok=True)
    return middle_path


def api_parser_profile(layout_path):
    """Record the actual cloud pipeline instead of borrowing the local recipe."""
    layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    ocr = layout.get("_ocr_enable")
    if type(ocr) is not bool:
        raise ValueError("API layout 缺少可信的 _ocr_enable。")
    version = layout.get("_version_name")
    backend = layout.get("_backend")
    effort = layout.get("_effort")
    if not all(isinstance(value, str) and value.strip() for value in (version, backend, effort)):
        raise ValueError("API layout 缺少 _version_name/_backend/_effort。")
    return {"name": "mineru-api", "version": version, "tier": "cloud",
            "backend": backend, "effort": effort, "page_range": "all",
            "ocr_mode": "ocr" if ocr else "txt", "image_analysis": False,
            "model_version": "vlm", "enable_formula": True, "enable_table": True,
            "adapter_revision": "mineru-api-layout-v1"}


def parse_structured_pdf(pdf_path, output_dir, *, project_root, api_layout=None):
    output_dir = Path(output_dir)
    middle_path = output_dir / "middle_json.json"
    if not middle_path.is_file():
        if api_layout is not None:
            install_api_bundle(Path(api_layout).resolve().parent, output_dir, project_root=project_root)
        else:
            python = os.environ.get("MINERU_PYTHON") or str(Path(project_root) / ".venv-mineru/Scripts/python.exe")
            if not Path(python).is_file():
                raise ValueError("请在 .venv-mineru 安装 requirements-mineru.txt，或设置 MINERU_PYTHON。")
            environment = dict(os.environ)
            environment.setdefault("MINERU_MODEL_SOURCE", "modelscope")
            environment.setdefault("MINERU_MODEL_SMALL_BACKEND", "torch")
            environment.setdefault("MINERU_MODEL_VLM_ENGINE", "lmdeploy")
            environment.setdefault("MINERU_DEVICE_MODE", "cuda")
            environment.setdefault("MINERU_LMDEPLOY_DEVICE", "cuda")
            environment["PYTHONIOENCODING"] = "utf-8"
            subprocess.run([python, str(Path(__file__).resolve()), str(pdf_path), str(output_dir)],
                           cwd=project_root, env=environment, check=True)
    return json.loads(middle_path.read_text(encoding="utf-8"))


def _inline(spans):
    if isinstance(spans, str):
        return spans
    parts = []
    for span in spans or []:
        content = span.get("content", "")
        text = _inline(content) if isinstance(content, list) else content
        parts.append("$" + text + "$" if span.get("type") == "equation_inline" else text)
    return "".join(parts)


def structure_units(middle):
    """Project the existing MiddleJson; keep the original JSON and asset paths on disk."""
    dimensions = {page["page_idx"]: [page["width_pt"], page["height_pt"]]
                  for page in middle.get("extensions", {}).get("docvortex_layout", {}).get("pages", [])}
    units, section_path = [], []

    def reference_section():
        for title in section_path:
            label = unicodedata.normalize("NFKC", title).strip()
            label = re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", label)
            if label.strip(" :：.").casefold() in ("references", "bibliography", "参考文献"):
                return True
        return False
    first_page = middle["pages"][0]
    frontmatter_end = next((block["bbox"][1] for block in first_page["blocks"]
                            if block["type"] == "paragraph_title" and block.get("bbox")
                            and _inline(block.get("content", [])).strip().casefold() in ("abstract", "摘要")), None)

    def project(block, page, path, inherited_bbox=None):
        nonlocal section_path
        kind = block["type"]
        bbox = block.get("bbox") or inherited_bbox
        identifier = f"p{page['page_idx']}:" + "/".join(str(value) for value in path)
        unit = {"block_id": identifier, "block_path": ["pages", page["page_idx"], "blocks", *path],
                "pdf_page": page["page_idx"] + 1, "bbox": deepcopy(bbox),
                "page_size": dimensions.get(page["page_idx"]), "coordinate_system": "normalized",
                "section_path": list(section_path), "continues_prev": block.get("continues_prev"),
                "source_char_available": True, "parser_type": kind}
        content = block.get("content", "")
        if kind in ("doc_title", "paragraph_title"):
            text = _inline(content)
            level = block.get("level", 1 if kind == "doc_title" else 2)
            if kind == "paragraph_title":
                depth = max(1, level - 1)
                section_path = section_path[:depth - 1] + [text]
            unit.update(type="heading", text=text, section_path=list(section_path), level=level)
        elif kind in ("table", "image", "chart"):
            children = content if isinstance(content, list) else []
            bodies = [child for child in children if child["type"].endswith("_body")]
            captions = [child for child in children if child["type"].endswith("_caption")]
            footnotes = [child for child in children if child["type"].endswith("_footnote")]
            body = bodies[0] if bodies else {}
            field_sources = {}

            def component_source(child, start, end):
                child_index = next(index for index, candidate in enumerate(children) if candidate is child)
                return {"block_id": identifier + "/content/" + str(child_index),
                        "bbox": deepcopy(child.get("bbox")), "page_size": unit["page_size"],
                        "coordinate_system": "normalized", "field_start": start, "field_end": end,
                        "source_field": "content", "source_char_available": False}

            def component_text(selected, field):
                text, sources = "", []
                for child in selected:
                    if text:
                        text += "\n"
                    start = len(text)
                    text += _inline(child.get("content", []))
                    sources.append(component_source(child, start, len(text)))
                field_sources[field] = sources
                return text

            unit.update(type="table" if kind == "table" else "image", text=body.get("content", ""),
                        caption=component_text(captions, "caption"),
                        footnotes=component_text(footnotes, "footnotes"),
                        assets=[{key: child[key] for key in ("type", "image_path", "image_url", "bbox", "index")
                                 if key in child} for child in children],
                        source_char_available=False)
            if kind == "table":
                unit["table_html"] = body.get("content", "")
                if body:
                    field_sources["table_html"] = [component_source(body, 0, len(unit["table_html"]))]
            unit["field_sources"] = field_sources
            unit["source_blocks"] = deepcopy(children)
        elif kind == "list":
            unit.update(type="reference" if block.get("sub_type") == "ref_text" or reference_section() else "list",
                        text="\n".join(_inline(child.get("content", [])) for child in content),
                        items=[_inline(child.get("content", [])) for child in content])
            unit["source_blocks"] = deepcopy(content)
        elif kind == "equation":
            unit.update(type="formula", text=content, source_char_available=False,
                        assets=[{key: block[key] for key in ("image_path", "image_url") if key in block}])
        else:
            role = {"ref_text": "reference", "header": "header", "footer": "footer",
                    "aside_text": "header", "page_number": "footer"}.get(kind, "text")
            if kind == "text" and reference_section():
                role = "reference"
            if (page["page_idx"] == first_page["page_idx"] and kind == "text" and bbox
                    and frontmatter_end is not None and bbox[3] <= frontmatter_end):
                # Authors/affiliations may occur later in block order than left-column prose.
                role = "header"
                unit["source_role"] = "frontmatter"
            unit.update(type=role, text=_inline(content))
        units.append(unit)

    for page in middle["pages"]:
        for index, block in enumerate(page["blocks"]):
            project(block, page, [index])
    return units


def _parse_and_save(pdf_path, output_dir):
    from mineru.parser import parse
    from mineru.parser.writer import FileBasedDataWriter

    result = parse(pdf_path, tier="standard", page_range="", ocr_mode="auto", image_analysis=False)
    result.save(FileBasedDataWriter(output_dir))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--api-layout":
        _write_api_middle(sys.argv[2], sys.argv[3])
    else:
        _parse_and_save(sys.argv[1], sys.argv[2])
