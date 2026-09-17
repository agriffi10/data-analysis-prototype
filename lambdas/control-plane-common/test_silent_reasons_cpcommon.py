"""A reason nobody is told: valid everywhere without a plane registering it, and worded nowhere.

The suite imports every domain layer into one process, so a code one plane registers validates in
every other plane's tests too. A fresh interpreter holding only the shared layer is what a deployed
function that imports one domain actually has.
"""

import os
import subprocess
import sys

import pytest
from cpcommon import messages

_CPCOMMON = os.path.dirname(os.path.abspath(__file__))


def test_a_silent_reason_is_raisable_and_silent_with_only_the_shared_layer_imported():
    script = (
        "import sys; sys.path[:0] = [sys.argv[1]]\n"
        "from cpcommon.errors import TerminalError\n"
        "from cpcommon.messages import REQUEST_ID_REUSED\n"
        "from cpcommon.notify import is_silent\n"
        "err = TerminalError(REQUEST_ID_REUSED, 'held by another execution')\n"
        "assert is_silent(err.reason), err.reason\n"
    )

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script, _CPCOMMON],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert result.returncode == 0, result.stderr


def test_a_domain_that_words_a_silent_reason_is_refused_at_registration():
    """A sentence for a reason nobody is told reads, to the next person in the table, as what the
    user sees. The ordinary code beside it is the positive control: the same call registers it."""
    messages.register({"a_code_only_this_test_words": "a sentence."}, prefix="Test: ")

    with pytest.raises(ValueError, match="never told: \\['request_id_reused'\\]"):
        messages.register({messages.REQUEST_ID_REUSED: "a sentence nobody reads."}, prefix="Test: ")

    assert messages.is_known_reason("a_code_only_this_test_words")
