"""Domain configuration for the table-share control plane.

The shared core — region, user pool identifiers, buckets, workgroup, notifications queue, the
catalog identifier rule — lives in ``cpcommon.config``. Only table-share's own constants live
here. The sizing evidence behind the four caps is in ``docs/lambda-rationale.md``.

Every cap below is a whole-request terminal in inspect-source, raised before either artifact
is written, so a refused share leaves nothing behind and no recipient runs.

Attributes:
  SHARE_MAX_OBJECTS: Object-count cap. **What sizes it is inspect-source's listing time.**
    ``list_data_objects`` pages at 1000 keys, so 20,000 objects is 20 ListObjectsV2 round
    trips — one to two seconds of a 60-second budget — and the copy plan it writes is about
    3.4 MB. It is no longer sized by the copy: SPEC-160 made that a Distributed Map over
    batches, so no single invocation carries a recipient's whole table any more.
  SHARE_MAX_TOTAL_BYTES: Total-size cap. **What sizes it is the Map Run's wall clock.** The
    fan-out reaches 160 concurrent server-side copies (``MAP_MAX_CONCURRENCY`` children x
    ``COPY_CONCURRENCY`` workers), so 1 TiB is roughly six minutes at 20 MB/s per stream and
    twenty-two at a pessimistic 5 MB/s — comfortably inside the state machine's
    ``TimeoutSeconds``, which is what a share that cannot finish now runs into.
  SHARE_MAX_TRANSFER_ITEMS: Cap on ``recipients x objects`` — the manifest's real bound, and
    the one neither cap above expresses, since 20,000 objects to 50 recipients is a million
    transfer items. **What sizes it is the manifest write and the collector's read-back**,
    which are the same volume in both directions: at S3's worst-case 1024-byte keys an item
    is about 2.3 KB, so 20,000 items is a ~46 MB manifest, and the Map Run export
    ``collect-transfer-results`` reads carries every batch's input again. Both verbs are
    sized for that (locals.tf). Step Functions' own limits are nowhere near binding — an
    ItemReader file may be 10 GB and a Map Run 100,000,000 items.
  RECIPIENT_KINDS: The two recipient kinds a share request may target.
  SHARE_MAX_RECIPIENTS: Recipient cap. What it prevents is not the fan-out but the Map's
    result: each failed item carries the raw Step Functions error, and breaching the 256 KB
    state payload raises a limit error on the Map that destroys every per-recipient outcome
    the Map exists to preserve. A test computes the worst case from these constants, so
    changing one without re-checking the other fails the build.
  SHARE_MAX_DEFINITION_BYTES: Sanity check on the serialised cloned table definition, and
    since SPEC-161 that is ALL it is — it is no longer a bound on the Step Functions state,
    because the definition travels by pointer. What sizes it now is Athena's query-string
    quota: the definition is rendered into one CREATE EXTERNAL TABLE, and Athena refuses a
    query string over 262,144 bytes (a hard quota). The rendered DDL is of the same order as
    the serialised JSON — the backticks and quotes replace the JSON keys — so a 128 KiB
    ceiling on the object leaves roughly a factor of two before the statement itself is
    refused. Rejected in inspect-source as a whole-request terminal, before the write and
    before any recipient runs, so nobody gets a definition that cannot be rendered.
"""

SHARE_MAX_OBJECTS = 20_000
SHARE_MAX_TOTAL_BYTES = 1024**4

SHARE_MAX_TRANSFER_ITEMS = 20_000

RECIPIENT_KINDS = frozenset({"user", "space"})

SHARE_MAX_RECIPIENTS = 50

SHARE_MAX_DEFINITION_BYTES = 128 * 1024
