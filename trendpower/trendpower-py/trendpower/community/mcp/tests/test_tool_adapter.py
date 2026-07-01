from types import SimpleNamespace

import pytest
from mcp.types import Tool as MCPTool

from trendpower.community.mcp.tool_adapter import (
    PREFIX_SEPARATOR,
    _format_call_result,
    adapt_mcp_tool,
    prefixed_tool_name,
)


class _FakeSession:
    def __init__(self) -> None:
        self.calls = []
        self.next_result = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")], isError=False
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.next_result


def test_prefixed_name() -> None:
    assert prefixed_tool_name("fs", "read") == f"fs{PREFIX_SEPARATOR}read"


def test_prefixed_name_sanitizes_invalid_chars() -> None:
    # Spaces / non-ASCII are coerced to '_' so strict providers accept the name.
    assert prefixed_tool_name("my server", "工具") == "my_server____"


def test_prefixed_name_truncates_long_names() -> None:
    name = prefixed_tool_name("server", "x" * 100)
    assert len(name) <= 64
    # Distinct over-long tools stay distinct via the hash suffix.
    other = prefixed_tool_name("server", "y" * 100)
    assert name != other


def test_adapt_preserves_raw_schema() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}
    mcp_tool = MCPTool(name="read_file", description="reads", inputSchema=schema)
    sess = _FakeSession()
    t = adapt_mcp_tool(server_name="fs", mcp_tool=mcp_tool, session=sess)  # type: ignore[arg-type]
    assert t.name == "fs__read_file"
    assert t.description == "reads"
    assert t.raw_input_schema == schema


async def test_invoke_forwards_to_session() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}
    mcp_tool = MCPTool(name="read_file", description="r", inputSchema=schema)
    sess = _FakeSession()
    t = adapt_mcp_tool(server_name="fs", mcp_tool=mcp_tool, session=sess)  # type: ignore[arg-type]
    result = await t.invoke({"path": "/x"}, None)
    assert sess.calls == [("read_file", {"path": "/x"})]
    assert result == "ok"


def test_format_text_content() -> None:
    r = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hello"),
            SimpleNamespace(type="text", text="world"),
        ],
        isError=False,
    )
    assert _format_call_result(r) == "hello\nworld"


def test_format_error_result() -> None:
    r = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="boom")], isError=True
    )
    formatted = _format_call_result(r)
    assert formatted["ok"] is False
    assert "boom" in formatted["error"]
    assert formatted["code"] == "mcp_tool_error"


def test_format_non_text_content_placeholder() -> None:
    r = SimpleNamespace(
        content=[SimpleNamespace(type="image")], isError=False
    )
    assert "image" in _format_call_result(r)
