"""ask_user_question tool — ask the user one or more parallel multiple-choice questions."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, List, Optional, TypedDict

from pydantic import BaseModel, Field

from ...foundation import AbortError, AbortSignal, define_tool


# --- runtime types ----------------------------------------------------------


class AskUserQuestionOption(TypedDict, total=False):
    label: str
    description: str
    preview: Optional[str]


class AskUserQuestionItem(TypedDict):
    question: str
    header: str
    options: List[AskUserQuestionOption]
    multi_select: bool


class AskUserQuestionParameters(TypedDict):
    questions: List[AskUserQuestionItem]


class AskUserQuestionAnswer(TypedDict):
    question_index: int
    selected_labels: List[str]


class AskUserQuestionResult(TypedDict):
    answers: List[AskUserQuestionAnswer]


# --- pydantic schema (model-facing) -----------------------------------------


class _AskUserQuestionOptionSchema(BaseModel):
    label: str = Field(description="Short display label for this choice (1–5 words).")
    description: str = Field(description="What this choice means or implies.")
    preview: Optional[str] = Field(
        default=None,
        description="Optional markdown preview when this option is focused (single-select only).",
    )


class _AskUserQuestionItemSchema(BaseModel):
    question: str = Field(description="Full question text; be specific and end with a question mark where appropriate.")
    header: str = Field(
        max_length=12,
        description="Very short tab/tag label (max 12 characters), e.g. Auth, Library.",
    )
    options: List[_AskUserQuestionOptionSchema] = Field(
        min_length=2,
        max_length=4,
        description="2–4 distinct choices; mutually exclusive unless multi_select is true.",
    )
    multi_select: bool = Field(description="If true, the user may pick multiple options; if false, exactly one.")


class _AskUserQuestionParametersSchema(BaseModel):
    questions: List[_AskUserQuestionItemSchema] = Field(
        min_length=1,
        max_length=4,
        description="1–4 parallel, independent questions (no dependency between them).",
    )


ask_user_question_parameters_schema = _AskUserQuestionParametersSchema


def _validate_result_against_params(
    params: AskUserQuestionParameters, result: AskUserQuestionResult
) -> None:
    if len(result["answers"]) != len(params["questions"]):
        raise ValueError(
            f"ask_user_question: expected {len(params['questions'])} answers, got {len(result['answers'])}"
        )
    by_index = {a["question_index"]: a for a in result["answers"]}
    for i, q in enumerate(params["questions"]):
        a = by_index.get(i)
        if a is None:
            raise ValueError(f"ask_user_question: missing answer for question_index {i}")
        labels = {o["label"] for o in q["options"]}
        for label in a["selected_labels"]:
            if label not in labels:
                raise ValueError(f'ask_user_question: unknown label "{label}" for question {i}')
        if q["multi_select"]:
            if len(a["selected_labels"]) < 1:
                raise ValueError(f"ask_user_question: multi-select question {i} requires at least one selection")
        elif len(a["selected_labels"]) != 1:
            raise ValueError(f"ask_user_question: single-select question {i} requires exactly one selection")


def create_ask_user_question_tool(
    callback: Callable[[AskUserQuestionParameters], Awaitable[AskUserQuestionResult]],
):
    """Tool: ask the user one or more parallel multiple-choice questions.

    The host must supply `callback` to block until the user submits (e.g. TUI/web).
    """

    async def invoke(params: _AskUserQuestionParametersSchema, signal: Optional[AbortSignal] = None) -> str:
        # Re-validate by re-dumping then re-parsing — mirrors the TS `.parse(input)` call.
        params_dict: AskUserQuestionParameters = params.model_dump()  # type: ignore[assignment]
        if signal is not None and signal.aborted:
            raise AbortError("Aborted")
        result = await callback(params_dict)
        if signal is not None and signal.aborted:
            raise AbortError("Aborted")
        _validate_result_against_params(params_dict, result)
        return json.dumps(result)

    return define_tool(
        name="ask_user_question",
        description=(
            "Ask the user one or more independent questions with fixed choices. Prefer this "
            "over free-form questions when options are clear. Questions are parallel (no "
            "dependency between them). You may send 1–4 questions in one call. For each "
            "question set multi_select true only when multiple answers make sense."
        ),
        parameters=_AskUserQuestionParametersSchema,
        invoke=invoke,
    )
