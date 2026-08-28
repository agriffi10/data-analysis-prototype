"""The tag set, the session name, and the caps — the half of the identity layer with no AWS in it.

**The requirement here is the one that silently succeeds when it is wrong.** Stamp the username
and omit the ten membership slots, and personal S3, personal Glue, notifications and the file
browser all keep working; only shared spaces refuse, and the app already has a "Refresh access"
recovery built for a documented propagation delay — so a missing tag *presents as that delay*.
Nothing about the running system distinguishes the two. That is why the assertions below are
written against the tag LIST rather than against any behaviour, and why the claim-to-tag mapping
is read back out of Terraform instead of transcribed.

**The Terraform read-backs are chained, and every link is asserted separately**, because a test
comparing two things that both come from a default passes while the deployed value is something
else. The chain: this module reads the slot count from an environment variable; the API module's
environment block sets that variable from a Tofu variable; the Identity Pool's tag map ranges over
the same Tofu variable. Assert only the ends and a broken middle reads as a pass.

Attributes:
  INFRA: The IaC tree.
  IDENTITY_POOL: The declaration AWS actually applies — which claim feeds which tag.
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
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apicommon import config, identity

INFRA = pathlib.Path(__file__).resolve().parent.parent.parent / "infra"
IDENTITY_POOL = INFRA / "modules" / "auth" / "identity-pool.tf"
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


def principal_tag_map(source: str, slots: int) -> dict[str, str]:
    """Parses ``principal_tags`` out of Terraform source into tag name to claim name.

    The declaration is an HCL ``merge()`` of one literal pair and one ``for`` comprehension, so a
    grep for a tag name would pass against a map rewritten to anything still containing the word.
    This reads the structure: the literal pair, and the comprehension's key and value templates
    with the loop variable expanded.

    Args:
      source: The Terraform source holding the map.
      slots: How many membership slots to expand the comprehension over.

    Returns:
      Tag name to the claim name it reads.

    Raises:
      AssertionError: If neither shape is found, so a parser that silently matches nothing
        cannot report an empty map as agreement.
    """
    block = re.search(r"principal_tags\s*=\s*merge\((.*?)\n\s*\)", source, re.DOTALL)
    assert block, "no principal_tags merge() was found — the parser has no subject"
    body = block.group(1)

    literal = re.search(r"\{\s*([A-Za-z_][\w]*)\s*=\s*\"([^\"]+)\"\s*\}", body)
    comprehension = re.search(
        r":\s*\"([^\"]*\$\{k\}[^\"]*)\"\s*=>\s*\"([^\"]*\$\{k\}[^\"]*)\"", body
    )
    assert literal, "the username pair was not found in the map"
    assert comprehension, "the membership comprehension was not found in the map"

    pairs = {literal.group(1): literal.group(2)}
    for slot in range(1, slots + 1):
        pairs[comprehension.group(1).replace("${k}", str(slot))] = comprehension.group(
            2
        ).replace("${k}", str(slot))
    return pairs


def test_the_claim_to_tag_mapping_is_the_one_terraform_declares() -> None:
    """The only thing this layer copies from the Identity Pool, asserted rather than transcribed.

    A hand-written slot name that drifts from the Tofu map produces a session with
    plausible-looking tags that match no policy statement — which reads as a denial everywhere
    and names nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any pair differs.
    """
    slots = config.max_shared_memberships()
    declared = principal_tag_map(IDENTITY_POOL.read_text(), slots)

    implemented = {config.principal_tag_key(): "cognito:username"}
    for slot in range(1, slots + 1):
        implemented[identity.SHARED_SPACE_TAG.format(slot)] = (
            identity.SHARED_SPACE_CLAIM.format(slot)
        )

    assert implemented == declared


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
