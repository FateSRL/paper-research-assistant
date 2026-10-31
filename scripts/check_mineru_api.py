"""Offline official API protocol checks; no account credentials or real requests."""

import io
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import httpx

from paper_assistant import config
from paper_assistant.config import ConfigError, MinerUAPISettings
from paper_assistant.mineru_api import MinerUAPIError, parse_pdf_via_api


class MinerUAPIChecks(unittest.TestCase):
    def test_config_upload_poll_and_original_bundle_without_gpu_or_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env"
            env.write_text("MINERU_API_TOKEN=offline-token\n", encoding="utf-8")
            with patch.object(config, "ENV_FILE", env):
                settings = config.load_mineru_api_settings()
            self.assertNotIn("offline-token", repr(settings))
            source = root / "paper.pdf"
            source.write_bytes(b"%PDF-1.7\noffline-upload")
            payload = io.BytesIO()
            with ZipFile(payload, "w") as archive:
                archive.writestr("paper/full.md", "every = all = each ≤ most")
                archive.writestr("paper/layout.json", '{"pdf_info": []}')
                archive.writestr("paper/images/formula.png", b"offline-image")
            seen, polls = [], 0
            submitted = []

            def handle(request):
                nonlocal polls
                seen.append((request.method, str(request.url)))
                if request.url.host == "mineru.net":
                    self.assertEqual(request.headers["Authorization"], "Bearer offline-token")
                else:
                    self.assertNotIn("Authorization", request.headers)
                if request.method == "POST":
                    self.assertEqual(request.url.path, "/api/v4/file-urls/batch")
                    body = json.loads(request.content)
                    submitted.append(deepcopy(body))
                    self.assertEqual(body["model_version"], "vlm")
                    self.assertTrue(body["enable_formula"])
                    self.assertTrue(body["enable_table"])
                    self.assertEqual(body["files"][0]["name"], "paper.pdf")
                    self.assertTrue(body["files"][0]["is_ocr"])
                    return httpx.Response(200, json={"code": 0, "data": {
                        "batch_id": "offline-batch", "file_urls": ["https://upload.invalid/paper"]}})
                if request.method == "PUT":
                    self.assertEqual(request.read(), source.read_bytes())
                    return httpx.Response(200)
                if request.url.host == "download.invalid":
                    return httpx.Response(200, content=payload.getvalue())
                self.assertEqual(request.url.path, "/api/v4/extract-results/batch/offline-batch")
                polls += 1
                row = {"state": "running"} if polls == 1 else {
                    "state": "done", "full_zip_url": "https://download.invalid/result.zip"}
                return httpx.Response(200, json={"code": 0, "data": {"extract_result": [row]}})

            def run(output, page_ranges):
                nonlocal polls, seen
                polls, seen = 0, []
                with httpx.Client(transport=httpx.MockTransport(handle)) as client, \
                        patch("paper_assistant.mineru_api.time.sleep"):
                    return parse_pdf_via_api(source, output, settings,
                                              page_ranges=page_ranges, http_client=client)

            full = run(root / "result-full", None)
            self.assertEqual(len(seen), 5)
            self.assertNotIn("page_ranges", submitted[-1]["files"][0])
            self.assertEqual(Path(full["markdown_files"][0]).read_text(encoding="utf-8"),
                             "every = all = each ≤ most")
            self.assertEqual(Path(full["json_files"][0]).name, "layout.json")
            self.assertTrue((root / "result-full/paper/images/formula.png").is_file())
            self.assertTrue((root / "result-full/result.zip").is_file())
            paged = run(root / "result-paged", "3")
            self.assertEqual(len(seen), 5)
            self.assertEqual(submitted[-1]["files"], [
                {"name": "paper.pdf", "is_ocr": True, "page_ranges": "3"}])
            self.assertEqual(Path(paged["markdown_files"][0]).read_text(encoding="utf-8"),
                             "every = all = each ≤ most")

    def test_api_layout_adapter_keeps_normalized_bboxes_and_records_page_sizes(self):
        from paper_assistant.mineru_parser import add_page_dimensions, api_parser_profile, structure_units

        middle = {"schema": "docvortex.middle", "schema_version": "2.0",
                  "metadata": {"file_suffix": "pdf", "producer": {"name": "mineru", "version": "3.4.4"}},
                  "extensions": {"mineru": {"tier": "basic", "parse_mode": "ocr"}, "kept": {"value": 1}},
                  "pages": [{"page_idx": 0, "blocks": [{
                      "type": "text", "index": 0, "bbox": [0.1, 0.2, 0.3, 0.4],
                      "content": [{"type": "text", "content": "every = all = each ≤ most"}]}]}]}
        layout = {"_backend": "hybrid", "_effort": "medium", "_ocr_enable": True, "_version_name": "3.4.4",
                  "pdf_info": [{"page_idx": 0, "page_size": [595, 842]}]}
        plotted = add_page_dimensions(deepcopy(middle), layout)
        self.assertEqual(plotted["pages"][0]["blocks"][0]["bbox"], [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(plotted["extensions"]["kept"], {"value": 1})
        self.assertEqual(plotted["extensions"]["docvortex_layout"]["pages"],
                         [{"page_idx": 0, "width_pt": 595, "height_pt": 842}])
        unit = structure_units(plotted)[0]
        self.assertEqual(unit["page_size"], [595, 842])
        self.assertEqual(unit["bbox"], [0.1, 0.2, 0.3, 0.4])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "layout.json"
            path.write_text(json.dumps(layout), encoding="utf-8")
            profile = api_parser_profile(path)
        self.assertEqual(profile["name"], "mineru-api")
        self.assertEqual(profile["version"], "3.4.4")
        self.assertEqual(profile["ocr_mode"], "ocr")
        self.assertEqual((profile["backend"], profile["effort"]), ("hybrid", "medium"))
        self.assertNotIn(profile["tier"], {"standard", "advanced"})
        self.assertNotEqual(profile["ocr_mode"], "auto")

    def test_missing_token_and_api_failures_do_not_claim_success_or_resubmit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env"
            env.write_text("MINERU_API_TOKEN=\n", encoding="utf-8")
            with patch.object(config, "ENV_FILE", env), self.assertRaises(ConfigError):
                config.load_mineru_api_settings()
            source = root / "paper.pdf"
            source.write_bytes(b"%PDF-1.7\noffline-upload")
            settings = MinerUAPISettings("offline-token")
            for status, response in ((401, {}), (200, {"code": "A0202", "msg": "offline-token invalid"})):
                with self.subTest(status=status):
                    calls = []
                    def reject(request):
                        calls.append(request)
                        return httpx.Response(status, json=response)
                    with httpx.Client(transport=httpx.MockTransport(reject)) as client, \
                            self.assertRaises(MinerUAPIError) as caught:
                        parse_pdf_via_api(source, root / "failed", settings, http_client=client)
                    self.assertEqual(len(calls), 1)
                    self.assertNotIn("offline-token", str(caught.exception))
                    self.assertFalse((root / "failed").exists())


if __name__ == "__main__":
    unittest.main()
