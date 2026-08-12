"""Domain configuration for the archive control plane.

The shared core — region, user pool identifiers, the two space buckets — lives in
``cpcommon.config``. Only archive's own constants live here, and **not one of them reads the
environment at import**: this module cannot fail at import, which matters because a shared
layer's import-time failure surfaces at COLD START, where no test and no deploy can see it
(PR #196).

``archive_bucket()`` is the one env-derived value, and it is a FUNCTION for exactly that reason.
It does **not** belong in ``cpcommon.config._REQUIRED_VARS``: that set is a fleet-wide contract
every plane's Lambda environment must satisfy — asserted per plane by
``test_the_common_environment_satisfies_every_import_time_require`` — so putting a variable only
THIS plane sets into it fails every other plane's guard. That test caught the mistake while the
change was being written, which is what it is for.

Every cap below is a whole-request terminal in validate-authorize, raised before any AWS call
that costs anything, so a refused archive leaves nothing behind.

Attributes:
  ARCHIVE_STORAGE_CLASS: **The single definition of the storage class every archived object is
    written at, and the choice that determines the shape of the whole arc.** No verb hard-codes
    the literal.

    ``GLACIER`` is S3 Glacier Flexible Retrieval. It is **not readable**: a ``CopyObject`` whose
    source is in this class fails ``InvalidObjectState``, so a restore is not a copy — it is
    ``RestoreObject``, a 3-5 hour wait and *then* a copy, which is why SPEC-171 grows a poll loop
    no other plane in this repo has.

    **The two alternatives were considered and rejected.** ``GLACIER_IR`` is readable in real
    time, which would delete the restore machinery entirely — and that is exactly why it is
    wrong: it is the most expensive Glacier class, and an archive a user can still read on
    demand is not an archive, it is data moved to a cheaper bucket. ``DEEP_ARCHIVE`` costs
    roughly 4x less again, but restores in **12-48 hours** and bills a **180-day** minimum, which
    turns an ordinary "I need that back" into a two-day wait.

    **The 90-day minimum storage duration is a property of this class, not a defect, and the
    user has to be told.** An object archived on Monday and restored the following week is still
    billed for 90 days. SPEC-172's confirm dialog says so in user-facing wording; it is recorded
    here because this constant is where someone would come looking.
  GLACIER_CLASSES: The three archival classes, for the guard that keeps
    ``ARCHIVE_STORAGE_CLASS`` one of them. The restore path is **unconditional** whatever this
    is set to — a class that needs no restore still tolerates one being requested, and making
    the machinery conditional on a constant is how a config change silently deletes a code path.
  ARCHIVE_MODES: The two things this ONE plane does. A single machine branches on ``mode``
    rather than a sixth module being stood up (SPEC-143's create/refresh branch is the
    precedent): the two verbs share the bucket, the execution role, the key layout and the
    receipt, and a restore is meaningless without the archive that produced it.
  SPACE_KINDS: The two source-space kinds. The kind decides which bucket the source resolves in
    and which authorization question is asked, so it is validated rather than inferred. **It is
    also the leading segment of every archive key**, which is not cosmetic — see
    ``arcommon.paths``.
  ARCHIVE_MAX_ITEMS: Cap on the NUMBER of selected items — the files and folders the user picked,
    **not** the objects they expand to. What sizes it is the per-item work that follows: the
    containment and reserved-root checks here, and in SPEC-169 one ``ListObjectsV2`` walk per
    folder plus a ``HeadObject`` per file. It is emphatically NOT a bound on the transfer; the
    object and byte caps over the *expanded* selection are SPEC-169's.

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
    1.2 MB of ``\\x01``. ``test_config_arcommon`` computes all three links of the chain, so
    changing one without the others fails the build.
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
  ARCHIVE_FOLDER: The receipt folder inside the space's own bucket, and the ``archive/`` segment
    of the archive-bucket key. One constant, because they are the same folder name by design —
    a user who sees ``archive/{uuid}/`` in their own space is looking at the same id the archived
    objects sit under.
  RECEIPT_NAME: The receipt object's basename. **A plain text file the user downloads and reads
    themselves** — deliberately not rendered in the browser, which leaves the project's
    no-preview rule untouched.
"""

from cpcommon.config import require as _require_env

ARCHIVE_STORAGE_CLASS = "GLACIER"

GLACIER_CLASSES = frozenset({"GLACIER", "GLACIER_IR", "DEEP_ARCHIVE"})

ARCHIVE_MODES = frozenset({"archive", "restore"})

SPACE_KINDS = frozenset({"personal", "shared"})

ARCHIVE_MAX_ITEMS = 200

ARCHIVE_MAX_ITEM_BYTES = 96 * 1024

RESERVED_SOURCE_ROOTS = (
    "archive",
    "athenaresults",
    "user_settings",
    "_data-quality-reports",
    "shared_tables",
)

PROTECTED_MARKER_BASENAME = "DO_NOT_DELETE.txt"

ARCHIVE_FOLDER = "archive"

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
