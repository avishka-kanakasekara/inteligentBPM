"""Turn unhandled endpoint exceptions into responses before they leave CORS."""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_exception_response


class UnhandledExceptionMiddleware:
    """Catch exceptions inside CORSMiddleware and return the standard 500 envelope.

    ServerErrorMiddleware is outside CORS, so an exception that reaches it is
    written without Access-Control-Allow-Origin. The browser then reports a
    CORS failure instead of the API error.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def sender(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, sender)
        except Exception as exc:
            if response_started:
                raise
            response = await unhandled_exception_response(Request(scope), exc)
            await response(scope, receive, send)
