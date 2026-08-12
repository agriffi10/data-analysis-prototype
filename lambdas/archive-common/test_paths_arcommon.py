"""The archive key layout, and the two properties the whole arc rests on.

The first is that **the archived key encodes its own origin**, so a restore can be rebuilt
from a listing rather than from the receipt. The second is that **the two namespaces are
partitioned by kind**, without which a shared space could restore a user's private files.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import messages, paths  # noqa: F401
from cpcommon.errors import TerminalError

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


def _refused(fn, *args):
    with pytest.raises(TerminalError) as caught:
        fn(*args)
    return caught.value.reason


# ── The request id is validated BEFORE it is ever concatenated (FR-004) ──────


def test_a_well_formed_uuid_v4_is_accepted():
    assert paths.validated_request_id(UUID) == UUID


@pytest.mark.parametrize(
    "bad",
    [
        "",
        None,
        123,
        "not-a-uuid",
        # A v1 uuid: right shape, wrong version nibble. Accepting it would not be a security
        # hole on its own, but the browser mints v4 and a v1 leaks a MAC address and a
        # timestamp into a key the user can read in their own file browser.
        "9f2c1b8e-4c1a-1b2f-8d3e-1a2b3c4d5e6f",
        # The two that matter: a key separator and a traversal segment. Either would let a
        # request id decide where in the bucket the archive lands.
        "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f/../evil",
        "../../etc",
        "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f/extra",
    ],
)
def test_anything_that_is_not_a_uuid_v4_is_refused_before_it_becomes_a_key(bad):
    assert _refused(paths.validated_request_id, bad) == "invalid_request"


def test_the_id_is_lowercased_so_one_archive_has_exactly_one_prefix():
    """S3 keys are case-sensitive. A re-submitted id in different case would open a SECOND
    archive under a name that reads identically in every message and every listing."""
    assert paths.validated_request_id(UUID.upper()) == UUID


@pytest.mark.parametrize(
    "builder",
    [
        lambda bad: paths.archive_root("personal", "alice", bad),
        lambda bad: paths.receipt_root("alice", bad),
        lambda bad: paths.receipt_key("alice", bad),
    ],
)
def test_every_builder_validates_the_id_rather_than_trusting_its_caller(builder):
    """The front door is not the only caller, and a helper that trusts its input is a helper
    that will one day be handed something else."""
    assert _refused(builder, "../evil") == "invalid_request"


# ── The kind segment, and the collision it exists to prevent ─────────────────


def test_a_personal_archive_is_partitioned_under_personal():
    assert paths.archive_root("personal", "alice", UUID) == f"personal/alice/archive/{UUID}/"


def test_a_shared_archive_is_partitioned_under_shared():
    assert paths.archive_root("shared", "alice", UUID) == f"shared/alice/archive/{UUID}/"


def test_a_user_and_a_space_of_the_SAME_NAME_do_not_share_an_archive_prefix():
    """THE REASON THE KIND SEGMENT EXISTS, asserted as the property rather than the string.

    Shared-space names are made unique against the shared-space REGISTRY only; nothing
    anywhere checks a proposed space name against the User Pool, so a user `alice` and a
    space `alice` can both exist today. Flat, they would share one archive prefix — and
    since SPEC-170 authorizes a restore by SPACE and then reads whatever sits at that
    prefix, a member of space `alice` could restore user `alice`'s files into the shared
    space.
    """
    personal = paths.archive_root("personal", "alice", UUID)
    shared = paths.archive_root("shared", "alice", UUID)

    assert personal != shared
    assert not personal.startswith(shared)
    assert not shared.startswith(personal)


def test_an_unknown_kind_is_refused_rather_than_defaulted():
    """Guessing wrong puts one namespace's data where the other's restore will read it."""
    assert _refused(paths.archive_root, "team", "alice", UUID) == "forbidden"


def test_an_empty_space_name_is_refused():
    assert _refused(paths.archive_root, "personal", "", UUID) == "forbidden"


# ── The receipt carries NO kind segment, and needs none ──────────────────────


def test_the_receipt_sits_at_the_spaces_own_root():
    assert paths.receipt_root("alice", UUID) == f"alice/archive/{UUID}/"
    assert paths.receipt_key("alice", UUID) == f"alice/archive/{UUID}/receipt.txt"


def test_the_receipt_path_carries_no_kind_segment_and_needs_none():
    """The asymmetry with `archive_root` is the whole point of both. Receipts live in each
    space's OWN bucket, so a user `alice` and a space `alice` cannot collide there and the
    partitioning would be noise; the archive bucket is the one place the two namespaces meet,
    so there it is load-bearing.

    An earlier version of this test asserted `receipt_key(…) == receipt_key(…)` with identical
    arguments — a fork whose two operands always agree, which stayed green with `receipt_key`
    returning the empty string. Measured.
    """
    receipt = paths.receipt_key("alice", UUID)
    archived = paths.archive_root("personal", "alice", UUID)

    assert not receipt.startswith(("personal/", "shared/"))
    assert "personal" not in receipt and "shared" not in receipt
    assert archived.startswith("personal/")
    assert receipt.startswith("alice/")


# ── The origin round-trip: the receipt is a report, not a record ─────────────


def test_an_archived_key_keeps_everything_below_the_source_root():
    prefix = paths.archive_root("personal", "alice", UUID)

    assert paths.archived_key(prefix, "alice/", "alice/reports/q1.csv") == f"{prefix}reports/q1.csv"


def test_the_origin_is_reconstructed_with_no_lookup_at_all():
    """SPEC-170 rebuilds every restore destination by listing the archive prefix and running
    each key through this, so a lost, truncated or hand-edited receipt cannot make a restore
    wrong. The manifest is a cross-check that can only fire when something is already broken."""
    prefix = paths.archive_root("personal", "alice", UUID)

    assert paths.origin_key(f"{prefix}reports/q1.csv", prefix, "alice/") == "alice/reports/q1.csv"


@pytest.mark.parametrize(
    "key",
    ["alice/reports/q1.csv", "alice/a", "alice/deep/nested/path/with spaces/f.txt", "alice/x/"],
)
def test_archived_key_and_origin_key_are_exact_inverses(key):
    prefix = paths.archive_root("shared", "marketing", UUID)
    archived = paths.archived_key(prefix, "alice/", key)

    assert paths.origin_key(archived, prefix, "alice/") == key


def test_an_object_outside_the_source_root_cannot_be_archived():
    """A listing cannot normally produce one. It fails rather than slicing the wrong length,
    because a mis-sliced key re-roots the object and its restore would put it back somewhere
    else."""
    prefix = paths.archive_root("personal", "alice", UUID)

    assert _refused(paths.archived_key, prefix, "alice/", "bob/secrets.csv") == "forbidden"


def test_a_key_outside_the_archive_prefix_has_no_origin():
    prefix = paths.archive_root("personal", "alice", UUID)

    assert _refused(paths.origin_key, "personal/bob/archive/x/f", prefix, "alice/") == "forbidden"


def test_the_archive_prefix_ITSELF_has_no_origin():
    """A zero-byte folder placeholder is a legal listing result, and reconstructing it would
    name the space ROOT — a restore destination that is a whole space rather than an object."""
    prefix = paths.archive_root("personal", "alice", UUID)

    assert _refused(paths.origin_key, prefix, prefix, "alice/") == "forbidden"


# ── Containment is NOT here, and that is the point (SPEC-156) ────────────────


def test_arcommon_does_not_carry_its_own_containment_rule():
    """The rule that decides whether a key is inside the caller's own space is an ALGORITHM,
    and a second copy of it is a second place a cross-tenant read can be introduced. It moved
    to cpcommon.paths with this spec, shared with file-send, rather than being copied here.

    Asserted against the module source so a future edit that reintroduces one fails here
    rather than in a review nobody runs.
    """
    source = pathlib.Path(paths.__file__).read_text()

    assert "def assert_inside_root" not in source
    assert "def has_dot_segment" not in source
    assert "def normalize_root" not in source
    assert "from cpcommon.paths import" in source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
