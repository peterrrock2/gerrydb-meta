from sqlalchemy import text

from gerrydb_meta.utils import create_column_value_partition_text


def test_create_column_value_partition_text():
    column_id = 42
    got = create_column_value_partition_text(column_id=column_id)
    wanted = text(
        "CREATE TABLE IF NOT EXISTS gerrydb.column_value_42 PARTITION OF gerrydb.column_value FOR VALUES IN (42)"
    )
    # different object instances, so compare string form
    assert str(got) == str(wanted)
