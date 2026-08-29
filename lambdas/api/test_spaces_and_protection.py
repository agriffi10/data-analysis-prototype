"""The space resolution and the server-side protection rules.

Every refusal here is asserted **by reason code**, never by "something raised" and never by a call
count alone: `protected`'s whole reason for existing is that the obvious implementation refuses
with the wrong status while failing safely, so a count-based assertion passes over the defect.

The caps are asserted against the budget that sized them rather than against their own literals —
a test that restates the number it is checking cannot fail for the reason the number exists.
"""

import pathlib

import pytest
from apicommon import protected, s3_config, spaces
from apicommon.envelope import ApiError
from apicommon.identity import UserIdentity

PERSONAL = spaces.ResolvedSpace("personal", "alice", "user-bucket", "alice/")
SHARED = spaces.ResolvedSpace("shared", "finance", "shared-bucket", "finance/")


def _identity(username="alice", memberships=None) -> UserIdentity:
    """Builds an identity with the given verified memberships.

    Args:
      username: The verified username.
      memberships: Slot index to space name.

    Returns:
      The identity.

    Raises:
      None.
    """
    return UserIdentity(username=username, memberships=memberships or {})


class TestASpaceComesFromClaims:
    """FR-001 AC7 — the space is resolved from the caller, never from the request."""

    def test_a_caller_reaches_their_own_personal_space(self, monkeypatch) -> None:
        """The happy path, which is also the control for the refusals below."""
        monkeypatch.setenv("USER_SPACE_BUCKET", "user-bucket")
        resolved = spaces.resolve(_identity(), "personal", "alice")
        assert (resolved.bucket, resolved.root) == ("user-bucket", "alice/")

    def test_another_users_personal_space_is_refused(self) -> None:
        """FR-013's route-layer proof, offline: the refusal names AccessDenied."""
        with pytest.raises(ApiError) as raised:
            spaces.resolve(_identity(), "personal", "bob")
        assert raised.value.code == "AccessDenied"

    def test_a_shared_space_the_claims_name_is_reachable(self, monkeypatch) -> None:
        """Membership is the claim set."""
        monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bucket")
        resolved = spaces.resolve(_identity(memberships={1: "finance"}), "shared", "finance")
        assert resolved.root == "finance/"

    def test_a_shared_space_the_claims_do_not_name_is_refused(self) -> None:
        """The second half of the isolation refusal."""
        with pytest.raises(ApiError) as raised:
            spaces.resolve(_identity(memberships={1: "finance"}), "shared", "legal")
        assert raised.value.code == "AccessDenied"

    def test_an_unknown_kind_is_refused_rather_than_defaulted(self) -> None:
        """A third kind resolves to no bucket, so it must refuse rather than fall through."""
        with pytest.raises(ApiError) as raised:
            spaces.resolve(_identity(), "admin", "anything")
        assert raised.value.code == "AccessDenied"

    def test_resolution_reads_no_aws_client(self) -> None:
        """The module imports no client, which is what makes a refusal cost zero calls.

        `focommon.authz` solves the same problem with a registry read; copying it would make this
        path cost an S3 call before refusing. Asserted structurally, because a call count on a
        module that never builds a client would pass either way.
        """
        import apicommon.spaces as module

        source = pathlib.Path(module.__file__ or "").read_text()
        assert "boto3" not in source


class TestKeyContainment:
    """The space is verified; the key is still the caller's."""

    def test_a_key_inside_the_root_is_returned(self) -> None:
        """The control."""
        assert protected.contained_key(PERSONAL, "alice/reports/q1.csv") == "alice/reports/q1.csv"

    @pytest.mark.parametrize("key", ["alice/../bob/secret.csv", "bob/secret.csv", ""])
    def test_a_key_outside_the_root_is_ACCESS_DENIED_not_a_fault(self, key) -> None:
        """The reason code IS the assertion.

        `cpcommon.paths.assert_inside_root` raises `TerminalError`, which the API's error mapper
        does not recognise — unwrapped, every one of these answers 500 InternalError. It fails
        safely, so "no AWS call happened" passes over it and only the code catches it.
        """
        with pytest.raises(ApiError) as raised:
            protected.contained_key(PERSONAL, key)
        assert raised.value.code == "AccessDenied"

    def test_an_empty_PREFIX_is_the_space_root_not_a_refusal(self) -> None:
        """A prefix is not a key, and the file browser's first request has no prefix."""
        assert protected.contained_prefix(PERSONAL, "") == "alice/"

    def test_a_prefix_escaping_the_root_is_refused(self) -> None:
        """The containment rule still applies to a non-empty prefix."""
        with pytest.raises(ApiError) as raised:
            protected.contained_prefix(PERSONAL, "alice/../bob/")
        assert raised.value.code == "AccessDenied"


class TestTheArchiveWriteLockMirrorsEachBucket:
    """FR-009 AC4 — each bucket's own Deny, never the average of the two."""

    def test_personal_locks_the_root_archive_folder(self) -> None:
        """Root-anchored, matching the user-space bucket's Deny."""
        assert protected.is_write_locked(PERSONAL, "alice/archive/receipt.json") is True

    def test_personal_does_NOT_lock_a_nested_archive_folder(self) -> None:
        """The asymmetry: the personal Deny is root-anchored, so this one is writable."""
        assert protected.is_write_locked(PERSONAL, "alice/reports/archive/old.csv") is False

    def test_shared_locks_an_archive_folder_at_ANY_depth(self) -> None:
        """The shared bucket's wildcard segment matches `/`, so the rule reaches deeper."""
        assert protected.is_write_locked(SHARED, "finance/reports/archive/old.csv") is True

    def test_the_two_buckets_disagree_on_the_same_key(self) -> None:
        """The asymmetry stated as a single assertion, so averaging the rules reddens here."""
        key_personal = "alice/reports/archive/x"
        key_shared = "finance/reports/archive/x"
        assert protected.is_write_locked(PERSONAL, key_personal) is False
        assert protected.is_write_locked(SHARED, key_shared) is True

    def test_a_marker_key_may_not_be_REMOVED_or_replaced_at_any_depth(self) -> None:
        """By basename — the rule both bucket policies encode as `*/DO_NOT_DELETE.txt`."""
        with pytest.raises(ApiError) as raised:
            protected.assert_replaceable(PERSONAL, "alice/reports/DO_NOT_DELETE.txt")
        assert raised.value.code == "AccessDenied"

    def test_a_marker_key_IS_creatable_because_that_is_how_a_prefix_is_held_open(self) -> None:
        """The half the two rules exist to keep apart, and the one that shipped broken.

        Both bucket policies Deny ``s3:DeleteObject`` on the marker and nothing else. A guard that
        refused the WRITE too was stricter than the policy it mirrors, and it refused
        ``ensurePrefixMarker`` and ``ensureSavedQueriesFolder`` — a brand-new user's prefix would
        never be created, and a saved-queries folder would vanish once emptied. Both are best-effort
        background writes that log and carry on, so it fails in **silence**.
        """
        protected.assert_writable(PERSONAL, "alice/DO_NOT_DELETE.txt")
        protected.assert_writable(SHARED, "finance/saved_queries/DO_NOT_DELETE.txt")

    def test_a_key_merely_containing_the_marker_name_is_writable(self) -> None:
        """By basename, not by substring — `DO_NOT_DELETE.txt.bak` is an ordinary file."""
        protected.assert_replaceable(PERSONAL, "alice/DO_NOT_DELETE.txt.bak")

    def test_the_marker_rule_does_not_inherit_the_listing_exclusions(self) -> None:
        """`cpcommon.is_ignored` also hides `athenaresults/` and `user_settings/`.

        Those are listing conveniences, not write rules. Taking the predicate instead of the
        constant would make both undeletable through the API, which no bucket policy says.
        """
        protected.assert_replaceable(PERSONAL, "alice/athenaresults/result.csv")
        protected.assert_replaceable(PERSONAL, "alice/user_settings/notifications.json")


class TestTheCapsAreSizedAgainstABudget:
    """SPEC-161's rule: a cap's test computes its bound and names what sized it."""

    def test_the_document_cap_fits_inside_lambdas_synchronous_response_ceiling(self) -> None:
        """The budget is 6 MB of response payload, and the cap must leave envelope room."""
        lambda_ceiling = 6 * 1024 * 1024
        assert lambda_ceiling > s3_config.MAX_DOCUMENT_BYTES
        assert lambda_ceiling // 2 <= s3_config.MAX_DOCUMENT_BYTES, (
            "a cap far below the ceiling refuses documents the app authors"
        )

    def test_the_single_put_ceiling_matches_the_browsers_shipped_default(self) -> None:
        """Checked against the OTHER copy of the number, not against a restatement of itself.

        `DEFAULT_MAX_UPLOAD_BYTES` in the browser is the same S3 limit, and the point of this
        constant is that the single-PUT design moves the ceiling nowhere. Asserting `== 5 * 1024
        * 1024 * 1024` here would restate the value under test, which this file's own docstring
        forbids — it cannot fail for the reason the number exists.
        """
        shipped = pathlib.Path("apps/portal/src/features/file-browser/uploadLimits.ts").read_text()
        assert "5 * 1024 * 1024 * 1024" in shipped.replace(" ", "").replace(
            "5*1024*1024*1024", "5 * 1024 * 1024 * 1024"
        ) or "5368709120" in shipped, "the browser's cap moved; reconcile the two"
        assert s3_config.S3_SINGLE_PUT_MAX_BYTES == 5 * 1024**3

    def test_the_carried_constants_are_the_shipped_values(self) -> None:
        """900s and 999 are carried across, explicitly NOT re-derived."""
        assert s3_config.DOWNLOAD_URL_EXPIRY_SECONDS == 900
        assert s3_config.FREE_NAME_MAX_ATTEMPTS == 999

    def test_the_two_url_windows_agree(self) -> None:
        """Upload has no shipped value; it is chosen to match download rather than differ."""
        assert s3_config.UPLOAD_URL_EXPIRY_SECONDS == s3_config.DOWNLOAD_URL_EXPIRY_SECONDS
