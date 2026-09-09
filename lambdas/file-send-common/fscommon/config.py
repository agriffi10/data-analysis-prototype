"""Domain configuration for the file-send control plane.

The shared core — region, user pool identifiers, buckets, the notifications queue — lives in
``cpcommon.config``. Only file-send's own constants live here, and **none of them reads the
environment**: this module cannot fail at import, which matters because a shared layer's
import-time failure surfaces at COLD START, where no test and no deploy can see it.

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
    exactly as it does for table-share's identical cap, and not the fan-out: The guard
    Map records a per-recipient outcome, each failed item carrying the raw Step Functions
    error bounded by ``cpcommon.errors.MAX_DETAIL_CHARS``, and breaching 256 KB raises
    ``States.DataLimitExceeded`` ON THE MAP — destroying every per-recipient outcome the Map
    exists to preserve, outside every Catch.
    ``test_the_validated_state_stays_under_the_payload_limit`` computes the worst case from these
    constants rather than asserting a number, and
    ``test_a_failed_recipient_carrying_a_bounded_error_still_fits`` does the same for the failure
    path, which is the binding one. Neither refuses a modest raise — the recipient cap has
    several times' room before either fires — so RE-CHECK the model when moving a cap rather
    than expecting the build to.
  SEND_MAX_ITEMS: Cap on the NUMBER of selected items — the files and folders the user picked,
    **not** the objects they expand to. What sizes it is the per-item work that follows: two
    containment checks and, one ``ListObjectsV2`` walk per folder. It is
    emphatically NOT a bound on the transfer — a single folder can hold a million objects — and
    the caps that bound *that* belong to the expansion and the manifest,
    the same three-way split table-share arrived at.

    **It does NOT bound the state payload, and an earlier version of this comment claimed it
    did.** A count cap cannot: S3 keys are arbitrary UTF-8, and JSON escaping expands a `"` to
    two bytes and a control character to six, so 200 items at a 1024-byte key is 216 KB of
    ASCII or 1.2 MB of ``\\x01``. The bound that actually holds is ``SEND_MAX_ITEM_BYTES``
    below, measured on the serialised selection. Two caps because there are two quantities;
    one cap standing in for both is how a bound comes to certify something it never checked.

    The product reading is comfortable: the file browser pages at 25, so this is eight full
    pages of selection.
  SEND_MAX_ITEM_BYTES: Cap on the SERIALISED selection, which is the term that actually rides.
    **What sizes it is not one limit but a chain, and the middle link is the one an obvious
    model misses.** The browser's SQS body carries the selection; the EventBridge Pipe wraps
    that body into a record as an ESCAPED JSON STRING and hands it to ``StartExecution`` as the
    execution input; Step Functions caps that input at 256 KB exactly as it caps a state. The
    escaping is not a rounding error — every ``"`` the selection already spent two bytes on
    costs four in the record — so a quote-heavy selection reaches the record at **twice** its
    measured size.

    **It came down from 96 KiB, and what moved was the fourth link's model rather than the
    request.** A failure state is that record PLUS an error whose ``Cause`` the service permits
    32,768 CHARACTERS of — a length on an execution-history event, not a byte quota on a state —
    so a Cause sitting inside a JSON string on the state costs twice that. The old model allowed
    it 4 KB. Reserved honestly, a quote-heavy selection at the old cap breached the 256 KiB limit
    on a ``Pass`` with no ``Catch``. **The number is not written here** — a byte figure in a
    docstring has nothing holding it to the model it came from, and the first one written here was
    stale within the same branch. ``lambdas/test_request_size_chain.py`` computes every link for
    every piped route against one constant and pins the overshoot; the message cap this sits under
    is derived in ``lambdas/api/apicommon/enqueue.py``.

    An earlier value of 192 KiB was measured against the validated output ALONE and would have
    permitted a request whose execution could not start. ``test_config_fscommon`` now computes
    all three links, so a change to one without the others fails the build.

    **THIS CAP CANNOT BE THE ONLY GUARD, and saying so is the honest version.** It is enforced
    in the first Task, and a request too large for ``StartExecution`` fails before any state
    exists to enforce it — the Pipe simply cannot start the execution. That failure is not
    silent: the message exhausts its redrive policy, lands on this plane's DLQ, and the
    drain turns it into a user notification. It is merely a worse experience than a refusal, so
    the producer carries the same bound (``fileSend.service.ts``) and a test holds the two
    numbers together.

    Checked AFTER normalisation rather than on the raw body: the item count is already bounded
    by then, so measuring the real serialised form costs nothing and measures the real thing.
  SEND_MAX_OBJECTS: Cap on the EXPANDED object count — what the selection resolves to, which
    is the quantity neither cap above can express: ``SEND_MAX_ITEMS`` bounds the things the
    user picked, and one of them can be a folder holding a million objects.

    **What sizes it is inspect-source holding the whole copy plan in memory before writing
    it**, not the listing time. ``list_data_objects`` pages at 1,000 keys, so 20,000 objects is
    20 round trips — a second or two of a 120-second budget, nowhere near binding. The plan is:
    each entry carries the absolute source key, the relative key and the owning item name, so
    at S3's worst-case 1024-byte keys an entry serialises to roughly 2.4 KB and the whole plan
    to ~48 MB, with the in-memory list of dicts several times that again. The verb's 1024 MB
    (locals.tf) is sized for exactly that, and
    ``test_the_worst_case_file_send_copy_plan_fits_in_the_verbs_memory`` computes the plan
    against that row and READS IT BACK. It refuses neither a modest raise of this cap nor a
    halving of the memory — the plan sits about four times inside it — so RE-DERIVE the pair
    when moving either number rather than expecting the build to object.

    It is NOT a bound on the transfer. The manifest carries one item per (recipient, object)
    pair, so 20,000 objects to 50 recipients is a million items — the product caps are
    The transfer's, sized against the Map Run its own ``TimeoutSeconds`` bounds.
  SEND_MAX_TOTAL_BYTES: Cap on the bytes ONE selection holds, and only that. Like its
    table-share twin it says nothing about how much the copy moves, because every recipient
    gets a full copy; it exists so a single send cannot be unbounded on its own.

    **What sizes it is the copy's MAKESPAN, at the rate the engine actually delivers.** The
    copy is ``cpcommon.transfer`` for this plane too, and its recorded model is a makespan
    rather than an aggregate: ``copy_batch`` hands one whole object to each worker and the
    multipart loop inside ``copy_one`` is serial, so the pessimistic denominator is
    ``MAP_MAX_CONCURRENCY x CONSERVATIVE_STREAM_BYTES_PER_SECOND`` — 500 MB/s, not the
    4 GB/s an aggregate-bandwidth reading suggests. At that rate 1 TiB is ~2,200 seconds for a
    single recipient, comfortably inside the 10,800-second ceiling the identical engine already
    runs under on table-share. ``test_a_full_size_selection_copies_inside_the_engines_ceiling``
    computes it.

    **It says nothing about the transfer, and the three caps below are what do.** This cap alone
    permits 50 recipients x 1 TiB = 50 TiB, which no plausible throughput moves. The transfer added
    them together with the machine's ``TimeoutSeconds``, because a product cap is meaningless
    until there is a ceiling to measure it against.
  SEND_MAX_OBJECT_BYTES: Cap on ONE object, and the cap without which the makespan model above
    certifies only the distributed case. 500 MB/s is reachable only when the bytes are spread
    over the whole worker pool; ONE object is copied by ONE worker at
    ``CONSERVATIVE_STREAM_BYTES_PER_SECOND``, and ``copy_one``'s multipart loop is serial. So
    what sizes this is a single batch's makespan against ``COPY_TIMEOUT_SECONDS`` — the batch
    verb's own Lambda timeout — and not the machine's ceiling.

    At 10 GiB that is ~429 s of a 900 s budget, which is the same value and the same arithmetic
    as table-share's ``SHARE_MAX_OBJECT_BYTES``: the two planes share the engine, the batch size
    and the timeout, so a different number here would mean one of them was wrong. Without it the
    worst legal case at ``SEND_MAX_TOTAL_BYTES`` was a single 1 TiB object on one worker —
    43,980 s, four times over the machine ceiling — recorded as owed rather than
    absent.
  SEND_MAX_TRANSFER_ITEMS: Cap on ``objects x REQUESTED recipients``, which is the manifest's
    length. Measured on the requested count, before the guard, because a cap that only bites
    after the destinations have been listed has already let the work happen.

    **What sizes it is the two verbs either side of the Map holding that manifest in memory**,
    not the copying: the builder holds the item list, its serialised form and the encoded bytes
    at once, and the collector parses an export that carries every batch's input back again. At
    S3's worst-case keys an item is ~2.6 KB, so 50,000 items is ~130 MB and peaks near 390 MB
    against the 2048 MB in ``locals.tf`` — which the test READS, so raising this without raising
    the memory fails the build.

    Neither per-source cap can express it: 20,000 objects is legal and so are 50 recipients, and
    every manifest item is a full copy, so the product is a million lines nothing else bounds.

    **It is deliberately NOT table-share's 20,000, and the divergence is the point.** The
    parity argument that fixes ``SEND_MAX_OBJECT_BYTES`` to table-share's value does not carry
    here: that cap bounds ONE object against a shared engine and a shared timeout, where this
    one bounds a product against a memory budget and a product this plane meets far more often.
    Table-share's transfer cap equals its own object cap, so at full size it permits exactly one
    recipient — acceptable when a share is one table. A send of a 2,000-file folder to a
    30-person team is the ordinary case here and would be refused at 20,000. The computed
    ceiling at the configured memory is ~150,000 items; 50,000 takes a third of it, and the
    verbs' 300-second timeouts are not the binding term (``test_the_manifest_verbs_do_their_json
    _work_inside_their_timeout`` computes that too).
  SEND_MAX_TRANSFER_BYTES: Cap on ``total bytes x REQUESTED recipients`` — what the Map actually
    moves, since every recipient gets a full copy.

    **What sizes it is the whole run's makespan against the machine's ``TimeoutSeconds``**, at
    ``MAP_MAX_CONCURRENCY x CONSERVATIVE_STREAM_BYTES_PER_SECOND`` = 500 MB/s and NOT the ~4
    GB/s an aggregate-bandwidth reading of the same constants suggests. Table-share made that
    mistake twice, in review rounds, after it read as satisfied both times. 3 TiB is ~6,600 s;
    the guard Map, the serial verbs and the per-child overhead of 50,000 items in batches of 8
    take the worst run to ~8,900 s inside the 10,800 s ceiling, and the test computes every term
    rather than asserting the total.

    The one term in that sum with no measurement behind it is the per-child overhead, and the
    test says so: it is charged per ROUND of the Map's concurrency rather than per child,
    because slots pipeline. That modelling choice is load-bearing — at even half a second per
    CHILD the budget would blow — so it is stated rather than buried, and the margin it leaves
    (~1,900 s, a break-even of ~9 s per round) is what a reader should re-derive before raising
    any cap here.
  SHARED_FILES_FOLDER: The destination inbox folder, one level under the recipient's space
    root and namespaced by sender — ``{target}/shared_files/{sender}/{item}``. Mirrors
    ``shared_tables/``, so two senders never collide and provenance is visible in the file
    browser without a metadata lookup. Named here because it is the one layout constant
    validate-authorize and the transfer verbs must agree on.
  USER_SETTINGS_FOLDER: The space's own portal-managed settings folder — the notification inbox
    and the shared-space connections cache. Excluded from an EXPANSION, anchored at
    the space root, not refused as a selected item: the browser hides it everywhere, so a user
    cannot select it, and the exclusion is what keeps a root-level walk from carrying it out.
  ATHENA_RESULTS_FOLDER: The space's own Athena results folder, refused as a send source.
    Re-exported from ``cpcommon.app_managed``, which owns the name.
    **A NEW RULE FOR THIS PLANE, not an existing list being reused** — ``protectedFolders.ts``
    keeps three deliberately divergent lists in which ``athenaresults/`` is never a paste
    destination and never a move source, while copying *out* of it is permitted in the browser
    today. A send is a copy, so no existing list answers this question, and that file's own
    note warns that unioning them is the wrong repair.
"""

from cpcommon import app_managed as _app_managed

RECIPIENT_KINDS = frozenset({"user", "space"})

SPACE_KINDS = frozenset({"personal", "shared"})

SEND_MAX_RECIPIENTS = 50

SEND_MAX_ITEMS = 200

SEND_MAX_ITEM_BYTES = 84 * 1024

SEND_MAX_OBJECTS = 20_000

SEND_MAX_TOTAL_BYTES = 1024**4

SEND_MAX_OBJECT_BYTES = 10 * 1024**3

SEND_MAX_TRANSFER_ITEMS = 50_000

SEND_MAX_TRANSFER_BYTES = 3 * 1024**4

SHARED_FILES_FOLDER = "shared_files"

ATHENA_RESULTS_FOLDER = _app_managed.ATHENA_RESULTS_FOLDER

USER_SETTINGS_FOLDER = "user_settings"
