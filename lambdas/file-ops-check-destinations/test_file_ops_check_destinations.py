"""Unit tests for the file-ops check-destinations Lambda.

The guard's whole value is that it fails closed and refuses only what it must. So the cases below
are the ones where the wrong implementation still looks right: an ambiguous head read as clear, a
merge into an existing folder read as a collision, an overwrite that stopped early, and a run where
every item conflicts.
"""

import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_check_destinations as m
import pytest
from cpcommon import clients
from focommon import messages, notify

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

    result = m.handler(_event(), None)

    assert _outcome(result, "alice/reports/")["outcome"] == "cleared"
    # Sorted, because the heads are appended from inside the worker pool: the ORDER they land in is
    # the scheduler's, and only `pool.map`'s results are ordered. What this asserts is coverage.
    assert sorted(fake.heads) == ["alice/out/reports/a", "alice/out/reports/b"]
    assert result["checkedCount"] == 2


# ── Failing closed ───────────────────────────────────────────────────────────


def test_a_403_counts_as_OCCUPIED():
    """A key this role cannot head is one it must not overwrite. Reading an ambiguous answer as
    "clear" is the one mistake here that ends in data loss."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _S3Error("AccessDenied", 403)},
    )

    result = m.handler(_event(), None)

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


# ── The overwrite predicate ──────────────────────────────────────────────────


def test_an_object_NEWER_than_the_submission_conflicts_the_item():
    """The user never saw it, so their confirmation cannot cover it."""
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _AFTER},
        on_conflict="overwrite",
    )

    result = m.handler(_event(on_conflict="overwrite"), None)

    assert _outcome(result, "alice/a/")["outcome"] == "conflict"


# ── The plan and the outcome list ────────────────────────────────────────────


# ── The second pass ──────────────────────────────────────────────────────────


def _cleared(item_key, label="a"):
    return {"itemKey": item_key, "label": label, "outcome": "cleared"}


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


# ── The sentence each answer earns ───────────────────────────────────────────

_REFUSE_SENTENCE = (
    "something is already in the way there. Please move what is there, or choose a different "
    "destination. Sending it again with overwrite turned on replaces what is there, and that "
    "cannot be undone."
)

_REFUSE_LATE_SENTENCE = (
    "something was put in the way there while this was being prepared. Please look at the "
    "destination, then try again. Sending it again with overwrite turned on replaces what is "
    "there, and that cannot be undone."
)

_OVERWRITE_SENTENCE = (
    "something was put there after this was sent, so what is there was left alone rather than "
    "replaced. Please look at the destination - sending it again now would replace what is there, "
    "and that cannot be undone."
)


@pytest.mark.parametrize(
    ("on_conflict", "guard_pass", "sentence"),
    [
        ("refuse", 1, _REFUSE_SENTENCE),
        ("refuse", 2, _REFUSE_LATE_SENTENCE),
        ("overwrite", 1, _OVERWRITE_SENTENCE),
        ("overwrite", 2, _OVERWRITE_SENTENCE),
    ],
    ids=["refuse-first", "refuse-second", "overwrite-first", "overwrite-second"],
)
def test_each_answer_reaches_the_user_as_its_own_SENTENCE(on_conflict, guard_pass, sentence):
    """THE WHOLE CLAUSE, because the two answers shared a reason code and so shared a sentence.

    An ``overwrite`` request was told to send it again with overwrite turned on — the setting it
    already had on — which reads as a broken feature, where what actually happened is that
    something landed at the destination after the request was sent and was deliberately left
    alone. The reason CODE is not the assertion: both answers refuse this item, both did so on the
    same object, and only the sentence separates them.

    Both passes are driven because the distinction the ``refuse`` codes draw — already there
    versus arrived while this was being prepared — collapses under ``overwrite``, where the
    predicate is ``LastModified >= submittedAt`` in either sweep and every collision is already
    the later event.
    """
    _install(
        [_item("alice/a/", "a", ["alice/out/a/x"])],
        {"alice/out/a/x": _AFTER},
        on_conflict=on_conflict,
    )
    event = _event(
        outcomes=[_cleared("alice/a/")] if guard_pass >= m.SECOND_PASS else [],
        on_conflict=on_conflict,
    )
    event["guardPass"] = guard_pass

    result = m.handler(event, None)

    record = _outcome(result, "alice/a/")
    assert record["outcome"] == "conflict"
    assert messages.item_clause(event["operation"], record) == sentence


def test_every_conflict_this_guard_records_is_worded_here_and_nowhere_borrowed():
    """A table guard rather than a scenario: what it protects cannot fail in one run.

    The advice after a collision used to hang off the OUTCOME, so a reason nobody worded inherited
    the ``refuse`` sentence in silence — which is how an overwrite request came to be told to turn
    overwrite on. Keyed per reason instead, a code nobody worded loses its advice rather than
    borrowing a false one, and losing it silently is what this holds shut. Equality rather than a
    subset, so a wording left behind by a retired code reddens too, and so that an empty producer
    cannot satisfy it.

    **BOTH tables, because the borrowing has two shapes and only one of them is the advice.** A
    code missing from the bodies falls through to the resolver's fallback, and the user reads
    "something went wrong." in front of advice about a destination — worse than the thin sentence
    a missing addition gives, and invisible to a guard that watches the additions alone. A subset
    there rather than equality: the bodies table words every reason this plane has, not only the
    collisions, and the equality above is what keeps this pair from going vacuous.
    """
    recorded = set(m._CONFLICT_REASONS.values()) | {m._OVERWRITE_CONFLICT_REASON}

    assert recorded == set(messages._REASON_ADDITIONS)
    assert recorded <= set(messages._BODIES)
