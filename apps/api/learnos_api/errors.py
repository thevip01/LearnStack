"""The error envelope, and the only exception hierarchy routes should raise.

The contract fixes one shape for every failure:

    {"error": {"code": ..., "message": ..., "detail": ...}}

Routes raise an ``AppError`` subclass; the handlers installed here turn it into
that envelope. FastAPI's own ``HTTPException`` and ``RequestValidationError`` are
translated too, so a client never has to parse two different error formats.

``message`` is safe to show a learner. ``detail`` carries structured context for
the UI (which fields failed, which package problems were found) and must never
contain a stack trace, a SQL string, or task answer material.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger

log = get_logger(__name__)

# Codes are exactly the set the contract enumerates.
ERROR_CODES = (
    "bad_request",
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "unprocessable",
    "rate_limited",
    "sandbox_unavailable",
    "internal_error",
)

_STATUS_TO_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "bad_request",
    409: "conflict",
    422: "unprocessable",
    429: "rate_limited",
    503: "sandbox_unavailable",
}


class AppError(Exception):
    """Base class. Subclasses only ever change ``code`` and ``status_code``."""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str, detail: Any = None, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.headers = headers or {}

    def envelope(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status_code, content=self.envelope(), headers=self.headers)


class BadRequest(AppError):
    code = "bad_request"
    status_code = 400


class Unauthorized(AppError):
    code = "unauthorized"
    status_code = 401

    def __init__(self, message: str = "authentication required", detail: Any = None) -> None:
        # A 401 without a challenge header is a 401 a browser cannot act on.
        super().__init__(message, detail, headers={"WWW-Authenticate": "Bearer"})


class Forbidden(AppError):
    code = "forbidden"
    status_code = 403


class NotFound(AppError):
    code = "not_found"
    status_code = 404


class Conflict(AppError):
    code = "conflict"
    status_code = 409


class Unprocessable(AppError):
    code = "unprocessable"
    status_code = 422


class RateLimited(AppError):
    code = "rate_limited"
    status_code = 429

    def __init__(self, message: str = "too many requests", retry_after_s: int = 60, detail: Any = None) -> None:
        super().__init__(message, detail, headers={"Retry-After": str(retry_after_s)})


class SandboxUnavailable(AppError):
    """No runner is live, or the runner refused the request.

    Distinct from a learner's code failing: that is a successful execution with a
    non-zero exit code, and it is never an HTTP error.
    """

    code = "sandbox_unavailable"
    status_code = 503


class InternalError(AppError):
    code = "internal_error"
    status_code = 500


def error_body(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("app_error", code=exc.code, message=exc.message, exc_info=exc)
        else:
            log.info("app_error", code=exc.code, message=exc.message)
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = [
            {"loc": [str(part) for part in err.get("loc", [])], "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("unprocessable", "request body failed validation", detail),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, "internal_error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Deliberately opaque to the client. The request id in the response header
        # is how support correlates this with the log line that has the traceback.
        log.error("unhandled_exception", exc_info=exc)
        return JSONResponse(status_code=500, content=error_body("internal_error", "internal server error"))
