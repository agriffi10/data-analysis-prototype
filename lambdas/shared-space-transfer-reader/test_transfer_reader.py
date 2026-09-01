"""The operator's CSV reader: what it enqueues, what it refuses whole, and what it never touches."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import transfer_reader as reader
from cpcommon import clients
from fakes import install

_BUCKET = "admin-bkt"


def _setup(files=None):
    """Installs the fakes, points the reader at a queue, and seeds the inbox.

    Args:
      files: Mapping of inbox file name to its text body.

    Returns:
      The S3 fake.

    Raises:
      None.
    """
    s3, *_ = install()
    os.environ["SHARED_SPACE_REQUESTS_QUEUE_URL"] = "https://sqs.test/shared-space-requests.fifo"
    for name, body in (files or {}).items():
        s3.store[(_BUCKET, f"{reader.INBOX}{name}")] = body.encode()
    return s3


def _sent():
    """The message bodies the reader put on the queue.

    Args:
      None.

    Returns:
      The parsed bodies, in send order.

    Raises:
      None.
    """
    return [json.loads(m["MessageBody"]) for m in clients._sqs.sent]


def _keys(s3, prefix):
    """Every key under one prefix in the fake.

    Args:
      s3: The S3 fake.
      prefix: The prefix to filter on.

    Returns:
      The sorted keys.

    Raises:
      None.
    """
    return sorted(key for bucket, key in s3.store if bucket == _BUCKET and key.startswith(prefix))


def test_each_valid_row_enqueues_exactly_one_correctly_shaped_message():
    """FR-007: one message per row, on the same queue and in the same group the API writes to."""
    _setup({"a.csv": "space,new_owner\nfinance,bcarter\nproject,dmehta\n"})

    reader.handler({}, None)

    sent = _sent()
    assert len(sent) == 2
    assert [(m["space"], m["payload"]["newOwner"]) for m in sent] == [
        ("finance", "bcarter"),
        ("project", "dmehta"),
    ]
    assert all(m["action"] == "transfer_ownership" for m in sent)
    assert all(m["origin"] == "operator" for m in sent)
    assert all("identity" not in m and "idToken" not in m for m in sent), (
        "an operator message carries no credential at all — the SenderId stands in for it"
    )
    assert all(m["schemaVersion"] == reader.SCHEMA_VERSION for m in sent)
    assert all(m["MessageGroupId"] == "shared-space" for m in clients._sqs.sent)
    assert [m["MessageDeduplicationId"] for m in clients._sqs.sent] == [m["requestId"] for m in sent]


def test_a_processed_file_is_copied_aside_and_removed_from_the_inbox():
    """FR-007: so a later tick cannot re-enqueue it."""
    s3 = _setup({"a.csv": "space,new_owner\nfinance,bcarter\n"})

    reader.handler({}, None)

    assert _keys(s3, reader.INBOX) == []
    processed = _keys(s3, reader.PROCESSED)
    assert len(processed) == 1 and processed[0].endswith("/a.csv")


def test_the_copy_is_confirmed_before_the_delete():
    """FR-007: a delete that ran first, followed by a failed copy, loses the operator's file — and
    loses it silently, because the next tick simply finds an empty inbox. The store looks identical
    either way, so the ORDER is what has to be asserted."""
    s3 = _setup({"a.csv": "space,new_owner\nfinance,bcarter\n"})

    reader.handler({}, None)

    kinds = [op[0] for op in s3.operations]
    assert kinds == ["copy", "delete"], f"the file was moved in the wrong order: {s3.operations}"


def test_an_empty_inbox_is_a_successful_no_op():
    """FR-007: the first firing of a newly created schedule must not fail."""
    _setup()

    result = reader.handler({}, None)

    assert result == {"status": "ok", "filesSeen": 0, "filesHandled": 0, "rowsEnqueued": 0}
    assert clients._sqs.sent == []


def test_a_wrong_header_rejects_the_WHOLE_file_and_enqueues_none_of_its_rows():
    """FR-007: including the transposed pair, which parses perfectly and would transfer every space
    it names to the wrong person."""
    s3 = _setup({"bad.csv": "new_owner,space\nbcarter,finance\ndmehta,project\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == [], "not one row was enqueued"
    assert _keys(s3, reader.INBOX) == []
    rejected = _keys(s3, reader.REJECTED)
    assert any(key.endswith("/bad.csv") for key in rejected)
    reason = next(key for key in rejected if key.endswith(".reason.txt"))
    assert b"header" in s3.store[(_BUCKET, reason)]


def test_a_malformed_row_rejects_the_whole_file_rather_than_part_of_it():
    s3 = _setup({"bad.csv": "space,new_owner\nfinance,bcarter\nproject\n"})

    reader.handler({}, None)

    assert clients._sqs.sent == [], "the good row above the bad one was not enqueued either"
    assert _keys(s3, reader.REJECTED)


def test_files_are_processed_in_listing_order():
    """FR-007: lexicographic, which is what makes a sequence of operator files replayable."""
    _setup(
        {
            "a.csv": "space,new_owner\nalpha,one\n",
            "b.csv": "space,new_owner\nbeta,two\n",
            "c.csv": "space,new_owner\ngamma,three\n",
        }
    )

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["alpha", "beta", "gamma"]


def test_the_row_cap_is_computed_from_the_budget_it_is_derived_from():
    """FR-007: named to its inputs rather than written down.

    The budget is the function's own timeout, of which a share is reserved for sending and the
    rest for the listing, the reads, the copies and the deletes, at a conservative round trip per
    send. A hard-coded number would hide a wrong model — recomputing here is what makes the cap
    move when the timeout does.
    """
    expected = int(
        reader.TIMEOUT_SECONDS * reader.SEND_BUDGET_FRACTION * 1000 / reader.SEND_MILLISECONDS
    )
    assert expected == reader.MAX_ROWS_PER_INVOCATION
    assert reader.TIMEOUT_SECONDS == 60, "the Terraform timeout this is derived from"


def test_a_file_over_the_cap_is_left_in_the_inbox_and_the_shortfall_is_logged():
    """FR-007: no silent cap. The file stays put and the next tick continues it."""
    rows = "\n".join(f"space{i},owner{i}" for i in range(reader.MAX_ROWS_PER_INVOCATION + 1))
    s3 = _setup({"big.csv": f"space,new_owner\n{rows}\n"})

    result = reader.handler({}, None)

    assert clients._sqs.sent == [], "an over-cap file is not partly enqueued"
    assert _keys(s3, reader.INBOX) == [f"{reader.INBOX}big.csv"], "it is still there for next time"
    assert _keys(s3, reader.PROCESSED) == []
    assert result["rowsEnqueued"] == 0


def test_the_reader_touches_only_the_ownership_transfers_prefix():
    """FR-007: it never reads or writes the registry, and holds no grant that would let it.

    Whether a space exists, whether the named member belongs to it and whether the caller may
    transfer it are the validator's questions; a reader that answered them is a second authority
    that will eventually disagree with the first.
    """
    s3 = _setup({"a.csv": "space,new_owner\nfinance,bcarter\n"})
    touched = []
    for name in ("get_object", "put_object", "delete_object", "list_objects_v2"):
        real = getattr(s3, name)

        def watch(_real=real, **kw):
            touched.append(kw.get("Key") or kw.get("Prefix"))
            return _real(**kw)

        setattr(s3, name, watch)
    real_copy = s3.copy_object

    def watch_copy(Bucket, Key, CopySource, **kw):
        touched.extend([Key, CopySource["Key"]])
        return real_copy(Bucket=Bucket, Key=Key, CopySource=CopySource, **kw)

    s3.copy_object = watch_copy

    reader.handler({}, None)

    assert touched, "the sweep recorded nothing, so this asserts nothing"
    stray = [key for key in touched if not key.startswith("ownership-transfers/")]
    assert stray == [], f"the reader reached outside its prefix: {stray}"


def test_a_replayed_file_reproduces_the_same_request_ids():
    """The dedup key is derived, not minted, so a tick that crashed between sending and moving the
    file resends the SAME ids and the queue collapses the replay."""
    _setup({"a.csv": "space,new_owner\nfinance,bcarter\n"})
    reader.handler({}, None)
    first = [m["MessageDeduplicationId"] for m in clients._sqs.sent]

    _setup({"a.csv": "space,new_owner\nfinance,bcarter\n"})
    reader.handler({}, None)
    second = [m["MessageDeduplicationId"] for m in clients._sqs.sent]

    assert first == second and first


def test_the_readers_envelope_constants_agree_with_the_plane_they_are_for():
    """The reader ships without the domain layer, so both constants are local copies. Copies drift;
    this is what stops these two doing it silently.

    ``SCHEMA_VERSION`` disagreeing means every operator message is refused as an unsupported
    version. The group id disagreeing is worse — the messages are accepted and simply stop being
    ordered against the API's, which nothing else would report.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
    from apicommon import fifo

    import config as domain_config

    assert reader.SCHEMA_VERSION == domain_config.SCHEMA_VERSION
    assert fifo._group_shared_space(None, {}) == reader.MESSAGE_GROUP_ID
