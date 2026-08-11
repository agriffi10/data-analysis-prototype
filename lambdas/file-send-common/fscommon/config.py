"""Domain configuration for the file-send control plane.

The shared core — region, user pool identifiers, buckets, the notifications queue — lives in
``cpcommon.config``. Only file-send's own constants live here, and **none of them reads the
environment**: this module cannot fail at import, which matters because a shared layer's
import-time failure surfaces at COLD START, where no test and no deploy can see it (PR #196).

Every cap below is a whole-request terminal in validate-authorize, raised before any AWS call
that costs anything, so a refused send leaves nothing behind.

Attributes:
  RECIPIENT_KINDS: The two recipient kinds a send may target. A ``space`` is any space by
    name — the sender need not be a member, matching table-share's recorded decision, because
    the execution role does the write and the sender's own access question is about the
    SOURCE.
  SPACE_KINDS: The two source-space kinds. The kind decides which bucket the source resolves
    in and which authorization question is asked, so it is validated rather than inferred.
  SEND_MAX_RECIPIENTS: Recipient cap. **What sizes it is the Step Functions state payload**,
    exactly as it does for table-share's identical cap, and not the fan-out: SPEC-166's guard
    Map records a per-recipient outcome, each failed item carrying the raw Step Functions
    error bounded by ``cpcommon.errors.MAX_DETAIL_CHARS``, and breaching 256 KB raises
    ``States.DataLimitExceeded`` ON THE MAP — destroying every per-recipient outcome the Map
    exists to preserve, outside every Catch. ``test_the_validated_state_stays_under_the_
    payload_limit`` computes the worst case from these constants rather than asserting a
    number, so raising either cap without re-checking fails the build.
  SEND_MAX_ITEMS: Cap on the number of SELECTED items — the files and folders the user picked,
    **not** the objects they expand to. **What sizes it is the same state payload**, since the
    selection rides inline from validate-authorize into SPEC-165: at S3's worst-case 1024-byte
    key an item costs about 1.1 KB, so the two caps are spending one 256 KB budget between
    them. It is emphatically NOT a bound on the transfer — a single folder can hold a million
    objects — and the caps that bound *that* belong to SPEC-165 (the expansion) and SPEC-166
    (the manifest), the same three-way split table-share arrived at.

    The product reading is comfortable: the file browser pages at 25, so this is eight full
    pages of selection.
  SHARED_FILES_FOLDER: The destination inbox folder, one level under the recipient's space
    root and namespaced by sender — ``{target}/shared_files/{sender}/{item}``. Mirrors
    ``shared_tables/``, so two senders never collide and provenance is visible in the file
    browser without a metadata lookup. Named here because it is the one layout constant
    validate-authorize and the SPEC-166 verbs must agree on.
  ATHENA_RESULTS_FOLDER: The space's own Athena results folder, refused as a send source.
    **A NEW RULE FOR THIS PLANE, not an existing list being reused** — ``protectedFolders.ts``
    keeps three deliberately divergent lists in which ``athenaresults/`` is never a paste
    destination and never a move source, while copying *out* of it is permitted in the browser
    today. A send is a copy, so no existing list answers this question, and that file's own
    note warns that unioning them is the wrong repair.
"""

RECIPIENT_KINDS = frozenset({"user", "space"})

SPACE_KINDS = frozenset({"personal", "shared"})

SEND_MAX_RECIPIENTS = 50

SEND_MAX_ITEMS = 200

SHARED_FILES_FOLDER = "shared_files"

ATHENA_RESULTS_FOLDER = "athenaresults"
