"""Entrypoint for Gerry API server."""

import gzip
import json
from http import HTTPStatus
from io import BytesIO

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
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


# It's best to keep the compression level at 1 for GeoPackages. GZIP has trouble getting good
# compression ratios on anything since the WKBs used to represent the geometries in the GeoPackage
# look relatively random. The remaining columns in the SQLite database are not very large, and
# compress pretty well with a small compression level. Setting the compression level above 1
# nets marginal improvements, but massively increases the compute time for the compression.
app.add_middleware(GZipMiddleware, compresslevel=1)
app.include_router(api_router, prefix=API_PREFIX)


@app.middleware("http")
async def log_400_errors(request: Request, call_next):
    response = await call_next(request)

    body_bytes = b""

    # Have to check the attribute because there is also a _StreamingResponse
    # class in starlette.middleware.base that is the thing that we actually see sometimes
    # and it is not the same as the starlette.responses.StreamingResponse class
    if hasattr(response, "body_iterator"):
        # If it’s a StreamingResponse, we need to consume .body_iterator
        # to capture all the bytes, then recreate a new StreamingResponse so downstream still
        # sees the original body.
        async for chunk in response.body_iterator:
            body_bytes += chunk

        # Keep a copy of the original compressed bytes
        original_body = body_bytes

        # If Content-Encoding: gzip, decompress before inspecting
        if response.headers.get("Content-Encoding") == "gzip":  # pragma: no cover
            try:
                body_bytes = gzip.decompress(body_bytes)
            except Exception:
                pass

        # Rebuild the StreamingResponse so the client still gets the same body:
        response = StreamingResponse(
            BytesIO(original_body),
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    else:  # pragma: no cover
        if hasattr(response, "body"):
            body_bytes = response.body
            if response.headers.get("Content-Encoding") == "gzip":
                try:
                    body_bytes = gzip.decompress(body_bytes)
                except Exception:
                    pass
        else:
            body_bytes = b""

    text = body_bytes.decode("utf-8", errors="replace")
    json_body = None
    if response.status_code in (400, 403, 409, 422):
        try:
            json_body = json.loads(text)
            detail_msg = json_body.get("detail", "No detail available")
        except Exception:  # pragma: no cover
            detail_msg = text

        log.error(
            f"{response.status_code} for Request: {request.method} {request.url}. "
            f"Detail: {detail_msg}"
        )

    # If it was a 422 (Unprocessable Entity) and the decoded body contains "regex",
    # print out a more user-friendly error message to tell the user what went wrong.
    if (
        response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and "String should match pattern" in text
    ):
        # This is the detail dictionary format that is normally returned by a regex
        text_dict = {
            "loc": ["unknown", "unknown"],
            "msg": "Unknown error",
            "type": "unknown",
        }
        if json_body is not None:
            text_dict = json_body.get("detail", [text_dict])[0]

        position_str = ""
        if len(text_dict["loc"]) > 2:
            position_str = f"at position '{text_dict['loc'][2]}' "
        location_str = f"Found unexpected expression in field '{text_dict['loc'][1]}' {position_str}of the request. "
        response = JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                "detail": (
                    location_str
                    + "Please refer to the documentation for more information on the expected "
                    "string formats for each field you are trying to set."
                ),
            },
            headers=response.headers,
        )

    return response


@app.get("/health")
def health_check():  # pragma: no cover
    return {"status": "healthy"}


@app.get("/middlewares")
def list_middlewares():  # pragma: no cover
    middleware_info = [{"class": str(m.cls), "options": m.options} for m in app.user_middleware]
    return {"middlewares": middleware_info}
