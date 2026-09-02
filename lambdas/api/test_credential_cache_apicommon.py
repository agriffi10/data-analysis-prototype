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

import datetime
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import TypedDict

import router
from apicommon import config, contract, errors, identity
from conftest import bearer, declare_route
from tf_blocks import lambda_declaration, lambda_input


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
    query=None,
    response=contract.UserDirectoryResponse,
)

_FAILURE_ROUTE = contract.Route(
    id="test.failure",
    method="GET",
    path="/v1/_test-failure",
    idempotent=True,
    plane="user",
    request=None,
    query=None,
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


# ── FR-006: the cache, and the leak it invites ────────────────────────────────


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

    # Read through tf_blocks rather than by regex, because the attribute is spelled differently
    # under the two packagings and a pattern that matches only one of them stops finding the
    # number without ever saying so.
    timeout = lambda_input(lambda_declaration(declared.read_text(), "api"), "timeout")

    assert int(timeout) == API_FUNCTION_TIMEOUT_SECONDS
    assert config.CREDENTIAL_EXPIRY_MARGIN_SECONDS == API_FUNCTION_TIMEOUT_SECONDS

    usable = (
        config.ASSUME_ROLE_DURATION_SECONDS - config.CREDENTIAL_EXPIRY_MARGIN_SECONDS
    ) / config.ASSUME_ROLE_DURATION_SECONDS
    assert usable > 0.95, (
        f"the margin leaves only {usable:.0%} of a session usable, so the cache buys nothing"
    )


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




class TestASigningSessionCoversTheWindowItSigns:
    """The cache's margin is one REQUEST; a presigned URL outlives the request.

    ``_usable`` hands back any session with more than one function timeout left, which is right for
    a call that finishes inside the invocation and wrong for a URL the browser redeems afterwards.
    The clamp then signs for whatever happens to remain, so the window a user gets is a draw from
    roughly the whole hour rather than the number the route asked for — about a quarter of mints
    under 900 s and about one in a hundred under a minute.

    **It is not a rare edge and it is not visible in a passing test**, which is why it needs its
    own: every offline assertion about the clamp is satisfied by a short window, because a short
    window IS correctly clamped.
    """

    def test_a_session_too_short_for_the_window_is_replaced_not_clamped_against(self, aws) -> None:
        """The fix, stated as the thing a user would notice.

        Args:
          aws: The stubbed AWS boundary.

        Returns:
          None.

        Raises:
          AssertionError: If the near-dead session is the one handed to the signer.
        """
        identity.reset_credential_cache()
        # The cached session is OLD, not short-lived: STS always issues the same duration, and what
        # varies is how long ago it was issued. The stub cannot age an entry, so the lifetime is
        # set per call — 120 s for the one already in the cache, a full session for the re-assume.
        aws.lifetime_seconds = 120
        caller = _caller("alice")
        identity.assume_user_role(caller)
        aws.lifetime_seconds = FAR_FUTURE_SECONDS

        _, credentials = identity.signing_client("s3", caller, covering=900)

        assert len(aws.assume_calls) == 2, "a session too short for the window was signed with"
        remaining = (
            credentials.expires_at - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        assert remaining > 900

    def test_a_session_that_ALREADY_covers_the_window_is_reused(self, aws) -> None:
        """The other half, and the one that keeps the fix from being "always re-assume".

        An unconditional force would make every presign an `AssumeRole` — and would defeat the
        cache the credential layer exists to have.

        Args:
          aws: The stubbed AWS boundary.

        Returns:
          None.

        Raises:
          AssertionError: If a perfectly good session is thrown away.
        """
        identity.reset_credential_cache()
        caller = _caller("alice")
        identity.assume_user_role(caller)

        identity.signing_client("s3", caller, covering=900)

        assert len(aws.assume_calls) == 1

    def test_the_client_signs_with_the_session_that_was_returned(self, aws) -> None:
        """The property the whole accessor exists for, re-asserted across the new branch.

        A forced re-assume that returned the FRESH credentials while building the client from the
        stale ones would be the original defect with an extra step — and every expiry assertion
        would still pass, because the returned expiry would be honest about a session that did not
        sign.

        Args:
          aws: The stubbed AWS boundary.

        Returns:
          None.

        Raises:
          AssertionError: If the client and the returned credentials disagree.
        """
        identity.reset_credential_cache()
        aws.lifetime_seconds = 120
        caller = _caller("alice")
        identity.assume_user_role(caller)
        aws.lifetime_seconds = FAR_FUTURE_SECONDS

        _, credentials = identity.signing_client("s3", caller, covering=900)

        assert aws.built[-1].session["aws_access_key_id"] == credentials.access_key_id
