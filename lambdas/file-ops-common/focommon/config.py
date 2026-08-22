"""Domain configuration for the file-operations control plane.

The shared core — region, user pool identifiers, buckets, the notifications queue — lives in
``cpcommon.config``. Only file-ops' own constants live here, and **none of them reads the
environment**: this module cannot fail at import, which matters because a shared layer's
import-time failure surfaces at COLD START, where no test and no deploy can see it.

Every cap below is a whole-request terminal — the two request-shape ones in validate-authorize,
raised before any AWS call that costs anything, and the three expansion ones inside the walk that
accumulates the list they bound, because a cap checked afterwards is one the verb has already paid
for. **None of them is written as a literal a reader has to trust** — ``test_config_focommon``
computes each against the budget that sizes it and names the schedulable unit it measures.

The protected-folder names are duplicated from the browser's ``protectedFolders.ts`` and
``writeLockedPrefix.ts``, because Python and TypeScript cannot share a list. A test reads both
files and holds the memberships together; that is the only thing keeping the two runtimes'
answers the same.

Attributes:
  OPERATIONS: The three operations one plane serves. Validated rather than inferred, because the
    operation decides which side is authorized and which protected-folder rules apply.
  SPACE_KINDS: The two space kinds. The kind decides which bucket a space resolves in and which
    authorization question is asked.
  ON_CONFLICT: The two answers a request may carry for a destination collision. Required for
    copy and move, rejected for delete.
  FILE_OPS_MAX_ITEMS: Cap on the NUMBER of selected items — the files and folders the user picked,
    **not** the objects they expand to. What sizes it is the per-item work in validate-authorize:
    two containment checks, the derived-destination guards and the protected-location rules, all
    of them string work with no network call. It is emphatically NOT a bound on the eventual
    transfer, and the caps that bound *that* belong to the expansion.
  FILE_OPS_MAX_SELECTION_BYTES: Cap on the SERIALISED selection, which is the term that actually
    rides. A count cap cannot stand in for it: S3 keys are arbitrary UTF-8 and JSON escaping
    expands a quote to two bytes and a control character to six, so the same item count can be
    ASCII-small and escape-huge. What sizes it is a CHAIN — the browser's SQS body carries the
    selection, the Pipe wraps that body into a record as an ESCAPED JSON STRING, and Step
    Functions caps the resulting execution input at 256 KB. The escaping is not a rounding error.
    And this plane's state carries a term file-send's does not: one outcome record per selected
    item rides beside the request from the first verb onward.
  FILE_OPS_MAX_OBJECTS: Cap on the EXPANDED object count — what the selection actually resolves
    to, which ``FILE_OPS_MAX_ITEMS`` says nothing about because one selected folder can hold any
    number of objects. It is the MINIMUM of two budgets held by two different verbs, and naming
    only one is how a cap comes to certify something it never checked: the plan held in MEMORY by
    inspect-source, and the destination guard's HEAD SWEEP against check-destinations' timeout at
    ``FILE_OPS_HEAD_CONCURRENCY``. If memory permitted 200,000 objects the guard could not head
    them at any concurrency inside Lambda's 900-second ceiling. ``test_config_focommon`` computes
    both, reads the memory and the timeout back out of ``locals.tf``, and asserts which one binds.
  FILE_OPS_MAX_TOTAL_BYTES: Cap on the bytes one selection holds, bounding the RUN rather than any
    one verb: the copy is the long pole and the machine's ``TimeoutSeconds`` is what it has to fit
    inside. The denominator is a MAKESPAN, not an aggregate bandwidth — one object is handed whole
    to one worker — so the rate is ``MAP_MAX_CONCURRENCY x CONSERVATIVE_STREAM_BYTES_PER_SECOND``.

    **DERIVED, no longer provisional — and it is the number that MOVED when the joint budget was
    finally computed.** At 3 TiB the whole run came to ~12,700s against a 10,800s ceiling: the
    copy's makespan, two guard sweeps, every serial verb's timeout and the lock give-up, which the
    earlier version of this budget omitted entirely. Raising the ceiling instead would have raised
    ``STALE_LOCK_SECONDS`` with it, and a longer stale window on a SHARED space blocks everyone who
    works in it rather than only the person whose run wedged. So the cap came down to 2 TiB.
  FILE_OPS_MAX_OBJECT_BYTES: Cap on ONE object, and the cap without which the makespan above
    certifies the distributed case only. A batch is one round of the worker pool and ONE OBJECT IS
    ONE WORKER, so a single object's copy time is bounded by nothing else: S3 accepts objects up to
    5 TiB, which at the conservative rate is ~220,000s against a 900-second batch timeout.
  FILE_OPS_HEAD_CONCURRENCY: Bounded worker pool for the destination guard's existence checks.
    **The binding constraint is botocore's CONNECTION POOL, not the thread count.** A ``HeadObject``
    is a small serial round trip, so the obvious model is "workers x timeout / latency" and the
    obvious value is as many workers as the memory affords — but ``boto3.client("s3")`` takes
    botocore's default ``max_pool_connections`` of 10, and threads past that do not each get a
    connection: they contend, and urllib3 opens and discards sockets rather than reusing them. So a
    wider pool buys throughput the client cannot deliver while every bound computed from it reads
    as satisfied. This plane creates no client of its own — it uses ``cpcommon.clients.s3()``,
    which passes no ``Config`` — so the default IS the ceiling.
  FILE_OPS_ITEM_ROUND_TRIP_SECONDS: The pessimistic serial round trip charged per ITEM when the
    listing timeout is sized. **Per item, not per page**, which is the term the obvious model drops:
    a ``file`` item costs its own serial ``HeadObject``, so 200 files is 200 round trips where
    20,000 objects in one folder is 20 pages.
  FILE_OPS_CONFLICT_SAMPLE: How many colliding destination paths a conflicted item NAMES. A
    presentation bound, and a bound on the STATE: every conflicted item carries its sample from the
    guard to the notification, and Step Functions caps a state at 256 KB. Measured at the selection
    byte cap with every item conflicted, one full-length path per item is all that fits — so the
    paths are shortened for display (below) and three of them fit with room over.
  FILE_OPS_SAMPLE_PATH_CHARS: Length a sampled path is shortened to for display, from the middle,
    so the basename — the part that identifies the file — survives. An ordinary path is untouched;
    what this bounds is the pathological key the caps admit and a notification could never render.
    The refusal says plainly that there may be more, so a sample is never read as exhaustive.
  PLAN_PREFIX: Key prefix for this plane's copy plans, under the admin bucket. Mirrored in the
    module's ``locals.tf`` (the IAM grant) and in the admin bucket's lifecycle rule; a test holds
    all three equal. It cannot match ``LOCK_PREFIX`` — ``locks/file-ops`` does not begin with
    ``file-ops`` — which is what keeps an expiry rule off the lock objects.
  MAX_TARGET_NAME: Length cap on a per-item destination name. S3 allows 1024 bytes for a whole
    key, and a single path segment approaching that leaves no room for the prefix it sits under.
  ATHENA_RESULTS_FOLDER: The space's own Athena results folder. Refused as a destination and as a
    delete or move source; copying *out* of it stays allowed, which is why this is named here
    rather than reused from a list.
  USER_SETTINGS_FOLDER: The space's own portal-managed settings folder. Refused as a source for
    EVERY operation, by this plane's own rule rather than by list membership — it is hidden from
    the browser and locked out of the picker, but deliberately not undeletable, so no existing
    list reaches it. Hiding is not enforcement, and this plane accepts a hand-crafted envelope.
  ARCHIVE_FOLDER: The archive receipts folder. Refused as a destination, and as a delete or move
    source, under the bucket asymmetry ``writeLockedPrefix.ts`` mirrors from IAM.
  MARKER_BASENAME: The undeletable marker both bucket policies deny by name at any depth.
  PICKER_LOCKED_FOLDERS: Never a destination. Root-anchored in whichever bucket.
  UNDELETABLE_ROOT_FOLDERS: Never a delete or move SOURCE, at a space root.
  LOCK_PREFIX: Key prefix for this plane's lock objects, under the admin bucket.
  LOCK_WAIT_SECONDS: The ASL ``Wait`` between re-acquire attempts. Mirrored in the module's
    ``locals.tf`` because ASL cannot import Python; a test holds the two equal.
  LOCK_MAX_ATTEMPTS: How many times a waiter re-acquires before giving up. **Python only.** The
    interval is an ASL field and must be mirrored; the cap is the verb's own decision, and a
    second home for it in Terraform is a number that can drift.
  MACHINE_TIMEOUT_SECONDS: The file-ops state machine's ``TimeoutSeconds``, mirrored here because
    a steal threshold is only meaningful against a bounded execution. **No longer provisional**:
    the transfer and the deletion exist, so ``test_config_focommon`` computes the joint budget
    against it rather than borrowing a number from a neighbouring plane. It did not move —
    ``FILE_OPS_MAX_TOTAL_BYTES`` did, for the reason recorded there.
  STALE_LOCK_SECONDS: Age past which a held lock is stolen — the machine ceiling plus a margin
    for the delay between an execution's last state and its timeout being observed. Strictly
    greater than the ceiling, asserted by a test: a threshold below it steals a RUNNING
    execution's lock.
"""

OPERATIONS = frozenset({"copy", "move", "delete"})

SPACE_KINDS = frozenset({"personal", "shared"})

ON_CONFLICT = frozenset({"refuse", "overwrite"})

FILE_OPS_MAX_ITEMS = 200

FILE_OPS_MAX_SELECTION_BYTES = 64 * 1024

MAX_TARGET_NAME = 255

FILE_OPS_MAX_OBJECTS = 20_000

FILE_OPS_MAX_TOTAL_BYTES = 2 * 1024**4

FILE_OPS_MAX_OBJECT_BYTES = 10 * 1024**3

FILE_OPS_HEAD_CONCURRENCY = 8

FILE_OPS_ITEM_ROUND_TRIP_SECONDS = 0.1

FILE_OPS_CONFLICT_SAMPLE = 3

FILE_OPS_SAMPLE_PATH_CHARS = 120

PLAN_PREFIX = "file-ops"

ATHENA_RESULTS_FOLDER = "athenaresults"

USER_SETTINGS_FOLDER = "user_settings"

ARCHIVE_FOLDER = "archive"

MARKER_BASENAME = "DO_NOT_DELETE.txt"

PICKER_LOCKED_FOLDERS = (
    "athenaresults",
    "user_settings",
    "_data-quality-reports",
    "_directory",
    "_config",
    "shared_tables",
    "archive",
)

UNDELETABLE_ROOT_FOLDERS = ("athenaresults", "saved_queries", "archive")

LOCK_PREFIX = "locks/file-ops"

LOCK_WAIT_SECONDS = 30

LOCK_MAX_ATTEMPTS = 20

MACHINE_TIMEOUT_SECONDS = 10_800

STALE_LOCK_SECONDS = MACHINE_TIMEOUT_SECONDS + 900
