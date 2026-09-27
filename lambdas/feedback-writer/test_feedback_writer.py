"""The feedback writer — the append, the day it lands in, and what it refuses to overwrite.

The fake below implements REAL conditional-put semantics with a changing ETag, because the whole
design turns on what happens when two submissions race for one day's object. A fake that ignored
``IfMatch``/``IfNoneMatch`` would make the compare-and-swap loop untestable and green either way.

The weight is on the three properties that make this safe to leave running unattended: the day
comes from the submission and not from this function's clock, an existing document is appended to
rather than replaced, and a document it cannot read is left exactly where it is.
"""

import json
import pathlib

import feedback_writer as w
import pytest
from cpcommon import cas, clients
from tf_blocks import lambda_declaration, lambda_input


class _Fault(Exception):
    """A botocore-shaped client error, built here rather than imported.

    Attributes:
      response: The shape ``cpcommon.errors.error_code`` reads a code out of.
    """

    def __init__(self, code):
        """Builds the error.

        Args:
          code: The service error code.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    """A minimal ``GetObject`` body.

    Attributes:
      _data: The bytes to hand back.
    """

    def __init__(self, data):
        """Holds the bytes.

        Args:
          data: The object's bytes.

        Returns:
          None.

        Raises:
          None.
        """
        self._data = data

    def read(self):
        """Returns the bytes.

        Args:
          None.

        Returns:
          The object's bytes.

        Raises:
          None.
        """
        return self._data


class FakeS3:
    """An S3 that honours the two preconditions, and can be told to fail a read.

    Attributes:
      objects: Key to a ``(bytes, etag)`` pair.
      puts: Every accepted put, in order.
      attempts: Every put ATTEMPTED, refused ones included. ``puts`` alone cannot see a
        conditional write that lost, which is exactly the write worth asserting on.
      reads: How many reads have been served.
      read_fault: An error to raise from the first ``get_object``, or None.
      steal_after: Which read a competing writer commits after, or None.
    """

    def __init__(self, objects=None, read_fault=None, steal_after=None):
        """Builds the fake.

        Args:
          objects: Initial key-to-document mapping, serialized on the way in.
          read_fault: Raised by the first read, to drive the fail-safe branch.
          steal_after: After this many reads, a competing writer replaces the object, so the
            next conditional write loses its precondition.

        Returns:
          None.

        Raises:
          None.
        """
        self.objects = {}
        self.puts = []
        self.attempts = []
        self.reads = 0
        self.read_fault = read_fault
        self.steal_after = steal_after
        self._tags = 0
        for key, document in (objects or {}).items():
            self._store(key, json.dumps(document).encode())

    def _store(self, key, body):
        """Writes an object and mints it a fresh entity tag.

        Args:
          key: The object key.
          body: The object's bytes.

        Returns:
          None.

        Raises:
          None.
        """
        self._tags += 1
        self.objects[key] = (body, f'"tag-{self._tags}"')

    def get_object(self, Bucket, Key):
        """Serves a read, optionally faulting or letting a competitor in first.

        Args:
          Bucket: The bucket. Unused; one bucket is faked.
          Key: The object key.

        Returns:
          The body and entity tag.

        Raises:
          _Fault: When the fake was built with a read fault, or the key is absent.
        """
        self.reads += 1
        if self.read_fault is not None and self.reads == 1:
            raise _Fault(self.read_fault)
        if Key not in self.objects:
            raise _Fault("NoSuchKey")
        body, etag = self.objects[Key]
        if self.steal_after is not None and self.reads == self.steal_after:
            self._store(Key, body)
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        """Writes an object, honouring both preconditions.

        Args:
          Bucket: The bucket. Unused.
          Key: The object key.
          Body: The bytes to write.
          ContentType: Ignored.
          IfMatch: Write only if the entity tag matches.
          IfNoneMatch: Write only if the object is absent.

        Returns:
          An empty response.

        Raises:
          _Fault: On a failed precondition.
        """
        current = self.objects.get(Key)
        self.attempts.append({"Key": Key, "IfMatch": IfMatch, "IfNoneMatch": IfNoneMatch})
        if IfNoneMatch == "*" and current is not None:
            raise _Fault("ConditionalRequestConflict")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _Fault("PreconditionFailed")
        self._store(Key, Body)
        self.puts.append({"Key": Key, "Body": Body, "IfMatch": IfMatch, "IfNoneMatch": IfNoneMatch})
        return {}

    def document(self, key):
        """The stored document, parsed.

        Args:
          key: The object key.

        Returns:
          The parsed document.

        Raises:
          None.
        """
        return json.loads(self.objects[key][0])


KEY = "feedback/year=2026/month=08/day=28/feedback_2026_08_28.json"


def _submission(**overrides):
    """One submission as the API sends it.

    Args:
      **overrides: Fields to replace or, with a None value, to remove.

    Returns:
      The message body.

    Raises:
      None.
    """
    body = {
        "schemaVersion": 1,
        "eventId": "0f2c4d1e-0000-4000-8000-000000000001",
        "username": "acarter",
        "category": "bug",
        "message": "The upload bar sticks at 0%.",
        "route": "/files",
        "submittedAt": "2026-08-28T14:03:11Z",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def _event(*submissions):
    """An SQS event carrying the given submissions.

    Args:
      *submissions: The message bodies.

    Returns:
      The event.

    Raises:
      None.
    """
    return {"Records": [{"body": json.dumps(s), "messageId": "m1"} for s in submissions]}


@pytest.fixture
def s3(monkeypatch):
    """Installs a fake S3 and names the bucket, returning a builder for the fake.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      A function that installs and returns a configured ``FakeS3``.

    Raises:
      None.
    """
    monkeypatch.setattr(w, "ADMIN_BUCKET", "admin-bucket")

    def _install(**kwargs):
        fake = FakeS3(**kwargs)
        monkeypatch.setattr(clients, "_s3", fake)
        return fake

    return _install


def test_an_absent_day_is_created_with_exactly_the_one_submission(s3):
    """The first submission of a day creates the object, and only create-only can create it."""
    fake = s3()

    result = w.handler(_event(_submission()), None)

    assert result == {"key": KEY, "entries": 1}
    assert fake.attempts == [{"Key": KEY, "IfMatch": None, "IfNoneMatch": "*"}], (
        "the first write must be create-only and nothing else, or two writers both creating a "
        "day lose one"
    )
    assert fake.puts[0]["IfMatch"] is None
    document = fake.document(KEY)
    assert document["version"] == 1
    assert document["date"] == "2026-08-28"
    assert [e["eventId"] for e in document["entries"]] == [_submission()["eventId"]]
    assert document["entries"][0]["message"] == "The upload bar sticks at 0%."


def test_three_submissions_land_in_one_document_in_submission_order(s3):
    """Every existing entry survives an append; the day's object is never a replacement."""
    fake = s3()
    ids = ["a", "b", "c"]

    for index, event_id in enumerate(ids):
        w.handler(
            _event(
                _submission(
                    eventId=event_id,
                    message=f"note {index}",
                    submittedAt=f"2026-08-28T14:0{index}:11Z",
                )
            ),
            None,
        )

    document = fake.document(KEY)
    assert [e["eventId"] for e in document["entries"]] == ids
    assert [e["message"] for e in document["entries"]] == ["note 0", "note 1", "note 2"]
    assert fake.puts[1]["IfMatch"] is not None, "an append must be conditional on the tag it read"


def test_the_day_comes_from_the_submission_not_from_this_functions_clock(s3):
    """A submission stamped last year lands in last year's object, whenever it is delivered.

    The key and the ``MessageGroupId`` the API derived have to agree; a writer that used its own
    clock would file a redelivered message in the day somebody is reading rather than the day it
    belongs to.
    """
    fake = s3()

    w.handler(_event(_submission(submittedAt="2025-01-02T23:59:59Z")), None)

    assert "feedback/year=2025/month=01/day=02/feedback_2025_01_02.json" in fake.objects


def test_a_stamp_in_another_offset_is_resolved_to_the_utc_day(s3):
    """The day is UTC, so an offset stamp near midnight must not file itself locally.

    ``2026-08-29T00:30:00+05:30`` is the 28th in UTC, which is the day the API's own
    ``MessageGroupId`` named.
    """
    fake = s3()

    w.handler(_event(_submission(submittedAt="2026-08-29T00:30:00+05:30")), None)

    assert KEY in fake.objects


def test_a_document_that_will_not_parse_is_raised_over_and_never_overwritten(s3):
    """The day's records are somebody's only copy, so a bad byte is not repaired by replacement."""
    fake = s3()
    fake.objects[KEY] = (b"{not json", '"tag-9"')

    with pytest.raises(w.CorruptDocumentError, match="not valid JSON"):
        w.handler(_event(_submission()), None)

    assert fake.puts == [], "nothing may be written over a document that could not be read"
    assert fake.objects[KEY][0] == b"{not json"


def test_a_document_of_a_newer_version_is_refused_untouched(s3):
    """A shape this build does not understand is not migrated in place by an unwatched function."""
    fake = s3(objects={KEY: {"version": 2, "date": "2026-08-28", "entries": []}})

    with pytest.raises(w.CorruptDocumentError, match="version 2"):
        w.handler(_event(_submission()), None)

    assert fake.puts == []


def test_a_lost_race_re_reads_and_the_winners_entry_survives(s3):
    """The append is rebuilt on what the winner wrote, which is the whole point of re-reading."""
    fake = s3(
        objects={KEY: {"version": 1, "date": "2026-08-28", "entries": [{"eventId": "winner"}]}},
        steal_after=1,
    )

    result = w.handler(_event(_submission(eventId="mine")), None)

    assert fake.reads == 2, "a precondition failure must re-read, not retry the same bytes"
    assert result["entries"] == 2
    assert [e["eventId"] for e in fake.document(KEY)["entries"]] == ["winner", "mine"]


def test_exhausting_the_attempts_raises_so_the_submission_dead_letters(s3, monkeypatch):
    """A submission dropped here would be gone with nothing recording that it ever arrived."""
    fake = s3(objects={KEY: {"version": 1, "date": "2026-08-28", "entries": []}})
    monkeypatch.setattr(fake, "steal_after", None)
    original = fake.get_object

    def _always_stolen(Bucket, Key):
        """Reads, then lets a competitor commit before the write every time.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          The read response.

        Raises:
          None.
        """
        response = original(Bucket=Bucket, Key=Key)
        fake._store(Key, fake.objects[Key][0])
        return response

    monkeypatch.setattr(fake, "get_object", _always_stolen)

    with pytest.raises(cas.CasExhausted, match=KEY):
        w.handler(_event(_submission()), None)

    assert fake.reads == w.MAX_CAS_ATTEMPTS


def test_an_unreadable_day_falls_back_to_a_create_only_write_that_cannot_overwrite(s3):
    """A denial must not read as absence and overwrite a day that is really there.

    The role holds no ``s3:ListBucket`` on this bucket, so S3 answers a missing key with
    ``AccessDenied`` rather than ``NoSuchKey``. Treating any read failure as absent is safe only
    because the write that follows is create-only — which is asserted here rather than argued.
    """
    fake = s3(
        objects={KEY: {"version": 1, "date": "2026-08-28", "entries": [{"eventId": "kept"}]}},
        read_fault="AccessDenied",
    )

    result = w.handler(_event(_submission(eventId="mine")), None)

    assert fake.attempts[0]["IfNoneMatch"] == "*", (
        "an unreadable day must be treated as absent, so the write is create-only"
    )
    assert fake.puts[0]["IfMatch"] is not None, (
        "and the write that actually landed must be the conditional retry, not the create"
    )
    assert result["entries"] == 2
    assert [e["eventId"] for e in fake.document(KEY)["entries"]] == ["kept", "mine"], (
        "the create-only write lost its precondition, so the re-read had to preserve the entry"
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"category": "praise"}, "unknown category"),
        ({"message": ""}, "message is missing"),
        ({"username": None}, "username is missing"),
        ({"eventId": None}, "eventId is missing"),
        ({"submittedAt": "not-a-date"}, "not an ISO 8601 timestamp"),
    ],
)
def test_a_message_the_api_could_not_have_sent_is_refused_by_its_own_reason(
    s3, overrides, reason
):
    """Each refusal names WHICH check refused, so a neighbouring one cannot catch the fixture."""
    fake = s3()

    with pytest.raises(w.ValidationError, match=reason):
        w.handler(_event(_submission(**overrides)), None)

    assert fake.puts == []


def test_a_batch_is_refused_rather_than_silently_truncated(s3):
    """Taking the first record would drop every submission but one, and each has no other copy."""
    fake = s3()

    with pytest.raises(w.ValidationError, match="batch_size = 1"):
        w.handler(_event(_submission(eventId="a"), _submission(eventId="b")), None)

    assert fake.puts == []


def test_the_message_text_reaches_no_emitted_record(s3, captured_events):
    """A user's own prose rides into a store with a far wider read audience than this queue."""
    fake = s3()
    secret = "my password is hunter2 and my email is a@b.com"

    w.handler(_event(_submission(message=secret)), None)

    rendered = json.dumps([dict(e) for e in captured_events.events])
    assert secret not in rendered, "the feedback message text was logged"
    assert "hunter2" not in rendered
    assert str(len(secret)) in rendered, (
        "the length should be recorded — without it the event says nothing about the submission"
    )
    assert fake.document(KEY)["entries"][0]["message"] == secret


def test_a_large_day_object_is_reported_before_it_becomes_fatal(s3, captured_events):
    """The warning is the only thing between steady growth and a silent OOM.

    An out-of-memory kill is a SIGKILL, so the span never flushes and the failure leaves no
    structured record at all — and from then on every submission that day fails the same way into
    a dead-letter queue nobody drains. So the growth has to be visible well before that, and the
    threshold is asserted to sit under what the function's memory can actually rewrite.
    """
    big = {
        "version": 1,
        "date": "2026-08-28",
        "entries": [{"eventId": f"e{n}", "message": "x" * 4000} for n in range(5000)],
    }
    fake = s3(objects={KEY: big})

    w.handler(_event(_submission()), None)

    warnings = [e for e in captured_events.events if e["message"] == "day object is large"]
    assert len(warnings) == 1, "a day that is expensive to rewrite went unreported"
    assert warnings[0]["fields"]["key"] == KEY
    assert warnings[0]["fields"]["bytes"] > w.LARGE_OBJECT_WARN_BYTES
    assert len(fake.document(KEY)["entries"]) == 5001, "the append still happened"


def test_the_warning_threshold_is_under_what_the_function_can_rewrite():
    """A warning that fires after the OOM is a warning nobody ever sees.

    The budget is the memory the module's Terraform declares, read rather than restated — and
    read through `tf_blocks`, because the two packagings spell that attribute differently and a
    pattern matching only one of them stops finding the number without ever saying so. Peak
    resident while appending is several multiples of the raw object — the bytes, the parsed
    objects, the re-serialised string and its encoding all coexist — so the threshold has to
    leave room for that multiple, not merely be smaller than the memory.
    """
    lambda_tf = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra"
        / "modules"
        / "feedback"
        / "lambda.tf"
    ).read_text(encoding="utf-8")
    memory_bytes = (
        int(lambda_input(lambda_declaration(lambda_tf, "writer"), "memory")) * 1024 * 1024
    )

    assert memory_bytes > w.LARGE_OBJECT_WARN_BYTES * 4, (
        f"the warning fires at {w.LARGE_OBJECT_WARN_BYTES / 1024 / 1024:.0f} MB against a "
        f"{memory_bytes / 1024 / 1024:.0f} MB budget; at a peak of four times the object it would "
        "fire after the kill it exists to pre-empt"
    )


def test_a_submission_with_no_route_is_stored_without_one(s3):
    """``route`` is optional on the wire and the API omits the key entirely when it has none.

    Measured: adding ``"route"`` to ``REQUIRED_FIELDS`` passes every other test in this file, and
    would dead-letter every routeless submission into a queue nobody drains.
    """
    fake = s3()

    result = w.handler(_event(_submission(route=None)), None)

    assert result["entries"] == 1
    entry = fake.document(KEY)["entries"][0]
    assert "route" not in entry
    assert entry["username"] == "acarter"


def test_only_the_declared_fields_are_persisted(s3):
    """The writer's half of "no token, no email address" — an allowlist, not a passthrough.

    The API is the only producer today, so a field it started sending would land in the day's file
    without anybody choosing that. Measured: replacing the projection with ``dict(event)`` passes
    every other test here, because every other fixture happens to send exactly the declared set.
    """
    fake = s3()
    smuggled = _submission()
    smuggled["idToken"] = "eyJhbGciOi.THIS_IS_A_TOKEN.sig"
    smuggled["email"] = "acarter@example.com"
    smuggled["internalScore"] = 7

    w.handler(_event(smuggled), None)

    entry = fake.document(KEY)["entries"][0]
    assert set(entry) == {*w.ENTRY_FIELDS, "schemaVersion"}
    assert "idToken" not in entry and "email" not in entry and "internalScore" not in entry
    assert "@" not in json.dumps(fake.document(KEY)), "an address reached the day's document"

