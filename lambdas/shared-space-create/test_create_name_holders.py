"""A name is one user's or one space's, and the creator holds no slot until the database is the space's.

The common layer is added to sys.path here because `lambdas/conftest.py` does not list
shared-space-common among the layer roots it puts there.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import create_space as c
import registry as reg
import teardown
from cpcommon import clients, errors
from cpcommon import config as cpconfig
from fakes import FakeClientError, install, raises

_REGISTRY = ("admin-bkt", "shared-spaces/sales.json")
_ALICE_CACHE = ("user-bkt", "alice/user_settings/shared-connections.json")
_PREFIX_MARKER = ("shared-bkt", "sales/DO_NOT_DELETE.txt")


class _Recording:
    """Wraps a fake client and records the name of every method called on it."""

    def __init__(self, inner):
        self._inner = inner
        self.called = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name == "exceptions" or not callable(attr):
            return attr

        def call(*args, **kwargs):
            self.called.append(name)
            return attr(*args, **kwargs)

        return call


def _install(pool=("alice",), **kwargs):
    s3, glue, lf, cognito = install(pool=set(pool), **kwargs)
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    clients._glue = _Recording(glue)
    return s3, glue, lf, cognito


def _notifications():
    return [json.loads(m["MessageBody"])["message"] for m in clients._sqs.sent]


def _card():
    return json.loads(clients._s3.store[_ALICE_CACHE])["connections"][0]


def _updates(cognito):
    return [call for call in cognito.calls if call[0] == "AdminUpdateUserAttributes"]


@pytest.mark.parametrize("status", ["CONFIRMED", "UNCONFIRMED"])
def test_a_space_named_after_a_user_is_refused_before_any_prefix_database_or_slot(status):
    s3, _glue, _lf, cognito = _install(pool=("alice", "sales"))
    cognito.statuses["sales"] = status

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken, "name already taken")

    assert _updates(cognito) == []
    assert _PREFIX_MARKER not in s3.store
    assert clients._glue.called == []
    assert json.loads(s3.store[_REGISTRY])["status"] == "failed"
    assert _card() == {
        "name": "sales",
        "role": "owner",
        "status": "failed",
        "reason": "name already taken",
        "failedAction": "create",
        "retryable": False,
    }
    assert _notifications() == ['We couldn\'t create shared space "sales": name already taken.']


def test_a_users_name_and_a_spaces_name_are_refused_in_the_same_words():
    _install(pool=("alice", "sales"))
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken)
    user_refusal = (_card()["reason"], _notifications())

    s3, *_ = _install()
    s3.store[_REGISTRY] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken)
    space_refusal = (_card()["reason"], _notifications())

    assert user_refusal == space_refusal


def test_a_reserved_create_whose_name_gains_a_user_before_its_retry_ends_failed():
    s3, *_ = _install(pool=("alice", "sales"))
    s3.store[_REGISTRY] = json.dumps(
        {"name": "sales", "owner": "alice", "members": ["alice"], "lastRequestId": "req-1", "status": "provisioning"}
    ).encode()

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken)

    assert json.loads(s3.store[_REGISTRY])["status"] == "failed"


@pytest.mark.parametrize(
    "fault, raised",
    [
        pytest.param(FakeClientError("AccessDeniedException"), FakeClientError, id="deterministic"),
        pytest.param(FakeClientError("TooManyRequestsException"), errors.TransientError, id="transient"),
    ],
)
def test_a_pool_fault_is_never_read_as_no_such_user(fault, raised):
    s3, _glue, _lf, cognito = _install()
    cognito.get_user_faults["sales"] = fault

    raises(lambda: c.create_space("sales", "alice", "req-1"), raised)

    assert _updates(cognito) == []
    assert clients._glue.called == []
    assert json.loads(s3.store[_REGISTRY])["status"] == "failed"
    assert "retryable" not in _card()


def test_a_name_no_user_holds_provisions_as_before():
    _s3, glue, _lf, cognito = _install()

    out = c.create_space("sales", "alice", "req-1")

    assert ("AdminGetUser", "sales") in cognito.calls
    assert out["status"] == "active"
    assert cognito.attrs["custom:shared_space_1"] == "sales"
    assert teardown.owns_database("sales") is True
    assert glue.created == ["sales"]


def _space_holds_it(s3, _glue, _cognito):
    s3.store[_REGISTRY] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()


def _database_holds_it(_s3, glue, _cognito):
    glue.databases.add("sales")


def _user_holds_it(_s3, _glue, cognito):
    cognito.pool.add("sales")


@pytest.mark.parametrize("hold", [_space_holds_it, _database_holds_it, _user_holds_it])
def test_every_taken_name_refusal_marks_the_card_not_retryable(hold):
    s3, glue, _lf, cognito = _install()
    hold(s3, glue, cognito)

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken, "name already taken")

    assert _card()["reason"] == "name already taken"
    assert _card()["retryable"] is False


def _reserve_s3_fault(monkeypatch, s3, _cognito):
    put = s3.put_object

    def failing(**kwargs):
        if kwargs["Key"] == "shared-spaces/sales.json":
            raise FakeClientError("InternalError")
        return put(**kwargs)

    monkeypatch.setattr(s3, "put_object", failing)


def _reserve_cas_exhausted(monkeypatch, s3, _cognito):
    s3.store[_REGISTRY] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "earlier", "status": "failed"}
    ).encode()

    def contended(name, record, etag):
        raise FakeClientError("PreconditionFailed")

    monkeypatch.setattr(reg, "_put", contended)


def _membership_limit(_monkeypatch, _s3, cognito):
    for k in range(1, 11):
        cognito.attrs[f"custom:shared_space_{k}"] = f"space_{k}"


@pytest.mark.parametrize("fail", [_reserve_s3_fault, _reserve_cas_exhausted, _membership_limit])
def test_a_failure_that_is_not_a_taken_name_keeps_retry(monkeypatch, fail):
    s3, _glue, _lf, cognito = _install()
    fail(monkeypatch, s3, cognito)

    with pytest.raises(Exception) as caught:
        c.create_space("sales", "alice", "req-1")

    assert not isinstance(caught.value, reg.NameTaken)
    assert _card()["status"] == "failed"
    assert "retryable" not in _card()


def test_a_database_that_is_not_the_spaces_is_refused_without_a_slot_ever_written():
    _s3, glue, _lf, cognito = _install()
    glue.databases.add("sales")

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.NameTaken)

    assert _updates(cognito) == []
    assert "custom:shared_space_1" not in cognito.attrs


def test_a_create_refused_for_the_membership_limit_leaves_a_marked_database_its_teardown_drops():
    s3, _glue, _lf, cognito = _install()
    _membership_limit(None, s3, cognito)

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "membership limit reached")

    assert json.loads(s3.store[_REGISTRY])["status"] == "failed"
    assert teardown.owns_database("sales") is True


@pytest.mark.parametrize(
    "seed, revoked",
    [
        pytest.param(lambda glue: None, 0, id="no-database"),
        pytest.param(lambda glue: glue.databases.add("sales"), 0, id="someone-elses"),
        pytest.param(lambda glue: glue.seed_space_database("sales"), 2, id="the-spaces-own"),
    ],
)
def test_the_teardown_revokes_only_on_a_database_the_space_made(seed, revoked):
    _s3, glue, lf, _cognito = install()
    seed(glue)

    teardown.revoke_portal_role("sales")

    assert len(lf.revokes) == revoked

