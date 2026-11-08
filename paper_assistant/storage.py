"""D4 任务 C/D：保存不可覆盖的论文分块，以及可重试的向量导入状态。

SQLite 保存原文和来源；它不生成 embedding，也不自行检查 Qdrant。
任务 D 在完成外部向量核对后，才通过本模块将对应导入状态写为 ready。
这里仅使用 Python 自带的 sqlite3，导入模块不会读 .env 或发起网络请求。
文件快照的完整校验由上层 loader 负责，本层仍检查字段、指纹和分块内容，
避免另一位调用者绕过 loader，直接把不一致的对象塞入数据库。
"""

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
import sqlite3
import threading

from paper_assistant.schemas import EvidenceRef


SCHEMA_VERSION = 2
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PAPER_FIELDS = (
    "paper_id", "arxiv_version", "title", "source_url", "local_path",
    "pdf_sha256", "page_count", "text_selectable",
)
CHUNK_FIELDS = (
    "chunk_id", "paper_id", "parse_revision", "pdf_sha256", "pdf_page",
    "segment_id", "char_start", "char_end", "text", "text_sha256",
    "filter_revision", "source_block_index", "source_line_indices", "segment_bbox",
)
STRUCTURED_CHUNK_FIELDS = (
    "chunk_id", "paper_id", "parse_revision", "pdf_sha256", "pdf_page", "text", "text_sha256",
    "parent_id", "section_path", "content_type", "source_spans", "token_count",
)


class StorageError(ValueError):
    """输入、数据库结构或保存内容不合法，不能继续导入或回查。"""


class StorageConflict(StorageError):
    """同一标识已有不同内容，拒绝覆盖、补洞或伪装成重复导入成功。"""


@dataclass(frozen=True)
class StoredVersionInput:
    """上层完成文件校验后，交给数据库的一篇完整版本。

    snapshot_path 是项目相对路径，manifest_sha256 是清单文件准确字节的哈希。
    frozen=True 防止替换属性；内部字典和列表仍会在导入时复制后重新检查。
    """

    paper: dict
    manifest: dict
    chunks: list[dict]
    snapshot_path: str
    manifest_sha256: str
    parents: list[dict] = field(default_factory=list)


def _canonical(value: object) -> str:
    """相同对象固定成同一 JSON；保留原文中的空白、换行和 Unicode。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise StorageError("记录必须能表示为有限值 JSON") from error


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonempty(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StorageError(f"{description} 必须是非空字符串")
    return value


def _sha(value: object, description: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise StorageError(f"{description} 必须是完整的小写 SHA-256")
    return value


def _positive(value: object, description: str) -> int:
    if type(value) is not int or value <= 0:
        raise StorageError(f"{description} 必须是正整数")
    return value


def index_import_key(paper_id: str, parse_revision: str, index_profile_id: str) -> str:
    """由论文、处理版本和索引配置确定唯一导入键，不使用时间或随机数。

    同一组输入失败后重试仍得到同一个键，因此只更新原来的状态记录；
    换模型等配置得到另一个 profile，才创建另一条独立的导入记录。
    JSON 数组保留三个字段的明确边界，避免简单字符串相加产生歧义。
    """
    for name, value in (("paper_id", paper_id), ("parse_revision", parse_revision),
                        ("index_profile_id", index_profile_id)):
        _nonempty(value, name)
        if not SAFE_ID.fullmatch(value):
            raise StorageError(f"{name} 必须是安全标识符")
    return "i_" + _digest(_canonical([paper_id, parse_revision, index_profile_id]))


def _paper_columns(paper: dict) -> dict:
    return {**{key: paper[key] for key in PAPER_FIELDS}, "text_selectable": int(paper["text_selectable"]),
            "paper_json": _canonical(paper)}


def _chunk_columns(chunk: dict) -> dict:
    """常用字段单独存列供 SQL 查询；完整记录另存 JSON 以免丢失元数据。

    SQLite 没有 Python 的 list 类型，因此数组显式编码为 JSON。回查再从
    record_json 还原，不能把 '[1,2]' 这样的字符串误当作真正的数组。
    """
    structured = "parent_id" in chunk
    result = {key: chunk.get(key) if structured else chunk[key]
              for key in CHUNK_FIELDS if key not in ("source_line_indices", "segment_bbox")}
    result["source_line_indices_json"] = None if structured else _canonical(chunk["source_line_indices"])
    result["segment_bbox_json"] = None if structured else _canonical(chunk["segment_bbox"])
    if structured:
        result["parent_id"] = chunk["parent_id"]
    result["record_json"] = _canonical(chunk)
    return result


def _parent_columns(parent: dict, order: int) -> dict:
    return {key: parent[key] for key in ("parent_id", "paper_id", "parse_revision", "text")} | {
        "parent_order": order, "record_json": _canonical(parent)}


def _validate_bundle(bundle: StoredVersionInput) -> tuple[dict, dict, list[dict]]:
    """重验内存输入，保持传入文本原样；这不是读取 PDF 的替代步骤。"""
    if not isinstance(bundle, StoredVersionInput):
        raise StorageError("必须传入 StoredVersionInput")
    # 复制一份 JSON 对象，之后统计和写入使用同一份已经核对的内容。
    paper = json.loads(_canonical(bundle.paper))
    manifest = json.loads(_canonical(bundle.manifest))
    chunks = json.loads(_canonical(bundle.chunks))
    if not isinstance(paper, dict) or any(key not in paper for key in PAPER_FIELDS):
        raise StorageError("paper 缺少论文清单的八个必填字段")
    paper_id = _nonempty(paper["paper_id"], "paper_id")
    if not SAFE_ID.fullmatch(paper_id):
        raise StorageError("paper_id 必须是安全标识符")
    for key in ("title", "local_path"):
        _nonempty(paper[key], key)
    for key in ("arxiv_version", "source_url"):
        if not isinstance(paper[key], str):
            raise StorageError(f"{key} 必须是字符串")
    if (paper["arxiv_version"] and (not re.fullmatch(r"v[1-9][0-9]*", paper["arxiv_version"])
                                    or not paper_id.endswith(paper["arxiv_version"]))):
        raise StorageError("论文 ID 与 arXiv 版本字段不一致")
    if not paper["arxiv_version"] and paper.get("source_type") != "local":
        raise StorageError("本地论文以外的来源须保留 arXiv 版本")
    _sha(paper["pdf_sha256"], "pdf_sha256")
    _positive(paper["page_count"], "page_count")
    if type(paper["text_selectable"]) is not bool:
        raise StorageError("text_selectable 必须是布尔值")

    if not isinstance(manifest, dict) or manifest.get("schema_revision") not in ("d4-chunk-version-v1", "structured-pdf-v1"):
        raise StorageError("不是支持的 D4 分块版本清单")
    revision = _nonempty(manifest.get("parse_revision"), "parse_revision")
    recipe_hash = _sha(manifest.get("recipe_sha256"), "recipe_sha256")
    recipe = manifest.get("recipe")
    if not isinstance(recipe, dict) or _digest(_canonical(recipe)) != recipe_hash:
        raise StorageError("recipe 内容与版本指纹不一致")
    if revision != "r_" + recipe_hash[:16] or manifest.get("paper_id") != paper_id:
        raise StorageError("论文 ID 或处理版本与完整指纹不一致")
    if recipe.get("paper_id") != paper_id or recipe.get("pdf_sha256") != paper["pdf_sha256"]:
        raise StorageError("recipe 的论文来源与 paper 不一致")
    if not isinstance(manifest.get("source_paths"), dict) or manifest["source_paths"].get("pdf") != paper["local_path"]:
        raise StorageError("清单中的 PDF 路径与论文清单不一致")
    # 指纹里的 paper hash 来自任务 B 保存的 pretty JSON，而非数据库的 canonical JSON。
    # 如果清单带有该项，本层也核对；文件字节的最终真实性仍由 loader 检查。
    if "paper_metadata_sha256" in recipe:
        pretty_paper = json.dumps(paper, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if recipe["paper_metadata_sha256"] != _digest(pretty_paper):
            raise StorageError("recipe 中的论文元数据哈希与 paper 不一致")
    _sha(bundle.manifest_sha256, "manifest_sha256")
    # 相对路径固定到当前论文和版本，防止错误地把另一个版本目录当作来源。
    expected_path = f"data/chunks/{paper_id}/{revision}"
    if bundle.snapshot_path != expected_path:
        raise StorageError(f"snapshot_path 必须是 {expected_path}")

    if manifest["schema_revision"] == "structured-pdf-v1":
        parents = json.loads(_canonical(bundle.parents))
        if not isinstance(parents, list) or not parents or not isinstance(chunks, list) or not chunks:
            raise StorageError("结构版本必须包含父内容和检索子块")
        parent_ids = {parent["parent_id"] for parent in parents}
        for parent in parents:
            if parent["paper_id"] != paper_id or parent["parse_revision"] != revision:
                raise StorageError("父内容与处理版本身份不一致")
            _nonempty(parent["text"], "parent.text")
        for chunk in chunks:
            if any(key not in chunk for key in STRUCTURED_CHUNK_FIELDS):
                raise StorageError("结构子块缺少必填字段")
            EvidenceRef.model_validate({key: chunk[key] for key in ("chunk_id", "paper_id", "parse_revision", "pdf_page")})
            if (chunk["paper_id"] != paper_id or chunk["parse_revision"] != revision
                    or chunk["pdf_sha256"] != paper["pdf_sha256"] or chunk["parent_id"] not in parent_ids):
                raise StorageError("结构子块的父内容或处理版本身份不一致")
            if not chunk["source_spans"] or any(span["pdf_page"] != chunk["pdf_page"] for span in chunk["source_spans"]):
                raise StorageError("结构子块须保留实际页内来源")
            if _digest(_nonempty(chunk["text"], "chunk.text")) != chunk["text_sha256"]:
                raise StorageError("chunk 原文与 text_sha256 不一致")
        return paper, manifest, chunks

    configuration = recipe.get("chunking")
    if not isinstance(configuration, dict):
        raise StorageError("recipe 缺少 chunking 配置")
    max_chars = _positive(configuration.get("max_chars"), "max_chars")
    overlap = configuration.get("overlap_chars")
    if type(overlap) is not int or not 0 <= overlap < max_chars:
        raise StorageError("overlap_chars 必须满足 0 <= overlap_chars < max_chars")
    _nonempty(recipe.get("filter_revision"), "filter_revision")
    if not isinstance(chunks, list) or not chunks:
        raise StorageError("chunks 必须是非空记录列表")

    seen_ids = set()
    page_counts = Counter()
    segment_counts = Counter()
    for chunk in chunks:
        if not isinstance(chunk, dict) or any(key not in chunk for key in CHUNK_FIELDS):
            raise StorageError("chunk 缺少必填字段")
        try:
            evidence = {key: chunk[key] for key in ("chunk_id", "paper_id", "parse_revision", "pdf_page")}
            checked = EvidenceRef.model_validate(evidence)
            if checked.model_dump() != evidence:
                raise ValueError("引用字段含首尾空白")
        except ValueError as error:
            raise StorageError(f"chunk 引用字段不合法：{error}") from error
        if (chunk["paper_id"] != paper_id or chunk["parse_revision"] != revision
                or chunk["pdf_sha256"] != paper["pdf_sha256"]):
            raise StorageError("chunk 的论文、处理版本或 PDF 哈希不一致")
        page = chunk["pdf_page"]
        if page > paper["page_count"]:
            raise StorageError("chunk 页码超过论文总页数")
        page_counts[page] += 1
        expected_id = f"{paper_id}_{revision}_p{page}_c{page_counts[page]}"
        if chunk["chunk_id"] != expected_id or chunk["chunk_id"] in seen_ids:
            raise StorageError("chunk_id 重复或不符合清单的稳定 ID 格式")
        seen_ids.add(chunk["chunk_id"])
        text = _nonempty(chunk["text"], "chunk.text")
        # 不调用 strip() 后存储：空格和换行属于原文，清理它们会破坏字符范围。
        if "\x00" in text or len(text) > max_chars:
            raise StorageError("chunk 原文含 NUL 或超过配置的最大长度")
        if _sha(chunk["text_sha256"], "text_sha256") != _digest(text):
            raise StorageError("chunk 原文与 text_sha256 不一致")
        start, end = chunk["char_start"], chunk["char_end"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end - start != len(text):
            raise StorageError("chunk 字符范围与原文长度不一致")
        segment_id = _nonempty(chunk["segment_id"], "segment_id")
        segment_counts[segment_id] += 1
        if chunk["filter_revision"] != recipe["filter_revision"]:
            raise StorageError("chunk 使用了不同的过滤规则版本")
        if type(chunk["source_block_index"]) is not int or chunk["source_block_index"] < 0:
            raise StorageError("source_block_index 必须是非负整数")
        lines = chunk["source_line_indices"]
        if (not isinstance(lines, list) or not lines or any(type(value) is not int or value < 0 for value in lines)
                or lines != list(range(lines[0], lines[-1] + 1))):
            raise StorageError("source_line_indices 必须是连续非负整数")
        box = chunk["segment_bbox"]
        if (not isinstance(box, list) or len(box) != 4
                or any(type(value) not in (int, float) or not isfinite(value) for value in box)
                or not (box[0] < box[2] and box[1] < box[3])):
            raise StorageError("segment_bbox 必须是有效矩形")

    expected_statistics = {
        "page_count": paper["page_count"], "segment_count": len(segment_counts), "chunk_count": len(chunks),
        "split_segment_count": sum(count > 1 for count in segment_counts.values()),
        "max_chunk_chars": max(len(chunk["text"]) for chunk in chunks),
        "chunks_per_page": {str(page): page_counts[page] for page in range(1, paper["page_count"] + 1)},
    }
    statistics = manifest.get("statistics")
    if (not isinstance(statistics, dict)
            or any(key not in statistics or _canonical(statistics[key]) != _canonical(value)
                   for key, value in expected_statistics.items())):
        raise StorageError("清单中的页数、片段数或分块统计与实际 chunks 不一致")
    return paper, manifest, chunks


TABLE_SQL = {
    "papers": """CREATE TABLE papers (
        paper_id TEXT PRIMARY KEY NOT NULL,
        arxiv_version TEXT NOT NULL,
        title TEXT NOT NULL,
        source_url TEXT NOT NULL,
        local_path TEXT NOT NULL,
        pdf_sha256 TEXT NOT NULL CHECK(length(pdf_sha256) = 64),
        page_count INTEGER NOT NULL CHECK(page_count > 0),
        text_selectable INTEGER NOT NULL CHECK(text_selectable IN (0, 1)),
        paper_json TEXT NOT NULL
    )""",
    "parse_versions": """CREATE TABLE parse_versions (
        paper_id TEXT NOT NULL,
        parse_revision TEXT NOT NULL,
        recipe_sha256 TEXT NOT NULL CHECK(length(recipe_sha256) = 64),
        pdf_sha256 TEXT NOT NULL CHECK(length(pdf_sha256) = 64),
        manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
        snapshot_path TEXT NOT NULL,
        page_count INTEGER NOT NULL CHECK(page_count > 0),
        segment_count INTEGER NOT NULL CHECK(segment_count > 0),
        chunk_count INTEGER NOT NULL CHECK(chunk_count > 0),
        configuration_json TEXT NOT NULL,
        statistics_json TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        PRIMARY KEY (paper_id, parse_revision),
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
    )""",
    "chunks": """CREATE TABLE chunks (
        chunk_id TEXT PRIMARY KEY NOT NULL,
        paper_id TEXT NOT NULL,
        parse_revision TEXT NOT NULL,
        pdf_sha256 TEXT NOT NULL CHECK(length(pdf_sha256) = 64),
        pdf_page INTEGER NOT NULL CHECK(pdf_page > 0),
        segment_id TEXT NOT NULL,
        char_start INTEGER NOT NULL CHECK(char_start >= 0),
        char_end INTEGER NOT NULL CHECK(char_end > char_start),
        text TEXT NOT NULL CHECK(length(text) > 0),
        text_sha256 TEXT NOT NULL CHECK(length(text_sha256) = 64),
        filter_revision TEXT NOT NULL,
        source_block_index INTEGER NOT NULL CHECK(source_block_index >= 0),
        source_line_indices_json TEXT NOT NULL,
        segment_bbox_json TEXT NOT NULL,
        record_json TEXT NOT NULL,
        CHECK(char_end - char_start = length(text)),
        FOREIGN KEY (paper_id, parse_revision) REFERENCES parse_versions(paper_id, parse_revision)
    )""",
    "index_imports": """CREATE TABLE index_imports (
        import_key TEXT PRIMARY KEY NOT NULL,
        paper_id TEXT NOT NULL,
        parse_revision TEXT NOT NULL,
        index_profile_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'ready', 'failed')),
        completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count >= 0),
        error_summary TEXT,
        UNIQUE (paper_id, parse_revision, index_profile_id),
        FOREIGN KEY (paper_id, parse_revision) REFERENCES parse_versions(paper_id, parse_revision)
    )""",
}

LEGACY_TABLE_SQL = dict(TABLE_SQL)
TABLE_SQL["parse_versions"] = TABLE_SQL["parse_versions"].replace(
    "segment_count INTEGER NOT NULL", "segment_count INTEGER")
TABLE_SQL["chunks"] = TABLE_SQL["chunks"].replace(
    "segment_id TEXT NOT NULL", "segment_id TEXT").replace(
    "char_start INTEGER NOT NULL", "char_start INTEGER").replace(
    "char_end INTEGER NOT NULL", "char_end INTEGER").replace(
    "filter_revision TEXT NOT NULL", "filter_revision TEXT").replace(
    "source_block_index INTEGER NOT NULL", "source_block_index INTEGER").replace(
    "source_line_indices_json TEXT NOT NULL", "source_line_indices_json TEXT").replace(
    "segment_bbox_json TEXT NOT NULL", "segment_bbox_json TEXT").replace(
    "record_json TEXT NOT NULL,", "record_json TEXT NOT NULL,\n        parent_id TEXT,").replace(
    "CHECK(char_end - char_start = length(text)),",
    "CHECK(char_end - char_start = length(text)),\n        FOREIGN KEY (parent_id) REFERENCES parent_contents(parent_id),")
TABLE_SQL["parent_contents"] = """CREATE TABLE parent_contents (
        parent_id TEXT PRIMARY KEY NOT NULL,
        paper_id TEXT NOT NULL,
        parse_revision TEXT NOT NULL,
        parent_order INTEGER NOT NULL,
        text TEXT NOT NULL,
        record_json TEXT NOT NULL,
        FOREIGN KEY (paper_id, parse_revision) REFERENCES parse_versions(paper_id, parse_revision)
    )"""

TRIGGER_SQL = {
    f"{table}_immutable_{operation.lower()}": f"""CREATE TRIGGER {table}_immutable_{operation.lower()}
        BEFORE {operation} ON {table}
        BEGIN SELECT RAISE(ABORT, '{table} rows are immutable'); END"""
    for table in ("papers", "parse_versions", "chunks", "parent_contents") for operation in ("UPDATE", "DELETE")
}
LEGACY_TRIGGER_SQL = {name: sql for name, sql in TRIGGER_SQL.items() if not name.startswith("parent_contents_")}
INDEX_SQL = "CREATE INDEX chunks_version_page ON chunks(paper_id, parse_revision, pdf_page)"


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";")


def _version_columns(bundle: StoredVersionInput, manifest: dict) -> dict:
    statistics = manifest["statistics"]
    return {
        "paper_id": manifest["paper_id"], "parse_revision": manifest["parse_revision"],
        "recipe_sha256": manifest["recipe_sha256"], "pdf_sha256": manifest["recipe"]["pdf_sha256"],
        "manifest_sha256": bundle.manifest_sha256, "snapshot_path": bundle.snapshot_path,
        "page_count": statistics["page_count"], "segment_count": statistics.get("segment_count"),
        "chunk_count": statistics["chunk_count"], "configuration_json": _canonical(manifest["recipe"]["chunking"]),
        "statistics_json": _canonical(statistics), "manifest_json": _canonical(manifest),
    }


class _LockedReadConnection:
    """Serialize the graph's read-only connection across worker threads."""

    def __init__(self, connection, lock):
        self._connection = connection
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._connection.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class PaperStore:
    """一条 SQLite 连接；用 with 让正常退出和异常退出都明确关闭文件。

    主键负责唯一身份，外键负责来源关系，事务负责一篇论文全部成功或全部
    回滚。这三种约束解决不同问题，不能仅凭 chunk_id 唯一就省略其它约束。
    read_only=True 用于回查，数据库不存在时直接报错，不生成空数据库冒充结果。
    """

    def __init__(self, database_path: Path, read_only: bool = False):
        if type(read_only) is not bool:
            raise StorageError("read_only 必须是布尔值")
        self.database_path = Path(database_path).resolve()
        self.read_only = read_only
        self._closed = True
        self._thread_sharing = False
        self._thread_lock = None
        if read_only and not self.database_path.is_file():
            raise StorageError(f"只读数据库不存在：{self.database_path}")
        try:
            if read_only:
                # URI 的 mode=ro 是 SQLite 本身的限制；不会只靠调用者自觉不写。
                self.connection = sqlite3.connect(self.database_path.as_uri() + "?mode=ro", uri=True,
                                                  timeout=30, isolation_level=None)
            else:
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                # isolation_level=None 禁止隐式事务，写操作下面显式 BEGIN/COMMIT。
                self.connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
            self._closed = False
            self.connection.row_factory = sqlite3.Row
            # SQLite 外键默认可能关闭，而且开关属于连接；每次连接都必须开启。
            self.connection.execute("PRAGMA foreign_keys = ON")
            if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise StorageError("无法开启 SQLite 外键检查")
            self._initialize_or_check_schema()
        except (sqlite3.Error, OSError, StorageError) as error:
            self.close()
            if isinstance(error, StorageError):
                raise
            raise StorageError(f"无法打开 SQLite 数据库：{error}") from error

    def __enter__(self) -> "PaperStore":
        self._ensure_open()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            if self.connection.in_transaction:
                self.connection.rollback()
            self.connection.close()
            self._closed = True

    def enable_thread_sharing(self) -> None:
        """Allow this read-only connection to be used serially by graph workers."""
        if not self.read_only:
            raise StorageError("只有只读连接可以启用跨线程读取")
        if self._thread_sharing:
            return
        self._ensure_open()
        self.connection.close()
        self.connection = sqlite3.connect(
            self.database_path.as_uri() + "?mode=ro", uri=True,
            timeout=30, isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._thread_lock = threading.RLock()
        self.connection = _LockedReadConnection(self.connection, self._thread_lock)
        self._thread_sharing = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise StorageError("PaperStore 连接已经关闭")

    def _initialize_or_check_schema(self) -> None:
        """只初始化空库；未知结构绝不猜测、重建或覆盖。"""
        current = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if current == 1 and not self.read_only:
            self._check_schema()
            self.connection.execute("PRAGMA foreign_keys = OFF")
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                for table in ("parse_versions", "chunks"):
                    temporary = "migrate_" + table
                    self.connection.execute(f"CREATE TEMP TABLE {temporary} AS SELECT * FROM {table}")
                    columns = ", ".join(row["name"] for row in self.connection.execute(f"PRAGMA table_info({temporary})"))
                    self.connection.execute(f"DROP TABLE {table}")
                    self.connection.execute(TABLE_SQL[table])
                    self.connection.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {temporary}")
                    self.connection.execute(f"DROP TABLE {temporary}")
                self.connection.execute(TABLE_SQL["parent_contents"])
                self.connection.execute(INDEX_SQL)
                for name, sql in TRIGGER_SQL.items():
                    if not name.startswith("papers_"):
                        self.connection.execute(sql)
                self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            finally:
                self.connection.execute("PRAGMA foreign_keys = ON")
        if not self.read_only:
            # 初始化也受事务保护。两个程序同时首次打开时，第二个等第一个
            # 完成再读取 user_version，避免都以为自己面对一个空库。
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.connection.execute("PRAGMA user_version").fetchone()[0]
            objects = self.connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if current == 0 and not objects and not self.read_only:
                # 不用 executescript：它会影响事务边界；逐句 execute 才能统一回滚。
                for sql in TABLE_SQL.values():
                    self.connection.execute(sql)
                self.connection.execute(INDEX_SQL)
                for sql in TRIGGER_SQL.values():
                    self.connection.execute(sql)
                self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif current != SCHEMA_VERSION and not (self.read_only and current == 1):
                raise StorageError(f"不支持数据库 schema user_version={current}，预期 {SCHEMA_VERSION}")
            self._check_schema()
            if not self.read_only:
                self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise

    def _check_schema(self) -> None:
        self._schema_version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        table_sql = LEGACY_TABLE_SQL if self._schema_version == 1 else TABLE_SQL
        trigger_sql = LEGACY_TRIGGER_SQL if self._schema_version == 1 else TRIGGER_SQL
        objects = self.connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        tables = {row["name"] for row in objects if row["type"] == "table"}
        if tables != set(table_sql):
            raise StorageError("数据库存储表不完整或存在未知表")
        actual = {row["name"]: row["sql"] for row in objects}
        # 核对 CREATE TABLE 能同时核对列、主键、CHECK 和 FK，避免只相信版本号。
        # 允许额外索引或测试触发器，但必要的不可变保护必须逐句相同。
        for name, expected in {**table_sql, **trigger_sql, "chunks_version_page": INDEX_SQL}.items():
            if name not in actual or not actual[name] or _normalized_sql(actual[name]) != _normalized_sql(expected):
                raise StorageError(f"数据库结构或不可变保护不匹配：{name}")
        if self.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageError("数据库中存在外键失联记录")

    @staticmethod
    def _matches(row: sqlite3.Row, expected: dict) -> bool:
        return all(row[key] == value for key, value in expected.items())

    def _insert(self, table: str, values: dict) -> None:
        # 表名和列名都由本模块固定代码提供，数据全部走 ? 占位符。
        # 即使原文含引号或 SQL 片段，也只是字符串，不会被拼接成 SQL 指令。
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        self.connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))

    def import_version(self, bundle: StoredVersionInput) -> dict:
        """原子导入一篇版本；精确相同才复用，任何内容冲突都拒绝。

        BEGIN IMMEDIATE 先取得写锁，再做“存在吗”的查询和插入。否则两个
        导入程序可能同时查到不存在，再分别尝试创建相同记录。
        一篇的 papers、parse_versions 和所有 chunks 在一个事务里完成。
        index_imports 此时保持空白，因为写入 SQLite 不等于向量检索就绪。
        """
        self._ensure_open()
        if self.read_only:
            raise StorageError("只读连接不能导入版本")
        paper, manifest, chunks = _validate_bundle(bundle)
        paper_values = _paper_columns(paper)
        version_values = _version_columns(bundle, manifest)
        chunk_values = [_chunk_columns(chunk) for chunk in chunks]
        parent_values = [_parent_columns(parent, order) for order, parent in enumerate(bundle.parents)]
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            old_paper = self.connection.execute("SELECT * FROM papers WHERE paper_id = ?", (paper["paper_id"],)).fetchone()
            if old_paper is not None and not self._matches(old_paper, paper_values):
                raise StorageConflict("已有 paper_id 的来源或论文元数据不同，拒绝覆盖")
            old_version = self.connection.execute(
                "SELECT * FROM parse_versions WHERE paper_id = ? AND parse_revision = ?",
                (paper["paper_id"], manifest["parse_revision"]),
            ).fetchone()
            reused = old_version is not None
            if reused:
                if not self._matches(old_version, version_values):
                    raise StorageConflict("已有处理版本的指纹、清单、快照路径或统计不同")
                existing = self.connection.execute(
                    "SELECT * FROM chunks WHERE paper_id = ? AND parse_revision = ?",
                    (paper["paper_id"], manifest["parse_revision"]),
                ).fetchall()
                existing_by_id = {row["chunk_id"]: row for row in existing}
                if len(existing) != len(chunks) or set(existing_by_id) != {chunk["chunk_id"] for chunk in chunks}:
                    raise StorageConflict("已有版本的 chunks 缺失或多出，拒绝静默修补")
                if any(not self._matches(existing_by_id[values["chunk_id"]], values) for values in chunk_values):
                    raise StorageConflict("已有版本的 chunk 原文或来源字段被修改")
                existing_parents = self.connection.execute(
                    "SELECT * FROM parent_contents WHERE paper_id = ? AND parse_revision = ? ORDER BY parent_order",
                    (paper["paper_id"], manifest["parse_revision"])).fetchall()
                if len(existing_parents) != len(parent_values) or any(
                        not self._matches(row, values) for row, values in zip(existing_parents, parent_values)):
                    raise StorageConflict("已有版本的父内容或来源关系不同")
            else:
                if old_paper is None:
                    self._insert("papers", paper_values)
                self._insert("parse_versions", version_values)
                for values in parent_values:
                    self._insert("parent_contents", values)
                for values in chunk_values:
                    self._insert("chunks", values)
            self.connection.commit()
            return {
                "paper_id": paper["paper_id"], "parse_revision": manifest["parse_revision"],
                "chunk_count": len(chunks), "inserted_chunks": 0 if reused else len(chunks), "reused": reused,
            }
        except Exception as error:
            if self.connection.in_transaction:
                self.connection.rollback()
            if isinstance(error, StorageError):
                raise
            if isinstance(error, sqlite3.IntegrityError):
                raise StorageConflict(f"SQLite 唯一性、不可变或来源约束拒绝导入：{error}") from error
            if isinstance(error, sqlite3.Error):
                raise StorageError(f"SQLite 导入失败且已回滚：{error}") from error
            raise

    def get_chunk(self, chunk_id: str) -> dict | None:
        """按真实 ID 回查原文和论文信息；不存在返回 None，不猜测相近 ID。

        回查无需等待 Qdrant ready：任务 C 已经能读取证据正文；以后向量检索
        入口再根据 index_imports 限定 ready 版本，两个阶段不要混为一谈。
        """
        self._ensure_open()
        _nonempty(chunk_id, "chunk_id")
        try:
            row = self.connection.execute(
                """SELECT c.*, p.title, p.arxiv_version, p.source_url, p.local_path,
                          p.pdf_sha256 AS paper_pdf_sha256, p.page_count AS paper_page_count,
                          p.paper_json, v.pdf_sha256 AS version_pdf_sha256, v.manifest_json
                   FROM chunks AS c
                   JOIN papers AS p ON p.paper_id = c.paper_id
                   JOIN parse_versions AS v ON v.paper_id = c.paper_id AND v.parse_revision = c.parse_revision
                   WHERE c.chunk_id = ?""", (chunk_id,),
            ).fetchone()
            if row is None:
                return None
            chunk = json.loads(row["record_json"])
            fields = STRUCTURED_CHUNK_FIELDS if isinstance(chunk, dict) and "parent_id" in chunk else CHUNK_FIELDS
            if not isinstance(chunk, dict) or any(key not in chunk for key in fields):
                raise StorageError("数据库 chunk 完整记录缺少字段")
            if not self._matches(row, _chunk_columns(chunk)):
                raise StorageError("数据库 chunk 的查询列与完整 JSON 记录不一致")
            if _digest(chunk["text"]) != chunk["text_sha256"]:
                raise StorageError("数据库 chunk 原文哈希不一致")
            if (chunk["pdf_sha256"] != row["paper_pdf_sha256"] or chunk["pdf_sha256"] != row["version_pdf_sha256"]
                    or not 1 <= chunk["pdf_page"] <= row["paper_page_count"]):
                raise StorageError("数据库 chunk 的 PDF 来源或页码不一致")
            paper = json.loads(row["paper_json"])
            manifest = json.loads(row["manifest_json"])
            if (not isinstance(paper, dict) or not isinstance(manifest, dict)
                    or paper.get("paper_id") != chunk["paper_id"]
                    or paper.get("pdf_sha256") != chunk["pdf_sha256"]
                    or manifest.get("paper_id") != chunk["paper_id"]
                    or manifest.get("parse_revision") != chunk["parse_revision"]
                    or any(paper.get(key) != row[key] for key in ("title", "arxiv_version", "source_url", "local_path"))):
                raise StorageError("数据库论文或处理版本完整记录与来源列不一致")
            return {**chunk, **{key: row[key] for key in ("title", "arxiv_version", "source_url", "local_path")}}
        except StorageError:
            raise
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise StorageError(f"SQLite 回查失败：{error}") from error

    def get_parent(self, parent_id: str) -> dict | None:
        """Read stored parent text and its actual ordered child/source relationships."""
        self._ensure_open()
        if self._schema_version == 1:
            return None
        row = self.connection.execute("SELECT record_json FROM parent_contents WHERE parent_id = ?", (parent_id,)).fetchone()
        return json.loads(row["record_json"]) if row is not None else None

    def get_version_parents(self, paper_id: str, parse_revision: str) -> list[dict]:
        self._ensure_open()
        if self._schema_version == 1:
            return []
        return [json.loads(row["record_json"]) for row in self.connection.execute(
            "SELECT record_json FROM parent_contents WHERE paper_id = ? AND parse_revision = ? ORDER BY parent_order",
            (paper_id, parse_revision)).fetchall()]

    def get_version_chunks(self, paper_id: str, parse_revision: str) -> list[dict]:
        """读取一篇明确版本的全部原文，保持页序和每页的真实块序。

        字符串排序会把 c10 放在 c2 前面，所以先读取页码，再把 ID 中的
        块序解析成整数排序。每条仍走 get_chunk 的 JSON、列和来源核对，
        并核对总数；不能把缺块的数据库当成完整的 embedding 输入。
        """
        self._ensure_open()
        # 复用身份检查，只为验证字段；这个临时值不写入 index_imports。
        index_import_key(paper_id, parse_revision, "scope_check")
        try:
            version = self.connection.execute(
                "SELECT chunk_count FROM parse_versions WHERE paper_id = ? AND parse_revision = ?",
                (paper_id, parse_revision),
            ).fetchone()
            if version is None:
                raise StorageError("指定论文及处理版本尚未保存到 SQLite")
            rows = self.connection.execute(
                "SELECT chunk_id, pdf_page FROM chunks WHERE paper_id = ? AND parse_revision = ?",
                (paper_id, parse_revision),
            ).fetchall()
            if len(rows) != version["chunk_count"]:
                raise StorageError("数据库版本的 chunk 数量与版本清单不一致")
            chunk_pattern = re.compile(re.escape(f"{paper_id}_{parse_revision}") + r"_p([1-9][0-9]*)_c([1-9][0-9]*)\Z")
            ordered = []
            for row in rows:
                match = chunk_pattern.fullmatch(row["chunk_id"])
                if match is None or int(match.group(1)) != row["pdf_page"]:
                    raise StorageError("数据库 chunk ID 的论文、版本或页序不一致")
                ordered.append((row["pdf_page"], int(match.group(2)), row["chunk_id"]))
            ordered.sort()
            page_counts = Counter()
            chunks = []
            for page, chunk_number, chunk_id in ordered:
                page_counts[page] += 1
                if chunk_number != page_counts[page]:
                    raise StorageError("数据库 chunk ID 的每页块序不连续")
                chunk = self.get_chunk(chunk_id)
                if chunk is None:
                    raise StorageError("读取版本时 chunk 缺失")
                if chunk["paper_id"] != paper_id or chunk["parse_revision"] != parse_revision:
                    raise StorageError("回查 chunk 属于另一篇论文或处理版本")
                chunks.append(chunk)
            return chunks
        except StorageError:
            raise
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise StorageError(f"无法读取版本的完整 chunks：{error}") from error

    @staticmethod
    def _checked_index_import(row: sqlite3.Row) -> dict:
        """检查状态行的身份与计数；expected_chunk_count 只用于内部核对。

        index_imports 是可变进度表，不能像原文表一样禁止 UPDATE。因此
        读取时也检查状态含义，避免手工写入的错误状态被查询入口信任。
        """
        result = dict(row)
        expected_count = result.pop("expected_chunk_count")
        if result["import_key"] != index_import_key(
            result["paper_id"], result["parse_revision"], result["index_profile_id"]
        ):
            raise StorageError("向量导入键与论文、处理版本及索引配置不一致")
        count = result["completed_count"]
        if type(count) is not int or not 0 <= count <= expected_count:
            raise StorageError("向量导入的完成数量不在该版本的合法范围内")
        if result["status"] not in ("pending", "ready", "failed"):
            raise StorageError("向量导入状态不合法")
        if result["status"] == "ready" and count != expected_count:
            raise StorageError("ready 状态缺少该版本的完整向量数量")
        error = result["error_summary"]
        if result["status"] == "failed":
            if not isinstance(error, str) or not error.strip() or len(error) > 500 or "\x00" in error:
                raise StorageError("failed 状态缺少合法的安全错误摘要")
        elif error is not None:
            raise StorageError("非 failed 状态不能携带旧错误摘要")
        return result

    def _index_import_row(self, import_key: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """SELECT i.*, v.chunk_count AS expected_chunk_count
               FROM index_imports AS i
               JOIN parse_versions AS v
                 ON v.paper_id = i.paper_id AND v.parse_revision = i.parse_revision
               WHERE i.import_key = ?""", (import_key,),
        ).fetchone()

    def get_index_import(self, paper_id: str, parse_revision: str, index_profile_id: str) -> dict | None:
        """按明确的三元身份读状态；不存在返回 None，不猜测当前版本。"""
        self._ensure_open()
        expected_key = index_import_key(paper_id, parse_revision, index_profile_id)
        try:
            # 先按 UNIQUE 的三元身份找，才能发现同一身份被错误写成别的键。
            row = self.connection.execute(
                """SELECT i.*, v.chunk_count AS expected_chunk_count
                   FROM index_imports AS i
                   JOIN parse_versions AS v
                     ON v.paper_id = i.paper_id AND v.parse_revision = i.parse_revision
                   WHERE i.paper_id = ? AND i.parse_revision = ? AND i.index_profile_id = ?""",
                (paper_id, parse_revision, index_profile_id),
            ).fetchone()
            if row is None:
                return None
            result = self._checked_index_import(row)
            if result["import_key"] != expected_key:
                raise StorageError("向量导入身份不一致")
            return result
        except sqlite3.Error as error:
            raise StorageError(f"无法读取向量导入状态：{error}") from error

    def list_index_imports(self, *, status: str | None = None, index_profile_id: str | None = None) -> list[dict]:
        """列出通过身份/计数检查的状态，可仅取某索引配置下的 ready 行。"""
        self._ensure_open()
        conditions, arguments = [], []
        if status is not None:
            if status not in ("pending", "ready", "failed"):
                raise StorageError("筛选状态必须是 pending、ready 或 failed")
            conditions.append("i.status = ?")
            arguments.append(status)
        if index_profile_id is not None:
            index_import_key("scope_check", "scope_check", index_profile_id)
            conditions.append("i.index_profile_id = ?")
            arguments.append(index_profile_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        try:
            rows = self.connection.execute(
                """SELECT i.*, v.chunk_count AS expected_chunk_count
                   FROM index_imports AS i
                   JOIN parse_versions AS v
                     ON v.paper_id = i.paper_id AND v.parse_revision = i.parse_revision"""
                + where + " ORDER BY i.paper_id, i.parse_revision, i.index_profile_id", arguments,
            ).fetchall()
            return [self._checked_index_import(row) for row in rows]
        except sqlite3.Error as error:
            raise StorageError(f"无法列出向量导入状态：{error}") from error

    def begin_index_import(
        self, paper_id: str, parse_revision: str, index_profile_id: str, *, completed_count: int = 0,
    ) -> dict:
        """创建或重新开始同一导入，状态写 pending，并清除旧错误摘要。

        重试前，调用者先核对 Qdrant 现存的点，再传入真实完成数量；即使
        原来已经 ready，本次重新构建也先取消 ready，避免半份重建结果
        暴露给检索。正常的 ready 复用无需调用本方法，由上层直接验证。
        事务只保证本行的修改完整，不能代替跨 SQLite/Qdrant 的核对。
        """
        self._ensure_open()
        if self.read_only:
            raise StorageError("只读连接不能开始向量导入")
        key = index_import_key(paper_id, parse_revision, index_profile_id)
        if type(completed_count) is not int or completed_count < 0:
            raise StorageError("completed_count 必须是非负整数")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            version = self.connection.execute(
                "SELECT chunk_count FROM parse_versions WHERE paper_id = ? AND parse_revision = ?",
                (paper_id, parse_revision),
            ).fetchone()
            if version is None or completed_count > version["chunk_count"]:
                raise StorageError("向量导入缺少对应版本，或完成数量超过版本总块数")
            existing = self.get_index_import(paper_id, parse_revision, index_profile_id)
            if existing is None:
                self._insert("index_imports", {
                    "import_key": key, "paper_id": paper_id, "parse_revision": parse_revision,
                    "index_profile_id": index_profile_id, "status": "pending",
                    "completed_count": completed_count, "error_summary": None,
                })
            else:
                self.connection.execute(
                    "UPDATE index_imports SET status = 'pending', completed_count = ?, error_summary = NULL WHERE import_key = ?",
                    (completed_count, key),
                )
            result = self._checked_index_import(self._index_import_row(key))
            self.connection.commit()
            return result
        except Exception as error:
            if self.connection.in_transaction:
                self.connection.rollback()
            if isinstance(error, sqlite3.Error):
                raise StorageError(f"开始向量导入失败且已回滚：{error}") from error
            raise

    def _write_index_import_state(
        self, import_key: str, status: str, completed_count: int | None, error_summary: str | None,
    ) -> dict:
        """把检查和 UPDATE 放在同一写事务中，避免读取后状态被并发改变。"""
        self._ensure_open()
        if self.read_only:
            raise StorageError("只读连接不能修改向量导入状态")
        if not isinstance(import_key, str) or not re.fullmatch(r"i_[0-9a-f]{64}", import_key):
            raise StorageError("import_key 必须是本模块生成的确定性导入键")
        if completed_count is not None and (type(completed_count) is not int or completed_count < 0):
            raise StorageError("completed_count 必须是非负整数")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self._index_import_row(import_key)
            if row is None:
                raise StorageError("向量导入记录不存在，请先开始导入")
            current = self._checked_index_import(row)
            count = current["completed_count"] if completed_count is None else completed_count
            expected_count = row["expected_chunk_count"]
            if count > expected_count:
                raise StorageError("向量完成数量超过该版本的总块数")
            allowed_before = {"pending": ("pending",), "failed": ("pending", "failed"), "ready": ("pending", "ready")}
            if current["status"] not in allowed_before[status]:
                raise StorageError("当前导入状态不支持此操作，请先用同一身份重新开始导入")
            if count < current["completed_count"]:
                raise StorageError("单次导入的完成进度不能减少；重新核对后请显式 begin_index_import")
            if status == "ready" and count != expected_count:
                raise StorageError("全部向量数量尚未完成，不能标为 ready")
            self.connection.execute(
                "UPDATE index_imports SET status = ?, completed_count = ?, error_summary = ? WHERE import_key = ?",
                (status, count, error_summary, import_key),
            )
            result = self._checked_index_import(self._index_import_row(import_key))
            self.connection.commit()
            return result
        except Exception as error:
            if self.connection.in_transaction:
                self.connection.rollback()
            if isinstance(error, sqlite3.Error):
                raise StorageError(f"修改向量导入状态失败且已回滚：{error}") from error
            raise

    def set_index_import_progress(self, import_key: str, completed_count: int) -> dict:
        """成功 upsert 并核对批次后记录进度；仍为 pending，不能提前检索。"""
        if type(completed_count) is not int or completed_count < 0:
            raise StorageError("completed_count 必须是非负整数")
        return self._write_index_import_state(import_key, "pending", completed_count, None)

    def fail_index_import(self, import_key: str, error_summary: str, *, completed_count: int | None = None) -> dict:
        """保留失败和已完成数量，重试继续使用原来的 import_key。

        调用者只传预先整理的安全短句（如阶段名、异常类型及状态码），
        不能传 API 密钥、原始响应体或 .env 内容。本层限制摘要长度，
        但无法判断任意文本是否含调用者私有的密钥。
        """
        _nonempty(error_summary, "error_summary")
        if len(error_summary) > 500 or "\x00" in error_summary:
            raise StorageError("error_summary 必须是不含 NUL、最多 500 字符的安全摘要")
        return self._write_index_import_state(import_key, "failed", completed_count, error_summary)

    def finish_index_import(self, import_key: str, completed_count: int) -> dict:
        """外部逐项核对所有 Qdrant 点后，正式写 ready。

        这里只能检查 SQLite 里的身份和数量；是否存在全部 point ID、
        payload/哈希是否对应、向量维度是否正确，必须由任务 D 的调用层
        在调用前验证。全部批次“请求成功”本身不足以调用本方法。
        """
        if type(completed_count) is not int or completed_count < 0:
            raise StorageError("completed_count 必须是非负整数")
        return self._write_index_import_state(import_key, "ready", completed_count, None)

    def counts(self) -> dict:
        self._ensure_open()
        try:
            return {table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in LEGACY_TABLE_SQL}
        except sqlite3.Error as error:
            raise StorageError(f"无法统计数据库记录：{error}") from error

    def list_versions(self) -> list[dict]:
        self._ensure_open()
        try:
            return [dict(row) for row in self.connection.execute(
                """SELECT paper_id, parse_revision, recipe_sha256, pdf_sha256,
                          manifest_sha256, snapshot_path, page_count, segment_count, chunk_count
                   FROM parse_versions ORDER BY paper_id, parse_revision"""
            ).fetchall()]
        except sqlite3.Error as error:
            raise StorageError(f"无法列出数据库处理版本：{error}") from error
