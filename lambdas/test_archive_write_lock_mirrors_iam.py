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

**And it is the PORTAL role's Deny throughout, which is not the only one in play.** The file
operations plane acts under its own execution role, and that role's Denies read
``{bucket}/*/system_settings/archive/*`` — any-depth in BOTH buckets, where the portal role's is
anchored at the caller's root. So ``_is_at_or_below`` is deliberately looser than the role its
plane runs under: it mirrors the browser's affordance, and ``focommon.protected.role_denied_folder``
carries the execution role's stricter rule, held against that role in
``test_file_ops_rules_mirror_execution_role.py``. Reading a green run
here as "the file-ops plane agrees with its own IAM" is the misreading to avoid; what it says is
that the plane's affordance agrees with the browser's, against the policy that defines it.

**The API's results-folder refusal is held the same way, against a DELETE Deny.** IAM permits a
write beneath the query results folder and refuses its removal, so ``is_in_results_folder`` is
pinned to where that Deny reaches — which is exactly where a write could never be undone. Its own
key table carries the rows that tell its rule apart: the depth-one name the folder left, a file
named like the folder, a sibling name, a split pair, and the nested pair on which the two buckets
disagree.

Attributes:
  ROOT: The repository root.
  PERSONAL_TEMPLATE: The user-space bucket's portal-role policy template.
  SHARED_TEMPLATE: The shared-space bucket's portal-role policy template.
  ANALYTICS_TEMPLATE: The template holding the user-space results Deny, which names its tag key
    through a template variable and is rendered to ``username`` before the matcher reads it.
  PERSONAL_RESULTS_DENY: The user-space results Deny as a predicate over keys.
  SHARED_RESULTS_DENY: The shared-space results Deny as a predicate over keys.
  RESULTS_KEY_SUFFIXES: The results-folder keys under test, as suffixes of a space root.
  RESULTS_BUCKETS: Each space kind with its root and its results Deny.
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
    ROOT / "infra" / "modules" / "shared-space-storage" / "policies" / "portal-role-shared-space.json.tftpl"
)
ANALYTICS_TEMPLATE = (
    ROOT / "infra" / "modules" / "analytics" / "policies" / "portal-role-analytics.json.tftpl"
)


def _deny_resource_of(body: str, sid: str) -> str:
    """The Resource string of the named Deny, as the template spells it.

    Sliced out by Sid rather than parsed: the shared template renders to JSON and is not JSON. The
    slice runs to the NEXT ``"Sid"``, and what makes that safe is that every statement carries one
    — so it is the ``"Effect"`` COUNT that is checked, not the slice's length. A length check
    cannot fire: both ``…SystemSettings`` lookups are the last statement in their document and run
    to EOF in normal operation, which is exactly the case a length check was supposed to catch
    (measured — removing it left every suite green). A statement with no Sid of its own, between
    this one and the next, is the real way the slice grows, and it brings a second ``"Effect"``
    with it.

    The Effect is checked here rather than left to the policy suites because it is a precondition
    of this matcher's MEANING, not a restatement of a policy rule: a key matcher built from an
    Allow's Resource would compare the predicates against a permission.

    Args:
      body: The template's text.
      sid: The statement id to read.

    Returns:
      The statement's Resource, with its template placeholders intact.

    Raises:
      AssertionError: If the Sid is absent, if the slice covers more than one statement, if the
        statement is not a Deny, or if it carries no single-string Resource.
    """
    start = body.find(f'"Sid": "{sid}"')
    assert start > -1, f"no {sid} statement — this matcher would otherwise be built from nothing"
    end = body.find('"Sid"', start + 1)
    statement = body[start:] if end == -1 else body[start:end]
    assert statement.count('"Effect"') == 1, (
        f"the {sid} slice covers more than one statement, so the Resource read below may belong to "
        "a neighbour — a statement carrying no Sid of its own is what makes the slice run on"
    )
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
    assert "?" not in key_part, (
        f"{resource!r} uses IAM's OTHER wildcard, which this matcher does not model: `?` matches "
        "any single character in a Resource ARN, and escaping it to a literal would make the "
        "matcher cover fewer keys than the Deny does"
    )
    pattern = "[\\s\\S]*".join(re.escape(part) for part in key_part.split("*"))
    return lambda key: re.fullmatch(pattern, key) is not None


def _archive_deny_sids(body: str) -> set[str]:
    """Every Sid in a template whose RESOURCE denies something under an ``archive`` folder.

    The union below NAMES its Sids rather than deriving them, which is what keeps a deleted
    statement loud — a derived list would shrink along with the thing it derives from and go on
    passing. This is the other half of that trade: a THIRD archive Deny added to either template
    would be unioned by nothing, and the matcher would keep agreeing with the two it knows about
    while the predicates were held to less than the policy says.

    Two readings are deliberately narrow. It is the Resource that names the folder, so a
    ``/archive/`` appearing in an ``s3:prefix`` Condition is not one of these — reading the whole
    statement made an ordinary ``ListBucket`` Deny report as an archive one, and the advice this
    test then gives ("union it above") would build a matcher from a bare bucket ARN. And ``archive``
    is read as a whole path SEGMENT rather than as the literal ``/archive/``, because that is only
    the spelling used today: ``/archive*`` and a bare ``/archive`` name the same folder, and a Deny
    spelled either way covers keys the table asserts are permitted while every row stays green.
    ``/archived-notes/*`` names a different folder and is not matched.

    Reach: statements whose ``"Sid"`` is their FIRST key, which is how every Sid-slicing reader in
    this repo finds them. One written with ``"Sid"`` last is invisible to this AND to the matchers
    above — measured, an any-depth archive Deny written that way leaves every row green — so that
    shape has to be refused where statements are counted, which is not this file.

    Args:
      body: The template's text.

    Returns:
      The Sids of its archive Denies.

    Raises:
      None.
    """
    found = set()
    for match in re.finditer(r'"Sid":\s*"([^"]+)"', body):
        end = body.find('"Sid"', match.end())
        statement = body[match.start() :] if end == -1 else body[match.start() : end]
        if not re.search(r'"Effect":\s*"Deny"', statement):
            continue
        resource = re.search(r'"Resource":\s*(\[[^\]]*\]|"[^"]*")', statement)
        named = re.findall(r'"([^"]*)"', resource.group(1)) if resource else []
        if any(re.search(r"/archive([/*]|$)", one) for one in named):
            found.add(match.group(1))
    return found


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

# One Sid per bucket again. The narrowing deleted the depth-one statement of each pair, and the
# survivor keeps its `…SystemSettings` name — so `_any_of` now wraps one matcher rather than two.
# It is kept rather than inlined because what it expresses is "every Deny that names this folder",
# and a second statement returning would otherwise be silently unmeasured.
PERSONAL_DENY = _any_of(
    _key_matcher(
        _deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritableSystemSettings"),
        "alice",
    ),
)
SHARED_DENY = _any_of(
    _key_matcher(
        _deny_resource_of(_SHARED_BODY, "SharedArchiveReceiptsAreNotUserWritableSystemSettings"),
        "finance",
    ),
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

_ANALYTICS_BODY = ANALYTICS_TEMPLATE.read_text()

PERSONAL_RESULTS_DENY = _key_matcher(
    _deny_resource_of(_ANALYTICS_BODY, "ResultsNoDeleteSystemSettings").replace(
        "${principal_tag_key}", "username"
    ),
    "alice",
)
SHARED_RESULTS_DENY = _key_matcher(
    _deny_resource_of(_SHARED_BODY, "SharedResultsNoDeleteSystemSettings"),
    "finance",
)

RESULTS_KEY_SUFFIXES = (
    "whatever.csv",
    "athenaresults/whatever.csv",
    "system_settings/whatever.csv",
    "system_settings/athenaresults/q-1.csv",
    "system_settings/athenaresults/x/",
    "system_settings/athenaresults",
    "system_settings/athenaresults-old/q.csv",
    "system_settings/x/athenaresults/q.csv",
    "backups/system_settings/athenaresults/q.csv",
    "backups/system_settings/athenaresults",
)

RESULTS_BUCKETS = (
    pytest.param("alice/", "personal", PERSONAL_RESULTS_DENY, id="personal"),
    pytest.param("finance/", "shared", SHARED_RESULTS_DENY, id="shared"),
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
    """``focommon.protected._is_at_or_below`` agrees with the PORTAL role's Deny, for the archive name.

    Called with ``ARCHIVE_FOLDER`` only. The same function serves ``athenaresults`` and
    ``user_settings``, whose rules this Deny does not describe, and constraining those here would
    pin the general predicate to a policy that says nothing about them.

    The role matters as much as the folder: this plane executes under its own role, whose personal
    Deny is any-depth, and this predicate deliberately does not mirror that one — see the module
    docstring.
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


def test_the_union_names_every_archive_deny_in_each_template():
    """A third archive Deny would be covered by neither predicate test, silently.

    The union is hard-coded on purpose — deriving it would make deleting a statement invisible —
    so this is what stops the enumeration falling behind the templates. If it fails because a
    legitimate new Deny landed, the fix is to union it above, not to widen the sets here.
    """
    assert _archive_deny_sids(_PERSONAL_BODY) == {
        "ArchiveReceiptsAreNotUserWritableSystemSettings",
    }
    assert _archive_deny_sids(_SHARED_BODY) == {
        "SharedArchiveReceiptsAreNotUserWritableSystemSettings",
    }


def test_the_table_can_tell_an_ANCHORED_personal_deny_from_a_widened_one():
    """The key table's adequacy, derived rather than counted.

    A row deleted from ``KEY_SUFFIXES`` takes a whole mutation class's only detector with it, and
    the loss is invisible twice over: the row names come from ``parametrize``, so no source grep
    sees the table shrink, and every agreement row that remains still passes. Measured — widening
    the personal ``…SystemSettings`` anchor reddens two rows while
    ``backups/system_settings/archive/…`` is in the table, and nothing at all once it is removed.

    So what is asserted is the PROPERTY rather than the membership: each personal Deny is compared
    against a copy of itself with the principal tag replaced by ``*`` — the widening that turns
    "the caller's own archive" into "any user's" while the document still parses and still ends
    ``/archive/*`` — and the table must hold a key that tells the two apart. A row count would pin
    the table's size and say nothing about what it can see.
    """
    for sid in ("ArchiveReceiptsAreNotUserWritableSystemSettings",):
        resource = _deny_resource_of(_PERSONAL_BODY, sid)
        widened_resource = resource.replace("$${aws:PrincipalTag/username}", "*")
        assert widened_resource != resource, f"{sid} is not anchored at the principal tag any more"

        anchored = _key_matcher(resource, "alice")
        widened = _key_matcher(widened_resource, "alice")

        assert any(anchored(f"alice/{s}") != widened(f"alice/{s}") for s in KEY_SUFFIXES), (
            f"no key in the table distinguishes {sid} from an unanchored copy of itself, so the "
            "widening that denies every user's archive would pass every row above"
        )


def test_the_table_can_tell_the_SHARED_wildcard_from_a_space_anchored_one():
    """The same property from the other side, where there is no anchor left to widen.

    The shared Denies already put ``*`` where the space name goes, so the change that would go
    unnoticed is the reverse: narrowing that slot to one literal space still refuses every
    ``finance/`` key the table asks about, while quietly ceasing to cover any other space.
    """
    for sid in ("SharedArchiveReceiptsAreNotUserWritableSystemSettings",):
        resource = _deny_resource_of(_SHARED_BODY, sid)
        narrowed_resource = resource.replace("}/*/", "}/finance/", 1)
        assert narrowed_resource != resource, f"{sid} has no wildcard space slot to narrow"

        wildcarded = _key_matcher(resource, "finance")
        narrowed = _key_matcher(narrowed_resource, "finance")

        assert any(wildcarded(f"finance/{s}") != narrowed(f"finance/{s}") for s in KEY_SUFFIXES), (
            f"no key in the table distinguishes {sid} from a space-anchored copy of itself"
        )


def test_the_two_denies_really_do_differ_so_the_asymmetry_is_not_an_artefact():
    """One key, two answers. If this fails, a policy changed shape and the predicates should
    follow it rather than the table being edited to agree with a rule nobody re-read.

    Asserted twice, and the second is the one that keeps the TABLE honest. The canonical example
    is spelled out because it is what a reader needs to see; the sweep over ``KEY_SUFFIXES`` is
    what fails if the rows carrying the asymmetry are ever removed, since a table on which the two
    buckets never disagree would let a predicate that averaged them pass every row above while
    this test still passed on its own hard-coded pair.
    """
    assert PERSONAL_DENY("alice/backups/system_settings/archive/x.csv") is False
    assert SHARED_DENY("finance/backups/system_settings/archive/x.csv") is True

    assert any(PERSONAL_DENY(f"alice/{s}") != SHARED_DENY(f"finance/{s}") for s in KEY_SUFFIXES), (
        "no key in the table is answered differently by the two buckets, so the asymmetry this "
        "whole file exists to hold is exercised by nothing in the rows above"
    )


def test_the_wildcard_matches_a_slash_which_is_the_trap_in_reading_these_resources():
    """``*`` in an S3 resource ARN is not a shell glob.

    A matcher that stopped at ``/`` would make every shared row above agree with a root-anchored
    predicate, and both tests would pass while the planes permitted writes IAM refuses.
    """
    assert SHARED_DENY("finance/a/b/c/system_settings/archive/x.csv") is True


def test_the_surviving_deny_covers_the_home_and_NOT_the_one_it_left():
    """What the narrowing did, read off the rendered policy rather than off the diff.

    This replaces the pair that discriminated the two halves of the old union. There is one half
    now, so the question it answers changes: not "which of the two carries the new home", but
    "does the survivor still refuse where the receipts are, and stop refusing where they no longer
    are". The second clause is the whole narrowing — if it is False, the depth-one statement is
    somehow still rendering and a user's own ``archive/`` folder is unwritable.
    """
    personal = _key_matcher(
        _deny_resource_of(_PERSONAL_BODY, "ArchiveReceiptsAreNotUserWritableSystemSettings"),
        "alice",
    )
    shared = _key_matcher(
        _deny_resource_of(_SHARED_BODY, "SharedArchiveReceiptsAreNotUserWritableSystemSettings"),
        "finance",
    )

    assert personal("alice/system_settings/archive/x.csv") is True
    assert personal("alice/archive/x.csv") is False

    assert shared("finance/system_settings/archive/x.csv") is True
    assert shared("finance/archive/x.csv") is False


@pytest.mark.parametrize("root, kind, deny", RESULTS_BUCKETS)
@pytest.mark.parametrize("suffix", RESULTS_KEY_SUFFIXES)
def test_the_api_results_refusal_answers_where_the_delete_deny_reaches(suffix, root, kind, deny):
    """``apicommon.protected.is_in_results_folder`` agrees with the results Deny, key by key.

    A False where the Deny says True lets a caller make an object nobody can delete; a True where
    it says False is a 403 for a write the user could have undone.

    Args:
      suffix: The key below the space root.
      root: The space root.
      kind: The space kind.
      deny: The bucket's results Deny as a predicate.

    Returns:
      None.

    Raises:
      AssertionError: If the predicate and the Deny disagree on the key.
    """
    space = spaces.ResolvedSpace(kind, root.rstrip("/"), f"{kind}-bucket", root)
    key = f"{root}{suffix}"

    assert api_protected.is_in_results_folder(space, key) is deny(key)


@pytest.mark.parametrize("root, kind, deny", RESULTS_BUCKETS)
def test_the_results_table_exercises_both_answers(root, kind, deny):
    """The positive control for the results rows, as ``test_the_key_table_exercises_both_answers``
    is for the archive rows.

    Args:
      root: The space root.
      kind: The space kind.
      deny: The bucket's results Deny as a predicate.

    Returns:
      None.

    Raises:
      AssertionError: If every results row is denied, or none is.
    """
    assert {deny(f"{root}{suffix}") for suffix in RESULTS_KEY_SUFFIXES} == {True, False}


def test_the_two_results_denies_differ_on_the_table_so_its_asymmetry_is_exercised():
    """The results Denies have the receipt folder's shape, and the table must hold a key on which
    the two buckets disagree, or a predicate that averaged them would pass every row.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no results row is answered differently by the two buckets.
    """
    assert PERSONAL_RESULTS_DENY("alice/backups/system_settings/athenaresults/q.csv") is False
    assert SHARED_RESULTS_DENY("finance/backups/system_settings/athenaresults/q.csv") is True
    assert any(
        PERSONAL_RESULTS_DENY(f"alice/{s}") != SHARED_RESULTS_DENY(f"finance/{s}")
        for s in RESULTS_KEY_SUFFIXES
    )
