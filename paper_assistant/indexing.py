"""D4 任务 D：协调向量缓存、Qdrant 写入和 SQLite 导入状态。

正文仍从 SQLite 读取。这里不生成答案，也不把相似度当成事实正确性。
一次向量请求成功后先原子保存整个响应，再写 Qdrant；这两个动作的顺序
让“API 已成功、向量库写入失败”的重试可以复用缓存，不再支付同一批请求。
"""

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from paper_assistant.config import EmbeddingSettings
from paper_assistant.embedding_client import EmbeddingBatch, embed_texts
from paper_assistant.retrieval import QdrantStore, point_id
from paper_assistant.storage import PaperStore


class IndexingError(ValueError):
    """配置、缓存或导入一致性没有满足要求。"""


def canonical_bytes(value: object) -> bytes:
    """统一字典顺序和空白，保证相同内容产生同一个完整 SHA-256。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """先写同目录临时文件，刷盘后替换，避免中断留下半个可读 JSON。

    临时文件与目标在同一文件系统，os.replace 不会先删掉旧目标再慢慢写。
    这是单进程工作流；Qdrant 的目录锁防止两个正式构建器同时运行。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def make_index_profile(settings: EmbeddingSettings) -> dict:
    """模型、维度、输入方式变化都会创建新身份，密钥不参与指纹或报告。

    当前明确要求指定维度，避免以“默认维度”建库后与服务实际返回不一致。
    endpoint 只接受没有账号、密码、查询参数或 fragment 的普通 API 基地址。
    输入原样传给 D2 已跑通的兼容接口，不添加 query/document 指令或改写文字。
    """
    if settings.backend != "dashscope" or not settings.model.strip():
        raise IndexingError("索引构建当前只支持已实现的 dashscope 文本向量客户端")
    if type(settings.dimension) is not int or settings.dimension <= 0:
        raise IndexingError("请在 EMBEDDING_DIMENSION 明确指定已验证的正整数维度")
    endpoint = urlsplit(settings.base_url or "")
    if (endpoint.scheme not in ("https", "http") or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment):
        raise IndexingError("向量 API 基地址不合法或包含不应进入索引记录的认证信息")
    recipe = {
        "backend": settings.backend, "model": settings.model, "dimension": settings.dimension,
        "base_url": (settings.base_url or "").rstrip("/"),
        "input_mode": "openai-compatible-default", "request_schema": "embeddings-input-array-v1",
        "encoding_format": "float", "preprocessing": "identity-text-v1", "distance": "cosine",
    }
    fingerprint = digest(recipe)
    profile_id = "ep_" + fingerprint[:16]
    return {"index_profile_id": profile_id, "recipe_sha256": fingerprint,
            "collection_name": "paper_chunks_" + profile_id, "recipe": recipe}


def save_index_profile(root: Path, profile: dict) -> Path:
    """固定配置清单不可静默覆盖；短 ID 碰撞时由完整内容核对拒绝混用。"""
    target = root / "profiles" / (profile["index_profile_id"] + ".json")
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != profile:
            raise IndexingError("已有索引配置清单内容冲突，不能覆盖")
    else:
        atomic_json(target, profile)
    return target


def validate_vectors(vectors: list, count: int, dimension: int) -> None:
    """数量、维度、有限数值和非零长度都必须正确，不能截断或补零凑齐。"""
    if not isinstance(vectors, list) or len(vectors) != count:
        raise IndexingError("返回向量数量与当前输入批次不一致")
    for vector in vectors:
        if (not isinstance(vector, list) or len(vector) != dimension
                or any(type(v) not in (int, float) or not isfinite(v) for v in vector)):
            raise IndexingError("向量维度不符或含非有限数值")
        norm_squared = sum(float(v) * float(v) for v in vector)
        if not isfinite(norm_squared) or norm_squared <= 0:
            raise IndexingError("向量长度为零或溢出，不能用于 cosine 比较")


class EmbeddingCache:
    """一批一个文件，保留成功响应、实际 usage 和向量与 chunk 的绑定。

    文件名由这批输入身份决定，与运行时间无关。磁盘里保存原始向量；
    Qdrant 的 cosine 存储会归一化向量，读回验证由检索存储层处理。
    缓存损坏会明确停止，绝不把坏缓存当成“没有缓存”并偷偷重新收费。
    """

    def __init__(self, root: Path, profile: dict):
        self.profile = profile
        self.path = root / profile["index_profile_id"]
        self.records: dict[str, dict] = {}
        self.batches: list[dict] = []
        for path in sorted(self.path.glob("batches/b_*.json")):
            self._read_batch(path)

    def _read_batch(self, path: Path) -> None:
        try:
            wrapped = json.loads(path.read_text(encoding="utf-8"))
            body = wrapped["batch"]
            if wrapped["sha256"] != digest(body) or body["index_profile_id"] != self.profile["index_profile_id"]:
                raise IndexingError("缓存批次哈希或索引配置不匹配")
            if body["recipe_sha256"] != self.profile["recipe_sha256"] or not body["records"]:
                raise IndexingError("缓存批次配置或条目无效")
            records = body["records"]
            validate_vectors([r["vector"] for r in records], len(records), self.profile["recipe"]["dimension"])
            keys = [{key: r[key] for key in ("chunk_id", "text_sha256")} for r in records]
            if path.name != "b_" + digest(keys) + ".json" or len({r["chunk_id"] for r in records}) != len(records):
                raise IndexingError("缓存文件名或批内 chunk 身份不一致")
            for record in records:
                if record["point_id"] != point_id(self.profile["index_profile_id"], record["chunk_id"]):
                    raise IndexingError("缓存 point ID 与确定性身份不一致")
                old = self.records.get(record["chunk_id"])
                if old is not None and old != record:
                    raise IndexingError("不同缓存批次中同一个 chunk 的向量或来源冲突")
                self.records[record["chunk_id"]] = record
            self.batches.append({key: body[key] for key in ("generated_at_utc", "total_tokens", "elapsed_seconds")})
        except IndexingError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise IndexingError("无法完整读取或校验已有向量缓存") from error

    def load(self, chunk: dict) -> list[float] | None:
        record = self.records.get(chunk["chunk_id"])
        if record is None:
            return None
        for key in ("paper_id", "parse_revision", "text_sha256", "pdf_sha256", "pdf_page"):
            if record.get(key) != chunk[key] or type(record.get(key)) is not type(chunk[key]):
                raise IndexingError("缓存向量的来源与 SQLite chunk 不一致")
        return list(record["vector"])

    def save_batch(self, chunks: list[dict], batch: EmbeddingBatch) -> None:
        # 输入错误必须在任何磁盘写入之前拒绝，不能先留下一个以后连
        # 初始化都读不通的坏批次。真实入口虽已验证SQLite，缓存API仍自检。
        if not isinstance(chunks, list) or not chunks or any(not isinstance(c, dict) for c in chunks):
            raise IndexingError("缓存输入必须是非空 chunk 对象列表")
        identifiers = []
        for chunk in chunks:
            for key in ("chunk_id", "paper_id", "parse_revision"):
                if not isinstance(chunk.get(key), str) or not chunk[key].strip():
                    raise IndexingError("缓存输入缺少合法的 chunk 来源身份")
            for key in ("text_sha256", "pdf_sha256"):
                if not isinstance(chunk.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", chunk[key]):
                    raise IndexingError("缓存输入缺少完整 SHA-256")
            if type(chunk.get("pdf_page")) is not int or chunk["pdf_page"] <= 0:
                raise IndexingError("缓存输入页码必须是正整数")
            text = chunk.get("text")
            if not isinstance(text, str) or not text.strip() or hashlib.sha256(text.encode("utf-8")).hexdigest() != chunk["text_sha256"]:
                raise IndexingError("缓存输入正文与文本哈希不一致")
            identifiers.append(chunk["chunk_id"])
        if len(set(identifiers)) != len(identifiers):
            raise IndexingError("缓存批次不能包含重复 chunk")
        if batch.total_tokens is not None and (type(batch.total_tokens) is not int or batch.total_tokens < 0):
            raise IndexingError("实际 token 用量必须为非负整数或缺失")
        if type(batch.elapsed_seconds) not in (int, float) or not isfinite(batch.elapsed_seconds) or batch.elapsed_seconds < 0:
            raise IndexingError("向量响应耗时无效")
        validate_vectors(batch.vectors, len(chunks), self.profile["recipe"]["dimension"])
        records = []
        for chunk, vector in zip(chunks, batch.vectors):
            record = {key: chunk[key] for key in ("chunk_id", "paper_id", "parse_revision", "pdf_page", "pdf_sha256", "text_sha256")}
            record.update(point_id=point_id(self.profile["index_profile_id"], chunk["chunk_id"]), vector=list(vector))
            if chunk["chunk_id"] in self.records:
                raise IndexingError("已有缓存不能被新响应静默覆盖")
            records.append(record)
        keys = [{key: r[key] for key in ("chunk_id", "text_sha256")} for r in records]
        body = {
            "index_profile_id": self.profile["index_profile_id"], "recipe_sha256": self.profile["recipe_sha256"],
            "generated_at_utc": datetime.now(timezone.utc).isoformat(), "total_tokens": batch.total_tokens,
            "elapsed_seconds": batch.elapsed_seconds, "records": records,
        }
        target = self.path / "batches" / ("b_" + digest(keys) + ".json")
        if target.exists():
            raise IndexingError("目标缓存批次已存在，拒绝覆盖")
        atomic_json(target, {"sha256": digest(body), "batch": body})
        self._read_batch(target)

    def stats(self) -> dict:
        known = [b["total_tokens"] for b in self.batches if type(b["total_tokens"]) is int]
        return {"vector_count": len(self.records), "successful_response_batches": len(self.batches),
                "known_total_tokens": sum(known), "usage_missing_batches": len(self.batches) - len(known)}


class IndexBuilder:
    """以一篇明确版本为最小发布单位，批次完成不等于版本 ready。"""

    def __init__(self, store: PaperStore, vectors: QdrantStore, cache: EmbeddingCache,
                 settings: EmbeddingSettings, profile: dict, embedder: Callable = embed_texts,
                 on_progress: Callable | None = None):
        if make_index_profile(settings) != profile or cache.profile != profile:
            raise IndexingError("构建器配置与缓存索引身份不一致")
        if (vectors.index_profile_id != profile["index_profile_id"]
                or vectors.dimension != profile["recipe"]["dimension"]
                or vectors.collection_name != profile["collection_name"]):
            raise IndexingError("构建器配置与目标 Qdrant collection 不一致")
        self.store, self.vectors, self.cache = store, vectors, cache
        self.settings, self.profile, self.embedder = settings, profile, embedder
        self.on_progress = on_progress
        self.requests: list[dict] = []

    def _notify(self, event: dict) -> None:
        if self.on_progress:
            self.on_progress(event)

    def _generate(self, chunks: list[dict]) -> None:
        # 请求统计在发出前增加，失败调用同样属于真实请求；无无限自动重试。
        event = {"request_no": len(self.requests) + 1, "chunk_count": len(chunks),
                 "chunk_ids": [c["chunk_id"] for c in chunks], "status": "pending",
                 "total_tokens": None, "started_at_utc": datetime.now(timezone.utc).isoformat()}
        self.requests.append(event)
        self._notify({"stage": "request_started", "request": event})
        start = perf_counter()
        try:
            batch = self.embedder([c["text"] for c in chunks], self.settings)
            # 即使后续校验或缓存写失败，服务已返回的真实 usage 也应留在日志中。
            event.update(total_tokens=batch.total_tokens, provider_elapsed_seconds=batch.elapsed_seconds)
            validate_vectors(batch.vectors, len(chunks), self.profile["recipe"]["dimension"])
            self.cache.save_batch(chunks, batch)
            event["status"] = "cached"
        except Exception as error:
            event.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            event["elapsed_seconds"] = round(perf_counter() - start, 6)
            self._notify({"stage": "request_finished", "request": event})

    def smoke(self, chunks: list[dict], batch_size: int = 10) -> dict:
        """使用同一配置的独立 collection，验证后删除试验 collection。

        不写 SQLite 正式导入状态；成功响应缓存在正式配置目录，后续正式
        导入可复用。重复 smoke 同样优先使用已存在的缓存。
        """
        self._check_batch_size(batch_size)
        if not 5 <= len(chunks) <= 10:
            raise IndexingError("试运行应明确选择 5 至 10 条 chunk")
        for offset in range(0, len(chunks), batch_size):
            missing = [c for c in chunks[offset:offset + batch_size] if self.cache.load(c) is None]
            if missing:
                self._generate(missing)
        name = self.profile["collection_name"] + "_smoke_" + uuid4().hex[:12]
        # 复用同一个本地客户端，不同时打开第二个 path 客户端争用文件锁。
        trial = QdrantStore(self.vectors.path, name, self.profile["index_profile_id"], self.settings.dimension,
                            client=self.vectors.client)
        try:
            trial.upsert(chunks, [self.cache.load(c) for c in chunks])
            verification = trial.validate(chunks, [self.cache.load(c) for c in chunks])
            return {"status": "success", "chunk_count": len(chunks), "temporary_collection": name,
                    "formal_import_marked_ready": False, "verification": verification}
        finally:
            trial.delete_temporary_collection()
            trial.close()

    @staticmethod
    def _check_batch_size(batch_size: int) -> None:
        if type(batch_size) is not int or not 1 <= batch_size <= 10:
            raise IndexingError("当前构建批次必须是 1 至 10 条")

    def import_version(self, paper_id: str, parse_revision: str, batch_size: int = 10) -> dict:
        self._check_batch_size(batch_size)
        chunks = self.store.get_version_chunks(paper_id, parse_revision)
        profile_id = self.profile["index_profile_id"]
        old = self.store.get_index_import(paper_id, parse_revision, profile_id)
        start_requests = len(self.requests)
        completed = 0
        import_key = None
        entry = {"paper_id": paper_id, "parse_revision": parse_revision, "index_profile_id": profile_id,
                 "expected_count": len(chunks), "reused_ready": False, "upserted_count": 0, "cached_reused_count": 0}
        try:
            if old and old["status"] == "ready":
                # 不只相信状态标记：重复执行仍复核真正磁盘中的完整向量与来源。
                verification = self._verify_complete(chunks)
                entry.update(status="ready", completed_count=len(chunks), import_key=old["import_key"],
                             reused_ready=True, embedding_requests=0, verification=verification)
                self._notify({"stage": "paper_ready", "paper": entry})
                return entry
            state = self.store.begin_index_import(paper_id, parse_revision, profile_id)
            import_key = state["import_key"]
            existing = self.vectors.completed_chunk_ids(chunks)
            completed = len(existing)
            self.store.set_index_import_progress(import_key, completed)
            missing_points = [c for c in chunks if c["chunk_id"] not in existing]
            for offset in range(0, len(missing_points), batch_size):
                group = missing_points[offset:offset + batch_size]
                cached_count = sum(self.cache.load(c) is not None for c in group)
                to_generate = [c for c in group if self.cache.load(c) is None]
                if to_generate:
                    self._generate(to_generate)
                # cache.save_batch 已完成。此处失败，下一次仍有付费响应可复用。
                vectors = [self.cache.load(c) for c in group]
                self.vectors.upsert(group, vectors)
                completed += len(group)
                self.store.set_index_import_progress(import_key, completed)
                entry["upserted_count"] += len(group)
                entry["cached_reused_count"] += cached_count
                self._notify({"stage": "batch_upserted", "paper_id": paper_id,
                              "completed_count": completed, "expected_count": len(chunks)})
            verification = self._verify_complete(chunks)
            self.store.finish_index_import(import_key, len(chunks))
            entry.update(status="ready", completed_count=len(chunks), import_key=import_key,
                         embedding_requests=len(self.requests) - start_requests, verification=verification)
            self._notify({"stage": "paper_ready", "paper": entry})
            return entry
        except Exception as error:
            # 不复制原始供应商响应或未知异常文本，避免错误日志回显请求/凭据。
            safe_error = "向量导入未通过：" + type(error).__name__
            try:
                current = self.store.get_index_import(paper_id, parse_revision, profile_id)
                if current is not None:
                    import_key = current["import_key"]
                    # 旧 ready 校验不通过，或写完 ready 后报告回调失败：先取消
                    # ready，再记 failed。不能留下已知失效的“可检索”标记。
                    if current["status"] == "ready":
                        self.store.begin_index_import(paper_id, parse_revision, profile_id, completed_count=completed)
                    self.store.fail_index_import(import_key, safe_error, completed_count=completed)
            except Exception as state_error:
                # 磁盘/SQLite本身故障时，记录失败也可能再失败。保留首个
                # 原因，不能让二次异常掩盖原来的导入错误。
                entry["state_recording_error_type"] = type(state_error).__name__
            entry.update(status="failed", completed_count=completed, import_key=import_key,
                         embedding_requests=len(self.requests) - start_requests, error=safe_error)
            try:
                self._notify({"stage": "paper_failed", "paper": entry})
            except Exception as reporting_error:
                entry["reporting_error_type"] = type(reporting_error).__name__
            raise

    def _verify_complete(self, chunks: list[dict]) -> dict:
        """不仅核对 payload，还逐条比较缓存与磁盘向量的归一化方向。

        缓存缺失或向量串位时不继续宣布 ready。这里不会收费自动修补，
        明确失败后重跑正式导入才进入已有点/缓存的恢复流程。
        """
        vectors = [self.cache.load(chunk) for chunk in chunks]
        if any(vector is None for vector in vectors):
            raise IndexingError("完整索引校验缺少对应的已保存向量缓存")
        return self.vectors.validate(chunks, vectors)

    def request_stats(self) -> dict:
        known = [r["total_tokens"] for r in self.requests if type(r["total_tokens"]) is int]
        return {"embedding_requests": len(self.requests), "cached_response_requests": sum(r["status"] == "cached" for r in self.requests),
                "failed_requests": sum(r["status"] == "failed" for r in self.requests),
                "known_total_tokens": sum(known), "usage_missing_requests": len(self.requests) - len(known),
                "request_elapsed_seconds": round(sum(r.get("elapsed_seconds", 0) for r in self.requests), 6)}
