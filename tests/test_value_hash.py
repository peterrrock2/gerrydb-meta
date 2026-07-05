"""Tests for order-independent column value fingerprints."""

from gerrydb_meta.enums import ColumnType
from gerrydb_meta.value_hash import encode_value, pair_digest, xor_fold


def test_encoding_golden_vectors():
    # Pinned: changing any byte of the encoding invalidates stored hashes.
    assert encode_value(ColumnType.INT, 5) == b"i:5"
    assert encode_value(ColumnType.INT, -12) == b"i:-12"
    assert encode_value(ColumnType.FLOAT, 1.0) == b"f:" + bytes.fromhex("3ff0000000000000")
    assert encode_value(ColumnType.BOOL, True) == b"b:1"
    assert encode_value(ColumnType.STR, "x") == b"s:x"
    # Declared type governs: an int arriving for a FLOAT column encodes as float.
    assert encode_value(ColumnType.FLOAT, 1) == encode_value(ColumnType.FLOAT, 1.0)


def test_pair_digest_golden_vector():
    # md5(b"geo:1\x00i:5") pinned as signed 64-bit halves.
    import hashlib

    d = hashlib.md5(b"geo:1\x00i:5").digest()
    expect = (
        int.from_bytes(d[:8], "big", signed=True),
        int.from_bytes(d[8:], "big", signed=True),
    )
    assert pair_digest("geo:1", ColumnType.INT, 5) == expect


def test_xor_fold_order_independent_and_self_inverse():
    a = pair_digest("a", ColumnType.INT, 1)
    b = pair_digest("b", ColumnType.INT, 2)
    c = pair_digest("c", ColumnType.INT, 3)
    assert xor_fold([a, b, c]) == xor_fold([c, a, b])
    # Removing a pair == XORing its digest back in.
    abc = xor_fold([a, b, c])
    assert xor_fold([abc, b]) == xor_fold([a, c])
    assert xor_fold([]) == (0, 0)
