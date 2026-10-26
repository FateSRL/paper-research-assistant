"""只读地复用已经由用户确认的 D4 分块抽样记录。

人工确认与不可变的 chunk 快照分开保存。重跑分块命令时，只有来源、
处理版本和实际样本都仍然相同，才可显示原有的人审状态；这里不会把
程序检查、AI 判断或同一篇论文的其他版本自动当成人工通过。
"""

from datetime import date
import hashlib
import json
from pathlib import Path
import re


REVIEW_RECORD = "artifacts/d4/human_review.json"
SAMPLE_FIELDS = (
    "chunk_id", "text_sha256", "pdf_page", "segment_id", "char_start", "char_end",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sample_identity(sample: dict) -> dict:
    """只取确认范围的六项身份字段，不依赖预览里的状态说明或排版。"""
    if not isinstance(sample, dict):
        raise ValueError("样本必须是对象")
    identity = {field: sample[field] for field in SAMPLE_FIELDS}
    if any(not isinstance(identity[field], str) or not identity[field]
           for field in ("chunk_id", "text_sha256", "segment_id")):
        raise ValueError("样本身份字段不完整")
    if not _SHA256.fullmatch(identity["text_sha256"]):
        raise ValueError("样本文本哈希无效")
    if any(type(identity[field]) is not int
           for field in ("pdf_page", "char_start", "char_end")):
        raise ValueError("页码和字符范围必须是整数")
    if identity["pdf_page"] < 1 or not 0 <= identity["char_start"] < identity["char_end"]:
        raise ValueError("样本范围无效")
    return identity


def review_for_chunk_samples(prepared, project_root, samples=None) -> dict:
    """返回当前版本/样本可继承的人审信息，不写文件、不请求外部服务。

    prepared 已由分块来源核对生成；本函数进一步对比 sidecar 保存的
    PDF、chunks 文件和版本清单哈希。提供 samples 时，也逐项核对实际
    预览顺序，防止改了抽样算法后把另一组样本标成人工确认。未传 samples
    时，只确认 sidecar 中的十条样本确实属于此版本，不能据此批准任意预览。

    pending 表示没有相应确认；outdated 表示已有记录但记录损坏或绑定不符。
    两者都不继承复核人和日期。该状态仅表示十条抽样，不覆盖全篇所有 chunk。
    """
    result = {
        "human_review_status": "pending",
        "human_reviewed_by": None,
        "human_reviewed_at": None,
        "human_review_record": REVIEW_RECORD,
        "human_review_scope": "B: ten preview samples only; not all chunks",
        "human_reviewed_sample_count": 0,
    }
    path = Path(project_root) / REVIEW_RECORD
    try:
        sidecar = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        result["human_review_reason"] = "no_confirmation_record"
        return result
    except (OSError, UnicodeError, ValueError):
        result.update(human_review_status="outdated", human_review_reason="invalid_confirmation_record")
        return result

    try:
        if not isinstance(sidecar, dict) or sidecar.get("schema_revision") != "d4-human-review-v1":
            raise ValueError("人工确认 schema 不符")
        if sidecar.get("human_review_status") != "human_verified":
            raise ValueError("总记录不是人工已确认")
        if sidecar.get("human_reviewed_by") != "user":
            raise ValueError("确认来源不是用户")
        date.fromisoformat(sidecar["human_reviewed_at"])
        records = sidecar["chunk_samples"]
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError("分块确认记录必须是对象数组")
        same_paper = [record for record in records if record.get("paper_id") == prepared.paper_id]
        matches = [record for record in same_paper
                   if record.get("parse_revision") == prepared.parse_revision]
        if not matches:
            result.update(
                human_review_status="outdated" if same_paper else "pending",
                human_review_reason="different_parse_revision" if same_paper else "paper_not_reviewed",
            )
            return result
        if len(matches) != 1:
            raise ValueError("同一论文版本有重复确认")
        record = matches[0]
        if record.get("human_review_status") != "human_verified" or record.get("human_reviewed_by") != "user":
            raise ValueError("此版本没有用户确认")
        reviewed_at = record["human_reviewed_at"]
        date.fromisoformat(reviewed_at)
        if reviewed_at != sidecar["human_reviewed_at"]:
            raise ValueError("确认日期不一致")

        # 直接比较将被保存的准确字节；只比较论文名会误认不同版本的结果。
        manifest = prepared.manifest
        if (manifest["paper_id"] != prepared.paper_id
                or manifest["parse_revision"] != prepared.parse_revision):
            raise ValueError("版本清单身份不符")
        expected_hashes = {
            "pdf_sha256": manifest["recipe"]["pdf_sha256"],
            "chunks_sha256": hashlib.sha256(prepared.files["chunks.jsonl"]).hexdigest(),
            "manifest_sha256": hashlib.sha256(prepared.files["version_manifest.json"]).hexdigest(),
        }
        for field, digest in expected_hashes.items():
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest) or record.get(field) != digest:
                raise ValueError("人工确认来源哈希不符")
        if json.loads(prepared.files["version_manifest.json"]) != manifest:
            raise ValueError("清单对象与清单字节不符")

        recorded_samples = record["samples"]
        if not isinstance(recorded_samples, list) or len(recorded_samples) != 10:
            raise ValueError("确认范围应当为十条样本")
        identities = [_sample_identity(sample) for sample in recorded_samples]
        if len({item["chunk_id"] for item in identities}) != len(identities):
            raise ValueError("样本 ID 重复")
        current_chunks = {chunk["chunk_id"]: chunk for chunk in prepared.chunks}
        if len(current_chunks) != len(prepared.chunks):
            raise ValueError("当前 chunk ID 重复")
        for identity in identities:
            chunk = current_chunks[identity["chunk_id"]]
            if _sample_identity(chunk) != identity:
                raise ValueError("人工确认样本与当前 chunk 不一致")
            if (not isinstance(chunk["text"], str)
                    or hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest() != identity["text_sha256"]
                    or len(chunk["text"]) != identity["char_end"] - identity["char_start"]):
                raise ValueError("样本原文与文本哈希/字符范围不符")
        if samples is not None:
            if not isinstance(samples, (list, tuple)):
                raise ValueError("实际预览样本必须是列表")
            if [_sample_identity(sample) for sample in samples] != identities:
                raise ValueError("当前预览与已确认样本序列不一致")
            # 允许传入六字段身份记录；若传入包含原文的预览块，原文也必须一致。
            if any("text" in sample and sample["text"] != current_chunks[sample["chunk_id"]]["text"]
                   for sample in samples):
                raise ValueError("预览原文与已确认 chunk 不一致")

        result.update(
            human_review_status="human_verified",
            human_reviewed_by="user",
            human_reviewed_at=reviewed_at,
            human_reviewed_sample_count=10,
            human_review_reason="matching_version_sources_and_samples",
        )
        return result
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        # sidecar 损坏只取消继承，不篡改来源文件，也不阻断已经有效的分块操作。
        result.update(human_review_status="outdated", human_review_reason="confirmation_binding_mismatch")
        return result
