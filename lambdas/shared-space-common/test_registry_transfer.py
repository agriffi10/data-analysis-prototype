"""The registry's ownership transfer: what it rewrites, what it must not, and the race it refuses."""

import json

import pytest
import registry as reg
from cpcommon import clients
from fakes import FakeClientError, install

_KEY = ("admin-bkt", "shared-spaces/finance.json")


def _seed(s3, **overrides):
    """Writes one active, two-member registry record and returns it.

    Args:
      s3: The S3 fake.
      **overrides: Fields to replace on the record.

    Returns:
      The record as seeded.

    Raises:
      None.
    """
    record = {
        "schemaVersion": 1,
        "name": "finance",
        "owner": "alice",
        "members": ["alice", "bob"],
        "acknowledged": ["bob"],
        "status": "active",
        "everActive": True,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "lastRequestId": "r0",
    }
    record.update(overrides)
    s3.store[_KEY] = json.dumps(record).encode()
    return record


def _stored(s3):
    """Reads the registry record back out of the fake.

    Args:
      s3: The S3 fake.

    Returns:
      The stored record.

    Raises:
      None.
    """
    return json.loads(s3.store[_KEY])


def test_a_transfer_rewrites_the_owner_and_leaves_the_rest_byte_identical():
    """FR-001: everything but the four fields a transfer is allowed to move survives.

    Compared as a whole record minus those four rather than field by field, because the failure
    this guards is a write that quietly drops a key nobody thought to assert on — the creation
    timestamp, the ever-active stamp, the schema version.
    """
    s3, *_ = install()
    before = _seed(s3)

    committed = reg.set_owner(before, "alice", "bob", "r1")

    after = _stored(s3)
    assert after["owner"] == "bob"
    assert committed["owner"] == "bob"

    moveable = {"owner", "acknowledged", "lastRequestId", "updatedAt"}
    assert {k: v for k, v in after.items() if k not in moveable} == {
        k: v for k, v in before.items() if k not in moveable
    }
    assert after["lastRequestId"] == "r1"


def test_the_outgoing_owner_joins_acknowledged_and_the_incoming_one_leaves_it():
    """FR-003: the one place "a transfer changes exactly one field" is false.

    The roster projection reads ``active if (m == owner or m in ack)``, so an owner-only rewrite
    would render the outgoing owner — a member since the space was created — as *pending*.
    """
    s3, *_ = install()
    _seed(s3, acknowledged=["bob"])

    reg.set_owner(_stored(s3), "alice", "bob", "r1")

    after = _stored(s3)
    assert after["acknowledged"] == ["alice"], "the outgoing owner is in, the incoming one is out"


def test_a_record_with_no_acknowledged_field_is_materialised_rather_than_left_absent():
    """FR-003: the legacy path, and why the field cannot simply be left alone.

    A record predating the field means "everyone is acknowledged", but the roster fan-out reads
    the STORED field and not the absence-tolerant reader — so leaving it absent would fan out an
    empty list and show every member pending. Materialising is what preserves the legacy meaning.
    """
    s3, *_ = install()
    _seed(s3, members=["alice", "bob", "carol"])
    stored = _stored(s3)
    del stored["acknowledged"]
    s3.store[_KEY] = json.dumps(stored).encode()

    reg.set_owner(_stored(s3), "alice", "bob", "r1")

    after = _stored(s3)
    assert sorted(after["acknowledged"]) == ["alice", "carol"]
    assert "bob" not in after["acknowledged"], "the new owner is never listed; they are the owner"


def test_a_concurrent_write_that_leaves_the_owner_alone_retries_against_the_fresh_record():
    """FR-001: an ordinary lost-update retry, carrying the newly read tag rather than the stale one."""
    s3, *_ = install()
    _seed(s3)

    real_put = s3.put_object
    attempts = []

    def put_once_failing(Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        attempts.append(IfMatch)
        if len(attempts) == 1:
            # Somebody else commits first: the record moves on, and its tag with it.
            fresh = json.loads(s3.store[(Bucket, Key)])
            fresh["members"] = ["alice", "bob", "carol"]
            real_put(Bucket=Bucket, Key=Key, Body=json.dumps(fresh).encode())
            raise FakeClientError("PreconditionFailed")
        return real_put(Bucket=Bucket, Key=Key, Body=Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    s3.put_object = put_once_failing
    reg.set_owner(_stored(s3), "alice", "bob", "r1")

    assert len(attempts) == 2, "the write retried exactly once"
    assert attempts[0] != attempts[1], "the second attempt carried the tag it just read, not the stale one"
    after = _stored(s3)
    assert after["owner"] == "bob"
    assert after["members"] == ["alice", "bob", "carol"], "the concurrent add survived the retry"


def test_a_retry_that_finds_the_space_already_transferred_refuses_rather_than_taking_it_back():
    """FR-001: the interleaving the expected-owner check exists for, driven exactly.

    Alice is authorized while she owns the space. Carol takes it. Alice's write loses its race,
    re-reads, and — without the check inside the transform — would re-apply her decision to a
    record it was never authorized against, taking the space away from carol. A lost
    authorization wearing the shape of a correct CAS retry.
    """
    s3, *_ = install()
    _seed(s3)

    real_put = s3.put_object

    def put_once_failing(Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        s3.put_object = real_put
        stolen = json.loads(s3.store[(Bucket, Key)])
        stolen["owner"] = "carol"
        real_put(Bucket=Bucket, Key=Key, Body=json.dumps(stolen).encode())
        raise FakeClientError("PreconditionFailed")

    s3.put_object = put_once_failing

    with pytest.raises(reg.OwnerChanged) as raised:
        reg.set_owner(_stored(s3), "alice", "bob", "r1")

    assert "carol" in str(raised.value), "the refusal names who actually holds it"
    assert _stored(s3)["owner"] == "carol", "carol keeps the space"


def test_a_transfer_against_a_deleted_record_refuses_instead_of_resurrecting_it():
    """The write is create-if-absent when the tag is None, so an unguarded transform would
    re-create a space whose name had been freed — under a new owner, and with the expected-owner
    check passing because it read the caller's stale copy."""
    s3, *_ = install()
    stale = _seed(s3)
    del s3.store[_KEY]

    with pytest.raises(reg.RegistryRecordMissing):
        reg.set_owner(stale, "alice", "bob", "r1")

    assert _KEY not in s3.store, "nothing was written"


def test_a_transfer_of_an_emptied_space_refuses_as_deleted():
    """FR-002's state, checked again at the write: a delete emptying the space after the request
    was authorized must not be overwritten with an owner."""
    s3, *_ = install()
    emptied = _seed(s3, members=[], acknowledged=[], emptiedAt="2026-02-01T00:00:00Z")
    del emptied["owner"]
    s3.store[_KEY] = json.dumps(emptied).encode()

    # The caller's copy still names alice, which is exactly what a request authorized before the
    # delete carries. The emptied stamp is read first, so the refusal says the space is gone
    # rather than that alice is no longer its owner — both true, one useful.
    stale = dict(emptied, owner="alice")
    with pytest.raises(reg.SpaceAlreadyEmptied):
        reg.set_owner(stale, "alice", "bob", "r1")

    assert "owner" not in _stored(s3), "the emptied record kept its shape"


def test_a_transfer_touches_no_object_no_table_and_no_grant():
    """FR-001: the roster did not change, so nothing that grants access changes either.

    Asserted as recorded calls on the fakes rather than described in a comment, because the
    intuition it contradicts — that ownership must be an entitlement somewhere — is the one an
    implementer arrives with.
    """
    s3, glue, lf, _cognito = install()
    _seed(s3)

    reg.set_owner(_stored(s3), "alice", "bob", "r1")

    assert s3.operations == [], "no object was copied or deleted"
    assert glue.created == [] and glue.databases == set() and glue.tables == {}
    assert lf.grants == [] and lf.revokes == [] and lf.lf_tags == []
    assert clients._sqs.sent == [], "the registry writer notifies nobody; the verb does"
