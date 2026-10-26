"""从项目根目录的 .env 读取并检查服务配置。"""

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class ConfigError(ValueError):
    """配置缺失或无效时抛出的错误。"""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model_id: str
    api_key: str = field(repr=False)
    base_url: str
    timeout: float


@dataclass(frozen=True)
class EmbeddingSettings:
    backend: str
    model: str
    api_key: str | None = field(repr=False)
    base_url: str | None
    dimension: int | None


@dataclass(frozen=True)
class RerankSettings:
    model: str
    api_key: str = field(repr=False)
    base_url: str
    timeout: float = 30.0


@dataclass(frozen=True)
class MinerUAPISettings:
    token: str = field(repr=False)


def load_mineru_api_settings() -> MinerUAPISettings:
    """只检查官方 MinerU API Token，不发送请求。"""
    required = _required(_read_env(), "MINERU_API_TOKEN")
    return MinerUAPISettings(token=required["MINERU_API_TOKEN"])


def _read_env() -> Mapping[str, str | None]:
    if not ENV_FILE.is_file():
        raise ConfigError(f"找不到配置文件：{ENV_FILE}；请参照 .env.example 创建 .env")
    return dotenv_values(ENV_FILE)


def _required(values: Mapping[str, str | None], *names: str) -> dict[str, str]:
    missing = [name for name in names if not (values.get(name) or "").strip()]
    if missing:
        raise ConfigError(f".env 缺少配置项：{', '.join(missing)}")
    return {name: (values[name] or "").strip() for name in names}


def _url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} 必须是完整的 http:// 或 https:// 地址")
    return value


def _positive_float(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是大于 0 的数字") from exc
    if not isfinite(number) or number <= 0:
        raise ConfigError(f"{name} 必须是大于 0 的数字")
    return number


def load_llm_settings() -> LLMSettings:
    """检查聊天模型配置；不会创建客户端或发送请求。"""
    values = _read_env()
    required = _required(
        values,
        "LLM_PROVIDER",
        "LLM_MODEL_ID",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_TIMEOUT",
    )
    return LLMSettings(
        provider=required["LLM_PROVIDER"],
        model_id=required["LLM_MODEL_ID"],
        api_key=required["LLM_API_KEY"],
        base_url=_url("LLM_BASE_URL", required["LLM_BASE_URL"]),
        timeout=_positive_float("LLM_TIMEOUT", required["LLM_TIMEOUT"]),
    )


def load_embedding_settings() -> EmbeddingSettings:
    """独立检查 embedding 配置；不会读取 LLM 的密钥或地址。"""
    values = _read_env()
    required = _required(values, "EMBEDDING_BACKEND", "EMBEDDING_MODEL")
    backend = required["EMBEDDING_BACKEND"].lower()

    if backend == "dashscope":
        cloud = _required(values, "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL")
        api_key = cloud["EMBEDDING_API_KEY"]
        base_url = _url("EMBEDDING_BASE_URL", cloud["EMBEDDING_BASE_URL"])
    elif backend in {"local", "sentence-transformers"}:
        api_key = None
        base_url = None
    else:
        raise ConfigError("EMBEDDING_BACKEND 目前只支持 dashscope、local 或 sentence-transformers")

    raw_dimension = (values.get("EMBEDDING_DIMENSION") or "").strip()
    if raw_dimension:
        try:
            dimension = int(raw_dimension)
        except ValueError as exc:
            raise ConfigError("EMBEDDING_DIMENSION 必须是大于 0 的整数") from exc
        if dimension <= 0:
            raise ConfigError("EMBEDDING_DIMENSION 必须是大于 0 的整数")
    else:
        dimension = None

    return EmbeddingSettings(
        backend=backend,
        model=required["EMBEDDING_MODEL"],
        api_key=api_key,
        base_url=base_url,
        dimension=dimension,
    )


def load_rerank_settings() -> RerankSettings | None:
    """未配置重排时保持 RRF；配置后可复用现有百炼 embedding 密钥。"""
    values = _read_env()
    if not any((values.get(name) or "").strip() for name in ("RERANK_MODEL", "RERANK_BASE_URL")):
        return None
    required = _required(values, "RERANK_MODEL", "RERANK_BASE_URL")
    api_key = ((values.get("RERANK_API_KEY") or "").strip()
               or (values.get("EMBEDDING_API_KEY") or "").strip())
    if not api_key:
        raise ConfigError(".env 缺少 RERANK_API_KEY 或可复用的 EMBEDDING_API_KEY")
    return RerankSettings(
        model=required["RERANK_MODEL"],
        api_key=api_key,
        base_url=_url("RERANK_BASE_URL", required["RERANK_BASE_URL"]),
        timeout=_positive_float("RERANK_TIMEOUT", (values.get("RERANK_TIMEOUT") or "30").strip()),
    )
