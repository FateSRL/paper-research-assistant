"""D3 任务 C：arXiv 元数据查询与选定版本的 PDF 下载。

这里只使用 HTTP + Atom XML，不调用聊天/embedding API，不读取 .env。
搜索结果是候选论文信息；只有明确选择版本后，才调用 download_pdf()。
查询失败或下载失败不影响已有 data/papers 中的本地论文。
"""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx
import pymupdf


API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
NS = {"atom": ATOM_NS, "os": "http://a9.com/-/spec/opensearch/1.1/"}
OFFICIAL_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
API_DELAY_SECONDS = 3.0
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_FALLBACK = (
    "可继续使用 data/papers 中已有的本地 PDF："
    "python -X utf8 -m scripts.parse_pdfs --corpus eval/corpus.json "
    "--output-dir data/parsed。此次失败不会改动语料清单或开发题。"
)

# 新式编号如 2210.03629；旧式编号如 hep-th/9901001。版本不能为 v0。
ID_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})"
ID_RE = re.compile(rf"(?P<id>{ID_PATTERN})(?P<version>v[1-9]\d*)?")
_NETWORK_LOCK = threading.RLock()


class ArxivError(Exception):
    """携带可记录的失败状态；不能把网络错误包装成搜索无结果。"""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def split_arxiv_id(value: str, *, require_version: bool = False) -> tuple[str, str | None]:
    """拆出裸编号与版本，拒绝 URL、路径及没有明确版本的下载输入。"""

    value = value.strip()
    if value.startswith("arxiv_"):
        value = value[len("arxiv_"):]
        # 项目 paper_id 把旧式编号中的 / 编成 _，这里恢复这个分隔符。
        # 普通裸编号仍要求写 hep-th/9901001v1，不猜测任意下划线含义。
        if re.fullmatch(r"[a-z][a-z0-9.-]*_\d{7}(?:v[1-9]\d*)?", value):
            value = value.replace("_", "/", 1)
    match = ID_RE.fullmatch(value)
    if match is None:
        raise ArxivError("invalid_id", "arXiv 编号格式错误，例如应写 2210.03629v3。")
    version = match.group("version")
    if require_version and version is None:
        raise ArxivError("version_required", "下载必须指定版本，例如 2210.03629v3；不能默认为最新版。")
    return match.group("id"), version


def official_https_url(value: str, *, allow_http_metadata: bool = False) -> str:
    """核对协议、完整主机名、端口和认证部分，不接受伪后缀域名。

    官方 Atom 示例中的链接仍有 http；只有解析元数据时可以将其升级
    为同一官方域名的 https。真正发请求和跟随重定向时只允许 https。
    """

    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as error:
        raise ArxivError("unsafe_url", "链接端口无效。") from error
    allowed_schemes = {"https", "http"} if allow_http_metadata else {"https"}
    if (parts.scheme not in allowed_schemes or parts.hostname not in OFFICIAL_HOSTS
            or parts.username is not None or parts.password is not None
            or port not in (None, 443) or parts.fragment):
        raise ArxivError("unsafe_url", "只允许无认证信息的 arXiv 官方 HTTPS 链接。")
    return urlunsplit(("https", parts.hostname, parts.path, parts.query, ""))


def _id_from_url(value: str, expected_prefix: str, *, require_version: bool = True) -> tuple[str, str | None]:
    safe_url = official_https_url(value, allow_http_metadata=True)
    parts = urlsplit(safe_url)
    if parts.query or not parts.path.startswith(expected_prefix):
        raise ArxivError("invalid_metadata", "Atom 返回的论文链接路径不符合预期。")
    identifier = parts.path[len(expected_prefix):]
    if expected_prefix == "/pdf/" and identifier.endswith(".pdf"):
        identifier = identifier[:-4]
    return split_arxiv_id(identifier, require_version=require_version)


def validate_pdf_url(value: str, selected_id: str) -> str:
    """每一跳都必须仍指向用户选中的版本，不能跳到其他网站或最新版。"""

    safe_url = official_https_url(value)
    actual = _id_from_url(safe_url, "/pdf/")
    expected = split_arxiv_id(selected_id, require_version=True)
    if actual != expected:
        raise ArxivError("version_mismatch", "PDF 链接指向的论文/版本与所选版本不同。")
    return safe_url


def parse_atom_feed(xml_bytes: bytes) -> dict:
    """使用标准库解析带命名空间的 Atom，返回供人选择的元数据。

    XML 的默认命名空间不能忽略：entry 的真实标签含有 Atom 命名空间。
    HTTP 200 的内容也可能是 arXiv 的错误 entry，因此须先识别错误。
    """

    if len(xml_bytes) > MAX_XML_BYTES:
        raise ArxivError("response_too_large", "元数据响应超过 2 MiB 上限。")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", xml_bytes, re.IGNORECASE):
        raise ArxivError("invalid_xml", "不接受包含 DTD/实体声明的 XML。")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise ArxivError("invalid_xml", "响应不是有效的 Atom XML。") from error
    if root.tag != f"{{{ATOM_NS}}}feed":
        raise ArxivError("invalid_xml", "响应缺少 Atom feed 根节点。")

    def text(node: ET.Element, field: str) -> str:
        # 这里只整理元数据空白；不用于清洗论文原始逐页文本。
        return " ".join((node.findtext(field, default="", namespaces=NS) or "").split())

    papers = []
    for entry in root.findall("atom:entry", NS):
        entry_id = text(entry, "atom:id")
        if "/api/errors" in entry_id or text(entry, "atom:title").lower() == "error":
            message = text(entry, "atom:summary")[:300] or "arXiv 返回 API 错误。"
            raise ArxivError("api_error", message)
        arxiv_id, version = _id_from_url(entry_id, "/abs/")
        title = text(entry, "atom:title")
        abstract = text(entry, "atom:summary")
        authors = [text(author, "atom:name") for author in entry.findall("atom:author", NS)]
        if not title or not abstract or not authors or any(not author for author in authors):
            raise ArxivError("invalid_metadata", "论文元数据缺少标题、摘要或作者。")
        versioned_id = f"{arxiv_id}{version}"
        # 元数据中的外部 DOI/期刊链接不用于 PDF 下载；只识别 PDF link。
        pdf_links = [link.get("href", "") for link in entry.findall("atom:link", NS)
                     if link.get("title") == "pdf" or link.get("type") == "application/pdf"]
        if not pdf_links:
            raise ArxivError("invalid_metadata", "论文元数据缺少 PDF 链接。")
        linked_id, linked_version = _id_from_url(pdf_links[0], "/pdf/", require_version=False)
        if linked_id != arxiv_id or linked_version not in (None, version):
            raise ArxivError("version_mismatch", "元数据的 PDF 链接与 entry 的论文/版本不同。")
        # 某些合法 feed 的 PDF href 没写版本，不能因此误判整个结果无效；
        # 也不能直接下载这个“最新版”链接。以 entry 的明确版本构造固定 URL。
        pdf_url = validate_pdf_url(f"https://arxiv.org/pdf/{versioned_id}", versioned_id)
        papers.append({
            "arxiv_id": arxiv_id,
            "arxiv_version": version,
            "paper_id": f"arxiv_{versioned_id.replace('/', '_')}",
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "source_url": f"https://arxiv.org/abs/{versioned_id}",
            "pdf_url": pdf_url,
        })
    total_text = root.findtext("os:totalResults", namespaces=NS)
    try:
        total_results = int(total_text) if total_text is not None else len(papers)
        if total_results < 0:
            raise ValueError
    except ValueError as error:
        raise ArxivError("invalid_metadata", "搜索结果总数无效。") from error
    return {"total_results": total_results, "papers": papers}


@contextmanager
def request_slot(rate_dir: Path):
    """本机 CLI 共用的请求闸门：单连接、相邻请求至少间隔三秒。

    线程锁约束同一进程；独占 lock 文件约束共用目录的多个 CLI 进程。
    锁覆盖整个响应读取，避免前一请求还没读完就开启下一连接。
    这不能协调另一台机器，使用者仍须避免多机同时抓取。
    崩溃遗留锁会明确报 busy，而不会自动删除另一个进程的锁。
    """

    rate_dir.mkdir(parents=True, exist_ok=True)
    lock_path = rate_dir / ".request.lock"
    state_path = rate_dir / "request_rate_state.json"
    with _NETWORK_LOCK:
        deadline = time.monotonic() + 30
        while True:
            try:
                lock_handle = lock_path.open("x", encoding="utf-8")
                lock_handle.write(str(os.getpid()))
                lock_handle.close()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ArxivError("busy", "arXiv 请求锁被占用；确认没有其他运行进程后检查遗留锁。")
                time.sleep(0.1)
        try:
            previous = 0.0
            if state_path.exists():
                previous = float(json.loads(state_path.read_text(encoding="utf-8"))["last_started"])
            delay = min(API_DELAY_SECONDS, max(0.0, API_DELAY_SECONDS - (time.time() - previous)))
            if delay:
                time.sleep(delay)
            state_path.write_text(json.dumps({"last_started": time.time()}), encoding="utf-8")
            yield
        finally:
            lock_path.unlink(missing_ok=True)


def verify_pdf_file(path: Path, selected_id: str, *, max_bytes: int = MAX_PDF_BYTES) -> dict:
    """PDF 头是初筛；实际打开、页数和首页版本标识才构成下载检查。

    固定版本标识缺失时明确失败，不能凭下载文件名猜版本。
    此处检查文件有效性，不表示公式、图表或阅读顺序质量通过。
    """

    expected = split_arxiv_id(selected_id, require_version=True)
    # 复用已有文件也须执行体积限制，避免绕过流式下载时的上限。
    file_size = path.stat().st_size
    if file_size > max_bytes:
        raise ArxivError("response_too_large", "待验证 PDF 文件超过体积上限。")
    with path.open("rb") as handle:
        if not handle.read(8).startswith(b"%PDF-"):
            raise ArxivError("invalid_pdf", "下载内容缺少 PDF 文件头，可能是 HTML 错误页。")
    try:
        # 用有限体积的文件字节进行验证。Windows 下某些损坏 PDF 在
        # 解析器构造失败时可能遗留文件句柄；内存输入不锁住临时文件，
        # 因而失败后仍能清理 .part。网络下载本身仍采用流式写入。
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass or document.page_count < 1:
                raise ArxivError("invalid_pdf", "下载文件不是可直接打开的非空 PDF。")
            page_count = document.page_count
            first_page_text = document[0].get_text("text")
    except ArxivError:
        raise
    except Exception as error:
        raise ArxivError("invalid_pdf", "下载文件无法被 PDF 解析器打开。") from error
    marker = re.search(rf"arXiv:\s*({ID_PATTERN}v[1-9]\d*)", first_page_text, re.IGNORECASE)
    if marker is None:
        raise ArxivError("version_unverified", "PDF 首页没有可提取的 arXiv 版本标识，需要人工核对。")
    if split_arxiv_id(marker.group(1), require_version=True) != expected:
        raise ArxivError("version_mismatch", "PDF 首页标识与选定的论文版本不同。")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return {"page_count": page_count, "pdf_sha256": digest.hexdigest(),
            "verified_arxiv_id": marker.group(1), "file_size_bytes": file_size}


class ArxivClient:
    """同步客户端；不自动重试，不并发搜索，也不自动下载所有候选。"""

    def __init__(self, *, rate_dir: Path, cache_dir: Path | None = None,
                 timeout_seconds: float = 20, http_client: httpx.Client | None = None):
        if not 0 < timeout_seconds <= 60:
            raise ArxivError("invalid_input", "超时须大于 0，且不超过 60 秒。")
        self.rate_dir = Path(rate_dir)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.request_count = 0
        self.owns_client = http_client is None
        self.client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False,
            headers={"User-Agent": "paper-research-assistant-study/0.1"},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.owns_client:
            self.client.close()

    def _transfer(self, url: str, sink, *, byte_limit: int, validator, params=None) -> dict:
        """边读边计数，拒绝超限响应；每次重定向都重新校验并经过闸门。"""

        redirects = []
        started = time.monotonic()
        for hop in range(4):
            url = validator(url)
            try:
                with request_slot(self.rate_dir):
                    self.request_count += 1
                    with self.client.stream("GET", url, params=params, follow_redirects=False) as response:
                        if response.is_redirect:
                            if hop == 3 or "location" not in response.headers:
                                raise ArxivError("redirect_error", "重定向超过三次或缺少目标地址。")
                            destination = validator(urljoin(str(response.url), response.headers["location"]))
                            redirects.append({"from": str(response.url), "to": destination})
                            url, params = destination, None
                            continue
                        if response.status_code != 200:
                            raise ArxivError("http_error", f"arXiv 返回 HTTP {response.status_code}；不自动重试。")
                        declared = response.headers.get("content-length")
                        if declared is not None:
                            try:
                                declared_size = int(declared)
                            except ValueError as error:
                                raise ArxivError("invalid_response", "Content-Length 不是整数。") from error
                            if declared_size < 0 or declared_size > byte_limit:
                                raise ArxivError("response_too_large", "响应声明的文件大小超过上限。")
                        size = 0
                        for chunk in response.iter_bytes(chunk_size=65536):
                            size += len(chunk)
                            if size > byte_limit:
                                raise ArxivError("response_too_large", "实际响应大小超过上限，已停止下载。")
                            if time.monotonic() - started > 60:
                                raise ArxivError("timeout", "整体响应读取超过 60 秒，已停止。")
                            sink(chunk)
                        if declared is not None and not response.headers.get("content-encoding") and size != int(declared):
                            raise ArxivError("incomplete_response", "实际字节数与 Content-Length 不一致。")
                        return {"final_url": str(response.url), "bytes_received": size, "redirects": redirects}
            except httpx.TimeoutException as error:
                raise ArxivError("timeout", f"arXiv 请求超时（{type(error).__name__}），未自动重试。") from error
            except httpx.HTTPError as error:
                raise ArxivError("network_error", f"arXiv 请求失败（{type(error).__name__}），未自动重试。") from error
        raise ArxivError("redirect_error", "重定向无法完成。")

    def search(self, *, query: str | None = None, id_list: list[str] | None = None,
               max_results: int = 3) -> dict:
        """查询少量候选；同参数成功响应缓存一天，避免重复联网。

        指定 id_list 可核对固定版本；query 与 id_list 二选一，避免初学者
        无意触发 API 的“在指定 ID 中过滤搜索词”规则。
        """

        started_request_count = self.request_count
        if bool(query and query.strip()) == bool(id_list):
            raise ArxivError("invalid_input", "query 和 id_list 必须且只能提供一种。")
        if type(max_results) is not int or not 1 <= max_results <= 10:
            raise ArxivError("invalid_input", "本学习项目每次只查询 1–10 条候选。")
        expected_ids = []
        params = {"start": 0, "max_results": max_results}
        if id_list:
            if len(id_list) > max_results:
                raise ArxivError("invalid_input", "id_list 数量不能超过 max_results。")
            expected_ids = [split_arxiv_id(value) for value in id_list]
            params["id_list"] = ",".join(f"{bare}{version or ''}" for bare, version in expected_ids)
        else:
            params["search_query"] = query.strip()
        cache_key = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.xml" if self.cache_dir is not None else None
        cache_hit = bool(cache_path and cache_path.is_file() and 0 <= time.time() - cache_path.stat().st_mtime < 86400)
        transport = None
        if cache_hit:
            body = cache_path.read_bytes()
        else:
            buffer = io.BytesIO()
            def validate_api_url(value: str) -> str:
                safe = official_https_url(value)
                if urlsplit(safe).path != "/api/query":
                    raise ArxivError("unsafe_url", "元数据请求只能转到官方 /api/query。")
                return safe
            transport = self._transfer(API_URL, buffer.write, byte_limit=MAX_XML_BYTES,
                                       validator=validate_api_url, params=params)
            body = buffer.getvalue()
        result = parse_atom_feed(body)
        for bare, version in expected_ids:
            matches = [paper for paper in result["papers"] if paper["arxiv_id"] == bare
                       and (version is None or paper["arxiv_version"] == version)]
            if not matches:
                raise ArxivError("metadata_missing", "API 未返回要求的论文版本；不能以其他版本替代。")
        if cache_path is not None and not cache_hit:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            # 一次完整成功响应才进入缓存；API 错误和不完整 XML 不缓存。
            # 临时写完再替换缓存，另一个 CLI 不会读到半份 XML。
            temporary_cache = None
            try:
                with tempfile.NamedTemporaryFile("wb", dir=cache_path.parent, suffix=".part", delete=False) as handle:
                    temporary_cache = Path(handle.name)
                    handle.write(body)
                os.replace(temporary_cache, cache_path)
                temporary_cache = None
            finally:
                if temporary_cache is not None:
                    temporary_cache.unlink(missing_ok=True)
        return {"status": "success" if result["papers"] else "no_results", **result,
                "request_params": params, "cache_hit": cache_hit, "transport": transport,
                "network_request_count": self.request_count - started_request_count}

    def download_pdf(self, selected_id: str, output_dir: Path,
                     *, max_bytes: int = MAX_PDF_BYTES) -> dict:
        """只下载所选固定版本，验证临时文件后原子完成；拒绝覆盖固定语料。"""

        started_request_count = self.request_count
        bare, version = split_arxiv_id(selected_id, require_version=True)
        selected_id = f"{bare}{version}"
        if type(max_bytes) is not int or not 1 <= max_bytes <= 50 * 1024 * 1024:
            raise ArxivError("invalid_input", "PDF 体积上限须在 1 字节至 50 MiB 之间。")
        output_dir = Path(output_dir).resolve()
        protected_dir = (PROJECT_ROOT / "data" / "papers").resolve()
        if output_dir.is_relative_to(protected_dir):
            raise ArxivError("protected_corpus", "下载验收不能写入 data/papers；请使用 archive/run_outputs/download_checks。")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{selected_id.replace('/', '_')}.pdf"
        paper_id = f"arxiv_{selected_id.replace('/', '_')}"
        url = f"https://arxiv.org/pdf/{selected_id}"
        if target.exists():
            # 已有同名文件只验证复用，不覆盖，不为了验收反复请求。
            return {"status": "existing_verified", "paper_id": paper_id, "arxiv_id": bare,
                    "arxiv_version": version, "source_url": f"https://arxiv.org/abs/{selected_id}",
                    "pdf_url": url, "local_path": str(target), **verify_pdf_file(target, selected_id, max_bytes=max_bytes),
                    "network_request_count": self.request_count - started_request_count}
        temporary = None
        try:
            # NamedTemporaryFile 放在目标目录，确保最后完成时不跨磁盘。
            # Windows 下先关闭文件，再交给 PDF 解析器读取。
            with tempfile.NamedTemporaryFile("wb", dir=output_dir, suffix=".part", delete=False) as handle:
                temporary = Path(handle.name)
                transport = self._transfer(url, handle.write, byte_limit=max_bytes,
                                           validator=lambda value: validate_pdf_url(value, selected_id))
                handle.flush()
                os.fsync(handle.fileno())
            verification = verify_pdf_file(temporary, selected_id, max_bytes=max_bytes)
            # 原子建立最终名称。link 会在目标已存在时失败，不会覆盖它；
            # 这比“先 exists 再 replace”更能避免两个进程同时完成的竞争。
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise ArxivError("destination_exists", "下载过程中目标文件出现，已拒绝覆盖。") from error
            temporary.unlink()
            temporary = None
            return {"status": "success", "paper_id": paper_id, "arxiv_id": bare,
                    "arxiv_version": version, "source_url": f"https://arxiv.org/abs/{selected_id}",
                    "pdf_url": url, "local_path": str(target), **verification,
                    "transport": transport, "network_request_count": self.request_count - started_request_count}
        finally:
            # 网络/验证失败也清理本次临时文件，不能留下可被误用的半份 PDF。
            if temporary is not None:
                temporary.unlink(missing_ok=True)
