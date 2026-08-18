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
    That is why this is not the 50 it once was.

    The time bound is what moved it off 50, and it is a **makespan, not a bandwidth**.
    ``ItemBatcher`` batches by count and never by bytes, and ``copy_batch`` hands one WHOLE
    object to each of ``COPY_CONCURRENCY`` workers — ``copy_one``'s multipart loop is serial —
    so an object occupies one worker for ``size / rate`` no matter how many other workers are
    idle. A batch therefore costs ``ceil(items / COPY_CONCURRENCY)`` rounds of the slowest
    object in it, which is NOT ``total bytes / (workers x rate)``. Dividing bytes by aggregate
    bandwidth is what let this bound read as satisfied through three review rounds.

    **This is why the value equals ``COPY_CONCURRENCY``.** At 8 the ceiling is exactly one
    round, so a batch costs one object's time — 429 s for a 10 GiB object at the conservative
    rate, inside two thirds of ``COPY_TIMEOUT_SECONDS``. At 10 it was two rounds and 859 s,
    41 seconds from a hard Lambda timeout. Keeping the two equal makes the relationship
    structural rather than arithmetic: a batch is one round, always.
    ``test_a_worst_case_batch_stays_under_the_input_limit`` computes the payload bound,
    ``test_a_worst_case_batch_copies_inside_the_verb_timeout`` the makespan, and
    ``test_a_batch_is_exactly_one_round_of_the_worker_pool`` the invariant, so raising any of
    these constants without re-checking fails the build.
  MAP_MAX_CONCURRENCY: Child executions in flight. Deliberately not the 10,000 default — each
    child invokes a Lambda that opens up to ``COPY_CONCURRENCY`` S3 connections, so the default
    would put the account's whole Lambda concurrency and a large S3 request rate behind one
    user's share. At 20 the fan-out is up to 160 in-flight copies, which is throughput without
    a self-inflicted throttle.
  COPY_TIMEOUT_SECONDS: The batch verb's Lambda timeout, mirrored from ``locals.tf`` so the
    time bound above can be computed rather than asserted. A test holds the two together.
  CONSERVATIVE_STREAM_BYTES_PER_SECOND: The per-stream server-side copy throughput the time
    bounds assume. **A STREAM is one object on one worker** — not a share of some aggregate
    pipe — because that is how the copier schedules. Deliberately pessimistic: a measured rate
    would make the bound depend on the day S3 was measured, and the cost of being wrong is a
    timed-out batch that fails a recipient. Raise it only with evidence.
"""

MAX_ITEMS_PER_BATCH = 8

MAP_MAX_CONCURRENCY = 20

COPY_TIMEOUT_SECONDS = 900

CONSERVATIVE_STREAM_BYTES_PER_SECOND = 25 * 1000**2
