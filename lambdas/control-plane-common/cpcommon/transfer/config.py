"""Sizing constants for the Distributed Map transfer.

These are the two numbers the fan-out is shaped by, and they are read from two places: the
batch verb (which they bound) and the rendered ASL (whose ``ItemBatcher`` and
``MaxConcurrency`` they set). Terraform cannot import Python, so the ASL carries literals fed
from ``locals.tf``; a test asserts the rendered numbers still equal these, because two homes
for one number is how a batch silently grows past the limit it was sized against.

Attributes:
  MAX_ITEMS_PER_BATCH: Items handed to one ``copy-objects`` invocation, and therefore the size
    of one child execution's input. **TWO bounds hold it, and the binding one is TIME, not
    payload size.** The payload bound is the 256 KB execution-input limit, taken at S3's worst
    case rather than a typical key: a 1024-byte source key, a 1024-byte destination key and
    63-byte bucket names put an item near 2.3 KB, so even 50 items sat under half the limit.
    That is why this was 50 until SPEC-161.

    The time bound is what moved it to 10. ``ItemBatcher`` batches by **count**, never by
    bytes, so the worst batch is ``MAX_ITEMS_PER_BATCH x SHARE_MAX_OBJECT_BYTES`` and the whole
    of it must copy inside ``copy-objects``' 900-second timeout on ``COPY_CONCURRENCY`` workers.
    While table-share's TOTAL cap was 20 GiB that bound was implicit — a batch could not exceed
    the whole table — and raising the total to 1 TiB removed it. At 10 items x 10 GiB the worst
    batch is 100 GiB, which finishes in ~537 s at a conservative 25 MB/s per stream; at the old
    50 it would have been 1000 GiB and timed out even at 100 MB/s per stream.
    ``test_a_worst_case_batch_stays_under_the_input_limit`` computes the payload bound and
    ``test_a_worst_case_batch_copies_inside_the_verb_timeout`` computes the time bound, so
    raising either constant without re-checking fails the build.
  MAP_MAX_CONCURRENCY: Child executions in flight. Deliberately not the 10,000 default — each
    child invokes a Lambda that opens up to ``COPY_CONCURRENCY`` S3 connections, so the default
    would put the account's whole Lambda concurrency and a large S3 request rate behind one
    user's share. At 20 the fan-out is up to 160 in-flight copies, which is throughput without
    a self-inflicted throttle.
  COPY_TIMEOUT_SECONDS: The batch verb's Lambda timeout, mirrored from ``locals.tf`` so the
    time bound above can be computed rather than asserted. A test holds the two together.
  CONSERVATIVE_STREAM_BYTES_PER_SECOND: The per-stream server-side copy throughput the time
    bound assumes. Deliberately pessimistic — a measured rate would make the bound depend on
    the day S3 was measured, and the cost of being wrong is a timed-out batch that fails a
    recipient. Raise it only with evidence.
"""

MAX_ITEMS_PER_BATCH = 10

MAP_MAX_CONCURRENCY = 20

COPY_TIMEOUT_SECONDS = 900

CONSERVATIVE_STREAM_BYTES_PER_SECOND = 25 * 1000**2
