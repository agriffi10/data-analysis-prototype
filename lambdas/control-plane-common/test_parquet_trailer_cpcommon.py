"""Tests for cpcommon.parquet_trailer.

Every refusal is asserted by the words that say which failure it was, because the three
readers that call this turn any ``ParquetTrailerError`` into the same refusal code, and the
message is all an operator has to tell a short object from a lying trailer.
"""

import struct

import pytest
from cpcommon.parquet_trailer import ParquetTrailerError, footer_span


def _trailer(declared):
    return struct.pack("<I", declared) + b"PAR1"


def test_a_trailer_locates_the_footer_that_ends_before_it():
    assert footer_span(1_000, _trailer(100)) == (892, 100)


@pytest.mark.parametrize(
    ("size", "trailer", "reason"),
    [
        (11, b"AR1" + _trailer(1), "11 bytes is too short"),
        (1_000, struct.pack("<I", 100) + b"PAR2", "does not end in PAR1"),
        (1_000, _trailer(0), "footer of zero bytes"),
        (1_000, _trailer(1_000 - 12 + 1), "989-byte footer it does not hold"),
    ],
    ids=["eleven-bytes", "not-par1", "zero-length", "one-past-the-object"],
)
def test_each_trailer_that_locates_no_footer_is_refused_for_its_own_reason(size, trailer, reason):
    with pytest.raises(ParquetTrailerError, match=reason):
        footer_span(size, trailer)


def test_the_largest_footer_the_object_can_hold_is_accepted():
    """The boundary the one-past case stands beside: a footer filling everything between the
    opening PAR1 and the trailer is a real file's shape, not a refusal."""
    assert footer_span(1_000, _trailer(1_000 - 12)) == (4, 988)
