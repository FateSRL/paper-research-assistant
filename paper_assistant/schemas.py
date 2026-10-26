"""任务 I：定义外部数据进入程序时需要满足的最小结构契约。

Python 的类型注解本身不会自动检查外部 JSON。这里使用 Pydantic：
只有输入满足字段类型、字段约束和跨字段规则，才能构造模型对象。

本模块检查的是结构。例如，引用 ID 非空并不代表该 ID 真实存在；
引用是否属于选定论文、解析版本和本轮证据集合，留给 D5 的业务校验。
导入本模块只会定义模型，不会调用 API、读取 PDF 或查询数据库。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Annotated 把额外的校验规则附加到一个类型上。
# NonEmptyStr 相当于“带最小长度约束的字符串”，避免每个字段重复写规则。
# Field(min_length=1) 要求至少有一个字符；首尾空白的清理由下方配置负责。
# 因此 "  r1  " 会变成 "r1"，而 "   " 会变成空字符串并被拒绝。
NonEmptyStr = Annotated[str, Field(min_length=1)]


class StrictSchema(BaseModel):
    """所有模型共用的严格校验配置，子类会继承这些设置。"""

    model_config = ConfigDict(
        # 只接受模型声明过的字段，防止拼错字段名却被静默忽略。
        # 例如 EvidenceRef 中额外出现 pdf_pages，会触发 ValidationError。
        extra="forbid",
        # 拒绝隐式类型转换。例如 pdf_page="1" 不会自动变成整数 1。
        # pdf_page=True 也不能因为 bool 是 int 的子类就被当作页码。
        strict=True,
        # 清理字符串两端的空白，再配合 NonEmptyStr 拒绝纯空白内容。
        str_strip_whitespace=True,
    )


class EvidenceRef(StrictSchema):
    """一条证据的位置标识；这里暂不检查它是否对应真实存储记录。"""

    # 片段 ID。D4 建立分块后才会有真实 chunk；检查脚本使用演示 ID。
    chunk_id: NonEmptyStr
    # 论文及固定版本的 ID，后续应与 corpus.json 中的约定一致。
    paper_id: NonEmptyStr
    # 解析版本，例如 r1；重新解析产生新版本的逻辑不由这个模型实现。
    parse_revision: NonEmptyStr
    # PDF 文件页序，从 1 开始。ge 表示 greater than or equal，即 >= 1。
    # 是否超过某份 PDF 的总页数，还需要业务层结合文件信息检查。
    pdf_page: int = Field(ge=1)


class EvidenceQuote(StrictSchema):
    """A model-selected original excerpt, without a separate source lookup."""

    chunk_id: NonEmptyStr
    quote: NonEmptyStr


class Claim(StrictSchema):
    """一条回答及其依据；旧记录未写 basis 时沿用论文证据。"""

    evidence_quotes: list[EvidenceQuote] = Field(default_factory=list)
    claim: NonEmptyStr
    basis: Literal["paper_evidence", "model_knowledge", "analysis"] = "paper_evidence"
    citation_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_basis(self) -> "Claim":
        if self.basis == "paper_evidence" and not self.citation_ids:
            raise ValueError("paper_evidence 必须提供 citation_ids")
        if self.basis == "model_knowledge" and self.citation_ids:
            raise ValueError("model_knowledge 不得附带论文引用")
        # analysis 可以引用推论的原文前提，引用不代表推论已由论文证实。
        return self


class AnswerDraft(StrictSchema):
    """模型生成的回答草稿；保留资料不足结构以读取历史记录。

    Literal 限定字段只能取列出的值，未知的 "done" 等状态会被拒绝。
    tool_error、invalid_output、budget_exceeded 是后续由程序产生的终态，
    不要求模型通过本草稿结构自行宣告这些程序错误。
    """

    status: Literal["answered", "insufficient_evidence"]
    # default_factory 每次构造对象时都创建一个新的空列表。
    # 输入省略 claims 时采用 []；answered 状态仍会在下方被拒绝。
    claims: list[Claim] = Field(default_factory=list)
    direct_answer: NonEmptyStr | None = None
    # None 表示没有提供原因；提供字符串时仍须满足 NonEmptyStr。
    # answered 可用 reason 简要说明范围或局限；历史资料不足记录必须提供。
    reason: NonEmptyStr | None = None

    # after 表示先完成字段检查，再检查多个字段之间的关系。
    # Pydantic 在构造模型时自动调用此方法，不需要 main 手动调用。
    @model_validator(mode="after")
    def check_consistency(self) -> "AnswerDraft":
        """检查状态与内容是否一致，成功返回当前对象，失败抛出异常。

        self 是已经通过字段检查的 AnswerDraft 对象，可以读取其属性。
        单个字段合法并不代表它们组合起来合理，例如“资料不足”却给出
        事实性结论，因此还需要这里的跨字段检查。
        """

        if self.status == "answered":
            # 声称已经回答，就必须至少有一个结论。
            # 结论文本和不同依据的引用规则已经由 Claim 模型检查。
            if not self.claims:
                raise ValueError("answered 至少需要一条 claim")

        if self.status == "insufficient_evidence":
            # 资料不足时不携带事实性结论，避免拒答状态和实际内容矛盾。
            if self.claims:
                raise ValueError("insufficient_evidence 的 claims 必须为空")
            # 空串、纯空白字符串已在字段检查时被拒绝，这里检查缺失情况。
            if self.reason is None:
                raise ValueError("insufficient_evidence 必须说明 reason")

        # after 验证器必须返回模型对象。只做检查却忘记 return self，
        # 就不能正确把通过校验的对象交回给调用方。
        # 上面的 ValueError 会被 Pydantic 包装成统一的 ValidationError。
        return self


def answer_evidence_status(draft: dict) -> str:
    """只描述回答的依据组成；不判断检索充分性或事实准确率。"""
    claims = draft.get("claims", [])
    if not any(claim.get("citation_ids") for claim in claims):
        return "none"
    if all(claim.get("basis", "paper_evidence") == "paper_evidence" for claim in claims):
        return "paper_only"
    return "mixed"
