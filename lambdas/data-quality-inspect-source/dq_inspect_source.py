"""data-quality inspect-source — the control plane's second verb.

Given an authorized location, lists the objects under it, classifies each by file extension,
enforces that the folder is a single consistent format, probes every file's header or schema,
detects Hive-style partition directories, and writes the manifest.

Two things differ from the Lambda-era design and are deliberate. Parquet is a supported input,
because the natural workflow is convert-then-verify and rejecting it would leave the two arcs
unable to talk to each other. And there is no total-size cap: that ceiling was a Lambda artefact,
since Athena reads the data now, so the only caps left are on object count — the manifest and the
cross-file comparison scale with the number of files, not their size — and on compressed object
size, because gzip is not splittable.

This verb reads listings, object metadata and bounded headers only. Bulk reading is Athena's job;
byte-level reading is the byte-scan verb's.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  JSON_SAMPLE_ROWS: Rows the JSON probe reads to infer types. Bounds the read while giving type
    inference more than a single row to work with — a lone row of nulls would otherwise type a
    whole column as null.
  _GZIP_PROBE_LINES: Lines the compressed probe decompresses before giving up on finding more. A
    CSV needs one, for its header; NDJSON wants a sample.
  GZIP_PROBE_MAX_BYTES: Compressed bytes pulled from S3 before the stream is abandoned. Small
    enough that the probe is cheap on a large archive, large enough to hold a header line of any
    realistic width after decompression.
  GZIP_PROBE_MAX_DECOMPRESSED_BYTES: The second bound, and the one that actually protects the
    function. Bounding the compressed side alone is not enough — that is the whole point of a
    compression bomb: deflate reaches roughly a thousand to one, so one chunk can expand to
    hundreds of megabytes and the compressed bound to gigabytes, against this verb's memory. A
    single-line archive or one of repetitive padded rows sits far under the object-size cap and
    passes it, then exhausts the function — and running out of memory is not a terminal error, so
    the actor gets no notification and no reason, the silent-failure class this arc exists to
    eliminate. This bound is orders of magnitude more than a header plus a sample needs, and a
    source whose first rows genuinely exceed it fails loudly with a reason.
  MANIFEST_BASENAME: The manifest's filename inside the request's report prefix.
  _NOT_FOUND_CODES: S3 codes meaning no such object for the single-file probe. A head reports a
    missing key differently from a read, so all three are matched: a wrong guess would misread a
    real folder as an access error, or an access error as a folder.
  _is_compressed: Shared with the byte-scan verb — the two must agree on what compressed means,
    or a file this one classifies as gzipped text gets its compressor output scanned as text.
"""

import io
import json
import logging

from cpcommon import bounded_read, clients, errors, events, observability, s3_listing
from cpcommon.errors import TerminalError, TransientError
from cpcommon.type_mapping import UnmappableTypeError, map_dtype
from dqcommon import config, messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

JSON_SAMPLE_ROWS = 1000

_GZIP_PROBE_LINES = JSON_SAMPLE_ROWS + 1

GZIP_PROBE_MAX_BYTES = 8 * 1024 * 1024

GZIP_PROBE_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024

MANIFEST_BASENAME = "manifest.json"

_NOT_FOUND_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def _classify(key: str) -> str | None:
    """Classifies one object key by extension, stripping one trailing compression suffix.

    Two cases are unsupported by design rather than by omission: a bare compression suffix with no
    inner extension, because nothing says what is inside it and this arc does not sniff content;
    and compressed Parquet, which Athena cannot read and whose footer cannot be range-read through
    the wrapper, so it is rejected rather than half-supported.

    Args:
      key: The object key.

    Returns:
      The canonical format, or None when the extension is unsupported.

    Raises:
      None.
    """
    name = key.rsplit("/", 1)[-1].lower()
    if name.endswith(config.GZIP_SUFFIX):
        name = name[: -len(config.GZIP_SUFFIX)]
        if "." not in name:
            return None
        if name.endswith(".parquet"):
            return None
    dot = name.rfind(".")
    if dot == -1:
        return None
    return config.EXT_FORMAT.get(name[dot:])


_is_compressed = config.is_compressed


def _resolve_listing_prefix(bucket: str, location: str) -> tuple[str, bool]:
    """Decides whether a location is a single file or a folder, and what prefix to list.

    A single-file location must yield a one-object manifest and proceed normally, so it is listed
    as its own exact key. A folder is listed with a trailing slash, which is load-bearing: a
    listing is a prefix match, not a directory match, so listing without one would silently
    swallow sibling folders sharing the name as a prefix and the user would get a report over
    files they never selected.

    The same hazard applies to the file branch, which is what the second return value is for: a
    prefix match on a file name also returns every key that starts with it. Listing cannot express
    "this exact key", so the caller filters the result instead. Left as a filter rather than a
    head-built manifest so the file branch keeps going through the same listing, cap and probe
    path as a folder.

    A zero-byte hit is treated as a folder, not a file. S3 has no directories: a folder is a
    zero-byte placeholder object, so an object at the location key with no bytes is the folder.
    Without this, a placeholder would make the head succeed, the prefix would stay slash-less, and
    the listing would quietly pull in sibling folders — the placeholder itself is dropped by the
    listing rules, so nothing would fail.

    Args:
      bucket: The source bucket.
      location: The authorized location.

    Returns:
      A ``(prefix to list, is single file)`` tuple.

    Raises:
      TransientError: On a retryable S3 fault. A bare boto error would not be retried, so the head
        doubles as the access probe.
      ClientError: Any other deterministic fault propagates; nothing but a plain missing key is
        read as a folder.
    """
    try:
        head = clients.s3().head_object(Bucket=bucket, Key=location)
    except Exception as err:
        if errors.error_code(err) in _NOT_FOUND_CODES:
            return f"{location}/", False
        errors.raise_if_transient(err, f"head {bucket}/{location}")
        raise
    if not head.get("ContentLength"):
        return f"{location}/", False
    return location, True


def _only_selected(objects: list[tuple[str, int]], location: str) -> list[tuple[str, int]]:
    """Keeps only the exactly-matching key from a single-file listing.

    A listing is a prefix match, so a check on one file also returns every key that starts with
    its name. Left unfiltered, those extra keys made the parent-folder promotion downstream not
    apply, the table was built over nothing, and — because the grouping still emits a total row —
    the user got a clean verdict over zero rows that nothing had read.

    The trailing-slash strip matches the query builder's normalisation exactly. The two helpers
    are the pair that must never disagree about what one file means, and comparing a raw location
    here against a stripped one there is precisely how they would start to. Unreachable today,
    since a key ending in a slash is classified unsupported first, which is why it is worth
    pinning rather than leaving to luck.

    Args:
      objects: The listed objects.
      location: The authorized location.

    Returns:
      The matching object, or an empty list. Empty is returned rather than raised on: the head
      already proved the object exists with bytes, so the only way to get here is a delete between
      the head and the list, and the existing no-data refusal is the right answer for that.

    Raises:
      None.
    """
    selected = location.rstrip("/")
    return [(key, size) for key, size in objects if key == selected]


@observability.step("list-objects")
def _list_objects(bucket: str, prefix: str) -> list[tuple[str, int]]:
    """Lists the non-ignored data objects under a prefix.

    The shared segment-level hidden-path rule is what keeps this pipeline's own reports folder
    from being read back as source data, and it also drops the marker, the results and settings
    folders, and zero-byte placeholders. Nothing here re-implements those rules.

    Args:
      bucket: The source bucket.
      prefix: The prefix to list.

    Returns:
      The objects as key and size pairs.

    Raises:
      TransientError: On a retryable S3 fault. A throttled page mid-pagination is retryable, and
        the shared lister propagates it raw, which only helps a verb that maps it — this is that
        verb.
      ClientError: Any other deterministic fault propagates.
    """
    try:
        return list(s3_listing.list_data_objects(bucket, prefix))
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise


def _enforce_caps(objects: list[tuple[str, int]]) -> None:
    """Applies the object-count cap and the compressed-object size cap.

    Args:
      objects: The listed objects.

    Returns:
      None.

    Raises:
      TerminalError: ``too_many_files`` or ``compressed_source_too_large``.
    """
    if len(objects) > config.DQ_MAX_OBJECTS:
        raise TerminalError(
            messages.TOO_MANY_FILES,
            f"{len(objects)} objects exceeds DQ_MAX_OBJECTS={config.DQ_MAX_OBJECTS}",
            tokens={"count": f"{len(objects):,}"},
        )
    for key, size in objects:
        if _is_compressed(key) and size > config.DQ_MAX_GZIP_OBJECT_BYTES:
            raise TerminalError(
                messages.COMPRESSED_SOURCE_TOO_LARGE,
                f"{key} is {size} bytes, over DQ_MAX_GZIP_OBJECT_BYTES="
                f"{config.DQ_MAX_GZIP_OBJECT_BYTES} (gzip is not splittable)",
                tokens={"object": key},
            )


@observability.step("resolve-format")
def _resolve_format(objects: list[tuple[str, int]], location: str) -> str:
    """Resolves the single canonical format of a listing.

    Mirrors table-builder's rule, so a folder that arc rejects for mixed formats is rejected here
    for the same reason: any unsupported extension is terminal, and more than one surviving format
    is terminal. The unsupported message offers no convert-first guidance for spreadsheets, since
    they are unsupported everywhere and pointing the user at a converter would send them somewhere
    that cannot help.

    Args:
      objects: The listed objects.
      location: The authorized location, for the failure detail.

    Returns:
      The canonical format.

    Raises:
      TerminalError: ``no_data_files`` for an empty listing, ``unsupported_format`` for an
        unrecognised extension, or ``mixed_formats`` when several survive.
    """
    if not objects:
        raise TerminalError(messages.NO_DATA_FILES, f"no data files under {location!r}")

    formats = set()
    for key, _size in objects:
        fmt = _classify(key)
        if fmt is None:
            raise TerminalError(messages.UNSUPPORTED_FORMAT, f"unsupported file: {key}")
        formats.add(fmt)

    if len(formats) > 1:
        raise TerminalError(
            messages.MIXED_FORMATS,
            f"multiple formats present: {sorted(formats)}",
            tokens={"formats": ", ".join(sorted(formats))},
        )
    return next(iter(formats))


def _parquet_source(bucket: str, key: str):
    """Opens a ranged file object over a Parquet object, whose schema is a footer at the end.

    The seam the tests point at a local file — polars reads either the same way.

    Args:
      bucket: The source bucket.
      key: The object key.

    Returns:
      A seekable reader.

    Raises:
      None.
    """
    return bounded_read.S3RangeReader(bucket, key)


def _check_access(bucket: str, key: str) -> None:
    """Probes access to one object before reading it.

    Catches the common S3 faults — object missing, access denied, throttling — before the scan,
    keeping them distinct from the probe's own errors, which are terminal.

    It does not close the gap, and the limit is worth stating plainly: this is a check-then-act,
    and the polars scan afterwards is what actually pulls the data. If S3 throttles that read,
    polars raises its own error, which the probe cannot tell apart from a corrupt file and so
    terminalizes as an unreadable header — a permanent-sounding verdict on a transient fault.
    Narrowing it would mean pattern-matching AWS text out of a polars exception, which is fragile
    in a different way. Table-builder's inference carries the same shape; if this is ever fixed,
    fix it in both.

    Args:
      bucket: The source bucket.
      key: The object key.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault. Without that mapping it would arrive as an
        unretried client error and be recorded as a permanent failure.
      ClientError: Any other deterministic fault propagates.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise


def _stream_gzip_head(bucket: str, key: str) -> bytearray:
    """Applies this verb's probe bounds to the shared compressed-stream reader.

    A bounded range is impossible for a compressed object: the format is not seekable, so there is
    no byte range that yields the header. The shared module owns that mechanism and the
    compression-bomb guard; this binds the three limits so the numbers this arc promises stay
    visible in this arc.

    Args:
      bucket: The source bucket.
      key: The object key.

    Returns:
      The untrimmed decompressed head.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other deterministic fault propagates.
      zlib.error: If the object is not a valid archive.
    """
    return bounded_read.stream_gzip_head(
        bucket,
        key,
        max_lines=_GZIP_PROBE_LINES,
        max_compressed_bytes=GZIP_PROBE_MAX_BYTES,
        max_decompressed_bytes=GZIP_PROBE_MAX_DECOMPRESSED_BYTES,
    )


def _read_gzip_head(bucket: str, key: str) -> bytes:
    """Returns the bounded compressed head, trimmed to whole lines.

    Args:
      bucket: The source bucket.
      key: The object key.

    Returns:
      The decompressed head.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other deterministic fault propagates.
      zlib.error: If the object is not a valid archive.
    """
    return bounded_read.read_gzip_head(
        bucket,
        key,
        max_lines=_GZIP_PROBE_LINES,
        max_compressed_bytes=GZIP_PROBE_MAX_BYTES,
        max_decompressed_bytes=GZIP_PROBE_MAX_DECOMPRESSED_BYTES,
    )


def _read_plain_head(bucket: str, key: str) -> bytes:
    """Returns the bounded head of a plain line-delimited object, whole lines only.

    A boto3 read rather than a polars scan, because polars' cloud reader does not work in this
    Lambda — the shared module owns the mechanism and the reasoning. The head is enough for the
    probe, since a CSV header is line one and JSON inference samples the first rows, so a whole
    large file is never downloaded. Parquet is not read here: its schema lives in a footer.

    Args:
      bucket: The source bucket.
      key: The object key.

    Returns:
      The head bytes.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other deterministic fault propagates.
    """
    return bounded_read.read_head(
        bucket,
        key,
        max_lines=_GZIP_PROBE_LINES,
        max_bytes=GZIP_PROBE_MAX_DECOMPRESSED_BYTES,
    )


def _hive(dtype, name: str, key: str = "") -> str:
    """Maps one probed dtype to its Hive type, naming the file in any refusal.

    The key is threaded here purely so the notification can name the object: the column name alone
    tells a user nothing about which of many files to go and look at. It is the user-facing token;
    the column and dtype stay in the operator-only detail.

    Args:
      dtype: The probed polars dtype.
      name: The column name, for the detail.
      key: The object key, for the user-facing token.

    Returns:
      The Hive type string.

    Raises:
      TerminalError: ``unreadable_header`` when the dtype has no Hive equivalent.
    """
    try:
        return map_dtype(dtype)
    except UnmappableTypeError as exc:
        raise TerminalError(
            messages.UNREADABLE_HEADER,
            f"column {name!r} has unmappable dtype {dtype}",
            tokens={"object": key},
        ) from exc


def _columns_from(source, fmt: str, key: str = "") -> list[dict]:
    """Reads the ordered columns from one probe source.

    Parquet goes through the schema reader rather than a lazy scan, which over a file object would
    read the whole object in one call. CSV reads the header only with no type inference, so every
    column is a string, matching the SerDe the temp table uses — and polars parses the header
    properly, so a quoted name containing a delimiter survives where a hand-rolled split would not.
    JSON streams a bounded sample.

    Args:
      source: An in-memory buffer of head bytes for text formats, plain or already decompressed,
        or a seekable ranged file object for Parquet.
      fmt: The canonical format.
      key: The object key, for the user-facing token in any refusal.

    Returns:
      The ordered columns, every format yielding the same shape. A type per column is needed
      because Athena does not auto-detect a Parquet schema.

    Raises:
      TerminalError: ``unreadable_header`` for an unmappable dtype or an unknown format.
    """
    import polars as pl

    if fmt == "parquet":
        schema = pl.read_parquet_schema(source)
        return [{"name": n, "type": _hive(d, n, key)} for n, d in schema.items()]

    if fmt == "csv":
        schema = pl.scan_csv(source, infer_schema_length=0).collect_schema()
        return [{"name": n, "type": "string"} for n in schema.names()]

    if fmt == "json":
        frame = pl.scan_ndjson(
            source,
            infer_schema_length=JSON_SAMPLE_ROWS,
            n_rows=JSON_SAMPLE_ROWS,
        ).collect()
        return [{"name": n, "type": _hive(d, n, key)} for n, d in frame.schema.items()]

    raise TerminalError(
        messages.UNREADABLE_HEADER, f"unknown format {fmt!r}", tokens={"object": key}
    )


def _probe_columns(bucket: str, key: str, fmt: str) -> list[dict]:
    """Reads the ordered columns of one object.

    A file whose header or schema cannot be read fails the whole request rather than being
    skipped: checking a folder while quietly ignoring a file we cannot parse would produce a
    report that omits the worst file in it.

    A transient error passes through rather than being caught by the general guard: the head read
    runs inside the same try, so a throttled read would otherwise be reported as an unreadable
    header — a permanent verdict on a fault the state machine would happily have retried.

    Args:
      bucket: The source bucket.
      key: The object key.
      fmt: The canonical format.

    Returns:
      The ordered columns.

    Raises:
      TerminalError: ``unreadable_header`` for a corrupt or mistyped object.
      TransientError: On a retryable S3 fault.
    """
    _check_access(bucket, key)
    try:
        if _is_compressed(key):
            return _columns_from(io.BytesIO(_read_gzip_head(bucket, key)), fmt, key=key)
        if fmt == "parquet":
            return _columns_from(_parquet_source(bucket, key), fmt, key=key)
        return _columns_from(io.BytesIO(_read_plain_head(bucket, key)), fmt, key=key)
    except (TerminalError, TransientError):
        raise
    except Exception as exc:
        raise TerminalError(
            messages.UNREADABLE_HEADER,
            f"could not read the schema of {key}: {exc}",
            tokens={"object": key},
        ) from exc


@observability.step("probe-columns")
def _probe_all(bucket: str, objects: list[tuple[str, int]], fmt: str) -> list[dict]:
    """Probes every object's columns, as one step.

    Every file is probed, not one sample: the per-file column lists are what the cross-file
    agreement check compares, and a single sample cannot show disagreement.

    The span wraps the whole loop rather than the per-object probe. A large folder would otherwise
    mint hundreds of child spans for one invocation, each an SQS message and a line in a day object
    the sweep rewrites in full. One span still answers the question the step exists for: how much
    of the verb's time went into reading headers.

    Args:
      bucket: The source bucket.
      objects: The listed objects.
      fmt: The canonical format.

    Returns:
      One manifest entry per object, carrying its key, size and columns.

    Raises:
      TerminalError: ``unreadable_header`` for any object that cannot be probed.
      TransientError: On a retryable S3 fault.
    """
    return [
        {"key": key, "size": size, "columns": _probe_columns(bucket, key, fmt)}
        for key, size in objects
    ]


def _relative_dirs(key: str, listing_prefix: str) -> list[str]:
    """Returns one key's directory segments beneath the listing prefix.

    Args:
      key: The object key.
      listing_prefix: The prefix the listing used.

    Returns:
      The directory segments, excluding the filename.

    Raises:
      None.
    """
    rel = key.removeprefix(listing_prefix)
    return rel.split("/")[:-1]


@observability.step("detect-partitions")
def _detect_partition_keys(objects: list[tuple[str, int]], listing_prefix: str) -> list[dict]:
    """Detects the ordered Hive partition keys and their observed values, or none if flat.

    Keys are auto-detected from the paths here, unlike table-builder where the user declares them
    and each object is validated against that declaration. With no declaration to check against,
    consistency has to be derived from the data itself.

    Every object must therefore yield the same ordered keys, and a partitioned source may not
    carry a plain directory segment. The disaster this prevents: the temp table is built with its
    location at the folder root and projection over these keys, so Athena only ever resolves the
    projected paths. An object outside those paths belongs to no partition, is never scanned, and
    is silently omitted from the report — the user would get a clean verdict over a folder we did
    not fully read. That is the same harm the unreadable-header refusal exists for.

    An empty key or value is the same harm as a layout mismatch: Hive spells an absent value
    ``__HIVE_DEFAULT_PARTITION__``, so the projection enum would instead contain an empty string
    — a partition that resolves to nothing, whose files are then silently missing from the
    report.

    The result is sorted for determinism: the manifest and the projection enum are compared across
    retries, and listing order is not guaranteed stable.

    Args:
      objects: The listed objects.
      listing_prefix: The prefix the listing used.

    Returns:
      The ordered keys with their observed values, or an empty list for a flat source — plain
      nested folders are fine, since Athena reads them recursively.

    Raises:
      TerminalError: ``partition_layout_mismatch`` for a plain segment in a partitioned source,
        disagreeing key orders, or an empty key or value; ``too_many_partition_values`` when a key
        exceeds the value cap.
    """
    dirs_by_key = {key: _relative_dirs(key, listing_prefix) for key, _ in objects}
    if not any("=" in seg for dirs in dirs_by_key.values() for seg in dirs):
        return []

    expected: tuple[str, ...] | None = None
    values: dict[str, list[str]] = {}
    for key, dirs in dirs_by_key.items():
        plain = [seg for seg in dirs if "=" not in seg]
        if plain:
            raise TerminalError(
                messages.PARTITION_LAYOUT_MISMATCH,
                f"{key} has non-partition folder segment(s) {plain} in a partitioned source",
                tokens={"object": key},
            )
        names = tuple(seg.split("=", 1)[0] for seg in dirs)
        if expected is None:
            expected = names
        elif names != expected:
            raise TerminalError(
                messages.PARTITION_LAYOUT_MISMATCH,
                f"{key} has partition keys {list(names)}, but the source uses {list(expected)}",
                tokens={"object": key},
            )
        for seg in dirs:
            name, value = seg.split("=", 1)
            if not name or not value:
                raise TerminalError(
                    messages.PARTITION_LAYOUT_MISMATCH,
                    f"{key} has an empty partition key or value in segment {seg!r}",
                    tokens={"object": key},
                )
            seen = values.setdefault(name, [])
            if value not in seen:
                seen.append(value)

    for name, seen in values.items():
        if len(seen) > config.DQ_MAX_PARTITION_VALUES:
            raise TerminalError(
                messages.TOO_MANY_PARTITION_VALUES,
                f"partition key {name!r} has {len(seen)} values, over "
                f"DQ_MAX_PARTITION_VALUES={config.DQ_MAX_PARTITION_VALUES}",
                tokens={"key": name, "count": f"{len(seen):,}"},
            )

    return [{"name": name, "values": sorted(values[name])} for name in expected]


def _manifest_key(report_prefix: str) -> str:
    """Derives the manifest's key, purely from the request's report prefix.

    The validate verb derives that prefix from the request id alone, so this key is too. That is
    what makes the pipeline replay-safe: a retry re-runs the whole verb and overwrites the manifest
    byte-identically, which is the only idempotency this codebase has.

    Args:
      report_prefix: The request's report prefix.

    Returns:
      The manifest key.

    Raises:
      None.
    """
    return f"{report_prefix.rstrip('/')}/{MANIFEST_BASENAME}"


@observability.step("write-inspection-manifest")
def _write_manifest(bucket: str, key: str, manifest: dict) -> None:
    """Writes the manifest canonically and compactly.

    Dropping the default whitespace is a real size saving at the object cap with wide column
    lists, in the object written here and read back later. Sorting the keys makes the output
    canonical rather than dependent on how the dict happened to be built — defence against a
    future edit, not what makes a replay byte-identical, which follows from the manifest being a
    pure function of the request and the listing.

    The span is not named after this function. `write-manifest` is a whole verb elsewhere in the
    fleet and `function` carries a verb's root span and a step alike, so the two would arrive as
    one field an operator cannot separate: an invocation's total duration mixed with this write's.

    Args:
      bucket: The reports bucket.
      key: The manifest key.
      manifest: The manifest document.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault. Losing the manifest to a one-off throttle must not
        fail the request: the whole verb is replay-safe, so a retry simply rewrites it, and
        unmapped this would arrive as an unretried client error after all the probing work is done.
      ClientError: Any other deterministic fault propagates.
    """
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise


def _inspect(event: dict) -> dict:
    """Lists, caps, classifies, partitions and probes the source, then writes the manifest.

    The single-file filter runs before the caps and before the format check, so neither can see —
    nor name in a refusal — a sibling the user did not select.

    Column names and partition-key names are recorded deliberately, reversing the instinct to be
    cautious with anything that came out of a file: a name is schema, and schema is what a schema
    bug is about. Column values would be file contents and are never recorded anywhere in this
    plane.

    **Whether this is a single-file check is decided here, and nowhere later.** The file list in
    hand is the one the manifest is about to be written from; every later verb would otherwise
    have to read the manifest back, from a key a caller can predict, and two reads are two
    decisions. So the answer rides the state as ``pathFilter`` and create and start both consume
    it — see ``dqcommon.sql.single_file_path``.

    The state output threads the request object and adds five small keys. The file list and the
    column lists stay in the manifest and are passed by pointer; partition values stay there too,
    since there can be many per key. The disaster this prevents is a state payload over the limit,
    which raises ``States.DataLimitExceeded`` and escapes every Catch here (``States.ALL`` does
    not match it and none names it) — the execution dies without reaching the notify state and
    the user is never told anything at all, on exactly the biggest folders. Threading the whole
    event is deliberate: dropping the request id or actor would make the terminal states hard-fail
    on an absent path, equally uncatchable, so "only these keys" means "add only these", not "keep
    only these".

    Args:
      event: The task input.

    Returns:
      The event with the manifest key, format, file count, partition key names and the
      single-file path filter added.

    Raises:
      TerminalError: Any inspection refusal.
      TransientError: On a retryable S3 fault.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)
    request_id = events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)

    listing_prefix, single_file = _resolve_listing_prefix(bucket, location)
    objects = _list_objects(bucket, listing_prefix)
    if single_file:
        objects = _only_selected(objects, location)
    _enforce_caps(objects)
    fmt = _resolve_format(objects, location)
    partition_keys = _detect_partition_keys(objects, listing_prefix)

    files = _probe_all(bucket, objects, fmt)

    manifest_key = _manifest_key(report_prefix)
    _write_manifest(
        bucket,
        manifest_key,
        {
            "requestId": request_id,
            "format": fmt,
            "fileCount": len(files),
            "partitionKeys": partition_keys,
            "files": files,
        },
    )

    logger.info(
        "inspected %s/%s: format=%s, %d files, partitionKeys=%s -> %s",
        bucket,
        listing_prefix,
        fmt,
        len(files),
        [k["name"] for k in partition_keys],
        manifest_key,
    )
    observability.info(
        "inspected source",
        prefix=listing_prefix,
        bucket=bucket,
        objects=len(files),
        bytes=sum(size for _key, size in objects),
        format=fmt,
        column_names=sorted({c["name"] for f in files for c in f["columns"]}),
        columns=len({c["name"] for f in files for c in f["columns"]}),
        partition_key_names=[k["name"] for k in partition_keys],
        capped=len(objects) >= config.DQ_MAX_OBJECTS,
        manifest_key=manifest_key,
    )

    out = dict(event)
    out["manifestKey"] = manifest_key
    out["format"] = fmt
    out["fileCount"] = len(files)
    out["partitionKeys"] = [k["name"] for k in partition_keys]
    out["pathFilter"] = sql.single_file_path(bucket, files, location)
    return out


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect-source")
def handler(event, context) -> dict:
    """Inspects the authorized location, writes the manifest, and passes its key onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    The failure detail is omitted here, and this is the one place in the front half where it is.
    The probe's general guard builds its detail from the underlying parse error, and polars quotes
    the offending value in its message — that is a cell out of a user's file wearing an error
    message, in a store retained forever. The reason token and the exception type answer why it
    stopped; the specific bad value is in CloudWatch, which is not retained forever, for the
    operator who needs it. It is suppressed for every terminal from this verb rather than only the
    unreadable ones, because the alternative is a denylist of reasons that the next reason added is
    added without.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the manifest key, format, file count, partition key names and the
      single-file path filter added.

    Raises:
      TerminalError: Any inspection refusal.
      TransientError: On a retryable S3 fault.
    """
    try:
        return _inspect(event)
    except TerminalError as err:
        observability.error(
            "inspect-source failed",
            error_type=type(err).__name__,
            reason=err.reason,
            tokens=err.tokens or {},
            detail_suppressed=True,
        )
        raise
