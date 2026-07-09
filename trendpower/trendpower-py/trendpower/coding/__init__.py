"""Coding layer: lead agent + tools + approval/permission system."""

from .agents import create_coding_agent
from .permissions import (
    CODING_TOOLS_REQUIRING_APPROVAL,
    ApprovalDecision,
    ApprovalManager,
    ApprovalPersistence,
    ApprovalRequest,
    create_coding_approval_middleware,
    global_approval_manager,
)
from .tools.ask_user_question import (
    AskUserQuestionAnswer,
    AskUserQuestionItem,
    AskUserQuestionOption,
    AskUserQuestionParameters,
    AskUserQuestionResult,
    create_ask_user_question_tool,
)
from .tools.ask_user_question_manager import (
    AskUserQuestionManager,
    AskUserQuestionRequest,
    global_ask_user_question_manager,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalManager",
    "ApprovalPersistence",
    "ApprovalRequest",
    "AskUserQuestionAnswer",
    "AskUserQuestionItem",
    "AskUserQuestionManager",
    "AskUserQuestionOption",
    "AskUserQuestionParameters",
    "AskUserQuestionRequest",
    "AskUserQuestionResult",
    "CODING_TOOLS_REQUIRING_APPROVAL",
    "create_ask_user_question_tool",
    "create_coding_agent",
    "create_coding_approval_middleware",
    "global_approval_manager",
    "global_ask_user_question_manager",
]
