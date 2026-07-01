"""A queue + subscription manager for routing tool-approval requests to a UI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from ...foundation import ToolUseContent
from .approval_types import ApprovalDecision

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 20


@dataclass
class ApprovalRequest:
    tool_use: ToolUseContent
    future: "asyncio.Future[ApprovalDecision]"


class ApprovalManager:
    def __init__(self) -> None:
        self._queue: List[ApprovalRequest] = []
        self._current_request: Optional[ApprovalRequest] = None
        self._subscriber: Optional[Callable[[Optional[ApprovalRequest]], None]] = None

    async def ask_user(self, tool_use: ToolUseContent) -> ApprovalDecision:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        if len(self._queue) >= _MAX_QUEUE_SIZE:
            logger.warning("[ApprovalManager] Queue overflow. Denying tool %s.", tool_use["name"])
            future.set_result("deny")
            return await future
        self._queue.append(ApprovalRequest(tool_use=tool_use, future=future))
        self._process_queue()
        return await future

    def _process_queue(self) -> None:
        if self._current_request is not None or not self._queue:
            if not self._queue and self._current_request is None and self._subscriber:
                self._subscriber(None)
            return
        self._current_request = self._queue.pop(0)
        if self._subscriber:
            self._subscriber(self._current_request)

    def respond(self, decision: ApprovalDecision) -> None:
        if self._current_request is None:
            return
        if not self._current_request.future.done():
            self._current_request.future.set_result(decision)
        self._current_request = None
        self._process_queue()

    def subscribe(
        self, callback: Callable[[Optional[ApprovalRequest]], None]
    ) -> Callable[[], None]:
        self._subscriber = callback
        self._process_queue()

        def unsubscribe() -> None:
            self._subscriber = None

        return unsubscribe


global_approval_manager = ApprovalManager()
