"""Assuming the role, caching what comes back, and telling three failures apart.

**None of this is visible to a single-user test.** A warm container serves many callers in
sequence and nothing about it is per-user, so a cache that is keyed wrongly hands the second
caller the first caller's session — which SUCCEEDS, against the wrong identity, returning
right-looking data. That is why the central assertion here is written as a SEQUENCE in one
process rather than as a property of one call, and why each of its clauses is load-bearing: drop
the first and a shared cache passes; drop the second and a cache keyed on the request id — safe
but useless — passes; drop the third and a cache that re-assumes with the previous caller's tags
passes.

**The credentials are measured where they leak, not where they are stored.** "B's client carries
B's credentials" is true of the cache, of the credentials object and of the client, and only the
last is the thing a route can call. So the assertion reads the access key recorded by the client
CONSTRUCTOR.

**An assume failure is not a denial, and the fixture makes STS say so.** STS answers
``AccessDenied`` when the trust policy is wrong, so a mapper that asked about the service code
before the exception type would report a misconfiguration to every user as "you don't have
permission" — for a trust statement that renders, plans, applies and unit-tests green. The
fixture for that path raises ``AccessDenied`` specifically; anything else would pass over the
defect.

Attributes:
  HERE: This function's package root.
  IDENTITY_LAYER: The modules this spec adds, named by EXACT path. The subject of the sweeps that
    say what this layer must never do — never a pattern, and never the refusal surface, which
    legitimately owns the unauthenticated code. **Every module the spec ships is here**: naming
    only the two obvious ones left the route and the request context outside both sweeps, which
    is a rule quietly covering less than its name claims.
  CREDENTIAL_SENTINEL: Marks every value the stubbed STS issues, so "no credential reached a
    record" is a search for a string that could only have come from a session.
  FAR_FUTURE_SECONDS: How much life a stubbed session has by default — comfortably past the
    margin, so a test that means to exercise expiry has to ask for it.
  ROLE_ARN: The portal role the fixture environment names.
  ACCOUNT_ID: An account id, for the assertion that neither it nor the role ARN reaches a body.
"""

import ast
import datetime
import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import TypedDict

import handler as api_handler
import router
from apicommon import config, contract, errors, identity
from conftest import bearer, declare_route, token


class _ClaimingBody(TypedDict):
    """A body that ASSERTS a username, declared so the contract accepts it.

    Declared rather than omitted on purpose: the point of the tests below is that a caller-stated
    username cannot reach the session tags, and a body the transport refuses before dispatch would
    prove that by never arriving. This one is admitted all the way to the router and still cannot
    influence anything.
    """

    username: str


_TEST_ROUTE = contract.Route(
    id="test.assume",
    method="GET",
    path="/v1/_test-assume",
    idempotent=True,
    plane="user",
    request=_ClaimingBody,
    response=contract.UserDirectoryResponse,
)

_FAILURE_ROUTE = contract.Route(
    id="test.failure",
    method="GET",
    path="/v1/_test-failure",
    idempotent=True,
    plane="user",
    request=None,
    response=contract.UserDirectoryResponse,
)

HERE = pathlib.Path(__file__).resolve().parent

IDENTITY_LAYER = (
    "apicommon/identity.py",
    "apicommon/planes.py",
    "apicommon/context.py",
)

CREDENTIAL_SENTINEL = "do-not-log-7f3a2c9e"
FAR_FUTURE_SECONDS = 3600
ROLE_ARN = "arn:aws:iam::696000197480:role/dat-portal-user-role"
ACCOUNT_ID = "696000197480"


# ── The stubbed service boundary ──────────────────────────────────────────────


class _Denied(Exception):
    """A botocore-shaped client error, built to a code the test chooses."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": (
            f"User: arn:aws:sts::{ACCOUNT_ID}:assumed-role/dat-portal-user-role/alice is not "
            f"authorized to perform: sts:AssumeRole on resource: {ROLE_ARN}"
        )}}


class _FakeSts:
    """STS, recording every AssumeRole and handing back a distinguishable session each time."""

    def __init__(self, state):
        self._state = state

    def assume_role(self, **kwargs):
        """Records the call and returns a session numbered by how many have been issued."""
        self._state.assume_calls.append(kwargs)
        if self._state.sts_error is not None:
            raise self._state.sts_error
        issued = len(self._state.assume_calls)
        return {
            "Credentials": {
                "AccessKeyId": f"AKIA{CREDENTIAL_SENTINEL}{issued}",
                "SecretAccessKey": f"secret{CREDENTIAL_SENTINEL}{issued}",
                "SessionToken": f"session{CREDENTIAL_SENTINEL}{issued}",
                # Timezone-AWARE, exactly as botocore returns it. A naive value here would
                # measure a shape STS never produces, and would hide the comparison raising.
                "Expiration": datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=self._state.lifetime_seconds),
            }
        }


class _FakeService:
    """Any other service, recording the credentials it was constructed with."""

    def __init__(self, service, session, state):
        self.service = service
        self.session = session
        self._state = state
        self.operations = []

    def list_objects_v2(self, **kwargs):
        """Records the call, and raises whatever the test queued for it."""
        self.operations.append(kwargs)
        self._state.calls.append((self.session.get("aws_access_key_id"), kwargs))
        if self._state.operation_errors:
            raise self._state.operation_errors.pop(0)
        return {"KeyCount": 0}


class _State:
    """What the stubbed boundary recorded, and what the test wants it to do next.

    Attributes:
      assume_calls: Every AssumeRole kwarg set, in order.
      built: Every non-STS client built, in order.
      calls: (access key, kwargs) for every operation issued.
      sts_error: Raised by the next AssumeRole, if set.
      operation_errors: Raised by the next operations, in order.
      lifetime_seconds: How long the next issued session lasts.
    """

    def __init__(self):
        self.assume_calls = []
        self.built = []
        self.calls = []
        self.sts_error = None
        self.operation_errors = []
        self.lifetime_seconds = FAR_FUTURE_SECONDS


@pytest.fixture
def aws(monkeypatch):
    """Replaces the one client constructor with a recording stub.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      The recorder.

    Raises:
      None.
    """
    import boto3

    state = _State()

    def _client(service, **session):
        if service == "sts":
            return _FakeSts(state)
        built = _FakeService(service, session, state)
        state.built.append(built)
        return built

    monkeypatch.setattr(boto3, "client", _client)
    return state


def _caller(username="alice", **spaces):
    """Builds a verified identity directly, for the tests that do not need a request.

    Args:
      username: The username.
      **spaces: ``slot_<k>=name`` for each occupied slot.

    Returns:
      The identity.

    Raises:
      None.
    """
    memberships = {
        int(name.split("_")[1]): value for name, value in spaces.items()
    }
    return identity.UserIdentity(username=username, memberships=memberships)


def _spaces(**slots):
    """Builds the ``custom:shared_space_k`` claims for a token.

    Args:
      **slots: ``slot_<k>=name`` for each occupied slot.

    Returns:
      The claim overrides.

    Raises:
      None.
    """
    return {
        identity.SHARED_SPACE_CLAIM.format(int(name.split("_")[1])): value
        for name, value in slots.items()
    }


# ── FR-001: the tags come from the claims and from nothing else ───────────────


def test_the_tags_come_from_the_CLAIM_when_the_request_says_otherwise(aws) -> None:
    """The fixture DISAGREES, and it has to: one where they agree passes over the defect.

    Driven through the handler with a full gateway event, because the router is handed headers
    alone by design — a headers-only fixture cannot carry the body and query string that are
    exactly what a credential-selecting route would read.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If anything the request asserted about itself reaches the tag list.
    """
    def _assuming(context):
        identity.user_client("s3", context.acting_as)
        return {"ok": True}

    with declare_route(_TEST_ROUTE, _assuming):
        api_handler.handler(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": "/v1/_test-assume"},
                    "requestId": "req-1",
                },
                "headers": {**bearer("alice"), "x-username": "mallory"},
                "queryStringParameters": {"username": "mallory"},
                "body": json.dumps({"username": "mallory"}),
            },
            None,
        )

    assert len(aws.assume_calls) == 1
    tags = aws.assume_calls[0]["Tags"]
    assert tags == [{"Key": "username", "Value": "alice"}]
    assert "mallory" not in json.dumps(aws.assume_calls)
    assert aws.assume_calls[0]["RoleSessionName"] == "alice"


def test_the_assume_names_the_configured_role_for_a_full_hour_and_nothing_transitive(
    aws,
) -> None:
    """Three properties of one call, each with its own way of being wrong.

    A transitive tag survives role chaining; nothing here chains, and a tag that outlives its
    session is a durable escalation. The hour is a ceiling in both directions — shorter caps
    every presigned link that a later spec signs with these credentials, and longer is refused
    outright, because a function running on an assumed-role session is already chaining.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three differs.
    """
    identity.assume_user_role(_caller())

    call = aws.assume_calls[0]
    assert call["RoleArn"] == config.portal_role_arn() == ROLE_ARN
    assert call["DurationSeconds"] == config.ASSUME_ROLE_DURATION_SECONDS == 3600
    assert "TransitiveTagKeys" not in call


def test_a_member_of_ten_spaces_is_stamped_with_ELEVEN_tags(aws) -> None:
    """Read off the call itself. This account records no AssumeRole event anywhere.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a slot is dropped.
    """
    spaces = {f"slot_{k}": f"space_{k}" for k in range(1, 11)}
    identity.assume_user_role(_caller("alice", **spaces))

    assert len(aws.assume_calls[0]["Tags"]) == 11


def test_this_layer_holds_no_decoder_of_its_own() -> None:
    """A second decoder is a signature check that silently is not one.

    It looks identical to a correct one on every genuine token, which is why this is a sweep
    rather than a review note.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module in this layer decodes anything.
    """
    forbidden = {
        "decode",
        "b64decode",
        "urlsafe_b64decode",
        "b64encode",
        "decode_complete",
        "get_unverified_header",
    }
    for relative in IDENTITY_LAYER:
        tree = ast.parse((HERE / relative).read_text(encoding="utf-8"))
        names = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not (names & forbidden), f"{relative} decodes: {sorted(names & forbidden)}"
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                assert "jwt" not in module and "base64" not in module, (
                    f"{relative} imports a decoder"
                )


def test_a_username_that_cannot_be_a_session_name_issues_NO_call(aws) -> None:
    """Refused before the call, not after it.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If any STS call was issued for an unrepresentable username.
    """
    for username in ("has-a-hyphen", "a" * 64):
        with pytest.raises(identity.IdentityUnavailableError):
            identity.assume_user_role(_caller(username))
    assert aws.assume_calls == []


# ── FR-006: the cache, and the leak it invites ────────────────────────────────


def test_three_requests_in_one_process_do_not_share_a_session(aws) -> None:
    """THE assertion of this file, and every clause of it is load-bearing.

    Alice, then Bob, then Alice again inside the margin. A container is warm for all three.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If any caller is served another's session, if the cache does not work at
        all, or if a re-assume carries the previous caller's tags.
    """
    alice = _caller("alice")
    bob = _caller("bob")

    identity.user_client("s3", alice).list_objects_v2(Bucket="b", Prefix="alice/")
    identity.user_client("s3", bob).list_objects_v2(Bucket="b", Prefix="bob/")
    identity.user_client("s3", alice).list_objects_v2(Bucket="b", Prefix="alice/")

    first, second, third = aws.calls

    assert second[0] != first[0], "Bob's client carried Alice's credentials"
    assert second[0] == f"AKIA{CREDENTIAL_SENTINEL}2"

    assert len(aws.assume_calls) == 2, (
        f"{len(aws.assume_calls)} assume calls across three requests — one per request means "
        "no cache, three means a key that is never a hit, and a count that ignores the caller "
        "would pass with the cache shared"
    )

    assert aws.assume_calls[1]["Tags"] == [{"Key": "username", "Value": "bob"}]

    assert third[0] == first[0], "Alice's second request did not reuse her own session"


def test_a_refreshed_token_whose_membership_CHANGED_is_a_cache_miss(aws) -> None:
    """The fourth request, and what a username-only key gets wrong.

    A username-only key pins a caller to whichever membership set their first request of the
    hour happened to carry — turning refresh-to-propagate into refresh-and-nothing-happens.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the changed membership reuses the old session.
    """
    identity.assume_user_role(_caller("alice", slot_1="marketing"))
    identity.assume_user_role(_caller("alice", slot_1="marketing"))
    assert len(aws.assume_calls) == 1

    identity.assume_user_role(_caller("alice", slot_1="marketing", slot_2="finance"))
    assert len(aws.assume_calls) == 2
    assert len(aws.assume_calls[1]["Tags"]) == 3


def test_two_tokens_differing_only_in_one_slot_claim_stamp_different_tag_sets(aws) -> None:
    """Asserted through the verifier, so the claim really is where the value comes from.

    A test whose two tokens differ in the USERNAME passes with the slot claims ignored entirely.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the two requests stamp the same tags.
    """
    from cpcommon.auth import verify_token

    def _identity_for(**slots):
        verified = verify_token(token("alice", **_spaces(**slots)), config.verifier_config())
        return identity.identity_from(verified)

    identity.assume_user_role(_identity_for(slot_1="marketing"))
    identity.assume_user_role(_identity_for(slot_1="marketing", slot_3="finance"))

    assert len(aws.assume_calls) == 2
    assert aws.assume_calls[0]["Tags"] != aws.assume_calls[1]["Tags"]
    assert [tag["Key"] for tag in aws.assume_calls[1]["Tags"]] == [
        "username",
        "shared_space_1",
        "shared_space_3",
    ]


def test_a_session_inside_the_margin_is_not_handed_out(aws) -> None:
    """The margin's whole job: nothing a request emits may outlive the credential.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a session too short to cover a request is reused.
    """
    aws.lifetime_seconds = config.CREDENTIAL_EXPIRY_MARGIN_SECONDS - 1
    identity.assume_user_role(_caller())
    identity.assume_user_role(_caller())
    assert len(aws.assume_calls) == 2, "a session inside the margin was reused"

    aws.lifetime_seconds = config.CREDENTIAL_EXPIRY_MARGIN_SECONDS + 60
    identity.reset_credential_cache()
    identity.assume_user_role(_caller())
    identity.assume_user_role(_caller())
    assert len(aws.assume_calls) == 3, "a session with life left was needlessly re-assumed"


def test_the_margin_is_the_life_of_one_request_computed_from_the_timeout() -> None:
    """The schedulable unit is ONE REQUEST, and the budget is the function's own timeout.

    A request's whole life is bounded by that timeout, so the longest downstream call it makes
    is subsumed by the same bound rather than omitted from it. No clock-skew number is invented
    on top: the single forced re-assume on an expired credential IS that allowance, and an
    invented literal would hide a wrong model.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the margin stops being derived, or grows enough to make the cache
        pointless.
    """
    from cpcommon.jwks import API_FUNCTION_TIMEOUT_SECONDS

    infra = pathlib.Path(__file__).resolve().parent.parent.parent / "infra"
    declared = infra / "modules" / "api" / "lambda.tf"

    timeout = re.search(r"^\s*timeout\s*=\s*(\d+)", declared.read_text(), re.MULTILINE)
    assert timeout, "the API function no longer declares a timeout"

    assert int(timeout.group(1)) == API_FUNCTION_TIMEOUT_SECONDS
    assert config.CREDENTIAL_EXPIRY_MARGIN_SECONDS == API_FUNCTION_TIMEOUT_SECONDS

    usable = (
        config.ASSUME_ROLE_DURATION_SECONDS - config.CREDENTIAL_EXPIRY_MARGIN_SECONDS
    ) / config.ASSUME_ROLE_DURATION_SECONDS
    assert usable > 0.95, (
        f"the margin leaves only {usable:.0%} of a session usable, so the cache buys nothing"
    )


def test_the_cache_reset_the_fixture_calls_actually_empties_it(aws) -> None:
    """Guard-the-guard: a reset that did nothing would leave every sequence above meaningless.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a seeded cache survives the reset.
    """
    identity.assume_user_role(_caller())
    assert len(aws.assume_calls) == 1
    identity.assume_user_role(_caller())
    assert len(aws.assume_calls) == 1, "the cache never held anything, so the reset proves nothing"

    identity.reset_credential_cache()
    identity.assume_user_role(_caller())
    assert len(aws.assume_calls) == 2, "the reset did not empty the cache"


# ── FR-006: the single expiry retry ───────────────────────────────────────────


def test_an_expired_session_is_re_assumed_once_and_the_retry_runs_on_a_NEW_client(aws) -> None:
    """boto3 binds credentials at construction, so retrying on the same object proves nothing.

    A proxy that re-assumes and then re-calls the client it already holds hits the same expired
    session, fails again and reports a fault — fail-closed, but the retry is decorative and
    every test of it passes.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the retry reuses the expired session, or carries the wrong tags.
    """
    caller = _caller("alice", slot_1="marketing")
    client = identity.user_client("s3", caller)
    aws.operation_errors = [_Denied("ExpiredToken")]

    client.list_objects_v2(Bucket="b", Prefix="alice/")

    assert len(aws.assume_calls) == 2, "the expiry did not force exactly one re-assume"
    assert aws.assume_calls[1]["Tags"] == aws.assume_calls[0]["Tags"]
    assert [tag["Value"] for tag in aws.assume_calls[1]["Tags"]] == ["alice", "marketing"]

    attempts = [access_key for access_key, _ in aws.calls]
    assert len(attempts) == 2
    assert attempts[0] != attempts[1], "the retry reused the expired session"


def test_a_second_expiry_is_a_fault_and_not_a_third_attempt(aws) -> None:
    """One retry is the whole allowance, and the second failure changes category.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a third attempt is made, or the failure is not a fault.
    """
    client = identity.user_client("s3", _caller())
    aws.operation_errors = [_Denied("ExpiredToken"), _Denied("ExpiredToken")]

    with pytest.raises(identity.IdentityUnavailableError):
        client.list_objects_v2(Bucket="b", Prefix="alice/")

    assert len(aws.calls) == 2, "a third attempt was made"


def test_a_denial_is_not_retried_at_all(aws) -> None:
    """Only an expiry earns the re-assume. A denial is an answer, not a transient.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a denial triggers a re-assume.
    """
    client = identity.user_client("s3", _caller())
    aws.operation_errors = [_Denied("AccessDenied")]

    with pytest.raises(_Denied):
        client.list_objects_v2(Bucket="b", Prefix="bob/")

    assert len(aws.assume_calls) == 1
    assert len(aws.calls) == 1


# ── FR-007: three conditions, three statuses, three codes ─────────────────────


def _assuming_route(context):
    """A route that does the smallest user-plane thing: assume, and report nothing.

    Args:
      context: The authenticated request.

    Returns:
      An empty body.

    Raises:
      None.
    """
    identity.user_client("s3", context.acting_as)
    return {"ok": True}


def _drive_via_handler(handler_fn, headers=None):
    """Runs one request through the FUNCTION rather than the router.

    The observability assertions need this: a child span has to have a parent, and the parent is
    the traced handler. Driving the router alone opens no trace, so a span assertion against it
    is vacuous rather than false.

    Args:
      handler_fn: The route handler.
      headers: The request headers.

    Returns:
      The response.

    Raises:
      None.
    """
    with declare_route(_FAILURE_ROUTE, handler_fn):
        return api_handler.handler(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": "/v1/_test-failure"},
                    "requestId": "req-span",
                },
                "headers": bearer() if headers is None else headers,
            },
            None,
        )


def _drive(handler_fn, headers=None):
    """Runs one request against a temporary route.

    Args:
      handler_fn: The route handler.
      headers: The request headers.

    Returns:
      The response.

    Raises:
      None.
    """
    with declare_route(_FAILURE_ROUTE, handler_fn):
        return router.route("GET", "/v1/_test-failure", bearer() if headers is None else headers)


def test_an_assume_failure_is_a_FAULT_even_though_sts_calls_it_access_denied(aws) -> None:
    """The conflation this mapping exists to prevent, driven with the code that causes it.

    A trust policy missing ``sts:TagSession`` renders, plans, applies and unit-tests green, and
    STS refuses it with ``AccessDenied``. Reported as a denial, every user is told they lack a
    permission for something only an operator can fix.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the assume failure is reported as a denial.
    """
    aws.sts_error = _Denied("AccessDenied")

    response = _drive(_assuming_route)

    assert response["statusCode"] == contract.ERROR_STATUS[errors.IDENTITY_UNAVAILABLE_CODE]
    assert json.loads(response["body"])["error"]["code"] == errors.IDENTITY_UNAVAILABLE_CODE


def test_a_denial_on_the_user_plane_is_a_403_and_stays_one(aws) -> None:
    """The pair of the test above: the same service code, the opposite status.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the isolation model working is reported as a fault.
    """
    def _denied(context):
        client = identity.user_client("s3", context.acting_as)
        aws.operation_errors = [_Denied("AccessDenied")]
        return client.list_objects_v2(Bucket="b", Prefix="bob/")

    response = _drive(_denied)

    assert response["statusCode"] == contract.ERROR_STATUS[errors.FORBIDDEN_CODE]
    assert json.loads(response["body"])["error"]["code"] == errors.FORBIDDEN_CODE


def test_a_lake_formation_denial_arrives_under_the_other_code(aws) -> None:
    """``AccessDeniedException`` is the shape a catalog denial takes.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If it is not answered the same way.
    """
    def _denied(context):
        client = identity.user_client("s3", context.acting_as)
        aws.operation_errors = [_Denied("AccessDeniedException")]
        return client.list_objects_v2(Bucket="b", Prefix="x/")

    assert _drive(_denied)["statusCode"] == contract.ERROR_STATUS[errors.FORBIDDEN_CODE]


def test_a_tag_set_that_cannot_be_BUILT_is_the_same_fault_as_a_failed_assume(
    aws, monkeypatch
) -> None:
    """Tag construction reads configuration, so it is a third way into the same condition.

    Outside the wrap this reached the caller as a bare gateway fault carrying no code — the one
    outcome the wire contract has no name for, and indistinguishable from a crash.

    Args:
      aws: The recorder.
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If it is not answered as an unavailable identity.
    """
    monkeypatch.setenv("PRINCIPAL_TAG_KEY", "")

    response = _drive(_assuming_route)

    assert response["statusCode"] == contract.ERROR_STATUS[errors.IDENTITY_UNAVAILABLE_CODE]
    assert json.loads(response["body"])["error"]["code"] == errors.IDENTITY_UNAVAILABLE_CODE
    assert aws.assume_calls == [], "a call was issued with a tag set that could not be built"


def test_a_route_that_hits_a_MISCONFIGURATION_gets_a_server_fault_with_a_code(aws) -> None:
    """Not a 401, not a denial, and not a bare 500 either.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If it is answered as anything but a named server fault.
    """
    from apicommon.config import ConfigError

    def _misconfigured(context):
        raise ConfigError("required environment variable 'SOMETHING' is unset or empty")

    response = _drive(_misconfigured)

    assert response["statusCode"] == contract.ERROR_STATUS[errors.SERVER_FAULT_CODE]
    assert json.loads(response["body"])["error"]["code"] == errors.SERVER_FAULT_CODE
    assert errors.UNAUTHENTICATED_CODE not in response["body"]


def test_the_refusal_of_an_unrepresentable_username_is_LOGGED_with_that_username(
    aws, captured_events
) -> None:
    """A fixed reason code is not enough on its own: an operator needs to know who.

    The username is user metadata and the field rule admits it. It rides the request stamp rather
    than the exception, which is why the assertion is on the records rather than on the raise.

    Args:
      aws: The recorder.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If no record names the refused caller.
    """
    refused = "has-a-hyphen"

    response = _drive_via_handler(_assuming_route, bearer(refused))

    assert response["statusCode"] == contract.ERROR_STATUS[errors.IDENTITY_UNAVAILABLE_CODE]
    assert refused not in json.dumps(response), "the refused name travelled to the caller"
    assert aws.assume_calls == [], "a call was issued for a name that cannot be a session name"
    stamped = [
        event
        for event in captured_events.events
        if event.get("fields", {}).get("username") == refused
    ]
    assert stamped, "the refusal names no caller, so an operator cannot tell who was refused"


def test_the_three_conditions_are_three_statuses_and_three_codes(aws) -> None:
    """A mapper that collapsed two of them passes any test exercising one at a time.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If any two conditions share a status or a code.
    """
    unauthenticated = router.route("GET", "/v1/user-directory", {})

    aws.sts_error = _Denied("AccessDenied")
    unavailable = _drive(_assuming_route)
    aws.sts_error = None

    def _denied(context):
        client = identity.user_client("s3", context.acting_as)
        aws.operation_errors = [_Denied("AccessDenied")]
        return client.list_objects_v2(Bucket="b", Prefix="bob/")

    forbidden = _drive(_denied)

    statuses = [response["statusCode"] for response in (unauthenticated, forbidden, unavailable)]
    codes = [json.loads(response["body"])["error"]["code"] for response in (unauthenticated, forbidden, unavailable)]

    assert statuses == [401, 403, 500]
    assert len(set(statuses)) == 3
    assert len(set(codes)) == 3


def test_no_raw_aws_text_crosses_the_boundary(aws) -> None:
    """The provider's own message names a role ARN and an account id. Neither may travel.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If either appears in a response.
    """
    aws.sts_error = _Denied("AccessDenied")
    response = _drive(_assuming_route)

    serialised = json.dumps(response)
    assert ROLE_ARN not in serialised
    assert ACCOUNT_ID not in serialised
    assert "not authorized" not in serialised


def test_the_403_names_nothing_and_so_cannot_become_an_existence_oracle(aws) -> None:
    """A refusal that described what it refused answers "does that exist?" for anyone asking.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the body carries a bucket, a key or a space name.
    """
    def _denied(context):
        client = identity.user_client("s3", context.acting_as)
        aws.operation_errors = [_Denied("AccessDenied")]
        return client.list_objects_v2(Bucket="secret-bucket", Prefix="finance-team/q4/")

    body = json.loads(_drive(_denied)["body"])

    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "requestId"}
    for leaked in ("secret-bucket", "finance-team", "q4", "alice", "Prefix", "s3"):
        assert leaked not in json.dumps(body)


def test_this_layer_never_mints_a_401_and_never_borrows_its_code() -> None:
    """The layer's obligation under the unauthenticated contract is a NEGATIVE one.

    The boundary above owns that status, that single code and the byte-identical bodies whole.
    Reusing either for an AWS-side failure would tell a user to sign in again for something
    signing in again cannot fix. The subject is named by exact module path, and the refusal
    surface is deliberately not in it — that module owns the code.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If this layer mints one.
    """
    for relative in IDENTITY_LAYER:
        source = (HERE / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in (401, "401"):
                raise AssertionError(f"{relative} mints a 401")
        assert errors.UNAUTHENTICATED_CODE not in source, (
            f"{relative} carries the unauthenticated code"
        )


@pytest.mark.parametrize(
    "raised",
    [
        _Denied("AccessDenied"),
        _Denied("AccessDeniedException"),
        identity.IdentityUnavailableError("x"),
        identity.PlaneViolationError("x"),
        RuntimeError("x"),
        ValueError("x"),
        _Denied("ThrottlingException"),
        _Denied("ExpiredToken"),
    ],
)
def test_the_classifier_answers_401_to_nothing(raised) -> None:
    """Behavioural, because the text sweep cannot cover the module that owns the 401.

    Args:
      raised: The exception to classify.

    Returns:
      None.

    Raises:
      AssertionError: If any shape is answered as unauthenticated.
    """
    answer = errors.for_exception(raised)
    if answer is None:
        return
    assert answer["statusCode"] != contract.ERROR_STATUS[errors.UNAUTHENTICATED_CODE]
    assert errors.UNAUTHENTICATED_CODE not in answer["body"]


def test_an_unrecognised_failure_keeps_rising(aws) -> None:
    """Flattening it into a refusal would say something untrue about it, and lose the span.

    Args:
      aws: The recorder.

    Returns:
      None.

    Raises:
      AssertionError: If an unknown failure is dressed up as a refusal.
    """
    assert errors.for_exception(RuntimeError("something else")) is None

    with pytest.raises(RuntimeError):
        _drive(lambda context: (_ for _ in ()).throw(RuntimeError("something else")))


# ── FR-009: what the records carry, and what they must not ────────────────────


def test_the_assume_opens_a_child_span_carrying_the_username_and_the_slot_count(
    aws, captured_events
) -> None:
    """The count, not the names — a per-item detail is a volume decision, and this is not one.

    Args:
      aws: The recorder.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If the span or its fields are missing.
    """
    def _two_spaces(context):
        identity.assume_user_role(
            identity.UserIdentity(
                username=context.acting_as.username,
                memberships={1: "marketing", 2: "finance"},
            )
        )
        return {"ok": True}

    _drive_via_handler(_two_spaces)

    assert captured_events.spans("assume_user_role"), "the assume opened no child span"
    narrated = captured_events.messages("assuming the caller's role")
    assert narrated
    assert narrated[-1]["fields"]["username"] == "alice"
    assert narrated[-1]["fields"]["membership_slots"] == 2


def test_the_username_is_stamped_per_REQUEST_and_survives_a_cache_hit(
    aws, captured_events
) -> None:
    """A stamp inside the cached assume fires on a cold cache and on nothing else.

    That leaves the overwhelming majority of requests — the warm ones — unattributable in the
    log store, while every offline test passes. Both halves are asserted in one sequence: the
    second request emits records carrying the username AND issues no assume at all.

    Args:
      aws: The recorder.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If a cache-served request is unattributable.
    """
    def _route(context):
        identity.user_client("s3", context.acting_as)
        return {"ok": True}

    _drive_via_handler(_route)
    assumed_after_first = len(aws.assume_calls)

    before = len(captured_events.events)
    _drive_via_handler(_route)

    assert len(aws.assume_calls) == assumed_after_first, "the second request re-assumed"

    second_request = captured_events.events[before:]
    assert second_request, "the second request emitted nothing"
    stamped = [
        event for event in second_request if event.get("fields", {}).get("username") == "alice"
    ]
    assert stamped, "a cache-served request emitted no record carrying the caller"


def test_no_field_this_layer_emits_carries_a_token_or_a_credential(
    aws, captured_events
) -> None:
    """The field rule. Usernames and space names go in; nothing bearer-shaped does.

    Args:
      aws: The recorder.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If a token or a session secret reaches a field.
    """
    supplied = token("alice", **_spaces(slot_1="marketing"))
    def _route(context):
        identity.user_client("s3", context.acting_as)
        return {"ok": True}

    _drive_via_handler(_route, {"authorization": f"Bearer {supplied}"})

    serialised = json.dumps(captured_events.events)
    assert supplied not in serialised
    assert CREDENTIAL_SENTINEL not in serialised, "session material reached a log record"
    assert "alice" in serialised, "the caller reached no record at all, so this proves nothing"


def test_no_session_material_reaches_a_record_that_DOES_carry_a_stack(
    aws, captured_events
) -> None:
    """The credential half of the field rule, driven where a stack is genuinely captured.

    ``end_event`` attaches ``format_exception`` to every failed span, and this layer adds
    credential material to that surface: an STS response holds a secret key and a session token,
    and they are live in the frames of any request that raises after assuming. The exposure is
    not automatic — ``format_exception`` renders each frame's SOURCE LINE, not its locals — so
    the live route is this repo's own code putting one into text, which the sweep below forbids.

    **The guard-the-guard is the part that matters.** Every refusal this API produces is
    RETURNED, so its span closes successfully and carries no stack at all; "the sentinel is in no
    record" would then be true of records that have no stack. So this drives a path that raises
    THROUGH the span, holding a real assumed session, and asserts a stack was captured before
    asserting what is not in it. The entry point converts that fault into the envelope's
    InternalError one frame OUTSIDE the span, which is what keeps both true at once — a catch
    inside would close the span successfully and leave nothing to scrub.

    Args:
      aws: The recorder.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If no stack was captured, or if any session material reached a record.
    """
    supplied = token("alice", **_spaces(slot_1="marketing"))

    def _route(context):
        identity.user_client("s3", context.acting_as)
        raise RuntimeError("something went wrong after the session existed")

    response = _drive_via_handler(_route, {"authorization": f"Bearer {supplied}"})
    assert response["statusCode"] == 500, "the fault did not reach the caller as a declared code"

    ended = [event for event in captured_events.events if event["message"] == "span.end"]
    with_error = [event for event in ended if "error" in event]
    assert with_error, "no span carried an error, so the absence below is vacuous"
    assert any("stack" in event["error"] for event in with_error), (
        "no error.stack was captured, so there is nothing for this to be an absence IN"
    )

    serialised = json.dumps(captured_events.events)
    assert aws.assume_calls, "no session was ever assumed, so nothing could have leaked"
    assert CREDENTIAL_SENTINEL not in serialised, "session material reached a record"
    assert supplied not in serialised, "the caller's token reached a record"


def test_no_module_interpolates_SESSION_MATERIAL_into_text_that_travels() -> None:
    """The preventative half, extended to what this layer adds to the surface.

    The boundary above already forbids the event, the headers and a token from being rendered
    into an f-string, a ``%``-format, a ``.format()`` call or a ``raise`` argument. This layer
    introduces four more names worth the same treatment, and they are the ones a builder reaches
    for when writing a diagnostic message about a failed assume.

    **This is prevention, not redaction, and the distinction is recorded rather than blurred.**
    ``log-foundry`` 0.6.0 exposes no way to turn stack capture off, and no redactor exists in
    this repo — so a future route that interpolates a session value into an exception message
    despite this sweep would still reach the log store. That residual is written down as owed
    rather than implied to be closed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module renders session material into text.
    """
    forbidden = {
        "credentials",
        "access_key_id",
        "secret_access_key",
        "session_token",
        "AccessKeyId",
        "SecretAccessKey",
        "SessionToken",
    }

    checked = 0
    for path in sorted(HERE.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            rendered = (
                isinstance(node, ast.JoinedStr)
                or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod))
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "format"
                )
                or isinstance(node, ast.Raise)
            )
            if not rendered:
                continue
            for part in ast.walk(node):
                if isinstance(part, ast.Name):
                    assert part.id not in forbidden, (
                        f"{path.name} renders {part.id!r} into text that travels"
                    )
                if isinstance(part, ast.Attribute):
                    assert part.attr not in forbidden, (
                        f"{path.name} renders .{part.attr} into text that travels"
                    )
    assert checked >= 10, (
        f"the sweep looked at {checked} modules. A floor set well below the real count lets half "
        "the package leave the sweep without anyone noticing."
    )


def test_every_record_carries_a_real_env_and_a_version_from_the_package_stamp(
    monkeypatch, tmp_path
) -> None:
    """FR-009's other half, asserted against the two mechanisms that actually decide.

    The environment name is read at configure time from the function's own variable; the version
    comes from a stamp written into the deployment package. Neither is asserted against a literal
    a test supplied to itself — the first is driven through ``init``, the second through the
    resolver, with a package that carries a stamp.

    Args:
      monkeypatch: pytest's patcher.
      tmp_path: A directory to stand in for the package root.

    Returns:
      None.

    Raises:
      AssertionError: If either mechanism stops populating its field.
    """
    from cpcommon import observability

    captured = {}
    monkeypatch.setattr(observability.lf, "configure", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setenv("ENV_NAME", "prod")

    observability.init(service="api", max_stack_bytes=8192)

    assert captured["env"] == "prod"
    assert captured["env"], "an empty env is a failure"
    assert captured["version"] == observability.build_version()

    (tmp_path / "BUILD_VERSION").write_text("b01930c8\n")
    monkeypatch.delenv("BUILD_VERSION", raising=False)
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    resolved = observability._build_version()

    assert resolved == "b01930c8"
    assert resolved != observability.UNSTAMPED_VERSION


def test_the_deploy_writes_the_stamp_the_resolver_reads() -> None:
    """The middle link. A resolver that reads a file nothing writes returns the unstamped value.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the deploy stopped writing the stamp into the package.
    """
    script = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / ".github"
        / "scripts"
        / "deploy-lambda.sh"
    )
    assert 'BUILD_VERSION"' in script.read_text(), (
        "the deploy no longer writes a build stamp into the package, so every record would "
        "carry the unstamped version"
    )


# ── The limits, announced rather than discovered ──────────────────────────────


def test_no_module_in_this_package_presigns_or_paginates() -> None:
    """Two tripwires for limits a later spec inherits silently otherwise.

    A presigned URL dies with the credential that signed it, so one signed from a cached session
    is valid for the life remaining on that session and not for its stated expiry — the margin
    has to be revisited by the spec that first presigns, not inherited. And the expiry retry sees
    direct calls only: a paginator holds its own client reference and bypasses it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either arrives without the limit being revisited.
    """
    for path in sorted(HERE.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "generate_presigned_url" not in names, (
            f"{path.name} presigns — the credential margin is sized for the life of a REQUEST, "
            "not for a URL that outlives it"
        )
        assert "get_paginator" not in names, (
            f"{path.name} paginates — the single expiry retry does not cover a paginator, "
            "which holds its own client reference"
        )
