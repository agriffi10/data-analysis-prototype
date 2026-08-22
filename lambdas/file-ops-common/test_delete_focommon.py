"""Unit tests for focommon.delete — the module that removes a user's own files.

Versioning is off in both data buckets, so every case here is one where the wrong implementation
still looks right: a partial batch read as complete, a replayed verb reporting its predecessor's
work as failures, a 409 collapsed into a 412, and an item refused over the whole list instead of on
its own.

Runnable under pytest or directly: python3 test_delete_focommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from focommon import delete


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    """Answers heads from a table and records every delete batch it is handed."""

    def __init__(self, heads=None, errors=None, raise_on_delete=None):
        self._heads = heads or {}
        self._errors = errors or {}
        self._raise = raise_on_delete
        self.batches = []
        self.headed = []

    def head_object(self, Bucket, Key):
        self.headed.append(Key)
        answer = self._heads.get(Key)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise _S3Error("NoSuchKey")
        return {"ETag": answer}

    def delete_objects(self, Bucket, Delete):
        if self._raise:
            raise self._raise
        self.batches.append(Delete)
        keys = [obj["Key"] for obj in Delete["Objects"]]
        return {
            "Errors": [
                {"Key": key, "Code": self._errors[key]} for key in keys if key in self._errors
            ]
        }


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


# ── The per-item refusal ─────────────────────────────────────────────────────


def test_a_key_outside_the_allowed_prefix_refuses_before_anything_is_issued():
    fake = _install()
    with pytest.raises(TerminalError) as caught:
        delete.assert_item_deletable(["bob/secrets.csv"], "alice/")
    assert caught.value.reason == "forbidden"
    assert fake.batches == []


def test_a_dot_segment_refuses_even_though_it_STARTS_with_the_root():
    """``alice/../bob/x`` passes a prefix test. S3 resolves nothing, so the key names an object that
    almost certainly does not exist — the rule is here because a containment rule that holds only
    while every consumer stays careful is not a rule, and this consumer is the one that deletes."""
    with pytest.raises(TerminalError) as caught:
        delete.assert_item_deletable(["alice/../bob/secrets.csv"], "alice/")
    assert caught.value.reason == "forbidden"


def test_the_protection_marker_refuses_at_ANY_depth():
    with pytest.raises(TerminalError) as caught:
        delete.assert_item_deletable(["alice/deep/nested/DO_NOT_DELETE.txt"], "alice/")
    assert caught.value.reason == "marker_not_deletable"


@pytest.mark.parametrize("folder", ["athenaresults", "user_settings", "archive"])
def test_a_portal_managed_folder_refuses_at_any_depth_MIRRORING_IAM(folder):
    """Any-depth because the role's Deny is any-depth — it cannot be root-anchored, since an IAM
    Resource wildcard matches "/" and this role carries no principal tag. Mirroring the browser's
    root-anchored rule instead would let the batch reach S3 and fail part way through."""
    with pytest.raises(TerminalError) as caught:
        delete.assert_item_deletable([f"alice/reports/{folder}/r.csv"], "alice/")
    assert caught.value.reason == "delete_refused"


def test_a_folder_NAME_that_merely_contains_a_managed_name_is_fine():
    """``archived/`` is not ``archive/``. Segment equality, never a substring test."""
    delete.assert_item_deletable(["alice/archived/r.csv", "alice/my_user_settings/x"], "alice/")


def test_a_file_NAMED_like_a_managed_folder_is_deletable():
    """The rule is about folders in the path, not the basename — only the marker is a basename
    rule."""
    delete.assert_item_deletable(["alice/reports/archive"], "alice/")


# ── The batch response ───────────────────────────────────────────────────────


def test_a_partial_Errors_array_is_READ_rather_than_inferred_from_the_status():
    """``DeleteObjects`` answers HTTP 200 with the failures inside the body. A response inspected by
    status code alone reads a half-done deletion as complete — the defect this repo has shipped
    once already."""
    _install(
        heads={"alice/a": '"e1"', "alice/b": '"e2"'},
        errors={"alice/b": "InternalError"},
    )

    result = delete.delete_item_keys(
        "user-bkt", ["alice/a", "alice/b"], {"alice/a": '"e1"', "alice/b": '"e2"'}, "alice/", conditional=True
    )

    assert result == {"deleted": 1, "failed": 1, "reason": "source_delete_failed"}


def test_Quiet_is_FALSE_so_the_errors_array_is_populated_at_all():
    fake = _install(heads={"alice/a": '"e1"'})
    delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)
    assert fake.batches[0]["Quiet"] is False


def test_a_412_is_source_changed_and_TERMINAL_for_that_item():
    _install(heads={"alice/a": '"e1"'}, errors={"alice/a": "PreconditionFailed"})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result["reason"] == "source_changed"
    assert result["failed"] == 1


def test_a_409_RAISES_rather_than_becoming_a_permanent_failure():
    """AWS documents the 409 as a concurrent delete or put beating this one, which is retryable —
    where a 412 precondition mismatch is terminal for that item.

    Collapsing the two, as ``cpcommon.cas.is_precondition`` deliberately does for a compare-and-set,
    would turn a retryable conflict into a permanent ``duplicate`` reported to the user.
    """
    _install(heads={"alice/a": '"e1"'}, errors={"alice/a": "ConditionalRequestConflict"})

    with pytest.raises(TransientError):
        delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)


def test_an_ALREADY_ABSENT_key_counts_as_DELETED_which_is_what_makes_a_Retry_safe():
    """The property ``arcommon.delete`` rests its whole replay story on, and the one a conditional
    delete does NOT get for free.

    A verb that deleted five batches of twenty, hit a throttle and retried would find those keys
    gone. Reported as failures, they would turn a completed move into a ``duplicate`` for items that
    moved correctly — and the browser would then invite a re-submit whose source no longer exists.
    """
    _install(heads={}, errors={"alice/a": "NoSuchKey"})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result == {"deleted": 1, "failed": 0, "reason": ""}


def test_an_AccessDenied_is_told_apart_from_a_precondition_mismatch():
    """One is ``delete_refused`` and the other is ``source_changed``; the user is told different
    things and only one of them is their fault."""
    _install(heads={"alice/a": '"e1"'}, errors={"alice/a": "AccessDenied"})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result["reason"] == "delete_refused"


def test_an_UNRECOGNISED_code_fails_the_object_rather_than_passing_it():
    """AWS does not document the batch path's precondition ``Code`` string, so the mapping has to
    fail closed on anything it does not know. A live probe is owed for exactly this reason."""
    _install(heads={"alice/a": '"e1"'}, errors={"alice/a": "SomeCodeAwsAddedLastTuesday"})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result["failed"] == 1
    assert result["reason"] == "source_delete_failed"


# ── The HEAD-compare path, which is the ACTIVE one ───────────────────────────


def test_the_head_compare_path_is_what_runs_by_default():
    """The conditional path is built and gated off. Reading ``ObjectIdentifier``'s members proves
    botocore will SERIALIZE the ETag, not that S3 enforces it — and a serialized-but-ignored
    condition deletes a changed source silently."""
    assert delete.CONDITIONAL_DELETE_ENABLED is False

    fake = _install(heads={"alice/a": '"e1"'})
    delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert fake.headed == ["alice/a"], "the active path did not compare the ETag"
    assert "ETag" not in fake.batches[0]["Objects"][0]


def test_an_object_whose_ETag_MOVED_is_not_deleted():
    """The whole point of comparing: its destination copy holds bytes that are no longer the
    source's, so removing the source would destroy the only current version."""
    fake = _install(heads={"alice/a": '"changed"'})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result == {"deleted": 0, "failed": 1, "reason": "source_changed"}
    assert fake.batches == [], "a changed object was still handed to DeleteObjects"


def test_a_head_that_cannot_be_read_treats_the_object_as_CHANGED():
    """Fail closed. An object this role cannot head is one it must not remove on the strength of an
    ETag it never confirmed."""
    _install(heads={"alice/a": _S3Error("AccessDenied")})

    result = delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert result["reason"] == "source_changed"


def test_a_throttled_head_retries_the_whole_verb_rather_than_deleting_anything():
    fake = _install(heads={"alice/a": _S3Error("SlowDown")})

    with pytest.raises(TransientError):
        delete.delete_item_keys(
"user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=True
)

    assert fake.batches == []


def test_the_capability_probe_reports_False_on_a_client_it_cannot_introspect():
    """A runtime whose model cannot be read takes the path that works everywhere, rather than the
    one that raises ParamValidationError on every deletion."""
    _install()
    assert delete.supports_conditional_delete() is False


# ── Batching ─────────────────────────────────────────────────────────────────


def test_keys_are_batched_at_S3s_own_limit():
    fake = _install(heads={f"alice/{n}": '"e"' for n in range(2500)})
    keys = [f"alice/{n}" for n in range(2500)]

    result = delete.delete_item_keys(
"user-bkt", keys, dict.fromkeys(keys, '"e"'), "alice/", conditional=True
)

    assert [len(batch["Objects"]) for batch in fake.batches] == [1000, 1000, 500]
    assert result["deleted"] == 2500


def test_an_UNCONDITIONAL_deletion_does_not_head_ANYTHING():
    """A ``delete`` operation's deletions are unconditional by design, and the cost of getting this
    wrong is not a wrong answer but a wrong QUESTION: comparing against an ETag nobody supplied
    mismatches every object, and the whole delete reports ``source_changed`` having removed nothing.

    Found by a delete-source fixture rather than reasoned about, which is why the flag is now the
    caller's explicit decision instead of being inferred from whether ETags were passed.
    """
    fake = _install(heads={"alice/a": '"e1"'})

    result = delete.delete_item_keys("user-bkt", ["alice/a"], {}, "alice/", conditional=False)

    assert fake.headed == [], "an unconditional deletion compared an ETag"
    assert result == {"deleted": 1, "failed": 0, "reason": ""}
    assert "ETag" not in fake.batches[0]["Objects"][0]


def test_an_unconditional_deletion_removes_an_object_that_HAS_changed():
    """The point of the distinction: the user asked for this object to go, and it going is correct
    whatever happened to it since."""
    fake = _install(heads={"alice/a": '"totally-different"'})

    result = delete.delete_item_keys(
        "user-bkt", ["alice/a"], {"alice/a": '"e1"'}, "alice/", conditional=False
    )

    assert [obj["Key"] for obj in fake.batches[0]["Objects"]] == ["alice/a"]
    assert result["deleted"] == 1
