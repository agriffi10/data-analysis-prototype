"""The file-operations plane's any-depth rules, held against the execution role that does the work.

The plane writes and deletes under its own role, and that role's two Denies — on ``s3:PutObject``
and on ``s3:DeleteObject`` — name the portal's folders with a wildcard where the space name goes.
The role carries no principal tag, so nothing anchors them at a space root, and a wildcard matches
``/``: each reaches its folder at any depth, in both space buckets. A rule on this plane that is
looser than that accepts a request the role then refuses part way through a run, which is how a
copy into a folder a user had made and called ``user_settings`` used to fail. A rule that is
stricter refuses what the role permits, which is how a user literally named ``user_settings`` used
to be unable to delete anything through this plane.

So ``focommon.protected.role_denied_folder`` — the one reading of those Denies, which the
destination rules, the manifest builder's write check and ``focommon.delete`` all go through — is
run over a key table against matchers built from the template itself, as
``test_archive_write_lock_mirrors_iam.py`` does for the PORTAL role's receipt Deny, and with its
key matcher rather than a second copy of one. The two files hold different roles and must not be
merged: the portal role's Deny is anchored at the principal tag in a personal space, and this one
is not anchored anywhere.

**Parsed as JSON, unlike its sibling.** This template carries no ``%{ … }`` directive, so the
document is JSON with ``${…}`` placeholders inside its strings, and reading it that way makes the
statement boundaries exact rather than sliced. A directive added later fails the parse loudly.

Attributes:
  ROOT: The repository root.
  EXECUTION_TEMPLATE: The file-operations execution role's policy template.
  WRITE_SID: The statement whose Resources this plane's write rules mirror.
  DELETE_SID: The statement whose Resources its delete rule mirrors.
  BUCKET_PLACEHOLDERS: Each space kind with the template variable naming its bucket.
  ROOTS: The space roots the table runs under. Two are ordinary names, and two are usernames the
    sign-up pattern admits that coincide with a portal folder — the only keys on which a scan that
    counts a key's first segment differs from the Deny.
  KEY_SUFFIXES: The keys under test, as suffixes of a root: each folder at the root, nested, and
    deep, as a folder and as a file named like it; a sibling name; the depth-one names the moving
    folders left; a split pair; an empty segment; and the marker.
"""

import fnmatch
import json
import pathlib
import re

import pytest
import test_archive_write_lock_mirrors_iam as portal_role_guard
from cpcommon.app_managed import app_managed_segments, segments_hold_app_managed
from cpcommon.errors import TerminalError
from focommon import delete
from focommon.config import ANY_DEPTH_DENIED_FOLDERS
from focommon.protected import destination_refusal, role_denied_folder

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXECUTION_TEMPLATE = ROOT / "infra" / "planes" / "file-ops" / "execution.json.tftpl"

WRITE_SID = "NeverOverwritePortalManagedObjects"
DELETE_SID = "NeverDeletePortalManagedObjects"

BUCKET_PLACEHOLDERS = {"personal": "${user_space_bucket_arn}", "shared": "${shared_space_bucket_arn}"}

ROOTS = ("alice/", "finance/", "user_settings/", "system_settings/")

KEY_SUFFIXES = (
    "x.csv",
    "x/",
    "user_settings/",
    "user_settings/notifications.json",
    "user_settings",
    "foo/user_settings/",
    "foo/user_settings/a.csv",
    "a/b/user_settings/c/d.csv",
    "foo/user_settings",
    "user_settings2/a.csv",
    "foo/my_user_settings/a.csv",
    "system_settings/athenaresults/q.csv",
    "foo/system_settings/athenaresults/",
    "foo/system_settings/athenaresults/q/r.csv",
    "foo/system_settings/athenaresults",
    "athenaresults/q.csv",
    "foo/athenaresults/q.csv",
    "system_settings/x/athenaresults/q.csv",
    "system_settings/archive/r.json",
    "backups/system_settings/archive/",
    "backups/system_settings/archive/r.json",
    "archive/r.json",
    "backups/archive/r.json",
    "system_settings/archive",
    "foo//user_settings/a.csv",
    "athenaresults/x.csv",
    "archive/x.csv",
    "DO_NOT_DELETE.txt",
    "foo/DO_NOT_DELETE.txt",
)


def _statements() -> list:
    """Every statement of the execution role's policy, read from the template as JSON.

    Returns:
      The statements, in document order.

    Raises:
      AssertionError: If the document has no statement list.
    """
    document = json.loads(EXECUTION_TEMPLATE.read_text())
    statements = document.get("Statement")
    assert isinstance(statements, list) and statements, "the execution role has no statements"
    return statements


def _as_list(value: object) -> list:
    """A policy field that may be one string or a list of them, as a list.

    Args:
      value: The field's value.

    Returns:
      The values, or an empty list when the field is absent.

    Raises:
      None.
    """
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _statement(sid: str) -> dict:
    """The one statement carrying a Sid, confirmed to be a Deny this matcher can read in full.

    A Condition, a ``NotAction`` or a ``NotResource`` would each change what the Resources mean,
    and none of them is modelled here, so each is refused rather than silently ignored.

    Args:
      sid: The statement id.

    Returns:
      The statement.

    Raises:
      AssertionError: If the Sid is absent or repeated, or the statement is not a plain Deny.
    """
    found = [s for s in _statements() if s.get("Sid") == sid]
    assert len(found) == 1, f"expected one {sid} statement, found {len(found)}"
    statement = found[0]
    assert statement.get("Effect") == "Deny", f"{sid} is not a Deny, so its Resources are a grant"
    unmodelled = {"Condition", "NotAction", "NotResource"} & statement.keys()
    assert not unmodelled, f"{sid} carries {sorted(unmodelled)}, which this matcher does not model"
    return statement


def _deny(sid: str, kind: str):
    """One bucket's half of a Deny, as a predicate over object keys.

    Each Resource naming that bucket becomes a matcher through the sibling guard's
    ``_key_matcher``, with ``*`` matching any character including ``/``; the rest are dropped.

    Args:
      sid: The statement id.
      kind: ``personal`` or ``shared``, which selects the bucket.

    Returns:
      A predicate true where any of that bucket's Resources covers a key.

    Raises:
      AssertionError: If the statement names that bucket in no Resource.
    """
    placeholder = BUCKET_PLACEHOLDERS[kind]
    resources = [r for r in _as_list(_statement(sid).get("Resource")) if r.startswith(f"{placeholder}/")]
    assert resources, f"{sid} names no {kind} bucket Resource — the matcher would deny nothing"
    matchers = [portal_role_guard._key_matcher(resource, "unused") for resource in resources]
    return lambda key: any(matches(key) for matches in matchers)


def _anchored_write_deny(kind: str):
    """A copy of one bucket's write Deny with its space slot anchored to ONE path segment.

    The shape a predicate takes when it mirrors the picker rather than the role, built from the
    Resources rather than written by hand, so the table's adequacy is measured against the
    statement it is meant to tell apart.

    Args:
      kind: ``personal`` or ``shared``.

    Returns:
      A predicate over keys.

    Raises:
      None.
    """
    placeholder = BUCKET_PLACEHOLDERS[kind]
    patterns = []
    for resource in _as_list(_statement(WRITE_SID).get("Resource")):
        if not resource.startswith(f"{placeholder}/*/"):
            continue
        head, *rest = resource[len(placeholder) + 1 :].split("*")
        pattern = re.escape(head) + "[^/]+" + "[\\s\\S]*".join(re.escape(part) for part in rest)
        patterns.append(pattern)
    return lambda key: any(re.fullmatch(pattern, key) for pattern in patterns)


WRITE_DENY = {kind: _deny(WRITE_SID, kind) for kind in BUCKET_PLACEHOLDERS}
DELETE_DENY = {kind: _deny(DELETE_SID, kind) for kind in BUCKET_PLACEHOLDERS}

ROWS = [
    pytest.param(kind, f"{root}{suffix}", id=f"{kind}:{root}{suffix}")
    for kind in BUCKET_PLACEHOLDERS
    for root in ROOTS
    for suffix in KEY_SUFFIXES
]


def _deletable(key: str) -> bool:
    """Whether ``focommon.delete`` lets one key through, with its root as the allowed prefix.

    Args:
      key: The key under test.

    Returns:
      False when the check refuses the key as something the role denies, True when it passes.

    Raises:
      AssertionError: If the check refuses for any other reason, which this table cannot compare.
    """
    try:
        delete.assert_item_deletable([key], key.split("/", 1)[0] + "/")
    except TerminalError as err:
        assert err.reason in {"marker_not_deletable", delete.DELETE_REFUSED}, err
        return False
    return True


@pytest.mark.parametrize(("kind", "key"), ROWS)
def test_the_write_predicate_answers_what_the_role_s_write_deny_says(kind, key):
    """A False where the Deny says True is a copy that fails at the write; a True where it says
    False is a refusal of a write the role permits.
    """
    assert (role_denied_folder(key) is not None) is WRITE_DENY[kind](key)


@pytest.mark.parametrize(("kind", "key"), ROWS)
def test_the_delete_check_answers_what_the_role_s_delete_deny_says(kind, key):
    """``focommon.delete`` refuses exactly what the role's delete Deny covers — its folders through
    the shared predicate, and the marker by basename, which is the one Resource the write Deny lacks.
    """
    assert _deletable(key) is not DELETE_DENY[kind](key)


@pytest.mark.parametrize(("kind", "key"), [row for row in ROWS if row.values[1].endswith("/")])
def test_a_destination_prefix_is_refused_wherever_the_role_denies_a_write_beneath_it(kind, key):
    """The prefix rule's WIRING, not just its predicate: every folder the role denies writing into
    is refused as a destination, and the any-depth arm refuses nothing the role permits.

    The picker-locked arm is allowed to refuse more — ``shared_tables/`` and the rest are locked by
    choice, not by the role — so only the any-depth arm's own reason is held in that direction.
    """
    root = key.split("/", 1)[0] + "/"
    refusal = destination_refusal(root, key)
    denied_beneath = WRITE_DENY[kind](f"{key}file.csv")

    if denied_beneath:
        assert refusal is not None
    if refusal is not None and refusal.reason == "destination_folder_reserved":
        assert denied_beneath


@pytest.mark.parametrize("kind", list(BUCKET_PLACEHOLDERS))
def test_the_table_exercises_both_answers_and_the_two_shapes_a_wrong_scan_takes(kind):
    """The table's adequacy, as properties rather than a row count.

    Both answers per Deny, so an always-True or always-False predicate cannot agree with a broken
    matcher. A key a ROOT-ANCHORED copy of the write Deny answers differently, so a predicate that
    stopped reaching nested folders reddens. And a key on which a scan COUNTING THE FIRST SEGMENT
    answers differently, which only the root-literal usernames supply — without them, reverting the
    predicate to that scan passes every row.
    """
    keys = [row.values[1] for row in ROWS if row.values[0] == kind]
    write, delete_deny, anchored = WRITE_DENY[kind], DELETE_DENY[kind], _anchored_write_deny(kind)

    def counts_first_segment(key: str) -> bool:
        return any(
            segments_hold_app_managed(key.split("/")[:-1], folder) for folder in ANY_DEPTH_DENIED_FOLDERS
        )

    assert {write(key) for key in keys} == {True, False}
    assert {delete_deny(key) for key in keys} == {True, False}
    assert any(write(key) != anchored(key) for key in keys)
    assert any(write(key) != counts_first_segment(key) for key in keys)


def test_every_space_bucket_deny_on_writes_or_deletes_is_one_this_file_reads():
    """The Sids are NAMED, which keeps a deleted statement loud; this is the other half of that
    trade. A second Deny on a space bucket's writes or deletes would be unioned by nothing, and the
    rules would go on agreeing with the one statement read here while the role refused more.

    An action is matched as IAM matches it — the policy's action as the PATTERN, case-insensitively
    — so ``s3:*`` and ``s3:Put*`` count.
    """
    def covering(action: str) -> set:
        found = set()
        for statement in _statements():
            if statement.get("Effect") != "Deny":
                continue
            resources = _as_list(statement.get("Resource")) + _as_list(statement.get("NotResource"))
            if not any(r.startswith(tuple(f"{p}/" for p in BUCKET_PLACEHOLDERS.values())) for r in resources):
                continue
            patterns = [a.lower() for a in _as_list(statement.get("Action"))]
            if statement.get("NotAction") is not None or any(
                fnmatch.fnmatchcase(action.lower(), pattern) for pattern in patterns
            ):
                found.add(statement.get("Sid"))
        return found

    assert covering("s3:PutObject") == {WRITE_SID}
    assert covering("s3:DeleteObject") == {DELETE_SID}


def test_the_denies_name_exactly_the_folders_the_predicate_reads():
    """The table can only see folders it has rows for, so a Resource added for a NEW folder — say
    ``*/saved_queries/*`` — leaves every row above green while the role refuses more than the plane.

    So the folders are read off the Resources and compared to what ``ANY_DEPTH_DENIED_FOLDERS``
    spells: each any-depth Resource must be ``{bucket}/*/<folder>/*`` for one of them, the delete
    Deny adds only the marker, and the only other shape is the user-space bucket's root
    ``_config/*`` and ``_directory/*``, which containment keeps out of every space.
    """
    expected = {"/".join(app_managed_segments(folder)) for folder in ANY_DEPTH_DENIED_FOLDERS}
    root_documents = {"_config/*", "_directory/*"}

    for sid, extra in ((WRITE_SID, set()), (DELETE_SID, {"DO_NOT_DELETE.txt"})):
        for kind, placeholder in BUCKET_PLACEHOLDERS.items():
            named, at_root = set(), set()
            for resource in _as_list(_statement(sid).get("Resource")):
                if not resource.startswith(f"{placeholder}/"):
                    continue
                rest = resource[len(placeholder) + 1 :]
                if rest.startswith("*/"):
                    named.add(rest[2:].removesuffix("/*"))
                else:
                    at_root.add(rest)

            assert named == expected | extra, (sid, kind, named)
            assert at_root == (root_documents if kind == "personal" else set()), (sid, kind, at_root)
