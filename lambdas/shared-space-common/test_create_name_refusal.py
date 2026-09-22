"""The catalog rule, applied where a shared space's name is chosen.

A live check on 2026-09-22 created the space ``live0922 odd`` through a signed-in
``POST /v1/enqueue/shared-space``. It provisioned, files uploaded into it and Athena answered
queries against it — and ``POST /v1/enqueue/table-build`` has been refused ever since, because the
API derives that plane's ``MessageGroupId`` from the raw database name and SQS's key grammar admits
no space character. Table share concatenates the same name, so a share out of it cannot be enqueued
either. Both are permanently unusable in a space the create path was happy to make.

The refusal these cases pin is on the CREATE alone. The space that prompted it still exists, and
refusing its name on a delete or a leave would strand it and the membership slot it holds.
"""

import auth
import pytest
from cpcommon.config import CATALOG_IDENTIFIER_RULE

_LIVE_CHECK_NAME = "live0922 odd"


def test_the_name_the_live_check_made_is_refused_and_the_sentence_says_what_to_do():
    """By code, and by a sentence that is neither the fallback nor a dead end.

    An unregistered code renders the generic TRANSFER sentence, which also quotes the space — so
    "it names the space" would pass with the wording table untouched. The two assertions that
    discriminate are that the sentence is about a CREATE and that it carries the rule, which is
    the only thing in it the requester can act on.
    """
    code, sentence = auth.create_refusal(_LIVE_CHECK_NAME)

    assert code == "CreateNameUnusable"
    assert f'"{_LIVE_CHECK_NAME}"' in sentence
    assert "create" in sentence
    assert CATALOG_IDENTIFIER_RULE in sentence


@pytest.mark.parametrize(
    ("space", "admitted"),
    [
        pytest.param("sales", True, id="ordinary"),
        pytest.param("s" * 63, True, id="sixty-three-characters"),
        pytest.param("live0922_odd", True, id="the-live-check-name-spelled-legally"),
        pytest.param(_LIVE_CHECK_NAME, False, id="space-character"),
        pytest.param("odd`tick", False, id="backtick"),
        pytest.param('odd"quote', False, id="double-quote"),
        pytest.param("*", False, id="wildcard"),
        pytest.param("Sales", False, id="uppercase"),
        pytest.param("s" * 64, False, id="sixty-four-characters"),
        pytest.param("sales\n", False, id="trailing-newline"),
        pytest.param("", False, id="empty"),
    ],
)
def test_the_create_admits_exactly_what_the_browser_dialog_admits(space, admitted):
    """The positive rows are the control: a refusal that took everything would satisfy the rest.

    ``*`` and the two quote characters are here because the name outlives the queue key — it
    becomes a principal tag value the portal role interpolates into a resource ARN, and a DDL
    identifier the catalog planes quote — so this rule is not the FIFO grammar written twice.
    """
    assert (auth.create_refusal(space) is None) is admitted


def test_a_name_that_is_not_a_string_is_refused_rather_than_raising_mid_decision():
    """A refusal reaches the requester; a raise here is caught by a state that names nobody."""
    assert auth.create_refusal(None)[0] == "CreateNameUnusable"
    assert auth.create_refusal(42)[0] == "CreateNameUnusable"
