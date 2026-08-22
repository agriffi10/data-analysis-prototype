"""Unit tests for the file-ops check-destinations Lambda.

The guard's whole value is that it fails closed and refuses only what it must. So the cases below
are the ones where the wrong implementation still looks right: an ambiguous head read as clear, a
merge into an existing folder read as a collision, an overwrite that stopped early, and a run where
every item conflicts.

Runnable under pytest or directly: python3 test_file_ops_check_destinations.py.
"""

import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_check_destinations as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from focommon import config, notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"
_SUBMITTED = "2026-08-20T10:00:00+00:00"
_BEFORE = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

#: A head that answers without the field the overwrite predicate turns on. S3 always sends one, so
#: this is the fail-closed branch rather than a case the API produces.
_NO_LAST_MODIFIED = object()
_AFTER = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)


class _S3Error(Exception):
    """A botocore-shaped fault, so the code under test classifies it the way it would in Lambda."""

    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    """Serves the plan from the admin bucket and answers heads from a per-key table."""

    def __init__(self, plan, destinations):
        self._plan = plan
        self._destinations = destinations
        self.heads = []

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(json.dumps(self._plan).encode())}

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        answer = self._destinations.get(Key)
        if answer is None:
            raise _S3Error("NoSuchKey", 404)
        if isinstance(answer, Exception):
            raise answer
        if answer is _NO_LAST_MODIFIED:
            return {"ContentLength": 1}
        return {"ContentLength": 1, "LastModified": answer}


def _plan_body(items, on_conflict="refuse"):
    objects = sum(len(item["objects"]) for item in items)
    return {
        "requestId": "req-1",
        "operation": "move",
        "submittedAt": _SUBMITTED,
        "onConflict": on_conflict,
        "actor": "alice",
        "executionArn": _EXECUTION,
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": {"bucket": "user-bkt", "prefix": "alice/out/"},
        "items": items,
        "itemCount": len(items),
        "objectCount": objects,
        "totalBytes": objects,
    }


def _item(item_key, label, dest_keys):
    return {
        "itemKey": item_key,
        "label": label,
        "kind": "folder",
        "targetName": label,
        "objects": [
            {
                "srcBucket": "user-bkt",
                "srcKey": f"{item_key}{n}",
                "relKey": str(n),
                "size": 1,
                "etag": '"e"',
                "destBucket": "user-bkt",
                "destKey": key,
            }
            for n, key in enumerate(dest_keys)
        ],
        "objectCount": len(dest_keys),
        "totalBytes": len(dest_keys),
    }


def _event(outcomes=None, on_conflict="refuse"):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": "move",
        "execution": {"arn": _EXECUTION},
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": {"bucket": "user-bkt", "root": "alice/", "prefix": "alice/out/"},
        "onConflict": on_conflict,
        "submittedAt": _SUBMITTED,
        "planKey": "file-ops/req-1/plan.json",
        "objectCount": None,
        "outcomes": outcomes or [],
    }


def _install(items, destinations, on_conflict="refuse"):
    plan = _plan_body(items, on_conflict)
    fake = _FakeS3(plan, destinations)
    clients._s3 = fake
    return fake


def _outcome(result, item_key):
    return next(o for o in result["outcomes"] if o["itemKey"] == item_key)


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    """The failure path enqueues a notification; these tests are about the verdict."""
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── The verdict ──────────────────────────────────────────────────────────────


def test_a_clear_item_is_cleared_and_every_key_was_actually_checked():
    """The ordinary case costs a full sweep: there is nothing to stop early on, which is what the
    guard's timeout is sized for."""
    fake = _install([_item("alice/reports/", "reports", ["alice/out/reports/a", "alice/out/reports/b"])], {})

    result = m._check_destinations(_event())

    assert _outcome(result, "alice/reports/")["outcome"] == "cleared"
    # Sorted, because the heads are appended from inside the worker pool: the ORDER they land in is
    # the scheduler's, and only `pool.map`'s results are ordered. What this asserts is coverage.
    assert sorted(fake.heads) == ["alice/out/reports/a", "alice/out/reports/b"]
    assert result["checkedCount"] == 2


def test_one_item_conflicting_leaves_every_other_item_alone():
    """The per-item model, and the whole difference from every other plane's guard: five folders
    selected and one colliding is not a reason to do nothing about the other four."""
    _install(
        [
            _item("alice/a/", "a", ["alice/out/a/x"]),
            _item("alice/b/", "b", ["alice/out/b/x"]),
        ],
        {"alice/out/b/x": _BEFORE},
    )

    result = m._check_destinations(_event())

    assert _outcome(result, "alice/a/")["outcome"] == "cleared"
    assert _outcome(result, "alice/b/")["outcome"] == "conflict"
    assert _outcome(result, "alice/b/")["reason"] == "destination_occupied"


def test_when_EVERY_item_conflicts_the_run_still_returns_normally():
    """Asserted by naming what came back rather than by asserting a branch is absent: the whole
    request is not a failure, and each item appears with its own outcome."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"]), _item("alice/b/", "b", ["alice/out/b/x"])],
        {"alice/out/a/x": _BEFORE, "alice/out/b/x": _BEFORE},
    )

    result = m._check_destinations(_event())

    assert [o["outcome"] for o in result["outcomes"]] == ["conflict", "conflict"]
    assert result["checkedCount"] == 2


def test_merging_into_an_existing_folder_is_NOT_a_conflict():
    """The collision unit is the derived destination KEY, not the destination subtree. Copying
    ``reports/`` into ``out/`` while ``out/reports/notes.txt`` exists is legal today and stays
    legal — the stricter test would remove a shipped capability."""
    _install(
        [_item("alice/reports/", "reports", ["alice/out/reports/a.csv"])],
        {"alice/out/reports/notes.txt": _BEFORE},
    )

    result = m._check_destinations(_event())

    assert _outcome(result, "alice/reports/")["outcome"] == "cleared"


# ── Failing closed ───────────────────────────────────────────────────────────


def test_a_403_counts_as_OCCUPIED():
    """A key this role cannot head is one it must not overwrite. Reading an ambiguous answer as
    "clear" is the one mistake here that ends in data loss."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _S3Error("AccessDenied", 403)},
    )

    result = m._check_destinations(_event())

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


@pytest.mark.parametrize("on_conflict", ["refuse", "overwrite"])
@pytest.mark.parametrize("fault", [_S3Error("AccessDenied", 403), _S3Error("InvalidRequest", 400)])
def test_an_unreadable_destination_conflicts_the_item_in_BOTH_modes(fault, on_conflict):
    """Only a proven 404 clears a key. Everything else — a 403, a malformed request, a KMS refusal —
    is an answer about what could be READ, and "an existing object" must never be read as "the ones
    we could head". Under ``overwrite`` the predicate is not even reached: there is no
    ``LastModified`` to compare, so the item conflicts before the comparison rather than by failing
    it, which is the one difference between this and an ordinary collision."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": fault},
        on_conflict=on_conflict,
    )

    result = m._check_destinations(_event(on_conflict=on_conflict))

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


def test_a_destination_with_no_LastModified_conflicts_under_OVERWRITE():
    """S3 always returns one; a response that did not would leave the predicate with nothing to
    compare, and the fallback has to be the occupied one. This is the fail-closed branch, and it is
    unreachable through the API on purpose — which is exactly why it needs a test."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _NO_LAST_MODIFIED},
        on_conflict="overwrite",
    )

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


def test_a_naive_LastModified_is_compared_as_UTC_rather_than_raising():
    """Comparing an aware instant with a naive one is a ``TypeError``, raised inside a worker while
    the guard is deciding whether to overwrite somebody's file."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": datetime(2026, 8, 20, 9, 0)},  # noqa: DTZ001 - naive IS the case
        on_conflict="overwrite",
    )

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "cleared"


@pytest.mark.parametrize("value", [None, "not-an-instant"])
def test_an_OVERWRITE_whose_plan_names_no_usable_instant_refuses_the_request(value):
    """Degrading to refuse semantics would apply a rule the user did not choose, and — worse — would
    take the short-circuit that overwrite must never take, reporting a partial sample as though the
    sweep had finished."""
    fake = _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])], {}, on_conflict="overwrite"
    )
    fake._plan["submittedAt"] = value

    with pytest.raises(TerminalError) as err:
        m._check_destinations(_event(on_conflict="overwrite"))

    assert err.value.reason == "plan_unreadable"


def test_a_throttle_retries_the_whole_verb_rather_than_clearing_anything():
    """A guard that cannot see the destination must retry and then fail its own state."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _S3Error("SlowDown", 503)},
    )

    with pytest.raises(TransientError):
        m._check_destinations(_event())


# ── The overwrite predicate ──────────────────────────────────────────────────


def test_an_object_older_than_the_submission_may_be_overwritten():
    """It is the object the user was looking at when they confirmed."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _BEFORE},
        on_conflict="overwrite",
    )

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "cleared"


def test_an_object_NEWER_than_the_submission_conflicts_the_item():
    """The user never saw it, so their confirmation cannot cover it."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _AFTER},
        on_conflict="overwrite",
    )

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


def test_overwrite_CANNOT_short_circuit():
    """A newer object anywhere in the item's key set refuses it, so the whole set has to be checked.
    A shared early exit would silently make ``overwrite`` sample-dependent — an item whose first few
    keys are old would be cleared while a newer file sat further down."""
    keys = [f"alice/out/a/{n:03d}" for n in range(40)]
    fake = _install(
        [_item("alice/a/", "a", keys)],
        dict.fromkeys(keys, _BEFORE) | {keys[-1]: _AFTER},
        on_conflict="overwrite",
    )

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"
    assert len(fake.heads) == len(keys)


def test_the_submission_time_is_read_from_the_PLAN_with_no_fallback_to_the_state():
    """The plan is the object that knows which request its destination keys were derived for, and
    taking the instant off the state instead is the substitution the supersession check exists to
    catch — which nothing else closes, because the plan's own identity check does not compare it.

    Asserted by making the two DISAGREE: the state says the request was submitted at 10:00 and the
    plan says 23:00, and the destination was modified at 11:00. Reading the state would conflict the
    item; reading the plan clears it.
    """
    fake = _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _AFTER},
        on_conflict="overwrite",
    )
    fake._plan["submittedAt"] = "2026-08-20T23:00:00+00:00"

    result = m._check_destinations(_event(on_conflict="overwrite"))

    assert _outcome(result, "alice/a/")["outcome"] == "cleared"


# ── The sample ───────────────────────────────────────────────────────────────


def test_the_refusal_names_a_bounded_sample_relative_to_the_space_root():
    """The user reads a path they recognise from the file browser, never an ``s3://`` URI."""
    keys = [f"alice/out/a/{n:03d}" for n in range(10)]
    _install([_item("alice/a/", "a", keys)], dict.fromkeys(keys, _BEFORE))

    record = _outcome(m._check_destinations(_event()), "alice/a/")

    assert len(record["sample"]) == config.FILE_OPS_CONFLICT_SAMPLE
    assert record["sample"][0] == "out/a/000"
    assert record["more"] is True


def test_the_short_circuit_survives_a_fixture_whose_collisions_INTERLEAVE():
    """The fixture is the test. Consecutive collisions fill the sample in the first round, so an
    implementation that never stopped early would pass — which is exactly why the equivalent test on
    the plane this was modelled on could not fail.
    """
    keys = [f"alice/out/a/{n:03d}" for n in range(80)]
    _install([_item("alice/a/", "a", keys)], {key: _BEFORE for n, key in enumerate(keys) if n % 17 == 0})
    fake = clients._s3

    record = _outcome(m._check_destinations(_event()), "alice/a/")

    assert len(record["sample"]) == config.FILE_OPS_CONFLICT_SAMPLE
    assert len(fake.heads) < len(keys), "the sweep did not stop once the sample was full"


def test_the_checked_count_is_what_was_HEADED_rather_than_what_was_planned():
    """The short-circuit means the two differ by orders of magnitude, and the plan's number is the
    one that is wrong: a 40-key item that collides on the first round would report forty checks
    after eight, onto a state a later verb reads and into the only operator view of the work done.
    """
    keys = [f"alice/out/a/{n:03d}" for n in range(40)]
    _install([_item("alice/a/", "a", keys)], dict.fromkeys(keys, _BEFORE))

    result = m._check_destinations(_event())

    assert result["checkedCount"] == config.FILE_OPS_HEAD_CONCURRENCY
    assert result["checkedCount"] < 40


def test_a_pathological_path_is_shortened_from_the_MIDDLE():
    """The caps admit keys no notification could render whole. Shortened from the middle so the
    basename — the part that identifies the file — survives."""
    key = "alice/out/a/" + ("x" * 900) + "/quarterly-report.csv"
    _install([_item("alice/a/", "a", [key])], {key: _BEFORE})

    sample = _outcome(m._check_destinations(_event()), "alice/a/")["sample"][0]

    assert len(sample) <= config.FILE_OPS_SAMPLE_PATH_CHARS
    assert sample.endswith("quarterly-report.csv")
    assert "..." in sample


# ── The plan and the outcome list ────────────────────────────────────────────


def test_the_guard_re_reads_the_plan_from_S3():
    """The derived destination keys exist only in the plan, so the guard cannot run off the state."""
    _install([_item("alice/a/", "a", ["alice/out/a/x"])], {})

    assert m._check_destinations(_event())["checkedCount"] == 1


def test_a_plan_from_another_execution_is_refused():
    """``plan_superseded`` applies to this read too, not only to the deletion's."""
    fake = _install([_item("alice/a/", "a", ["alice/out/a/x"])], {})
    fake._plan["executionArn"] = "arn:aws:states:us-east-1:1:execution:file-ops:run-2"

    with pytest.raises(TerminalError) as err:
        m._check_destinations(_event())

    assert err.value.reason == "plan_superseded"


def test_a_plan_short_of_the_count_it_records_is_refused():
    """A non-empty list is not a complete one, and a truncated plan is the shape that produces a
    copy which succeeds over a user told everything went well."""
    fake = _install([_item("alice/a/", "a", ["alice/out/a/x"])], {})
    fake._plan["objectCount"] = 9

    with pytest.raises(TerminalError) as err:
        m._check_destinations(_event())

    assert err.value.reason == "plan_unreadable"


def test_the_earlier_producers_outcomes_all_survive_this_verb():
    """The test the whole carry-forward rule exists for: one refusal, one empty item and one
    conflict, from three different verbs, all present at the end."""
    _install(
        [_item("alice/logs/", "logs", ["alice/out/logs/a.txt"])],
        {"alice/out/logs/a.txt": _BEFORE},
    )
    incoming = [
        {
            "itemKey": "alice/athenaresults/",
            "label": "athenaresults",
            "outcome": "protected",
            "reason": "results_folder_not_deletable",
        },
        {"itemKey": "alice/empty/", "label": "empty", "outcome": "source_empty", "reason": "source_empty"},
        {"itemKey": "alice/logs/", "label": "logs", "outcome": "cleared"},
    ]

    result = m._check_destinations(_event(outcomes=incoming))

    assert [(o["itemKey"], o["outcome"]) for o in result["outcomes"]] == [
        ("alice/athenaresults/", "protected"),
        ("alice/empty/", "source_empty"),
        ("alice/logs/", "conflict"),
    ]


def test_a_cleared_item_stays_where_it_was_in_the_list():
    """A person reads this list. The guard revising a provisional verdict must not reorder it."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"]), _item("alice/b/", "b", ["alice/out/b/x"])],
        {"alice/out/a/x": _BEFORE},
    )
    incoming = [
        {"itemKey": "alice/a/", "label": "a", "outcome": "cleared"},
        {"itemKey": "alice/b/", "label": "b", "outcome": "cleared"},
    ]

    result = m._check_destinations(_event(outcomes=incoming))

    assert [o["itemKey"] for o in result["outcomes"]] == ["alice/a/", "alice/b/"]


def test_the_handler_runs_the_whole_decorated_stack():
    """Every other test calls the orchestration directly, so without this the tracing and
    failure-notification decorators the handler's docstring argues about are never executed."""
    _install([_item("alice/a/", "a", ["alice/out/a/x"])], {})

    result = m.handler(_event(), None)

    assert _outcome(result, "alice/a/")["outcome"] == "cleared"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── The second pass ──────────────────────────────────────────────────────────


def _cleared(item_key, label="a"):
    return {"itemKey": item_key, "label": label, "outcome": "cleared"}


def test_the_second_pass_conflicts_under_its_OWN_reason_code():
    """"The guard has not run" and "the guard ran and found nothing" are indistinguishable inside a
    handler, so the two passes' collisions have to be tellable apart by the code alone."""
    items = [_item("alice/a/", "a", ["alice/out/a/0"])]
    _install(items, {"alice/out/a/0": _BEFORE})

    first = m._check_destinations({**_event(outcomes=[_cleared("alice/a/")]), "guardPass": 1})
    second = m._check_destinations({**_event(outcomes=[_cleared("alice/a/")]), "guardPass": 2})

    assert _outcome(first, "alice/a/")["reason"] == "destination_occupied"
    assert _outcome(second, "alice/a/")["reason"] == "destination_occupied_late"


def test_the_second_pass_does_NOT_re_head_an_item_the_first_pass_conflicted():
    """It may NARROW, never widen. The colliding object may have been deleted in between, and
    resurrecting the item would overwrite a terminal that was already decided — the rule this fleet
    states as "an earlier terminal is never overwritten".

    Asserted on the HEADS, not just the outcome: an implementation that re-headed and then discarded
    the answer would still be spending the destination's sweep twice.
    """
    items = [_item("alice/a/", "a", ["alice/out/a/0"]), _item("alice/b/", "b", ["alice/out/b/0"])]
    # `a` collided on pass one; nothing is in the way any more.
    fake = _install(items, {})
    arrived = [
        {
            "itemKey": "alice/a/",
            "label": "a",
            "outcome": "conflict",
            "reason": "destination_occupied",
            "sample": ["out/a/0"],
        },
        _cleared("alice/b/", "b"),
    ]

    result = m._check_destinations({**_event(outcomes=arrived), "guardPass": 2})

    assert fake.heads == ["alice/out/b/0"], "the second pass re-headed a decided item"
    assert _outcome(result, "alice/a/")["outcome"] == "conflict"
    assert _outcome(result, "alice/a/")["reason"] == "destination_occupied"
    assert _outcome(result, "alice/b/")["outcome"] == "cleared"


def test_the_second_pass_leaves_every_NON_cleared_outcome_exactly_as_it_arrived():
    """Not only conflicts: a protected location, a no-op and a missing source were all decided
    before this verb ever ran, and each must survive the sweep byte for byte."""
    items = [_item("alice/a/", "a", ["alice/out/a/0"])]
    _install(items, {})
    arrived = [
        {"itemKey": "alice/p/", "label": "p", "outcome": "protected", "reason": "archive_read_only"},
        {"itemKey": "alice/n/", "label": "n", "outcome": "noop"},
        {"itemKey": "alice/m/", "label": "m", "outcome": "source_missing", "reason": "source_missing"},
        _cleared("alice/a/"),
    ]

    result = m._check_destinations({**_event(outcomes=arrived), "guardPass": 2})

    for record in arrived[:3]:
        assert _outcome(result, record["itemKey"]) == record


def test_an_ABSENT_guardPass_is_the_FIRST_pass():
    """The seed arrives from the ASL. A verb invoked without it must behave as the pass that
    considers every planned item — reading a missing seed as "the second pass" would silently skip
    every item on a machine whose first guard had not yet run."""
    items = [_item("alice/a/", "a", ["alice/out/a/0"])]
    fake = _install(items, {})

    result = m._check_destinations(_event(outcomes=[]))

    assert fake.heads == ["alice/out/a/0"]
    assert _outcome(result, "alice/a/")["outcome"] == "cleared"


def test_the_FIRST_pass_judges_every_planned_item_even_with_no_outcomes_yet():
    """The first pass must not be filtered by the cleared set: the expansion's records arrive with
    it, but a first pass that trusted them would decide nothing on a state where they were absent."""
    items = [_item("alice/a/", "a", ["alice/out/a/0"]), _item("alice/b/", "b", ["alice/out/b/0"])]
    fake = _install(items, {})

    result = m._check_destinations({**_event(outcomes=[]), "guardPass": 1})

    assert sorted(fake.heads) == ["alice/out/a/0", "alice/out/b/0"]
    assert len(result["outcomes"]) == 2
