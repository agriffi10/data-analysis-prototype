"""Measures the results-conversion converter's output size and speed, per format.

``rccommon.config.OUTPUT_EXPANSION`` is bytes of output per byte of result CSV, and the size cap
each streamed format gets is derived from it — the scratch disk has to hold the downloaded object
and the written file at once. ``MEASURED_ON`` records what the numbers were measured against.
Until this script existed those figures had no runnable derivation: a reader could see the
constant and the sentence beside it, and had nothing to re-measure with.

**It drives the shipped verb, not a copy of it.** The frame is built by ``rc_convert._frame`` from
a schema ``rc_convert._schemas`` produced, and the file is written by ``rc_convert._write``. A
script that re-implemented the read or the write would measure itself, and the constant it fed
would describe a program nobody runs.

**Run it in the fleet image**, because polars' writers are what is being measured and the image is
where their version is pinned::

    docker build -f lambdas/Dockerfile -t lambda-fleet:measure .
    docker run --rm --entrypoint python3 \\
        -v "$PWD:/src" -w /src \\
        -e PYTHONPATH=/src/lambdas/results-conversion-convert:/src/lambdas/results-conversion-common:/src/lambdas/control-plane-common \\
        -e USER_SPACE_BUCKET=measure -e SHARED_SPACE_BUCKET=measure -e ADMIN_BUCKET=measure \\
        lambda-fleet:measure scripts/measure_conversion_expansion.py

The throughput column is local and is compared against production through the ratio the plane's
budget test applies; the expansion column is a property of the writers and of the data, not of the
machine.

Attributes:
  SIZES_MB: The four fixture sizes ``MEASURED_ON`` already names, so a new format's figure is
    measured over the same ladder as the ones beside it rather than over a ladder of its own.
  SHAPES: The generated result sets. ``mixed`` is an Athena-shaped result of the types a query
    actually returns. ``quoted`` and ``wide`` are the two that push a CSV conversion's own ratio
    up: every field holds a comma and a quote, so polars has to quote each one it writes and can
    shed none of the quoting Athena spent — and ``wide``'s fields are long enough that the two
    quotes they save are a vanishing share of the field, which is what takes the ratio to within
    a thousandth of 1. ``quoted`` alone was measured at 0.976 and read as the maximum, which it
    is not; the ceiling is 1, because polars quotes a SUBSET of the fields Athena quotes and
    doubles an inner quote exactly as Athena does. A format's figure is the WORST across every
    shape and size, which is what the constant's docstring says it is.
"""

import pathlib
import sys
import tempfile
import time

SIZES_MB = (7.2, 14.6, 29.2, 58.6)

SHAPES: dict[str, list[tuple[str, str, str]]] = {
    "mixed": [
        ("id", "bigint", "{i}"),
        ("stamp", "timestamp", "2026-09-{day:02d} 10:{minute:02d}:00.000"),
        ("name", "varchar", "customer-{i:012d}"),
        ("amount", "double", "{i}.25"),
        ("flag", "boolean", "true"),
        ("note", "varchar", "a note of ordinary width {i}"),
    ],
    "quoted": [
        ("id", "bigint", "{i}"),
        ("one", "varchar", 'a,b "{i}" c'),
        ("two", "varchar", 'x,y "{i}" z'),
        ("three", "varchar", 'p,q "{i}" r'),
        ("four", "varchar", 'l,m "{i}" n'),
    ],
    "wide": [
        ("id", "bigint", "{i}"),
        ("one", "varchar", 'a,b "{i}" ' + "w" * 2000),
        ("two", "varchar", 'x,y "{i}" ' + "w" * 2000),
    ],
}


def _described(shape: str) -> list[dict]:
    """The column metadata describe-results would emit for one shape.

    Args:
      shape: The shape's name.

    Returns:
      One ``{name, type}`` per column, in result order.

    Raises:
      None.
    """
    return [{"name": name, "type": kind} for name, kind, _ in SHAPES[shape]]


def _generate(shape: str, target_bytes: int, path: pathlib.Path) -> int:
    """Writes an Athena-shaped result object of about one size.

    Athena quotes EVERY field and doubles an embedded quote, and writes a NULL as an unquoted
    empty field. Both are reproduced here, because the quoting is most of what a CSV conversion's
    own ratio is about — a generator that left fields bare would measure a file Athena never
    writes and would understate the output against the input.

    Args:
      shape: The shape's name.
      target_bytes: How large to make it, approximately.
      path: Where to write it.

    Returns:
      The size actually written.

    Raises:
      None.
    """
    columns = SHAPES[shape]
    header = ",".join(f'"{name}"' for name, _, _ in columns) + "\n"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        written, row = len(header), 0
        while written < target_bytes:
            fields = []
            for _name, _kind, pattern in columns:
                value = pattern.format(i=row, day=(row % 28) + 1, minute=row % 60)
                fields.append('"' + value.replace('"', '""') + '"')
            line = ",".join(fields) + "\n"
            handle.write(line)
            written += len(line.encode("utf-8"))
            row += 1
    return path.stat().st_size


def _convert_once(convert, shape: str, source: pathlib.Path, fmt: str, out: pathlib.Path):
    """Runs the shipped read and the shipped write for one format, and times the write.

    Args:
      convert: The imported ``rc_convert`` module.
      shape: The shape's name, for its described columns.
      source: The generated result object.
      fmt: The output format.
      out: Where the converted file goes.

    Returns:
      The written size, the row count and the seconds the write took.

    Raises:
      Exception: Whatever the verb's own code raises.
    """
    read_schema, write_schema = convert._schemas(_described(shape), None, fmt)
    frame = convert._frame(source, read_schema)
    started = time.monotonic()
    rows, _precision = convert._write(fmt, frame, write_schema, out)
    elapsed = time.monotonic() - started
    return out.stat().st_size, rows, elapsed


def main() -> int:
    """Measures every format over every shape and size and prints the table.

    Args:
      None.

    The input and the outputs are prefixed apart because a CSV conversion writes a ``.csv``
    beside the ``.csv`` it reads: sharing the name measured a zero-byte file and deleted the
    fixture the next format was about to read.

    Returns:
      0.

    Raises:
      None.
    """
    import rc_convert as convert

    formats = ("csv", "parquet", "json")
    worst_expansion: dict[str, float] = {}
    worst_seconds_per_mb: dict[str, float] = {}
    scratch = pathlib.Path(tempfile.mkdtemp())
    print(f"{'shape':8} {'in MB':>8} {'format':8} {'out MB':>9} {'ratio':>7} {'rows':>9} {'MB/s':>8}")
    for shape in SHAPES:
        for size_mb in SIZES_MB:
            source = scratch / f"in-{shape}-{size_mb}.csv"
            size = _generate(shape, int(size_mb * 1024**2), source)
            for fmt in formats:
                out = scratch / f"out-{shape}-{size_mb}.{fmt}"
                written, rows, elapsed = _convert_once(convert, shape, source, fmt, out)
                ratio = written / size
                rate = (size / 1024**2) / elapsed if elapsed else float("inf")
                worst_expansion[fmt] = max(worst_expansion.get(fmt, 0.0), ratio)
                worst_seconds_per_mb[fmt] = max(
                    worst_seconds_per_mb.get(fmt, 0.0), elapsed / (size / 1024**2)
                )
                print(
                    f"{shape:8} {size / 1024**2:8.1f} {fmt:8} {written / 1024**2:9.2f} "
                    f"{ratio:7.3f} {rows:9d} {rate:8.1f}"
                )
                out.unlink()
            source.unlink()
    print()
    for fmt in formats:
        print(
            f"WORST {fmt}: expansion {worst_expansion[fmt]:.3f}, "
            f"throughput {1 / worst_seconds_per_mb[fmt]:.1f} MB/s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
