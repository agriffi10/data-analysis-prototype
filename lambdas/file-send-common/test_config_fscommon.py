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

import pytest

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

#: The state-machine ceiling the IDENTICAL copy engine already runs under on table-share
#: (SPEC-161's top-level TimeoutSeconds). Named here as the target SPEC-166 must adopt when it
#: adds this plane's timeout — this cap is measured against it in advance rather than after.
_TRANSFER_CEILING_SECONDS = 10_800


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
    """The makespan model for SEND_MAX_TOTAL_BYTES — **conditional on a per-object cap**, which
    this plane does not have yet, so read the tripwire below with it.

    ``cpcommon.transfer`` schedules a whole object per worker and part-copies serially inside
    one, so the denominator is a MAKESPAN — ``MAP_MAX_CONCURRENCY x
    CONSERVATIVE_STREAM_BYTES_PER_SECOND``, 500 MB/s — not the ~4 GB/s an aggregate-bandwidth
    reading of the same constants suggests. Table-share found that mistake twice, in review
    rounds, after it read as satisfied both times.

    **What this figure assumes, and what it therefore does NOT certify.** 500 MB/s is only
    reachable when the bytes are spread over the whole worker pool. One object is copied by ONE
    worker at ``CONSERVATIVE_STREAM_BYTES_PER_SECOND``, so the true floor on the makespan is
    ``largest_object / 25 MB/s`` — and with no per-object cap the worst legal case at these caps
    is a single 1 TiB object at **43,980 s**, four times over the ceiling. That is not a defect
    in this cap; it is the per-object cap's absence, which SPEC-166 closes along with the
    ``TimeoutSeconds`` this compares against. Until then this test certifies the DISTRIBUTED
    case only.
    """
    rate = transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    seconds = config.SEND_MAX_TOTAL_BYTES / rate

    assert seconds < _TRANSFER_CEILING_SECONDS / 2, (
        f"one distributed copy of a cap-size selection is {seconds:.0f}s at "
        f"{rate / 1000**2:.0f} MB/s, against the {_TRANSFER_CEILING_SECONDS}s ceiling the same "
        f"engine runs under"
    )


def test_the_single_object_worst_case_is_the_reason_a_per_object_cap_is_owed():
    """The arithmetic the test above deliberately does not cover, kept as a number rather than a
    sentence so SPEC-166 inherits the size of the problem instead of re-deriving it.

    Table-share recorded this exact shape: while its total cap was 20 GiB the per-object bound
    was implicit, and raising the total to 1 TiB removed it with nothing replacing it. This
    plane starts at 1 TiB.
    """
    serial = config.SEND_MAX_TOTAL_BYTES / transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND

    assert serial > _TRANSFER_CEILING_SECONDS, (
        "a single cap-size object now copies inside the ceiling — the per-object cap SPEC-166 "
        "owes may no longer be load-bearing, so re-check before dropping it"
    )
    assert serial > 4 * _TRANSFER_CEILING_SECONDS


@pytest.mark.parametrize("cap", ["SEND_MAX_TRANSFER_BYTES", "SEND_MAX_OBJECT_BYTES"])
def test_the_caps_SPEC_166_owes_are_still_absent_and_that_is_deliberate(cap):
    """The honest statement of what SPEC-165 does not do, for BOTH deferred caps.

    ``SEND_MAX_TRANSFER_BYTES``: every recipient gets a full copy, so the transfer is
    ``recipients x total_bytes`` — 50 TiB at these caps. ``SEND_MAX_OBJECT_BYTES``: one object is
    one worker, so a single large object blows the makespan model above regardless of the total.
    Both are measured against a ``TimeoutSeconds`` this machine does not have.

    Written as a test so each gap is a recorded expectation rather than an oversight: when
    SPEC-166 adds one, this FAILS, and its replacement is the real bound. An earlier version
    covered only the first, which left the per-object gap living in prose — the weaker half of
    the pair, and the one whose absence undermines a test that reads as satisfied.
    """
    assert not hasattr(config, cap), (
        f"SPEC-166 added {cap} — replace this case with one computing it against the machine's "
        f"TimeoutSeconds, and update the SEND_MAX_TOTAL_BYTES docstring"
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
