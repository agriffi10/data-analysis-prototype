"""Domain configuration for the table-share control plane.

The shared core — region, user pool identifiers, buckets, workgroup, notifications queue, the
catalog identifier rule — lives in ``cpcommon.config``. Only table-share's own constants live
here. The sizing evidence behind the four caps is in ``docs/lambda-rationale.md``.

Every cap below is a whole-request terminal in inspect-source, raised before either artifact
is written, so a refused share leaves nothing behind and no recipient runs.

Attributes:
  SHARE_MAX_OBJECTS: Object-count cap. **What sizes it is inspect-source's listing time.**
    ``list_data_objects`` pages at 1000 keys, so 20,000 objects is 20 ListObjectsV2 round
    trips — one to two seconds of a 120-second budget — and the copy plan it writes is ~3.4 MB
    at ordinary Hive keys, ~21 MB at S3's worst-case 1024-byte ones, which is what the verb's
    1024 MB is sized for (locals.tf). It is no longer sized by the copy: SPEC-160 made that a
    Distributed Map over batches, so no single invocation carries a recipient's whole table.
  SHARE_MAX_TOTAL_BYTES: Cap on the SOURCE table's size, and only that. It bounds what
    inspect-source lists and what the copy plan describes — **it says nothing about how much
    the Map Run moves**, because the manifest carries one item per (recipient, object) pair and
    every one of them is a full copy. ``SHARE_MAX_TRANSFER_BYTES`` below is the cap on the
    transfer; this one keeps a single source from being unbounded on its own.
  SHARE_MAX_TRANSFER_BYTES: Cap on ``recipients x total_bytes`` — the bytes the Distributed Map
    actually copies, and the byte-axis twin of ``SHARE_MAX_TRANSFER_ITEMS``. **What sizes it is
    the state machine's ``TimeoutSeconds``.** The fan-out reaches 160 concurrent server-side
    copies (``MAP_MAX_CONCURRENCY`` children x ``COPY_CONCURRENCY`` workers), so at
    ``CONSERVATIVE_STREAM_BYTES_PER_SECOND`` 16 TiB is about 4,400 seconds against a 10,800
    second ceiling.

    It exists because the source cap could not stand in for it: 50 recipients x a 1 TiB source
    is **50 TiB**, which needs 3.8 hours even at the conservative rate and 19 at the pessimistic
    one — so the timeout would kill a share every cap had accepted, mid-copy, leaving recipients
    holding partial data. That is the same omission ``SHARE_MAX_TRANSFER_ITEMS`` exists to close
    one axis over, and it was missed here for two review rounds because the timeout's arithmetic
    was written against the un-multiplied number.
  SHARE_MAX_OBJECT_BYTES: Cap on ONE object, which the total-size cap does not imply and which
    raising that cap is what made necessary. **What sizes it is the copy verb's timeout, via
    the BATCH — not via the object.** That distinction is the whole of this constant and an
    earlier version of it got it wrong: ``ItemBatcher`` batches by **count**, never by bytes,
    so the unit that has to finish inside ``copy-objects``' 900 seconds is
    ``MAX_ITEMS_PER_BATCH`` objects, not one. While ``SHARE_MAX_TOTAL_BYTES`` was 20 GiB the
    bound was implicit — a batch could not exceed the whole table — and raising the total to
    1 TiB removed it without anything replacing it. At 10 GiB with a 10-item batch the worst
    batch is 100 GiB, ~537 seconds at a conservative 25 MB/s per stream across
    ``COPY_CONCURRENCY`` workers. ``test_a_worst_case_batch_copies_inside_the_verb_timeout``
    computes that from the constants, so raising either without the other fails the build.
    It also stays above S3's 5 GiB single-copy limit, keeping the multipart part-copy path
    reachable rather than silently dead.
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
    query string over 262,144 bytes (a hard quota, not adjustable).

    **The rendered DDL can be TWICE the serialised JSON, and the doubling is not spread
    evenly.** ``ddl.literal`` backslash-escapes, so a ``'`` costs one byte in the JSON this
    cap measures and two in the statement. Where that ``'`` sits decides the ratio: a column
    pays ~40 bytes of JSON overhead per comment, so apostrophe-heavy COMMENTS render at about
    1.7x, while a table property or a SerDe parameter pays ~9 and renders at nearly the full
    2x. Measured at a 128 KiB cap the worst case reached **99.98%** of the quota — sixty-two
    bytes of margin, which is a coin flip rather than a check — so the cap is 64 KiB, where
    the same worst case lands near half. ``test_an_at_cap_definition_still_renders_under_
    athenas_query_string_quota`` builds the property-shaped worst case, not the comment-shaped
    one. Rejected in inspect-source as a whole-request terminal, before the write and before
    any recipient runs, so nobody gets a definition that cannot be rendered.
"""

SHARE_MAX_OBJECTS = 20_000
SHARE_MAX_TOTAL_BYTES = 1024**4
SHARE_MAX_OBJECT_BYTES = 10 * 1024**3

SHARE_MAX_TRANSFER_ITEMS = 20_000
SHARE_MAX_TRANSFER_BYTES = 16 * 1024**4

RECIPIENT_KINDS = frozenset({"user", "space"})

SHARE_MAX_RECIPIENTS = 50

SHARE_MAX_DEFINITION_BYTES = 64 * 1024
