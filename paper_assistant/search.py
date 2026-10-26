"""D4 任务 E：把问题转换为向量，返回能够回查的论文原文候选。

这是后续问答流程的检索入口。相似度只用于候选排序，不能证明论文
回答了问题；本模块不调用聊天模型，也不产生 answered / 拒答结论。
Qdrant 负责寻找位置，SQLite 负责提供正文，二者的身份必须完全对应。
"""

from collections.abc import Sequence
from copy import deepcopy
from math import hypot, isfinite
from time import perf_counter
from typing import Callable
from uuid import UUID

from qdrant_client import models

from paper_assistant.config import EmbeddingSettings
from paper_assistant.deadline import DeadlineExceeded, remaining
from paper_assistant.embedding_client import EmbeddingAPIError, embed_texts
from paper_assistant.indexing import make_index_profile, validate_vectors
from paper_assistant.retrieval import PAYLOAD_FIELDS, QdrantStore, filter_for_versions, point_id
from paper_assistant.storage import PaperStore


def _statistics() -> dict:
    """未发请求时所有次数为零；未知的供应商用量用 None 表示。"""
    return {
        "embedding_requests": 0, "failed_requests": 0, "total_tokens": None,
        "provider_elapsed_seconds": None, "embedding_elapsed_seconds": 0.0,
        "query_elapsed_seconds": 0.0, "total_elapsed_seconds": 0.0,
    }


class SearchError(ValueError):
    """检索失败的安全摘要，同时携带失败阶段和本次真实调用统计。

    无命中是一次成功执行的空结果，不能用这个异常表示。异常消息不复制
    未知 SDK 的任意原始文本，避免服务将请求内容或认证信息回显到报告。
    """

    def __init__(self, message: str, *, stage: str = "input", statistics: dict | None = None,
                 status="tool_error", code="search_error"):
        super().__init__(message)
        self.stage, self.status, self.code = stage, status, code
        self.statistics = deepcopy(statistics if statistics is not None else _statistics())


def validate_allowed_point_ids(allowed_point_ids) -> list[str] | None:
    """Accept only an explicit nonempty set of canonical UUID strings.

    Source-qualified callers construct these IDs from verified chunks and the
    current profile. None retains the original version-only search. Empty
    verified scopes must stop in the caller, never widen into an unfiltered
    search. Return an independent deterministic snapshot of the whitelist.
    """
    if allowed_point_ids is None:
        return None
    if not isinstance(allowed_point_ids, (list, tuple, set, frozenset)) or not allowed_point_ids:
        raise SearchError("allowed_point_ids 必须是非空的规范 UUID 集合")
    checked = []
    for identifier in allowed_point_ids:
        if type(identifier) is not str:
            raise SearchError("point 白名单只能包含规范 UUID 字符串")
        try:
            canonical = str(UUID(identifier))
        except (ValueError, AttributeError) as error:
            raise SearchError("point 白名单含有非法 UUID") from error
        if canonical != identifier or identifier in checked:
            raise SearchError("point 白名单 UUID 不规范或重复")
        checked.append(identifier)
    return sorted(checked)


class EvidenceSearcher:
    """检索一个明确的索引配置中已完整入库的论文/处理版本。

    调用者负责以只读模式打开 SQLite，并在打开 QdrantStore 前确认正式
    collection 存在。QdrantStore 构造器用于构建时会创建缺失的 collection，
    因此 CLI 的打开步骤不能直接把“搜索”变成一次空库创建操作。
    本对象也会检查 collection 存在，且不会调用 ensure_collection。
    """

    supports_remaining_time = True

    def __init__(
        self, store: PaperStore, vectors: QdrantStore, settings: EmbeddingSettings,
        profile: dict, embedder: Callable = embed_texts,
    ) -> None:
        self.store, self.vectors, self.settings = store, vectors, settings
        # 索引配置没有 API 密钥。复制后避免外部字典在检索过程中被修改，
        # 造成检查的是一套模型而实际查询使用另一套身份。
        self.profile = deepcopy(profile)
        self.embedder = embedder
        self._check_configuration()

    def _check_configuration(self) -> None:
        """核对完整配置指纹，不只比较模型名或短 profile ID。

        同一模型但不同 endpoint、输入方式、预处理或维度，也不能混用。
        API 密钥可以正常轮换：密钥不影响向量的含义，也不进入配置指纹。
        """
        try:
            if not isinstance(self.profile, dict) or make_index_profile(self.settings) != self.profile:
                raise SearchError("问题向量配置与已有索引配置不一致", stage="configuration")
            if (self.vectors.index_profile_id != self.profile["index_profile_id"]
                    or self.vectors.dimension != self.profile["recipe"]["dimension"]
                    or self.vectors.collection_name != self.profile["collection_name"]):
                raise SearchError("向量库身份、维度或 collection 与索引配置不一致", stage="configuration")
            if not isinstance(self.settings.api_key, str) or not self.settings.api_key.strip():
                raise SearchError("向量服务配置缺少 API 密钥", stage="configuration")
            if not callable(self.embedder):
                raise SearchError("embedder 必须是可调用的向量接口", stage="configuration")
        except SearchError:
            raise
        except Exception as error:
            raise SearchError("无法核对问题向量配置：" + type(error).__name__, stage="configuration") from error

    @staticmethod
    def _check_input(query: object, selected_versions: object, top_k: object) -> list[tuple[str, str]]:
        """先拒绝模糊或错误输入，避免无效请求消耗一次付费调用。

        每项必须同时给论文和处理版本；不能分别传两组列表形成交叉范围。
        问题只检查非空，保留首尾空白等原始文字，因为索引的预处理为 identity。
        """
        if not isinstance(query, str) or not query.strip():
            raise SearchError("query 必须是非空问题字符串")
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise SearchError("top_k 必须是 1 至 20 的整数")
        if (not isinstance(selected_versions, Sequence)
                or isinstance(selected_versions, (str, bytes)) or not selected_versions):
            raise SearchError("必须提供至少一个明确的论文/处理版本配对")
        pairs = []
        for pair in selected_versions:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise SearchError("selected_versions 每项必须是 (paper_id, parse_revision)")
            if any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in pair):
                raise SearchError("论文 ID 和处理版本必须是没有首尾空白的非空字符串")
            checked = (pair[0], pair[1])
            if checked in pairs:
                raise SearchError("不能重复选择相同论文/处理版本")
            pairs.append(checked)
        return pairs

    def _ready_filter(self, pairs: list[tuple[str, str]]):
        """收费前检查 ready 门槛，并核对实际范围点数。

        SQLite 的 ready 状态是 D 构建后完整验证的记录。这里继续检查版本
        存在、完成数等于版本总数，以及 Qdrant 磁盘中的对应数量，避免已知
        的缺库/部分入库仍发问题向量请求。全部点的向量缓存方向复核由 D 的
        validate_index 负责；E 再逐条严格核对实际返回的候选身份和正文。
        """
        profile_id = self.profile["index_profile_id"]
        try:
            versions = {(row["paper_id"], row["parse_revision"]): row for row in self.store.list_versions()}
            expected_count = 0
            for paper, revision in pairs:
                version = versions.get((paper, revision))
                if version is None:
                    raise SearchError("所选论文或处理版本尚未保存到 SQLite", stage="ready")
                count = version.get("chunk_count")
                if type(count) is not int or count <= 0:
                    raise SearchError("所选处理版本没有合法的完整 chunk 数量", stage="ready")
                state = self.store.get_index_import(paper, revision, profile_id)
                if (state is None or state["status"] != "ready"
                        or type(state.get("completed_count")) is not int or state["completed_count"] != count):
                    raise SearchError("所选论文/处理版本在当前索引配置下尚未完整 ready", stage="ready")
                expected_count += count
            if not self.vectors.client.collection_exists(self.vectors.collection_name):
                raise SearchError("正式 Qdrant collection 不存在，请先完成任务 D", stage="ready")
            # filter_for_versions 内部是若干完整 pair 的 OR，再与 profile 条件
            # 做 AND；例如选择 (A,r1)、(B,r2)，不会误放行 (A,r2)。
            scope = filter_for_versions(pairs, index_profile_id=profile_id)
            count = self.vectors.client.count(
                collection_name=self.vectors.collection_name, count_filter=scope, exact=True,
            ).count
            if type(count) is not int or count != expected_count:
                raise SearchError("所选 Qdrant 范围点数与 SQLite ready 数量不一致", stage="ready")
            return scope
        except SearchError:
            raise
        except Exception as error:
            raise SearchError("检索前完整入库检查失败：" + type(error).__name__, stage="ready") from error

    @staticmethod
    def _query_direction(vector: list[float]) -> list[float]:
        """用稳定的单位方向查询，与 D 中 cosine 文档向量的处理一致。

        先缩放再计算范数，避免巨大或极小数值直接平方造成数值问题。
        这个操作只规范向量方向，没有修改问题文字或增加模型输入指令。
        """
        scale = max(abs(value) for value in vector)
        scaled = [value / scale for value in vector]
        length = hypot(*scaled)
        return [value / length for value in scaled]

    def _read_hit(self, hit: object, rank: int, pairs: set[tuple[str, str]], seen: set[str]) -> dict:
        """先校验位置，再从 SQLite 取正文；绝不展示 payload 中的伪正文。

        get_chunk 已经核对原文 JSON、查询列、论文元数据、版本及 PDF 来源。
        此处把这些可信来源再与 Qdrant payload 逐字段比较，防止向量点串位、
        页码错误或其他论文混入。任一候选损坏就明确失败，不静默丢弃后
        声称返回了完整 top-k。
        """
        payload = getattr(hit, "payload", None)
        if not isinstance(payload, dict) or set(payload) != set(PAYLOAD_FIELDS) | {"index_profile_id"}:
            raise SearchError("候选缺少完整的 Qdrant 来源 payload", stage="evidence")
        chunk_id = payload.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip() or chunk_id in seen:
            raise SearchError("候选 chunk ID 为空、类型错误或重复", stage="evidence")
        if (payload.get("paper_id"), payload.get("parse_revision")) not in pairs:
            raise SearchError("候选超出选定的论文/处理版本范围", stage="evidence")
        if str(getattr(hit, "id", "")) != point_id(self.profile["index_profile_id"], chunk_id):
            raise SearchError("候选 point UUID 与 profile/chunk ID 不一致", stage="evidence")
        score = getattr(hit, "score", None)
        if type(score) not in (int, float) or not isfinite(score):
            raise SearchError("候选相似度分数不是有限数值", stage="evidence")
        # 本配置明确使用 cosine，合法值在 -1 到 1 之间。float32 的归一化
        # 和点积可能带来很小的舍入偏差，允许 1e-5；更大偏差属于异常结果，
        # 不能作为“非常相似”的证据分数展示。
        if not -1.0 - 1e-5 <= score <= 1.0 + 1e-5:
            raise SearchError("候选相似度分数超出 cosine 的合法范围", stage="evidence")
        chunk = self.store.get_chunk(chunk_id)
        if chunk is None:
            raise SearchError("候选 chunk ID 在 SQLite 中不存在", stage="evidence")
        expected_payload = {field: chunk[field] for field in PAYLOAD_FIELDS}
        expected_payload["index_profile_id"] = self.profile["index_profile_id"]
        for field, expected in expected_payload.items():
            if payload[field] != expected or type(payload[field]) is not type(expected):
                raise SearchError("候选来源字段 " + field + " 与 SQLite 不一致", stage="evidence")
        text = chunk.get("text")
        if (not isinstance(text, str) or not text.strip()):
            raise SearchError("SQLite 候选原文为空或文本哈希不一致", stage="evidence")
        # 返回完整 chunk 中的 segment_id、字符区间、原始块/行索引等字段，
        # 后续可以定位 PDF，也可以核对这段文字在处理快照中的精确来源。
        seen.add(chunk_id)
        return {**chunk, "rank": rank, "score": float(score), "point_id": str(hit.id),
                "index_profile_id": self.profile["index_profile_id"]}

    def search_evidence(self, query: str, selected_versions: Sequence[tuple[str, str]], top_k: int = 5,
                        *, allowed_point_ids=None, remaining_seconds=None) -> dict:
        """一次问题 embedding、一次带范围过滤的查询，返回实际数量的证据候选。

        调用可以多次进行，每次统计独立。重复问题仍属于新的一次检索请求；
        文档 embedding 的缓存/入库由 D 负责，不会在这里重新生成文档向量。
        可选 point 白名单只收紧查询；完整 ready 数量仍按原版本/profile 范围核验。
        """
        statistics = _statistics()
        start = perf_counter()
        stage = "input"
        try:
            pairs = self._check_input(query, selected_versions, top_k)
            point_ids = validate_allowed_point_ids(allowed_point_ids)
            remaining(remaining_seconds)
            stage = "configuration"
            self._check_configuration()
            stage = "ready"
            scope = self._ready_filter(pairs)
            remaining(remaining_seconds)
            if point_ids is not None:
                scope = models.Filter(must=[scope, models.HasIdCondition(has_id=point_ids)])
            stage = "embedding"
            # 在调用前计数：网络超时等失败请求同样真实发起过一次。
            timed = remaining_seconds is not None
            if timed and getattr(self.embedder, "supports_remaining_time", False) is not True:
                raise SearchError("预算检索需要显式 deadline-aware embedder 或 LegacyEmbedderAdapter", stage="configuration")
            if not timed:
                statistics["embedding_requests"] = 1
            embedding_start = perf_counter()
            try:
                options = {"remaining_seconds": remaining_seconds} if timed else {}
                batch = self.embedder([query], self.settings, **options)
                if timed:
                    statistics.update(failed_requests=0 if type(batch.request_attempts) is int else None,
                                      embedding_requests=batch.request_attempts,
                                      request_started=batch.request_started,
                                      timeout_seconds=batch.timeout_seconds,
                                      accounting_basis=batch.accounting_basis)
                usage = batch.total_tokens
                if type(usage) is int and usage >= 0:
                    statistics["total_tokens"] = usage
                provider_elapsed = batch.elapsed_seconds
                if type(provider_elapsed) in (int, float) and isfinite(provider_elapsed) and provider_elapsed >= 0:
                    statistics["provider_elapsed_seconds"] = float(provider_elapsed)
                remaining(remaining_seconds)
                validate_vectors(batch.vectors, 1, self.profile["recipe"]["dimension"])
                direction = self._query_direction(batch.vectors[0])
            except EmbeddingAPIError as error:
                if timed:
                    statistics.update(deepcopy(error.statistics))
                else:
                    statistics["failed_requests"] = 1
                raise
            except DeadlineExceeded:
                raise
            except Exception:
                statistics["failed_requests"] = statistics["embedding_requests"]
                raise
            finally:
                statistics["embedding_elapsed_seconds"] = round(perf_counter() - embedding_start, 6)
            remaining(remaining_seconds)
            stage = "query"
            query_start = perf_counter()
            try:
                response = self.vectors.client.query_points(
                    collection_name=self.vectors.collection_name, query=direction,
                    query_filter=scope, limit=top_k, with_payload=True, with_vectors=False,
                )
            finally:
                statistics["query_elapsed_seconds"] = round(perf_counter() - query_start, 6)
            remaining(remaining_seconds)
            stage = "evidence"
            hits = response.points
            if not isinstance(hits, list) or len(hits) > top_k:
                raise SearchError("Qdrant 返回的候选列表类型或数量不合法", stage="evidence")
            if point_ids is not None and any(str(getattr(hit, "id", "")) not in point_ids for hit in hits):
                raise SearchError("Qdrant 候选 point 超出本轮白名单", stage="evidence")
            seen: set[str] = set()
            results = []
            for rank, hit in enumerate(hits, start=1):
                remaining(remaining_seconds)
                results.append(self._read_hit(hit, rank, set(pairs), seen))
                remaining(remaining_seconds)
            statistics["total_elapsed_seconds"] = round(perf_counter() - start, 6)
            result = {
                "status": "success" if results else "no_hits", "query": query,
                "index_profile_id": self.profile["index_profile_id"],
                "selected_versions": [{"paper_id": paper, "parse_revision": revision} for paper, revision in pairs],
                "top_k": top_k, "results": results, "returned_count": len(results), "statistics": statistics,
            }
            if point_ids is not None:
                result["allowed_point_ids"] = deepcopy(point_ids)
            return result
        except Exception as error:
            statistics["total_elapsed_seconds"] = round(perf_counter() - start, 6)
            expired = isinstance(error, DeadlineExceeded) or (isinstance(error, EmbeddingAPIError) and error.status == "budget_exceeded")
            if not expired:
                try:
                    remaining(remaining_seconds)
                except DeadlineExceeded:
                    expired = True
                    statistics["interrupted_failure"] = {"code": getattr(error, "code", "local_error"), "stage": stage}
            if expired:
                raise SearchError("本轮检索截止预算已到", stage=stage, statistics=statistics,
                                  status="budget_exceeded", code="deadline_exceeded") from None
            if isinstance(error, SearchError):
                # 低层校验尚未拿到本轮统计；抛给调用者前统一补上实际计数。
                raise SearchError(str(error), stage=error.stage, statistics=statistics,
                                  status=error.status, code=error.code) from error
            if isinstance(error, EmbeddingAPIError):
                message = str(error)  # 原客户端已过滤供应商回显，只保留安全错误码。
            else:
                message = "证据检索失败：" + type(error).__name__
            raise SearchError(message, stage=stage, statistics=statistics) from error
