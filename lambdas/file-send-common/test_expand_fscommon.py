"""Turning a selection into the object list a send will copy (SPEC-165 FR-001/FR-002/FR-004).

AWS is faked, and the fake PAGES at 1,000 keys exactly as S3 does — the pagination boundary is
the one thing a fixture proves least, so a fake that handed back every key in one page would
make the folder-expansion tests agree with a bug. Runnable under pytest or directly:
python3 test_expand_fscommon.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from fscommon import config, expand
from fscommon.paths import relative_key

#: S3's own page size, which is what makes a multi-page folder the realistic case.
_S3_PAGE_SIZE = 1000


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    """A bucket as a {key: size} map, listed with real prefix filtering and real paging."""

    def __init__(self, objects: dict, head_error: str | None = None):
        self._objects = objects
        self._head_error = head_error
        self.listed_prefixes: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects, listed = self._objects, self.listed_prefixes

        class _P:
            def paginate(self, Bucket, Prefix):
                listed.append(Prefix)
                matching = sorted((k, s) for k, s in objects.items() if k.startswith(Prefix))
                for start in range(0, max(len(matching), 1), _S3_PAGE_SIZE):
                    yield {
                        "Contents": [
                            {"Key": k, "Size": s}
                            for k, s in matching[start : start + _S3_PAGE_SIZE]
                        ]
                    }

        return _P()

    def head_object(self, Bucket, Key):
        if self._head_error:
            raise _S3Error(self._head_error)
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key]}


def _install(objects, head_error=None):
    fake = _FakeS3(objects, head_error)
    clients._s3 = fake
    return fake


def _source(items, root="alice/", bucket="user-bkt"):
    return {"bucket": bucket, "root": root, "items": items}


def _folder(key):
    return {"kind": "folder", "key": key}


def _file(key):
    return {"kind": "file", "key": key}


def _refused(source):
    with pytest.raises(TerminalError) as caught:
        expand.expand(source)
    return caught.value.reason


# ── FR-001: expansion, relative keys, pagination ─────────────────────────────


def test_a_file_item_resolves_to_exactly_that_object():
    _install({"alice/notes.txt": 512})

    objects, total = expand.expand(_source([_file("alice/notes.txt")]))

    assert objects == [
        {"item": "notes.txt", "relKey": "", "srcKey": "alice/notes.txt", "size": 512}
    ]
    assert total == 512


def test_a_folder_item_keeps_each_objects_key_relative_to_the_item():
    """THE RULE THAT MAKES A FOLDER ARRIVE INTACT. `reports/2026/q1.csv` under a selected
    `reports/` keeps `2026/q1.csv` — not its whole path, and not just its basename."""
    _install(
        {
            "alice/reports/2026/q1.csv": 10,
            "alice/reports/2026/q2.csv": 20,
            "alice/reports/readme.md": 30,
        }
    )

    objects, total = expand.expand(_source([_folder("alice/reports/")]))

    assert {(o["item"], o["relKey"]) for o in objects} == {
        ("reports", "2026/q1.csv"),
        ("reports", "2026/q2.csv"),
        ("reports", "readme.md"),
    }
    assert total == 60


def test_a_folder_past_the_pagination_boundary_is_expanded_whole():
    """2,500 objects is three ListObjectsV2 pages. A verb that read `Contents` once and stopped
    would report 1,000 here and copy a silently truncated folder — the failure this test exists
    for is not an error, it is a plausible-looking smaller number."""
    _install({f"alice/big/{i:05d}.csv": 1 for i in range(2_500)})

    objects, total = expand.expand(_source([_folder("alice/big/")]))

    assert len(objects) == 2_500
    assert total == 2_500
    assert objects[0]["relKey"] == "00000.csv"


def test_the_prefix_marker_and_folder_placeholders_are_excluded():
    _install(
        {
            "alice/reports/": 0,
            "alice/reports/empty/": 0,
            "alice/reports/DO_NOT_DELETE.txt": 180,
            "alice/reports/q1.csv": 10,
        }
    )

    objects, _ = expand.expand(_source([_folder("alice/reports/")]))

    assert [o["relKey"] for o in objects] == ["q1.csv"]


def test_a_genuinely_empty_FILE_is_still_sent():
    """The divergence from `cpcommon.s3_listing.is_ignored`, asserted rather than assumed.

    That rule drops every zero-byte object, which is right for a table's source data and wrong
    for a file copy: a user's empty file is a file, and dropping it would be a silent omission
    from a send that reported success. A folder PLACEHOLDER is excluded by its trailing slash
    instead — the shape `createFolder` actually writes.
    """
    _install({"alice/reports/empty.txt": 0, "alice/reports/q1.csv": 10})

    objects, total = expand.expand(_source([_folder("alice/reports/")]))

    assert sorted(o["relKey"] for o in objects) == ["empty.txt", "q1.csv"]
    assert total == 10


def test_the_spaces_own_query_results_are_excluded_from_a_listing():
    """BELT AND BRACES, AND SAYING SO IS THE HONEST VERSION.

    The only listing that can surface `{root}athenaresults/` is one whose prefix is the space
    root, and validate-authorize refuses a root selection outright — its ancestor rule fires
    because the root CONTAINS the results folder. So this exclusion has no live path through
    the shipped front door, and it is here anyway for the reason SPEC-164 gave for writing that
    rule as containment rather than equality: a rule that holds only while a check two modules
    away stays correct is not a rule. Exercised by calling this module on the selection
    validate-authorize would have rejected, which is a contract this module owns on its own.
    """
    _install({"alice/athenaresults/x.csv": 10, "alice/reports/q1.csv": 10})

    objects, _ = expand.expand(_source([_folder("alice/")]))

    assert [o["srcKey"] for o in objects] == ["alice/reports/q1.csv"]


def test_a_user_made_athenaresults_folder_deeper_in_the_space_IS_sent():
    """SPEC-164 records this as an ordinary sendable folder, and reusing the analytics ignore
    rule would have dropped it SILENTLY — the whole reason this plane has its own predicate.
    The exclusion is anchored at the SPACE ROOT, not at whatever prefix is being listed."""
    _install({"alice/reports/athenaresults/kept.csv": 10})

    objects, _ = expand.expand(_source([_folder("alice/reports/")]))

    assert [o["relKey"] for o in objects] == ["athenaresults/kept.csv"]


def test_the_portal_managed_settings_folder_is_excluded():
    """NOT in FR-001 AC4's list, and here because narrowing an exclusion set is a decision.

    `user_settings/` holds the sender's notification inbox and shared-space connections cache;
    the browser hides it everywhere. Unlike the two analytics rules this plane deliberately does
    not reuse, anchoring this one at the SPACE ROOT keeps it with zero false positives — a user's
    own `reports/user_settings/` is untouched, as the next test asserts.
    """
    _install({"alice/user_settings/notifications.json": 10, "alice/reports/q1.csv": 10})

    objects, _ = expand.expand(_source([_folder("alice/")]))

    assert [o["srcKey"] for o in objects] == ["alice/reports/q1.csv"]


def test_a_user_made_folder_of_that_name_deeper_in_the_space_IS_sent():
    _install({"alice/reports/user_settings/mine.json": 10})

    objects, _ = expand.expand(_source([_folder("alice/reports/")]))

    assert [o["relKey"] for o in objects] == ["user_settings/mine.json"]


def test_the_results_folder_selected_as_a_file_is_REFUSED_not_merely_excluded():
    """The one exclusion that is also a front-door rule, and the rule wins: `_checked` runs
    before the excluder, so the sender is told why rather than getting `nothing_to_send`."""
    _install({"alice/athenaresults/x.csv": 10})

    assert _refused(_source([_file("alice/athenaresults/x.csv")])) == "results_not_sendable"


@pytest.mark.parametrize(
    ("key", "size"), [("alice/DO_NOT_DELETE.txt", 180), ("alice/reports/", 0)]
)
def test_an_excluded_object_selected_AS_A_FILE_is_excluded_too(key, size):
    """The exclusions were applied only to a listing, and a `file` item is filtered by nothing
    upstream — validate-authorize normalises a FOLDER key and leaves a file key untouched. So
    naming the prefix marker as a file copied it into someone's inbox, and naming a folder as a
    file copied its zero-byte placeholder as a file called `reports`. AC4 says these are excluded
    from the copy set; it does not say "when they turn up in a listing"."""
    _install({key: size})

    assert _refused(_source([_file(key)])) == "nothing_to_send"


def test_an_excluded_file_beside_a_real_one_does_not_fail_the_send():
    """The other direction: exclusion is exclusion, not refusal, exactly as it is in a listing."""
    _install({"alice/DO_NOT_DELETE.txt": 180, "alice/notes.txt": 5})

    objects, _ = expand.expand(
        _source([_file("alice/DO_NOT_DELETE.txt"), _file("alice/notes.txt")])
    )

    assert [o["srcKey"] for o in objects] == ["alice/notes.txt"]


def test_an_underscore_prefixed_folder_IS_sent():
    """The other analytics rule that would have dropped a user's files without saying so. It
    exists because ATHENA ignores such paths, which says nothing about a byte-for-byte copy."""
    _install({"alice/reports/_drafts/notes.md": 10})

    objects, _ = expand.expand(_source([_folder("alice/reports/")]))

    assert [o["relKey"] for o in objects] == ["_drafts/notes.md"]


def test_a_selection_that_resolves_to_nothing_is_refused():
    """"Nothing to send" is not a successful send. An empty folder reports success and delivers
    nothing, which the recipient experiences as a message about files that never arrive."""
    _install({"alice/empty/": 0})

    assert _refused(_source([_folder("alice/empty/")])) == "nothing_to_send"


def test_a_folder_holding_only_excluded_objects_is_refused_too():
    _install({"alice/empty/DO_NOT_DELETE.txt": 180, "alice/empty/sub/": 0})

    assert _refused(_source([_folder("alice/empty/")])) == "nothing_to_send"


def test_a_missing_file_fails_the_whole_request_naming_it():
    _install({"alice/other.txt": 5})

    with pytest.raises(TerminalError) as caught:
        expand.expand(_source([_file("alice/gone.txt")]))

    assert caught.value.reason == "source_missing"
    assert "alice/gone.txt" in caught.value.detail


def test_a_throttled_head_is_transient_not_a_missing_file():
    """The direction that matters: classifying a throttle as `source_missing` would tell the
    user their file is gone, permanently, over a fault a Retry fixes."""
    _install({"alice/notes.txt": 5}, head_error="SlowDown")

    with pytest.raises(TransientError):
        expand.expand(_source([_file("alice/notes.txt")]))


def _listing_returns(key: str):
    """Installs an S3 whose listing returns exactly ``key``, whatever prefix it is asked for."""

    class _Leaky:
        def get_paginator(self, name):
            class _P:
                def paginate(self, Bucket, Prefix):
                    yield {"Contents": [{"Key": key, "Size": 10}]}

            return _P()

    clients._s3 = _Leaky()


def test_a_listed_key_outside_the_root_is_refused():
    """FR-001's re-check. Nothing known makes S3 return a key outside the prefix it was asked
    for — the value is that the rule holds for what is actually COPIED, not only for what was
    asked for, and this is the first point in a request's life where a key comes from S3."""
    _listing_returns("bob/secrets.csv")

    assert _refused(_source([_folder("alice/reports/")])) == "forbidden"


def test_a_listed_key_with_a_dot_segment_is_refused():
    """THE ONLY LIVE CONTENT OF THE RE-CHECK, and the test above does not reach it.

    A key that is outside the root is also outside the ITEM, so `relative_key` refuses it with
    the same reason whether or not the containment check runs — measured: replacing `_checked`'s
    body with `return key` left the whole suite green. The root-prefix rule is logically implied
    on this path too (a listed key starts with the item key, which validate-authorize already
    proved starts with the root). What is NOT implied is the dot-segment rule, so this is the
    assertion that actually holds `_checked` in place.

    The key below is under the item prefix and passes `relative_key` cleanly, yielding
    `relKey = "../evil.csv"` and a destination of `bob/shared_files/alice/reports/../evil.csv`.
    Not an exploitable read — S3 resolves nothing — which is exactly `paths.py`'s recorded
    reasoning for why the rule exists anyway.
    """
    _listing_returns("alice/reports/../evil.csv")

    assert _refused(_source([_folder("alice/reports/")])) == "forbidden"


def test_the_dot_segment_key_would_otherwise_reach_the_plan():
    """Guards the guard above: if `relative_key` ever started refusing it, the test would pass
    for the wrong reason and `_checked` could be deleted unnoticed all over again."""
    assert relative_key("alice/reports/", "alice/reports/../evil.csv") == "../evil.csv"


# ── FR-002: overlap, duplicates, name collisions ─────────────────────────────


def test_the_same_item_listed_twice_collapses():
    _install({"alice/notes.txt": 5})

    objects, _ = expand.expand(
        _source([_file("alice/notes.txt"), _file("alice/notes.txt")])
    )

    assert len(objects) == 1


@pytest.mark.parametrize("order", [("file", "folder"), ("folder", "file")])
def test_one_key_named_as_both_a_file_and_a_folder_is_refused_not_collapsed(order):
    """THE SILENT DROP FR-002 EXISTS TO PREVENT, and collapsing on the key alone caused it.

    validate-authorize normalises a `folder` key to a trailing slash and leaves a `file` key
    exactly as it arrived, so these two reach the expansion with the SAME key and different
    kinds. Collapsed on the key, whichever came first won: `file` first sent one zero-byte
    placeholder and none of the folder's contents while reporting success, and reversing the
    order sent the folder — an outcome depending on the order of a JSON list.
    """
    kinds = {"file": _file("alice/reports/"), "folder": _folder("alice/reports/")}
    _install({"alice/reports/": 0, "alice/reports/q1.csv": 10})

    assert _refused(_source([kinds[order[0]], kinds[order[1]]])) == "overlapping_items"


def test_the_same_pair_is_refused_even_before_the_folder_key_is_normalised():
    """Belt and braces on the shape validate-authorize would not produce. Unnormalised, the two
    keys differ, so the overlap rule does not fire — the NAME rule does, and it is still a
    refusal rather than a drop."""
    _install({"alice/reports/": 0, "alice/reports/q1.csv": 10})

    refused = _refused(_source([_file("alice/reports/"), _folder("alice/reports")]))

    assert refused == "colliding_item_names"


def test_a_folder_and_a_file_inside_it_is_refused_naming_both():
    _install({"alice/reports/q1.csv": 5})

    with pytest.raises(TerminalError) as caught:
        expand.expand(_source([_folder("alice/reports/"), _file("alice/reports/q1.csv")]))

    assert caught.value.reason == "overlapping_items"
    assert "alice/reports/" in caught.value.detail
    assert "alice/reports/q1.csv" in caught.value.detail


def test_a_folder_and_a_folder_inside_it_is_refused():
    _install({"alice/a/b/q1.csv": 5})

    assert _refused(_source([_folder("alice/a/"), _folder("alice/a/b/")])) == "overlapping_items"


def test_a_sibling_whose_name_merely_starts_the_same_is_not_an_overlap():
    """`alice/ab.csv` starts with `alice/a` but is not under `alice/a/`. The same
    prefix-versus-startswith distinction the containment rule turns on, and getting it wrong
    here would refuse ordinary selections."""
    _install({"alice/a/q1.csv": 5, "alice/ab.csv": 5})

    objects, _ = expand.expand(_source([_folder("alice/a/"), _file("alice/ab.csv")]))

    assert len(objects) == 2


def test_two_items_that_would_arrive_under_one_name_are_refused():
    _install({"alice/x/reports/q1.csv": 5, "alice/y/reports/q2.csv": 5})

    with pytest.raises(TerminalError) as caught:
        expand.expand(_source([_folder("alice/x/reports/"), _folder("alice/y/reports/")]))

    assert caught.value.reason == "colliding_item_names"
    assert caught.value.tokens == {"itemName": "reports"}


def test_a_file_and_a_folder_of_the_same_name_also_collide():
    """`alice/reports` (a file) and `alice/other/reports/` are different keys, so the collapse
    does not touch them and the overlap rule does not either — the destination is keyed by NAME,
    which is what makes this a collision at all."""
    _install({"alice/reports": 5, "alice/other/reports/q1.csv": 5})

    assert (
        _refused(_source([_file("alice/reports"), _folder("alice/other/reports/")]))
        == "colliding_item_names"
    )


def test_the_refusals_run_before_any_listing():
    """A selection that cannot be laid out costs nothing. Checked because the ordering is easy
    to lose in a refactor and impossible to see from the outcome: both orders refuse."""
    fake = _install({"alice/reports/q1.csv": 5})

    _refused(_source([_folder("alice/reports/"), _file("alice/reports/q1.csv")]))

    assert fake.listed_prefixes == []


# ── FR-004: the caps ─────────────────────────────────────────────────────────


def test_the_object_cap_refuses_a_selection_that_expands_past_it(monkeypatch):
    monkeypatch.setattr(config, "SEND_MAX_OBJECTS", 5)
    monkeypatch.setattr(expand, "SEND_MAX_OBJECTS", 5)
    _install({f"alice/big/{i}.csv": 1 for i in range(6)})

    assert _refused(_source([_folder("alice/big/")])) == "too_many_objects"


def test_a_selection_exactly_at_the_object_cap_is_allowed(monkeypatch):
    """The off-by-one that would make the documented cap a lie."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECTS", 5)
    _install({f"alice/big/{i}.csv": 1 for i in range(5)})

    objects, _ = expand.expand(_source([_folder("alice/big/")]))

    assert len(objects) == 5


def test_the_byte_cap_refuses_a_selection_over_it(monkeypatch):
    monkeypatch.setattr(expand, "SEND_MAX_TOTAL_BYTES", 100)
    _install({"alice/big/a.csv": 60, "alice/big/b.csv": 60})

    assert _refused(_source([_folder("alice/big/")])) == "source_too_large"


def test_a_cap_is_enforced_DURING_the_walk_not_after_it(monkeypatch):
    """A cap checked afterwards is a cap the verb has already paid for: the list it bounds is
    accumulating in memory as it grows, so a folder of ten million objects would exhaust the
    Lambda before the check that exists to refuse it ever ran."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECTS", 3)
    _install({f"alice/big/{i:05d}.csv": 1 for i in range(2_000)})

    with pytest.raises(TerminalError) as caught:
        expand.expand(_source([_folder("alice/big/")]))

    assert caught.value.reason == "too_many_objects"


def test_the_caps_bound_the_whole_selection_not_one_item(monkeypatch):
    """Two folders each under the cap must not add up to a send over it."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECTS", 3)
    _install({"alice/a/1.csv": 1, "alice/a/2.csv": 1, "alice/b/1.csv": 1, "alice/b/2.csv": 1})

    assert _refused(_source([_folder("alice/a/"), _folder("alice/b/")])) == "too_many_objects"


# ── Source resolution ────────────────────────────────────────────────────────


def test_a_shared_space_source_lists_its_own_bucket():
    fake = _install({"sales/reports/q1.csv": 5})

    objects, _ = expand.expand(
        _source([_folder("sales/reports/")], root="sales/", bucket="shared-bkt")
    )

    assert objects[0]["srcKey"] == "sales/reports/q1.csv"
    assert fake.listed_prefixes == ["sales/reports/"]


def test_a_root_without_its_trailing_slash_still_anchors_the_exclusions():
    """The root arrives normalised from validate-authorize, but the exclusion anchor is derived
    from it here — an unnormalised root would build `aliceathenaresults/` and exclude nothing."""
    _install({"alice/athenaresults/x.csv": 10, "alice/reports/q1.csv": 10})

    objects, _ = expand.expand(_source([_folder("alice/")], root="alice"))

    assert [o["srcKey"] for o in objects] == ["alice/reports/q1.csv"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_an_object_over_the_per_object_cap_is_refused(monkeypatch):
    """SPEC-166. The cap SPEC-165 recorded as owed, and the one the distributed makespan model
    cannot stand in for: 500 MB/s is only reachable when the bytes are SPREAD over the worker
    pool, and one object is one worker at 25 MB/s however small the rest of the send is."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECT_BYTES", 100)
    _install({"alice/big/a.csv": 10, "alice/big/b.csv": 101})

    assert _refused(_source([_folder("alice/big/")])) == "object_too_large"


def test_an_object_exactly_at_the_per_object_cap_is_allowed(monkeypatch):
    """The off-by-one that would make the documented cap a lie, and the sentence names a size."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECT_BYTES", 100)
    _install({"alice/big/a.csv": 100})

    objects, total = expand.expand(_source([_folder("alice/big/")]))

    assert total == 100 and len(objects) == 1


def test_the_per_object_cap_is_checked_before_the_object_joins_the_plan(monkeypatch):
    """Same reasoning as the walk-time caps beside it: the refusal must not wait for a list it
    is refusing to finish accumulating. Asserted through the walk rather than the outcome, which
    both orders share."""
    monkeypatch.setattr(expand, "SEND_MAX_OBJECT_BYTES", 100)
    monkeypatch.setattr(expand, "SEND_MAX_OBJECTS", 3)
    # The oversized object sorts FIRST, so the walk meets it while the count cap is still
    # satisfied — which is the only arrangement where the two refusals can be told apart.
    _install({"alice/big/a-big.csv": 500, **{f"alice/big/z{i}.csv": 1 for i in range(2_000)}})

    assert _refused(_source([_folder("alice/big/")])) == "object_too_large"
