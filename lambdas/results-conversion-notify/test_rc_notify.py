"""notify: one message, one link, and nothing it can do to fail a conversion that already ran."""

import os
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "results-conversion-common"))
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_notify as n


def _converted(**overrides):
    """The converted request, as the machine's Converted state hands it over."""
    state = {
        "requestId": "req-1",
        "username": "alice",
        "format": "parquet",
        "onConflict": "refuse",
        "queryExecutionId": "11111111-2222-4333-8444-555555555555",
        "resultsKey": "alice/athenaresults/exec.csv",
        "destination": {
            "bucket": "user-bkt",
            "key": "alice/out/q1.parquet",
            "prefix": "out/",
            "spaceKind": "personal",
            "spaceName": "alice",
        },
        "outcome": "converted",
        "reason": None,
        "rows": 1234,
        "bytes": 5678,
        "precisionNote": False,
        "tokens": None,
    }
    state.update(overrides)
    return state


@pytest.fixture
def sent(monkeypatch):
    """Captures what reaches the notifications queue."""
    captured = []
    monkeypatch.setattr(
        n.notify, "emit_notification", lambda user, message, **kw: captured.append((user, message, kw))
    )
    return captured


def test_one_message_names_the_file_the_format_and_the_rows_and_links_to_the_folder(sent):
    threaded = n.handler(_converted(), None)

    assert threaded == _converted(), "the state is threaded on unchanged"
    assert len(sent) == 1
    user, message, extras = sent[0]
    assert user == "alice"
    assert message == 'Saved 1,234 rows as Parquet to "q1.parquet".'
    assert extras["link"] == "/files?prefix=alice/out/"
    assert extras["payload"] == {"requestId": "req-1", "format": "parquet"}


def test_a_shared_space_link_names_the_space_first(sent):
    n.handler(
        _converted(
            destination={
                "bucket": "shared-bkt",
                "key": "finance/reports/q1.parquet",
                "prefix": "reports/",
                "spaceKind": "shared",
                "spaceName": "finance",
            }
        ),
        None,
    )

    assert sent[0][2]["link"] == "/files?space=finance&prefix=finance/reports/", (
        "the row's own feature gate tests for the literal '?space=', so a link with the prefix "
        "first lands the reader in their personal space while the message names a shared one"
    )


def test_the_precision_sentence_rides_only_on_the_file_that_earned_it(sent):
    n.handler(_converted(format="xlsx", precisionNote=True, rows=1), None)
    plain = sent[0][1]
    assert plain.startswith('Saved 1 row as Excel to "q1.parquet".')
    assert "may be rounded" in plain
    assert "column" not in plain and "1234" not in plain, (
        "the sentence says what happened and nothing about the data"
    )

    n.handler(_converted(format="xlsx", precisionNote=False), None)
    assert "may be rounded" not in sent[1][1]


def test_an_empty_result_set_is_reported_as_zero_rows(sent):
    n.handler(_converted(rows=0), None)
    assert sent[0][1] == 'Saved 0 rows as Parquet to "q1.parquet".'


def test_a_space_name_the_browser_could_not_resolve_produces_no_link_rather_than_a_broken_one(sent):
    n.handler(
        _converted(
            destination={
                "bucket": "shared-bkt",
                "key": "../etc/q1.parquet",
                "prefix": "",
                "spaceKind": "shared",
                "spaceName": "../etc",
            }
        ),
        None,
    )

    assert len(sent) == 1, "the message is still sent"
    assert sent[0][2]["link"] is None


def test_nothing_this_verb_does_can_fail_a_conversion_that_already_wrote(monkeypatch):
    """By the time this runs the object is in the user's space. A raise here would replace a
    completed conversion with a failed execution and tell the user their save did not happen."""

    def explode(*args, **kwargs):
        raise RuntimeError("the notifications queue is unreachable")

    monkeypatch.setattr(n.notify, "emit_notification", explode)
    assert n.handler(_converted(), None) == _converted()

    monkeypatch.setattr(n.messages, "success_message", explode)
    assert n.handler(_converted(), None) == _converted()

    assert n.handler(None, None) == {}
    assert n.handler({"username": "alice"}, None) == {"username": "alice"}


def test_the_verb_carries_no_failure_decorator():
    """`@notifies_on_failure` would report a failure of the notifier as a failure of the
    conversion — the opposite of what the state's own `Catch` is arranged to prevent."""
    import ast

    tree = ast.parse((_HERE / "rc_notify.py").read_text())
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "handler"
    )
    # Read from the decorator list rather than from the source text: the docstring explaining
    # this rule names the decorator, so a substring sweep would report the explanation as the
    # violation — and would keep passing if the explanation were deleted along with the rule.
    applied = [ast.unparse(decorator) for decorator in handler.decorator_list]
    assert applied == ["observability.traced('notify')"], (
        f"the notifier's decorator stack is {applied}; a failure decorator here would report a "
        "failure of the notification as a failure of the conversion"
    )
