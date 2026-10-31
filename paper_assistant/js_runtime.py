"""Small, isolated JavaScript execution for model-initiated numeric work.

The model supplies only data it has already received.  This module exposes no
files, network, database, environment, Python object or Node.js bridge; each
call owns and closes one MiniRacer context.  The limits are deliberately local
to one execution and are not another retrieval or model budget.
"""

from time import perf_counter
import json

import py_mini_racer


MAX_CODE_BYTES = 64 * 1024
MAX_STDOUT_BYTES = 1024 * 1024
EXECUTION_TIMEOUT_SECONDS = 5
MEMORY_LIMIT_BYTES = 64 * 1024 * 1024
RUNTIME_VERSION = "mini-racer-0.12.4"
_OUTPUT_LIMIT_MARKER = "__PRA_STDOUT_LIMIT__"


class JavaScriptError(ValueError):
    """Safe execution failure; the caller records the code, not the source."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _run(code):
    return f"""
(function () {{
  var __logs = [];
  var __size = 0;
  var __limit = {MAX_STDOUT_BYTES};
  function __append(line) {{
    __size += line.length + 1;
    if (__size > __limit) {{ throw new Error("{_OUTPUT_LIMIT_MARKER}"); }}
    __logs.push(line);
  }}
  var console = {{
    log: function () {{
      var parts = [];
      for (var i = 0; i < arguments.length; i++) {{ parts.push(String(arguments[i])); }}
      __append(parts.join(" "));
    }}
  }};
  {code}
  return JSON.stringify(__logs);
}})()
"""


def run_javascript(code):
    """Execute one snippet and return its captured console.log output.

    Raises JavaScriptError with a fixed code for rejections, syntax/runtime
    errors, timeout, memory exhaustion and output overflow.
    """
    if not isinstance(code, str) or not code.strip():
        raise JavaScriptError("javascript_empty_code", "code 必须是非空 JavaScript 字符串")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise JavaScriptError("javascript_code_too_large", "code 超过 64 KiB 输入上限")
    started = perf_counter()
    runtime = py_mini_racer.MiniRacer()
    try:
        runtime.set_hard_memory_limit(MEMORY_LIMIT_BYTES)
        runtime.set_soft_memory_limit(MEMORY_LIMIT_BYTES * 3 // 4)
        try:
            value = runtime.eval(_run(code), timeout_sec=EXECUTION_TIMEOUT_SECONDS)
        except py_mini_racer.JSTimeoutException:
            raise JavaScriptError("javascript_timeout", "JavaScript 执行超过 5 秒上限") from None
        except py_mini_racer.JSOOMException:
            raise JavaScriptError("javascript_memory_limit", "JavaScript 达到运行时内存上限") from None
        except (py_mini_racer.JSParseException, py_mini_racer.JSEvalException) as error:
            message = str(error)
            if _OUTPUT_LIMIT_MARKER in message:
                raise JavaScriptError("javascript_stdout_limit", "console.log 输出超过 1 MiB 上限") from None
            raise JavaScriptError("javascript_error", message[:500]) from None
        output = value if isinstance(value, str) else "[]"
        try:
            lines = json.loads(output)
        except (TypeError, ValueError):
            raise JavaScriptError("javascript_error", "JavaScript 输出无法读取") from None
        if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
            raise JavaScriptError("javascript_error", "JavaScript 输出无法读取")
        stdout = "\n".join(lines)
        if len(stdout.encode("utf-8")) > MAX_STDOUT_BYTES:
            raise JavaScriptError("javascript_stdout_limit", "console.log 输出超过 1 MiB 上限")
        return {"status": "success", "stdout": stdout,
                "stdout_chars": len(stdout), "elapsed_seconds": round(perf_counter() - started, 6),
                "v8_version": runtime.v8_version}
    finally:
        runtime.close()
