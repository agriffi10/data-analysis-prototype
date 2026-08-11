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
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon import errors
from fscommon import config

_STATE_PAYLOAD_LIMIT = 256 * 1024

_MAX_KEY_BYTES = 1024

_WORST_ESCAPE = "\x01"


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


def test_the_validated_state_stays_under_the_payload_limit():
    """The real bound: the byte cap plus a full recipient list, which is what rides together."""
    size = _worst_case_validated_state(config.SEND_MAX_ITEM_BYTES, config.SEND_MAX_RECIPIENTS)

    assert size < _STATE_PAYLOAD_LIMIT, (
        f"a worst-case validated state is {size} bytes, over the {_STATE_PAYLOAD_LIMIT}-byte "
        f"limit — and SPEC-166's Map throws States.DataLimitExceeded outside every Catch"
    )


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
    cap at all, which is precisely how a bound comes to certify something it never checked."""
    used = _worst_case_validated_state(config.SEND_MAX_ITEM_BYTES, config.SEND_MAX_RECIPIENTS)

    assert used > _STATE_PAYLOAD_LIMIT // 2, (
        f"the modelled state is only {used} bytes — that is not a worst case, it is an empty "
        f"model wearing one"
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
