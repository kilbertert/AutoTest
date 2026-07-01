"""A queue + subscription manager for routing ask_user_question requests to a UI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from .ask_user_question import AskUserQuestionParameters, AskUserQuestionResult

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 20


@dataclass
class AskUserQuestionRequest:
    params: AskUserQuestionParameters
    future: "asyncio.Future[AskUserQuestionResult]"


class AskUserQuestionManager:
    def __init__(self) -> None:
        self._queue: List[AskUserQuestionRequest] = []
        self._current_request: Optional[AskUserQuestionRequest] = None
        self._subscriber: Optional[Callable[[Optional[AskUserQuestionRequest]], None]] = None

    async def ask_user_question(self, params: AskUserQuestionParameters) -> AskUserQuestionResult:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AskUserQuestionResult] = loop.create_future()
        if len(self._queue) >= _MAX_QUEUE_SIZE:
            logger.warning("[AskUserQuestionManager] Queue overflow; rejecting request.")
            future.set_exception(RuntimeError("Ask user question queue overflow"))
            return await future
        self._queue.append(AskUserQuestionRequest(params=params, future=future))
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

    def respond_with_answers(self, result: AskUserQuestionResult) -> None:
        if self._current_request is None:
            return
        if not self._current_request.future.done():
            self._current_request.future.set_result(result)
        self._current_request = None
        self._process_queue()

    def subscribe(
        self, callback: Callable[[Optional[AskUserQuestionRequest]], None]
    ) -> Callable[[], None]:
        self._subscriber = callback
        self._process_queue()

        def unsubscribe() -> None:
            self._subscriber = None

        return unsubscribe


global_ask_user_question_manager = AskUserQuestionManager()
