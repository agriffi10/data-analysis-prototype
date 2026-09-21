"""Reads a written Parquet file's own footer: how many rows it holds, and how it is compressed.

Two callers, one decoder. The converter needs the row count for the notification, and the
suite needs the compression codec so that a polars default changing on an upgrade is a red
test rather than a silent change in what users receive.

**It exists because the row count must not come from polars.** The streamed formats are read
with ``scan_csv`` and written with ``sink_*`` precisely so no frame is ever materialised, and
the guard on that property is behavioural — ``LazyFrame.collect`` is made to raise while both
streamed paths run end to end. A count taken with ``scan_parquet(...).select(pl.len()).collect()``
would be a footer read in truth and a ``collect`` to that guard, and the guard would have to be
narrowed to a name sweep that a helper function walks straight past. Reading the footer here
keeps the guard total.

polars has no reader for either fact — ``read_parquet_schema`` returns types, and 1.44's
``read_parquet_metadata`` returns only the file's custom key-value pairs — so the format's own
trailer is parsed. The layout is fixed and tiny: the file ends with the
Thrift-compact ``FileMetaData`` struct, a four-byte little-endian length, and ``PAR1``. Where that
struct sits is ``cpcommon.parquet_trailer``'s to say, because the schema probe reads the same
trailer from S3 and one set of checks cannot drift from another.

**The struct reader is generic and field-numbered rather than named**, so it carries no schema
of its own to drift from the format. The two walks below are the whole of what this module
knows about Parquet: ``FileMetaData`` field 3 is ``num_rows`` and field 4 is the row groups;
a ``RowGroup``'s field 1 is its column chunks; a ``ColumnChunk``'s field 3 is its metadata and
that struct's field 4 is the codec enum.

Attributes:
  CODECS: The Parquet ``CompressionCodec`` enum, by its wire value.
  _NUM_ROWS: ``FileMetaData``'s row-count field number.
  _ROW_GROUPS: ``FileMetaData``'s row-group list field number.
  _COLUMNS: ``RowGroup``'s column-chunk list field number.
  _META_DATA: ``ColumnChunk``'s metadata field number.
  _CODEC: ``ColumnMetaData``'s codec field number.
  _TRUE, _FALSE, _BYTE, _I16, _I32, _I64, _DOUBLE, _BINARY, _LIST, _SET, _MAP, _STRUCT: The
    Thrift compact-protocol type nibbles, numbered as that specification numbers them. A
    boolean STRUCT FIELD carries its value in this nibble and consumes no byte, which is why
    ``value`` returns for both without reading one; a boolean inside a LIST is a byte each, a
    shape ``collection`` refuses rather than decode into a silent desynchronisation.
"""

import struct

from cpcommon import parquet_trailer

__all__ = ["CODECS", "codecs_of", "row_count"]

CODECS = {
    0: "uncompressed",
    1: "snappy",
    2: "gzip",
    3: "lzo",
    4: "brotli",
    5: "lz4",
    6: "zstd",
    7: "lz4_raw",
}

_NUM_ROWS = 3
_ROW_GROUPS = 4
_COLUMNS = 1
_META_DATA = 3
_CODEC = 4

_TRUE, _FALSE, _BYTE, _I16, _I32, _I64, _DOUBLE, _BINARY, _LIST, _SET, _MAP, _STRUCT = range(1, 13)


class ParquetFooterError(Exception):
    """A file whose trailer is not one this decoder can read.

    Attributes:
      None.
    """


class _Reader:
    """A cursor over the footer bytes, decoding Thrift's compact protocol.

    Attributes:
      data: The footer bytes.
      at: The cursor position.
    """

    def __init__(self, data: bytes):
        """Positions the cursor at the start of the footer.

        Args:
          data: The footer bytes, without the length trailer or the magic.

        Returns:
          None.

        Raises:
          None.
        """
        self.data, self.at = data, 0

    def byte(self) -> int:
        """Reads one byte.

        Args:
          None.

        Returns:
          The byte's value.

        Raises:
          ParquetFooterError: At the end of the buffer, which means the footer is truncated.
        """
        if self.at >= len(self.data):
            raise ParquetFooterError("the footer ended mid-value")
        value = self.data[self.at]
        self.at += 1
        return value

    def unsigned(self) -> int:
        """Reads an unsigned LEB128 varint.

        Args:
          None.

        Returns:
          The value.

        Raises:
          ParquetFooterError: On a truncated varint.
        """
        value = shift = 0
        while True:
            part = self.byte()
            value |= (part & 0x7F) << shift
            if not part & 0x80:
                return value
            shift += 7

    def signed(self) -> int:
        """Reads a zigzag-encoded varint, which is how compact Thrift carries every integer.

        Args:
          None.

        Returns:
          The value.

        Raises:
          ParquetFooterError: On a truncated varint.
        """
        raw = self.unsigned()
        return (raw >> 1) ^ -(raw & 1)

    def value(self, kind: int):
        """Reads one value of the given compact-protocol type.

        Args:
          kind: The type nibble.

        Returns:
          The decoded value: a bool, an int, a float, bytes, a list, a dict or a field-numbered
          dict for a nested struct.

        Raises:
          ParquetFooterError: For a type this decoder does not implement, which means the
            format has grown something the two walks above may also need.
        """
        if kind in (_TRUE, _FALSE):
            return kind == _TRUE
        if kind == _BYTE:
            return self.byte()
        if kind in (_I16, _I32, _I64):
            return self.signed()
        if kind == _DOUBLE:
            packed = self.data[self.at : self.at + 8]
            self.at += 8
            return struct.unpack("<d", packed)[0]
        if kind == _BINARY:
            size = self.unsigned()
            packed = self.data[self.at : self.at + size]
            self.at += size
            return packed
        if kind in (_LIST, _SET):
            return self.collection()
        if kind == _STRUCT:
            return self.struct()
        if kind == _MAP:
            return self.mapping()
        raise ParquetFooterError(f"unhandled thrift type {kind}")

    def collection(self) -> list:
        """Reads a list or set header and its elements.

        A boolean ELEMENT is one byte, while a boolean struct FIELD is zero — its value lives
        in the type nibble — and ``value`` implements the field encoding. Decoding a boolean
        list with it would consume nothing and read every following byte as the next field: a
        wrong answer rather than an error. No Parquet footer reaches one, so it refuses instead
        of growing a second decoder for a case that cannot arrive.

        Args:
          None.

        Returns:
          The elements.

        Raises:
          ParquetFooterError: For a boolean element type, and propagated from the element reads.
        """
        header = self.byte()
        size, kind = header >> 4, header & 0xF
        if size == 15:
            size = self.unsigned()
        if kind in (_TRUE, _FALSE):
            raise ParquetFooterError("a boolean list needs the element encoding, not the field one")
        return [self.value(kind) for _ in range(size)]

    def mapping(self) -> dict:
        """Reads a map header and its entries.

        Args:
          None.

        Returns:
          The entries.

        Raises:
          ParquetFooterError: Propagated from the entry reads.
        """
        size = self.unsigned()
        if size == 0:
            return {}
        kinds = self.byte()
        key_kind, value_kind = kinds >> 4, kinds & 0xF
        return {self.value(key_kind): self.value(value_kind) for _ in range(size)}

    def struct(self) -> dict:
        """Reads a struct as a field-number-keyed dict, following compact Thrift's field deltas.

        Args:
          None.

        Returns:
          The struct's fields, keyed by field number.

        Raises:
          ParquetFooterError: Propagated from the field reads.
        """
        fields: dict[int, object] = {}
        field_id = 0
        while True:
            header = self.byte()
            if header == 0:
                return fields
            kind, delta = header & 0xF, header >> 4
            field_id = field_id + delta if delta else self.signed()
            fields[field_id] = self.value(kind)


def _metadata(path) -> dict:
    """Decodes one Parquet file's ``FileMetaData``.

    Read by SEEKING to the trailer rather than by reading the file. That is not a micro-
    optimisation: this module exists so the converter never materialises what it wrote, and a
    decoder that pulled a multi-gigabyte Parquet file into memory to find a 4 KB struct would
    size the function's memory against the output — the exact property the streaming writers
    were chosen to avoid. The trailer's checks are ``parquet_trailer.footer_span``'s, and this
    makes none of its own.

    Args:
      path: The written file.

    Returns:
      The metadata struct, keyed by field number.

    Raises:
      ParquetFooterError: When the file is not Parquet or its trailer will not decode.
    """
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        length = handle.tell()
        handle.seek(max(0, length - parquet_trailer.TRAILER_BYTES))
        trailer = handle.read(parquet_trailer.TRAILER_BYTES)
        try:
            offset, size = parquet_trailer.footer_span(length, trailer)
        except parquet_trailer.ParquetTrailerError as err:
            raise ParquetFooterError(f"{path}: {err}") from err
        handle.seek(offset)
        return _Reader(handle.read(size)).struct()


def row_count(path) -> int:
    """Returns how many rows a written Parquet file holds, from its footer alone.

    Args:
      path: The written file.

    Returns:
      The row count. Zero for a file carrying only a schema.

    Raises:
      ParquetFooterError: When the file is not Parquet or its trailer will not decode.
    """
    rows = _metadata(path).get(_NUM_ROWS)
    if not isinstance(rows, int):
        raise ParquetFooterError(f"{path} declares no row count")
    return rows


def codecs_of(path) -> set:
    """Returns every compression codec used by a written Parquet file's column chunks.

    A file with no rows has no column chunks and therefore no codec, which is why the
    assertion over the default belongs on a fixture that holds data.

    Args:
      path: The written file.

    Returns:
      The codec names. An unrecognised wire value comes back as ``codec-<n>`` rather than
      being dropped, so a codec Parquet adds later reads as a change instead of as an empty
      set — which is the answer that would pass an assertion about the default silently.

    Raises:
      ParquetFooterError: When the file is not Parquet, its trailer will not decode, or a
        column chunk declares no codec at all.
    """
    found: set[str] = set()
    for group in _metadata(path).get(_ROW_GROUPS) or []:
        for chunk in (group or {}).get(_COLUMNS) or []:
            codec = ((chunk or {}).get(_META_DATA) or {}).get(_CODEC)
            if not isinstance(codec, int):
                raise ParquetFooterError(f"{path} has a column chunk declaring no codec")
            found.add(CODECS.get(codec, f"codec-{codec}"))
    return found
