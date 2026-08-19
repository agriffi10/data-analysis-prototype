"""``release`` cannot fail the request, whatever it is handed.

A separate file rather than an addition to ``test_table_lock.py``, because that suite is the
evidence that moving the protocol into ``cpcommon`` preserved behaviour and is deliberately left
as it was. What is asserted here is the contract that move nearly broke: composing the lock key as
an ARGUMENT to the shared release runs it before the etag check and outside the guard, so an
uncatalog-safe name raises out of a function whose docstring promises it raises nothing.

Why that matters more than its reachability suggests: ``release-refresh-lock`` runs on EVERY
terminal path of the machine, including the failure path, and carries no failure notifier because
it is not supposed to be able to produce one. A raise there is a task failure that replaces a
recorded user-facing failure with silence.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from cpcommon import clients, config
from tbcommon import table_lock

HOLDER = "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"


class FakeS3:
    """Records writes and never fails, so the only failure a test sees is the code's own."""

    def __init__(self):
        self.puts = []

    def get_object(self, Bucket, Key):
        raise KeyError(Key)

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": '"etag-1"'}


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(clients, "_s3", fake)
    monkeypatch.setattr(config, "ADMIN_BUCKET", "dat-prod-athena-admin", raising=False)
    return fake


@pytest.mark.parametrize("database,table", [("Alice", "sales"), ("alice", "Sales"), ("", "sales")])
def test_a_name_that_is_not_catalog_safe_never_raises_out_of_release(s3, database, table, captured_events):
    """The name is rejected, but as a recorded failure rather than an exception.

    Reachability is low — both the acquire and the release read the same request fields, and the
    acquire's own key check would have refused first — but that is a property of today's callers,
    not of this function, and the docstring's promise is unconditional.
    """
    table_lock.release(database, table, '"etag-1"')

    assert s3.puts == []
    assert captured_events.messages("refresh lock release failed")


def test_a_release_with_no_etag_is_a_no_op_even_for_an_unusable_name(s3, captured_events):
    """The etag check comes FIRST, which is what it did before the protocol moved: there is
    nothing to condition on, so there is nothing to report either."""
    table_lock.release("Alice", "sales", None)

    assert s3.puts == []
    assert captured_events.messages("refresh lock release failed") == []


def test_the_holder_refusal_still_names_which_lock(s3):
    """The shared guard words the message from a label the binding supplies. Without it every
    plane's locks report identically, and the string reaches CloudWatch and the decoded Step
    Functions cause, where "which lock" is the first thing a reader needs."""
    with pytest.raises(ValueError, match="refresh lock holder is not a usable identity"):
        table_lock.acquire("alice", "sales", "")

    assert s3.puts == []
