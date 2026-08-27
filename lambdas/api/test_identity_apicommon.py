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
from cpcommon.config import CATALOG_IDENTIFIER_RE

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


def test_the_map_parser_reads_the_structure_rather_than_recognising_the_words() -> None:
    """Guard-the-guard: fed a map naming nothing familiar, the parser must return THAT map.

    A parser that matched on the strings it expects would agree with any file still containing
    them, which is the failure the read-back exists to prevent.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the parser does not return the synthetic map it was given.
    """
    synthetic = """
  principal_tags = merge(
    { handle = "provider:handle" },
    { for k in range(1, var.slots + 1) : "team_${k}" => "custom:team_${k}" }
  )
"""
    assert principal_tag_map(synthetic, 2) == {
        "handle": "provider:handle",
        "team_1": "custom:team_1",
        "team_2": "custom:team_2",
    }


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


def test_the_slot_count_is_the_same_tofu_variable_all_the_way_down() -> None:
    """The middle link: the API's environment block, and the map's own range.

    Asserting the Python constant against a Tofu DEFAULT would pass even if the API module never
    set the variable at all, and an unset repo variable renders as the empty string — which
    satisfies a required variable and overrides a default. So the assertion is on the wiring.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the environment block does not carry the variable, or the tag map
        ranges over a different one.
    """
    lambda_source = API_LAMBDA.read_text()
    for key, expression in (
        ("PORTAL_ROLE_ARN", r"var\.portal_role_arn"),
        ("PRINCIPAL_TAG_KEY", r"var\.principal_tag_key"),
        ("MAX_SHARED_MEMBERSHIPS", r"tostring\(var\.max_shared_memberships\)"),
    ):
        assert re.search(rf"{key}\s*=\s*{expression}", lambda_source), (
            f"the API function's environment does not set {key} from its Tofu variable"
        )

    assert re.search(
        r"range\(1,\s*var\.max_shared_memberships \+ 1\)", IDENTITY_POOL.read_text()
    ), "the tag map no longer ranges over the variable the function is sized from"


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


def test_an_unoccupied_slot_contributes_no_tag_at_all() -> None:
    """Absent, never present-and-empty — asserted on the KEY, not on the value being falsy.

    An empty-valued tag makes a shared-space resource ARN resolve to the bucket followed by a
    bare slash, which is a live grant on every key beginning with one, and S3 permits such a key.
    An unstamped slot matches nothing instead.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an unoccupied slot appears in the list at all.
    """
    tags = identity.session_tags(_identity("alice", slot_2="marketing"))
    keys = [tag["Key"] for tag in tags]

    assert keys == ["username", "shared_space_2"]
    for slot in range(1, 11):
        if slot != 2:
            assert f"shared_space_{slot}" not in keys


def test_an_empty_or_non_string_claim_occupies_no_slot() -> None:
    """The two shapes a claim can arrive in that must not become a tag.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either produces a membership.
    """
    for value in ("", None, 0, [], {}):
        claims = {identity.SHARED_SPACE_CLAIM.format(3): value}
        assert identity.memberships_from(claims) == {}


def test_the_tag_count_bound_is_computed_against_the_limits_that_size_it() -> None:
    """The schedulable unit is ONE TAG PER MEMBERSHIP SLOT, plus one for the username.

    A hard-coded ceiling hides a wrong model, so this computes the headroom rather than asserting
    a number, and fails if raising the slot count would breach a limit STS actually enforces.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the tag set, its keys or its values exceed what STS accepts.
    """
    slots = config.max_shared_memberships()
    tags_per_session = 1 + slots
    assert tags_per_session <= STS_MAX_SESSION_TAGS, (
        f"{slots} membership slots plus the username is {tags_per_session} session tags, over "
        f"STS's ceiling of {STS_MAX_SESSION_TAGS}"
    )

    longest_key = max(
        [len(config.principal_tag_key())]
        + [len(identity.SHARED_SPACE_TAG.format(slot)) for slot in range(1, slots + 1)]
    )
    assert longest_key <= STS_MAX_TAG_KEY

    assert CATALOG_MAX_LENGTH <= STS_MAX_TAG_VALUE, (
        "a catalog-safe name no longer fits in a session tag value"
    )

    headroom = STS_MAX_SESSION_TAGS - tags_per_session
    assert headroom >= 0
    assert slots + headroom == STS_MAX_SESSION_TAGS - 1, (
        "the computation lost track of the username tag"
    )


def test_the_catalog_rule_admits_exactly_the_lengths_this_computation_assumes() -> None:
    """The 63 above is derived from the rule, not counted off it by a reader.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the rule's bounds moved.
    """
    assert CATALOG_IDENTIFIER_RE.match("a" * CATALOG_MAX_LENGTH)
    assert not CATALOG_IDENTIFIER_RE.match("a" * (CATALOG_MAX_LENGTH + 1))
    assert CATALOG_IDENTIFIER_RE.match("a" * CATALOG_MIN_LENGTH)
    assert not CATALOG_IDENTIFIER_RE.match("a" * (CATALOG_MIN_LENGTH - 1))


def test_the_session_name_is_the_username_verbatim() -> None:
    """No prefix, no suffix, no transformation.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the name differs from the username by any byte.
    """
    for username in ("alice", "bob_smith", "a" * CATALOG_MAX_LENGTH, "abc"):
        assert identity.role_session_name(username) == username


def test_no_valid_username_needs_escaping() -> None:
    """Containment, COMPUTED: nothing the catalog rule admits can need escaping for STS.

    The character class is a strict subset and the length range sits inside. Both are arithmetic
    a reader would otherwise take on trust, and taking it on trust is how a session name comes to
    be silently transformed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either containment fails.
    """
    catalog_alphabet = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    sts_alphabet = {chr(code) for code in range(32, 127) if re.match(r"[\w+=,.@-]", chr(code))}
    assert catalog_alphabet < sts_alphabet, "a catalog-safe username can need escaping"

    assert STS_MIN_ROLE_SESSION_NAME <= CATALOG_MIN_LENGTH
    assert CATALOG_MAX_LENGTH <= identity.MAX_ROLE_SESSION_NAME


def test_the_prefix_BUDGET_is_one_character_which_is_why_there_is_no_prefix() -> None:
    """The spec's arithmetic here was off by one, and computing it is what found that.

    SPEC-196 FR-004 states that "63 + any non-empty prefix exceeds 64". It does not: the longest
    catalog-safe username is 63 and STS admits 64, so the budget is exactly ONE character and a
    one-character prefix fits. The requirement is unaffected — the session name is the username
    verbatim — but the reason is not the one written down, and a reason that reads false to
    whoever checks it is worse than none.

    The true reason is this budget: one character is not a namespace, so any prefix worth having
    (a service name, an environment, a separator) overflows for the longest usernames — and the
    only way to make it fit is to truncate, which collapses two distinct usernames onto one
    identity in every trail that records the session.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the budget grew enough to make a real prefix possible, or if
        truncation stopped colliding.
    """
    budget = identity.MAX_ROLE_SESSION_NAME - CATALOG_MAX_LENGTH
    assert budget == 1, (
        f"the prefix budget is now {budget} characters — if it has grown, the argument for a "
        "verbatim session name has to be remade rather than inherited"
    )

    for prefix in ("portal-", "api_", "u-", "ab"):
        assert len(prefix) + CATALOG_MAX_LENGTH > identity.MAX_ROLE_SESSION_NAME, (
            f"the prefix {prefix!r} now fits, so this reasoning needs rewriting"
        )

    prefix = "portal-"
    retained = identity.MAX_ROLE_SESSION_NAME - len(prefix)
    assert retained < CATALOG_MAX_LENGTH, (
        "the prefix no longer costs any username characters, so nothing below is a collision"
    )

    first = "a" * retained + "b"
    second = "a" * retained + "c"
    assert first != second
    assert (prefix + first)[: identity.MAX_ROLE_SESSION_NAME] == (prefix + second)[
        : identity.MAX_ROLE_SESSION_NAME
    ], "truncation collapses two distinct usernames onto one session identity"


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


def test_the_refusal_carries_a_fixed_reason_and_not_the_name_it_refused() -> None:
    """A reason code is not a message; the username travels as a log field instead.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the refused value appears in the exception text.
    """
    refused = "Mallory-The-Attacker"
    with pytest.raises(identity.IdentityUnavailableError) as raised:
        identity.role_session_name(refused)
    assert str(raised.value) == identity.REASON_UNREPRESENTABLE_USERNAME
    assert refused not in str(raised.value)
