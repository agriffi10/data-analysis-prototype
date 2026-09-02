"""The operator's CSV reader: what it enqueues, what it refuses whole, and what it never touches."""

import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import transfer_reader as reader
from cpcommon import clients
from fakes import install
from tf_blocks import lambda_declaration, lambda_input

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


def _rows_for(tag, count):
    """Builds a CSV whose every space name starts with one tag, so its rows are identifiable.

    Args:
      tag: The prefix every space name in this file carries.
      count: How many data rows to write.

    Returns:
      The file body.

    Raises:
      None.
    """
    return "space,new_owner\n" + "\n".join(f"{tag}{i},o{i}" for i in range(count))


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


def test_a_file_saved_by_excel_parses_rather_than_being_rejected_whole():
    """Excel writes a UTF-8 BOM by default, and an operator's CSV is exactly the file Excel makes.

    Left in, the first column reads `\ufeffspace`, the header comparison fails and the whole file
    is refused — for a reason invisible in the operator's own editor. `str.strip()` does not remove
    it either: U+FEFF is not whitespace.
    """
    s3 = _setup({"excel.csv": "\ufeffspace,new_owner\nfinance,bcarter\n"})

    reader.handler({}, None)

    assert [m["space"] for m in _sent()] == ["finance"]
    assert _keys(s3, reader.REJECTED) == []


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

    # Recomputing the same expression can only agree with itself. The half with teeth is the
    # budget's own source: the timeout TERRAFORM sets, read out of the resource block rather than
    # pinned to a literal here — otherwise the two drift and the function budgets for an
    # invocation it no longer has.
    module = pathlib.Path(__file__).resolve().parents[2] / "infra" / "modules" / "shared-spaces"
    block = lambda_declaration((module / "lambda.tf").read_text(), "transfer_reader")
    declared = int(lambda_input(block, "timeout"))
    assert declared == reader.TIMEOUT_SECONDS, (
        f"the reader budgets for {reader.TIMEOUT_SECONDS}s and Terraform gives it {declared}s"
    )


def test_a_file_bigger_than_the_WHOLE_cap_is_refused_rather_than_deferred_forever():
    """FR-007, and the distinction the first draft of this function got wrong.

    A file of more rows than one invocation can ever send cannot be processed by ANY tick. Leaving
    it in the inbox is not "waiting for the next tick", it is waiting forever — in a prefix that
    deliberately has no expiry rule, behind a log line nobody is alerted on. So it is refused with
    a reason naming the cap, which is something the operator can act on by splitting the file.
    """
    rows = "\n".join(f"space{i},owner{i}" for i in range(reader.MAX_ROWS_PER_INVOCATION + 1))
    s3 = _setup({"big.csv": f"space,new_owner\n{rows}\n"})

    result = reader.handler({}, None)

    assert clients._sqs.sent == [], "an over-cap file is not partly enqueued"
    assert _keys(s3, reader.INBOX) == [], "and it does not sit in the inbox forever"
    assert _keys(s3, reader.PROCESSED) == []
    assert result["rowsEnqueued"] == 0

    reason_key = next(k for k in _keys(s3, reader.REJECTED) if k.endswith(".reason.txt"))
    reason = s3.store[(_BUCKET, reason_key)].decode()
    assert str(reader.MAX_ROWS_PER_INVOCATION) in reason, "the operator is told the cap"
    assert "Split it" in reason, "and what to do about it"


def test_a_spent_budget_STOPS_the_sweep_so_a_later_file_cannot_overtake_an_earlier_one():
    """FR-007: processed in listing order, and the cap is where that is easiest to lose.

    Skipping the file that does not fit and carrying on would let a small later file jump ahead of
    a large earlier one — and listing order is the whole of what makes a sequence of operator
    files replayable.
    """
    # c.csv is DELIBERATELY small enough to fit what is left after a.csv. With three equal files
    # the budget excludes b and c alike, so `break` and `continue` behave identically and the test
    # asserts nothing — which is exactly what the first version of it did.
    half = reader.MAX_ROWS_PER_INVOCATION // 2 + 10
    s3 = _setup(
        {
            "a.csv": _rows_for("a", half),
            "b.csv": _rows_for("b", half),
            "c.csv": _rows_for("c", 5),
        }
    )

    result = reader.handler({}, None)

    assert result["filesHandled"] == 1, "the count must not include a file it did not handle"
    assert _keys(s3, reader.INBOX) == [f"{reader.INBOX}b.csv", f"{reader.INBOX}c.csv"]
    spaces = [json.loads(m["MessageBody"])["space"] for m in clients._sqs.sent]
    assert all(s.startswith("a") for s in spaces), (
        f"c.csv fits the remaining budget and overtook b.csv: {sorted(set(spaces))}"
    )


def test_the_shortfall_is_logged_rather_than_dropped_silently(captured_events):
    """CLAUDE.md's "no silent caps": if a check bounds coverage, it says what was dropped.

    Asserted on the emitted event rather than on the absence of work, because "nothing was
    enqueued and the file is still there" is equally true of a reader that says nothing at all.
    """
    half = reader.MAX_ROWS_PER_INVOCATION // 2 + 10
    _setup({name: _rows_for(name[0], half) for name in ("a.csv", "b.csv")})

    reader.handler({}, None)

    # Through the shared sink rather than by reading stdout: the plain-text line beside the event
    # says the same thing, so a stream scan passes while the structured field is gone.
    deferred = [
        event
        for event in captured_events.events
        if (event.get("fields") or {}).get("rows_not_processed")
    ]
    assert deferred, f"the rows it did not process were never reported: {captured_events.events}"
    assert deferred[0]["fields"]["rows_not_processed"] == half
    assert deferred[0]["fields"]["cap"] == reader.MAX_ROWS_PER_INVOCATION


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
