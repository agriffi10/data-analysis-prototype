"""The footer decoder, against files polars actually wrote.

A decoder that returned a constant would satisfy any single-codec assertion, so the control
here is that it tells five codecs apart — and each file is written by the library whose default
the converter's suite goes on to pin.
"""

import builtins
import io
import os
import sys

import polars as pl
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from rccommon import parquet_footer

#: polars' compression name to the codec the FILE ends up carrying. The two differ in one place
#: and it is not a decoder bug: polars' `"lz4"` writes Parquet's LZ4_RAW (enum 7), not the
#: deprecated LZ4 (enum 5). Written as a pair so the mismatch is a recorded fact rather than an
#: expectation someone later "fixes" into agreement.
CODEC_CASES = (
    ("uncompressed", "uncompressed"),
    ("snappy", "snappy"),
    ("gzip", "gzip"),
    ("lz4", "lz4_raw"),
    ("zstd", "zstd"),
)


def _written(tmp_path, rows, name="out", columns=2, streamed=False, **kwargs):
    """Writes one Parquet file through polars and returns its path.

    `columns` is not decoration. A file of fewer than fifteen columns has one column chunk per
    row group and its Thrift list header fits in a nibble; at fifteen or more the header takes
    compact protocol's long-form escape, which is a different code path in the decoder. Two
    columns is the shape the small fixtures use and the shape that would leave that path
    unexercised, so one fixture below is deliberately wide.
    """
    path = tmp_path / f"{name}.parquet"
    frame = pl.DataFrame({f"c{i}": list(range(rows)) for i in range(columns)})
    if streamed:
        frame.lazy().sink_parquet(path, **kwargs)
    else:
        frame.write_parquet(path, **kwargs)
    return path


def test_the_row_count_is_the_files_own_and_an_empty_file_reads_as_zero(tmp_path):
    assert parquet_footer.row_count(_written(tmp_path, 0, name="none")) == 0
    assert parquet_footer.row_count(_written(tmp_path, 1, name="one")) == 1
    assert parquet_footer.row_count(_written(tmp_path, 2_500, name="many")) == 2_500


@pytest.mark.parametrize(("asked", "written"), CODEC_CASES)
def test_the_decoder_tells_the_codecs_apart(asked, written, tmp_path):
    """The positive control. Without it, a decoder hard-wired to answer "zstd" would satisfy
    every assertion the converter's suite makes about polars' default."""
    assert parquet_footer.codecs_of(_written(tmp_path, 8, compression=asked)) == {written}


def test_a_wide_file_takes_the_long_list_header_and_still_decodes(tmp_path):
    """Compact protocol writes a list of fifteen or more elements with an escape nibble and a
    separate varint count. Every other fixture here is two columns, so without this the escape
    is dead code — and a result set of fifteen columns is entirely ordinary."""
    wide = _written(tmp_path, 20, name="wide", columns=40)
    assert parquet_footer.row_count(wide) == 20
    assert parquet_footer.codecs_of(wide) == {"zstd"}


def test_the_streaming_writer_the_converter_uses_decodes_the_same_way(tmp_path):
    """The converter writes with `sink_parquet`, not `write_parquet`. They are different
    writers, and a footer assertion that only ever saw the eager one would be asserting about
    a file the plane never produces."""
    for rows in (0, 1, 5_000):
        streamed = _written(tmp_path, rows, name=f"s{rows}", streamed=True)
        assert parquet_footer.row_count(streamed) == rows


def test_the_decoder_reads_the_trailer_rather_than_the_file(tmp_path):
    """The module exists so the converter never materialises what it wrote; a decoder that
    read the whole file to find a four-kilobyte struct would put the output back in memory and
    size the function against it. Asserted on BYTES READ, because "it seeks" is a claim about
    an implementation and this is a claim about the cost."""
    big = _written(tmp_path, 200_000, name="big", columns=8)
    assert big.stat().st_size > 1_000_000

    read_bytes = 0
    total = big.stat().st_size

    class _Counting(io.BufferedReader):
        def read(self, size=-1):
            nonlocal read_bytes
            chunk = super().read(size)
            read_bytes += len(chunk)
            return chunk

    original = builtins.open

    def patched(file, mode="r", *args, **kwargs):
        if str(file) == str(big) and "b" in mode:
            return _Counting(io.FileIO(str(file), "rb"))
        return original(file, mode, *args, **kwargs)

    builtins.open = patched
    try:
        assert parquet_footer.row_count(big) == 200_000
    finally:
        builtins.open = original
    assert read_bytes < total // 10, (
        f"read {read_bytes} of {total} bytes to find the footer; it is not seeking to the trailer"
    )


def test_a_file_with_no_rows_has_no_codec_at_all(tmp_path):
    """Which is why the assertion over polars' default belongs on a fixture that holds data:
    an empty file carries no column chunk to read a codec from, and an empty set would pass
    any `not in` check written against it."""
    assert parquet_footer.codecs_of(_written(tmp_path, 0)) == set()


def test_a_file_that_is_not_parquet_refuses_rather_than_returning_a_number(tmp_path):
    plain = tmp_path / "not.parquet"
    plain.write_bytes(b"PAR1" + b"\x00" * 32)
    with pytest.raises(parquet_footer.ParquetFooterError):
        parquet_footer.row_count(plain)
    truncated = tmp_path / "short.parquet"
    truncated.write_bytes(b"PAR1")
    with pytest.raises(parquet_footer.ParquetFooterError):
        parquet_footer.row_count(truncated)


def test_an_unrecognised_codec_reads_as_a_change_rather_than_an_empty_set(tmp_path, monkeypatch):
    """A codec Parquet adds later must not vanish from the set — an empty answer would read as
    "no compression assertion to make" on exactly the upgrade the assertion exists to catch.

    Driven through `codecs_of` against a real file with the lookup table emptied, rather than
    asserted about the table's contents: a test that only read the dict would pass with the
    fallback branch deleted, which is the branch it is named for.
    """
    assert parquet_footer.CODECS[6] == "zstd"
    monkeypatch.setattr(parquet_footer, "CODECS", {})
    assert parquet_footer.codecs_of(_written(tmp_path, 4)) == {"codec-6"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
