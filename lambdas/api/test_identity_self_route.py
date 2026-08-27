"""The probe, and the negative control that is the whole reason it exists.

A route asserting only that a caller can list their own prefix would pass with the isolation model
deleted. So the pass condition is a conjunction, and both halves are driven here — including the
case that matters most and is easiest to get wrong: a foreign listing must come back ``false``
because **AWS refused it**, never because something went wrong. A broad handler would render
``false`` for a timeout, a throttle or a missing bucket, and report a passing isolation proof for
a call that never happened.

Attributes:
  FOREIGN: The constant prefix the negative control lists.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import handler as api_handler
import router
from apicommon import identity
from conftest import bearer
from cpcommon.config import CATALOG_IDENTIFIER_RE
from routes.identity_self import FOREIGN_PREFIX, PROBE_MAX_KEYS, identity_self

FOREIGN = FOREIGN_PREFIX


class _Denied(Exception):
    """A botocore-shaped refusal."""

    def __init__(self, code="AccessDenied"):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": "not authorized"}}


class _S3:
    """S3, refusing whichever prefixes the test names."""

    def __init__(self, refuse, fault=None):
        self.refuse = refuse
        self.fault = fault
        self.calls = []

    def list_objects_v2(self, **kwargs):
        """Records the listing and refuses the named prefixes."""
        self.calls.append(kwargs)
        if self.fault is not None and kwargs["Prefix"] == self.fault[0]:
            raise self.fault[1]
        if kwargs["Prefix"] in self.refuse:
            raise _Denied()
        return {"KeyCount": 0}


@pytest.fixture
def s3(monkeypatch):
    """Installs an S3 stub in place of the user-plane door.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      A factory taking the refused prefixes and an optional fault.

    Raises:
      None.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    installed = {}

    def _install(refuse=(), fault=None):
        client = _S3(set(refuse), fault)
        installed["client"] = client
        monkeypatch.setattr(identity, "user_client", lambda service, caller: client)
        return client

    return _install


def _event(headers=None, **extra):
    """One API Gateway payload-format-2.0 request for the probe.

    Args:
      headers: The request headers.
      **extra: Anything else to hang off the event.

    Returns:
      The event.

    Raises:
      None.
    """
    return {
        "requestContext": {
            "http": {"method": "GET", "path": "/_identity/self"},
            "requestId": "req-probe",
        },
        "headers": bearer() if headers is None else headers,
        **extra,
    }


def test_the_foreign_prefix_can_never_be_a_username_by_CONSTRUCTION(s3) -> None:
    """Not by choosing something unlikely — by failing the rule every username satisfies.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If the constant could ever collide with a real caller's prefix.
    """
    bare = FOREIGN.rstrip("/")
    assert not CATALOG_IDENTIFIER_RE.match(bare), (
        f"{bare!r} satisfies the username rule, so the negative control could be listing a real "
        "user's prefix"
    )
    assert FOREIGN.endswith("/")
    assert bare not in ("_directory", "_config"), (
        "the negative control names a prefix the portal role is separately granted"
    )


def test_the_probe_lists_exactly_two_prefixes_one_key_each(s3) -> None:
    """One key is enough to learn whether a listing is permitted, and it is billed like any other.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If the probe issues anything other than the two bounded listings.
    """
    client = s3(refuse={FOREIGN})
    api_handler.handler(_event(), None)

    assert [call["Prefix"] for call in client.calls] == ["alice/", FOREIGN]
    assert all(call["MaxKeys"] == PROBE_MAX_KEYS == 1 for call in client.calls)
    assert all(call["Bucket"] == "dat-prod-user-space" for call in client.calls)


def test_the_pass_condition_is_a_CONJUNCTION_and_arrives_as_a_200(s3) -> None:
    """Both booleans, in a 200 body — not a 403.

    This is the shape a per-request classifier would have destroyed: the negative control's whole
    job is to be refused, so a refusal that ended the request would make the pass condition
    unreachable, and the failure would read as "isolation working".

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If either boolean is wrong, or the refusal escaped the route.
    """
    s3(refuse={FOREIGN})
    response = api_handler.handler(_event(), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["ownPrefixListable"] is True
    assert body["foreignPrefixListable"] is False
    assert body["ownPrefixListable"] and not body["foreignPrefixListable"]


def test_an_unstamped_tag_shows_up_as_the_FIRST_boolean(s3) -> None:
    """The two halves fail for different reasons, and this is the one a tag drop produces.

    The portal role grants a listing only under a prefix condition naming the tag, so a session
    without it cannot list even its own prefix.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If a refused own-prefix listing is not reported.
    """
    s3(refuse={"alice/", FOREIGN})
    body = json.loads(api_handler.handler(_event(), None)["body"])

    assert body["ownPrefixListable"] is False
    assert body["foreignPrefixListable"] is False


def test_an_over_granted_policy_shows_up_as_the_SECOND(s3) -> None:
    """The other half. A probe asserting only the first would pass with isolation deleted.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If a permitted foreign listing is not reported.
    """
    s3(refuse=set())
    body = json.loads(api_handler.handler(_event(), None)["body"])

    assert body["ownPrefixListable"] is True
    assert body["foreignPrefixListable"] is True, (
        "a foreign prefix was listable and the probe reported it as isolated"
    )


def test_a_FAULT_on_the_negative_control_is_not_reported_as_isolation(s3) -> None:
    """"False" must mean AWS refused, never that the call did not happen.

    This is the one route the whole live verification hangs on, so a throttle or an outage
    rendering as a passing isolation proof would be the worst kind of green.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If a non-denial failure is flattened into the boolean.
    """
    s3(refuse=set(), fault=(FOREIGN, _Denied("ServiceUnavailable")))

    with pytest.raises(_Denied, match="ServiceUnavailable"):
        api_handler.handler(_event(), None)


def test_the_probe_reports_the_caller_and_their_space_count(s3) -> None:
    """The count comes from the claims, which is a limitation this route records rather than hides.

    Nothing it touches is governed by a membership tag, so the number is the same with every slot
    tag dropped — the slot half of the proof is owed to the spec that reaches a shared space.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If either field is wrong.
    """
    s3(refuse={FOREIGN})
    claims = {
        identity.SHARED_SPACE_CLAIM.format(1): "marketing",
        identity.SHARED_SPACE_CLAIM.format(4): "finance",
    }
    body = json.loads(
        api_handler.handler(_event(bearer("alice", **claims)), None)["body"]
    )

    assert body["username"] == "alice"
    assert body["spaceCount"] == 2


def test_the_probe_takes_no_parameter_of_any_kind(s3) -> None:
    """A route that listed a caller-supplied prefix is credential selection wearing a probe's hat.

    Asserted twice: the handler's signature offers nowhere to put one, and a request carrying a
    query string and a body changes nothing about what is listed.

    Args:
      s3: The stub factory.

    Returns:
      None.

    Raises:
      AssertionError: If the route accepts an input, or a supplied one reaches a listing.
    """
    import inspect

    assert list(inspect.signature(identity_self).parameters) == ["context"]

    client = s3(refuse={FOREIGN})
    api_handler.handler(
        _event(
            queryStringParameters={"prefix": "bob/", "username": "bob"},
            body=json.dumps({"prefix": "bob/"}),
        ),
        None,
    )

    listed = [call["Prefix"] for call in client.calls]
    assert listed == ["alice/", FOREIGN]
    assert not any("bob" in prefix for prefix in listed)


def test_the_probe_needs_a_verified_token() -> None:
    """It makes a real call as a real caller, so it cannot be reachable without one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If it answers anything but the one refusal.
    """
    assert router.route("GET", "/_identity/self", {})["statusCode"] == 401
    assert (
        router.route("GET", "/_identity/self", {"authorization": "Bearer nope"})[
            "statusCode"
        ]
        == 401
    )
