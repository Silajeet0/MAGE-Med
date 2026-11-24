"""Structured API error handlers."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mage_med_contracts import ErrorBody, ErrorResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))


def _response(*, request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=_request_id(request))
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Register stable, non-sensitive error envelopes."""

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _response(
            request=request,
            code="http_error",
            message=message,
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return _response(
            request=request,
            code="validation_error",
            message="Request validation failed",
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled request error",
            extra={"request_id": _request_id(request), "exception_type": type(exc).__name__},
        )
        return _response(
            request=request,
            code="internal_error",
            message="The service could not complete the request",
            status_code=500,
        )
