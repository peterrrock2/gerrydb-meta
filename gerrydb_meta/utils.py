import csv
import io
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from gerrydb_meta import models


def copy_rows(
    db: Session,
    *,
    table: str,
    columns: tuple[str, ...],
    rows: Iterable[tuple],
    quote_all: bool = False,
) -> None:
    """Bulk-inserts rows with COPY on the session's own connection.

    Several times faster than executemany at millions of rows, and the COPY
    stays inside the session's transaction. None becomes NULL under default
    quoting; pass quote_all=True for tables whose text values may be empty
    strings (COPY reads an unquoted empty field as NULL).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL)
    writer.writerows(rows)
    buf.seek(0)
    raw = db.connection().connection
    with raw.cursor() as cursor:
        cursor.copy_expert(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN (FORMAT csv)", buf
        )


def create_column_value_partition_text(column_id: int):
    table_name = models.ColumnValue.__table__.name
    sql = f"CREATE TABLE IF NOT EXISTS {models.SCHEMA}.{table_name}_{column_id} PARTITION OF {models.SCHEMA}.{table_name} FOR VALUES IN ({column_id})"
    return text(sql)
