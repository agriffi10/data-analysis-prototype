"""Unit tests for the file-ops inspect-source Lambda.

What this verb owes is a plan that describes exactly what the operation will touch, and a per-item
outcome for everything it could not. The cases below are the ones where a plausible implementation
is silently wrong: a folder past its pagination boundary, an exclusion that empties a legal copy, a
duplicate that collapses into a placeholder, and an item an earlier verb already decided.

Runnable under pytest or directly: python3 test_file_ops_inspect_source.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_inspect_source as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from focommon import config, notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"


class _S3Error(Exception):
    """A botocore-shaped fault, so the code under test classifies it the way it would in Lambda."""

    def __init__(self, code, status=404):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    """An S3 that pages at a thousand keys, exactly as the real one does."""

    def __init__(self, objects, admin=None):
        self._objects = objects
        self._admin = admin or {}
        self.puts = []
        self.pages = 0

    def get_paginator(self, name):
        objects = self._objects
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for k in objects if k.startswith(Prefix))
                for start in range(0, max(len(keys), 1), 1000):
                    outer.pages += 1
                    yield {
                        "Contents": [
                            {"Key": k, "Size": objects[k], "ETag": f'"{k}-etag"'}
                            for k in keys[start : start + 1000]
                        ]
                    }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key], "ETag": f'"{Key}-etag"'}

    def get_object(self, Bucket, Key):
        if Key not in self._admin:
            raise _S3Error("NoSuchKey")

        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._admin[Key])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self._admin[Key] = Body
        return {}


def _install(objects, admin=None):
    fake = _FakeS3(objects, admin)
    clients._s3 = fake
    return fake


def _event(items=None, operation="move", outcomes=None, destination=True):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "execution": {"arn": _EXECUTION},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "destination": None,
        "onConflict": None,
        "submittedAt": None,
        "outcomes": outcomes or [],
    }
    if destination and operation != "delete":
        event["destination"] = {"bucket": "user-bkt", "root": "alice/", "prefix": "alice/out/"}
        event["onConflict"] = "refuse"
        event["submittedAt"] = "2026-08-20T10:00:00+00:00"
    return event


def _plan(fake):
    return json.loads(fake.puts[-1]["Body"])


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    """The failure path enqueues a notification; the tests are about the plan, not the message."""
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── Expansion, relative keys and destinations ────────────────────────────────


def test_a_folders_objects_keep_their_structure_under_the_destination():
    """The relative-key rule: a folder arrives with its shape intact, one level under where it was
    dropped, whatever depth it lived at."""
    fake = _install({"alice/reports/2026/q1.csv": 91234, "alice/reports/notes.txt": 12})

    result = m._inspect_source(_event())

    objects = _plan(fake)["items"][0]["objects"]
    assert [o["destKey"] for o in objects] == [
        "alice/out/reports/2026/q1.csv",
        "alice/out/reports/notes.txt",
    ]
    assert [o["relKey"] for o in objects] == ["2026/q1.csv", "notes.txt"]
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 91246


def test_the_layout_is_unaffected_by_how_deep_the_source_sat():
    """A rebuilt copy of the source's own path is the obvious wrong answer, and it is invisible
    until someone moves something out of a deep folder."""
    _install({"alice/deep/nested/q1.csv": 4})
    fake = clients._s3

    m._inspect_source(_event([{"kind": "file", "key": "alice/deep/nested/q1.csv"}]))

    assert _plan(fake)["items"][0]["objects"][0]["destKey"] == "alice/out/q1.csv"


def test_a_renamed_folder_lands_under_the_name_the_request_asked_for():
    """``targetName`` is what makes a rename expressible at all, and it is honoured exactly once —
    on the item, never again on each object."""
    fake = _install({"alice/reports/a/b.csv": 1})

    m._inspect_source(
        _event([{"kind": "folder", "key": "alice/reports/", "targetName": "archive-2026"}])
    )

    assert _plan(fake)["items"][0]["objects"][0]["destKey"] == "alice/out/archive-2026/a/b.csv"


def test_a_folder_past_the_pagination_boundary_is_fully_expanded():
    """S3 returns at most 1,000 keys per page. A verb that read one page would plan two thirds of a
    2,500-object folder and report success — and for a move, delete the rest."""
    fake = _install({f"alice/reports/f{n:05d}.csv": 1 for n in range(2500)})

    result = m._inspect_source(_event())

    assert result["objectCount"] == 2500
    assert fake.pages == 3


def test_every_object_carries_the_etag_the_listing_already_returned():
    """The only cheap producer of it — one listing per thousand objects against one HeadObject per
    object — and what a later conditional delete turns on."""
    fake = _install({"alice/reports/a.csv": 3})

    m._inspect_source(_event())

    assert _plan(fake)["items"][0]["objects"][0]["etag"] == '"alice/reports/a.csv-etag"'


def test_a_selected_file_carries_its_own_etag_and_size():
    """A file item costs its own serial head, and the same fields have to come back from it."""
    fake = _install({"alice/q1.csv": 77})

    m._inspect_source(_event([{"kind": "file", "key": "alice/q1.csv"}]))

    entry = _plan(fake)["items"][0]["objects"][0]
    assert entry["size"] == 77 and entry["etag"] == '"alice/q1.csv-etag"'


def test_a_delete_plans_no_destination_at_all():
    """There is nowhere for it to go, and a destination key on a delete plan is a key some later
    verb could copy to."""
    fake = _install({"alice/reports/a.csv": 1})

    m._inspect_source(_event(operation="delete"))

    entry = _plan(fake)["items"][0]["objects"][0]
    assert "destKey" not in entry and "destBucket" not in entry
    assert _plan(fake)["destination"] is None


def test_a_listed_key_outside_the_root_is_refused():
    """Containment was checked on the REQUEST's keys, which the caller supplied. These arrive from
    S3, and the two are not the same assurance."""
    _install({"alice/reports/a.csv": 1, "alice2/leak.csv": 1})
    clients._s3._objects["alice/reports/../../alice2/leak.csv"] = 1

    with pytest.raises(TerminalError) as err:
        m._inspect_source(_event())

    assert err.value.reason == "forbidden"


# ── The closed exclusion set ─────────────────────────────────────────────────


def test_a_nested_marker_is_excluded_from_the_plan_rather_than_refusing_the_folder():
    """Both bucket policies deny deleting it and ``saved_queries/`` ships one, so failing a whole
    folder on a nested marker is a regression the browser never had."""
    fake = _install({"alice/reports/a.csv": 1, f"alice/reports/{config.MARKER_BASENAME}": 1})

    m._inspect_source(_event())

    assert [o["srcKey"] for o in _plan(fake)["items"][0]["objects"]] == ["alice/reports/a.csv"]


def test_a_zero_byte_folder_placeholder_is_KEPT():
    """The shared default predicate drops every ``size == 0`` object, so taking it would silently
    lose an empty subfolder from a move that is meant to preserve a folder's shape."""
    fake = _install({"alice/reports/empty/": 0, "alice/reports/a.csv": 1})

    m._inspect_source(_event())

    assert "alice/reports/empty/" in [o["srcKey"] for o in _plan(fake)["items"][0]["objects"]]
    assert "alice/out/reports/empty/" in [o["destKey"] for o in _plan(fake)["items"][0]["objects"]]


def test_a_users_own_hidden_folder_is_KEPT():
    """The same default drops any ``_``- or ``.``-prefixed segment. A user's ``_drafts/`` is theirs,
    and dropping it from a move is silent data loss."""
    fake = _install({"alice/reports/_drafts/x.md": 1})

    m._inspect_source(_event())

    assert _plan(fake)["items"][0]["objectCount"] == 1


def test_the_default_ignore_predicate_is_NOT_the_one_this_plane_uses():
    """Asserted against the shared rule directly, because the two exclusions above are exactly the
    ones it would apply — a future refactor reaching for the default would pass every other test
    here only if it also lost these two."""
    from cpcommon import s3_listing

    ignore = m._excluder("alice/", "alice/reports/")

    assert s3_listing.is_ignored("alice/reports/empty/", 0, "alice/reports/")
    assert s3_listing.is_ignored("alice/reports/_drafts/x.md", 1, "alice/reports/")
    assert not ignore("alice/reports/empty/", 0, "alice/reports/")
    assert not ignore("alice/reports/_drafts/x.md", 1, "alice/reports/")


def test_the_portal_managed_folders_are_swept_out_of_an_expansion_that_reaches_them_from_ABOVE():
    """The second anchor, and a deliberate second rule rather than a duplicate: the selection rules
    anchor on the item the user named and none of them looks up. An ancestor sweeps the notification
    inbox and the connections cache into a move."""
    fake = _install(
        {
            "alice/reports/a.csv": 1,
            "alice/user_settings/inbox.json": 1,
            "alice/athenaresults/r.csv": 1,
        }
    )

    m._inspect_source(_event([{"kind": "folder", "key": "alice/"}]))

    assert [o["srcKey"] for o in _plan(fake)["items"][0]["objects"]] == ["alice/reports/a.csv"]


def test_copying_OUT_of_athenaresults_still_copies_something():
    """The trap the root-anchored rule sets. Copying out of the results folder is permitted on
    purpose — the source rules refuse it as a delete or move source and deliberately not as a copy
    source — so an exclusion applied to a legally selected item would list its every object, exclude
    every one, and report the item empty."""
    fake = _install({"alice/athenaresults/r.csv": 5})

    result = m._inspect_source(
        _event([{"kind": "folder", "key": "alice/athenaresults/"}], operation="copy")
    )

    assert result["objectCount"] == 1
    assert _plan(fake)["items"][0]["objects"][0]["destKey"] == "alice/out/athenaresults/r.csv"


# ── Identity, overlaps and duplicates ────────────────────────────────────────


def test_two_items_sharing_a_LEAF_NAME_stay_apart():
    """``targetName`` makes leaf names non-unique. Keyed by name, the plan would hold two groups
    called ``reports`` and the guard's output could not tell them apart — so the commit gate would
    act on their union."""
    fake = _install({"alice/a/reports/x": 1, "alice/b/reports/y": 1})

    m._inspect_source(
        _event(
            [
                {"kind": "folder", "key": "alice/a/reports/", "targetName": "r1"},
                {"kind": "folder", "key": "alice/b/reports/", "targetName": "r2"},
            ]
        )
    )

    plan = _plan(fake)
    assert [item["itemKey"] for item in plan["items"]] == ["alice/a/reports/", "alice/b/reports/"]
    assert [item["label"] for item in plan["items"]] == ["reports", "reports"]
    assert [item["objects"][0]["destKey"] for item in plan["items"]] == [
        "alice/out/r1/x",
        "alice/out/r2/y",
    ]


def test_one_item_containing_another_refuses_the_WHOLE_request():
    """Copying an object twice and silently dropping one are both worse than a clear refusal, and
    neither of the two items is the wrong one."""
    _install({"alice/reports/a.csv": 1})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(
            _event(
                [
                    {"kind": "folder", "key": "alice/reports/"},
                    {"kind": "file", "key": "alice/reports/a.csv"},
                ]
            )
        )

    assert err.value.reason == "overlapping_items"


def test_an_exact_repeat_is_collapsed_rather_than_refused():
    """There is one right answer and no ambiguity about what the user meant."""
    fake = _install({"alice/reports/a.csv": 1})

    m._inspect_source(
        _event([{"kind": "folder", "key": "alice/reports/"}] * 2)
    )

    assert len(_plan(fake)["items"]) == 1


def test_a_duplicate_is_kind_AND_key_never_the_key_alone():
    """One key can arrive with two kinds — a folder key is normalised to a trailing slash and a file
    key is not — and collapsing on the key alone carried a zero-byte placeholder and none of the
    folder's contents while reporting success, with the outcome depending on list order."""
    _install({"alice/reports/": 0, "alice/reports/a.csv": 1})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(
            _event(
                [
                    {"kind": "file", "key": "alice/reports/"},
                    {"kind": "folder", "key": "alice/reports/"},
                ]
            )
        )

    assert err.value.reason == "overlapping_items"


# ── Per-item outcomes ────────────────────────────────────────────────────────


def test_a_missing_file_fails_ITS_ITEM_and_the_rest_proceed():
    """The browser has always carried on with the rest, and a select-all must still do what it may.
    file-send fails the whole request here on purpose; this plane deliberately does not."""
    fake = _install({"alice/reports/a.csv": 1})

    result = m._inspect_source(
        _event(
            [
                {"kind": "file", "key": "alice/gone.csv"},
                {"kind": "folder", "key": "alice/reports/"},
            ]
        )
    )

    assert [(o["itemKey"], o["outcome"]) for o in result["outcomes"]] == [
        ("alice/gone.csv", "source_missing"),
        ("alice/reports/", "cleared"),
    ]
    assert [item["itemKey"] for item in _plan(fake)["items"]] == ["alice/reports/"]


def test_an_item_that_resolves_to_nothing_is_a_per_item_FAILURE():
    """``deleteFolder`` returns success over an empty listing. On a plane, "nothing happened" must be
    distinguishable from "it worked"."""
    _install({"alice/reports/a.csv": 1})

    result = m._inspect_source(_event([{"kind": "folder", "key": "alice/empty/"}]))

    assert result["outcomes"][0]["outcome"] == "source_empty"
    assert result["itemCount"] == 0


def test_every_expanded_item_gets_a_PROVISIONAL_cleared_entry():
    """Without it the delete branch has nothing to seed from — the expanded item keys live only
    inside the plan, in S3, so a Pass state cannot construct the list."""
    _install({"alice/reports/a.csv": 1})

    result = m._inspect_source(_event(operation="delete"))

    assert result["outcomes"] == [
        {"itemKey": "alice/reports/", "label": "reports", "outcome": "cleared"}
    ]


def test_the_outcome_list_is_CARRIED_FORWARD_rather_than_recreated():
    """Three verbs produce outcomes and each returns the complete list. A verb returning only its
    own would drop the refusals the model exists to carry."""
    _install({"alice/reports/a.csv": 1})
    incoming = [
        {"itemKey": "alice/old/", "label": "old", "outcome": "noop"},
        {
            "itemKey": "alice/athenaresults/",
            "label": "athenaresults",
            "outcome": "protected",
            "reason": "results_folder_not_deletable",
        },
    ]

    result = m._inspect_source(_event(outcomes=incoming))

    assert result["outcomes"][:2] == incoming
    assert result["outcomes"][2]["itemKey"] == "alice/reports/"


def test_an_item_an_earlier_verb_DECIDED_is_never_expanded():
    """A same-key no-op's destination subtree IS its source subtree, so expanding it would have the
    guard report every one of its objects as a collision and flip a success into a refusal."""
    fake = _install({"alice/old/a.csv": 1, "alice/reports/a.csv": 1})
    incoming = [{"itemKey": "alice/old/", "label": "old", "outcome": "noop"}]

    result = m._inspect_source(
        _event(
            [{"kind": "folder", "key": "alice/old/"}, {"kind": "folder", "key": "alice/reports/"}],
            outcomes=incoming,
        )
    )

    assert [item["itemKey"] for item in _plan(fake)["items"]] == ["alice/reports/"]
    assert [o["outcome"] for o in result["outcomes"]] == ["noop", "cleared"]


# ── The caps ─────────────────────────────────────────────────────────────────


def test_the_object_cap_is_enforced_INSIDE_the_walk(monkeypatch):
    """A cap checked afterwards is one the verb has already paid for: the list it bounds accumulates
    in memory as it grows, so the check that exists to refuse a folder would run after the
    allocation that exhausts the Lambda.

    **Asserted on the NUMBER the refusal names**, which is the only externally visible difference
    between the two implementations: a check inside the walk can only say what it had reached and
    that it was still counting, where one after it would name the true total.
    """
    monkeypatch.setattr(m, "FILE_OPS_MAX_OBJECTS", 5)
    _install({f"alice/reports/f{n:04d}.csv": 1 for n in range(3000)})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(_event())

    assert err.value.reason == "too_many_objects"
    assert "reached 6 objects and was still counting" in err.value.detail
    assert "3000" not in err.value.detail


def test_the_caps_bound_the_WHOLE_selection_rather_than_each_item(monkeypatch):
    """Ten folders of three thousand objects is over the cap; per-item arithmetic admits it."""
    monkeypatch.setattr(m, "FILE_OPS_MAX_OBJECTS", 5)
    _install({f"alice/a/{n}": 1 for n in range(3)} | {f"alice/b/{n}": 1 for n in range(3)})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(
            _event([{"kind": "folder", "key": "alice/a/"}, {"kind": "folder", "key": "alice/b/"}])
        )

    assert err.value.reason == "too_many_objects"


def test_one_oversized_object_refuses_the_request():
    """A total-bytes makespan says nothing about the largest single object, because one object is
    one worker."""
    _install({"alice/reports/huge.bin": config.FILE_OPS_MAX_OBJECT_BYTES + 1})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(_event())

    assert err.value.reason == "object_too_large"


def test_a_cap_refusal_is_whole_request_rather_than_per_item(monkeypatch):
    """A per-item reading would let a request approach the bound by attrition."""
    monkeypatch.setattr(m, "FILE_OPS_MAX_TOTAL_BYTES", 10)
    _install({"alice/reports/a.csv": 11})

    with pytest.raises(TerminalError) as err:
        m._inspect_source(_event())

    assert err.value.reason == "selection_too_large_to_expand"


# ── The plan ─────────────────────────────────────────────────────────────────


def test_the_plan_goes_to_S3_and_only_its_pointer_and_counts_ride_on_the_state():
    """At the object cap the list is tens of megabytes against a 256 KB payload limit."""
    fake = _install({"alice/reports/a.csv": 4})

    result = m._inspect_source(_event())

    assert result["planKey"] == "file-ops/req-1/plan.json"
    assert fake.puts[-1]["Bucket"] == "admin-bkt"
    assert "objects" not in json.dumps(result)


def test_the_plan_carries_the_three_fields_a_later_verb_must_not_take_off_the_state():
    """Without the request id the supersession check has nothing to compare; taking the submission
    time or the conflict answer off the state instead is the substitution it exists to catch."""
    fake = _install({"alice/reports/a.csv": 4})

    m._inspect_source(_event())

    plan = _plan(fake)
    assert plan["requestId"] == "req-1"
    assert plan["submittedAt"] == "2026-08-20T10:00:00+00:00"
    assert plan["onConflict"] == "refuse"
    assert plan["executionArn"] == _EXECUTION


def test_a_second_execution_reusing_the_request_id_is_refused():
    """The id is browser-supplied and is the whole identity of a plan, so without this a run could
    plan over another execution's object list while that run was still copying from it."""
    fake = _install({"alice/reports/a.csv": 4})
    m._inspect_source(_event())
    fake.puts.clear()

    event = _event()
    event["execution"] = {"arn": "arn:aws:states:us-east-1:1:execution:file-ops:run-2"}

    with pytest.raises(TerminalError) as err:
        m._inspect_source(event)

    assert err.value.reason == "request_id_reused"
    assert not fake.puts


def test_THIS_executions_own_retry_rewrites_its_plan_rather_than_refusing_it():
    """Every task on this machine retries three times, so a transient fault after the write is an
    ordinary event. A guard refusing any occupied prefix would refuse the request it had itself just
    planned and tell the user their id had been used before."""
    fake = _install({"alice/reports/a.csv": 4})
    m._inspect_source(_event())

    result = m._inspect_source(_event())

    assert result["planKey"] == "file-ops/req-1/plan.json"
    assert len(fake.puts) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
