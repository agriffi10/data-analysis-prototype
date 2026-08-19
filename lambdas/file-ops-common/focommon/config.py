"""Domain configuration for the file-operations control plane.

The shared core — region, user pool identifiers, buckets, the notifications queue — lives in
``cpcommon.config``. Only file-ops' own constants live here, and **none of them reads the
environment**: this module cannot fail at import, which matters because a shared layer's
import-time failure surfaces at COLD START, where no test and no deploy can see it.

Every cap below is a whole-request terminal in validate-authorize, raised before any AWS call that
costs anything, so a refused operation leaves nothing behind. **Neither is written as a literal a
reader has to trust** — ``test_config_focommon`` computes both against the budget that sizes them
and names the unit it measures.

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
    a steal threshold is only meaningful against a bounded execution. PROVISIONAL: this machine
    does no work yet, so the number is taken from the two transfer-bearing planes that do, and
    the spec that adds the transfer re-derives it together with the two constants below.
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
