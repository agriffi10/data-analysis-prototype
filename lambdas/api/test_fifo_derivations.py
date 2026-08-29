"""Every FIFO key, replayed against vectors captured from the browser before it was deleted.

The vectors are the whole point: a wrong group id still sends, so nothing at runtime reports that
delivery stopped being ordered the way the planes' locks were sized for. They were captured by
driving the ten live TypeScript services against a stubbed SQS client and recording the whole
``SendMessageCommand`` input, at commit ``b4344599``.

Two recorded values are deliberately NOT reproduced, and each has its own test below rather than a
quiet exemption: table-share's dedup id, which hashed the ID token and now hashes the verified
actor, and notifications' dedup id, which is a fresh UUID on both sides.
"""

import ast
import hashlib
import json
import os
import pathlib
from unittest import mock

import pytest
from apicommon import fifo
from apicommon.envelope import ApiError
from cpcommon.auth import Principal

_VECTORS = json.loads((pathlib.Path(__file__).parent / "fifo_vectors.json").read_text())

_EXPECTED_ROUTES = {
    "sharedSpace.enqueue",
    "notifications.enqueue",
    "tableBuild.create",
    "tableBuild.refresh",
    "tableShare.enqueue",
    "dataQuality.enqueue",
    "fileSend.enqueue",
    "archive.archive",
    "archive.restore",
    "fileOps.enqueue",
}

_DEDUP_NOT_REPRODUCIBLE = {"tableShare.enqueue", "notifications.enqueue"}


@pytest.fixture(autouse=True)
def _buckets():
    """Points the bucket configuration at the names the vectors were captured under.

    Returns:
      None.

    Raises:
      None.
    """
    with mock.patch.dict(
        os.environ,
        {
            "USER_SPACE_BUCKET": _VECTORS["buckets"]["user"],
            "SHARED_SPACE_BUCKET": _VECTORS["buckets"]["shared"],
        },
    ):
        yield


def _actor(vector) -> Principal:
    """Builds the caller a vector was captured for.

    Args:
      vector: One recorded vector.

    Returns:
      A principal whose username is the one the browser put in the body, so a derivation that
      reads the verified actor reproduces what the browser produced from the caller-supplied one.

    Raises:
      None.
    """
    inputs = vector["inputs"]
    return Principal(
        username=inputs.get("username", inputs.get("actor", "alice")), claims={}
    )


def _body(vector) -> dict:
    """Reads the message body the browser sent, minus the token it carried.

    Args:
      vector: One recorded vector.

    Returns:
      The parsed body.

    Raises:
      None.
    """
    return json.loads(vector["sent"]["MessageBody"])


@pytest.mark.parametrize(
    "vector", _VECTORS["vectors"], ids=lambda v: f"{v['route']}:{id(v)}"
)
def test_every_captured_vector_replays_byte_for_byte(vector):
    """The Python derivation reproduces what the browser sent, for every recorded call."""
    route = vector["route"].split("@")[0]
    principal, body = _actor(vector), _body(vector)

    group = fifo.group_id_for(route, principal, body)
    dedup = (
        None
        if route in _DEDUP_NOT_REPRODUCIBLE
        else fifo.dedup_id_for(route, principal, body)
    )

    assert group == vector["sent"]["MessageGroupId"], f"{route} group id moved"
    if dedup is not None:
        assert dedup == vector["sent"]["MessageDeduplicationId"], (
            f"{route} dedup id moved"
        )


def test_the_vector_file_covers_every_route_and_both_space_kinds():
    """A vector file that lost a route is a failure, not a smaller run."""
    routes = {v["route"].split("@")[0] for v in _VECTORS["vectors"]}
    kinds = {
        v["inputs"]["space"]["kind"]
        for v in _VECTORS["vectors"]
        if isinstance(v["inputs"].get("space"), dict)
    }

    assert routes == _EXPECTED_ROUTES
    assert kinds == {"personal", "shared"}


def test_data_quality_strips_both_ends_where_the_space_planes_keep_a_trailing_slash():
    """The one-character divergence that reads as a typo and is not."""
    principal = Principal(username="alice", claims={})
    space = {"kind": "personal", "name": "alice"}

    messy = fifo.group_id_for(
        "dataQuality.enqueue",
        principal,
        {"space": space, "location": "  /data/2026/q1/  "},
    )
    clean = fifo.group_id_for(
        "dataQuality.enqueue", principal, {"space": space, "location": "data/2026/q1"}
    )
    space_keyed = fifo.group_id_for(
        "fileSend.enqueue", principal, {"source": {"space": space}}
    )

    assert messy == clean
    assert messy != space_keyed


def test_archive_restore_keys_on_the_archive_root_and_carries_no_bucket():
    """The restore group id names the archive, and the vault bucket is deliberately absent."""
    principal = Principal(username="alice", claims={})
    body = {"space": {"kind": "personal", "name": "alice"}, "archiveId": "arc-123"}

    with mock.patch.dict(
        os.environ, {"USER_SPACE_BUCKET": "a-completely-different-bucket"}
    ):
        under_another_bucket = fifo.group_id_for("archive.restore", principal, body)
    original = fifo.group_id_for("archive.restore", principal, body)

    assert under_another_bucket == original


def test_table_share_dedup_survives_a_token_refresh():
    """The divergence FR-003 exists for: two submits a minute apart used to be two shares."""
    body = _body(
        next(v for v in _VECTORS["vectors"] if v["route"] == "tableShare.enqueue")
    )
    alice = Principal(username="alice", claims={})

    browser_before, browser_after = (
        v["sent"]["MessageDeduplicationId"]
        for v in _VECTORS["vectors"]
        if v["route"].startswith("tableShare.enqueue")
    )

    with mock.patch.object(fifo.time, "time", return_value=_VECTORS["nowMs"] / 1000):
        before = fifo.dedup_id_for("tableShare.enqueue", alice, body)
        body_after_refresh = {**body, "actor": _VECTORS["tokenAfterRefresh"]}
        after = fifo.dedup_id_for("tableShare.enqueue", alice, body_after_refresh)

    assert browser_before != browser_after, "the browser's digest used to move with the token"
    assert before == after, "the new digest must not"
    assert before not in {browser_before, browser_after}


def test_the_table_share_canonical_form_is_pinned_field_by_field():
    """Every element of the array, because the replay cannot cover this one derivation.

    Table-share is excluded from the vector replay — its digest deliberately no longer matches the
    browser's — so without this the whole canonical form is unguarded: dropping a field, reordering
    the source object's keys or losing the compact separators all still produce a 64-character hex
    string, and every assertion that only checks the shape stays green while double-submits stop
    collapsing.
    """
    alice = Principal(username="alice", claims={})
    base = {
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": "bob"}],
    }
    variants = {
        "another table name": {**base, "tableName": "orders_other"},
        "another source table": {**base, "source": {"database": "alice", "table": "invoices"}},
        "another recipient": {**base, "recipients": [{"kind": "user", "name": "carol"}]},
    }

    with mock.patch.object(fifo.time, "time", return_value=_VECTORS["nowMs"] / 1000):
        digests = {
            label: fifo.dedup_id_for("tableShare.enqueue", alice, body)
            for label, body in {"base": base, **variants}.items()
        }
        reordered = fifo.dedup_id_for(
            "tableShare.enqueue",
            alice,
            {**base, "source": {"table": "orders", "database": "alice"}},
        )
        resorted = fifo.dedup_id_for(
            "tableShare.enqueue",
            alice,
            {
                **base,
                "recipients": [
                    {"kind": "user", "name": "bob"},
                    {"kind": "space", "name": "salesteam"},
                ],
            },
        )
        resorted_other_order = fifo.dedup_id_for(
            "tableShare.enqueue",
            alice,
            {
                **base,
                "recipients": [
                    {"kind": "space", "name": "salesteam"},
                    {"kind": "user", "name": "bob"},
                ],
            },
        )

    assert len(set(digests.values())) == len(digests), "a field dropped out of the canonical form"
    assert reordered == digests["base"], "the source object's key order must not move the digest"
    assert resorted == resorted_other_order, "recipients are sorted before hashing"


def test_two_users_sharing_one_table_do_not_collapse_into_each_other():
    """Dropping the actor entirely would deliver one user's share and silently drop the other's."""
    body = _body(
        next(v for v in _VECTORS["vectors"] if v["route"] == "tableShare.enqueue")
    )

    with mock.patch.object(fifo.time, "time", return_value=_VECTORS["nowMs"] / 1000):
        alice = fifo.dedup_id_for(
            "tableShare.enqueue", Principal(username="alice", claims={}), body
        )
        bob = fifo.dedup_id_for(
            "tableShare.enqueue", Principal(username="bob", claims={}), body
        )

    assert alice != bob


def test_a_derivation_refuses_an_input_it_cannot_digest_and_says_which():
    """The two refusals no user exercises, asserted by reason code rather than by "it raised".

    An empty bucket or name would put every space behind one group id, and an unknown kind would
    otherwise pick a bucket by falling through. Both are ``InvalidRequest`` rather than
    ``AccessDenied``: the API refuses on shape, and the plane's verb owns authorization.
    """
    principal = Principal(username="alice", claims={})

    with pytest.raises(ApiError) as unknown_kind:
        fifo.group_id_for(
            "dataQuality.enqueue",
            principal,
            {"space": {"kind": "archive", "name": "alice"}, "location": "data/"},
        )
    with pytest.raises(ApiError) as empty_name:
        fifo.group_id_for(
            "fileSend.enqueue",
            principal,
            {"source": {"space": {"kind": "personal", "name": " / "}}},
        )

    assert unknown_kind.value.code == "InvalidRequest"
    assert empty_name.value.code == "InvalidRequest"


def test_the_notifications_dedup_id_is_minted_fresh_every_time():
    """The one id this service mints. It is a queue key and never reaches a response or a body."""
    principal = Principal(username="alice", claims={})
    body = {"action": "markAllRead"}

    first = fifo.dedup_id_for("notifications.enqueue", principal, body)
    second = fifo.dedup_id_for("notifications.enqueue", principal, body)

    assert first != second


def test_notifications_groups_on_the_verified_actor_and_ignores_the_body():
    """The one group id that used to be a caller-supplied string."""
    body = {"action": "markRead", "id": "n-1", "username": "someone-else"}

    group = fifo.group_id_for(
        "notifications.enqueue", Principal(username="alice", claims={}), body
    )

    assert group == "alice"


def test_the_derivations_live_in_one_module_and_no_handler_computes_one():
    """One builder, because the vectors above can only prove the one builder right.

    A second derivation anywhere is a second thing to keep byte-identical, and the failure is
    silent: a handler that hashes its own group id still sends, and the queue simply stops
    grouping the way the plane's lock was sized for.
    """
    here = pathlib.Path(__file__).parent
    definitions = {"group_id_for": 0, "dedup_id_for": 0}
    hashing_handlers = []

    for path in sorted(here.rglob("*.py")):
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in definitions:
                definitions[node.name] += 1
            if (
                path.parent.name == "routes"
                and isinstance(node, ast.Attribute)
                and node.attr == "sha256"
            ):
                hashing_handlers.append(str(path.relative_to(here)))

    assert definitions == {"group_id_for": 1, "dedup_id_for": 1}
    assert hashing_handlers == []


def test_a_derived_key_the_queue_would_refuse_is_a_400_rather_than_a_generic_failure():
    """Two derivations concatenate a value nothing upstream bounds.

    A source table name is only required to be a non-empty string, and a caller's own request id
    becomes the dedup id verbatim — so both a 200-character table name and a 5000-character request
    id reach SQS, which refuses the send and hands the user a generic failure naming nothing, every
    time they try.
    """
    alice = Principal(username="alice", claims={})

    with pytest.raises(ApiError) as too_long:
        fifo.group_id_for(
            "tableShare.enqueue",
            alice,
            {"source": {"database": "db", "table": "t" * 200}},
        )
    with pytest.raises(ApiError) as illegal_character:
        fifo.group_id_for(
            "tableShare.enqueue",
            alice,
            {"source": {"database": "db", "table": "orders 2026"}},
        )
    with pytest.raises(ApiError) as unbounded_dedup:
        fifo.dedup_id_for("fileSend.enqueue", alice, {"requestId": "r" * 5000})

    assert too_long.value.code == "InvalidRequest"
    assert illegal_character.value.code == "InvalidRequest"
    assert unbounded_dedup.value.code == "InvalidRequest"


def test_a_non_ascii_value_digests_the_way_the_browser_digests_it():
    """`json.dumps` escapes non-ASCII by default and `JSON.stringify` does not.

    A shared-space name is format-checked nowhere server-side and reaches the canonical array as a
    recipient, so the two would disagree on exactly the values the vectors — all ASCII — cannot
    show.
    """
    alice = Principal(username="alice", claims={})
    body = {
        "source": {"database": "db", "table": "orders"},
        "tableName": "copy",
        "recipients": [{"kind": "space", "name": "café"}],
    }

    with mock.patch.object(fifo.time, "time", return_value=_VECTORS["nowMs"] / 1000):
        digest = fifo.dedup_id_for("tableShare.enqueue", alice, body)

    expected = hashlib.sha256(
        json.dumps(
            [
                "alice",
                {"database": "db", "table": "orders"},
                "copy",
                ["space:café"],
                int(_VECTORS["nowMs"]) // fifo.DEDUP_BUCKET_MS,
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert digest == expected
