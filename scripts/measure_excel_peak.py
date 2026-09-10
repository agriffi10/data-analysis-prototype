"""Measure the Excel converter's peak memory per cell, per shape, inside the fleet image.

The Excel caps in ``rccommon.config`` are derived from what this prints, and the plane suite's
``MEASURED_EXCEL_SHAPES`` corpus is its output. Re-run it whenever polars or xlsxwriter moves, or
the image does: the constants are only as true as the library that produced them.

Each shape is a generated Athena-shaped result — every field quoted, NULL as an unquoted blank —
run through the converter's own ``_frame`` and ``_write_excel`` in ONE container per run, so the
peak is that run's alone. It is measured at two sizes and the per-cell figure is the SLOPE
between them, which cancels the fixed cost of importing the Excel path. The peak read is the
container's cgroup v2 ``memory.peak``: it counts the page cache of the CSV and of xlsxwriter's
temporary XML as well as the process, so it is the larger and the more conservative of the two
measures. The process's own peak RSS is printed beside it.

The caps are LIFTED inside the worker, because most of the corpus was measured above them: a
shape run at the sizes its row was measured at would otherwise be refused before it is built.

Build the image first, for either architecture::

    DOCKER_BUILDKIT=1 docker buildx build --load -f lambdas/Dockerfile -t dq-fleet:measure .
    DOCKER_BUILDKIT=1 docker buildx build --platform linux/amd64 --load \\
        -f lambdas/Dockerfile -t dq-fleet:measure-amd64 .

BuildKit is required: the image's ``lambdas/Dockerfile.dockerignore`` is read only by BuildKit,
and the legacy builder falls back to the root ``.dockerignore``, which excludes ``lambdas/``.

Then, for example::

    python3 scripts/measure_excel_peak.py --image dq-fleet:measure uniq20x15
    python3 scripts/measure_excel_peak.py --image dq-fleet:measure-amd64 --platform linux/amd64

**Memory transfers across architectures and time does not.** Production runs amd64; an amd64
image under emulation on an arm64 machine measures memory within a few percent of the native
figure and is how the two were compared, but its TIME is the emulator's. The local rate this
prints is only meaningful from a native run, and it is slowed by the measured
local-to-production ratio before any check compares it with the converter's timeout.

Attributes:
  SHAPES: Every shape the corpus names: its label, its column types, the two row counts it is
    measured at, and the function that generates one row's values.
  _CONTAINER_WORK: Where the host's working directory is mounted inside the container.
  _DESCRIPTION: The command line's one-line summary.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class Shape(NamedTuple):
    """One measured shape.

    Attributes:
      label: The name its row carries in the plane suite's corpus.
      types: One Athena type per column, in order.
      sizes: The two row counts the slope is taken between.
      row: The values of row ``r``; ``None`` is a NULL.
    """

    label: str
    types: tuple[str, ...]
    sizes: tuple[int, int]
    row: Callable[[int], Sequence[object]]


def _same(athena: str, value: object, width: int = 15) -> tuple[tuple[str, ...], Callable[[int], Sequence[object]]]:
    """A shape whose every cell is one value of one type.

    Args:
      athena: The column type.
      value: The value every cell holds.
      width: The column count.

    Returns:
      The column types and the row function.

    Raises:
      None.
    """
    return (athena,) * width, lambda r: [value] * width


def _registry() -> dict[str, Shape]:
    """Builds the shape registry, keyed by the short name the command line takes.

    Args:
      None.

    Returns:
      Every shape, in the corpus's order.

    Raises:
      None.
    """
    fifteen = (100_000, 300_000)
    four = (300_000, 1_000_000)
    shapes = {
        "null_varchar": ("NULL text", *_same("varchar", None), fifteen),
        "empty_varchar": ("empty text", *_same("varchar", ""), fifteen),
        "str1x15": (
            "one-character text, the query that timed out in production",
            ("varchar",) * 15,
            lambda r: list("abcdefghijklmno"),
            fifteen,
        ),
        "int1": ("small integer", *_same("integer", 1), fifteen),
        "int_uniq": (
            "unique integer",
            ("integer",) * 15,
            lambda r: [r * 15 + i + 1000 for i in range(15)],
            fifteen,
        ),
        "double": ("double", *_same("double", 1.5), fifteen),
        "bool": ("boolean", *_same("boolean", "true"), fifteen),
        "date": ("date", *_same("date", "2020-01-02"), fifteen),
        "ts": ("timestamp", *_same("timestamp", "2020-01-02 03:04:05.123"), fifteen),
        "decimal": ("decimal(10,2)", *_same("decimal(10,2)", "123.45"), fifteen),
        "dec38": (
            "unique decimal(38,10)",
            ("decimal(38,10)",) * 15,
            lambda r: [f"{r:027d}.{i:010d}" for i in range(15)],
            fifteen,
        ),
        "uniq20x15": (
            "unique 20-character text",
            ("varchar",) * 15,
            lambda r: [f"{r:012d}{i:02d}unique" for i in range(15)],
            fifteen,
        ),
        "uniq40x15": (
            "unique 37-character text",
            ("varchar",) * 15,
            lambda r: [f"{r:012d}{i:02d}" + "u" * 23 for i in range(15)],
            fifteen,
        ),
        "null_int": ("NULL integer", *_same("integer", None), fifteen),
        "null_double": ("NULL double", *_same("double", None), fifteen),
        "str1x60": ("one-character text, sixty wide", *_same("varchar", "a", 60), (30_000, 90_000)),
        "prod490": (
            "three bigints and a label, the 490,000-row production run",
            ("bigint", "bigint", "bigint", "varchar"),
            lambda r: [
                r // 700 + 1,
                r % 700 + 1,
                (r // 700 + 1) * (r % 700 + 1),
                f"row-{(r // 700 + 1) * 1000 + r % 700 + 1}",
            ],
            (122_500, 490_000),
        ),
        "live4m": (
            "unique 13-character text, the live check at the caps",
            ("varchar",) * 4,
            lambda r: [f"{r:012d}{chr(97 + i)}" for i in range(4)],
            (250_000, 1_000_000),
        ),
        "uniq16x4": (
            "unique 16-character text",
            ("varchar",) * 4,
            lambda r: [f"{r:010d}{i:02d}uniq" for i in range(4)],
            (250_000, 1_000_000),
        ),
        "ts4": ("timestamp, four wide", *_same("timestamp", "2020-01-02 03:04:05.123", 4), four),
        "dec4": ("decimal(10,2), four wide", *_same("decimal(10,2)", "123.45", 4), four),
        "uniq200x4": (
            "unique 200-character text",
            ("varchar",) * 4,
            lambda r: [(f"{r:08d}{i}" * 23)[:200] for i in range(4)],
            (100_000, 300_000),
        ),
        "str1x1": ("one-character text, one wide", ("varchar",), lambda r: ["a"], (500_000, 1_048_575)),
    }
    return {
        key: Shape(label=label, types=types, sizes=sizes, row=row)
        for key, (label, types, row, sizes) in shapes.items()
    }


SHAPES = _registry()

_CONTAINER_WORK = "/work"

_DESCRIPTION = "Measure the Excel converter's peak memory per cell, per shape, inside the fleet image."


def _quoted(value: object) -> str:
    """Renders one cell the way Athena writes its result CSV.

    Args:
      value: The cell's value, or ``None`` for a NULL.

    Returns:
      The field: quoted, with quotes doubled, or empty and unquoted for a NULL.

    Raises:
      None.
    """
    if value is None:
        return ""
    return '"' + str(value).replace('"', '""') + '"'


def _generate(shape: Shape, rows: int, path: pathlib.Path) -> None:
    """Writes one Athena-shaped result object.

    Args:
      shape: The shape.
      rows: How many data rows.
      path: Where to write it.

    Returns:
      None.

    Raises:
      OSError: If the file cannot be written.
    """
    names = [f"c{i:02d}" for i in range(1, len(shape.types) + 1)]
    with path.open("w", newline="") as handle:
        handle.write(",".join(_quoted(name) for name in names) + "\n")
        for r in range(rows):
            handle.write(",".join(_quoted(value) for value in shape.row(r)) + "\n")


def _described(types: tuple[str, ...]) -> list[dict]:
    """Describes the columns the way describe-results does, a decimal's parameters included.

    Args:
      types: The Athena types.

    Returns:
      One ``{name, type}`` per column, with ``precision`` and ``scale`` for a decimal.

    Raises:
      None.
    """
    described: list[dict] = []
    for index, athena in enumerate(types, start=1):
        entry: dict = {"name": f"c{index:02d}", "type": athena}
        if athena.startswith("decimal("):
            precision, scale = athena[len("decimal(") : -1].split(",")
            entry = {**entry, "type": "decimal", "precision": int(precision), "scale": int(scale)}
        described.append(entry)
    return described


def _cgroup(name: str) -> int | None:
    """Reads one cgroup v2 memory counter for the container this runs in.

    Args:
      name: The counter's file name.

    Returns:
      Its value in bytes, or None where the counter is not available.

    Raises:
      None.
    """
    try:
        return int(pathlib.Path(f"/sys/fs/cgroup/{name}").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _worker(key: str, rows: int) -> None:
    """Runs inside the container: generates one size of one shape, converts it, prints the peak.

    Args:
      key: The shape's short name.
      rows: How many data rows.

    Returns:
      None. Prints one JSON object.

    Raises:
      KeyError: For an unknown shape.
    """
    os.environ.setdefault("USER_SPACE_BUCKET", "measure-bucket")
    sys.path[:0] = ["/opt/python", os.environ.get("LAMBDA_TASK_ROOT", "/var/task")]
    rc_config: Any = importlib.import_module("rccommon.config")
    rc_types = importlib.import_module("rccommon.types")
    rc_convert = importlib.import_module("rc_convert")
    rc_config.EXCEL_MAX_ROWS = sys.maxsize
    rc_config.EXCEL_MAX_CELLS = sys.maxsize
    shape = SHAPES[key]
    work = pathlib.Path(tempfile.mkdtemp(prefix="measure-excel-"))
    source = work / "results.csv"
    _generate(shape, rows, source)
    schema = rc_types.schema_of(_described(shape.types))
    started = time.monotonic()
    written, _ = rc_convert._write_excel(rc_convert._frame(source, schema), schema, work / "out.xlsx")
    seconds = time.monotonic() - started
    print(
        json.dumps(
            {
                "shape": key,
                "rows": rows,
                "written": written,
                "columns": len(shape.types),
                "csv_bytes": source.stat().st_size,
                "seconds": seconds,
                "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                "peak_cgroup": _cgroup("memory.peak"),
            }
        )
    )
    shutil.rmtree(work, ignore_errors=True)


def _run_once(image: str, platform: str | None, mount: pathlib.Path, key: str, rows: int) -> dict:
    """Runs one size of one shape in its own container.

    Args:
      image: The fleet image's tag.
      platform: A ``--platform`` for the container, or None for the native one.
      mount: The host directory holding a copy of this script.
      key: The shape's short name.
      rows: How many data rows.

    Returns:
      The worker's JSON object.

    Raises:
      subprocess.CalledProcessError: If the container fails.
    """
    command = ["docker", "run", "--rm", "-v", f"{mount}:{_CONTAINER_WORK}", "--entrypoint", "python"]
    if platform:
        command += ["--platform", platform]
    command += [image, f"{_CONTAINER_WORK}/{pathlib.Path(__file__).name}", "--worker", key, str(rows)]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    result: dict = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


def _measure(image: str, platform: str | None, keys: list[str]) -> list[dict]:
    """Measures each shape at its two sizes and reduces the pair to a slope.

    Args:
      image: The fleet image's tag.
      platform: A ``--platform`` for the containers, or None.
      keys: The shapes to measure.

    Returns:
      One row per shape: the label, the columns, CSV bytes per cell, peak bytes per cell by
      cgroup and by RSS, the cgroup peak extrapolated to no cells (the shape's fixed cost, in
      MiB), and cells per second.

    Raises:
      subprocess.CalledProcessError: If a container fails.
    """
    mount = pathlib.Path(tempfile.mkdtemp(prefix="measure-excel-host-"))
    shutil.copy(__file__, mount / pathlib.Path(__file__).name)
    rows_out = []
    try:
        for key in keys:
            shape = SHAPES[key]
            small, large = (_run_once(image, platform, mount, key, rows) for rows in shape.sizes)
            cells = (large["rows"] - small["rows"]) * large["columns"]
            slope = (large["peak_cgroup"] - small["peak_cgroup"]) / cells
            rows_out.append(
                {
                    "shape": key,
                    "label": shape.label,
                    "columns": large["columns"],
                    "csv_bytes_per_cell": round(large["csv_bytes"] / (large["rows"] * large["columns"]), 2),
                    "peak_bytes_per_cell": round(slope, 1),
                    "rss_bytes_per_cell": round((large["peak_rss"] - small["peak_rss"]) / cells, 1),
                    "intercept_mib": round(
                        (small["peak_cgroup"] - slope * small["rows"] * small["columns"]) / 1024**2, 1
                    ),
                    "cells_per_second": round(cells / (large["seconds"] - small["seconds"])),
                }
            )
    finally:
        shutil.rmtree(mount, ignore_errors=True)
    return rows_out


def main(argv: list[str] | None = None) -> int:
    """Measures the named shapes, or every shape, and prints one JSON line per shape.

    Args:
      argv: The command line, without the program name; None reads ``sys.argv``.

    Returns:
      The exit status.

    Raises:
      None.
    """
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument("shapes", nargs="*", help=f"any of: {', '.join(SHAPES)} (default: all)")
    parser.add_argument("--image", default="dq-fleet:measure", help="the built fleet image's tag")
    parser.add_argument("--platform", default=None, help="e.g. linux/amd64 for an emulated run")
    parser.add_argument("--worker", nargs=2, metavar=("SHAPE", "ROWS"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        _worker(args.worker[0], int(args.worker[1]))
        return 0
    unknown = [key for key in args.shapes if key not in SHAPES]
    if unknown:
        parser.error(f"unknown shape(s): {', '.join(unknown)}")
    for row in _measure(args.image, args.platform, args.shapes or list(SHAPES)):
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
