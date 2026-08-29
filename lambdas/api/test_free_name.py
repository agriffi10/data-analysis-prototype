"""The free-name route: one call per gesture, and exhaustion told apart from failure.

The head count is the assertion that matters. A route that probed every candidate regardless, or
that stopped early on an error, would return the same name for the same fixture — only counting
the calls separates them.
"""

import json

import pytest
import router
from apicommon import contract, s3_config
from conftest import bearer
from routes.objects_free_name import numbered_name


class _Missing(Exception):
    """A botocore-shaped absence."""

    def __init__(self, code="NoSuchKey"):
        """Builds it.

        Args:
          code: The service error code.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": ""}}


class Probing:
    """A client where a named set of keys exists and everything else does not.

    Attributes:
      heads: Every key it was asked about, in order.
    """

    def __init__(self, taken=(), error_on=None):
        """Builds the fake.

        Args:
          taken: Keys that exist.
          error_on: A key that raises a NON-absence error, to prove the walk stops.

        Returns:
          None.

        Raises:
          None.
        """
        self._taken = set(taken)
        self._error_on = error_on
        self.heads = []

    def head_object(self, **kwargs):
        """Reports whether the key is taken.

        Args:
          **kwargs: The head request.

        Returns:
          A head response when the key is taken.

        Raises:
          _Missing: When absent, or with a denial code for the configured key.
        """
        key = kwargs["Key"]
        self.heads.append(key)
        if key == self._error_on:
            raise _Missing("AccessDenied")
        if key in self._taken:
            return {"ContentLength": 1}
        raise _Missing()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Buckets and a probing client.

    Args:
      monkeypatch: The pytest fixture.

    Yields:
      A factory installing a fake.

    Raises:
      None.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "user-bucket")
    monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bucket")

    def _install(fake):
        monkeypatch.setattr("apicommon.identity.user_client", lambda service, caller: fake)
        return fake

    yield _install


def _ask(prefix="alice/", base="report.csv", kind="file"):
    """Drives the route.

    Args:
      prefix: The folder to search.
      base: The original leaf name.
      kind: file or folder.

    Returns:
      The router's answer.

    Raises:
      None.
    """
    return router.route(
        "POST",
        "/v1/objects/free-name",
        bearer(),
        "rq",
        {
            "space": {"kind": "personal", "name": "alice"},
            "prefix": prefix,
            "baseName": base,
            "kind": kind,
        },
        None,
    )


class TestItStopsAtTheFirstFreeName:
    """One head per candidate, and no more."""

    def test_a_prefix_holding_1_and_2_costs_exactly_three_heads(self, _env) -> None:
        """The count IS the assertion — the name alone cannot tell the implementations apart."""
        fake = _env(Probing(taken={"alice/report (1).csv", "alice/report (2).csv"}))
        answer = _ask()
        assert json.loads(answer["body"])["name"] == "report (3).csv"
        assert len(fake.heads) == 3

    def test_an_empty_folder_costs_one_head(self, _env) -> None:
        """The common case must not walk."""
        fake = _env(Probing())
        assert json.loads(_ask()["body"])["name"] == "report (1).csv"
        assert len(fake.heads) == 1

    def test_a_denial_stops_the_walk_rather_than_counting_as_free(self, _env) -> None:
        """A throttle or a denial read as 'free' proposes a name that is taken.

        The copy that follows would then overwrite somebody's object, and versioning is off.
        """
        fake = _env(Probing(error_on="alice/report (1).csv"))
        answer = _ask()
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert len(fake.heads) == 1


class TestExhaustionIsNotFailure:
    """The distinction the browser cannot currently make."""

    def test_every_candidate_taken_is_a_conflict_naming_the_attempts(self, _env) -> None:
        """A Conflict with `attempts`, which the browser renders as its own sentence."""
        every = {
            f"alice/report ({n}).csv" for n in range(1, s3_config.FREE_NAME_MAX_ATTEMPTS + 1)
        }
        _env(Probing(taken=every))
        answer = _ask()
        assert answer["statusCode"] == 409
        error = json.loads(answer["body"])["error"]
        assert error["code"] == "Conflict"
        assert error["params"] == {"attempts": s3_config.FREE_NAME_MAX_ATTEMPTS}

    def test_the_bound_is_the_shipped_one(self) -> None:
        """999, carried across rather than re-derived."""
        assert s3_config.FREE_NAME_MAX_ATTEMPTS == 999


class TestTheNamingRule:
    """One implementation, in Python. The TypeScript copy goes with the port."""

    @pytest.mark.parametrize(
        ("base", "attempt", "is_folder", "expected"),
        [
            ("report.csv", 1, False, "report (1).csv"),
            (".gitignore", 1, False, ".gitignore (1)"),
            (".env.local", 1, False, ".env (1).local"),
            ("report.csv", 12, False, "report (12).csv"),
            ("archive.tar.gz", 1, False, "archive.tar (1).gz"),
            ("noextension", 1, False, "noextension (1)"),
            ("reports", 1, True, "reports (1)"),
            ("folder.with.dots", 1, True, "folder.with.dots (1)"),
        ],
    )
    def test_the_extension_is_preserved_for_files_and_ignored_for_folders(
        self, base, attempt, is_folder, expected
    ) -> None:
        """A folder has no extension, and a LEADING dot is not one either.

        `.gitignore` is a dotfile, not a file with a `gitignore` extension. Getting that wrong
        produces `" (1).gitignore"` — which `validateLeafName` refuses for its leading space, so
        the route would propose a name the app's own validator rejects. The browser's rule is
        `lastIndexOf('.') <= 0`; this is the same rule, and these two rows are what pin them
        together now that only one implementation is left.
        """
        assert numbered_name(base, attempt, is_folder) == expected


class TestTheRouteIsDeclaredIdempotentDespiteBeingAPost:
    """Idempotency belongs to the route, never to the method."""

    def test_it_is_idempotent(self) -> None:
        """It resolves a name and changes nothing, so a retry above the transport is safe."""
        route = next(r for r in contract.ROUTES if r.id == "objects.freeName")
        assert route.method == "POST"
        assert route.idempotent is True
