"""The acquire verb: what it returns, and what it must not destroy.

Two properties dominate this file, and both fail silently rather than loudly:

  - it is called in a LOOP and the machine replaces the whole state with its result, so a verb
    that returned only its own fields would erase the request on the first pass;
  - a cross-space request takes BOTH locks or NEITHER, so a waiter never holds one across the
    ``Wait`` and the give-up path has nothing left to free.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_acquire_lock as v
from focommon.config import LOCK_MAX_ATTEMPTS

ARN = "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"


@pytest.fixture(autouse=True)
def calls(monkeypatch):
    """Records every acquire and release, and lets a test decide which claims succeed."""
    log = {"acquired": [], "released": [], "refuse": set()}

    def _acquire(bucket, root, holder):
        log["acquired"].append((bucket, root, holder))
        if (bucket, root) in log["refuse"]:
            return False, None
        return True, f'"etag-{len(log["acquired"])}"'

    def _release(bucket, root, etag):
        log["released"].append((bucket, root, etag))

    monkeypatch.setattr(v.lock, "acquire", _acquire)
    monkeypatch.setattr(v.lock, "release", _release)
    return log


def _event(destination=None, attempt=None, **extra):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": "move" if destination else "delete",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": destination,
        "outcomes": [{"itemKey": "alice/a/", "label": "a", "outcome": "noop"}],
        "execution": {"arn": ARN},
    }
    if attempt is not None:
        event["lock"] = {"attempt": attempt}
    event.update(extra)
    return event


def test_the_whole_event_is_ECHOED_not_replaced():
    """The machine threads the running object through the payload and takes the result as the
    entire new state. A verb returning only its own fields would destroy the request, the actor
    and the outcome list on the FIRST pass — before the Wait had even run — and every later state
    would then read paths that are gone."""
    result = v.handler(_event(), None)

    assert result["requestId"] == "req-1"
    assert result["actor"] == {"username": "alice"}
    assert result["outcomes"] == [{"itemKey": "alice/a/", "label": "a", "outcome": "noop"}]
    assert result["source"]["root"] == "alice/"


def test_a_single_space_takes_one_lock():
    result = v.handler(_event(), None)

    assert result["lock"]["acquired"] is True
    assert result["lock"]["attempt"] == 1
    assert len(result["lock"]["spaces"]) == 1


def test_a_cross_space_move_takes_TWO_locks(calls):
    result = v.handler(_event(destination={"bucket": "shared-bkt", "root": "sales/"}), None)

    assert result["lock"]["acquired"] is True
    assert len(result["lock"]["spaces"]) == 2
    assert len(calls["acquired"]) == 2


def test_a_destination_in_the_SAME_space_takes_one_lock(calls):
    """Claiming the same lock twice would take it, then re-claim it — and the re-claim rewrites
    the object, so the first tag would be dead and only the second could release. Correct by luck
    rather than by construction."""
    v.handler(_event(destination={"bucket": "user-bkt", "root": "alice/"}), None)

    assert len(calls["acquired"]) == 1


def test_the_two_locks_are_claimed_in_DIGEST_SORTED_order(calls):
    """Sorted by digest rather than by name, because the digest is what the key is built from.
    Unordered acquisition deadlocks when two requests cross in opposite directions."""
    forward = v.handler(_event(destination={"bucket": "shared-bkt", "root": "sales/"}), None)
    order_a = [(b, r) for b, r, _ in calls["acquired"]]

    calls["acquired"].clear()
    reverse = {
        **_event(destination={"bucket": "user-bkt", "root": "alice/"}),
        "source": {"bucket": "shared-bkt", "root": "sales/"},
    }
    v.handler(reverse, None)
    order_b = [(b, r) for b, r, _ in calls["acquired"]]

    assert forward["lock"]["acquired"] is True
    assert order_a == order_b


def test_losing_the_SECOND_lock_releases_the_first(calls):
    """The property that keeps a waiter from holding a lock across the Wait. Without it a
    cross-space request would wedge a space it never operated on for as long as it kept waiting.
    """
    # Refuse whichever space is claimed SECOND, computed from the digest order the verb uses —
    # refusing the first would leave nothing held, which is a different (and also correct) path.
    event = _event(destination={"bucket": "shared-bkt", "root": "sales/"})
    first, second = v._targets(event)
    calls["refuse"].add(second)

    result = v.handler(event, None)

    assert result["lock"]["acquired"] is False
    assert len(calls["released"]) == 1
    assert calls["released"][0][:2] == first


def test_losing_the_FIRST_lock_releases_nothing(calls):
    """The other half, so the rule above cannot be satisfied by a verb that releases
    indiscriminately: nothing was held, so nothing is freed."""
    event = _event(destination={"bucket": "shared-bkt", "root": "sales/"})
    first, _ = v._targets(event)
    calls["refuse"].add(first)

    v.handler(event, None)

    assert calls["released"] == []


def test_a_refused_claim_reports_not_yet_rather_than_raising(calls):
    calls["refuse"].add(("user-bkt", "alice/"))

    result = v.handler(_event(), None)

    assert result["lock"] == {"attempt": 1, "acquired": False, "exhausted": False, "etags": []}


def test_the_attempt_count_comes_from_the_verb_not_an_intrinsic(calls):
    """`States.MathAdd` raises an uncatchable error, so the machine cannot count. The verb reads
    its own prior count off the state and returns the increment."""
    calls["refuse"].add(("user-bkt", "alice/"))

    assert v.handler(_event(attempt=3), None)["lock"]["attempt"] == 4


def test_the_first_attempt_reads_no_prior_count(calls):
    """Nothing on the state carries a lock record yet, and reading an absent path is what the
    machine's own Choice is guarded against."""
    calls["refuse"].add(("user-bkt", "alice/"))

    assert v.handler(_event(), None)["lock"]["attempt"] == 1


def test_the_verb_decides_exhaustion_so_the_cap_has_ONE_home(calls):
    """The machine reads a boolean rather than comparing a number, so the attempt cap lives only
    in Python and cannot drift into Terraform."""
    calls["refuse"].add(("user-bkt", "alice/"))

    assert v.handler(_event(attempt=LOCK_MAX_ATTEMPTS - 1), None)["lock"]["exhausted"] is True
    assert v.handler(_event(attempt=LOCK_MAX_ATTEMPTS - 2), None)["lock"]["exhausted"] is False


def test_the_holder_is_the_EXECUTION_arn(calls):
    """A request id identifies the MESSAGE, and delivery is at-least-once — so a redelivered
    message runs a second execution carrying the same id, and a lock keyed on it would hand both
    of them the same claim with no refusal recorded."""
    v.handler(_event(), None)

    assert calls["acquired"][0][2] == ARN


def test_the_tags_are_replaced_on_every_attempt_never_accumulated(calls):
    """A re-claim rewrites the lock object and returns a NEW tag; releasing against an earlier one
    is a silent no-op that leaves the space locked until the staleness rule recovers it."""
    first = v.handler(_event(), None)
    second = v.handler({**_event(), "lock": first["lock"]}, None)

    assert len(second["lock"]["etags"]) == 1
    assert second["lock"]["etags"] != first["lock"]["etags"]
