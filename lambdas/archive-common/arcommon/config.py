"""Domain configuration for the archive control plane.

The shared core — region, user pool identifiers, the two space buckets — lives in
``cpcommon.config``. Only archive's own constants live here, and **not one of them reads the
environment at import**: this module cannot fail at import, which matters because a shared
layer's import-time failure surfaces at COLD START, where no test and no deploy can see it
.

``archive_bucket()`` is the one env-derived value, and it is a FUNCTION for exactly that reason.
It does **not** belong in ``cpcommon.config._REQUIRED_VARS``: that set is a fleet-wide contract
every plane's Lambda environment must satisfy, so putting a variable only THIS plane sets into it
breaks every other plane. A guard caught exactly that mistake while this change was being
written — though only on table-builder, despite a name that suggested the fleet, and it was later
retired. ``test_fleet_environment.py`` now holds the contract across every deployed function,
refusing any required name a function's own code can reach and its Terraform does not set.

Every cap below is a whole-request terminal in validate-authorize, raised before any AWS call
that costs anything, so a refused archive leaves nothing behind.

Attributes:
  ARCHIVE_STORAGE_CLASS: **The single definition of the storage class every archived object is
    written at, and the choice that determines the shape of the whole arc.** No verb hard-codes
    the literal.

    ``GLACIER`` is S3 Glacier Flexible Retrieval. It is **not readable**: a ``CopyObject`` whose
    source is in this class fails ``InvalidObjectState``, so a restore is not a copy — it is
    ``RestoreObject``, a 3-5 hour wait and *then* a copy, which is why the restore grows a poll loop
    no other plane in this repo has.

    **The two alternatives were considered and rejected.** ``GLACIER_IR`` is readable in real
    time, which would delete the restore machinery entirely — and that is exactly why it is
    wrong: it is the most expensive Glacier class, and an archive a user can still read on
    demand is not an archive, it is data moved to a cheaper bucket. ``DEEP_ARCHIVE`` costs
    roughly 4x less again, but restores in **12-48 hours** and bills a **180-day** minimum, which
    turns an ordinary "I need that back" into a two-day wait.

    **The 90-day minimum storage duration is a property of this class, not a defect, and the
    user has to be told.** An object archived on Monday and restored the following week is still
    billed for 90 days. The confirm dialog says so in user-facing wording; it is recorded
    here because this constant is where someone would come looking.
  GLACIER_CLASSES: The three archival classes, for the guard that keeps
    ``ARCHIVE_STORAGE_CLASS`` one of them. The restore path is **unconditional** whatever this
    is set to — a class that needs no restore still tolerates one being requested, and making
    the machinery conditional on a constant is how a config change silently deletes a code path.
  ARCHIVE_MODES: The two things this ONE plane does. A single machine branches on ``mode``
    rather than a sixth module being stood up (the create/refresh branch is the
    precedent): the two verbs share the bucket, the execution role, the key layout and the
    receipt, and a restore is meaningless without the archive that produced it.
  SPACE_KINDS: The two source-space kinds. The kind decides which bucket the source resolves in
    and which authorization question is asked, so it is validated rather than inferred. **It is
    also the leading segment of every archive key**, which is not cosmetic — see
    ``arcommon.paths``.
  ARCHIVE_MAX_ITEMS: Cap on the NUMBER of selected items — the files and folders the user picked,
    **not** the objects they expand to. What sizes it is the per-item work that follows: the
    containment and reserved-root checks here, and and one ``ListObjectsV2`` walk per
    folder plus a ``HeadObject`` per file. It is emphatically NOT a bound on the transfer; the
    object and byte caps over the *expanded* selection belong to the expansion.

    The value matches file-send's ``SEND_MAX_ITEMS`` because the per-item work is the same shape
    and the same browser pages the selection at 25 — eight full pages of selection. A different
    number here would have to be justified by a difference that does not exist yet.
  ARCHIVE_MAX_ITEM_BYTES: Cap on the SERIALISED selection, which is the term that actually
    rides, and it bounds a **chain** rather than one limit. The browser's SQS body carries the
    selection; the EventBridge Pipe wraps that body into a record as an ESCAPED JSON STRING and
    hands it to ``StartExecution`` as the execution input; Step Functions caps that input at
    256 KB exactly as it caps a state. The escaping is not a rounding error — every ``"`` the
    selection already spent two bytes on costs four in the record — so a quote-heavy selection
    reaches the record at **twice** its measured size.

    A count cap cannot stand in for this: S3 keys are arbitrary UTF-8, and JSON escaping expands
    a control character to six bytes, so 200 items at a 1024-byte key is 216 KB of ASCII or
    1.2 MB of ``\\x01``.

    **It came down from 96 KiB, and the reason is the fourth link rather than the three above.**
    A failure state is the Pipe's record PLUS an error whose ``Cause`` the service permits 32,768
    CHARACTERS of — which is a length on an execution-history event, not a byte quota on a state,
    so a Cause sitting inside a JSON string on the state costs twice that. Reserved honestly, a
    quote-heavy selection at the old cap reached a ``RecordFailure`` of 263,223 bytes against a
    262,144-byte limit: on a ``Pass`` with no ``Catch``, so the user whose request failed was told
    nothing at all. The fleet guard computes every link for every piped route against one
    constant, and ``lambdas/api/apicommon/enqueue.py`` derives the message cap this sits under.
  ARCHIVE_MAX_OBJECTS: Cap on the EXPANDED object count — what the selection actually resolves
    to, which ``ARCHIVE_MAX_ITEMS`` says nothing about because one selected folder can hold any
    number of objects. What sizes it is the copy plan held in MEMORY by inspect-source, which
    builds the whole list, serialises it and encodes that at once;
    ``test_the_worst_case_archive_copy_plan_fits_in_the_verbs_memory`` computes it against
    the memory ``locals.tf`` configures and READS THAT NUMBER BACK, so LOWERING that memory
    fails the build rather than the invocation. It does not bound a raise of this cap: the
    worst-case plan sits 5x inside the configured memory, and what refuses a raise is the
    restore arm's timeout guards, from about 24,000 objects up.
  ARCHIVE_MAX_BYTES: Cap on the expanded byte total, and it bounds the RUN rather than any one
    verb: the Distributed Map's copy is the long pole, and the machine's own ``TimeoutSeconds``
    is the thing it has to fit inside. The denominator is a **makespan**, not an aggregate
    bandwidth — ``copy_batch`` hands one WHOLE object to one worker and ``copy_one``'s multipart
    loop is serial, so the rate is ``MAP_MAX_CONCURRENCY x CONSERVATIVE_STREAM_BYTES_PER_SECOND``
    and not the far larger number multiplying every constant together suggests.
    ``test_the_whole_archive_run_fits_the_machines_ceiling`` adds every term of the run —
    the copy, the per-child overhead, the serial verbs and the deletion pass — and reads the
    ceiling out of ``locals.tf``.

    **Unlike file-send's there is no product cap beside it**, and the absence is structural: an
    archive has one destination, so a manifest item is one object and the source cap IS the
    transfer cap.
  ARCHIVE_MAX_OBJECT_BYTES: Cap on ONE object, and the spec does not name it because the
    arithmetic above does. A batch is one round of the worker pool and **one object is one
    worker**, so a single object's copy time is bounded by nothing else: S3 accepts objects up to
    5 TiB, which at the conservative rate is ~220,000s — 240x the batch verb's own timeout and
    5x the whole machine's ceiling. Without this the makespan model certifies the DISTRIBUTED
    case only, which is the recorded finding inherited rather than rediscovered.

    10 GiB matches the two shipped planes, and at the conservative rate it is 429s inside
    ``COPY_TIMEOUT_SECONDS``' 900.
  RESTORE_HEAD_CONCURRENCY: Bounded worker pool for the destination guard's existence checks.

    **The binding constraint is botocore's CONNECTION POOL, not the thread count**, and the
    first version of this constant had it wrong. A ``HeadObject`` is a small serial round trip,
    so the obvious model is "workers x timeout / latency" and the obvious value is as many
    workers as the memory affords — but ``boto3.client("s3")`` takes botocore's default
    ``max_pool_connections`` of **10**, and threads past that do not get a connection each. They
    contend, and urllib3 opens and discards sockets rather than reusing them, so a pool of 32
    buys throughput the client cannot deliver while the arithmetic says otherwise. 8 sits inside
    that ceiling with headroom, which is also — not by coincidence — why ``COPY_CONCURRENCY`` is
    8.

    The verb's TIMEOUT is then the free variable, and it is where the real work is paid for: at
    ``ARCHIVE_MAX_OBJECTS`` (20,000) heads, 8 at a time, at a pessimistic 100 ms each, the worst
    case is ~250s, so ``locals.tf`` gives the guard 600s.
    ``test_the_guard_can_head_every_destination_inside_its_timeout`` computes exactly that and
    READS THE TIMEOUT BACK from the Terraform, so raising the object cap or lowering the timeout
    fails the build rather than the invocation — and
    ``test_the_guards_pool_fits_inside_the_clients_connection_pool`` pins the ceiling that sizes
    this number, because that is the term a later "just raise the concurrency" would skip.
  RESTORE_STORAGE_CLASS: The class the copy-back writes at, and **it is stated rather than
    omitted**. ``cpcommon.transfer`` treats an empty storage class as "do not pass the argument",
    which is S3's own default and is what table-share and file-send rely on — but here the
    default is not what makes the restore work, the explicit class is. **The copy IS the thing
    that changes the storage class.** The temporary object a retrieval materialises expires;
    without a copy at ``STANDARD`` the object is still ``GLACIER`` and becomes unreadable again,
    so a restore that relied on a default nobody stated would look identical for a few days and
    then have delivered nothing.
  RESTORE_TIER: The Glacier retrieval tier every ``RestoreObject`` asks for, and the constant
    that decides how long a user waits. ``Standard`` restores in **3-5 hours**, which is what
    ``RESTORE_MAX_POLLS`` is sized against.

    **The two alternatives are rejected rather than unconsidered.** ``Expedited`` returns in
    1-5 minutes but is per-request, costs several times as much, and is **subject to capacity**
    — without provisioned capacity units it can return ``GlacierExpeditedRetrievalNotAvailable``,
    which turns a restore into a failure for a reason the user cannot act on. Buying capacity
    units is a standing monthly charge this portal does not make. ``Bulk`` is the cheapest and
    takes **5-12 hours**, which doubles the worst-case wait for somebody sitting in front of a
    browser and would push the machine's ceiling past half a day.
  RESTORE_AVAILABILITY_DAYS: How long the temporary readable copy S3 materialises stays
    available. **It is measured against the COPY-BACK, not against the retrieval**, and it is
    generous on purpose: the copy reads that temporary object, so the object has to outlive the
    copy that reads it.

    **The failure mode if it does not is the one worth stating**, because it does not look like
    a configuration error. The copy-back begins succeeding, and then partway through — as the
    earliest-restored objects expire back to unreadable — items start failing
    ``InvalidObjectState``. It presents as a partial restore with no obvious cause, on a run
    that has already worked for hours, and the objects it fails on are the ones it retrieved
    FIRST. Seven days against a copy-back whose worst case is under two hours is not caution
    about the copy; it is caution about a retrieval that finishes hours before the machine
    notices, since the window starts when each object becomes available and not when the copy
    starts.
  RESTORE_POLL_SECONDS: The ``Wait`` between poll iterations, mirrored into ``locals.tf``
    because ASL cannot import Python — a test asserts the two agree, the same way the transfer
    Map's batch numbers are held together. Five minutes against a 3-5 hour retrieval is ~1% of
    the wait spent asking, which is the ratio worth having: shorter buys nothing a user can
    perceive and costs an invocation every time.
  RESTORE_MAX_POLLS: How many iterations before the loop gives up with ``restore_timed_out``.
    ``RESTORE_POLL_SECONDS x RESTORE_MAX_POLLS`` is the retrieval BUDGET — seven hours — and
    **the headroom over the tier's own five is the whole point of the number.** AWS documents
    3-5 hours as typical rather than contractual, and the cost of being wrong is asymmetric in a
    way most timeouts are not: giving up on a retrieval that was going to finish does not merely
    fail a run, it makes the user pay for a SECOND billed retrieval to try again. Waiting two
    more hours costs a Lambda invocation every five minutes.
    ``test_the_retrieval_budget_clears_the_tiers_own_worst_case`` computes it, and
    ``test_the_whole_restore_fits_the_machines_ceiling`` adds it to the copy-back — so raising it
    without raising the machine's ceiling fails the build.
  RESTORE_POLL_PAGE: How many objects the poll advances its recorded progress by. **The poll
    samples rather than re-heading the archive on every iteration**: it starts at the index the
    last iteration reached, and a page whose every object reports complete moves that index on.
    An archive of 200,000 objects would otherwise issue 200,000 heads every five minutes for
    hours.

    One invocation advances as MANY pages as it can before it meets an incomplete object, which
    is the half a strict one-page-per-iteration reading gets wrong: all objects were requested
    at once at one tier, so they complete together, and sweeping 20,000 objects a page at a time
    would add twenty ``Wait``s — over an hour and a half — after the retrieval had already
    finished. The page is the granularity progress is RECORDED at, not a bound on one
    invocation's work; the invocation's bound is ``ARCHIVE_MAX_OBJECTS`` heads at
    ``RESTORE_HEAD_CONCURRENCY``, which is the guard's own arithmetic and the guard's own 600s.
  RESTORE_CONFLICT_SAMPLE: How many colliding destinations the refusal NAMES. It is a
    presentation bound, not a work bound — the guard short-circuits, so it has usually seen only
    a handful — and it exists because the message must fit in a notification a person reads:
    at five, the sentence stays one or two lines whatever the paths are. **The refusal says
    plainly that there may be more**, because a sample implying it is exhaustive would send the
    user round the clear-and-retry loop once per hidden collision.
  RESERVED_SOURCE_ROOTS: Root-level folders that may not be archived, **anchored at the space
    root**, each with its own reason. This is archive's **OWN list** — it is not
    ``protectedFolders.ts`` reused and not a union of the browser's three lists, whose own header
    comment warns that unioning them is the wrong repair. The question here is new and no
    existing list answers it: *may this be moved out of the space and DELETED?*

      ``archive/``               the receipts this plane writes; archiving an archive.
      ``athenaresults/``         the role policy denies ``DeleteObject`` beneath it, so the
                                 source deletion would fail halfway through.
      ``user_settings/``         portal-managed state — the notification inbox and the
                                 connections cache. Archiving it breaks the app for the user.
      ``_data-quality-reports/`` the reports the data-quality notifications LINK to; a dead link
                                 is worse than a missing report.
      ``shared_tables/``         the table-share pipeline owns the layout, and a Glue table
                                 pointing at a deleted location returns nothing rather than
                                 failing.
  PROTECTED_MARKER_BASENAME: The prefix marker both bucket policies deny ``DeleteObject`` on, at
    ANY depth (``*`` matches ``/``). A selection containing one is refused for the WHOLE request
    rather than skipped: archiving deletes the source, so an un-deletable object would fail the
    run after some of the data had already moved.
  RESERVED_SOURCE_ROOTS: The space's own portal-managed folders, never an archive source. The
    three that are about to move are spelled through ``cpcommon.app_managed``; the browser reads
    this tuple as text and resolves those names against that module.
  RECEIPT_NAME: The receipt object's basename. **A plain text file the user downloads and reads
    themselves** — deliberately not rendered in the browser, which leaves the project's
    no-preview rule untouched.
"""

from cpcommon.app_managed import (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    SHARED_TABLES_FOLDER,
    SYSTEM_SETTINGS_FOLDER,
)
from cpcommon.config import require as _require_env

ARCHIVE_STORAGE_CLASS = "GLACIER"

GLACIER_CLASSES = frozenset({"GLACIER", "GLACIER_IR", "DEEP_ARCHIVE"})

ARCHIVE_MODES = frozenset({"archive", "restore"})

SPACE_KINDS = frozenset({"personal", "shared"})

ARCHIVE_MAX_ITEMS = 200

ARCHIVE_MAX_ITEM_BYTES = 89 * 1024

ARCHIVE_MAX_OBJECTS = 20_000

ARCHIVE_MAX_BYTES = 3 * 1024**4

ARCHIVE_MAX_OBJECT_BYTES = 10 * 1024**3

RESTORE_HEAD_CONCURRENCY = 8

RESTORE_CONFLICT_SAMPLE = 5

RESTORE_STORAGE_CLASS = "STANDARD"

RESTORE_TIER = "Standard"

RESTORE_AVAILABILITY_DAYS = 7

RESTORE_POLL_SECONDS = 300

RESTORE_MAX_POLLS = 84

RESTORE_POLL_PAGE = 1000

RESERVED_SOURCE_ROOTS = (
    RECEIPT_FOLDER,
    ATHENA_RESULTS_FOLDER,
    "user_settings",
    "_data-quality-reports",
    SHARED_TABLES_FOLDER,
    SYSTEM_SETTINGS_FOLDER,
)

PROTECTED_MARKER_BASENAME = "DO_NOT_DELETE.txt"

RECEIPT_NAME = "receipt.txt"


def archive_bucket() -> str:
    """Returns the archive bucket's name, read from the environment on every call.

    Bucket 5 — the one bucket the BROWSER has no relationship with at all: no CORS, absent
    from the CSP ``connect-src``, and the portal role holds zero statements naming it. Only
    this plane's execution role can reach it, and the only route to archived bytes is a restore
    request through this plane.

    Args:
      None.

    Returns:
      The bucket name.

    Raises:
      RuntimeError: If ``ARCHIVE_BUCKET`` is unset or empty — raised HERE, at first use, rather
        than at import, so a verb that never touches the archive bucket is unaffected.
    """
    return _require_env("ARCHIVE_BUCKET")
