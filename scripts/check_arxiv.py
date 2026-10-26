"""任务 C 的离线边界检查：MockTransport 不访问 arXiv 或任何模型服务。

测试使用真正的小 PDF 字节和假的 HTTP 响应，检查失败不会留下最终文件。
它们检验程序边界，不代表真实联网搜索/下载已经成功。
"""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
import pymupdf

from paper_assistant import arxiv_client as arxiv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTED_ID = "2210.03629v3"


def atom_xml(identifier=SELECTED_ID, *, pdf_url=None) -> bytes:
    """构造与官方 Atom 格式一致的小样本；不复制真实查询来冒充联网记录。"""

    pdf_url = pdf_url or f"http://arxiv.org/pdf/{identifier}"
    return f'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>1</opensearch:totalResults>
      <entry>
        <id>http://arxiv.org/abs/{identifier}</id>
        <title> ReAct: Test\n Metadata </title>
        <summary> An abstract with\n multiple lines. </summary>
        <author><name> Author A </name></author>
        <author><name>Author B</name></author>
        <link title="pdf" type="application/pdf" href="{pdf_url}"/>
      </entry>
    </feed>'''.encode("utf-8")


def small_pdf(identifier=SELECTED_ID) -> bytes:
    """生成可被 PyMuPDF 真正打开的 PDF，首页有测试用版本标记。"""

    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), f"arXiv:{identifier}\nOffline boundary test PDF")
        return document.tobytes()


class BrokenStream(httpx.SyncByteStream):
    """模拟连接建立后，读取过程中断；不同于下载前的连接超时。"""

    def __iter__(self):
        yield b"%PDF-1.7\npartial"
        raise httpx.ReadError("simulated interrupted stream")


class ArxivBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf_bytes = small_pdf()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        # 大部分测试只检查业务边界，跳过实际三秒等待；请求闸门另测。
        self.gate_patch = patch.object(arxiv, "request_slot", side_effect=lambda _: nullcontext())
        self.gate_patch.start()
        self.addCleanup(self.gate_patch.stop)

    def client(self, handler, *, cache=False):
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        self.addCleanup(http_client.close)
        return arxiv.ArxivClient(rate_dir=self.root / "rate", http_client=http_client,
                                 cache_dir=self.root / "cache" if cache else None)

    def assert_download_fails(self, handler, status, *, max_bytes=arxiv.MAX_PDF_BYTES):
        client = self.client(handler)
        output = self.root / "downloads"
        with self.assertRaises(arxiv.ArxivError) as caught:
            client.download_pdf(SELECTED_ID, output, max_bytes=max_bytes)
        self.assertEqual(caught.exception.status, status)
        self.assertFalse((output / f"{SELECTED_ID}.pdf").exists())
        self.assertEqual(list(output.glob("*.part")), [])

    def test_atom_namespace_authors_version_and_whitespace(self):
        paper = arxiv.parse_atom_feed(atom_xml())["papers"][0]
        self.assertEqual(paper["arxiv_id"], "2210.03629")
        self.assertEqual(paper["arxiv_version"], "v3")
        self.assertEqual(paper["paper_id"], "arxiv_2210.03629v3")
        self.assertEqual(paper["title"], "ReAct: Test Metadata")
        self.assertEqual(paper["authors"], ["Author A", "Author B"])
        self.assertEqual(paper["abstract"], "An abstract with multiple lines.")
        self.assertEqual(paper["pdf_url"], f"https://arxiv.org/pdf/{SELECTED_ID}")

    def test_empty_feed_is_no_results_not_network_error(self):
        empty = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
        client = self.client(lambda request: httpx.Response(200, content=empty))
        result = client.search(query="all:missing", max_results=1)
        self.assertEqual(result["status"], "no_results")
        self.assertEqual(result["papers"], [])

    def test_keyword_query_is_encoded_as_parameters_not_manual_url_text(self):
        query = 'all:"retrieval augmented generation"'
        def handler(request):
            self.assertEqual(request.url.params["search_query"], query)
            self.assertEqual(request.url.params["max_results"], "2")
            self.assertEqual(request.url.params["start"], "0")
            self.assertEqual(request.url.scheme, "https")
            self.assertNotIn("id_list", request.url.params)
            return httpx.Response(200, content=atom_xml())
        client = self.client(handler)
        result = client.search(query=query, max_results=2)
        self.assertEqual(result["status"], "success")

    def test_unversioned_pdf_link_is_fixed_by_explicit_entry_version(self):
        paper = arxiv.parse_atom_feed(atom_xml(pdf_url="http://arxiv.org/pdf/2210.03629"))["papers"][0]
        self.assertEqual(paper["pdf_url"], "https://arxiv.org/pdf/2210.03629v3")
        self.assertEqual(paper["arxiv_version"], "v3")

    def test_legacy_paper_id_round_trips_without_losing_version(self):
        paper = arxiv.parse_atom_feed(atom_xml("hep-th/9901001v2"))["papers"][0]
        self.assertEqual(paper["paper_id"], "arxiv_hep-th_9901001v2")
        self.assertEqual(arxiv.split_arxiv_id(paper["paper_id"], require_version=True),
                         ("hep-th/9901001", "v2"))

    def test_http_200_api_error_entry_is_rejected(self):
        body = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>http://arxiv.org/api/errors#incorrect_id_format</id>
          <title>Error</title><summary>incorrect id format</summary></entry></feed>'''
        client = self.client(lambda request: httpx.Response(200, content=body))
        with self.assertRaises(arxiv.ArxivError) as caught:
            client.search(id_list=[SELECTED_ID])
        self.assertEqual(caught.exception.status, "api_error")

    def test_malformed_xml_wrong_namespace_and_doctype_rejected(self):
        for body in [b"<feed", b"<feed/>", b'<!DOCTYPE feed><feed xmlns="http://www.w3.org/2005/Atom"/>']:
            with self.subTest(body=body):
                with self.assertRaises(arxiv.ArxivError) as caught:
                    arxiv.parse_atom_feed(body)
                self.assertEqual(caught.exception.status, "invalid_xml")

    def test_download_requires_real_version_before_request(self):
        client = self.client(lambda request: self.fail("invalid input must not make a request"))
        for identifier in ["2210.03629", "2210.03629v0", "../2210.03629v3", "https://arxiv.org/pdf/2210.03629v3"]:
            with self.subTest(identifier=identifier), self.assertRaises(arxiv.ArxivError):
                client.download_pdf(identifier, self.root / "downloads")
        self.assertEqual(client.request_count, 0)

    def test_requested_metadata_version_cannot_be_silently_changed(self):
        client = self.client(lambda request: httpx.Response(200, content=atom_xml("2210.03629v2")))
        with self.assertRaises(arxiv.ArxivError) as caught:
            client.search(id_list=[SELECTED_ID])
        self.assertEqual(caught.exception.status, "metadata_missing")

    def test_metadata_pdf_link_must_match_official_version(self):
        for pdf_url in ["https://example.com/test.pdf", "https://arxiv.org/pdf/2210.03629v2"]:
            with self.subTest(pdf_url=pdf_url), self.assertRaises(arxiv.ArxivError):
                arxiv.parse_atom_feed(atom_xml(pdf_url=pdf_url))

    def test_url_blocks_http_external_userinfo_and_port(self):
        urls = ["http://arxiv.org/pdf/2210.03629v3", "https://arxiv.org.evil.test/pdf/2210.03629v3",
                "https://arxiv.org@evil.test/pdf/2210.03629v3", "https://user@arxiv.org/pdf/2210.03629v3",
                "https://arxiv.org:444/pdf/2210.03629v3"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(arxiv.ArxivError):
                arxiv.validate_pdf_url(url, SELECTED_ID)

    def test_redirect_to_external_http_or_wrong_version_is_rejected(self):
        for location, status in [("https://example.com/test.pdf", "unsafe_url"),
                                 ("http://arxiv.org/pdf/2210.03629v3", "unsafe_url"),
                                 ("https://arxiv.org/pdf/2210.03629v2", "version_mismatch")]:
            with self.subTest(location=location):
                self.assert_download_fails(lambda request: httpx.Response(302, headers={"location": location}), status)

    def test_redirect_loop_has_finite_limit(self):
        self.assert_download_fails(lambda request: httpx.Response(302, headers={"location": str(request.url)}),
                                   "redirect_error")

    def test_allowed_redirect_download_verifies_real_pdf_hash_and_page(self):
        def handler(request):
            if not request.url.path.endswith(".pdf"):
                return httpx.Response(302, headers={"location": f"/pdf/{SELECTED_ID}.pdf"})
            return httpx.Response(200, content=self.pdf_bytes)
        client = self.client(handler)
        result = client.download_pdf(SELECTED_ID, self.root / "downloads")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["verified_arxiv_id"], SELECTED_ID)
        self.assertEqual(result["pdf_sha256"], hashlib.sha256(self.pdf_bytes).hexdigest())
        self.assertEqual(client.request_count, 2)

    def test_html_or_broken_pdf_cannot_form_final_file(self):
        for body in [b"<html>blocked</html>", b"%PDF-1.7\nnot a document"]:
            with self.subTest(body=body):
                self.assert_download_fails(lambda request: httpx.Response(200, content=body,
                                           headers={"content-type": "application/pdf"}), "invalid_pdf")

    def test_actual_pdf_version_mismatch_is_rejected(self):
        wrong = small_pdf("2210.03629v2")
        self.assert_download_fails(lambda request: httpx.Response(200, content=wrong), "version_mismatch")

    def test_pdf_without_extractable_version_requires_review(self):
        body = small_pdf("not-a-version")
        self.assert_download_fails(lambda request: httpx.Response(200, content=body), "version_unverified")

    def test_declared_and_actual_size_limits_both_enforced(self):
        self.assert_download_fails(lambda request: httpx.Response(200, content=self.pdf_bytes),
                                   "response_too_large", max_bytes=10)
        self.assert_download_fails(lambda request: httpx.Response(200, stream=httpx.ByteStream(self.pdf_bytes)),
                                   "response_too_large", max_bytes=10)

    def test_mismatched_declared_length_is_incomplete(self):
        self.assert_download_fails(lambda request: httpx.Response(200, stream=httpx.ByteStream(self.pdf_bytes),
                                  headers={"content-length": str(len(self.pdf_bytes) + 1)}), "incomplete_response")

    def test_http_error_timeout_and_interrupted_stream_clean_up(self):
        self.assert_download_fails(lambda request: httpx.Response(503), "http_error")
        def timeout(request):
            raise httpx.ConnectTimeout("simulated timeout", request=request)
        self.assert_download_fails(timeout, "timeout")
        self.assert_download_fails(lambda request: httpx.Response(200, stream=BrokenStream()), "network_error")

    def test_existing_verified_file_is_reused_without_network(self):
        output = self.root / "downloads"
        output.mkdir()
        target = output / f"{SELECTED_ID}.pdf"
        target.write_bytes(self.pdf_bytes)
        client = self.client(lambda request: self.fail("existing verified file should not be downloaded"))
        result = client.download_pdf(SELECTED_ID, output)
        self.assertEqual(result["status"], "existing_verified")
        self.assertEqual(target.read_bytes(), self.pdf_bytes)
        self.assertEqual(client.request_count, 0)

    def test_fixed_corpus_directory_is_protected_before_network(self):
        client = self.client(lambda request: self.fail("fixed corpus must not be requested"))
        with self.assertRaises(arxiv.ArxivError) as caught:
            client.download_pdf(SELECTED_ID, PROJECT_ROOT / "data" / "papers")
        self.assertEqual(caught.exception.status, "protected_corpus")
        self.assertEqual(client.request_count, 0)

    def test_existing_file_cannot_bypass_size_limit_or_be_overwritten(self):
        output = self.root / "downloads"
        output.mkdir()
        target = output / f"{SELECTED_ID}.pdf"
        target.write_bytes(self.pdf_bytes)
        client = self.client(lambda request: self.fail("existing oversized file must not trigger a request"))
        with self.assertRaises(arxiv.ArxivError) as caught:
            client.download_pdf(SELECTED_ID, output, max_bytes=10)
        self.assertEqual(caught.exception.status, "response_too_large")
        self.assertEqual(target.read_bytes(), self.pdf_bytes)

    def test_successful_query_is_cached_without_second_network_request(self):
        client = self.client(lambda request: httpx.Response(200, content=atom_xml()), cache=True)
        first = client.search(id_list=[SELECTED_ID])
        second = client.search(id_list=[SELECTED_ID])
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["network_request_count"], 1)
        self.assertEqual(second["network_request_count"], 0)
        self.assertEqual(client.request_count, 1)

    def test_request_gate_serializes_and_waits_three_seconds(self):
        # 独立验证真正的闸门；假时钟使测试不用真实睡眠。
        self.gate_patch.stop()
        clock = [1000.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        with patch.object(arxiv.time, "time", side_effect=lambda: clock[0]), \
                patch.object(arxiv.time, "sleep", side_effect=sleep):
            with arxiv.request_slot(self.root / "rate"):
                self.assertTrue((self.root / "rate" / ".request.lock").exists())
            with arxiv.request_slot(self.root / "rate"):
                self.assertTrue((self.root / "rate" / ".request.lock").exists())
        self.assertEqual(sleeps, [3.0])
        state = json.loads((self.root / "rate" / "request_rate_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["last_started"], 1003.0)
        self.assertFalse((self.root / "rate" / ".request.lock").exists())


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
