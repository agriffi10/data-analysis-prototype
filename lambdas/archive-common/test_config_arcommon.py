"""The archive plane's constants, and the bounds they are supposed to hold.

Every cap here is COMPUTED against the thing that sizes it rather than asserted as a number.
A hard-coded number in a test restates the constant; it does not check it, and it hides a
wrong model — which on this plane means a request the Pipe cannot start, or a state that
breaches 256 KB and raises States.DataLimitExceeded, which escapes every Catch here (States.ALL
does not match it and none names it).
"""

import json
import math
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import config
from cpcommon import config as cp_config

#: Step Functions' hard cap on a state payload AND on an execution input. Breaching either
#: raises States.DataLimitExceeded, which escapes every Catch here (States.ALL does not match it
#: and none names it). Read from the fleet constant rather than restated — four private copies of
#: one service quota is the rule-written-twice failure, and the copies do not have to disagree to
#: be a problem: they have to be able to.
_STATE_PAYLOAD_LIMIT = cp_config.STATE_PAYLOAD_LIMIT_BYTES

#: S3's own maximum key length. The worst case a cap has to survive, not the typical one.
_MAX_S3_KEY = 1024


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
    Over-counting is the safe direction for a bound. The tag is a multipart upload's at S3's
    10,000-part ceiling, the longest an ETag gets, and it is serialised with its quotes escaped.
    """
    entry = {"relKey": "r" * _MAX_S3_KEY, "bytes": 10 * 1024**3, "etag": '"' + "f" * 32 + '-10000"'}
    return len(json.dumps(entry, separators=(",", ":")).encode())


def test_the_validated_state_this_plane_returns_fits_the_payload_limit():
    """LINK THREE, which is this plane's own and stays here.

    Links one and two — the caller's body and the Pipe's escaped record — moved to
    ``lambdas/test_request_size_chain.py``, which computes them for every piped route against one
    constant. Three plane guards used to compute overlapping parts of that chain and disagreed
    about the fourth link; one model is the repair. What cannot move is this: link three is what a
    VERB RETURNS, and each plane's is a different shape.
    """
    at_cap = "x" + '"' * (config.ARCHIVE_MAX_ITEM_BYTES // 2)
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


def test_the_worst_case_archive_copy_plan_fits_in_the_verbs_memory():
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
    Over-counting is the safe direction for a bound. It carries every field either arm's builder
    writes — the restore's conditional-write flag, the archive's source pin and both arms' folder
    flag — so a field added to a line has to be added here for the bound to keep measuring the
    real line. No real line carries both the flag and the pin; this one does, which over-counts.
    """
    item = {
        "srcBucket": "b" * 63,
        "srcKey": "s" * _MAX_S3_KEY,
        "destBucket": "d" * 63,
        "destKey": "d" * _MAX_S3_KEY,
        "size": 10 * 1024**3,
        "storageClass": config.ARCHIVE_STORAGE_CLASS,
        "ifAbsent": True,
        "srcEtag": '"' + "f" * 32 + '-10000"',
        "folder": False,
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


def test_the_whole_archive_run_fits_the_machines_ceiling():
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


def test_delete_source_can_head_every_original_inside_its_timeout():
    """WHAT SIZES delete-source's timeout. Before it deletes anything it heads every original to
    confirm it still carries the tag the plan recorded, which is the guard's work over the same
    plan at the same pool — so it is the guard's arithmetic, read against delete-source's own row.
    """
    timeout = _verb_row("delete-source")[0]
    rounds = math.ceil(config.ARCHIVE_MAX_OBJECTS / config.SOURCE_HEAD_CONCURRENCY)
    seconds = rounds * _HEAD_LATENCY_SECONDS

    assert seconds < timeout / 2, (
        f"a worst-case check of the originals is ~{seconds:,.0f}s against delete-source's "
        f"{timeout}s — raise the timeout in infra/modules/archive/locals.tf"
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
    assert _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS >= config.SOURCE_HEAD_CONCURRENCY

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


#: The Standard retrieval tier's own worst case, in seconds. AWS documents 3-5 hours; the budget
#: is measured against the 5. A LITERAL for `_MAX_S3_KEY`'s reason — it is an external fact about
#: a service, not a constant this repo owns — and it is the number the whole loop is sized by, so
#: the tier changing is the thing that should fail this build.
_STANDARD_TIER_WORST_CASE_SECONDS = 5 * 3600


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
    ARCHIVE's backstop too — a wedged archive is now reported after twelve hours rather than
    three.
    That is accepted; what must not happen quietly is the ceiling drifting so far that it stops
    being a backstop for the arm that does not wait at all."""
    from cpcommon.transfer import config as transfer_config

    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND

    assert config.ARCHIVE_MAX_BYTES / rate < _machine_timeout_seconds() / 4, (
        "the archive arm's own long pole is now a small fraction of a ceiling sized for a "
        "Glacier retrieval — re-read the restore arm's arithmetic before widening it further"
    )


def test_the_browser_mirrors_the_request_shape_caps():
    """Two homes for one number is how a bound quietly stops matching the thing it bounds.

    The producer cannot import Python, so ``archive.service.ts`` restates both request-shape
    caps — and a restatement nobody checks is worse than no guard at all, because the wrong
    number reads as deliberate. Read as data from the TypeScript source, exactly as file-send
    holds its own pair together.

    Only these two are mirrored, and that is the line: they bound the REQUEST, which is what the
    browser composes. Everything below them — the object count, the byte totals, the per-object
    ceiling — is discovered by expanding a folder the browser never lists, so a browser-side copy
    could only ever be a guess.
    """
    service = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "portal"
        / "src"
        / "features"
        / "archive"
        / "archive.service.ts"
    ).read_text()

    declared = dict(
        re.findall(r"const (ARCHIVE_MAX_ITEMS|ARCHIVE_MAX_ITEM_BYTES) = ([^;]+);", service)
    )

    assert declared, "the producer no longer declares the caps under the expected names"
    assert eval(declared["ARCHIVE_MAX_ITEMS"]) == config.ARCHIVE_MAX_ITEMS  # noqa: S307
    assert eval(declared["ARCHIVE_MAX_ITEM_BYTES"]) == config.ARCHIVE_MAX_ITEM_BYTES  # noqa: S307



def test_the_index_path_cannot_outlast_the_verbs_that_run_it():
    """A stall on the index is swallowed only if it ends before the verb's Lambda timeout does.

    The worst case is the deadline plus one bounded call started just before it: every attempt of
    that call waits out its connect and read bounds, and the standard retry mode sleeps at most
    ``2 ** (attempt - 1)`` seconds before each retry. It must leave at least half of each verb's
    timeout to the work the verb exists for — the receipt write — which runs on the unbounded
    default client.
    """
    from arcommon import index_store
    from cpcommon import clients

    attempts = clients.BOUNDED_MAX_ATTEMPTS
    per_call = attempts * (clients.BOUNDED_CONNECT_SECONDS + clients.BOUNDED_READ_SECONDS) + sum(
        2 ** (attempt - 1) for attempt in range(1, attempts)
    )
    worst = index_store.INDEX_DEADLINE_SECONDS + per_call

    for verb in ("write-receipt", "update-receipt"):
        timeout = _verb_row(verb)[0]
        assert worst <= timeout / 2, (
            f"the index path can take {worst}s inside {verb}, whose timeout is {timeout}s"
        )


def test_the_browser_states_the_same_name_rule():
    """The name's cap and refused ranges, read as data out of the browser's rule.

    The corpus both sides run holds the LOGIC together; this holds the two constants, which a
    corpus can only sample — a range narrowed by one code point at an edge no case sits on would
    pass every corpus case.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "portal"
        / "src"
        / "features"
        / "archive"
        / "archiveName.ts"
    ).read_text()

    cap = re.search(r"export const ARCHIVE_NAME_MAX_CHARS = (\d+);", source)
    block = re.search(r"ARCHIVE_NAME_REFUSED_RANGES[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    assert cap and block, "the browser no longer declares the name rule under the expected names"
    ranges = tuple(
        (int(low, 16), int(high, 16))
        for low, high in re.findall(r"\[0x([0-9a-fA-F]+),\s*0x([0-9a-fA-F]+)\]", block.group(1))
    )

    assert int(cap.group(1)) == config.ARCHIVE_NAME_MAX_CHARS
    assert ranges == config.ARCHIVE_NAME_REFUSED_RANGES
