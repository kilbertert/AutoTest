"""Tool definitions — FunctionTool + define_tool helper, StructuredToolResult."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Optional,
    Type,
    TypeVar,
    TypedDict,
    Union,
)

from pydantic import BaseModel

from .abort_signal import AbortSignal


# --- structured tool result -------------------------------------------------


class StructuredToolSuccess(TypedDict, total=False):
    ok: bool  # always True
    summary: str
    data: Any


class StructuredToolError(TypedDict, total=False):
    ok: bool  # always False
    summary: str
    error: str
    code: str
    details: Dict[str, Any]


StructuredToolResult = Union[StructuredToolSuccess, StructuredToolError]


# --- function tool ----------------------------------------------------------


P = TypeVar("P", bound=BaseModel)
R = TypeVar("R")


@dataclass
class FunctionTool(Generic[P, R]):
    """A function tool the agent can call.

    `parameters` is a pydantic BaseModel **class** describing the input shape
    (replacing zod schema in the TS source). `invoke` receives a validated
    instance of that model plus an optional AbortSignal.

    `raw_input_schema` is an optional escape hatch: when set, provider adapters
    use it verbatim instead of `parameters.model_json_schema()`. MCP tools use
    this to pass the server's exact JSON Schema through without round-tripping
    it through pydantic.
    """

    name: str
    description: str
    parameters: Type[P]
    # invoke is wrapped by define_tool() so callers can pass either a pydantic
    # model or a raw dict — the wrapper handles validation.
    invoke: Callable[[Dict[str, Any], Optional[AbortSignal]], Awaitable[Any]]
    raw_input_schema: Optional[Dict[str, Any]] = None


Tool = FunctionTool[BaseModel, Any]


def define_tool(
    *,
    name: str,
    description: str,
    parameters: Type[P],
    invoke: Callable[..., Awaitable[R]],
) -> FunctionTool[P, R]:
    """Defines a function tool.

    The user-supplied `invoke` is called with a **validated pydantic instance**
    of `parameters` (and an optional `signal`). The returned tool's `.invoke`
    accepts a raw dict (as produced by the model) and validates internally.
    """

    async def wrapped(raw_input: Dict[str, Any], signal: Optional[AbortSignal] = None) -> R:
        # Validate raw dict against the pydantic schema, matching the TS
        # `z.infer<P>` contract where the user receives a typed object.
        validated = parameters.model_validate(raw_input)
        # Accept either an `(input)` or `(input, signal)` invoke signature.
        try:
            return await invoke(validated, signal)
        except TypeError:
            return await invoke(validated)

    return FunctionTool(name=name, description=description, parameters=parameters, invoke=wrapped)
