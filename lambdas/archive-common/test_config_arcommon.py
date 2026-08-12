"""The archive plane's constants, and the bounds they are supposed to hold.

Every cap here is COMPUTED against the thing that sizes it rather than asserted as a number.
A hard-coded number in a test restates the constant; it does not check it, and it hides a
wrong model — which on this plane means a request the Pipe cannot start, or a state that
breaches 256 KB and raises States.DataLimitExceeded outside every Catch.
"""

import json
import math
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import config

#: Step Functions' hard cap on a state payload AND on an execution input. Breaching either
#: raises States.DataLimitExceeded, which is thrown OUTSIDE every Catch.
_STATE_PAYLOAD_LIMIT = 256 * 1024

#: S3's own maximum key length. The worst case a cap has to survive, not the typical one.
_MAX_S3_KEY = 1024


# ── FR-002: the storage class is the single definition, and it is GLACIER ────


def test_the_storage_class_is_glacier():
    assert config.ARCHIVE_STORAGE_CLASS == "GLACIER"


def test_the_storage_class_is_one_of_the_three_archival_classes():
    """A typo here would not fail an apply — S3 rejects an unknown class at COPY time, per
    object, halfway through a transfer that has already started deleting nothing yet but has
    spent real time."""
    assert config.ARCHIVE_STORAGE_CLASS in config.GLACIER_CLASSES


def test_no_verb_hard_codes_the_storage_class_literal():
    """FR-002 AC1: ONE definition. A second literal is how the copy verb and the restore verb
    come to disagree about what class the objects are actually in — which is not a cosmetic
    disagreement, because whether a CopyObject fails InvalidObjectState depends on it."""
    plane = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for root, _dirs, files in os.walk(plane):
        if "__pycache__" in root or not os.path.basename(root).startswith(("archive-", "arcommon")):
            continue
        for name in files:
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            path = os.path.join(root, name)
            if os.path.abspath(path) == os.path.abspath(config.__file__):
                continue
            body = pathlib.Path(path).read_text()
            if re.search(r'"(GLACIER|GLACIER_IR|DEEP_ARCHIVE)"', body):
                offenders.append(path)

    assert not offenders, f"storage-class literal outside arcommon.config: {offenders}"


def test_the_restore_path_is_not_conditional_on_the_class():
    """FR-002 AC4. Setting this to GLACIER_IR must not silently bypass SPEC-171's restore
    machinery: a class that needs no restore still TOLERATES one being requested, and making
    the machinery conditional on a constant is how a config change deletes a code path with
    nothing to show for it in a diff.

    Asserted as the absence of any branch on the constant anywhere on the plane, which is the
    form the mistake would take.
    """
    plane = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for root, _dirs, files in os.walk(plane):
        if "__pycache__" in root or not os.path.basename(root).startswith(("archive-", "arcommon")):
            continue
        for name in files:
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            body = pathlib.Path(root, name).read_text()
            for line in body.splitlines():
                if "ARCHIVE_STORAGE_CLASS" in line and re.match(r"\s*(if|elif|assert|while)\b", line):
                    offenders.append(f"{name}: {line.strip()}")

    assert not offenders, f"the restore path must be unconditional: {offenders}"


# ── FR-005: the item cap, and what actually sizes it ─────────────────────────


def test_the_item_cap_fits_the_per_item_work_inside_the_validators_timeout():
    """COMPUTED against the thing that sizes it, not restated. An earlier version asserted
    `200 % 25 == 0` — which is arithmetic about the file browser's page size and says nothing
    about whether the cap is safe.

    What sizes it is the per-item work: the two containment rules and the reserved-root scan
    here (pure string work, microseconds), and in SPEC-169 **one round trip per ITEM** — a
    `ListObjectsV2` walk for a folder, a serial `HeadObject` for a file. The per-item cost is
    therefore a NETWORK round trip, and the file case is the binding one because 200 files is
    200 serial round trips where 20,000 objects in one folder is 20 paged ones.

    The budget is validate-authorize's own 15-second timeout (`locals.tf`, READ BACK here so
    lowering it fails the build) minus a cold start. SPEC-169's expansion runs in its own verb
    with its own longer timeout, so this bounds THIS verb.
    """
    locals_tf = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "infra" / "modules" / "archive" / "locals.tf"
    ).read_text()
    block = locals_tf[locals_tf.index('"validate-authorize"'):]
    timeout = int(re.search(r"timeout = (\d+)", block).group(1))

    # Conservative: 25 ms per S3 round trip, and 3 s of the budget spent on a cold start plus
    # the JWKS fetch and the registry read that precede the loop.
    worst_case_seconds = config.ARCHIVE_MAX_ITEMS * 0.025
    assert worst_case_seconds < timeout - 3, (
        f"{config.ARCHIVE_MAX_ITEMS} items is ~{worst_case_seconds:.1f}s of serial round trips "
        f"against a {timeout}s verb timeout"
    )


def test_a_count_cap_cannot_bound_the_bytes_and_that_is_why_there_are_two():
    """S3 keys are arbitrary UTF-8, and JSON escaping expands a control character to six
    bytes. Computed, not asserted: at the count cap alone the worst case is several times the
    payload limit, which is the whole reason ARCHIVE_MAX_ITEM_BYTES exists."""
    worst = [{"kind": "file", "key": "\x01" * _MAX_S3_KEY} for _ in range(config.ARCHIVE_MAX_ITEMS)]
    serialized = len(json.dumps(worst, separators=(",", ":")).encode())

    assert serialized > _STATE_PAYLOAD_LIMIT, (
        f"the count cap alone bounds the selection at {serialized:,} bytes, inside the "
        f"{_STATE_PAYLOAD_LIMIT:,}-byte limit — so this test no longer demonstrates why the "
        "byte cap exists"
    )


def test_the_byte_cap_survives_every_link_of_the_chain_it_bounds():
    """THE MIDDLE LINK IS THE ONE AN OBVIOUS MODEL MISSES, and file-send got it wrong once at
    a value measured against the validated output alone — which would have permitted a request
    whose execution could not start at all.

    The chain: the browser's SQS body carries the selection; the EventBridge Pipe wraps that
    body into a record as an ESCAPED JSON STRING and hands it to StartExecution as the
    execution input; Step Functions caps that input at 256 KB exactly as it caps a state.
    Escaping is not a rounding error — every `"` the selection already spent two bytes on
    costs four in the record.

    All three links are computed here, so changing one without the others fails the build.
    """
    # A quote-heavy selection at exactly the byte cap: the worst case the cap admits.
    at_cap = "x" + '"' * (config.ARCHIVE_MAX_ITEM_BYTES // 2)
    body = json.dumps(
        {
            "requestId": "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f",
            "mode": "archive",
            "actor": {"idToken": "e" * 2048},
            "source": {"space": {"kind": "personal", "name": "a" * 63}, "items": at_cap},
        },
        separators=(",", ":"),
    )

    # LINK 1 — the SQS body itself.
    assert len(body.encode()) < _STATE_PAYLOAD_LIMIT

    # LINK 2 — the Pipe's record, which carries the body as an ESCAPED STRING.
    record = json.dumps([{"messageId": "m" * 36, "body": body}], separators=(",", ":"))
    assert len(record.encode()) < _STATE_PAYLOAD_LIMIT, (
        f"a selection at ARCHIVE_MAX_ITEM_BYTES reaches {len(record.encode()):,} bytes once the "
        f"Pipe escapes it into StartExecution's input — over the {_STATE_PAYLOAD_LIMIT:,}-byte "
        "limit, so the execution could not start and no state would exist to refuse it"
    )

    # LINK 3 — the validated state the verb returns, which carries the selection again plus
    # the resolved source and archive blocks.
    validated = json.dumps(
        {
            "requestId": "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f",
            "mode": "archive",
            "actor": {"username": "a" * 63},
            "source": {"bucket": "b" * 63, "root": "a" * 64, "kind": "personal", "name": "a" * 63,
                       "items": at_cap},
            "archive": {"bucket": "b" * 63, "root": "personal/" + "a" * 63 + "/archive/" + "0" * 36 + "/",
                        "receiptBucket": "b" * 63, "receiptKey": "a" * 63 + "/archive/" + "0" * 36 + "/receipt.txt"},
        },
        separators=(",", ":"),
    )
    assert len(validated.encode()) < _STATE_PAYLOAD_LIMIT


# ── FR-005: the reserved list ────────────────────────────────────────────────


# ── SPEC-169: the caps over the EXPANDED selection ───────────────────────────

#: Seconds of overhead per Distributed-Map child execution. A real term at 20,000 items in
#: batches of 8, and one that bytes alone cannot see.
_CHILD_EXECUTION_OVERHEAD_SECONDS = 3

#: How much more a parsed JSON document costs in memory than its bytes. Plan entries are
#: dominated by one ~1 KB string, so the true factor is nearer 1.3; 3 is the pessimistic
#: direction, which is the safe one for a bound.
_PARSED_OBJECT_OVERHEAD = 3


def _locals_text() -> str:
    """The archive module's Terraform locals, as text.

    Read as DATA rather than restated, because a ceiling raised in one place and asserted in
    another is how a cap comes to certify something it never checked.
    """
    return (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "infra" / "modules" / "archive" / "locals.tf"
    ).read_text()


def _verb_row(name: str) -> tuple:
    """One verb's configured timeout and memory, from the Terraform locals.

    Args:
      name: The verb's suffix.

    Returns:
      ``(timeout, memory)``.

    Raises:
      AssertionError: When the row is gone, which would make every bound below vacuous.
    """
    text = _locals_text()
    found = re.search(rf'"{name}"\s*=\s*\{{([^}}]*)\}}', text)
    assert found, f"the archive locals no longer configure a {name!r} verb"
    block = found.group(1)
    return (
        int(re.search(r"timeout\s*=\s*(\d+)", block).group(1)),
        int(re.search(r"memory\s*=\s*(\d+)", block).group(1)),
    )


def _machine_timeout_seconds() -> int:
    """The machine's own top-level TimeoutSeconds, from the Terraform locals."""
    found = re.search(r"state_machine_timeout_seconds\s*=\s*(\d+)", _locals_text())

    assert found, "the archive machine has no top-level TimeoutSeconds in its locals"
    return int(found.group(1))


def _plan_entry_bytes() -> int:
    """One copy-plan entry at S3's worst-case key length, serialised.

    Pessimistic in a way real entries cannot be: the relative key is a SUFFIX of a 1024-byte
    absolute key, so it can never itself be 1024 bytes once the space root is taken off.
    Over-counting is the safe direction for a bound.
    """
    entry = {"relKey": "r" * _MAX_S3_KEY, "bytes": 10 * 1024**3}
    return len(json.dumps(entry, separators=(",", ":")).encode())


def test_the_object_cap_is_a_bound_the_item_cap_could_not_express():
    """The two-quantities argument one level down, asserted where it can fail. One selected
    folder can hold any number of objects, so even a single item can breach the object cap —
    which is why ``ARCHIVE_MAX_ITEMS`` cannot stand in for it."""
    assert config.ARCHIVE_MAX_OBJECTS > 1
    assert _plan_entry_bytes() * config.ARCHIVE_MAX_OBJECTS > config.ARCHIVE_MAX_ITEM_BYTES


def test_the_worst_case_copy_plan_fits_in_the_verbs_memory():
    """WHAT SIZES ARCHIVE_MAX_OBJECTS, computed rather than asserted.

    inspect-source holds the whole plan as a list of dicts, serialises it to a string and
    encodes that to bytes — three live copies at the moment of the write. Half the configured
    memory is left for the interpreter, boto3 and its response buffers, which is not a rounding
    allowance: a cold Lambda with botocore loaded is already tens of megabytes before the first
    object.

    delete-source is checked with it because it loads the same plan back and holds the same
    list, so the two rows have to move together.
    """
    plan_bytes = _plan_entry_bytes() * config.ARCHIVE_MAX_OBJECTS
    live_copies = plan_bytes * (_PARSED_OBJECT_OVERHEAD + 2)

    for verb in ("inspect-source", "delete-source"):
        memory_bytes = _verb_row(verb)[1] * 1024**2
        assert live_copies < memory_bytes / 2, (
            f"a worst-case plan is ~{live_copies / 1024**2:,.0f} MB live against {verb}'s "
            f"{_verb_row(verb)[1]} MB — raise the memory in infra/modules/archive/locals.tf or "
            "lower ARCHIVE_MAX_OBJECTS"
        )


def _transfer_item_bytes() -> int:
    """One manifest line at S3's worst-case key length, serialised.

    Pessimistic in a way real items cannot be: the destination key is DERIVED from the source key
    (the archive prefix plus the same relative path), so both cannot independently be 1024 bytes.
    Over-counting is the safe direction for a bound.
    """
    item = {
        "srcBucket": "b" * 63,
        "srcKey": "s" * _MAX_S3_KEY,
        "destBucket": "d" * 63,
        "destKey": "d" * _MAX_S3_KEY,
        "size": 10 * 1024**3,
        "storageClass": config.ARCHIVE_STORAGE_CLASS,
    }
    return len(json.dumps(item, separators=(",", ":")).encode())


def test_the_worst_case_manifest_fits_in_the_verbs_either_side_of_the_map():
    """The OTHER memory bound, and the two rows it covers were prose until now.

    The manifest builder holds the plan, the item list and the serialised JSONL at once; the
    collector parses an export that carries every batch's input back again. Both are JSON work
    over the object cap, so memory buys CPU as much as headroom — and neither row was read by any
    test, which is exactly how a cap comes to certify something it never checked.
    """
    manifest_bytes = _transfer_item_bytes() * config.ARCHIVE_MAX_OBJECTS
    live_copies = manifest_bytes * (_PARSED_OBJECT_OVERHEAD + 2)

    for verb in ("build-transfer-manifest", "collect-transfer-results"):
        memory_bytes = _verb_row(verb)[1] * 1024**2
        assert live_copies < memory_bytes / 2, (
            f"a worst-case manifest is ~{live_copies / 1024**2:,.0f} MB live against {verb}'s "
            f"{_verb_row(verb)[1]} MB"
        )


def test_the_per_object_cap_keeps_one_object_inside_one_batch_timeout():
    """WHAT SIZES ARCHIVE_MAX_OBJECT_BYTES, and the cap FR-001 does not name because this
    arithmetic does.

    A batch is one round of the worker pool and **one object is one worker**: ``copy_batch``
    hands a whole object to a thread and ``copy_one``'s multipart loop is serial, so nothing
    else bounds a single object's copy time. S3 accepts objects up to 5 TiB, which at the
    conservative rate is ~220,000s — 240x the batch verb's own timeout. Without this cap the
    makespan model certifies the distributed case only, which is SPEC-166's recorded finding.
    """
    from cpcommon.transfer import config as transfer_config

    seconds = config.ARCHIVE_MAX_OBJECT_BYTES / transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    timeout = _verb_row("copy-objects")[0]

    assert timeout == transfer_config.COPY_TIMEOUT_SECONDS, (
        "the engine's copy budget and the deployed verb's timeout have come apart"
    )
    assert seconds < timeout, (
        f"one {config.ARCHIVE_MAX_OBJECT_BYTES / 1024**3:.0f} GiB object is ~{seconds:,.0f}s of "
        f"copying against a {timeout}s batch timeout"
    )


def test_the_whole_run_fits_the_machines_ceiling():
    """WHAT SIZES ARCHIVE_MAX_BYTES, and the one place every term is added up.

    The copy is not the only thing inside the ceiling, and a model that only counted it would be
    the aggregate-bandwidth mistake wearing a different hat. Three terms, each read from the
    locals or the engine's constants rather than restated here:

    * the transfer itself, at the MAKESPAN rate (concurrency x per-stream), not the aggregate —
      ``copy_batch`` gives one whole object to one worker, so an object occupies that worker for
      ``size / rate`` however many other workers are idle;
    * the per-child overhead of ``ARCHIVE_MAX_OBJECTS`` in batches of ``MAX_ITEMS_PER_BATCH`` at
      ``MAP_MAX_CONCURRENCY``;
    * the seven serial verbs, which on this plane include a whole deletion pass.

    They are summed rather than checked one at a time because they all happen in the same run.
    Unlike file-send there is no recipient product: an archive has one destination, so the
    source cap IS the transfer cap.
    """
    from cpcommon.transfer import config as transfer_config

    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    copying = config.ARCHIVE_MAX_BYTES / rate

    batches = -(-config.ARCHIVE_MAX_OBJECTS // transfer_config.MAX_ITEMS_PER_BATCH)
    rounds = -(-batches // transfer_config.MAP_MAX_CONCURRENCY)
    child_overhead = rounds * _CHILD_EXECUTION_OVERHEAD_SECONDS

    serial = sum(
        _verb_row(verb)[0]
        for verb in (
            "validate-authorize",
            "inspect-source",
            "build-transfer-manifest",
            "collect-transfer-results",
            "write-manifest",
            "delete-source",
            "write-receipt",
        )
    )

    worst = copying + child_overhead + serial

    assert worst < _machine_timeout_seconds(), (
        f"the worst legal run is {worst:,.0f}s — copy {copying:,.0f}s + child overhead "
        f"{child_overhead:,.0f}s + serial verbs {serial:,.0f}s — against a "
        f"{_machine_timeout_seconds():,}s ceiling. Lower a cap or raise the timeout in "
        "infra/modules/archive/locals.tf, and do not raise the rate without evidence"
    )


def test_the_byte_cap_admits_more_than_one_object_at_the_per_object_cap():
    """A relationship rather than arithmetic on two constants: a total cap beneath the
    per-object one would refuse a selection of two large files while permitting one, which is a
    product rule nobody wrote."""
    assert config.ARCHIVE_MAX_BYTES > config.ARCHIVE_MAX_OBJECT_BYTES


def test_every_reserved_root_is_a_bare_folder_name():
    """A trailing slash or a leading one here would silently stop the anchored comparison in
    `assert_not_reserved` from matching anything, and the rule would pass by refusing nothing."""
    for folder in config.RESERVED_SOURCE_ROOTS:
        assert folder and not folder.startswith("/") and not folder.endswith("/")


def test_the_reserved_list_has_no_duplicates():
    assert len(set(config.RESERVED_SOURCE_ROOTS)) == len(config.RESERVED_SOURCE_ROOTS)


# ── The restore guard's bounds (SPEC-170) ────────────────────────────────────


#: A pessimistic HeadObject round trip, in seconds. Real ones inside the same region are single-
#: digit milliseconds; 100 ms is two orders out, which is the safe direction for a bound.
_HEAD_LATENCY_SECONDS = 0.1

#: botocore's default ``max_pool_connections``, which is what actually bounds how many heads can
#: be in flight at once — see ``RESTORE_HEAD_CONCURRENCY``. A LITERAL, like `_MAX_S3_KEY` and
#: `_STATE_PAYLOAD_LIMIT` above and for the same reason: it is an external constant, and this
#: suite deliberately has no boto3 in it (every test stubs `clients._s3`, so the fleet's test
#: environment installs neither boto3 nor botocore). The test below reads it off botocore anyway
#: WHEN THE PACKAGE HAPPENS TO BE PRESENT, so a drift is caught wherever it can be — rather than
#: the literal being trusted forever or a dependency being added for one assertion.
_BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS = 10


def test_the_guard_can_head_every_destination_inside_its_timeout():
    """WHAT SIZES RESTORE_HEAD_CONCURRENCY, computed rather than asserted.

    THE SCHEDULABLE UNIT IS ONE HEAD ON ONE WORKER. A HeadObject is a small serial round trip
    holding nothing, so unlike the copy pool — where one worker holds a whole multi-gigabyte
    object — the binding constraint here is round trips rather than bytes, and the verb's
    capacity is ``concurrency x timeout / latency``. The worst case is an archive at the object
    cap whose destinations are ALL clear: the short-circuit saves nothing then, and every key is
    headed.

    Half the timeout is left as headroom for the cold start, the plan read and the pool's own
    scheduling. The timeout is READ BACK from the Terraform, so raising ARCHIVE_MAX_OBJECTS or
    lowering the verb's timeout fails the build rather than the invocation.
    """
    timeout = _verb_row("check-destination-clear")[0]
    rounds = math.ceil(config.ARCHIVE_MAX_OBJECTS / config.RESTORE_HEAD_CONCURRENCY)
    seconds = rounds * _HEAD_LATENCY_SECONDS

    assert seconds < timeout / 2, (
        f"a worst-case guard is ~{seconds:,.0f}s against check-destination-clear's {timeout}s — "
        "raise RESTORE_HEAD_CONCURRENCY or the timeout in infra/modules/archive/locals.tf"
    )


def test_the_guards_pool_fits_inside_the_clients_connection_pool():
    """THE TERM THE OBVIOUS MODEL SKIPS, and the one that made the first version of this constant
    wrong. "Workers x timeout / latency" says to widen the pool until the arithmetic fits — but
    ``boto3.client("s3")`` takes botocore's default ``max_pool_connections``, so threads past that
    do not each get a connection: they contend, and urllib3 opens and discards sockets rather than
    reusing them. A pool of 32 buys throughput the client cannot deliver while every bound
    computed from it reads as satisfied.

    The bound is asserted against a literal because this suite has no botocore in it — every test
    stubs ``clients._s3``, and the fleet's test environment installs neither it nor boto3. Where
    the package IS importable the literal is checked against the real default in the same breath,
    so this cannot quietly become a restatement of a number that has since moved.
    """
    assert _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS >= config.RESTORE_HEAD_CONCURRENCY

    try:
        from botocore.config import Config
    except ImportError:
        return
    assert Config().max_pool_connections == _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS, (
        "botocore's default connection pool has moved; RESTORE_HEAD_CONCURRENCY was computed "
        "against the old value"
    )


def test_the_restore_plan_fits_in_the_lookup_verbs_memory():
    """inspect-archive is inspect-source's mirror and is sized by the same quantity: it holds the
    whole restore plan as a list of dicts, serialises it and encodes that at once. Each entry is
    LARGER than a copy-plan entry — it carries the archive key AND the destination key — so the
    bound is recomputed rather than inherited.

    check-destination-clear is checked with it because it loads the same plan back, so the two
    rows have to move together.
    """
    entry = {
        "archiveKey": "a" * _MAX_S3_KEY,
        "destKey": "d" * _MAX_S3_KEY,
        "bytes": 10 * 1024**3,
    }
    plan_bytes = len(json.dumps(entry, separators=(",", ":")).encode()) * config.ARCHIVE_MAX_OBJECTS
    live_copies = plan_bytes * (_PARSED_OBJECT_OVERHEAD + 2)

    for verb in ("inspect-archive", "check-destination-clear"):
        memory_bytes = _verb_row(verb)[1] * 1024**2
        assert live_copies < memory_bytes / 2, (
            f"a worst-case restore plan is ~{live_copies / 1024**2:,.0f} MB live against "
            f"{verb}'s {_verb_row(verb)[1]} MB — raise the memory in "
            "infra/modules/archive/locals.tf or lower ARCHIVE_MAX_OBJECTS"
        )


def test_the_conflict_sample_is_small_enough_to_read_and_large_enough_to_act_on():
    """A presentation bound, not a work bound. One collision is not a pattern a user can act on
    and twenty is not a sentence anybody reads in a notification."""
    assert 1 < config.RESTORE_CONFLICT_SAMPLE <= 10


# ── The archive bucket is read from the env, and only on demand ──────────────


def test_the_archive_bucket_is_a_function_so_the_layer_stays_import_safe():
    """A constant resolved at import time in a layer module runs for every attaching function
    whether or not it uses the value, and an unset variable then crashes at COLD START, where
    no test and no deploy can see it (PR #196)."""
    assert callable(config.archive_bucket)
    assert not hasattr(config, "ARCHIVE_BUCKET")


def test_the_archive_bucket_raises_where_it_is_read_when_the_variable_is_unset():
    previous = os.environ.pop("ARCHIVE_BUCKET", None)
    try:
        with pytest.raises(RuntimeError) as caught:
            config.archive_bucket()
        assert "ARCHIVE_BUCKET" in str(caught.value)
    finally:
        if previous is not None:
            os.environ["ARCHIVE_BUCKET"] = previous


# ── SPEC-171: the retrieval's bounds, each against the thing that sizes it ───

#: The Standard retrieval tier's own worst case, in seconds. AWS documents 3-5 hours; the budget
#: is measured against the 5. A LITERAL for `_MAX_S3_KEY`'s reason — it is an external fact about
#: a service, not a constant this repo owns — and it is the number the whole loop is sized by, so
#: the tier changing is the thing that should fail this build.
_STANDARD_TIER_WORST_CASE_SECONDS = 5 * 3600


def test_the_tier_is_standard_and_the_alternatives_stay_rejected():
    """FR-001 AC2. Expedited is capacity-limited without a standing monthly charge this portal
    does not make, and Bulk's 5-12 hours doubles the worst case for somebody sitting in a
    browser — so the tier is not a dial to be turned without re-deriving the budget below."""
    assert config.RESTORE_TIER == "Standard"


def test_the_retrieval_budget_clears_the_tiers_own_worst_case():
    """WHAT SIZES RESTORE_MAX_POLLS, computed rather than asserted. A retrieval that is merely
    slow must not be reported as a failure the user has to PAY to repeat — re-submitting means a
    second billed retrieval — so the budget is sized above the tier's worst case with headroom
    rather than at it."""
    budget = config.RESTORE_POLL_SECONDS * config.RESTORE_MAX_POLLS

    assert budget > _STANDARD_TIER_WORST_CASE_SECONDS * 1.2, (
        f"the loop gives up after {budget:,}s against a tier whose worst case is "
        f"{_STANDARD_TIER_WORST_CASE_SECONDS:,}s — a slow-but-healthy retrieval would be "
        "reported as a failure and repeating it costs a second bill"
    )


def test_the_poll_can_sweep_the_whole_plan_inside_its_timeout():
    """WHAT SIZES the poll verb's timeout, and it is the GUARD'S ARITHMETIC re-used rather than
    re-derived, because it does the same work: HeadObject over the plan at
    RESTORE_HEAD_CONCURRENCY, which botocore's connection pool holds at 8.

    The worst case is the invocation that finds every page complete and therefore sweeps the
    whole archive — which is the point of sweeping past the page rather than stopping at it,
    since one page per five-minute Wait would add over an hour after a retrieval had already
    finished. The timeout is READ BACK from the Terraform.
    """
    timeout = _verb_row("poll-restore")[0]
    rounds = math.ceil(config.ARCHIVE_MAX_OBJECTS / config.RESTORE_HEAD_CONCURRENCY)
    seconds = rounds * _HEAD_LATENCY_SECONDS

    assert seconds < timeout / 2, (
        f"a full sweep is ~{seconds:,.0f}s against poll-restore's {timeout}s"
    )


def test_the_page_is_smaller_than_the_plan_it_is_paging():
    """A page at or above ARCHIVE_MAX_OBJECTS makes the progress record decorative — every
    iteration would re-head everything, which is precisely what FR-002 AC4 exists to prevent —
    while a page of one would record progress on every object and spend the sweep's time in
    PutObject calls."""
    assert 1 < config.RESTORE_POLL_PAGE < config.ARCHIVE_MAX_OBJECTS


def test_the_availability_window_outlives_the_copy_that_reads_it():
    """WHAT SIZES RESTORE_AVAILABILITY_DAYS. The temporary object a retrieval materialises is
    what the copy-back reads, so it has to outlive it — and the failure if it does not is the
    one worth computing for, because it does not look like a configuration error: the copy
    begins succeeding and then starts failing InvalidObjectState partway through, on the objects
    it retrieved FIRST.

    The margin is generous against the copy alone because the window starts when each object
    becomes available, not when the copy starts — so the real quantity it has to cover is the
    rest of the run after the earliest object lands.
    """
    from cpcommon.transfer import config as transfer_config

    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    copying = config.ARCHIVE_MAX_BYTES / rate
    window = config.RESTORE_AVAILABILITY_DAYS * 86_400

    assert window > (copying + _machine_timeout_seconds()) * 2, (
        f"a {config.RESTORE_AVAILABILITY_DAYS}-day window against a ~{copying:,.0f}s copy-back "
        f"inside a {_machine_timeout_seconds():,}s ceiling leaves too little margin"
    )


def test_the_whole_restore_fits_the_machines_ceiling():
    """WHAT SIZES the machine's TimeoutSeconds on the RESTORE arm, and the one place every term
    is added up. The restore's long pole is not a copy — it is a WAIT — which is why this arm
    needed the ceiling raised where the archive arm did not.

    Five terms, each read from the constants rather than restated:

    * the retrieval budget, RESTORE_POLL_SECONDS x RESTORE_MAX_POLLS;
    * the poll's own work, which is TWO quantities and not one — the forward sweep is paid ONCE
      in total across the whole loop (each page is swept past exactly once), while re-heading
      the current page is paid EVERY iteration. Multiplying a full sweep by the iteration count
      would model a loop that re-reads the archive every five minutes, which is the very thing
      the progress record exists to prevent;
    * the copy-back, at the MAKESPAN rate — one whole object to one worker — not the aggregate;
    * both Maps' per-child overhead, since the retrieval fans out over the same items;
    * the serial verbs on this arm, which include a whole deletion pass.
    """
    from cpcommon.transfer import config as transfer_config

    waiting = config.RESTORE_POLL_SECONDS * config.RESTORE_MAX_POLLS

    sweep_rounds = math.ceil(config.ARCHIVE_MAX_OBJECTS / config.RESTORE_HEAD_CONCURRENCY)
    page_rounds = math.ceil(config.RESTORE_POLL_PAGE / config.RESTORE_HEAD_CONCURRENCY)
    polling = (sweep_rounds + page_rounds * config.RESTORE_MAX_POLLS) * _HEAD_LATENCY_SECONDS

    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    copying = config.ARCHIVE_MAX_BYTES / rate

    batches = -(-config.ARCHIVE_MAX_OBJECTS // transfer_config.MAX_ITEMS_PER_BATCH)
    rounds = -(-batches // transfer_config.MAP_MAX_CONCURRENCY)
    child_overhead = 2 * rounds * _CHILD_EXECUTION_OVERHEAD_SECONDS

    serial = sum(
        _verb_row(verb)[0]
        for verb in (
            "validate-authorize",
            "inspect-archive",
            "check-destination-clear",
            "build-restore-manifest",
            "update-receipt",
            "collect-transfer-results",
            "delete-archived",
        )
    )

    worst = waiting + polling + copying + child_overhead + serial

    assert worst < _machine_timeout_seconds(), (
        f"the worst legal restore is {worst:,.0f}s — retrieval budget {waiting:,.0f}s + polling "
        f"{polling:,.0f}s + copy-back {copying:,.0f}s + child overhead {child_overhead:,.0f}s + "
        f"serial verbs {serial:,.0f}s — against a {_machine_timeout_seconds():,}s ceiling. Lower "
        "RESTORE_MAX_POLLS or a cap, or raise the timeout in infra/modules/archive/locals.tf"
    )


def test_the_raised_ceiling_still_leaves_the_archive_arm_far_inside_it():
    """THE COST OF ONE MACHINE WITH TWO ARMS, stated where it can be measured. TimeoutSeconds is
    a top-level ASL field and cannot differ per branch, so raising it for the restore raised the
    ARCHIVE's backstop too — a wedged archive is now reported after ten hours rather than three.
    That is accepted; what must not happen quietly is the ceiling drifting so far that it stops
    being a backstop for the arm that does not wait at all."""
    from cpcommon.transfer import config as transfer_config

    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND

    assert config.ARCHIVE_MAX_BYTES / rate < _machine_timeout_seconds() / 4, (
        "the archive arm's own long pole is now a small fraction of a ceiling sized for a "
        "Glacier retrieval — re-read the restore arm's arithmetic before widening it further"
    )


def test_the_restore_storage_class_is_stated_and_is_not_an_archival_one():
    """FR-003 AC2. The copy IS what changes the class: the object a retrieval materialises is
    temporary, so an item copied without an explicit STANDARD lands back in GLACIER and expires
    to unreadable a few days later — having looked like a success throughout. The engine treats
    an empty class as "do not pass the argument", so relying on S3's default here would be
    indistinguishable in the code and catastrophic in effect."""
    assert config.RESTORE_STORAGE_CLASS == "STANDARD"
    assert config.RESTORE_STORAGE_CLASS not in config.GLACIER_CLASSES


def test_the_archive_bucket_is_not_in_cpcommons_fleet_wide_required_set():
    """That set is a contract EVERY plane's Lambda environment must satisfy, asserted per
    plane by test_the_common_environment_satisfies_every_import_time_require. A variable only
    this plane sets belongs in this layer, not there — putting it there fails every other
    plane's guard, which is how this was caught while it was being written."""
    from cpcommon import config as cpconfig

    assert "ARCHIVE_BUCKET" not in cpconfig._REQUIRED_VARS.values()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
