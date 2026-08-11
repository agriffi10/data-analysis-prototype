"""The file-send caps are COMPUTED from what sizes them, never asserted as numbers.

A hard-coded cap number hides a wrong model, and this plane's siblings are the evidence: four
review rounds on SPEC-161 each found a table-share bound measured against the wrong quantity,
and every one of them read as satisfied until someone derived it independently. So the tests
here model the thing the cap protects and compute the ceiling; the constant only has to fit
under it.

**There are TWO quantities, and one cap cannot stand for both.** The first version of this file
had ``SEND_MAX_ITEMS`` bounding the 256 KB Step Functions state, modelled at one payload byte
per key character. That model was wrong in the direction that matters: S3 keys are arbitrary
UTF-8, and JSON escaping expands ``"`` to two bytes and a control character to six, so the same
200 items measure 216 KB of ASCII keys and 1.2 MB of ``\\x01`` ones. The count cap bounds the
per-item WORK; ``SEND_MAX_ITEM_BYTES`` bounds the STATE, measured on the serialised selection
the verb actually emits.

Attributes:
  _STATE_PAYLOAD_LIMIT: Step Functions' hard cap on a state payload.
  _MAX_KEY_BYTES: S3's maximum key length.
  _WORST_ESCAPE: The most expensive character a legal S3 key can hold, per JSON byte. A
    control character escapes to a six-byte ``\\uXXXX``. Modelled rather than excluded: refusing
    control characters in keys would be a product rule this spec never wrote, and the bound
    holds without one.
"""

import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon import errors
from cpcommon.transfer import config as transfer_config
from fscommon import config

_STATE_PAYLOAD_LIMIT = 256 * 1024

_MAX_KEY_BYTES = 1024

_WORST_ESCAPE = "\x01"

#: A Cognito ID token, which rides in the same body as the selection.
_MAX_TOKEN_BYTES = 1200


def _selection_bytes(items: int, key_char: str) -> int:
    """Serialised size of the normalised selection, which is what the byte cap measures.

    Args:
      items: Number of selected items.
      key_char: The character every key is made of, which decides the JSON expansion.

    Returns:
      The serialised byte length.

    Raises:
      None.
    """
    selection = [{"kind": "folder", "key": key_char * _MAX_KEY_BYTES} for _ in range(items)]
    return len(json.dumps(selection, separators=(",", ":")).encode())


def _worst_case_validated_state(selection_bytes: int, recipients: int) -> int:
    """Serialised size of validate-authorize's whole output at its worst allowed shape.

    Args:
      selection_bytes: The serialised selection, at the byte cap.
      recipients: Number of recipients, each carrying an ``invalid`` annotation.

    Returns:
      The serialised byte length.

    Raises:
      None.
    """
    envelope = {
        "requestId": "0" * 36,
        "actor": {"username": "a" * 64},
        "source": {"bucket": "b" * 63, "root": ("r" * 63) + "/", "items": []},
        "recipients": [
            {"kind": "space", "name": "s" * 64, "invalid": "unknown_space"} for _ in range(recipients)
        ],
    }
    return len(json.dumps(envelope, separators=(",", ":")).encode()) + selection_bytes


def _pipe_record(items: list) -> int:
    """Serialised size of the execution input the Pipe hands to ``StartExecution``.

    **The link an obvious model leaves out.** The Pipe wraps the SQS body into a record as an
    escaped JSON string, so every ``"`` the selection already spent two bytes on costs four
    here — a quote-heavy selection arrives at twice its measured size. Step Functions caps this
    input at 256 KB exactly as it caps a state, so a request over it cannot start an execution
    at all: no verb runs, no Catch fires, and nothing notifies anyone.

    Args:
      items: The selection, as the browser sends it.

    Returns:
      The serialised byte length of the Pipe's forwarded batch.

    Raises:
      None.
    """
    body = json.dumps(
        {
            "requestId": "0" * 36,
            "actor": "t" * _MAX_TOKEN_BYTES,
            "source": {"space": {"kind": "personal", "name": "a" * 64}, "items": items},
            "recipients": [
                {"kind": "space", "name": "s" * 64} for _ in range(config.SEND_MAX_RECIPIENTS)
            ],
        },
        separators=(",", ":"),
    )
    record = [
        {
            "messageId": "m" * 36,
            "receiptHandle": "r" * 1024,
            "body": body,
            "attributes": {"MessageGroupId": "g" * 64, "MessageDeduplicationId": "d" * 36},
            "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:dat-prod-file-send-requests.fifo",
        }
    ]
    return len(json.dumps(record, separators=(",", ":")).encode())


def _items_at_the_byte_cap(key_char: str) -> list:
    """The largest selection of ``key_char`` keys the byte cap accepts.

    Args:
      key_char: The character every key is made of.

    Returns:
      The selection.

    Raises:
      None.
    """
    count = 0
    while (
        count + 1 <= config.SEND_MAX_ITEMS
        and _selection_bytes(count + 1, key_char) <= config.SEND_MAX_ITEM_BYTES
    ):
        count += 1
    return [{"kind": "folder", "key": key_char * _MAX_KEY_BYTES} for _ in range(count)]


def test_the_validated_state_stays_under_the_payload_limit():
    """The real bound: the byte cap plus a full recipient list, which is what rides together."""
    size = _worst_case_validated_state(config.SEND_MAX_ITEM_BYTES, config.SEND_MAX_RECIPIENTS)

    assert size < _STATE_PAYLOAD_LIMIT, (
        f"a worst-case validated state is {size} bytes, over the {_STATE_PAYLOAD_LIMIT}-byte "
        f"limit — and SPEC-166's Map throws States.DataLimitExceeded outside every Catch"
    )


def test_a_selection_at_the_byte_cap_can_actually_START_an_execution():
    """THE LINK THE FIRST TWO MODELS BOTH MISSED, in opposite ways.

    The first version measured the item COUNT against the state and ignored escaping. The
    second measured the serialised selection against the state and ignored that the Pipe
    escapes it AGAIN into the execution input. A cap that permits a request whose execution
    cannot start is the worst of the three: the user hears nothing, because the failure happens
    before any state exists to catch it.
    """
    for char in ("k", '"', _WORST_ESCAPE):
        record = _pipe_record(_items_at_the_byte_cap(char))

        assert record < _STATE_PAYLOAD_LIMIT, (
            f"a byte-cap selection of {char!r} keys reaches the Pipe as a {record}-byte "
            f"execution input, over the {_STATE_PAYLOAD_LIMIT}-byte limit"
        )


def test_the_failure_state_carries_the_request_and_still_fits():
    """The failure path reads the whole request back from $$.Execution.Input, so the recorded
    object is the record PLUS the error. If that breached, the notification would be lost on
    exactly the failures the state exists to report."""
    for char in ("k", '"'):
        recorded = _pipe_record(_items_at_the_byte_cap(char)) + 4 * 1024

        assert recorded < _STATE_PAYLOAD_LIMIT, f"failure state for {char!r} keys is {recorded}"


def test_the_byte_cap_leaves_room_for_the_fields_spec_165_adds():
    """A bound with no headroom is a bound the next spec silently breaks. SPEC-165 resolves this
    same state, adding an expanded object count and a plan pointer."""
    used = _worst_case_validated_state(config.SEND_MAX_ITEM_BYTES, config.SEND_MAX_RECIPIENTS)

    assert _STATE_PAYLOAD_LIMIT - used > 16 * 1024


#: A long-but-ordinary key: a few nested folders and a descriptive filename. Not S3's 1024-byte
#: maximum, which is a pathological key nobody's browser produces — the point of separating the
#: two caps is that the byte one handles those.
_ORDINARY_KEY_BYTES = 200


def test_a_full_selection_of_ordinary_keys_is_not_refused_by_the_byte_cap():
    """The direction that keeps the two caps honest with each other. If the byte budget could
    not hold a full count-capped selection of ordinary keys, the count cap would be decoration
    and users would hit a limit nothing documents."""
    selection = [
        {"kind": "folder", "key": "k" * _ORDINARY_KEY_BYTES} for _ in range(config.SEND_MAX_ITEMS)
    ]
    ordinary = len(json.dumps(selection, separators=(",", ":")).encode())

    assert ordinary <= config.SEND_MAX_ITEM_BYTES, (
        f"{config.SEND_MAX_ITEMS} ordinary keys serialise to {ordinary} bytes, over the "
        f"{config.SEND_MAX_ITEM_BYTES}-byte budget — one of the two caps is wrong"
    )


def test_which_cap_binds_depends_on_the_keys_and_that_is_the_design():
    """Stated as an assertion because it is the thing a single cap could not express.

    At ordinary key lengths the COUNT binds — a user selecting a 201st file is told they
    selected too many. At S3's maximum key length the BYTES bind first, and the message says
    the selection is too large rather than miscounting. Neither cap is redundant.
    """
    assert _selection_bytes(config.SEND_MAX_ITEMS, "k") > config.SEND_MAX_ITEM_BYTES


def test_the_count_cap_alone_would_NOT_have_bounded_the_state():
    """The defect this pair of caps exists for, pinned so it cannot come back as one cap.

    At the worst legal escaping, the count cap permits a selection several times the payload
    limit. If this assertion ever fails, the count cap has become a real byte bound by
    accident — which would be fine, but the reasoning above would no longer be why.
    """
    escaped = _selection_bytes(config.SEND_MAX_ITEMS, _WORST_ESCAPE)

    assert escaped > _STATE_PAYLOAD_LIMIT, (
        f"{config.SEND_MAX_ITEMS} worst-escaped keys are {escaped} bytes"
    )


def test_the_byte_cap_holds_at_the_worst_legal_escaping():
    """The claim that matters: whatever the keys are made of, the cap is measured on the
    SERIALISED form, so a pathological key costs its real size and is refused earlier."""
    for char in ("k", '"', "\\", _WORST_ESCAPE):
        items = 1
        while _selection_bytes(items, char) <= config.SEND_MAX_ITEM_BYTES:
            items += 1
        largest_allowed = _selection_bytes(items - 1, char)

        assert (
            _worst_case_validated_state(largest_allowed, config.SEND_MAX_RECIPIENTS)
            < _STATE_PAYLOAD_LIMIT
        ), f"the byte cap does not hold for keys made of {char!r}"


def test_the_model_is_not_trivially_satisfied():
    """Guards the guard. A model that measured almost nothing would pass every test above at any
    cap at all, which is precisely how a bound comes to certify something it never checked.

    Measured on the PIPE RECORD rather than the state, because that is the binding link: the
    state at the cap is a comfortable ~104 KB and the record is ~200 KB, and a guard pointed at
    the roomy one would go quiet exactly when the tight one started to matter.
    """
    record = _pipe_record(_items_at_the_byte_cap('"'))

    assert record > _STATE_PAYLOAD_LIMIT // 2, (
        f"the modelled execution input is only {record} bytes — that is not a worst case, it "
        f"is an empty model wearing one"
    )


def test_a_failed_recipient_carrying_a_bounded_error_still_fits():
    """SPEC-166's guard Map records a per-recipient outcome, each failed item carrying the raw
    Step Functions error. That is the term that sank table-share's first recipient cap, so the
    recipient count is checked against it here, before the Map that will produce it exists."""
    records = [
        {
            "kind": "space",
            "name": "s" * 64,
            "error": {"Error": "TerminalError", "Cause": "x" * errors.MAX_DETAIL_CHARS},
        }
        for _ in range(config.SEND_MAX_RECIPIENTS)
    ]
    size = len(json.dumps(records, separators=(",", ":")).encode())

    assert size < _STATE_PAYLOAD_LIMIT, (
        f"{config.SEND_MAX_RECIPIENTS} refused recipients at the bounded Cause ceiling is "
        f"{size} bytes — the recipient cap and errors.MAX_DETAIL_CHARS have drifted apart"
    )


def test_the_item_cap_covers_a_realistic_selection():
    """The direction a purely technical bound forgets: a cap that is safe and unusable is still
    a defect. The file browser pages at 25 (LISTING_PAGE_SIZE), so the cap must comfortably
    clear a few full pages of select-all."""
    assert config.SEND_MAX_ITEMS >= 25 * 4


def test_nothing_here_reads_the_environment():
    """This module must not be able to fail at import. A shared layer's import-time failure
    surfaces at COLD START, where no test and no deploy can see it — PR #196's outage, and the
    reason every cap here is a literal rather than an env lookup."""
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fscommon", "config.py")
    with open(source) as handle:
        text = handle.read()

    assert "os.environ" not in text and "getenv" not in text and "_require" not in text


# ── SPEC-165: the expansion caps ─────────────────────────────────────────────

#: S3's page size for ListObjectsV2. The pagination boundary, and the unit the listing's cost
#: is counted in.
_S3_PAGE_SIZE = 1000

#: A pessimistic S3 round trip, chosen well above a warm same-region call (tens of ms). The
#: point of the timeout model is to survive a bad day, not to describe a good one.
_ROUND_TRIP_SECONDS = 0.2

#: A child execution's own cost — the StartExecution, the cold start and the poll — charged once
#: per ROUND of the Map's concurrency. Deliberately generous: it is the term a bytes-only model
#: drops entirely, and at 50,000 items in batches of 8 there are hundreds of rounds.
_CHILD_EXECUTION_OVERHEAD_SECONDS = 3

#: How much more a parsed JSON document costs in memory than its bytes. Items here are dominated
#: by two ~1 KB strings, so the true factor is nearer 1.3; 3 is the pessimistic direction, which
#: is the safe one for a bound.
_PARSED_OBJECT_OVERHEAD = 3


def _locals_text() -> str:
    """The file-send Terraform locals, as text.

    Read as DATA rather than restated, for the reason the browser cap mirror is: two homes for
    one number is how a bound quietly stops matching the thing it bounds.
    """
    return (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra"
        / "modules"
        / "file-send"
        / "locals.tf"
    ).read_text()


def _verb_row(name: str):
    """One verb's configured timeout and memory, from the Terraform locals."""
    row = re.search(
        rf'"{name}"\s*=\s*\{{[^}}]*timeout\s*=\s*(\d+)[^}}]*memory\s*=\s*(\d+)', _locals_text()
    )
    assert row, f"{name} is no longer in the file-send locals, or its row changed shape"
    return int(row.group(1)), int(row.group(2))


def _verb_timeout(name: str) -> int:
    """One verb's configured timeout, in seconds."""
    return _verb_row(name)[0]


def _verb_memory(name: str) -> int:
    """One verb's configured memory, in MB."""
    return _verb_row(name)[1]


def _machine_timeout_seconds() -> int:
    """The state machine's own top-level TimeoutSeconds, from the Terraform locals.

    Every cap that bounds the RUN is measured against this, and it lives in Terraform — so it is
    read rather than restated. A ceiling raised in one place and asserted in another is how a cap
    comes to certify something it never checked.
    """
    found = re.search(r"state_machine_timeout_seconds\s*=\s*(\d+)", _locals_text())
    assert found, "the file-send machine has no top-level TimeoutSeconds in its locals"
    return int(found.group(1))


def _guard_map_concurrency() -> int:
    """The guard Map's fan-out, from the Terraform locals."""
    found = re.search(r"guard_map_max_concurrency\s*=\s*(\d+)", _locals_text())
    assert found, "the guard Map's concurrency is no longer a named local"
    return int(found.group(1))


def _transfer_item_bytes() -> int:
    """One manifest line at S3's worst-case key length, serialised.

    Pessimistic in a way real items cannot be: the destination key is derived FROM the source
    key, so both cannot independently be 1024 bytes. Over-counting is the safe direction.
    """
    item = {
        "recipient": "r" * 63,
        "kind": "space",
        "srcBucket": "b" * 63,
        "srcKey": "s" * _MAX_KEY_BYTES,
        "destBucket": "d" * 63,
        "destKey": "x" * _MAX_KEY_BYTES,
        "size": 10 * 1024**3,
    }
    return len(json.dumps(item, separators=(",", ":")).encode())


def _verb_sizing():
    """inspect-source's configured timeout and memory, read from the Terraform locals.

    Read as DATA rather than restated, for the reason the browser cap mirror is: two homes for
    one number is how a bound quietly stops matching the thing it bounds. The cap below is
    meaningless without the memory it is measured against, and the memory lives in Terraform.
    """
    locals_tf = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra"
        / "modules"
        / "file-send"
        / "locals.tf"
    ).read_text()
    row = re.search(
        r'"inspect-source"\s*=\s*\{[^}]*timeout\s*=\s*(\d+)[^}]*memory\s*=\s*(\d+)', locals_tf
    )
    assert row, "inspect-source is no longer in the file-send locals, or its row changed shape"
    return int(row.group(1)), int(row.group(2))


def _plan_entry_bytes() -> int:
    """One copy-plan entry at S3's worst-case key length, serialised.

    Deliberately pessimistic in a way real keys cannot be: ``relKey`` is a SUFFIX of ``srcKey``,
    so the two can never both be 1024 bytes. Over-counting is the safe direction for a bound.
    """
    entry = {
        "item": "i" * 255,
        "relKey": "r" * _MAX_KEY_BYTES,
        "srcKey": "s" * _MAX_KEY_BYTES,
        "size": 10 * 1024**3,
    }
    return len(json.dumps(entry, separators=(",", ":")).encode())


def test_the_worst_case_copy_plan_fits_in_the_verbs_memory():
    """WHAT SIZES SEND_MAX_OBJECTS, computed rather than asserted.

    The verb holds the whole plan as a list of dicts, serialises it to a string and encodes that
    to bytes — three live copies at the moment of the write. Half the configured memory is left
    for the interpreter, boto3 and its response buffers, which is not a rounding allowance: a
    cold Lambda with botocore loaded is already tens of megabytes before the first object.
    """
    _timeout, memory_mb = _verb_sizing()
    plan_bytes = _plan_entry_bytes() * config.SEND_MAX_OBJECTS
    peak = 3 * plan_bytes

    assert peak < (memory_mb * 1024**2) / 2, (
        f"a worst-case plan of {config.SEND_MAX_OBJECTS} objects is {plan_bytes / 1024**2:.0f} MB "
        f"and peaks near {peak / 1024**2:.0f} MB against {memory_mb} MB — raise the memory in "
        f"infra/modules/file-send/locals.tf or lower the cap"
    )


def test_the_worst_case_listing_fits_in_the_verbs_timeout():
    """The other half of the sizing, and it is NOT the pagination.

    The tempting model counts ListObjectsV2 pages — 20 at the cap, a couple of seconds. The term
    it misses is that a ``file`` item costs its own HeadObject and they run SERIALLY, so a
    selection of 200 files is 200 round trips before a single folder is walked. The bound is
    therefore per-ITEM plus per-PAGE, and the item half dominates.
    """
    timeout, _memory = _verb_sizing()
    pages = -(-config.SEND_MAX_OBJECTS // _S3_PAGE_SIZE)
    round_trips = config.SEND_MAX_ITEMS + pages
    seconds = round_trips * _ROUND_TRIP_SECONDS

    assert seconds < timeout / 2, (
        f"{round_trips} worst-case round trips is {seconds:.0f}s against a {timeout}s timeout"
    )


def test_the_item_half_of_the_timeout_model_is_the_dominant_one():
    """The term a page-counting model drops, asserted where it can actually fail.

    ``pages < SEND_MAX_ITEMS`` was the first version and it is arithmetic on two constants —
    trivially true, and true at any caps at all. The claim worth holding is that dropping the
    HEAD term changes the ANSWER: a page-only model must come out materially cheaper than the
    real one, or a future reader is entitled to simplify the model back and lose nothing.
    """
    pages = -(-config.SEND_MAX_OBJECTS // _S3_PAGE_SIZE)
    page_only = pages * _ROUND_TRIP_SECONDS
    real = (config.SEND_MAX_ITEMS + pages) * _ROUND_TRIP_SECONDS

    assert real > 5 * page_only, (
        f"a page-only model gives {page_only:.0f}s and the real one {real:.0f}s — close enough "
        f"that the HeadObject term is no longer what sizes the timeout, so re-derive it"
    )


def test_a_full_size_selection_copies_inside_the_engines_ceiling():
    """The makespan model for SEND_MAX_TOTAL_BYTES, at the rate the engine actually delivers.

    ``cpcommon.transfer`` schedules a whole object per worker and part-copies serially inside
    one, so the denominator is a MAKESPAN — ``MAP_MAX_CONCURRENCY x
    CONSERVATIVE_STREAM_BYTES_PER_SECOND``, 500 MB/s — not the ~4 GB/s an aggregate-bandwidth
    reading of the same constants suggests. Table-share found that mistake twice, in review
    rounds, after it read as satisfied both times.

    500 MB/s is reachable only when the bytes are SPREAD over the worker pool, which is why the
    per-object cap below is not optional: one object is one worker at 25 MB/s whatever this
    figure says.
    """
    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    seconds = config.SEND_MAX_TOTAL_BYTES / rate

    assert seconds < _machine_timeout_seconds() / 2, (
        f"one distributed copy of a cap-size selection is {seconds:.0f}s at "
        f"{rate / 1000**2:.0f} MB/s, against the machine's own ceiling"
    )


def test_a_cap_size_object_copies_inside_the_batch_verbs_own_timeout():
    """WHAT SIZES SEND_MAX_OBJECT_BYTES, and note it is NOT the machine's ceiling.

    A batch is exactly one round of the worker pool (``MAX_ITEMS_PER_BATCH ==
    COPY_CONCURRENCY``), so a batch costs its slowest object — and that object is copied by ONE
    worker whose multipart loop is serial. The budget it has to fit inside is therefore
    ``COPY_TIMEOUT_SECONDS``, the batch verb's own Lambda timeout, not the three hours the run
    has. Two thirds of it, so a retry of a slow-but-not-hopeless batch still fits.
    """
    makespan = config.SEND_MAX_OBJECT_BYTES / transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND

    assert makespan < transfer_config.COPY_TIMEOUT_SECONDS * 2 / 3, (
        f"a {config.SEND_MAX_OBJECT_BYTES / 1024**3:,.0f} GiB object takes {makespan:,.0f}s at "
        f"{transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND / 1e6:.0f} MB/s per stream, "
        f"against copy-objects' {transfer_config.COPY_TIMEOUT_SECONDS}s timeout"
    )


def test_the_per_object_cap_is_what_closes_the_single_object_hole():
    """The gap SPEC-165 recorded as owed, asserted as CLOSED rather than as arithmetic.

    Without a per-object cap the worst legal case at ``SEND_MAX_TOTAL_BYTES`` was one 1 TiB
    object on one worker — 43,980s, four times the machine ceiling — while every distributed
    model read as satisfied. The claim worth holding is that the cap changes that ANSWER: the
    largest single object this plane accepts must now fit the ceiling with room to spare, and
    the uncapped case must still not.
    """
    rate = transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    capped = config.SEND_MAX_OBJECT_BYTES / rate
    uncapped = config.SEND_MAX_TOTAL_BYTES / rate

    assert capped < _machine_timeout_seconds() / 2
    assert uncapped > 4 * _machine_timeout_seconds(), (
        "a single source-cap-size object now copies inside the ceiling, so the per-object cap "
        "may no longer be load-bearing — re-check before touching it"
    )


def test_the_worst_case_manifest_fits_in_the_verbs_memory():
    """WHAT SIZES SEND_MAX_TRANSFER_ITEMS, computed against the memory in Terraform.

    The builder holds the item list, its serialised form and the encoded bytes at once; the
    collector parses an export carrying every batch's input back again, and a parsed dict of
    long strings costs more than its JSON bytes. Half the configured memory is left for the
    interpreter and botocore, which a cold Lambda has already spent tens of megabytes on.
    """
    manifest_mb = _verb_memory("build-transfer-manifest")
    collector_mb = _verb_memory("collect-transfer-results")
    manifest_bytes = _transfer_item_bytes() * config.SEND_MAX_TRANSFER_ITEMS

    assert 3 * manifest_bytes < (manifest_mb * 1024**2) / 2, (
        f"a worst-case manifest of {config.SEND_MAX_TRANSFER_ITEMS:,} items is "
        f"{manifest_bytes / 1024**2:.0f} MB and peaks near {3 * manifest_bytes / 1024**2:.0f} MB "
        f"against {manifest_mb} MB — raise the memory in infra/modules/file-send/locals.tf or "
        f"lower the cap"
    )
    assert _PARSED_OBJECT_OVERHEAD * manifest_bytes < (collector_mb * 1024**2) / 2, (
        f"the collector cannot parse a {manifest_bytes / 1024**2:.0f} MB export in "
        f"{collector_mb} MB"
    )


def test_the_transfer_item_cap_is_a_bound_neither_source_cap_could_express():
    """20,000 objects is legal and so are 50 recipients, and every manifest item is a full copy.
    The claim is that the product cap BITES before those two do — otherwise it is decoration."""
    unbounded_product = config.SEND_MAX_OBJECTS * config.SEND_MAX_RECIPIENTS

    assert unbounded_product > config.SEND_MAX_TRANSFER_ITEMS, (
        "the per-source caps now imply the transfer cap, so it no longer bounds anything"
    )


def test_the_whole_run_fits_the_machines_ceiling():
    """WHAT SIZES SEND_MAX_TRANSFER_BYTES, and the one place every term is added up.

    The copy is not the only thing inside the ceiling, and a model that only counted it would be
    the aggregate-bandwidth mistake wearing a different hat. Four terms, each read from the
    locals or the engine's constants rather than restated here:

    * the transfer itself, at the MAKESPAN rate (500 MB/s), not the aggregate;
    * the per-child overhead of ``SEND_MAX_TRANSFER_ITEMS`` in batches of ``MAX_ITEMS_PER_BATCH``
      at ``MAP_MAX_CONCURRENCY`` — a real term at 50,000 items, and one bytes alone cannot see;
    * the guard Map, which is ``ceil(recipients / its concurrency)`` rounds of a whole verb
      timeout;
    * the four serial verbs either side of it.

    They are summed rather than checked one at a time because they all happen in the same run.
    """
    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    copying = config.SEND_MAX_TRANSFER_BYTES / rate

    batches = -(-config.SEND_MAX_TRANSFER_ITEMS // transfer_config.MAX_ITEMS_PER_BATCH)
    rounds = -(-batches // transfer_config.MAP_MAX_CONCURRENCY)
    child_overhead = rounds * _CHILD_EXECUTION_OVERHEAD_SECONDS

    guard_rounds = -(-config.SEND_MAX_RECIPIENTS // _guard_map_concurrency())
    guarding = guard_rounds * _verb_timeout("check-target-absent")

    serial = sum(
        _verb_timeout(verb)
        for verb in (
            "validate-authorize",
            "inspect-source",
            "build-transfer-manifest",
            "collect-transfer-results",
        )
    )

    worst = copying + child_overhead + guarding + serial

    assert worst < _machine_timeout_seconds(), (
        f"the worst legal run is {worst:,.0f}s — copy {copying:,.0f}s + child overhead "
        f"{child_overhead:,.0f}s + guard {guarding:,.0f}s + serial verbs {serial:,.0f}s — "
        f"against a {_machine_timeout_seconds():,}s ceiling. Lower a cap or raise the timeout "
        f"in infra/modules/file-send/locals.tf, and do not raise the rate without evidence"
    )


def test_the_transfer_byte_cap_is_measured_on_the_product_and_not_the_source():
    """The distinction table-share's own timeout was short by a factor of 50 for. Asserted as a
    relationship: the transfer cap must exceed one source, or a single-recipient send at the
    source cap would be refused — and it must be beneath the unbounded product, or it bounds
    nothing."""
    assert config.SEND_MAX_TOTAL_BYTES < config.SEND_MAX_TRANSFER_BYTES
    assert config.SEND_MAX_TRANSFER_BYTES < config.SEND_MAX_TOTAL_BYTES * config.SEND_MAX_RECIPIENTS


def test_the_rendered_asl_carries_the_engines_own_batch_numbers():
    """Terraform cannot import Python, so the ASL's ItemBatcher and MaxConcurrency are literals
    fed from locals.tf. Two homes for one number is how a batch silently grows past the limit it
    was sized against, so the locals are read back and compared with the constants."""
    text = _locals_text()

    assert re.search(
        rf"transfer_max_items_per_batch\s*=\s*{transfer_config.MAX_ITEMS_PER_BATCH}\b", text
    )
    assert re.search(
        rf"transfer_map_max_concurrency\s*=\s*{transfer_config.MAP_MAX_CONCURRENCY}\b", text
    )


def test_the_object_cap_is_a_bound_the_item_cap_could_not_express():
    """The two-quantities argument again, one level down, and asserted where it can fail.

    ``SEND_MAX_OBJECTS > SEND_MAX_ITEMS`` was the first version — arithmetic on two constants.
    The real claim is that the item cap does not IMPLY the object cap: one selected folder can
    hold any number of objects, so even a single item can breach it.
    """
    assert config.SEND_MAX_OBJECTS > 1, (
        "the object cap is reachable by a single selected folder, which is the whole reason the "
        "item cap cannot stand in for it"
    )
    assert _plan_entry_bytes() * config.SEND_MAX_OBJECTS > config.SEND_MAX_ITEM_BYTES


def test_the_plan_could_never_have_ridden_on_the_state():
    """Why it is a pointer, computed. Not "it was close to the limit" — at these caps the object
    list is two orders of magnitude over it, so inline was never a design that could have been
    tuned into working."""
    plan_bytes = _plan_entry_bytes() * config.SEND_MAX_OBJECTS

    assert plan_bytes > 100 * _STATE_PAYLOAD_LIMIT


def test_the_browser_mirrors_the_same_caps():
    """Two homes for one number is how a bound quietly stops matching the thing it bounds.

    The producer cannot import Python, so ``fileSend.service.ts`` restates both caps — and a
    restatement nobody checks is worse than no guard at all, because the wrong number reads as
    deliberate. Read as data from the TypeScript source, the way the ASL's batch size is held
    against ``cpcommon.transfer.config``.
    """
    service = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "portal"
        / "src"
        / "features"
        / "file-send"
        / "fileSend.service.ts"
    ).read_text()

    declared = dict(re.findall(r"const (SEND_MAX_ITEMS|SEND_MAX_ITEM_BYTES) = ([^;]+);", service))

    assert declared, "the producer no longer declares the caps under the expected names"
    assert eval(declared["SEND_MAX_ITEMS"]) == config.SEND_MAX_ITEMS  # noqa: S307
    assert eval(declared["SEND_MAX_ITEM_BYTES"]) == config.SEND_MAX_ITEM_BYTES  # noqa: S307
