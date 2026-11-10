"""API error shape from the contract: {error:{code,message,retryable}}."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)

    def as_body(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


def http_error(status_code: int, code: str, message: str, retryable: bool = False) -> AppError:
    return AppError(status_code, code, message, retryable)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.as_body())


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = "http_error"
    if exc.status_code == 401:
        code = "unauthorized"
    elif exc.status_code == 404:
        code = "not_found"
    elif exc.status_code == 409:
        code = "conflict"
    elif exc.status_code == 400:
        code = "bad_request"
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message, "retryable": False}},
    )


async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Unexpected server error.",
                "retryable": True,
            }
        },
    )
