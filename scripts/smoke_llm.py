"""D2 第 7 节：真实调用一次聊天模型并保存脱敏结果。"""

import json
import sys
from datetime import datetime, timezone
from time import perf_counter

from paper_assistant.config import PROJECT_ROOT, LLMSettings, load_llm_settings
from paper_assistant.llm_client import invoke_llm


PROMPT = "请用一句话解释检索增强生成。"
RESULT_FILE = PROJECT_ROOT / "archive" / "run_logs" / "d2" / "llm_smoke.json"


def _safe_error(exc: Exception, settings: LLMSettings | None) -> dict[str, str]:
    message = str(exc)
    if settings is not None:
        message = message.replace(settings.api_key, "[REDACTED]")
    error = {"type": type(exc).__name__, "message": message}
    if exc.__context__ is not None:
        error["cause_type"] = type(exc.__context__).__name__
    return error


def main() -> int:
    settings: LLMSettings | None = None
    record: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": None,
        "model_id": None,
        "timeout_seconds": None,
        "wrapper_invocations": 0,
        "http_requests": "unknown",
        "input": PROMPT,
        "elapsed_seconds": None,
        "output": None,
        "usage": None,
        "error": None,
    }
    started = perf_counter()
    try:
        settings = load_llm_settings()
        record["provider"] = settings.provider
        record["model_id"] = settings.model_id
        record["timeout_seconds"] = settings.timeout
        record["wrapper_invocations"] = 1
        output = invoke_llm([{"role": "user", "content": PROMPT}], settings)
        if not isinstance(output, str) or not output.strip():
            raise ValueError("模型返回空文本")
        record["output"] = output.strip()
        return_code = 0
    except Exception as exc:
        record["error"] = _safe_error(exc, settings)
        return_code = 1
    finally:
        record["elapsed_seconds"] = round(perf_counter() - started, 3)
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if return_code == 0:
        print(f"LLM 连通成功：{record['model_id']}，耗时 {record['elapsed_seconds']} 秒")
        print(f"模型输出：{record['output']}")
    else:
        print(f"LLM 连通失败：{record['error']}", file=sys.stderr)
    print(f"结果文件：{RESULT_FILE}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
