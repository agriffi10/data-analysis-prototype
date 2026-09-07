"""The two Python archive write-locks, held against the IAM Deny they claim to mirror.

The rule that ``archive/`` is not user-writable has three implementations — one in the browser and
one in each of two control planes — and only the browser's was tied to the policy. Both Python
copies were pinned by hand-written expectations whose docstrings NARRATE the Deny but never read
it, so a change to what the policy MEANS left them green. Measured: widening the personal Deny's
anchor from the principal tag to ``*`` — the document still parses, still ends ``/archive/*``, and
now denies any user's archive rather than the caller's own — reddens ``archiveWriteLock.test.ts``
on three rows while both Python suites stay green.

This is that test's method in Python, over ONE matcher and ONE key table serving both planes, so
the two cannot drift from the policy or from each other.

**The two buckets deny DIFFERENTLY, and the table must not average them.** The personal Deny is
anchored at the caller's own root, because in that bucket the prefix IS the principal tag. The
shared Deny puts a wildcard where the space name goes, and an S3 resource wildcard matches ``/``,
so it reaches an ``archive`` folder at any depth. Both ``protected.py`` module docstrings say so in
prose; the rows below are what makes the claim executable, and the controls at the bottom are what
stop a matcher that had collapsed into one rule from agreeing with everything.

**Read as TEXT, never parsed as JSON.** The shared template carries ``%{ for … }`` directives that
render the per-membership-slot Allows, so there is no JSON document until ``templatefile()`` runs.
The question being asked — what does this Sid's Resource say — does not need one.

**What is pinned is the ARCHIVE arm, not either predicate in general.**
``focommon.protected._is_at_or_below`` takes a folder NAME and serves ``athenaresults`` and
``user_settings`` too, whose rules are a different shape: delete-only for the first, and no bucket
Deny at all for the second, which is this plane's own rule. Holding the general predicate to the
archive Deny would assert something the policy does not say.

Attributes:
  ROOT: The repository root.
  PERSONAL_TEMPLATE: The user-space bucket's portal-role policy template.
  SHARED_TEMPLATE: The shared-space bucket's portal-role policy template.
  PERSONAL_DENY: The user-space Deny as a predicate over keys, both statements unioned.
  SHARED_DENY: The shared-space Deny as a predicate over keys, both statements unioned.
  KEY_SUFFIXES: The keys under test, written once as suffixes of a space root so both kinds are
    provably the same shapes and the asymmetry below cannot be an artefact of two hand-written
    tables. Two rows are here for the ``…SystemSettings`` sibling rather than for the rule:
    ``backups/system_settings/archive/…`` is the ONLY key that distinguishes the sibling's anchor
    from a widened one, since every other settings key sits directly under the space root where an
    anchored and an unanchored Deny answer alike — measured, the widening survived without it. And
    ``system_settings/archive`` with no trailing slash is the file/folder distinction on the second
    home, which the first version of the API's segment scan got wrong.
  BUCKETS: Each space kind with its root and its Deny, the parametrisation both agreement tests
    take.
"""

import pathlib
import re
import sys
from typing import TYPE_CHECKING

import pytest
from focommon.config import ARCHIVE_FOLDER
from focommon.protected import _is_at_or_below

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas" / "api"))

from apicommon import protected as api_protected
from apicommon import spaces

if TYPE_CHECKING:
    from collections.abc import Callable

PERSONAL_TEMPLATE = ROOT / "infra" / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
SHARED_TEMPLATE = (
    ROOT / "infra" / "modules" / "shared-spaces" / "policies" / "portal-role-shared-space.json.tftpl"
)


def _deny_resource_of(body: str, sid: str) -> str:
    """The Resource string of the named Deny, as the template spells it.

    Sliced out by Sid rather than parsed: the shared template renders to JSON and is not JSON. The
    slice runs to the NEXT ``"Sid"`` and its length is checked against the document's, because a
    slice that ran to the end of the file would pick up a Resource belonging to another statement
    and agree with anything.

    The Effect is checked here rather than left to the policy suites because it is a precondition
    of this matcher's MEANING, not a restatement of a policy rule: a key matcher built from an
    Allow's Resource would compare the predicates against a permission.

    Args:
      body: The template's text.
      sid: The statement id to read.

    Returns:
      The statement's Resource, with its template placeholders intact.

    Raises:
      AssertionError: If the Sid is absent, if the slice swallowed the document, if the statement
        is not a Deny, or if it carries no single-string Resource.
    """
    start = body.find(f'"Sid": "{sid}"')
    assert start > -1, f"no {sid} statement — this matcher would otherwise be built from nothing"
    end = body.find('"Sid"', start + 1)
    statement = body[start:] if end == -1 else body[start:end]
    assert len(statement) < len(body), f"the {sid} slice swallowed the document"
    assert re.search(r'"Effect":\s*"Deny"', statement), f"{sid} is not a Deny, so its Resource is a grant"
    resource = re.search(r'"Resource":\s*"([^"]+)"', statement)
    assert resource, f"{sid} has no single-string Resource"
    return resource.group(1)


def _key_matcher(resource: str, principal: str) -> "Callable[[str], bool]":
    """The IAM resource as a predicate over object keys.

    Everything after the bucket ARN, with ``*`` matching ANY character INCLUDING ``/`` — the
    property that makes the shared Deny reach any depth, and the one an intuition about shell globs
    gets wrong.

    The principal tag is substituted in the ONE spelling a template can carry. It survives two
    stages — ``$${aws:PrincipalTag/username}`` here escapes to ``${aws:PrincipalTag/username}`` in
    the rendered policy, and at request time IAM substitutes the caller's own username for it — but
    this reads the template, so the escaped form is the only one that ever arrives. Handling the
    rendered form too would be a branch nothing can reach: measured, replacing it with a no-op left
    every row green.

    That the substitution HAPPENED is asserted rather than assumed. A renamed tag key would leave
    the placeholder standing in the pattern, and a pattern comparing keys against a literal
    ``${aws:PrincipalTag/…}`` answers False for every personal row — a disagreement the table would
    report as the predicate's fault.

    Args:
      resource: The Deny's Resource, as the template spells it.
      principal: The username or space name to substitute for the principal tag.

    Returns:
      A predicate answering whether this Deny's Resource covers a key.

    Raises:
      AssertionError: If the Resource carries no bucket ARN to strip, which would leave the matcher
        comparing keys against an ARN and answering False for everything, or if a principal tag
        survived substitution.
    """
    bucket_end = resource.find("}/")
    assert bucket_end > -1, f"no bucket ARN placeholder in {resource!r}"
    key_part = resource[bucket_end + 2 :].replace("$${aws:PrincipalTag/username}", principal)
    assert "PrincipalTag" not in key_part, (
        f"a principal tag survived substitution in {resource!r} — the matcher would compare keys "
        "against a literal placeholder and deny nothing"
    )
    pattern = "[\\s\\S]*".join(re.escape(part) for part in key_part.split("*"))
    return lambda key: re.fullmatch(pattern, key) is not None


def _any_of(*matchers: "Callable[[str], bool]") -> "Callable[[str], bool]":
    """The union of a Sid and its ``…SystemSettings`` sibling.

    The receipt folder has two admitted homes and IAM refuses each with its own statement, so a
    matcher built from one of them would agree with a predicate only where that one reaches — and
    the row that would catch it is the row the sibling exists for.

    Args:
      *matchers: The statements' matchers.

    Returns:
      A predicate true where any of them is.

    Raises:
      None.
    """
    return lambda key: any(matches(key) for matches in matchers)


_PERSONAL_BODY = PERSONAL_TEMPLATE.read_text()
_SHARED_BODY = SHARED_TEMPLATE.read_text()

PERSONAL_DENY = _any_of(
    _key_matcher(_deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritable"), "alice"),
    _key_matcher(_deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritableSystemSettings"), "alice"),
)
SHARED_DENY = _any_of(
    _key_matcher(_deny_resource_of(_SHARED_BODY, "SharedArchiveReceiptsAreNotUserWritable"), "finance"),
    _key_matcher(_deny_resource_of(_SHARED_BODY, "SharedArchiveReceiptsAreNotUserWritableSystemSettings"), "finance"),
)

KEY_SUFFIXES = (
    "whatever.csv",
    "archive/whatever.csv",
    "archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/receipt.json",
    "reports/whatever.csv",
    "backups/archive/whatever.csv",
    "backups/archive/",
    "archived-notes/whatever.csv",
    "system_settings/whatever.csv",
    "system_settings/archive/whatever.csv",
    "system_settings/archive/3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93/receipt.json",
    "backups/system_settings/archive/whatever.csv",
    "a/b/c/archive/whatever.csv",
    "archive",
    "reports/archive",
    "system_settings/archive",
)

BUCKETS = (
    pytest.param("alice/", "personal", PERSONAL_DENY, id="personal"),
    pytest.param("finance/", "shared", SHARED_DENY, id="shared"),
)


@pytest.mark.parametrize("root, kind, deny", BUCKETS)
@pytest.mark.parametrize("suffix", KEY_SUFFIXES)
def test_the_api_write_lock_answers_what_the_deny_says(suffix, root, kind, deny):
    """``apicommon.protected.is_write_locked`` agrees with the bucket's own Deny, key by key.

    This is the API's last word before a presign, so a False where the Deny says True hands the
    browser a URL S3 will refuse, and a True where it says False is a 403 for a write that would
    have worked.
    """
    space = spaces.ResolvedSpace(kind, root.rstrip("/"), f"{kind}-bucket", root)
    key = f"{root}{suffix}"

    assert api_protected.is_write_locked(space, key) is deny(key)


@pytest.mark.parametrize("root, kind, deny", BUCKETS)
@pytest.mark.parametrize("suffix", KEY_SUFFIXES)
def test_the_file_ops_write_lock_answers_what_the_deny_says(suffix, root, kind, deny):
    """``focommon.protected._is_at_or_below`` agrees with the same Deny, for the archive name.

    Called with ``ARCHIVE_FOLDER`` only. The same function serves ``athenaresults`` and
    ``user_settings``, whose rules this Deny does not describe, and constraining those here would
    pin the general predicate to a policy that says nothing about them.
    """
    key = f"{root}{suffix}"

    assert _is_at_or_below(key, root, ARCHIVE_FOLDER, space_kind=kind) is deny(key)


@pytest.mark.parametrize("root, kind, deny", BUCKETS)
def test_the_key_table_exercises_both_answers(root, kind, deny):
    """The positive control, per bucket: a table every row of which is denied — or none of which
    is — would let an always-True or always-False predicate agree with an equally broken matcher
    and pass every row above.
    """
    assert {deny(f"{root}{suffix}") for suffix in KEY_SUFFIXES} == {True, False}


def test_the_two_denies_really_do_differ_so_the_asymmetry_is_not_an_artefact():
    """One key, two answers. If this fails, a policy changed shape and the predicates should
    follow it rather than the table being edited to agree with a rule nobody re-read.
    """
    assert PERSONAL_DENY("alice/backups/archive/x.csv") is False
    assert SHARED_DENY("finance/backups/archive/x.csv") is True


def test_the_wildcard_matches_a_slash_which_is_the_trap_in_reading_these_resources():
    """``*`` in an S3 resource ARN is not a shell glob.

    A matcher that stopped at ``/`` would make every shared row above agree with a root-anchored
    predicate, and both tests would pass while the planes permitted writes IAM refuses.
    """
    assert SHARED_DENY("finance/a/b/c/archive/x.csv") is True


def test_the_settings_sibling_is_what_covers_the_personal_second_home():
    """Without this the union could be carried by either half, and the sibling could be deleted
    with every row still green — the shape that makes a union matcher vacuous.
    """
    original = _key_matcher(_deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritable"), "alice")
    sibling = _key_matcher(
        _deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritableSystemSettings"), "alice"
    )

    assert original("alice/system_settings/archive/x.csv") is False
    assert sibling("alice/system_settings/archive/x.csv") is True
    assert sibling("alice/archive/x.csv") is False


def test_the_shared_siblings_redundancy_is_real_rather_than_assumed():
    """The shared wildcard already reached the second home before the sibling landed.

    The browser test says so in prose and the narrowing depends on it — removing the old form has
    to leave the second home covered — so it is asserted rather than believed.
    """
    original = _key_matcher(_deny_resource_of(_SHARED_BODY, "SharedArchiveReceiptsAreNotUserWritable"), "finance")

    assert original("finance/system_settings/archive/x.csv") is True
