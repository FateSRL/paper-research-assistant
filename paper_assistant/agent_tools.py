"""LangChain tool wrappers bound to one question's AgentEvidenceState."""

from langchain_core.tools import StructuredTool

from paper_assistant.agent_actions import (
    read_context_tool_definition, run_javascript_tool_definition, search_tool_definition,
)


TOOL_PROTOCOL = "langchain-core-1.7.3"


def _definition(name):
    return next(row for row in (
        search_tool_definition(), read_context_tool_definition(), run_javascript_tool_definition())
        if row["function"]["name"] == name)["function"]


def build_agent_tools(state):
    """Create the same three tools for one question, sharing its state."""
    search = _definition("search")
    read = _definition("read_context")
    javascript = _definition("run_javascript")

    def search_call(**arguments):
        return state.invoke_search(arguments)

    def read_call(**arguments):
        return state.invoke_read(arguments)

    def javascript_call(**arguments):
        return state.invoke_javascript(arguments)

    return {
        "search": StructuredTool.from_function(
            func=search_call, name="search", description=search["description"],
            args_schema=search["parameters"]),
        "read_context": StructuredTool.from_function(
            func=read_call, name="read_context", description=read["description"],
            args_schema=read["parameters"]),
        "run_javascript": StructuredTool.from_function(
            func=javascript_call, name="run_javascript", description=javascript["description"],
            args_schema=javascript["parameters"]),
    }
