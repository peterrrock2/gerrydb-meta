"""Database connections."""

import os
import urllib.parse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uvicorn.config import logger as log

if os.getenv("INSTANCE_CONNECTION_NAME"):  # pragma: no cover
    username = os.environ["DB_USER"]
    password = urllib.parse.quote(os.environ["DB_PASS"])
    db_name = os.environ["DB_NAME"]
    socket = f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}"
    db_url = f"postgresql://{username}:{password}@/{db_name}?host={socket}"
    # For Cloud Run deployments, credentials are written to a connection service file
    # on app initialization.
    # see https://www.postgresql.org/docs/current/libpq-pgservice.html
    ogr2ogr_db_config = "PG:service=gerrydb"

else:
    # Local development: use Postgres URL direcrly.
    db_url = os.getenv("GERRYDB_DATABASE_URI")
    if os.getenv("GERRYDB_RUN_TESTS"):  # pragma: no cover
        db_url = os.getenv("GERRYDB_TEST_DATABASE_URI")

    ogr2ogr_db_config = f"PG:{db_url}"

log.debug("Using database URL: %s", db_url)

_session_factory = None


def __getattr__(name):
    # Lazy Session: the API workers import this module for db_url but use
    # their own pooled engine; building another engine at import time was
    # pure waste. Admin/CLI consumers keep `from gerrydb_meta.db import
    # Session` working, paying for the engine only when they use it.
    if name == "Session":
        global _session_factory
        if _session_factory is None:
            _session_factory = sessionmaker(create_engine(db_url))
        return _session_factory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
