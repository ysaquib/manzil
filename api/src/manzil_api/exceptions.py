"""Error taxonomy + global handlers (Phase 1 plan §1.4).

`ManzilAPIError` is the base every domain exception subclasses with a fixed
`status_code` + machine-readable `code`; the global handler maps them (and
Pydantic `ValidationError`) to the single `ErrorResponse` envelope. Domain
modules define their own subclasses in their `exceptions.py`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from manzil_api.schemas import ErrorResponse

logger = logging.getLogger("manzil_api")


class ManzilAPIError(Exception):
    """Base for every API-raised error. Subclasses set `status_code` + `code`."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.__name__
        super().__init__(self.detail)


class NotImplementedYet(ManzilAPIError):
    """Scaffolding placeholder — the route exists (so OpenAPI/codegen see it) but
    its logic lands in a later Phase 1 task. Remove each raise as its task fills in."""

    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = "not_implemented"


class BackendMisconfigured(ManzilAPIError):
    """Required backend configuration (Supabase keys, etc.) is missing or invalid."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "backend_misconfigured"


def _envelope(status_code: int, detail: str, code: str) -> JSONResponse:
    body = ErrorResponse(detail=detail, code=code)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ManzilAPIError)
    async def _handle_manzil_error(_: Request, exc: ManzilAPIError) -> JSONResponse:
        return _envelope(exc.status_code, exc.detail, exc.code)

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc.errors()), "validation_error"
        )

    @app.exception_handler(ValidationError)
    async def _handle_pydantic_validation(_: Request, exc: ValidationError) -> JSONResponse:
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc.errors()), "validation_error"
        )


class CatchAllMiddleware(BaseHTTPMiddleware):
    """Return enveloped 500s for unhandled exceptions.

    Must be registered *before* CORSMiddleware in code (add_middleware prepends),
    so CORS stays outermost and these responses still carry Access-Control-Allow-Origin.
    A plain @app.exception_handler(Exception) does not — Starlette routes that
    through ServerErrorMiddleware, which sits outside CORSMiddleware.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
            return _envelope(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Internal server error",
                "internal_error",
            )
