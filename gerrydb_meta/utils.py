from sqlalchemy import text

from gerrydb_meta import models


def create_column_value_partition_text(column_id: int):
    table_name = models.ColumnValue.__table__.name
    sql = f"CREATE TABLE IF NOT EXISTS {models.SCHEMA}.{table_name}_{column_id} PARTITION OF {models.SCHEMA}.{table_name} FOR VALUES IN ({column_id})"
    return text(sql)
