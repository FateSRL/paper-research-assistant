"""D4 任务 D：在本地磁盘持久保存可核对的 Qdrant 向量。

本模块只负责向量存储与完整性检查，不调用 embedding 服务，也不读取密钥。
正文仍从 SQLite 读取；Qdrant payload 只保存回查所需的身份和来源字段。
一份 Qdrant 本地目录同时只能由一个客户端持有，调用者应使用 with 及时关闭。
"""

from collections.abc import Sequence
from math import hypot, isfinite
from pathlib import Path
import re
from uuid import UUID, uuid5

from qdrant_client import QdrantClient, models
from qdrant_client.local.qdrant_local import QdrantLocal


# UUID5 的命名空间固定在源码中。相同配置、相同 chunk 反复运行，生成相同点 ID。
# 不使用随机 UUID，否则重试会产生重复点，点数增长且无法准确恢复进度。
POINT_NAMESPACE = UUID("c6db1f27-5391-5ea4-9dc9-b2f863058823")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PAYLOAD_FIELDS = (
    "chunk_id", "paper_id", "parse_revision", "pdf_page", "text_sha256", "pdf_sha256",
)


class VectorStoreError(ValueError):
    """向量、索引配置或已保存的来源信息无法通过核对。"""


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreError(f"{name} 必须是非空字符串")
    return value


def point_id(index_profile_id: str, chunk_id: str) -> str:
    """把可读身份转成 Qdrant 接受的 UUID，避免分隔符拼接造成身份碰撞。"""
    profile = _nonempty(index_profile_id, "index_profile_id")
    chunk = _nonempty(chunk_id, "chunk_id")
    # 使用长度前缀而非简单的 profile + ':' + chunk，不依赖标识中禁用冒号。
    return str(uuid5(POINT_NAMESPACE, f"{len(profile)}:{profile}{len(chunk)}:{chunk}"))


def filter_for_versions(
    selected_versions: Sequence[tuple[str, str]], *, index_profile_id: str | None = None,
) -> models.Filter:
    """筛选明确的 (论文, 处理版本) 配对，不能把两组列表分别筛选。

    例如允许 (RAG, r1) 和 (ReAct, r2)，就不能误放行 (RAG, r2)。
    每个内层 must 表示一个完整配对，外层 should 表示至少允许一个配对。
    这只是构造条件；调用者仍须先检查 SQLite 导入状态是否 ready。
    """
    if not selected_versions:
        raise VectorStoreError("至少需要选择一个明确的论文/处理版本配对")
    pairs: list[tuple[str, str]] = []
    for pair in selected_versions:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise VectorStoreError("selected_versions 每项必须是 (paper_id, parse_revision)")
        checked = (_nonempty(pair[0], "paper_id"), _nonempty(pair[1], "parse_revision"))
        if checked not in pairs:
            pairs.append(checked)
    alternatives = [
        models.Filter(must=[
            models.FieldCondition(key="paper_id", match=models.MatchValue(value=paper)),
            models.FieldCondition(key="parse_revision", match=models.MatchValue(value=revision)),
        ])
        for paper, revision in pairs
    ]
    pair_filter = models.Filter(should=alternatives)
    if index_profile_id is None:
        return pair_filter
    return models.Filter(must=[
        models.FieldCondition(
            key="index_profile_id", match=models.MatchValue(
                value=_nonempty(index_profile_id, "index_profile_id"),
            ),
        ),
        pair_filter,
    ])


class QdrantStore:
    """一个持久化目录、一个索引配置对应的 collection。

    dimension 必须来自已核对的实际模型配置。打开既有 collection 时先检查
    维度和 cosine 距离，不能把新模型或不同维度的向量混入旧索引。
    本模块不把“存在若干点”等同于导入 ready；完整版本须通过 validate。
    """

    def __init__(
        self, path: Path, collection_name: str, index_profile_id: str, dimension: int,
        *, client: QdrantClient | None = None,
    ) -> None:
        self.path = Path(path)
        self.collection_name = _nonempty(collection_name, "collection_name")
        self.index_profile_id = _nonempty(index_profile_id, "index_profile_id")
        if type(dimension) is not int or dimension <= 0:
            raise VectorStoreError("dimension 必须是正整数")
        self.dimension = dimension
        self._owns_client = client is None
        # 正式索引拥有一个磁盘客户端；试运行 collection 借用同一客户端，
        # 避免在同一进程里重复打开相同目录导致目录锁冲突。
        # 借用者关闭时不释放拥有者的客户端，最终由正式索引统一关闭。
        if client is None:
            self.path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.path))
        else:
            if not isinstance(client, QdrantClient):
                raise VectorStoreError("client 必须是可借用的 QdrantClient")
            self.client = client
        try:
            self.ensure_collection()
        except Exception:
            if self._owns_client:
                self.client.close()
            raise

    def __enter__(self) -> "QdrantStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """提交本地存储并释放目录锁，其他进程随后才可以打开同一目录。"""
        if self._owns_client:
            self.client.close()

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.dimension, distance=models.Distance.COSINE,
                ),
            )
            return
        info = self.client.get_collection(self.collection_name)
        config = info.config.params.vectors
        # 初版只保存一个稠密向量；named vectors 或其他距离类型不能假装兼容。
        if not isinstance(config, models.VectorParams):
            raise VectorStoreError("既有 collection 不是单个稠密向量配置")
        if config.size != self.dimension or config.distance != models.Distance.COSINE:
            raise VectorStoreError("既有 collection 的维度或距离与索引配置不一致")

    def _payload(self, chunk: dict) -> dict:
        if not isinstance(chunk, dict):
            raise VectorStoreError("chunk 必须是对象")
        for field in ("chunk_id", "paper_id", "parse_revision"):
            _nonempty(chunk.get(field), field)
        if type(chunk.get("pdf_page")) is not int or chunk["pdf_page"] <= 0:
            raise VectorStoreError("pdf_page 必须是从 1 开始的正整数")
        for field in ("text_sha256", "pdf_sha256"):
            value = chunk.get(field)
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise VectorStoreError(f"{field} 必须是完整的小写 SHA-256")
        return {**{field: chunk[field] for field in PAYLOAD_FIELDS},
                "index_profile_id": self.index_profile_id}

    def _vector(self, vector: object) -> list[float]:
        if not isinstance(vector, (list, tuple)) or len(vector) != self.dimension:
            raise VectorStoreError("向量维度不等于索引配置")
        if any(type(value) not in (int, float) or not isfinite(value) for value in vector):
            raise VectorStoreError("向量必须全部为有限数值")
        # cosine 需要有方向的非零向量；零向量虽然长度正确，仍不能有效比较相似度。
        if not any(value != 0 for value in vector):
            raise VectorStoreError("cosine 索引不能接受全零向量")
        return [float(value) for value in vector]

    def _cosine_vector(self, vector: object) -> list[float]:
        """得到 cosine 使用的单位方向，先缩放避免巨大/微小数值平方溢出。

        Qdrant 的 cosine 本就保存归一化向量。先在 Python 中稳定地计算同一
        方向，再交给客户端，既不改变相似度，也避免 float32 内部范数溢出。
        原始模型返回值仍由上层缓存保存，以便重新核对。
        """
        checked = self._vector(vector)
        scale = max(abs(value) for value in checked)
        scaled = [value / scale for value in checked]
        length = hypot(*scaled)
        return [value / length for value in scaled]

    def _expected(self, chunks: Sequence[dict]) -> dict[str, dict]:
        if not chunks:
            raise VectorStoreError("完整性核对至少需要一条 chunk")
        expected: dict[str, dict] = {}
        for chunk in chunks:
            payload = self._payload(chunk)
            identifier = point_id(self.index_profile_id, payload["chunk_id"])
            if identifier in expected:
                raise VectorStoreError("输入含重复 chunk_id")
            expected[identifier] = payload
        return expected

    def upsert(self, chunks: Sequence[dict], vectors: Sequence[Sequence[float]]) -> int:
        """整批验证后才写入，同一确定性 ID 再写不会增加点数。

        调用者应先把模型响应原子保存到 embedding 缓存，再调用本方法。
        如进程在 SQLite 进度提交前中断，重跑可复用缓存和这些相同点 ID。
        """
        if not chunks or len(chunks) != len(vectors):
            raise VectorStoreError("chunks 和 vectors 必须非空且数量一致")
        expected = self._expected(chunks)
        points = [
            models.PointStruct(id=identifier, payload=payload, vector=self._cosine_vector(vector))
            for (identifier, payload), vector in zip(expected.items(), vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def _check_point(self, record: object, expected_payload: dict) -> None:
        identifier = point_id(self.index_profile_id, expected_payload["chunk_id"])
        if str(record.id) != identifier:
            raise VectorStoreError("保存的 point ID 与确定性 UUID 不一致")
        if not isinstance(record.payload, dict):
            raise VectorStoreError("保存的 point 缺少 payload")
        for field, expected_value in expected_payload.items():
            actual_value = record.payload.get(field)
            # bool 在 Python 中等于某些整数，页码仍要求准确的整数类型。
            if actual_value != expected_value or type(actual_value) is not type(expected_value):
                raise VectorStoreError(f"保存的 point 字段 {field} 与 SQLite 来源不一致")
        self._vector(record.vector)

    def completed_chunk_ids(self, chunks: Sequence[dict]) -> set[str]:
        """返回已经存在且通过核对的 chunk ID，缺少的点留给调用者继续处理。

        只查本次指定的确定性 ID，因此可给出一个批次或完整版本。发现已有点
        的来源或向量异常会失败，不能把可疑点算作完成，也不能宣告 ready。
        """
        expected = self._expected(chunks)
        identifiers = list(expected)
        completed: set[str] = set()
        for start in range(0, len(identifiers), 128):
            records = self.client.retrieve(
                collection_name=self.collection_name, ids=identifiers[start:start + 128],
                with_payload=True, with_vectors=True,
            )
            for record in records:
                identifier = str(record.id)
                if identifier not in expected:
                    raise VectorStoreError("按 ID 回查返回了未请求的 point")
                payload = expected[identifier]
                self._check_point(record, payload)
                completed.add(payload["chunk_id"])
        return completed

    def collection_count(self) -> int:
        return int(self.client.count(collection_name=self.collection_name, exact=True).count)

    def delete_temporary_collection(self) -> None:
        """关闭试验 collection 的文件句柄后删除，保留正式 collection。

        qdrant-client 1.19.1 的本地 delete_collection 会从管理列表移除
        collection，却没有先 close 它的 SQLite storage。Windows 因打开
        的句柄拒绝删除文件，而 SDK 使用 ignore_errors 会悄悄留下目录。
        当前没有公开的单 collection 关闭接口，因此在此处隔离这个已核对
        的本地 SDK 兼容处理；不修改已安装依赖，也不关闭共享客户端。
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*_smoke_[0-9a-f]{12}",
                            self.collection_name):
            raise VectorStoreError("只允许删除程序生成的 smoke 临时 collection")
        local = self.client._client
        if not isinstance(local, QdrantLocal):
            raise VectorStoreError("临时 collection 清理仅支持本项目的本地 Qdrant")
        target = local._collection_path(self.collection_name)
        if target is None:
            raise VectorStoreError("临时 collection 必须有明确的磁盘目录")
        target_path = Path(target).resolve()
        root_path = self.path.resolve()
        # 删除前核对绝对目标必须位于预期索引目录内；不接受目录本身或目录外目标。
        if target_path == root_path or not target_path.is_relative_to(root_path):
            raise VectorStoreError("临时 collection 的目录超出了预期 Qdrant 根目录")
        if self.client.collection_exists(self.collection_name):
            local._get_collection(self.collection_name).close()
        self.client.delete_collection(self.collection_name)
        if self.client.collection_exists(self.collection_name) or target_path.exists():
            raise VectorStoreError("临时 collection 的元数据或磁盘目录未完全删除")

    def validate(
        self, chunks: Sequence[dict], vectors: Sequence[Sequence[float]] | None = None,
    ) -> dict:
        """严格核对所给完整版本范围里的点数、ID、来源哈希及向量维度。

        首先按完整论文/版本配对遍历。筛选时刻意不隐藏 profile 不同的点，
        否则错误 profile 的额外点会被过滤掉，可能把不一致的库误报为正确。
        只有本方法成功返回后，上层才可把相同版本的 SQLite 状态写成 ready。
        """
        self.ensure_collection()
        expected = self._expected(chunks)
        expected_vectors: dict[str, list[float]] | None = None
        if vectors is not None:
            if len(vectors) != len(chunks):
                raise VectorStoreError("缓存向量数与 chunks 数量不一致")
            expected_vectors = {
                identifier: self._cosine_vector(vector)
                for identifier, vector in zip(expected, vectors, strict=True)
            }
        pairs = sorted({(payload["paper_id"], payload["parse_revision"])
                        for payload in expected.values()})
        scope_filter = filter_for_versions(pairs)
        count = int(self.client.count(
            collection_name=self.collection_name, count_filter=scope_filter, exact=True,
        ).count)
        if count != len(expected):
            raise VectorStoreError(f"版本范围点数不符：应有 {len(expected)}，实际 {count}")
        seen: set[str] = set()
        offset = None
        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.collection_name, scroll_filter=scope_filter,
                limit=128, offset=offset, with_payload=True, with_vectors=True,
            )
            for record in records:
                identifier = str(record.id)
                if identifier not in expected or identifier in seen:
                    raise VectorStoreError("版本范围中含额外或重复 point ID")
                self._check_point(record, expected[identifier])
                if expected_vectors is not None:
                    # 本地 Qdrant 用 float32 保存单位方向，允许其舍入误差；
                    # 较大差异说明来源虽相同，但向量可能串位或被错误覆盖。
                    if any(abs(actual - cached) > 1e-5
                           for actual, cached in zip(record.vector, expected_vectors[identifier],
                                                     strict=True)):
                        raise VectorStoreError("保存的向量方向与对应 chunk 的模型缓存不一致")
                seen.add(identifier)
            if next_offset is None:
                break
            if next_offset == offset:
                raise VectorStoreError("Qdrant 遍历游标没有前进")
            offset = next_offset
        if seen != set(expected):
            raise VectorStoreError("保存的完整 point ID 集合与 SQLite chunks 不一致")
        return {
            "status": "success", "collection_name": self.collection_name,
            "index_profile_id": self.index_profile_id, "dimension": self.dimension,
            "distance": "cosine", "expected_count": len(expected), "verified_count": len(seen),
            "selected_versions": [{"paper_id": paper, "parse_revision": revision}
                                  for paper, revision in pairs],
            "point_ids_match": True, "payload_hashes_match": True,
            "vectors_finite_and_nonzero": True,
            "cached_vector_directions_match": True if expected_vectors is not None else None,
        }
