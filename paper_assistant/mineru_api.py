"""Call the official MinerU v4 upload API and save its original result bundle."""

from contextlib import nullcontext
from pathlib import Path
import time
from zipfile import BadZipFile, ZipFile

import httpx

from paper_assistant.config import MinerUAPISettings


API_BASE_URL = "https://mineru.net/api/v4"


class MinerUAPIError(ValueError):
    """A failed upload, parsing task or result download."""


def parse_pdf_via_api(pdf_path, output_dir, settings: MinerUAPISettings, *,
                      page_ranges=None, wait_timeout=600.0, poll_interval=3.0,
                      http_client=None, on_progress=None):
    """Upload one PDF, wait for the task, and unpack MD/JSON/assets without indexing."""
    source, output = Path(pdf_path).resolve(), Path(output_dir).resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("请指定存在的 PDF 文件。")
    if output.exists():
        raise ValueError("输出目录已存在，请指定新的 --output-dir，保留已有解析结果。")
    if not settings.token.strip():
        raise ValueError("请先在项目 .env 中填写 MINERU_API_TOKEN。")
    headers = {"Authorization": "Bearer " + settings.token}
    started = time.monotonic()

    def progress(message):
        if on_progress:
            on_progress(message)

    def api_json(response):
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise MinerUAPIError("MinerU API 没有返回有效 JSON。") from error
        if not isinstance(body, dict) or body.get("code") != 0:
            code = body.get("code", "unknown") if isinstance(body, dict) else "unknown"
            message = str(body.get("msg", "请求失败")) if isinstance(body, dict) else "响应格式错误"
            message = message.replace(settings.token, "[redacted]")
            raise MinerUAPIError(f"MinerU API 错误 {code}：{message}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MinerUAPIError("MinerU API 响应缺少 data。")
        return data

    owner = httpx.Client(timeout=30.0) if http_client is None else nullcontext(http_client)
    try:
        with owner as client:
            file_options = {"name": source.name, "is_ocr": True}
            if page_ranges:
                file_options["page_ranges"] = page_ranges
            payload = {"files": [file_options], "model_version": "vlm",
                       "enable_formula": True, "enable_table": True}
            progress("申请上传：VLM，OCR／公式／表格识别均开启。")
            data = api_json(client.post(API_BASE_URL + "/file-urls/batch",
                                        headers=headers, json=payload))
            batch_id, upload_urls = data.get("batch_id"), data.get("file_urls")
            if not batch_id or not isinstance(upload_urls, list) or len(upload_urls) != 1:
                raise MinerUAPIError("MinerU API 未返回本文件的 batch_id 或上传地址。")
            progress("任务批次：" + str(batch_id))
            with source.open("rb") as stream:
                client.put(upload_urls[0], content=stream).raise_for_status()

            deadline, last_state = time.monotonic() + wait_timeout, None
            while True:
                if time.monotonic() >= deadline:
                    raise MinerUAPIError(f"等待解析超时，批次 {batch_id}；未重新提交任务。")
                data = api_json(client.get(API_BASE_URL + "/extract-results/batch/" + str(batch_id),
                                           headers=headers))
                rows = data.get("extract_result") or []
                row = rows[0] if rows else {}
                state = row.get("state", "pending")
                if state != last_state:
                    progress("解析状态：" + str(state))
                    last_state = state
                if state == "failed":
                    message = str(row.get("err_msg") or "服务未提供失败原因")
                    raise MinerUAPIError("MinerU 解析失败：" + message.replace(settings.token, "[redacted]"))
                if state == "done":
                    download_url = row.get("full_zip_url")
                    if not download_url:
                        raise MinerUAPIError("解析已结束，但没有返回结果 ZIP 地址。")
                    break
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

            output.mkdir(parents=True)
            archive_path = output / "result.zip"
            progress("下载并解压原始结果。")
            with client.stream("GET", download_url, follow_redirects=True) as response:
                response.raise_for_status()
                with archive_path.open("wb") as stream:
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
            with ZipFile(archive_path) as archive:
                for entry in archive.infolist():
                    if not (output / entry.filename).resolve().is_relative_to(output):
                        raise MinerUAPIError("结果 ZIP 包含输出目录之外的路径。")
                archive.extractall(output)
    except httpx.HTTPStatusError as error:
        raise MinerUAPIError(f"MinerU 请求失败，HTTP {error.response.status_code}。") from None
    except httpx.RequestError as error:
        raise MinerUAPIError(f"MinerU 网络请求失败：{type(error).__name__}。") from None
    except BadZipFile:
        raise MinerUAPIError("MinerU 下载结果不是有效 ZIP；已保留下载文件。") from None

    markdown = sorted(output.rglob("*.md"))
    json_files = sorted(output.rglob("*.json"))
    if not markdown or not json_files:
        raise MinerUAPIError("结果包缺少 Markdown 或 JSON，请检查原始 ZIP 内容。")
    return {"batch_id": batch_id, "output_dir": str(output),
            "markdown_files": [str(path) for path in markdown],
            "json_files": [str(path) for path in json_files],
            "elapsed_seconds": round(time.monotonic() - started, 3)}
