"""Sizing constants for the Distributed Map transfer.

These are the two numbers the fan-out is shaped by, and they are read from two places: the
batch verb (which they bound) and the rendered ASL (whose ``ItemBatcher`` and
``MaxConcurrency`` they set). Terraform cannot import Python, so the ASL carries literals fed
from ``locals.tf``; a test asserts the rendered numbers still equal these, because two homes
for one number is how a batch silently grows past the limit it was sized against.

Attributes:
  MAX_ITEMS_PER_BATCH: Items handed to one ``copy-objects`` invocation, and therefore the size
    of one child execution's input. Sized against the 256 KB execution-input limit at S3's
    WORST case rather than a typical key: a 1024-byte source key, a 1024-byte destination key
    and 63-byte bucket names put an item near 2.3 KB, so 50 items sit under half the limit with
    ordinary Hive keys nowhere near it. ``test_a_worst_case_batch_stays_under_the_input_limit``
    computes that bound rather than asserting the number. The second bound is time: 50
    server-side copies on the bounded pool finish far inside ``copy-objects``' 900-second
    timeout even when several are multipart.
  MAP_MAX_CONCURRENCY: Child executions in flight. Deliberately not the 10,000 default — each
    child invokes a Lambda that opens up to ``COPY_CONCURRENCY`` S3 connections, so the default
    would put the account's whole Lambda concurrency and a large S3 request rate behind one
    user's share. At 20 the fan-out is up to 160 in-flight copies, which is throughput without
    a self-inflicted throttle.
"""

MAX_ITEMS_PER_BATCH = 50

MAP_MAX_CONCURRENCY = 20
