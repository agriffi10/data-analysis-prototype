"""The file-send caps are COMPUTED from what sizes them, never asserted as numbers.

A hard-coded cap number hides a wrong model, and this plane's siblings are the evidence: four
review rounds on SPEC-161 each found a table-share bound measured against the wrong quantity,
and every one of them read as satisfied until someone derived it independently. So the tests
here model the thing the cap protects and compute the ceiling; the constant only has to fit
under it.

**The quantity both file-send caps are spending is one 256 KB Step Functions state payload.**
``SEND_MAX_ITEMS`` and ``SEND_MAX_RECIPIENTS`` are not independent — the selection and the
recipient list ride on the same state — which is exactly the relationship a pair of
independently-chosen round numbers would hide. Breaching the limit raises
``States.DataLimitExceeded``, which is thrown OUTSIDE every Catch, so the sender is told
nothing at all.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon import errors
from fscommon import config

#: Step Functions' hard cap on a state payload.
_STATE_PAYLOAD_LIMIT = 256 * 1024

#: S3's maximum key length. The worst case, not a typical Hive key, because a cap sized
#: against the typical case is a cap that fails only for the user who has the deepest folders.
_MAX_KEY_BYTES = 1024


def _worst_case_validated_state(items: int, recipients: int) -> int:
    """Serialised size of validate-authorize's output at its worst allowed shape.

    Models what actually rides: the request id, the verified actor, the resolved source with
    every selected item at S3's longest legal key, and every recipient at the longest legal
    username carrying an ``invalid`` annotation.

    Args:
      items: Number of selected items.
      recipients: Number of recipients.

    Returns:
      The serialised byte length.

    Raises:
      None.
    """
    state = {
        "requestId": "0" * 36,
        "actor": {"username": "a" * 64},
        "source": {
            "bucket": "b" * 63,
            "root": ("r" * 63) + "/",
            "items": [{"kind": "folder", "key": "k" * _MAX_KEY_BYTES} for _ in range(items)],
        },
        "recipients": [
            {"kind": "space", "name": "s" * 64, "invalid": "unknown_space"} for _ in range(recipients)
        ],
    }
    return len(json.dumps(state, separators=(",", ":")).encode())


def test_the_validated_state_stays_under_the_payload_limit():
    """The two caps together, because together is how they are spent."""
    size = _worst_case_validated_state(config.SEND_MAX_ITEMS, config.SEND_MAX_RECIPIENTS)

    assert size < _STATE_PAYLOAD_LIMIT, (
        f"a worst-case validated state is {size} bytes, over the {_STATE_PAYLOAD_LIMIT}-byte "
        f"limit — States.DataLimitExceeded is thrown outside every Catch, so the sender would "
        f"be told nothing at all"
    )


def test_the_model_is_not_trivially_satisfied():
    """Guards the guard. A model that measured almost nothing would pass the test above at any
    cap at all, which is precisely how a bound comes to certify something it never checked."""
    used = _worst_case_validated_state(config.SEND_MAX_ITEMS, config.SEND_MAX_RECIPIENTS)

    assert used > _STATE_PAYLOAD_LIMIT // 2, (
        f"the modelled state is only {used} bytes — that is not a worst case, it is an empty "
        f"model wearing one"
    )


def _largest_fitting_item_count() -> int:
    """The most items that fit beside a full recipient list, computed rather than assumed.

    Args:
      None.

    Returns:
      The largest item count whose worst-case state stays under the payload limit.

    Raises:
      None.
    """
    count = 0
    while _worst_case_validated_state(count + 1, config.SEND_MAX_RECIPIENTS) < _STATE_PAYLOAD_LIMIT:
        count += 1
    return count


def test_the_item_cap_is_derived_from_the_ceiling_and_not_picked():
    """Both directions, because only one of them is usually checked.

    Under the ceiling, or the state breaches. But also NEAR it: a cap far below what the model
    allows is a number somebody chose, and the next person to wonder why it is 200 has nothing
    to read. The margin that IS deliberate is SPEC-165's — it resolves this same state, adding
    an expanded object count and a plan pointer — so the cap leaves room for a term that does
    not exist yet rather than spending the whole budget today.
    """
    ceiling = _largest_fitting_item_count()

    assert ceiling >= config.SEND_MAX_ITEMS, (
        f"SEND_MAX_ITEMS is {config.SEND_MAX_ITEMS} but only {ceiling} items fit beside "
        f"{config.SEND_MAX_RECIPIENTS} recipients"
    )
    assert ceiling * 0.7 <= config.SEND_MAX_ITEMS, (
        f"SEND_MAX_ITEMS is {config.SEND_MAX_ITEMS} against a computed ceiling of {ceiling} — "
        f"that is not a bound, it is a guess well inside one"
    )


def test_a_failed_recipient_carrying_a_bounded_error_still_fits():
    """SPEC-166's guard Map records a per-recipient outcome, each failed item carrying the raw
    Step Functions error. That is the term that sank table-share's first recipient cap, so the
    recipient count is checked against it here, before the Map that will produce it exists."""
    records = [
        {
            "kind": "space",
            "name": "s" * 64,
            "error": {
                "Error": "TerminalError",
                "Cause": "x" * errors.MAX_DETAIL_CHARS,
            },
        }
        for _ in range(config.SEND_MAX_RECIPIENTS)
    ]
    size = len(json.dumps(records, separators=(",", ":")).encode())

    assert size < _STATE_PAYLOAD_LIMIT, (
        f"{config.SEND_MAX_RECIPIENTS} refused recipients at the bounded Cause ceiling is "
        f"{size} bytes — the recipient cap and errors.MAX_DETAIL_CHARS have drifted apart"
    )


def test_the_item_cap_covers_a_realistic_selection():
    """The other direction, and the one a purely technical bound forgets: a cap that is safe
    and unusable is still a defect. The file browser pages at 25 (LISTING_PAGE_SIZE), so the
    cap must comfortably clear a few full pages of select-all."""
    assert config.SEND_MAX_ITEMS >= 25 * 4


def test_nothing_here_reads_the_environment():
    """This module must not be able to fail at import. A shared layer's import-time failure
    surfaces at COLD START, where no test and no deploy can see it — PR #196's outage, and the
    reason every cap here is a literal rather than an env lookup."""
    source = (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fscommon", "config.py")
    )
    with open(source) as handle:
        text = handle.read()

    assert "os.environ" not in text and "getenv" not in text and "_require" not in text
