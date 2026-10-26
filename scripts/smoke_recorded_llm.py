"""D5 B：真实调用一次聊天服务，保存完整响应与实际请求统计。

正常路径一次聊天请求，瞬态网络故障最多重试一次。不检索论文、不请求
embedding；这是适配器连通检查，不是 D5 端到端问答或答案准确率评测。
"""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sys
from time import monotonic

from paper_assistant.config import PROJECT_ROOT, load_llm_settings
from paper_assistant.indexing import atomic_json
from paper_assistant.llm_client import ChatBudget, ChatPolicy, LLMCallError, RecordedLLM


MESSAGES = [
    {"role": "system", "content": "Return only a valid JSON object. This is a chat API connectivity check, not a paper answer."},
    {"role": "user", "content": "Return an object with ok equal to true and message equal to a short connectivity confirmation."},
]


def main() -> int:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    policy = ChatPolicy()
    budget = ChatBudget(policy)
    report = {"task": "D5-B-real-chat-adapter-smoke", "run_id": stamp, "started_at_utc": now.isoformat(),
              "started_at_local": now.astimezone(timezone(timedelta(hours=8))).isoformat(),
              "timezone": "Asia/Shanghai", "status": "failed", "scope": "chat adapter connectivity only",
              "messages": MESSAGES, "policy": asdict(policy), "provider": None, "model_id": None,
              "thinking_mode": None, "sdk_max_retries": 0, "http_follow_redirects": False,
              "result": None, "error": None, "embedding_requests": 0, "is_answer_accuracy": False,
              "secrets_saved": False,
              "history_report": f"archive/run_logs/d5/llm_smoke_{stamp}.json"}
    began = monotonic()
    try:
        settings = load_llm_settings()
        with RecordedLLM(settings, policy=policy, budget=budget) as client:
            report.update(provider=settings.provider, model_id=settings.model_id,
                          thinking_mode="disabled" if settings.provider.lower() == "deepseek" else "provider_default")
            result = client.invoke(MESSAGES, require_json=True)
            report["result"] = result
            if result["status"] != "success":
                report["status"] = "invalid_output"
            else:
                obj = json.loads(result["content"])
                good = (isinstance(obj, dict) and obj.get("ok") is True
                        and isinstance(obj.get("message"), str) and bool(obj["message"].strip()))
                report["smoke_object_check"] = good
                report["status"] = "success" if good else "invalid_output"
    except LLMCallError as error:
        report["status"] = error.status
        report["error"] = {"code": error.code, "message": str(error), "attempts": error.attempts}
    except Exception:
        # 配置/本地保存之外的未知错误不复制异常正文，避免认证信息回显。
        report["status"] = "tool_error"
        report["error"] = {"code": "local_error", "message": "本地配置或烟雾检查未完成"}
    report["statistics"] = budget.statistics()
    report["llm_requests"] = budget.http_requests
    report["network_requests"] = budget.http_requests
    report["elapsed_seconds"] = round(monotonic() - began, 6)
    atomic_json(PROJECT_ROOT / report["history_report"], report)
    atomic_json(PROJECT_ROOT / "artifacts/d5/llm_smoke.json", report)
    content = report["result"]["content"] if report["result"] else None
    lines = ["# D5 B：聊天适配器真实连通检查", "", f"状态：`{report['status']}`。",
             f"模型：`{report['model_id']}`；thinking：`{report['thinking_mode']}`。", "",
             "这不是论文问答。没有执行检索、没有请求文档或问题 embedding。", "",
             f"SDK 尝试：{budget.attempts}；HTTP 发送尝试：{budget.http_requests}；网络重试：{budget.network_retries}。",
             "", "响应文本（JSON 字符串形式）：", "", json.dumps(content, ensure_ascii=False), "",
             "统计：", "", json.dumps(report["statistics"], ensure_ascii=False, indent=2), "",
             f"历史记录：`{report['history_report']}`。", ""]
    (PROJECT_ROOT / "artifacts/d5/llm_smoke.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "model_id": report["model_id"],
                      "statistics": report["statistics"], "report": "artifacts/d5/llm_smoke.json"},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
