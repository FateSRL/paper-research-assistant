r"""任务 I：用 14 组固定数据演示 Pydantic 结构契约的接受与拒绝行为。

在项目根目录运行：
    .\.venv\Scripts\python.exe -X utf8 -m scripts.check_schemas

本脚本不调用模型、读取配置或写结果文件；所有输入都在下面直接定义。
"""

import json

from pydantic import BaseModel, ValidationError

from paper_assistant.schemas import AnswerDraft, EvidenceRef


def check_case(
    name: str,
    model: type[BaseModel],
    payload: dict[str, object],
    expected_valid: bool,
) -> bool:
    """检查一组输入，返回实际行为是否符合这组样例的预期。

    ``model`` 是要检查的 Pydantic 模型类，例如 EvidenceRef。
    ``payload`` 是固定的 Python 字典；先转为 JSON 字符串，再交给模型，
    是为了演示未来接收模型 JSON 输出时所用的验证入口。

    ``expected_valid=True`` 表示这组输入应该通过结构验证；False 表示
    它应该被拒绝。返回值不是“输入是否合法”，而是“检查是否符合预期”：
    非法输入确实被拒绝，也算这组检查通过。
    """
    # json.dumps 把 Python 字典序列化为 JSON 文本。例如 Python 的 None
    # 会变成 JSON 的 null。ensure_ascii=False 使中文保留为可读字符，
    # 它只影响文本表示，不会改变字段类型或替我们验证数据是否合法。
    json_text = json.dumps(payload, ensure_ascii=False)

    try:
        # model_validate_json 完成“解析 JSON + 按模型验证”两步。
        # strict=True 等规则已经在 schemas.py 的模型中定义；这里沿用规则，
        # 所以页码 "1" 不会因为看起来像数字就被当成整数 1 接受。
        validated = model.model_validate_json(json_text)
    except ValidationError as exc:
        actual_valid = False
        print(f"\n{name}：结构被拒绝")

        # ValidationError 是 Pydantic 的验证失败异常；errors() 返回各个
        # 错误的结构化信息。loc 是定位路径，例如
        # ('claims', 0, 'citation_ids', 0) 指向第一个 claim 的第一个引用。
        # 空 loc 通常表示整份对象的跨字段规则失败，例如 answered 没有 claim。
        # 这里只打印定位、错误类型和解释，不把整个异常输入重复打印出来。
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            if not location:
                location = "(根对象 / 跨字段规则)"
            print(f"  {location}: {error['type']} — {error['msg']}")
    else:
        actual_valid = True
        print(f"\n{name}：结构通过")
        # 序列化验证后的对象，让读者看到最终字段和默认值。
        # 这里输出的是脚本写死的演示数据，不是业务回答或真实证据。
        print(f"  {validated.model_dump_json()}")

    # 比较的是“实际接受 / 拒绝”与“预期接受 / 拒绝”是否一致。
    # 例如页码 0 的 expected_valid 是 False，被拒绝后本项仍应打印 PASS。
    passed = actual_valid == expected_valid
    expected_behavior = "结构通过" if expected_valid else "结构被拒绝"
    result = "PASS" if passed else "FAIL"
    print(f"  {result}：预期 {expected_behavior}")
    return passed


def main() -> int:
    """顺序运行 14 个固定样例，并把整体检查结果变成进程退出码。

    这是学习结构契约的固定数据演示，不是问答服务的业务入口。
    demo_paper、demo_chunk、demo_parse_v1 都是虚构标识，不对应真实论文。
    最后一例故意使用 made_up_id：它满足非空字符串的结构要求，因此应该
    通过本阶段验证；通过不代表引用真实存在。D5 还需要检查 ID 是否存在、
    是否属于选定论文与解析版本，以及是否在本轮实际发送的证据集合内。

    返回 0 表示全部样例的接受 / 拒绝行为符合预期；返回 1 表示至少一例
    与预期不同。两者都是整数，交给文件末尾的 SystemExit 使用。
    """
    # 每个 tuple 依次保存：展示名称、模型类、输入字典、预期是否合法。
    # 样例各自使用独立字典，避免修改某一例时影响另一例。
    cases = [
        (
            "01 合法证据",
            EvidenceRef,
            {
                "chunk_id": "demo_chunk",
                "paper_id": "demo_paper",
                "parse_revision": "demo_parse_v1",
                "pdf_page": 1,
            },
            True,
        ),
        (
            "02 证据缺少 paper_id",
            EvidenceRef,
            {
                "chunk_id": "demo_chunk",
                "parse_revision": "demo_parse_v1",
                "pdf_page": 1,
            },
            False,
        ),
        (
            "03 页码为 0",
            EvidenceRef,
            {
                "chunk_id": "demo_chunk",
                "paper_id": "demo_paper",
                "parse_revision": "demo_parse_v1",
                "pdf_page": 0,
            },
            False,
        ),
        (
            "04 页码是字符串",
            EvidenceRef,
            {
                "chunk_id": "demo_chunk",
                "paper_id": "demo_paper",
                "parse_revision": "demo_parse_v1",
                "pdf_page": "1",
            },
            False,
        ),
        (
            "05 证据出现额外字段",
            EvidenceRef,
            {
                "chunk_id": "demo_chunk",
                "paper_id": "demo_paper",
                "parse_revision": "demo_parse_v1",
                "pdf_page": 1,
                "extra_field": "unexpected",
            },
            False,
        ),
        (
            "06 合法回答",
            AnswerDraft,
            {
                "status": "answered",
                "claims": [
                    {
                        "claim": "This is a demo claim.",
                        "citation_ids": ["demo_chunk"],
                    }
                ],
            },
            True,
        ),
        (
            "07 未知状态",
            AnswerDraft,
            {"status": "unknown", "claims": []},
            False,
        ),
        (
            "08 answered 没有 claim",
            AnswerDraft,
            {"status": "answered", "claims": []},
            False,
        ),
        (
            "09 claim 的引用列表为空",
            AnswerDraft,
            {
                "status": "answered",
                "claims": [{"claim": "This is a demo claim.", "citation_ids": []}],
            },
            False,
        ),
        (
            "10 引用 ID 只有空白",
            AnswerDraft,
            {
                "status": "answered",
                "claims": [
                    {"claim": "This is a demo claim.", "citation_ids": ["   "]}
                ],
            },
            False,
        ),
        (
            "11 insufficient_evidence 却带有 claim",
            AnswerDraft,
            {
                "status": "insufficient_evidence",
                "claims": [
                    {
                        "claim": "This is a demo claim.",
                        "citation_ids": ["demo_chunk"],
                    }
                ],
                "reason": "The provided evidence is insufficient.",
            },
            False,
        ),
        (
            "12 insufficient_evidence 的 reason 只有空白",
            AnswerDraft,
            {"status": "insufficient_evidence", "claims": [], "reason": "   "},
            False,
        ),
        (
            "13 合法的 insufficient_evidence",
            AnswerDraft,
            {
                "status": "insufficient_evidence",
                "claims": [],
                "reason": "The provided evidence is insufficient.",
            },
            True,
        ),
        (
            "14 虚构引用 ID 仍能通过结构检查",
            AnswerDraft,
            {
                "status": "answered",
                "claims": [
                    {
                        "claim": "This is a demo claim.",
                        "citation_ids": ["made_up_id"],
                    }
                ],
            },
            True,
        ),
    ]

    passed_count = 0
    for name, model, payload, expected_valid in cases:
        # 每一例都会被执行。即使前一例 FAIL，也继续检查后面的样例，
        # 最后统一给出汇总；这样能一次看到所有不符合预期的行为。
        if check_case(name, model, payload, expected_valid):
            passed_count += 1

    print(f"\n检查汇总：{passed_count}/{len(cases)} 符合预期")
    print("made_up_id 的结构通过仅说明格式合法；真实性与范围留待 D5 检查。")
    # 退出码是脚本与终端之间的约定：0 表示成功，非 0 表示检查失败。
    # 输入被拒绝本身不构成脚本失败；只有拒绝 / 接受不符合预期才构成失败。
    return 0 if passed_count == len(cases) else 1


if __name__ == "__main__":
    # python -m scripts.check_schemas 时，本文件的 __name__ 是 "__main__"，
    # 所以会执行 main()。别的模块 import 本文件时，此处不会自动运行。
    # SystemExit 把 main 返回的 0 或 1 交给操作系统成为进程退出码。
    raise SystemExit(main())
