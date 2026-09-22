"""The two membership sources, what the index one refuses, and the parity that expires.

**Everything here guards a failure that is invisible in the response.** A session carrying the
wrong spaces answers every request the same way it always did; the only symptom is a caller
reaching a space they should not, or being refused one they should reach and told it is a
permission problem. So the assertions are about the tag set and the call count, never about a
status code.

The source is resolved at module import, so every test that changes it goes through
``membership_source`` — which reloads on the way out as well as on the way in, unconditionally. A
reload whose module body raises leaves a half-initialised module in ``sys.modules``, and
``apicommon.identity`` holds a reference to it, so without the teardown one refusal test would
poison every test after it in the package.

Attributes:
  ADMIN: The admin bucket the environment fixture installs.
  ACTIVE: The one space status that yields a tag.
"""

import importlib
import json
import os
import sys
from typing import ClassVar

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from apicommon import config, identity, memberships, spaces
from apicommon.envelope import ApiError
from conftest import bearer

ADMIN = "admin-bkt"
ACTIVE = "active"
INDEX_KEY = "memberships/alice.json"
CACHE_KEY = "alice/user_settings/shared-connections.json"


class _Body:
    """The streaming body ``get_object`` returns."""

    def __init__(self, payload):
        """Holds the payload.

        Args:
          payload: The bytes to serve.

        Returns:
          None.

        Raises:
          None.
        """
        self._payload = payload

    def read(self):
        """Returns the payload.

        Args:
          None.

        Returns:
          The bytes.

        Raises:
          None.
        """
        return self._payload


class _Missing(Exception):
    """What S3 raises for an absent key to a caller that can list the prefix."""

    response: ClassVar[dict] = {"Error": {"Code": "NoSuchKey"}}


class _Throttled(Exception):
    """What S3 raises when it is asking to be called again later."""

    response: ClassVar[dict] = {"Error": {"Code": "ThrottlingException"}}


class _Denied(Exception):
    """What S3 raises when the read is refused outright."""

    response: ClassVar[dict] = {"Error": {"Code": "AccessDenied"}}


class _Recorder:
    """An execution-role client that serves one index document, or raises.

    Attributes:
      calls: Every call made through it, as ``(service, operation)`` pairs, so a test can assert
        how many times AWS was reached and by which door — the only way to tell a request that
        refused before calling from one that refused after.
      objects: **Full S3 KEY** to the document bytes to serve, never a username derived from the
        key. Deriving it would make every key that is not the one under test read as absent, so a
        test seeding some other object could never observe an implementation that reached for it —
        which is exactly what the bypass test exists to observe.
      error: An exception every read raises instead.
    """

    def __init__(self, objects=None, error=None):
        """Builds the recorder.

        Args:
          objects: Full S3 key to document bytes.
          error: What every read should raise.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls = []
        self.objects = objects or {}
        self.error = error

    def client(self, service, credentials=None):
        """Stands in for the package's one client constructor.

        Args:
          service: The AWS service name.
          credentials: The caller's assumed session, or None for the execution role.

        Returns:
          Itself, recording which service was asked for.

        Raises:
          None.
        """
        self._service = service
        return self

    def get_object(self, Bucket, Key):
        """Serves one membership index document.

        Args:
          Bucket: The bucket asked for.
          Key: The key asked for.

        Returns:
          A response carrying the document.

        Raises:
          Exception: Whatever the recorder was built with, or ``_Missing``.
        """
        self.calls.append(("s3", "get_object", Key))
        if self.error is not None:
            raise self.error
        if Key not in self.objects:
            raise _Missing()
        return {"Body": _Body(self.objects[Key])}

    def assume_role(self, **kwargs):
        """Records that the caller's role was assumed, and vends a usable session.

        Args:
          **kwargs: The assume-role arguments, recorded whole so a test can read the tags.

        Returns:
          A credentials block an hour from now.

        Raises:
          None.
        """
        import datetime

        self.calls.append(("sts", "assume_role", kwargs))
        return {
            "Credentials": {
                "AccessKeyId": "AKIA",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            }
        }


def document(spaces_named):
    """Builds an index document.

    Args:
      spaces_named: ``(name, status)`` pairs.

    Returns:
      The document, JSON-encoded.

    Raises:
      None.
    """
    return json.dumps(
        {
            "version": 1,
            "username": "alice",
            "spaces": [{"name": name, "status": status} for name, status in spaces_named],
            "updatedAt": "2026-08-31T00:00:00Z",
        }
    ).encode()


@pytest.fixture(autouse=True)
def _admin_bucket(monkeypatch):
    """The bucket the index read names, which the package's own fixture does not set."""
    monkeypatch.setenv("ADMIN_BUCKET", ADMIN)


@pytest.fixture
def membership_source(monkeypatch):
    """Resolves the module against one configured source, and restores it afterwards.

    The restore is unconditional and reloads with the variable REMOVED, so a test that leaves the
    module raising on import cannot hand a half-initialised module to the next one.

    Args:
      monkeypatch: Pytest's patcher.

    Yields:
      A function taking the source name and returning the reloaded module.

    Raises:
      None.
    """

    def _use(name):
        """Reloads the source module under one configured value.

        Args:
          name: The value to configure, or None to leave it unset.

        Returns:
          The reloaded module.

        Raises:
          MembershipSourceError: If the value is not one the module implements.
        """
        if name is None:
            monkeypatch.delenv(memberships.SOURCE_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(memberships.SOURCE_VARIABLE, name)
        return importlib.reload(memberships)

    yield _use
    monkeypatch.delenv(memberships.SOURCE_VARIABLE, raising=False)
    importlib.reload(memberships)


@pytest.fixture
def index_plane(monkeypatch):
    """Installs a recorder as the package's one client constructor.

    Args:
      monkeypatch: Pytest's patcher.

    Yields:
      A function taking the recorder to install and returning it.

    Raises:
      None.
    """

    def _install(recorder):
        """Installs one recorder.

        Args:
          recorder: The client to serve.

        Returns:
          The recorder, for assertions.

        Raises:
          None.
        """
        monkeypatch.setattr(identity, "_client", recorder.client)
        return recorder

    return _install


def caller(username="alice", **claims):
    """Builds a verified principal with the given membership claims.

    Args:
      username: The verified username.
      **claims: Slot keyword (``slot1``…) to space name.

    Returns:
      The principal.

    Raises:
      None.
    """
    from cpcommon.auth import Principal

    body = {"cognito:username": username}
    for key, value in claims.items():
        body[memberships.SHARED_SPACE_CLAIM.format(int(key.removeprefix("slot")))] = value
    return Principal(username=username, claims=body)


# ── FR-002: the source is a declared choice, resolved once ────────────────────


class TestTheSourceIsResolvedOnceAtImport:
    """One implementation, chosen at cold start, with no fallback anywhere."""

    def test_an_unset_variable_is_the_claims_source(self, membership_source) -> None:
        """Every deployed environment omits it, so the default is the shipped behaviour."""
        assert membership_source(None).SOURCE == memberships.SOURCE_CLAIMS

    def test_an_empty_variable_is_an_unset_one(self, membership_source) -> None:
        """An unset repository variable renders as the empty string, which is not a typo."""
        assert membership_source("").SOURCE == memberships.SOURCE_CLAIMS

    @pytest.mark.parametrize("name", ["claims", "index"])
    def test_each_named_source_resolves_to_itself(self, membership_source, name) -> None:
        """The control for the refusal below: both names are accepted."""
        assert name == membership_source(name).SOURCE

    def test_an_unrecognised_value_kills_the_container(self, membership_source) -> None:
        """It does not warn and it does not fall back.

        A typo resolving silently to the default produces a working application with the wrong
        authorization model, and nothing in any response says which one is running.

        The type is asserted by NAME rather than by identity, and that is not a shortcut: a reload
        redefines every class in the module, so the class object the raise carries is not the one
        this module bound at import — comparing them would fail against a correct implementation.
        The message match pins the offending value, so an unrelated ``RuntimeError`` on the way
        there cannot satisfy it.
        """
        with pytest.raises(RuntimeError, match="clams") as raised:
            membership_source("clams")
        assert type(raised.value).__name__ == "MembershipSourceError"

    def test_neither_implementation_is_reachable_except_through_the_one_call(self) -> None:
        """A call site that could name an implementation could pick the wrong one.

        Both are private, and ``resolve`` is the only public entry — which is also what makes the
        parity test below able to drive them the same way.

        Restricted to what the module DEFINES, so an imported helper that happens to be callable
        does not read as a second entry point.
        """
        import inspect

        public = {
            name
            for name in dir(memberships)
            if not name.startswith("_")
            and inspect.isfunction(getattr(memberships, name))
            and getattr(memberships, name).__module__ == memberships.__name__
        }
        assert public == {"resolve"}


# ── FR-003: the index source, and what absence means ──────────────────────────


class TestTheIndexSource:
    """Read the caller's index, keep the active spaces, refuse everything else."""

    def test_the_active_spaces_become_tags_in_a_stable_order(
        self, membership_source, index_plane
    ) -> None:
        """The happy path, and the control for every refusal below."""
        membership_source(memberships.SOURCE_INDEX)
        index_plane(
            _Recorder({INDEX_KEY: document([("legal", ACTIVE), ("finance", ACTIVE)])})
        )

        resolved = identity.identity_from(caller())
        assert resolved.memberships == {1: "finance", 2: "legal"}

    def test_an_absent_index_is_a_member_of_nothing_and_not_an_error(
        self, membership_source, index_plane
    ) -> None:
        """The correct answer for every caller who has never been added to a space."""
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({}))

        assert identity.identity_from(caller()).memberships == {}

    @pytest.mark.parametrize("status", ["provisioning", "failed", "deleting"])
    def test_a_space_that_is_not_active_yields_no_tag(
        self, membership_source, index_plane, status
    ) -> None:
        """A space's status decides, and the entry beside it is the control.

        Both are in the same document, so a implementation that ignored status entirely would
        stamp two tags and fail here rather than passing on the one it happened to keep.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(
            _Recorder({INDEX_KEY: document([("finance", ACTIVE), ("legal", status)])})
        )

        assert identity.identity_from(caller()).memberships == {1: "finance"}

    def test_a_malformed_index_is_a_failure_and_not_an_absence(
        self, membership_source, index_plane
    ) -> None:
        """An unparseable document is not evidence that the caller is a member of nothing.

        **All four refusals share one reason code, deliberately, and the fixtures discriminate
        the branches.** The caller learns nothing either way and a per-branch token would be a wire
        detail nobody renders — so what keeps this from being one test wearing four hats is that
        each body reaches a different refusal in the reader: an unparseable body, a document that
        is not a mapping, a space list that is not a list, and an ENTRY that is not a mapping.
        Removing any one guard makes its body raise something the request has no name for, which
        is what these assertions catch.
        """
        membership_source(memberships.SOURCE_INDEX)
        bodies = (
            b"{ not json",
            json.dumps(["finance"]).encode(),
            json.dumps({"version": 1, "spaces": {"finance": ACTIVE}}).encode(),
            json.dumps({"version": 1, "spaces": ["finance"]}).encode(),
            json.dumps({"version": 1, "spaces": [{"status": ACTIVE}]}).encode(),
        )
        for body in bodies:
            recorder = index_plane(_Recorder({INDEX_KEY: body}))
            with pytest.raises(
                identity.IdentityUnavailableError,
                match=memberships.REASON_INDEX_UNREADABLE,
            ):
                identity.identity_from(caller())
            assert not any(call[0] == "sts" for call in recorder.calls)

    @pytest.mark.parametrize("failure", [_Throttled(), _Denied()])
    def test_a_read_fault_mints_nothing_and_caches_nothing(
        self, membership_source, index_plane, failure
    ) -> None:
        """The whole of FR-003's failure contract, in one sequence.

        The alternative — stamp what was resolved and continue — fails closed in the permissions
        sense, which reads as safe and is the worst option available: the caller is refused a
        space they genuinely belong to, told it is a denial, and no gate can see it.

        The cache assertion is seeded rather than empty. ``reset_credential_cache`` runs between
        tests, so "the cache is empty afterwards" passes on a path that never reached the cache
        at all — which is every path this test drives.
        """
        membership_source(memberships.SOURCE_INDEX)
        recorder = index_plane(_Recorder(error=failure))
        keeper = identity.UserIdentity(username="carol", memberships={})
        identity._CREDENTIAL_CACHE[identity._cache_key(keeper)] = identity.AssumedCredentials(
            "AKIA", "secret", "token", _hour_from_now()
        )

        with pytest.raises(identity.IdentityUnavailableError):
            identity.for_request(caller())

        assert not any(call[0] == "sts" for call in recorder.calls)
        assert list(identity._CREDENTIAL_CACHE) == [identity._cache_key(keeper)]

    def test_an_unresolvable_identity_is_answered_5xx_WITH_A_CODE(
        self, membership_source, index_plane
    ) -> None:
        """The failure has to survive the router, and the pre-dispatch path is not the one below.

        ``for_request`` runs before dispatch, so a failure it raises never reaches the guard where
        ``errors.for_exception`` maps it — without a clause of its own it leaves ``route()``
        entirely and arrives as ``InternalError``, which names nothing an operator or the browser
        can act on. Asserted by CODE, and specifically **not** as a denial: a permission failure
        is what a partial mint would have told the caller, and it would be untrue.

        The single read is the other half: this layer retries nothing, because retry is the
        caller's under the transport's declared policy.
        """
        membership_source(memberships.SOURCE_INDEX)
        recorder = index_plane(_Recorder(error=_Throttled()))

        response = router.route(
            "GET",
            "/v1/objects",
            headers=bearer("alice"),
            request_id="r-2",
            query={"spaceKind": "personal", "spaceName": "alice"},
        )

        assert json.loads(response["body"])["error"]["code"] == "IdentityUnavailable"
        assert response["statusCode"] >= 500
        assert len(recorder.calls) == 1

    def test_the_read_is_by_exact_key_and_happens_once_per_request(
        self, membership_source, index_plane
    ) -> None:
        """One ``GetObject``, on the caller's OWN key, and no second cache anywhere.

        The credential cache is keyed on the resolved tag set, which is what this read produces,
        so nothing can consult it before the read — and a username-keyed read cache would freeze
        membership for the container's life, which is exactly what the credential cache's own key
        exists to prevent.
        """
        membership_source(memberships.SOURCE_INDEX)
        recorder = index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))

        identity.for_request(caller())
        reads = [call for call in recorder.calls if call[1] == "get_object"]
        assert reads == [("s3", "get_object", "memberships/alice.json")]


def _hour_from_now():
    """A timezone-aware expiry an hour out, matching what STS returns.

    Args:
      None.

    Returns:
      The expiry.

    Raises:
      None.
    """
    import datetime

    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)


# ── FR-009: the ceiling still binds ───────────────────────────────────────────


class TestTheSlotCeiling:
    """The cap binds on the index source too, and it refuses rather than truncating."""

    def test_an_index_naming_more_spaces_than_there_are_slots_fails_the_request(
        self, membership_source, index_plane
    ) -> None:
        """Truncating would silently drop an entitlement the plane believes it granted.

        Unreachable while ``assign_or_find_slot`` is live, and reachable the moment the slots
        retire — which is why it is asserted rather than assumed impossible.
        """
        membership_source(memberships.SOURCE_INDEX)
        cap = config.max_shared_memberships()
        index_plane(
            _Recorder(
                {INDEX_KEY: document([(f"space_{n}", ACTIVE) for n in range(cap + 1)])}
            )
        )

        with pytest.raises(
            identity.IdentityUnavailableError, match=memberships.REASON_INDEX_OVER_CAP
        ):
            identity.identity_from(caller())

    def test_exactly_the_cap_is_admitted(self, membership_source, index_plane) -> None:
        """The control: the refusal above is about the boundary, not about the read."""
        membership_source(memberships.SOURCE_INDEX)
        cap = config.max_shared_memberships()
        index_plane(
            _Recorder({INDEX_KEY: document([(f"space_{n}", ACTIVE) for n in range(cap)])})
        )

        assert len(identity.identity_from(caller()).memberships) == cap


# ── FR-005: the connections cache is not the index ────────────────────────────


class TestTheCacheIsNotTheIndex:
    """There is an object one GetObject away with exactly this shape, and it is the wrong one."""

    def test_a_connections_cache_naming_a_space_stamps_no_tag(
        self, membership_source, index_plane
    ) -> None:
        """Driven directly, because the reasoning is what a reader would otherwise have to trust.

        ``{username}/user_settings/shared-connections.json`` lists a user's spaces, keyed by
        username, and the portal role grants ``PutObject`` on that whole prefix with no Deny under
        ``user_settings/`` — it is hidden client-side only. Reading it would hand a caller a
        session tag for any space they cared to name.

        The cache object is seeded under the key production code would actually ask for, and the
        index under its own. A stub deriving the username from whatever key it was handed would
        answer "absent" to every key but one, so an implementation reaching for the cache would
        read as a caller in no space and this test would pass — which is the shape it exists to
        refuse.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(
            _Recorder(
                {
                    INDEX_KEY: document([]),
                    CACHE_KEY: json.dumps(
                        {
                            "version": 1,
                            "connections": [{"name": "finance", "status": ACTIVE}],
                        }
                    ).encode(),
                }
            )
        )

        assert identity.identity_from(caller()).memberships == {}

    def test_neither_module_names_the_cache_key(self) -> None:
        """The structural half, which is the guard the drive-it test above only samples."""
        import pathlib

        for module in (identity, memberships):
            source = pathlib.Path(module.__file__ or "").read_text()
            for forbidden in ("user_settings", "shared-connections"):
                assert forbidden not in source, (
                    f"{module.__name__} names {forbidden!r} — the roster cache is user-writable "
                    "and reading it is a complete authorization bypass"
                )

    def test_the_read_door_is_named_by_nothing_else_in_the_package(self) -> None:
        """A route holding the door could read another user's memberships.

        The door takes a username, so it is not self-scoping the way the user plane is. Two
        modules may name it: the one that owns it and the one that resolves the source.
        """
        import pathlib

        package = pathlib.Path(identity.__file__ or "").parent.parent
        allowed = {"apicommon/identity.py", "apicommon/memberships.py"}
        offenders = [
            str(path.relative_to(package))
            for path in sorted(package.rglob("*.py"))
            if not path.name.startswith(("test_", "conftest."))
            and str(path.relative_to(package)) not in allowed
            and "membership_index_document" in path.read_text()
        ]
        assert offenders == []


# ── FR-004: the route check and the tag set agree ─────────────────────────────


class TestTheRouteCheckAndTheTagSetAgree:
    """Two membership answers in one request is a defect whichever one is right."""

    @pytest.mark.parametrize("source", ["claims", "index"])
    def test_a_space_the_route_accepts_always_has_a_tag_and_one_it_refuses_never_does(
        self, membership_source, index_plane, monkeypatch, source
    ) -> None:
        """Driven under BOTH sources, from one identity, because that is the whole claim."""
        membership_source(source)
        monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bkt")
        index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))

        acting_as = identity.identity_from(caller(slot1="finance"))
        tagged = {tag["Value"] for tag in identity.session_tags(acting_as)}

        assert spaces.resolve(acting_as, "shared", "finance").name == "finance"
        assert "finance" in tagged

        with pytest.raises(ApiError) as raised:
            spaces.resolve(acting_as, "shared", "legal")
        assert raised.value.code == "AccessDenied"
        assert "legal" not in tagged

    def test_a_refusal_reaches_no_aws_service_beyond_the_callers_own_index(
        self, membership_source, index_plane, monkeypatch
    ) -> None:
        """SPEC-198's zero-call refusal, restated honestly for the source that makes one read.

        The literal "zero AWS calls" is not satisfiable under the index source — the request made
        one read of the caller's own index before any route was chosen. What is preserved, and
        what the assertion pins, is that the refusal itself costs nothing: no ``AssumeRole`` and
        no listing, so the request still discloses nothing about the space it named.
        """
        membership_source(memberships.SOURCE_INDEX)
        monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bkt")
        monkeypatch.setenv("USER_SPACE_BUCKET", "user-bkt")
        recorder = index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))

        response = router.route(
            "GET",
            "/v1/objects",
            headers=bearer("alice"),
            request_id="r-1",
            query={"spaceKind": "shared", "spaceName": "legal"},
        )

        assert json.loads(response["body"])["error"]["code"] == "AccessDenied"
        assert recorder.calls == [("s3", "get_object", "memberships/alice.json")]


# ── FR-006: the index IS an authorization input ───────────────────────────────


class TestTheIndexIsAnAuthorizationInput:
    """Which inverts SPEC-146's advisory-directory rule, deliberately."""

    def test_a_removal_takes_effect_on_the_next_request_with_no_token_refresh(
        self, membership_source, index_plane
    ) -> None:
        """The residual is a staleness window, and it is smaller than the one it replaces.

        Under the claims source a cleared slot does not reach the caller until their token
        refreshes — the propagation delay a browser hook exists to paper over. The index is read
        per request, so the same removal lands on the next one, with the SAME token.
        """
        membership_source(memberships.SOURCE_INDEX)
        recorder = index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))
        token = caller()

        before = identity.assume_user_role(identity.identity_from(token))
        recorder.objects[INDEX_KEY] = document([])
        after = identity.assume_user_role(identity.identity_from(token))

        assumed = [call for call in recorder.calls if call[0] == "sts"]
        assert len(assumed) == 2, "the tag set changed, so the credential cache must have missed"
        assert [tag["Value"] for tag in assumed[0][2]["Tags"]] == ["alice", "finance"]
        assert [tag["Value"] for tag in assumed[1][2]["Tags"]] == ["alice"]
        assert before.session_token == after.session_token == "token"

    def test_the_index_is_never_treated_as_advisory(self) -> None:
        """No fallback beyond "member of no space", and no path that reads it for display.

        SPEC-146's username directory is forbidden from being an authorization input; this one is
        one. The inversion is safe only while the three properties hold, and the cheapest of them
        to lose is this: a reader added "for the roster screen" would put the document on a route.
        """
        import pathlib

        package = pathlib.Path(identity.__file__ or "").parent.parent
        routes = sorted((package / "routes").rglob("*.py"))
        assert routes, "the route sweep found nothing — it has stopped working"
        for path in routes:
            source = path.read_text()
            assert "memberships/" not in source
            assert "membership_index" not in source


# ── FR-009 continued, and FR-010: what the record has to carry ────────────────


class TestTheNameThatBecomesATag:
    """A space name is a tag VALUE the portal role's policy interpolates into a resource ARN."""

    def test_a_username_the_catalog_rule_refuses_costs_no_read(
        self, membership_source, index_plane
    ) -> None:
        """Refused BEFORE the call, not after it.

        The successor account's username claim is a subject carrying hyphens and uppercase, which
        this rule will not admit — so this is the ordinary case there, not an exotic one. Without
        the check the request spends an admin-bucket read on the execution role before failing,
        and a value botocore rejects changes the reason from "cannot be represented" to "the index
        is unreadable", which sends an operator to the wrong place.
        """
        membership_source(memberships.SOURCE_INDEX)
        recorder = index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))

        with pytest.raises(
            identity.IdentityUnavailableError,
            match=identity.REASON_UNREPRESENTABLE_USERNAME,
        ):
            identity.identity_from(caller(username="Alice-Smith"))
        assert recorder.calls == []

    def test_a_space_name_the_catalog_rule_refuses_fails_the_request(
        self, membership_source, index_plane
    ) -> None:
        """A name of ``*`` is a wildcard grant over every shared space.

        The portal role's shared-space statements interpolate the tag value straight into a
        resource ARN, and a space created before the create path took the rule was format-checked
        nowhere at all —
        the create path's rule refuses a CREATE and cannot reach a name already given — so this is
        the last point at which such a name can be refused before it becomes an entitlement. Refused whole rather than skipped: a partial tag set is what FR-003 forbids.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE), ("*", ACTIVE)])}))

        with pytest.raises(
            identity.IdentityUnavailableError, match=memberships.REASON_INDEX_UNSAFE_NAME
        ):
            identity.identity_from(caller())

    def test_an_unset_admin_bucket_is_a_configuration_fault_not_an_unreadable_index(
        self, membership_source, index_plane, monkeypatch
    ) -> None:
        """The two 5xx codes mean different things and send an operator to different places.

        An empty ``TF_VAR_`` renders as an empty variable, which reads as unset. Caught by the
        read's own wrap it would arrive as "the index is unreadable" — S3 grants, throttling — for
        a missing environment variable.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({}))
        monkeypatch.setenv("ADMIN_BUCKET", "")

        with pytest.raises(config.ConfigError, match="ADMIN_BUCKET"):
            identity.identity_from(caller())


class TestTheRecordCarriesWhatTheLiveCheckReadsBack:
    """FR-007's live check reads the resolved space set out of the log store, and expires.

    So the field is not telemetry that can be dropped and re-added later: the comparison it feeds
    cannot be re-run once the environment moves. It is asserted per REQUEST as well as per mint,
    because a mint happens on a cold credential cache and on nothing else — a per-mint-only field
    is absent from the overwhelming majority of records, which are warm.
    """

    def test_every_request_stamps_the_source_and_the_resolved_spaces(
        self, membership_source, index_plane, monkeypatch
    ) -> None:
        """The per-request half.

        Args:
          membership_source: The source fixture.
          index_plane: The client fixture.
          monkeypatch: Pytest's patcher.

        Returns:
          None.

        Raises:
          AssertionError: If either field is missing from what the request stamped.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))
        stamped: list[dict] = []
        monkeypatch.setattr(
            "cpcommon.observability.stamp", lambda **fields: stamped.append(fields)
        )

        identity.for_request(caller())

        merged = {key: value for record in stamped for key, value in record.items()}
        assert merged["membership_source"] == memberships.SOURCE_INDEX
        assert merged["spaces"] == ["finance"]

    def test_the_mint_records_the_source_the_spaces_and_their_count(
        self, membership_source, index_plane, monkeypatch
    ) -> None:
        """The per-mint half, which is the span the spec names.

        Args:
          membership_source: The source fixture.
          index_plane: The client fixture.
          monkeypatch: Pytest's patcher.

        Returns:
          None.

        Raises:
          AssertionError: If the mint record omits the source, the names or the count.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(
            _Recorder({INDEX_KEY: document([("legal", ACTIVE), ("finance", ACTIVE)])})
        )
        emitted: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            "cpcommon.observability.info",
            lambda message, **fields: emitted.append((message, fields)),
        )

        identity.assume_user_role(identity.identity_from(caller()))

        mints = [fields for message, fields in emitted if "assuming" in message]
        assert len(mints) == 1
        assert mints[0]["membership_source"] == memberships.SOURCE_INDEX
        assert mints[0]["spaces"] == ["finance", "legal"]
        assert mints[0]["membership_slots"] == 2

    def test_no_record_carries_the_token_the_claims_or_the_document(
        self, membership_source, index_plane, monkeypatch
    ) -> None:
        """Space names and usernames are permitted metadata. Nothing else here is.

        Args:
          membership_source: The source fixture.
          index_plane: The client fixture.
          monkeypatch: Pytest's patcher.

        Returns:
          None.

        Raises:
          AssertionError: If a claim value or the document body reaches a record.
        """
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({INDEX_KEY: document([("finance", ACTIVE)])}))
        seen: list[dict] = []
        for name in ("stamp", "info", "warning", "error"):
            monkeypatch.setattr(
                f"cpcommon.observability.{name}",
                (lambda **fields: seen.append(fields))
                if name == "stamp"
                else (lambda message, **fields: seen.append(fields)),
            )

        identity.assume_user_role(identity.identity_from(caller(slot1="finance")))

        rendered = json.dumps(seen)
        for forbidden in ("custom:shared_space", "cognito:username", "updatedAt", '"version"'):
            assert forbidden not in rendered


# ── FR-007: the two sources agree, while both exist ───────────────────────────


class TestTheParityThatExpires:
    """The reason this ships before the environment moves.

    While Cognito slots and the index both exist, one user's membership is knowable two ways. In
    the successor account only one survives, and a wrong implementation is indistinguishable from
    a right one — which is why the assertion is written now, and why it cannot be re-run later.
    """

    FIXTURE_CLAIMS: ClassVar[dict] = {"slot1": "finance", "slot4": "legal", "slot7": "newspace"}
    SETTLED: ClassVar[set] = {"finance", "legal"}
    MID_PROVISION = "newspace"
    REMOVED = "oldspace"

    def _both(self, membership_source, index_plane, entries):
        """Resolves the fixture user under both sources.

        Args:
          membership_source: The source fixture.
          index_plane: The client fixture.
          entries: The index document's ``(name, status)`` pairs.

        Returns:
          A ``(claims set, index set)`` pair of space names.

        Raises:
          None.
        """
        principal = caller(**self.FIXTURE_CLAIMS)
        membership_source(memberships.SOURCE_CLAIMS)
        from_claims = set(identity.identity_from(principal).memberships.values())
        membership_source(memberships.SOURCE_INDEX)
        index_plane(_Recorder({INDEX_KEY: document(entries)}))
        from_index = set(identity.identity_from(principal).memberships.values())
        return from_claims, from_index

    def test_the_settled_spaces_agree_as_sets(self, membership_source, index_plane) -> None:
        """More than one space, because a single-space fixture agrees under almost anything."""
        from_claims, from_index = self._both(
            membership_source,
            index_plane,
            [(name, ACTIVE) for name in sorted(self.SETTLED)],
        )
        assert from_claims - {self.MID_PROVISION} == from_index == self.SETTLED

    def test_a_space_mid_provision_is_a_POSITIVE_divergence_not_an_exclusion(
        self, membership_source, index_plane
    ) -> None:
        """``create_space`` assigns the slot BEFORE it finalizes the record as active.

        So a space still provisioning legitimately holds a Cognito slot and legitimately yields no
        tag from the index. Asserted as that exact shape — present in one, absent from the other —
        rather than excused away, because without it the mandated non-active fixture makes the
        mandated equality fail on a correct implementation.
        """
        from_claims, from_index = self._both(
            membership_source,
            index_plane,
            [(name, ACTIVE) for name in sorted(self.SETTLED)],
        )
        assert self.MID_PROVISION in from_claims
        assert self.MID_PROVISION not in from_index

    def test_a_space_the_user_was_removed_from_is_in_neither(
        self, membership_source, index_plane
    ) -> None:
        """The third leg, and the one that would catch a source reading a stale projection."""
        from_claims, from_index = self._both(
            membership_source,
            index_plane,
            [(name, ACTIVE) for name in sorted(self.SETTLED)] + [(self.REMOVED, "deleting")],
        )
        assert self.REMOVED not in from_claims
        assert self.REMOVED not in from_index
