"""Download one official MinerU API result without changing the paper library.

Run: python -X utf8 -m scripts.parse_mineru_api <PDF path> [--pages 3]
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from paper_assistant.config import ConfigError, load_mineru_api_settings
from paper_assistant.mineru_api import MinerUAPIError, parse_pdf_via_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="官方 MinerU 精准解析 API：VLM + OCR，保存原始 MD/JSON")
    parser.add_argument("pdf", nargs="?", help="PDF 路径；相对路径按项目根目录解释")
    parser.add_argument("--output-dir", help="新的输出目录，默认 artifacts/v2/parsing/mineru-api-<UTC时间>")
    parser.add_argument("--pages", help='可选页码范围，例如 "3" 或 "2,4-6"；默认整篇')
    parser.add_argument("--check-config", action="store_true", help="只检查 Token 是否配置，不发送网络请求")
    args = parser.parse_args(argv)
    try:
        settings = load_mineru_api_settings()
        if args.check_config:
            print("[OK] 已从项目 .env 读取 MINERU_API_TOKEN；未发送网络请求。")
            return 0
        if not args.pdf:
            parser.error("请指定 PDF 路径，或使用 --check-config。")
        source = PROJECT_ROOT / args.pdf
        output = (PROJECT_ROOT / args.output_dir if args.output_dir else
                  PROJECT_ROOT / "artifacts/v2/parsing" /
                  ("mineru-api-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")))
        result = parse_pdf_via_api(source, output, settings, page_ranges=args.pages,
                                  on_progress=lambda message: print(message, flush=True))
    except (ConfigError, MinerUAPIError, OSError, ValueError) as error:
        print("[FAIL] " + str(error))
        return 1
    print(f"[OK] 解析结果：{result['output_dir']}，用时 {result['elapsed_seconds']} 秒")
    for path in result["markdown_files"]:
        print("Markdown：" + path)
    print("原始 JSON／图片及 ZIP 同目录保存；本次未入库或调用 embedding。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
