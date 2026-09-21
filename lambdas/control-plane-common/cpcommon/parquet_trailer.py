"""Where a Parquet object's footer sits, read from its size and its last eight bytes.

A Parquet file ends with its ``FileMetaData`` struct, that struct's length as four little-endian
bytes, and ``PAR1``. Two readers need the footer's position: the schema probe in
``bounded_read``, which fetches the footer alone from S3, and the converter's
``rccommon.parquet_footer``, which decodes a file it has just written. The checks live here once
so the two cannot drift apart, and the S3 reader gets the check it would otherwise have lacked —
a declared length longer than the object.

The file's LEADING ``PAR1`` is not checked. An object that ends in ``PAR1`` and declares a
footer it holds is decoded next, and a file that is not Parquet fails there; checking the head
would cost the S3 reader a third request for a check the decode already makes.

Attributes:
  MAGIC: The four bytes that open and close every Parquet file.
  TRAILER_BYTES: The footer's length field and the closing ``MAGIC``, which end every file.
  MIN_OBJECT_BYTES: The smallest object that can be Parquet at all: the opening ``MAGIC`` and
    the trailer, with no footer between them.
"""

import struct

MAGIC = b"PAR1"

TRAILER_BYTES = 8

MIN_OBJECT_BYTES = len(MAGIC) + TRAILER_BYTES


class ParquetTrailerError(ValueError):
    """A Parquet object whose footer a reader will not read: its trailer locates no footer the
    object holds, or — for the S3 probe — the footer is over the probe's bound or S3 did not send
    the range asked for.

    Attributes:
      None.
    """


def footer_span(object_size: int, trailer: bytes) -> tuple[int, int]:
    """Returns the footer's offset and length, from an object's size and its last eight bytes.

    The size is checked first, so a trailer shorter than eight bytes — which is all an object that
    small has — is never indexed. A zero-length footer is refused rather than returned: the
    range that would fetch it is inverted, and S3 answers an invalid range by ignoring it and
    sending the whole object.

    Args:
      object_size: The object's length in bytes.
      trailer: The object's last ``TRAILER_BYTES`` bytes, or the whole object when it is shorter.

    Returns:
      The footer's offset from the start of the object, and its length in bytes.

    Raises:
      ParquetTrailerError: For an object too short to be Parquet, a trailer that does not end in
        ``MAGIC``, a footer declared as zero bytes, or one declared longer than the object holds.
    """
    if object_size < MIN_OBJECT_BYTES:
        raise ParquetTrailerError(
            f"an object of {object_size} bytes is too short to be a Parquet file"
        )
    if trailer[-len(MAGIC) :] != MAGIC:
        raise ParquetTrailerError("the object does not end in PAR1, so it is not a Parquet file")
    length = struct.unpack("<I", trailer[-TRAILER_BYTES : -len(MAGIC)])[0]
    if length == 0:
        raise ParquetTrailerError("the object declares a footer of zero bytes")
    if length > object_size - MIN_OBJECT_BYTES:
        raise ParquetTrailerError(
            f"the object declares a {length}-byte footer it does not hold"
        )
    return object_size - TRAILER_BYTES - length, length
