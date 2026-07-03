"""Entrypoint for Gerry API server."""

import gzip
import json
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from uvicorn.config import logger as log

from gerrydb_meta.api import api_router
from gerrydb_meta.exceptions import (
    BulkCreateError,
    BulkPatchError,
    ColumnValueTypeError,
    CreateValueError,
)

API_PREFIX = "/api/v1"

app = FastAPI(title="gerrydb-meta", openapi_url=f"{API_PREFIX}/openapi.json")


class CommitBeforeSendMiddleware:
    """Commits the request's DB session before the response starts to send.

    Guarantees a client can never observe a success response whose transaction
    has not committed. FastAPI's yield-dependency teardown gives no such
    ordering guarantee in this stack (verified empirically: back-to-back
    bootstrap requests raced the commit once get_obj_meta's sleep was removed),
    so the commit is tied to the ASGI http.response.start message instead.
    Error responses (>= 400) skip the commit; get_db's close rolls them back.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message["status"] < 400:
                db = scope.get("state", {}).get("db")
                if db is not None:
                    await run_in_threadpool(db.commit)
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Innermost middleware (added first): commits fire when the router emits the
# response, before GZip/logging layers or the client can see it.
app.add_middleware(CommitBeforeSendMiddleware)


@app.exception_handler(CreateValueError)
def create_value_error(request: Request, exc: CreateValueError):
    """Handles generic object creation failures."""
    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        content={
            "kind": "Create value error",
            "detail": f"Object creation failed. Reason: {exc}",
        },
    )


@app.exception_handler(ColumnValueTypeError)
def column_value_type_error(request: Request, exc: ColumnValueTypeError):
    """Handles generic object creation failures."""
    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        content={
            "kind": "Column value type error",
            "detail": "Type errors found in column values.",
            "errors": exc.errors,
        },
    )


@app.exception_handler(BulkCreateError)
def bulk_create_error(request: Request, exc: BulkCreateError):
    """Handles (bulk) creation conflicts."""
    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        content={
            "kind": "Bulk create error",
            "detail": f"Object creation failed. Reason: {exc}",
            "paths": exc.paths,
        },
    )


@app.exception_handler(BulkPatchError)
def bulk_create_error(request: Request, exc: BulkCreateError):
    """Handles (bulk) creation conflicts."""
    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        content={
            "kind": "BulkPatchError",
            "detail": f"Object patch failed. Reason: {exc}",
            "paths": exc.paths,
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, exc: RequestValidationError):
    """Rewrites regex-pattern validation failures into a friendlier 400.

    All other validation errors get FastAPI's stock 422 response. Handling this
    here (instead of sniffing 422 bodies in middleware) keeps response bodies
    untouched on the hot path.
    """
    pattern_errors = [
        err for err in exc.errors() if "String should match pattern" in str(err.get("msg", ""))
    ]
    if not pattern_errors:
        return await request_validation_exception_handler(request, exc)

    loc = pattern_errors[0].get("loc", ())
    field = loc[1] if len(loc) > 1 else "unknown"
    position_str = f"at position '{loc[2]}' " if len(loc) > 2 else ""
    return JSONResponse(
        status_code=HTTPStatus.BAD_REQUEST,
        content={
            "detail": (
                f"Found unexpected expression in field '{field}' {position_str}of the request. "
                "Please refer to the documentation for more information on the expected "
                "string formats for each field you are trying to set."
            ),
        },
    )


# It's best to keep the compression level at 1 for GeoPackages. GZIP has trouble getting good
# compression ratios on anything since the WKBs used to represent the geometries in the GeoPackage
# look relatively random. The remaining columns in the SQLite database are not very large, and
# compress pretty well with a small compression level. Setting the compression level above 1
# nets marginal improvements, but massively increases the compute time for the compression.
app.add_middleware(GZipMiddleware, compresslevel=1)
app.include_router(api_router, prefix=API_PREFIX)


_LOGGED_ERROR_STATUSES = frozenset(
    {
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.CONFLICT,
        HTTPStatus.UNPROCESSABLE_ENTITY,
    }
)


@app.middleware("http")
async def log_error_responses(request: Request, call_next):
    """Logs error-response bodies. Success bodies stream through untouched."""
    response = await call_next(request)
    if response.status_code not in _LOGGED_ERROR_STATUSES:
        return response

    # Error bodies are small; buffer for logging, then rebuild the response.
    body = bytearray()
    if hasattr(response, "body_iterator"):
        async for chunk in response.body_iterator:
            body.extend(chunk)
        response = Response(
            content=bytes(body),
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    else:  # pragma: no cover
        body.extend(getattr(response, "body", b""))

    text_bytes = bytes(body)
    if response.headers.get("Content-Encoding") == "gzip":  # pragma: no cover
        try:
            text_bytes = gzip.decompress(text_bytes)
        except Exception:
            pass
    text = text_bytes.decode("utf-8", errors="replace")
    try:
        detail_msg = json.loads(text).get("detail", "No detail available")
    except Exception:
        detail_msg = text

    log.error(
        f"{response.status_code} for Request: {request.method} {request.url}. Detail: {detail_msg}"
    )
    return response


@app.get("/health")
def health_check():  # pragma: no cover
    return {"status": "healthy"}


@app.get("/middlewares")
def list_middlewares():  # pragma: no cover
    middleware_info = [{"class": str(m.cls), "options": m.options} for m in app.user_middleware]
    return {"middlewares": middleware_info}
