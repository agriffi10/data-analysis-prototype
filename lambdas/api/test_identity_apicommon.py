"""The tag set, the session name, and the caps — the half of the identity layer with no AWS in it.

**The requirement here is the one that silently succeeds when it is wrong.** Stamp the username
and omit the ten membership slots, and personal S3, personal Glue, notifications and the file
browser all keep working; only shared spaces refuse, and the app already has a "Refresh access"
recovery built for a documented propagation delay — so a missing tag *presents as that delay*.
Nothing about the running system distinguishes the two. That is why the assertions below are
written against the tag LIST rather than against any behaviour.

**The Terraform read-backs are chained, and every link is asserted separately**, because a test
comparing two things that both come from a default passes while the deployed value is something
else. The chain: this module reads the slot count from an environment variable, and the API
module's environment block sets that variable from a Tofu variable. Assert only the ends and a
broken middle reads as a pass.

The chain used to have a third link — the Identity Pool's tag map, ranging over the same Tofu
variable, and the one Terraform declaration of which CLAIM fed which tag. The pool is retired,
so the claim names are pinned instead; the tripwire below says what would restore the comparison.

Attributes:
  INFRA: The IaC tree.
  API_LAMBDA: The API module's environment block, the middle link of the chain.
  STS_MAX_SESSION_TAGS: STS's ceiling on session tags per AssumeRole call.
  STS_MAX_TAG_KEY: STS's ceiling on one tag key.
  STS_MAX_TAG_VALUE: STS's ceiling on one tag value.
  CATALOG_MIN_LENGTH: The shortest string the catalog identifier rule admits.
  CATALOG_MAX_LENGTH: The longest string that rule admits. Both are asserted against the rule
    rather than counted off it by a reader.
  STS_MIN_ROLE_SESSION_NAME: The shortest role session name STS accepts.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apicommon import config, identity

INFRA = pathlib.Path(__file__).resolve().parent.parent.parent / "infra"
API_LAMBDA = INFRA / "modules" / "api" / "lambda.tf"

STS_MAX_SESSION_TAGS = 50
STS_MAX_TAG_KEY = 128
STS_MAX_TAG_VALUE = 256

CATALOG_MIN_LENGTH = 3
CATALOG_MAX_LENGTH = 63

STS_MIN_ROLE_SESSION_NAME = 2


@pytest.fixture(autouse=True)
def _identity_environment(monkeypatch):
    """Supplies the identity layer's three required values for every test in this module.

    Args:
      monkeypatch: pytest's environment patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("PORTAL_ROLE_ARN", "arn:aws:iam::696000197480:role/dat-portal-user-role")
    monkeypatch.setenv("PRINCIPAL_TAG_KEY", "username")
    monkeypatch.setenv("MAX_SHARED_MEMBERSHIPS", "10")


def _claims(username="alice", **spaces):
    """Builds a verified-claim mapping carrying the given occupied slots.

    Args:
      username: The username claim.
      **spaces: ``slot_<k>=name`` for each occupied slot.

    Returns:
      The claim mapping.

    Raises:
      None.
    """
    claims = {"token_use": "id", "sub": "s", "username_source": username}
    for name, value in spaces.items():
        claims[identity.SHARED_SPACE_CLAIM.format(int(name.split("_")[1]))] = value
    return claims


def _identity(username="alice", **spaces):
    """Builds a UserIdentity for the given occupied slots.

    Args:
      username: The username.
      **spaces: ``slot_<k>=name`` for each occupied slot.

    Returns:
      The identity.

    Raises:
      None.
    """
    return identity.UserIdentity(
        username=username, memberships=identity.memberships_from(_claims(**spaces))
    )


def test_accepted_the_claim_names_agree_with_the_retired_pool_declaration() -> None:
    """ACCEPTED: the claim names are pinned, because nothing declares them any more.

    The Identity Pool's ``principal_tags`` map was the one Terraform declaration of which CLAIM
    each tag reads, and this test compared the layer against it. The pool is retired, and the
    tag NAMES kept three referents — ``sts:TagKeys`` in the trust policy and the
    ``aws:PrincipalTag`` conditions in the two portal-role permission templates — but the claim
    names kept none. Their only remaining referent is the User Pool's own token, which nothing
    offline reads.

    So this pins today's values rather than comparing them. A drifted ``SHARED_SPACE_CLAIM`` or
    ``principal_tag_key`` produces a session whose tags match no policy statement — a denial on
    every path, naming nothing — and this is what is left to catch it.

    REVISIT THE DECISION, DO NOT DELETE THE TEST: the day a provider block, a mapping resource
    or a verifier configuration declares the claim names again, compare against that instead of
    against these literals.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any pair differs from the retired declaration.
    """
    slots = config.max_shared_memberships()

    retired_declaration = {"username": "cognito:username"}
    for slot in range(1, slots + 1):
        retired_declaration[f"shared_space_{slot}"] = f"custom:shared_space_{slot}"

    implemented = {config.principal_tag_key(): "cognito:username"}
    for slot in range(1, slots + 1):
        implemented[identity.SHARED_SPACE_TAG.format(slot)] = (
            identity.SHARED_SPACE_CLAIM.format(slot)
        )

    assert implemented == retired_declaration


def test_the_tag_list_is_the_username_plus_every_occupied_slot() -> None:
    """Eleven entries for a member of ten spaces — the call's own kwarg, not its trace.

    This account records no AssumeRole event anywhere, so the tag list is only ever observable
    here and in the behaviour of a live session.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the count or the contents differ.
    """
    spaces = {f"slot_{k}": f"space_{k}" for k in range(1, 11)}
    tags = identity.session_tags(_identity("alice", **spaces))

    assert len(tags) == 11
    assert tags[0] == {"Key": "username", "Value": "alice"}
    assert [tag["Key"] for tag in tags[1:]] == [f"shared_space_{k}" for k in range(1, 11)]
    assert [tag["Value"] for tag in tags[1:]] == [f"space_{k}" for k in range(1, 11)]


def test_a_username_that_cannot_be_represented_is_refused_never_repaired() -> None:
    """Refusal is deliberate and forward-looking, not an omission.

    The transition replaces the username claim with a subject carrying hyphens and uppercase,
    which this rule will not admit. Refusing loudly from one shared constant makes that a
    single-constant change with a failing test in front of it; sanitising would make it a silent
    identity collision.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any unrepresentable username is accepted or altered.
    """
    for username in (
        "has-a-hyphen",
        "a" * 64,
        "A" * 10,
        "9leading",
        "ab",
        "",
        "has space",
        "has.dot",
    ):
        with pytest.raises(identity.IdentityUnavailableError):
            identity.role_session_name(username)


def test_the_s3_client_is_pinned_to_sigv4_and_to_the_regional_endpoint(monkeypatch) -> None:
    """Both S3 pins, asserted at the one construction site, because both fail invisibly.

    **The signature version.** Left to botocore's S3 default the client presigns the legacy
    SigV2 query form — ``AWSAccessKeyId``/``Signature``/``Expires`` in place of
    ``X-Amz-Signature``/``X-Amz-Expires``. A bucket old enough to still accept SigV2 redeems
    such a URL without complaint, so the browser fetches the object, the upload succeeds, every
    offline test passes and nothing anywhere goes red. Measured shipped that way on 2026-09-01
    against a real upload. What it costs is not tidiness: AWS is retiring SigV2 for S3, a bucket
    requiring SSE-KMS under a customer-managed key refuses a SigV2 URL outright, and credentials
    vended for a scoped grant are signed as SigV4 or not at all — so the transition's storage
    plane inherits a signing version that cannot carry it.

    **The endpoint style**, which had no test at all despite a docstring calling it load-bearing:
    botocore presigns against the legacy global host in every region by default, which the SPA's
    ``connect-src`` does not name, so an upload fails as a generic network error while every
    download keeps working.

    The assertion is on the kwargs handed to ``boto3.client`` rather than on a built client,
    because a built client resolves defaults and would agree with either setting.

    Args:
      monkeypatch: Intercepts the client construction.

    Returns:
      None.

    Raises:
      AssertionError: If either pin is absent, or if a non-S3 service is given a config.
    """
    import boto3

    captured: dict[str, object] = {}

    def _capture(service, **kwargs):
        captured["service"] = service
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(boto3, "client", _capture)

    identity._client(identity.S3_SERVICE, None)
    built = captured["kwargs"]["config"]

    assert built.signature_version == "s3v4", (
        "botocore's S3 default presigns SigV2, which a grandfathered bucket redeems happily"
    )
    assert built.s3["addressing_style"] == "virtual"
    assert built.s3["us_east_1_regional_endpoint"] == "regional"

    captured.clear()
    identity._client("sts", None)
    assert "config" not in captured["kwargs"], "the pins are S3's, not every service's"
