"""Order-independent content fingerprints for column values.

A pair digest is md5(geo_path || 0x00 || typed-encoding(value)); a column's
fingerprint over a geo set is the XOR of its member pairs' digests, stored
as two signed 64-bit halves. XOR gives order independence and O(1)
incremental updates (XOR-ing a digest twice removes it). Geo paths are
unique within a set, so pairs cannot repeat and even-multiplicity
cancellation cannot occur.

The client mirrors this encoding exactly (gerrydb/value_hash.py in
gerrydb-client-py); the SQL backfill mirrors it via convert_to/float8send.
Changing any byte of the encoding invalidates every stored hash.
"""

import hashlib
import json
import struct

from gerrydb_meta.enums import ColumnType

_TYPE_TAGS = {
    ColumnType.INT: b"i:",
    ColumnType.FLOAT: b"f:",
    ColumnType.BOOL: b"b:",
    ColumnType.STR: b"s:",
    ColumnType.JSON: b"j:",
}


def encode_value(col_type: ColumnType, value) -> bytes:
    """Canonical byte encoding of a value, keyed by the column's declared type.

    Typed encoding (not repr of whatever arrived) makes client-side dtype
    drift (e.g. pandas promoting int64 to float64) harmless.
    """
    tag = _TYPE_TAGS[col_type]
    if col_type == ColumnType.INT:
        return tag + str(int(value)).encode()
    if col_type == ColumnType.FLOAT:
        return tag + struct.pack(">d", float(value))
    if col_type == ColumnType.BOOL:
        return tag + (b"1" if value else b"0")
    if col_type == ColumnType.STR:
        return tag + str(value).encode()
    return tag + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def pair_digest(path: str, col_type: ColumnType, value) -> tuple[int, int]:
    """Digest of one (geo path, value) pair as signed (hi, lo) 64-bit halves."""
    d = hashlib.md5(path.encode() + b"\x00" + encode_value(col_type, value)).digest()
    return (
        int.from_bytes(d[:8], "big", signed=True),
        int.from_bytes(d[8:], "big", signed=True),
    )


def xor_fold(digests) -> tuple[int, int]:
    """Folds (hi, lo) digest pairs into one fingerprint; empty folds to (0, 0)."""
    hi = lo = 0
    for h, l in digests:
        hi ^= h
        lo ^= l
    return hi, lo
