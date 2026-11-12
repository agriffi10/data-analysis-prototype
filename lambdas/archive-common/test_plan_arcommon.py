"""The copy plan: the expansion, the three admin-bucket keys, and the write/read round trip.

Everything downstream of this module trusts the plan completely — the manifest is built from it,
the commit gate counts against it, and the SOURCE DELETION deletes exactly its keys. So the tests
here lean on the two properties that make that trust safe: nothing enters the plan without being
re-checked against the authorized root, and nothing leaves ``load`` that cannot be shown to be
complete.
"""

import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from arcommon import plan
from arcommon.config import (
    ARCHIVE_MAX_BYTES,
    ARCHIVE_MAX_OBJECT_BYTES,
    ARCHIVE_MAX_OBJECTS,
)
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    """An S3 that pages at a configurable size, so the paginator is genuinely exercised."""

    def __init__(
        self, objects, page_size=1000, put_error=None, get_body=None, get_error=None, etags=None
    ):
        self._objects = objects
        self._etags = etags or {}
        self._page_size = page_size
        self._put_error = put_error
        self._get_body = get_body
        self._get_error = get_error
        self.puts = []
        self.pages_served = 0

    def get_paginator(self, name):
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix):
                matching = [(k, s) for k, s in sorted(fake._objects.items()) if k.startswith(Prefix)]
                for start in range(0, max(len(matching), 1), fake._page_size):
                    fake.pages_served += 1
                    yield {
                        "Contents": [
                            {"Key": k, "Size": s, **({"ETag": fake._etags[k]} if k in fake._etags else {})}
                            for k, s in matching[start : start + fake._page_size]
                        ]
                    }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key], **({"ETag": self._etags[Key]} if Key in self._etags else {})}

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._put_error:
            raise self._put_error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise self._get_error

        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._get_body)}


def _install(objects=None, **kwargs):
    fake = _FakeS3(objects or {}, **kwargs)
    clients._s3 = fake
    return fake


def _source(items, root="alice/", bucket="user-bkt"):
    return {"bucket": bucket, "root": root, "items": items}


def _request(request_id="9f2c1b8e-1111-4222-8333-444444444444"):
    return {
        "requestId": request_id,
        "archive": {"bucket": "archive-bkt", "root": f"personal/alice/archive/{request_id}/"},
    }


# ── The three admin-bucket keys (FR-001 AC7, FR-002 AC2) ─────────────────────


def test_the_plan_and_the_results_are_keyed_by_the_request_alone():
    """Execution-STABLE on purpose: a Retry of inspect-source rewrites the same object rather
    than leaving a second plan behind."""
    request = _request()

    assert plan.plan_key(request) == plan.plan_key(dict(request))
    assert plan.plan_key(request).startswith(f"archive/{request['requestId']}/")
    assert plan.transfer_results_prefix(request).endswith("/results")


def test_the_manifest_key_is_execution_unique_where_the_plan_is_not():
    """FR-002 AC2, and the one place this plane's layout differs from the plan's. Two
    overlapping executions of the same request must not clobber each other's dataset while a Map
    is reading it (SPEC-160)."""
    request = _request()

    first = plan.transfer_manifest_key(request, "exec-1")
    second = plan.transfer_manifest_key(request, "exec-2")

    assert first != second
    assert "exec-1/" in first and first.endswith(plan.MANIFEST_BASENAME)
    assert plan.plan_key(request) == plan.plan_key(request)


def test_a_manifest_key_with_no_execution_name_is_refused_rather_than_fallen_back():
    """The fallback a missing name invites — the bare request id — is EXACTLY the collision the
    execution segment exists to prevent, and it would only ever appear under concurrency."""
    for missing in (None, "", "   ", 7):
        with pytest.raises(TerminalError):
            plan.transfer_manifest_key(_request(), missing)


def test_every_key_needs_the_request_id_and_refuses_without_one():
    """The value becomes an S3 KEY, and a key built from `None` is a real object in a real
    bucket."""
    for builder in (
        plan.plan_key,
        plan.transfer_results_prefix,
        plan.restore_plan_key,
        plan.restore_progress_key,
        plan.retrieval_results_prefix,
        plan.restore_results_prefix,
    ):
        with pytest.raises(TerminalError):
            builder({"requestId": ""})


# ── SPEC-171's three new layouts ────────────────────────────────────────────


def test_every_artifact_of_one_run_shares_its_folder_and_none_collides():
    """Six key layouts on one plane now, and this module owns all of them for SPEC-161's reason:
    one module, one place a key can be wrong. Asserted as DISTINCTNESS rather than by restating
    each string, because the failure mode is two of them colliding — a progress record written
    over a plan is a restore that reads its own poll counter as an object list."""
    request = _request()
    keys = {
        plan.plan_key(request),
        plan.restore_plan_key(request),
        plan.restore_progress_key(request),
        plan.transfer_manifest_key(request, "exec-1"),
        plan.restore_manifest_key(request, "exec-1"),
        plan.transfer_results_prefix(request),
        plan.retrieval_results_prefix(request),
        plan.restore_results_prefix(request),
        plan.claim_key(request),
        plan.source_decision_key(request),
    }

    assert len(keys) == 10
    assert all(key.startswith(f"archive/{request['requestId']}/") for key in keys)


def test_the_restore_manifest_is_execution_unique_and_the_progress_record_is_not():
    """The manifest carries the execution for the transfer manifest's reason — two overlapping
    executions must not clobber each other's dataset while a Map is reading it. The progress
    record deliberately does NOT: it exists so a poll does not re-head what an earlier one saw
    complete, and a Retry or a redrive should pick that up rather than start again from zero.
    There is nothing there for two runs to clobber that re-heading would not repair."""
    request = _request()

    assert plan.restore_manifest_key(request, "exec-1") != plan.restore_manifest_key(request, "exec-2")
    assert plan.restore_progress_key(request) == plan.restore_progress_key(dict(request))
    assert plan.restore_progress_key(request).endswith(plan.PROGRESS_BASENAME)


def test_a_restore_manifest_key_refuses_a_missing_execution_name():
    """It refuses rather than falling back to the bare request id: the fallback is exactly the
    collision the execution segment exists to prevent, and it would appear only under
    concurrency."""
    with pytest.raises(TerminalError):
        plan.restore_manifest_key(_request(), "")


def test_the_two_map_exports_are_told_apart_by_their_prefix():
    """FR-003 AC3. They could not collide — the two Maps run in one execution under one request
    id — and they are named apart so an operator reading the admin bucket can tell which
    direction a run was going, and so the collector's prefix names only what it reads."""
    request = _request()

    assert plan.retrieval_results_prefix(request).endswith(f"/{plan.RETRIEVAL_RESULTS_FOLDER}")
    assert plan.restore_results_prefix(request).endswith(f"/{plan.RESTORE_RESULTS_FOLDER}")


def test_the_admin_prefix_matches_the_iam_grant_and_the_lifecycle_rule():
    """FR-001 AC9. Three files, one decision: a plan written outside the execution role's grant
    fails at runtime, and one written outside the lifecycle rule is never expired. Read as text
    rather than restated, because restating it is how the three come apart.

    The machine role's grant is the shared module's one template, rendered with the prefix the
    archive call hands it, so both halves are read: the template grants the prefix it is given,
    and the archive call gives it this one."""
    import pathlib

    infra = pathlib.Path(__file__).resolve().parent.parent.parent / "infra"
    execution = (infra / "planes" / "archive" / "execution.json.tftpl").read_text()
    sfn = (
        infra / "modules" / "control-plane" / "policies" / "sfn-permissions.json.tftpl"
    ).read_text()
    call = (infra / "plane-archive.tf").read_text()
    lifecycle = (infra / "modules" / "analytics" / "s3.tf").read_text()

    assert f"admin_bucket_arn}}/{plan.PREFIX}/*" in execution
    assert "admin_bucket_arn}/${manifest_prefix}/*" in sfn
    assert re.findall(
        r"^\s*distributed_map\s*=\s*\{[^}]*?\bmanifest_prefix\s*=\s*\"([^\"]+)\"", call, re.MULTILINE
    ) == [plan.PREFIX]
    assert f'prefix = "{plan.PREFIX}/"' in lifecycle


# ── FR-001: the expansion ────────────────────────────────────────────────────


def test_a_folder_is_expanded_through_its_pagination_boundary():
    """A truncated listing treated as complete is a DATA-LOSS bug on this plane specifically:
    the objects that never entered the plan are never copied, and the objects that did are
    deleted anyway. FR-001 AC1 gives the paginator its own test for that reason."""
    objects = {f"alice/reports/f{i:05d}.csv": 10 for i in range(2500)}
    fake = _install(objects, page_size=1000)

    result, total = plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert len(result) == 2500
    assert total == 25000
    assert fake.pages_served >= 3


@pytest.mark.parametrize(
    "listed", ["alice2/secrets.csv", "alice/../bob/secrets.csv"], ids=["sibling-root", "dot-segment"]
)
def test_a_listed_key_outside_the_authorized_root_fails_the_request(listed):
    """FR-001 AC2, and the reason it is a re-check rather than trust. The request's keys were
    checked as strings the browser supplied; these arrive from a ``ListObjectsV2`` response,
    which is the first point in the request's life where a key is produced by something other
    than the request. Nothing known makes S3 return a key outside the prefix it was asked for —
    the value of the check is that the rule holds for what is actually COPIED and DELETED, not
    for what was asked for, so the listing is made to return one.

    ``alice2/`` is the case a raw ``startswith`` on an unnormalised root would accept; the dot
    segment is the case normalisation does nothing about, and it matters here because the same
    string is concatenated into an archive key.
    """
    fake = _install({"alice/reports/a.csv": 1})
    fake._objects[listed] = 1

    class _P:
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": key, "Size": 1} for key in fake._objects]}

    fake.get_paginator = lambda name: _P()

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert err.value.reason == "forbidden"


def test_a_folder_placeholder_is_carried_and_counts_but_weighs_nothing():
    """FR-001 AC3, and the one rule that makes this plane's listing predicate differ from every
    other plane's: an archived EMPTY folder has to come back, and nothing else in the plan
    records that it existed."""
    _install({"alice/reports/empty/": 0, "alice/reports/a.csv": 5})

    objects, total = plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert {entry["relKey"] for entry in objects} == {"reports/empty/", "reports/a.csv"}
    assert total == 5


def test_every_planned_object_carries_the_tag_it_was_listed_or_headed_with():
    """What delete-source compares before it removes an original, and the only moment it can be
    had cheaply: the listing and the file head already returned it. A folder's objects take the
    listing's tag and a selected file takes its head's, so both paths are driven."""
    _install(
        {"alice/reports/a.csv": 5, "alice/notes.txt": 2},
        etags={"alice/reports/a.csv": '"listed"', "alice/notes.txt": '"headed"'},
    )

    objects, _ = plan.expand(
        _source([
            {"kind": "folder", "key": "alice/reports/"},
            {"kind": "file", "key": "alice/notes.txt"},
        ])
    )

    assert objects == [
        {"relKey": "reports/a.csv", "bytes": 5, "etag": '"listed"'},
        {"relKey": "notes.txt", "bytes": 2, "etag": '"headed"'},
    ]


def test_a_hidden_or_underscore_folder_is_the_users_own_and_is_archived():
    """The shared paginator's default predicate drops these because ATHENA ignores them, which
    says nothing about a byte-for-byte copy of a user's own folder."""
    _install({"alice/reports/_drafts/a.csv": 3, "alice/reports/.hidden": 2})

    objects, total = plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert len(objects) == 2
    assert total == 5


def test_a_prefix_marker_is_excluded_from_the_expansion():
    """Both bucket policies deny DeleteObject on it at any depth, so carrying it into a plan
    whose last step is a delete would fail the run AFTER data had moved. Excluding it also keeps
    a space whose root holds one archivable at all."""
    _install({"alice/reports/DO_NOT_DELETE.txt": 0, "alice/reports/a.csv": 4})

    objects, _ = plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert [entry["relKey"] for entry in objects] == ["reports/a.csv"]


def test_a_marker_named_as_a_FILE_is_excluded_too():
    """Nothing upstream filters a file item — validate-authorize normalises a FOLDER key and
    leaves a file key untouched — and FR-001 says these are excluded from the copy set, not
    "when they turn up in a listing"."""
    _install({"alice/DO_NOT_DELETE.txt": 0})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "file", "key": "alice/DO_NOT_DELETE.txt"}]))

    assert err.value.reason == "nothing_to_archive"


def test_a_users_own_record_named_file_at_the_SPACE_ROOT_refuses_the_whole_archive():
    """**FOUND IN REVIEW, AND IT IS THE WORST OUTCOME THIS ARC COULD STILL PRODUCE.**

    An object's archive key is `{archivePrefix}{relKey}`, and the integrity record's is
    `{archivePrefix}_manifest.json` — so a user's own file at the space root with that name maps to
    exactly the record's key. Nothing upstream stopped it: `assert_not_reserved` refuses selecting
    the space root as a FOLDER, but naming that file directly passes containment, the reserved rule
    and the marker rule.

    What it would have cost: the copy lands, `write-manifest` OVERWRITES it with the record,
    `delete-source` deletes the user's original — the vault has versioning off — and the run reports
    SUCCESS. The archive is then permanently unrestorable too, because the restore excludes that key
    as the record and counts one object fewer than the record claims, refusing
    `restore_archive_incomplete` for everything archived alongside it.

    A WHOLE-REQUEST refusal rather than an exclusion (SPEC-165's direction): dropping it silently
    would archive everything else and delete the one object it could not carry.
    """
    _install({"alice/_manifest.json": 12, "alice/reports/a.csv": 4})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "file", "key": "alice/_manifest.json"}]))

    assert err.value.reason == "reserved_object_name"
    assert err.value.tokens == {"itemName": "_manifest.json"}


def test_the_refusal_fires_through_a_folder_expansion_too():
    """The collision is a property of the RELATIVE key, not of how the object was selected, so a
    folder selection that expands onto it must refuse identically — otherwise the whole rule is
    one selection kind away from being bypassed."""
    _install({"alice/_manifest.json": 12, "alice/reports/a.csv": 4})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/"}]))

    assert err.value.reason == "reserved_object_name"


def test_the_same_name_deeper_down_archives_like_any_other_file():
    """The rule is exactly as narrow as the collision is. `reports/_manifest.json` has a relative
    key of `reports/_manifest.json`, lands at `{archivePrefix}reports/_manifest.json`, and collides
    with nothing — refusing it would take a user's own file hostage to a name."""
    _install({"alice/reports/_manifest.json": 12, "alice/reports/a.csv": 4})

    objects, _ = plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert [entry["relKey"] for entry in objects] == ["reports/_manifest.json", "reports/a.csv"]


def test_a_portal_managed_folder_at_the_space_root_is_excluded():
    """Defence in depth over the validator, anchored at the SPACE ROOT, which is where
    `assert_not_reserved` refuses it first."""
    _install(
        {"alice/system_settings/athenaresults/q.csv": 9, "alice/reports/mine.csv": 4}
    )

    objects, total = plan.expand(_source([{"kind": "folder", "key": "alice/"}]))

    assert [entry["relKey"] for entry in objects] == ["reports/mine.csv"]
    assert total == 4


@pytest.mark.parametrize(
    ("path", "folder"),
    [
        ("system_settings/archive", "archive"),
        ("system_settings/athenaresults", "athenaresults"),
        ("user_settings", "user_settings"),
    ],
)
def test_an_undeletable_folder_at_any_depth_refuses_the_whole_request(path, folder):
    """**Found in review, and it is the one place two correct rules disagreed.** The code's
    reserved-folder rule is anchored at the space root on purpose — `alice/projects/archive/` is
    an ordinary folder the user made. The IAM Deny protecting the same names cannot be anchored
    anywhere, because `*` matches `/` in a resource ARN and IAM has no single-segment wildcard.

    So this object would have been copied into Glacier at the 90-day minimum, had its record
    written, and then failed PART WAY THROUGH the deletion with "contact an administrator". It is
    refused up front instead, and refused WHOLE rather than excluded, because a silent exclusion
    drops the user's own data out of an archive that reports success.

    The path column carries the folder's SEGMENTS since the narrowing: two of the three moved and
    the Deny moved with them, so what has to appear mid-key is ``system_settings/archive`` rather
    than ``archive``. ``user_settings`` did not move, which is why the two columns differ — and the
    name a moving folder LEFT is covered by the test below.
    """
    _install({f"alice/projects/{path}/notes.txt": 4, "alice/projects/keep.csv": 1})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/projects/"}]))

    assert err.value.reason == "undeletable_folder"
    assert err.value.tokens == {"folderName": folder}


@pytest.mark.parametrize("folder", ["archive", "athenaresults"])
def test_the_name_a_moving_folder_LEFT_is_archivable_at_any_depth(folder):
    """The other side of the narrowing: a nested folder the user named after a retired home.

    ``alice/projects/archive/`` was refused while the IAM Deny read ``*/archive/*``. That Deny is
    gone, the prefix is proved empty and the objects moved, so the folder is the user's — and an
    archive of its parent has to include it rather than refuse the whole request. Nothing else in
    this file visits that path, and the rule fails in the SAFE direction, so without this row it
    could stay wrong indefinitely and look like caution.
    """
    _install({f"alice/projects/{folder}/notes.txt": 4, "alice/projects/keep.csv": 1})

    objects, total = plan.expand(_source([{"kind": "folder", "key": "alice/projects/"}]))

    assert sorted(entry["relKey"] for entry in objects) == [
        f"projects/{folder}/notes.txt",
        "projects/keep.csv",
    ]
    assert total == 5


def test_a_FILE_named_after_an_undeletable_folder_is_still_archivable():
    """The IAM Deny needs a segment AFTER the folder name (`*/archive/*`), so a file simply
    CALLED `archive` is deletable and must not be refused — the rule reads folder segments, not
    basenames."""
    _install({"alice/projects/archive": 7})

    objects, total = plan.expand(_source([{"kind": "file", "key": "alice/projects/archive"}]))

    assert [entry["relKey"] for entry in objects] == ["projects/archive"]
    assert total == 7


def test_overlapping_selections_collapse_to_one_entry_each():
    """FR-001 AC4, and the one place this plane deliberately parts company with file-send, which
    REFUSES an overlap. Here every object keeps its path relative to the space root, so
    `reports/` and `reports/q1.csv` name the same destination for the same bytes and there is
    exactly one right answer. A duplicated destination would be copied twice, counted twice, and
    the commit gate compares counts."""
    _install({"alice/reports/q1.csv": 7, "alice/reports/q2.csv": 3})

    objects, total = plan.expand(
        _source([
            {"kind": "folder", "key": "alice/reports/"},
            {"kind": "file", "key": "alice/reports/q1.csv"},
        ])
    )

    assert [entry["relKey"] for entry in objects] == ["reports/q1.csv", "reports/q2.csv"]
    assert len({entry["relKey"] for entry in objects}) == len(objects)
    assert total == 10


def test_a_selected_file_that_is_gone_fails_the_whole_request():
    """The user picked it from their own browser moments ago, so a miss means the request no
    longer describes reality — and this plane DELETES what it copies, which makes proceeding
    over a stale selection the worst of the options."""
    _install({"alice/reports/a.csv": 1})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "file", "key": "alice/reports/gone.csv"}]))

    assert err.value.reason == "source_missing"


def test_an_empty_expansion_is_a_refusal_and_never_a_success():
    """FR-001 AC6. A receipt claiming zero files archived is worse than a refusal, and an empty
    archive prefix would be indistinguishable at restore time from one whose objects vanished."""
    _install({})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert err.value.reason == "nothing_to_archive"


def test_the_object_cap_is_enforced_inside_the_walk():
    """A cap checked afterwards is a cap the verb has already paid for: the list it bounds is
    accumulating in memory as it grows."""
    _install({f"alice/reports/f{i}.csv": 1 for i in range(ARCHIVE_MAX_OBJECTS + 2)})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert err.value.reason == "too_many_objects"


def test_the_per_object_cap_refuses_before_anything_is_written():
    """A batch is one round of the worker pool and ONE OBJECT IS ONE WORKER, so nothing else
    bounds a single object's copy time — S3 would accept one 240x the batch verb's timeout."""
    _install({"alice/reports/huge.bin": ARCHIVE_MAX_OBJECT_BYTES + 1})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "file", "key": "alice/reports/huge.bin"}]))

    assert err.value.reason == "object_too_large"


def test_the_total_byte_cap_is_measured_across_the_whole_selection():
    """A different bound against a different budget: the per-object cap is a batch timeout, and
    this one is the whole machine's ceiling at the makespan rate. Neither implies the other —
    every object here is legal on its own."""
    each = ARCHIVE_MAX_OBJECT_BYTES
    enough = ARCHIVE_MAX_BYTES // each + 1
    _install({f"alice/reports/{i}.bin": each for i in range(enough)})

    with pytest.raises(TerminalError) as err:
        plan.expand(_source([{"kind": "folder", "key": "alice/reports/"}]))

    assert err.value.reason == "source_too_large"


# ── The archive prefix must be unused (found in review) ──────────────────────


def test_an_unused_archive_prefix_passes_and_costs_one_listing():
    fake = _install()
    fake.list_objects_v2 = lambda Bucket, Prefix, MaxKeys=None: {"KeyCount": 0, "Contents": []}

    assert plan.assert_archive_unused(_request()) is None


@pytest.mark.parametrize(
    "response",
    [{"KeyCount": 1, "Contents": [{"Key": "x"}]}, {"Contents": [{"Key": "x"}]}],
    ids=["key-count", "contents-without-a-count"],
)
def test_an_occupied_archive_prefix_refuses_the_request(response):
    """Both shapes, because S3 reports an empty listing with ``KeyCount: 0`` and a non-empty one
    with both fields — reading only the count would miss a response that carries the objects and
    omits it."""
    fake = _install()
    fake.list_objects_v2 = lambda Bucket, Prefix, MaxKeys=None: response

    with pytest.raises(TerminalError) as err:
        plan.assert_archive_unused(_request())

    assert err.value.reason == "request_id_reused"


def test_a_request_with_no_archive_destination_is_refused_rather_than_listed():
    """The destination is resolved by validate-authorize; its absence means the state is not the
    shape this verb runs against, and listing a bucket named ``None`` is not the way to find out."""
    with pytest.raises(TerminalError) as err:
        plan.assert_archive_unused({"requestId": "x"})

    assert err.value.reason == "forbidden"


@pytest.mark.parametrize(
    "code,expected",
    [("SlowDown", TransientError), ("AccessDenied", _S3Error)],
    ids=["retryable", "deterministic"],
)
def test_a_listing_fault_keeps_its_own_kind(code, expected):
    """A throttle must retry; a permanent denial must not be dressed up as one, or the run spends
    three more attempts on a failure that already happened."""

    def boom(Bucket, Prefix, MaxKeys=None):
        raise _S3Error(code)

    fake = _install()
    fake.list_objects_v2 = boom

    with pytest.raises(expected):
        plan.assert_archive_unused(_request())


# ── The write / read round trip ──────────────────────────────────────────────


def test_the_plan_round_trips_and_records_what_it_describes():
    """A reader — the manifest builder, delete-source, or an operator looking at a failed run —
    must not have to join the plan back against the execution to know what it describes."""
    fake = _install()
    objects = [{"relKey": "reports/a.csv", "bytes": 5}]

    key = plan.write(_request(), _source([], root="alice/"), "alice", objects, 5)
    body = json.loads(fake.puts[0]["Body"])

    assert key == plan.plan_key(_request())
    assert body["objectCount"] == 1
    assert body["totalBytes"] == 5
    assert body["source"] == {"bucket": "user-bkt", "root": "alice/"}
    assert body["archive"]["root"].endswith("/")

    fake = _install(get_body=json.dumps(body).encode())
    assert plan.load(key, _request())["objects"] == objects


def test_a_plan_short_of_the_count_it_records_is_refused():
    """**The shape this plane must never proceed over.** A short plan produces a manifest short
    of its lines, a copy that succeeds over it, and a commit gate that AGREES — because the gate
    compares the export against the plan and both would be short by the same amount — and then a
    deletion of a source the archive does not hold."""
    truncated = {
        "objects": [{"relKey": "a.csv", "bytes": 1}],
        "objectCount": 2,
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": "personal/alice/archive/x/"},
    }
    _install(get_body=json.dumps(truncated).encode())

    with pytest.raises(TerminalError) as err:
        plan.load("archive/req/copy-plan.json", {})

    assert err.value.reason == "plan_unreadable"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps([]).encode(),
        json.dumps({"objects": [], "objectCount": 0}).encode(),
        json.dumps({
            "objects": [{"relKey": "a"}],
            "objectCount": 1,
            "source": {"bucket": "b"},
            "archive": {"bucket": "a", "root": "r/"},
        }).encode(),
        json.dumps({
            "objects": [{"bytes": 1}],
            "objectCount": 1,
            "source": {"bucket": "b", "root": "alice/"},
            "archive": {"bucket": "a", "root": "r/"},
        }).encode(),
    ],
    ids=["not-json", "not-an-object", "no-objects", "no-source-root", "entry-without-a-key"],
)
def test_every_unreadable_plan_shape_is_a_whole_request_terminal(body):
    """Never a partial plan handed on: inspect-source wrote it earlier in this same execution,
    so a failure here means the object is missing or corrupt, which no retry fixes."""
    _install(get_body=body)

    with pytest.raises(TerminalError) as err:
        plan.load("archive/req/copy-plan.json", {})

    assert err.value.reason == "plan_unreadable"


def test_a_deterministic_fault_is_not_dressed_up_as_a_retry():
    """The two directions have to be told apart, because a Retry over a permanent AccessDenied is
    three more minutes of a user waiting for a failure that already happened. The write
    propagates raw (the machine's Catch records it); the read becomes this plane's own reason,
    because inspect-source wrote that object earlier in the same execution."""
    _install(put_error=_S3Error("AccessDenied"))
    with pytest.raises(_S3Error):
        plan.write(_request(), _source([]), "alice", [{"relKey": "a", "bytes": 1}], 1)

    _install(get_error=_S3Error("AccessDenied"))
    with pytest.raises(TerminalError) as err:
        plan.load("archive/req/copy-plan.json", {})

    assert err.value.reason == "plan_unreadable"


def test_a_retryable_fault_stays_transient_on_both_sides_of_the_round_trip():
    """The state's Retry re-runs the verb, which is safe because the key is a pure function of
    the request id — so a throttle must not be terminalized into a refusal."""
    _install(put_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        plan.write(_request(), _source([]), "alice", [{"relKey": "a", "bytes": 1}], 1)

    _install(get_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        plan.load("archive/req/copy-plan.json", {})


# ── the claim outlives every run that could reuse its id (SPEC-237 FR-005) ──────────────────


def _hcl_blocks(text, opener):
    """Every brace-delimited block opening with a given header, by depth rather than by regex."""
    blocks = []
    for match in re.finditer(opener, text):
        depth, start = 0, match.end() - 1
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : index + 1])
                    break
    return blocks


#: SQS's own default message retention, which applies to a queue that declares none. Named here
#: because the requests queue declares none, and a test that silently used 0 for the value that
#: actually bounds this race would print a margin far wider than the real one.
_SQS_DEFAULT_RETENTION_SECONDS = 345_600


def _queue_retention(sqs: str, resource: str) -> int:
    """The retention one queue declares, or SQS's default when it declares none.

    Args:
      sqs: The control-plane module's ``main.tf``, which declares every plane's two queues.
      resource: The ``aws_sqs_queue`` resource name.

    Returns:
      The retention in seconds.

    Raises:
      AssertionError: When the resource is not in the file at all, which means the parse has
        stopped matching rather than that the queue has no retention.
    """
    blocks = _hcl_blocks(sqs, rf'resource\s+"aws_sqs_queue"\s+"{resource}"\s*\{{')
    assert len(blocks) == 1, f"expected one {resource} queue, found {len(blocks)}"
    declared = re.search(r"message_retention_seconds\s*=\s*(\d+)", blocks[0])
    return int(declared.group(1)) if declared else _SQS_DEFAULT_RETENTION_SECONDS


def test_the_claim_outlives_every_message_that_could_start_a_second_run_of_one_id():
    """**The bound that makes an expiring claim safe, and it is not self-evident.**

    A claim is what makes an archive id one run's, and this one expires: it sits under the admin
    bucket's ``archive/`` prefix so the plane's existing grant and lifecycle rule both already
    cover it, and that rule deletes after ``admin_results_retention_days``. That is only safe
    while no second run of the same id can start after the claim is gone — and the thing that
    bounds THAT is not in this plane at all: it is how long a message can survive in the queues
    plus the longest a run can last.

    **The chain is summed, not maxed, and the REQUESTS queue is the term that matters.** A
    dead-letter message starts no execution — the drain notifies and deletes, it never redrives —
    so the DLQ's retention only counts as the time a message can wait before an operator moves it
    back with ``StartMessageMoveTask``, after which the requests queue's own retention runs from
    the start again. Reading the DLQ alone names a queue that cannot begin a run; taking the max
    of the two models a redrive as free. The requests queue declares no retention, so SQS's
    default applies, and that is read explicitly rather than allowed to parse as nothing.

    Data quality's claim is never expired and a test keeps every expiring rule off its prefix.
    This one takes the other side deliberately, so the arithmetic is what has to hold, and
    ``admin_results_retention_days`` is shared by five prefixes — a later cost cut aimed at
    Athena results would shorten this one too, with nothing on either side looking wrong.

    Every value is READ rather than restated, and every parse is asserted to have found something:
    a regex that stops matching returns nothing, and nothing compares clean.
    """
    infra = pathlib.Path(__file__).resolve().parent.parent.parent / "infra"
    lifecycle = (infra / "modules" / "analytics" / "s3.tf").read_text()
    variables = (infra / "modules" / "analytics" / "variables.tf").read_text()
    sqs = (infra / "modules" / "control-plane" / "main.tf").read_text()
    call = (infra / "plane-archive.tf").read_text()

    configurations = _hcl_blocks(
        lifecycle, r'resource\s+"aws_s3_bucket_lifecycle_configuration"[^{]*\{'
    )
    assert configurations, "the admin lifecycle configuration was not found"
    claim_rules = [
        block
        for block in _hcl_blocks(configurations[0], r"\brule\s*\{")
        if re.search(rf'prefix\s*=\s*"{plan.PREFIX}/"', block)
    ]
    assert len(claim_rules) == 1, (
        f"expected one rule filtering {plan.PREFIX}/, found {len(claim_rules)}"
    )

    expiry_var = re.search(r"expiration\s*\{[^}]*days\s*=\s*var\.(\w+)", claim_rules[0])
    assert expiry_var, f"the {plan.PREFIX}/ rule names no expiry in days"
    default = re.search(
        rf'variable\s+"{expiry_var.group(1)}"\s*\{{(?:[^{{}}]|\{{[^}}]*\}})*?default\s*=\s*(\d+)',
        variables,
    )
    assert default, f"{expiry_var.group(1)} has no default to read"

    ceiling = re.search(r"^\s*ceiling\s*=\s*\{[^}]*?\bseconds\s*=\s*(\d+)", call, re.MULTILINE)
    assert ceiling, "the machine has no timeout to read"

    dlq = _queue_retention(sqs, "requests_dlq")
    requests = _queue_retention(sqs, "requests")
    claim_lifetime = int(default.group(1)) * 86_400
    latest_second_run = dlq + requests + int(ceiling.group(1))

    assert claim_lifetime > latest_second_run, (
        f"a claim expires after {claim_lifetime}s, but a second run of one id could still be "
        f"going {latest_second_run}s after the first started — {dlq}s waiting in the DLQ, "
        f"{requests}s in the requests queue after a redrive, and {ceiling.group(1)}s of run. "
        "Shortening the claim's expiry, or lengthening either retention, reopens the reused-id "
        "race silently."
    )


def test_the_claim_sits_under_the_prefix_the_grant_and_the_lifecycle_rule_already_cover():
    """The claim's key is not a new decision: it is the copy plan's folder with another basename,
    which is what makes the test above read the right lifecycle rule and what keeps the execution
    role's existing grant sufficient. Derived from ``claim_key`` rather than restated."""
    request = _request()

    assert plan.claim_key(request).startswith(f"{plan.PREFIX}/")
    assert plan.claim_key(request) == plan.plan_key(request).replace(
        plan.BASENAME, plan.CLAIM_BASENAME
    )


class _RecordS3:
    """An admin bucket that honours create-only writes, for the decision record."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType, IfNoneMatch=None):
        if IfNoneMatch == "*" and Key in self.objects:
            raise _S3Error("PreconditionFailed")
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _S3Error("AccessDenied")

        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self.objects[Key])}


def test_an_earlier_attempts_verdict_wins_over_a_later_one_whatever_either_says():
    """The record exists so a Retry finishes what its first attempt began rather than deciding
    again: a second verdict meets the first, and gets the first back."""
    clients._s3 = _RecordS3()
    request = {**_request(), "execution": {"name": "exec-1"}}

    first = plan.record_source_decision(request, "delete", 0)
    second = plan.record_source_decision(request, "refuse", 2)

    assert first == ({"decision": "delete", "changed": 0}, True)
    assert second == ({"decision": "delete", "changed": 0}, False)
    assert plan.read_source_decision(request) == {"decision": "delete", "changed": 0}

