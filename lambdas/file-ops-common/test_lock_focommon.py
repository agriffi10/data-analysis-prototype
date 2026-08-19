"""The per-space lock's binding: the digest, the key, and the wiring to the shared protocol.

The protocol itself is tested where it lives. What is asserted here is what this plane owns — and
above all that the digest is the SAME one the browser hashes for the queue's ``MessageGroupId``,
because nothing at runtime would notice if it were not.
"""

import hashlib
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon import lock as shared_lock
from focommon import config, lock

#: The pinned cross-runtime vector, COMPUTED INDEPENDENTLY IN BOTH RUNTIMES rather than copied from
#: this one's output — a value copied from Python asserts only that Python is self-consistent, which
#: is not the property that matters. The browser's own suite asserts the identical pair, so a change
#: on either side fails a test rather than silently splitting the lock from the queue's ordering.
_VECTOR_BUCKET = "dat-prod-user-space"
_VECTOR_SPACE = "alice"
_VECTOR_DIGEST = "fdeab79570d11a19a05ce52dba54a66b83597ae4fb6eecfd1a378e83b1b6a039"


def test_the_digest_matches_the_pinned_cross_runtime_vector():
    """The one assertion that keeps the lock and the queue talking about the same space.

    The browser hashes ``{bucket}/{spaceName}/`` to derive ``MessageGroupId``; this hashes the same
    string to derive the lock key. A difference of one character — a missing trailing slash, say —
    means delivery is ordered per space while the lock is keyed by something else, and NOTHING at
    runtime reports that: operations simply stop being serialized.
    """
    assert lock.space_digest(_VECTOR_BUCKET, _VECTOR_SPACE) == _VECTOR_DIGEST


def test_the_trailing_slash_is_INSIDE_what_is_hashed():
    """Stated separately because it is the detail a reimplementation drops, and the vector alone
    would not say which of several plausible canonical strings produced it."""
    expected = hashlib.sha256(f"{_VECTOR_BUCKET}/{_VECTOR_SPACE}/".encode()).hexdigest()

    assert lock.space_digest(_VECTOR_BUCKET, _VECTOR_SPACE) == expected


def test_a_root_with_or_without_its_slash_is_the_same_space():
    assert lock.space_digest("b", "alice") == lock.space_digest("b", "alice/")


def test_two_spaces_never_share_a_lock():
    """The failure this prevents is silent: one digest for two spaces serializes unrelated work,
    and one digest for one space across two buckets serializes a personal space against a shared
    one that happens to share its name."""
    assert lock.space_digest("b", "alice") != lock.space_digest("b", "alice2")
    assert lock.space_digest("user-bkt", "sales") != lock.space_digest("shared-bkt", "sales")


@pytest.mark.parametrize("bucket,root", [("", "alice"), ("b", ""), ("", "")])
def test_an_unidentifiable_space_raises_rather_than_collapsing_onto_one_digest(bucket, root):
    """An empty part would hash to a constant, putting every space behind one lock and serializing
    the entire plane — which looks like correctness until it looks like a deadlock."""
    with pytest.raises(ValueError, match="needs a bucket and a root"):
        lock.space_digest(bucket, root)


def test_the_key_cannot_escape_its_prefix_whatever_the_space_is_called():
    """Keying by the digest rather than the path makes the traversal question unaskable rather
    than merely answered: a hex digest has no slashes and no dot segments."""
    key = lock.lock_key("b", "../../etc/")

    assert key.startswith(f"{config.LOCK_PREFIX}/")
    assert re.fullmatch(rf"{re.escape(config.LOCK_PREFIX)}/[0-9a-f]{{64}}\.json", key)


def test_the_protocol_is_the_SHARED_one_and_not_a_second_copy():
    """The whole reason the protocol was extracted. Asserted as identity rather than behaviour,
    because a second implementation that behaves the same today is exactly what drifts."""
    assert lock.acquire.__module__ == "focommon.lock"
    source = (pathlib.Path(__file__).parent / "focommon" / "lock.py").read_text()

    assert "_lock.acquire(" in source and "_lock.release(" in source
    for forbidden in ("IfNoneMatch", "IfMatch", "is_precondition", "put_object"):
        assert forbidden not in source, (
            f"{forbidden!r} in this plane's lock module means the protocol was re-implemented "
            f"rather than bound"
        )


def test_the_wording_is_this_planes_and_the_fields_avoid_the_reserved_names():
    """A binding whose fields collided with the protocol's own would raise on the steal or the
    refusal branch alone — the rarest paths, and the ones a test is least likely to reach."""
    assert lock.WORDING.acquired == "space lock acquired"
    shared_lock.assert_fields_are_free({"space_bucket": "b", "space_root": "alice/"})


def test_the_stale_threshold_this_plane_binds_is_its_own():
    """Read from this plane's config rather than inherited from the module it binds, because the
    threshold is only meaningful against THIS machine's ceiling."""
    assert config.STALE_LOCK_SECONDS > config.MACHINE_TIMEOUT_SECONDS
