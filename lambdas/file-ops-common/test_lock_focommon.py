"""The per-space lock's binding: the digest, the key, and the wiring to the shared protocol.

The protocol itself is tested where it lives. What is asserted here is what this plane owns — and
above all that the digest is the SAME one the API hashes for the queue's ``MessageGroupId``,
because nothing at runtime would notice if it were not.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

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

    The API hashes ``{bucket}/{spaceName}/`` to derive ``MessageGroupId``; this hashes the same
    string to derive the lock key. A difference of one character — a missing trailing slash, say —
    means delivery is ordered per space while the lock is keyed by something else, and NOTHING at
    runtime reports that: operations simply stop being serialized.
    """
    assert lock.space_digest(_VECTOR_BUCKET, _VECTOR_SPACE) == _VECTOR_DIGEST


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
