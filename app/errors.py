from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details


def error_body(error_code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"error_code": error_code, "message": message}
    if details is not None:
        body["details"] = details
    return body


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content=error_body("VALIDATION_ERROR", "Request validation failed", {"fields": fields}),
        )
