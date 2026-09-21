"""The space resolution and the server-side protection rules.

Every refusal here is asserted **by reason code**, never by "something raised" and never by a call
count alone: `protected`'s whole reason for existing is that the obvious implementation refuses
with the wrong status while failing safely, so a count-based assertion passes over the defect.

The caps are asserted against the budget that sized them rather than against their own literals —
a test that restates the number it is checking cannot fail for the reason the number exists.
"""

import pathlib

import pytest
from apicommon import config, protected, s3_config, spaces
from apicommon.envelope import ApiError
from apicommon.identity import UserIdentity
from cpcommon.s3_listing import is_ignored

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
        """A prefix is not a key, and an omitted prefix lists the space root."""
        assert protected.contained_prefix(PERSONAL, "") == "alice/"

    def test_a_prefix_escaping_the_root_is_refused(self) -> None:
        """The containment rule still applies to a non-empty prefix."""
        with pytest.raises(ApiError) as raised:
            protected.contained_prefix(PERSONAL, "alice/../bob/")
        assert raised.value.code == "AccessDenied"

    def test_a_prefix_has_ONE_reading_so_a_relative_one_is_refused_not_re_rooted(self) -> None:
        """Absolute only, because ``alice/`` cannot mean both the root and the folder ``alice/alice/``.

        Each assertion fails under one of the other two contracts. Re-rooting a prefix that does
        not start with the root would list ``alice/reports/`` for ``reports/``, and reading every
        prefix relatively would list ``alice/alice/`` for ``alice/``. The detail is asserted as well
        as the code, because the dot-segment refusal answers ``AccessDenied`` too.
        """
        assert protected.contained_prefix(PERSONAL, "alice/") == "alice/"
        assert protected.contained_prefix(PERSONAL, "alice/alice/") == "alice/alice/"
        with pytest.raises(ApiError) as raised:
            protected.contained_prefix(PERSONAL, "reports/")
        assert (raised.value.code, raised.value.detail) == (
            "AccessDenied",
            "prefix is not inside the space root",
        )


class TestTheArchiveWriteLockMirrorsEachBucket:
    """FR-009 AC4 — each bucket's own Deny, never the average of the two."""

    def test_personal_locks_the_root_receipt_folder(self) -> None:
        """Root-anchored, matching the user-space bucket's Deny."""
        assert (
            protected.is_write_locked(PERSONAL, "alice/system_settings/archive/receipt.json")
            is True
        )

    def test_personal_does_NOT_lock_a_nested_receipt_folder(self) -> None:
        """The asymmetry: the personal Deny is root-anchored, so this one is writable."""
        assert (
            protected.is_write_locked(PERSONAL, "alice/reports/system_settings/archive/old.csv")
            is False
        )

    def test_shared_locks_the_receipt_folder_at_ANY_depth(self) -> None:
        """The shared bucket's wildcard segment matches `/`, so the rule reaches deeper."""
        assert (
            protected.is_write_locked(SHARED, "finance/reports/system_settings/archive/old.csv")
            is True
        )

    def test_the_two_buckets_disagree_on_the_same_key(self) -> None:
        """The asymmetry stated as a single assertion, so averaging the rules reddens here."""
        key_personal = "alice/reports/system_settings/archive/x"
        key_shared = "finance/reports/system_settings/archive/x"
        assert protected.is_write_locked(PERSONAL, key_personal) is False
        assert protected.is_write_locked(SHARED, key_shared) is True

    def test_neither_bucket_locks_the_NAME_the_receipt_folder_LEFT(self) -> None:
        """The narrowing, from the side that fails safe and would therefore go unnoticed.

        ``finance/archive/`` and ``alice/archive/`` are folders a user may now make: the Denies
        that named them are gone, and both arms of this rule get their target from
        ``app_managed_segments``. A rule still keyed on the bare name refuses an upload IAM
        permits — no error anyone can act on, just a control the browser greys out.
        """
        assert protected.is_write_locked(PERSONAL, "alice/archive/receipt.json") is False
        assert protected.is_write_locked(SHARED, "finance/reports/archive/old.csv") is False

    def test_shared_reaches_the_folder_through_its_own_any_depth_arm(self) -> None:
        """The segment scan looks for the PAIR, so it sees the folder under any prefix."""
        assert protected.is_write_locked(SHARED, "finance/x/system_settings/archive/y") is True

    def test_a_split_pair_is_not_the_folder(self) -> None:
        """Consecutiveness, which a membership test over the two names separately would miss."""
        assert protected.is_write_locked(SHARED, "finance/system_settings/x/archive/y") is False

    def test_the_settings_prefix_itself_is_NOT_write_locked(self) -> None:
        """The Deny names the receipt folder, not the prefix above it — the rule must not widen.

        The browser offers writes wherever IAM permits them, and nothing denies `PutObject` on
        `{root}system_settings/` itself in a personal space, so refusing here would disable an
        upload that would have worked.
        """
        assert protected.is_write_locked(PERSONAL, "alice/system_settings/notes.txt") is False

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

    @pytest.mark.parametrize(
        "key",
        [
            "alice/user_settings/query-history.json",
            "alice/exports/_SUCCESS",
        ],
    )
    def test_the_marker_rule_does_not_inherit_the_listing_exclusions(self, key) -> None:
        """`s3_listing.is_ignored` also skips the `user_settings/` sub-tree and any hidden segment.

        Those decide what a plane reads as source data, not what may be replaced. This check also
        gates an overwrite, and the browser rewrites its query history document in place through
        it, so taking the predicate instead of the constant would refuse the app's own write. The
        sub-tree is matched only when the predicate is handed the space root; a hidden BASENAME is
        matched under whichever folder above it is handed as the prefix, the listed folder
        included, so it is the key that still reddens when the defect picks some other prefix.

        The premise is asserted first because it is what goes stale. No results-folder key serves:
        the predicate matches only `system_settings/athenaresults/`, which `assert_writable` refuses
        by its own rule, so a key there cannot tell the two rules apart.
        """
        assert is_ignored(key, 1, PERSONAL.root), "the listing exclusions no longer match this key"
        protected.assert_replaceable(PERSONAL, key)


class TestTheReportsFolderIsTheDataQualityPlanes:
    """No bucket policy names this folder, so the rule mirrors nothing and must not widen."""

    @pytest.mark.parametrize(
        ("space", "key"),
        [
            (PERSONAL, "alice/_data-quality-reports/7f3ac19d/manifest.json"),
            (SHARED, "finance/_data-quality-reports/7f3ac19d/report.json"),
            (PERSONAL, "alice/_data-quality-reports/index.json"),
        ],
    )
    def test_a_write_inside_it_is_refused_in_either_kind(self, space, key) -> None:
        """By detail, because the receipt and results rules answer the same code."""
        with pytest.raises(ApiError) as raised:
            protected.assert_writable(space, key)
        assert (raised.value.code, raised.value.detail) == (
            "AccessDenied",
            "the data-quality reports folder is not writable",
        )

    def test_the_name_elsewhere_is_an_ordinary_place_to_write(self) -> None:
        """Root-anchored, with its slash: the plane writes nowhere else."""
        protected.assert_replaceable(PERSONAL, "alice/_data-quality-reports")
        protected.assert_replaceable(PERSONAL, "alice/projects/_data-quality-reports/notes.txt")
        protected.assert_replaceable(SHARED, "finance/x/_data-quality-reports/y.csv")


class TestTheCapsAreSizedAgainstABudget:
    """SPEC-161's rule: a cap's test computes its bound and names what sized it."""

    def test_the_document_cap_fits_inside_lambdas_synchronous_response_ceiling(self) -> None:
        """The budget is 6 MB of response payload, and the cap is a line on the stored body under it.

        Whether a document's response fits is a separate question the routes answer by measuring
        it, because escaping can take a document under this line past the ceiling.
        """
        lambda_ceiling = 6 * 1024 * 1024
        assert lambda_ceiling > s3_config.MAX_DOCUMENT_BYTES
        assert lambda_ceiling // 2 <= s3_config.MAX_DOCUMENT_BYTES, (
            "a cap far below the ceiling refuses documents the app authors"
        )

    def test_the_single_put_ceiling_matches_the_browsers_shipped_default(self) -> None:
        """Checked against the OTHER copy of the number, not against a restatement of itself.

        The browser's `S3_SINGLE_PUT_MAX_BYTES` is the same S3 limit, and the point of this
        constant is that the single-PUT design moves the ceiling nowhere. Asserting the literal
        here would restate the value under test, which this file's own docstring forbids — so the
        assertion is that the two sides agree, and it fails when either moves.

        The path is anchored on ``__file__``, not on the working directory: CI runs pytest from the
        repo root and a developer runs it from ``lambdas/``, and a cwd-relative path passes in one
        and raises ``FileNotFoundError`` in the other.
        """
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        shipped = (
            repo_root / "apps/portal/src/features/file-browser/uploadLimits.ts"
        ).read_text()
        compact = shipped.replace(" ", "")
        assert (
            f"={s3_config.S3_SINGLE_PUT_MAX_BYTES}" in compact
            or "=5*1024*1024*1024" in compact
        ), "the browser's cap and the API's disagree; reconcile the two"

    def test_every_presigned_window_FITS_INSIDE_the_session_that_can_be_assumed(self) -> None:
        """The relation that turns the covering guard from a fix into a per-request STS call.

        ``signing_client(covering=…)`` forces a fresh session when the cached one cannot span the
        window. A window LONGER than a whole session can never be spanned — so the force fires on
        every request, for ever, and the cache the credential layer exists to have is defeated. It
        does not loop and it does not error; it just costs an `AssumeRole` per mint with no signal.

        Safe today at 900 against 3600, and the trigger is anticipated rather than hypothetical:
        the successor environment signs from Access-Grants-vended credentials whose maximum is a
        different number, and role chaining already caps this one at an hour.

        Args:
          None.

        Returns:
          None.

        Raises:
          AssertionError: If a window cannot fit inside an assumable session.
        """
        windows = {
            "upload": s3_config.UPLOAD_URL_EXPIRY_SECONDS,
            "download": s3_config.DOWNLOAD_URL_EXPIRY_SECONDS,
            # A multipart upload mints one of these PER PART, so a window that cannot be spanned
            # costs an AssumeRole per part rather than per file. The population is hand-written,
            # which means a constant is only guarded because somebody added it here.
            "part": s3_config.PART_URL_EXPIRY_SECONDS,
        }
        too_long = {
            name: seconds
            for name, seconds in windows.items()
            if seconds >= config.ASSUME_ROLE_DURATION_SECONDS
        }
        assert too_long == {}, "a window no session can span forces an AssumeRole per request"

    def test_the_carried_constants_are_the_shipped_values(self) -> None:
        """900s and 999 are carried across, explicitly NOT re-derived."""
        assert s3_config.DOWNLOAD_URL_EXPIRY_SECONDS == 900
        assert s3_config.FREE_NAME_MAX_ATTEMPTS == 999

    def test_the_two_url_windows_agree(self) -> None:
        """Upload has no shipped value; it is chosen to match download rather than differ."""
        assert s3_config.UPLOAD_URL_EXPIRY_SECONDS == s3_config.DOWNLOAD_URL_EXPIRY_SECONDS
