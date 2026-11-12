"""The catalog routes need no new IAM, and this is the half of that claim a byte pin cannot make.

The assumed portal role already holds every permission the six Athena and Glue calls need — it is
the same role, doing the same work, reached from a different place. So this spec adds no statement
to any portal-role policy, and two different guards say so:

- ``test_portal_role_preservation`` pins every permission template byte-for-byte against a
  baseline commit. That catches a tidy, a reorder and a deletion.
- **This file catches a WIDENING that a re-baselined pin would absorb.** If somebody moves the
  baseline forward — which that test's own docstring tells them to do when a change is
  deliberate — the byte pin agrees with whatever it is moved to. An assertion about the actions
  and resources actually named survives that, because it is about the content rather than about
  the bytes.

**Not a golden-file snapshot, deliberately.** A test that writes the rendered templates during the
build and diffs them against themselves compares a copy of the answer with itself and passes
whatever happens — the technique this repo already corrected once.

Attributes:
  BASE_REF: What the branch is measured against. The merge base with the default branch, so the
    comparison is "what this branch added", not "what has changed since some fixed date". On
    ``main`` after a merge the base IS the head, so these assertions are tautologies there — they
    are a branch guard, and a green ``main`` is not evidence from them.
  POLICY_PATTERN: Which templates this covers. Every portal-role permission template, found by
    pattern rather than named, so a new one joins by existing.
  CATALOG_PREFIXES: The action families this spec would have had to widen if it needed anything.
    Used only to confirm the baseline has a subject; the comparison itself reads every action.
  SYSTEM_SETTINGS: The prefix the three app-managed folders are being admitted under ahead of the
    move. The ONE admitted widening, and admitted by shape against the base rather than by naming
    files — ``_is_admitted_twin``.
  MOVING_FOLDERS: The three folders that get a second home, read from the module that OWNS those
    names rather than spelled again here — a folder list written twice is a rule that can be wrong
    in one copy.
  ADMITTED_ACTIONS: The catalog actions a template may gain on purpose, by template, each argued
    where it is admitted. One so far: ``athena:GetQueryRuntimeStatistics`` on the analytics
    template, which the row-count route calls as the caller. The status bar used to count a
    result by fetching every page of it, each page a billed API call, and Athena's runtime
    statistics hold the same count in one call that scans nothing. It is workgroup-scoped like
    every other Athena action in that statement, so it reaches no execution the role could not
    already read. Once the change adding it merges, the base holds the action and this entry
    admits nothing; it stays as the record of the decision rather than being deleted.
  MOVED_FROM: Templates that moved module, mapped to where the base may still hold them. A moved
    template read at its new path alone would find nothing at the base and report every line as
    gained; read at the old path it is compared with itself, as a move should be. The base copy at
    the NEW path wins whenever it exists, so once the move merges the entry is inert.
"""

import pathlib
import re
import shutil
import subprocess
import tempfile

from cpcommon.app_managed import (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    SHARED_TABLES_FOLDER,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
BASE_REF = "origin/main"
POLICY_PATTERN = re.compile(r"infra/modules/[^/]+/policies/portal-role-.*\.json\.tftpl")
CATALOG_PREFIXES = ("athena:", "glue:", "lakeformation:")
SYSTEM_SETTINGS = "system_settings"
MOVING_FOLDERS = frozenset({ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER})
ADMITTED_ACTIONS: dict[str, frozenset[str]] = {
    "infra/modules/analytics/policies/portal-role-analytics.json.tftpl": frozenset(
        {"athena:GetQueryRuntimeStatistics"}
    ),
}

MOVED_FROM: dict[str, str] = {
    "infra/modules/shared-space-storage/policies/portal-role-shared-space.json.tftpl": (
        "infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl"
    ),
}

_ACTION_BLOCK_RE = re.compile(r'"Action"\s*:\s*(\[[^\]]*\]|"[^"]*")', re.DOTALL)
_RESOURCE_BLOCK_RE = re.compile(r'"Resource"\s*:\s*(\[[^\]]*\]|"[^"]*")', re.DOTALL)


def _git(*args: str, root: pathlib.Path | None = None) -> str:
    """Runs one git command in the repository.

    Args:
      *args: The command's arguments.
      root: The repository to run in, for the fixture that proves the enumeration below reads
        paths raw. Defaults to this checkout.

    Returns:
      Its standard output.

    Raises:
      AssertionError: If git fails, which is a broken checkout rather than a finding.
    """
    git = shutil.which("git") or "git"
    finished = subprocess.run(  # noqa: S603
        [git, *args], cwd=root or REPO, capture_output=True, text=True, check=False
    )
    assert finished.returncode == 0, f"git {' '.join(args)} failed: {finished.stderr}"
    return finished.stdout


def _templates(root: pathlib.Path | None = None) -> list[str]:
    """Every portal-role permission template in the working tree.

    ``-z`` rather than plain ``ls-files``: git C-QUOTES a path that is not plain ASCII, wrapping
    it in double quotes and escaping the bytes, and a quoted path fails the pattern below. The
    template would then drop out of the population this guard protects, silently and in the
    direction that reads as clean.

    Args:
      root: The repository to enumerate, for the fixture that proves the above. Defaults to this
        checkout.

    Returns:
      Repo-relative paths.

    Raises:
      AssertionError: If git fails.
    """
    listed = _git("ls-files", "-z", "infra/modules", root=root)
    return sorted(
        path for path in listed.split("\0") if POLICY_PATTERN.fullmatch(path)
    )


def _at_base(path: str) -> str:
    """One template's contents at the branch's base, followed across a move.

    Args:
      path: The repo-relative path.

    Returns:
      The file's contents at the base — at ``path``, or failing that at the path ``MOVED_FROM``
      says it moved from — or the empty string if it existed at neither.

    Raises:
      None.
    """
    git = shutil.which("git") or "git"
    for candidate in (path, MOVED_FROM.get(path)):
        if candidate is None:
            continue
        finished = subprocess.run(  # noqa: S603
            [git, "show", f"{_merge_base()}:{candidate}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if finished.returncode == 0:
            return finished.stdout
    return ""


def _merge_base() -> str:
    """Where this branch left the default branch.

    Args:
      None.

    Returns:
      The merge-base commit.

    Raises:
      AssertionError: If git fails.
    """
    return _git("merge-base", "HEAD", BASE_REF).strip()


def _actions(source: str) -> set[str]:
    """Every action a template names, catalog-family or not.

    **Every action, not only the three prefixes this spec would have widened.** A first version
    matched ``athena:``/``glue:``/``lakeformation:`` alone, which made a bare ``"Action": "*"``
    invisible — the largest widening there is, and precisely the kind a re-baselined byte pin
    absorbs, which is this file's whole reason to exist.

    Args:
      source: The template's contents.

    Returns:
      The action strings.

    Raises:
      None.
    """
    found: set[str] = set()
    for block in _ACTION_BLOCK_RE.findall(source):
        found.update(re.findall(r'"([^"]*)"', block))
    return found


def _resources(source: str) -> set[str]:
    """Every resource string a template names.

    Args:
      source: The template's contents.

    Returns:
      The resource strings, whitespace-normalised so a reformat is not a finding.

    Raises:
      None.
    """
    found: set[str] = set()
    for block in _RESOURCE_BLOCK_RE.findall(source):
        found.update(re.findall(r'"([^"]*)"', block))
    return found


def _is_admitted_twin(resource: str, base: set[str]) -> bool:
    """Reports whether a gained resource is the ``system_settings/`` twin of one held at the base.

    Three app-managed folders are being admitted at a second, equally protected location under
    ``system_settings/`` before they move there, so every statement naming one gains a sibling
    naming the same folder one segment deeper. Those siblings ARE new resources and this guard is
    right to see them; what makes them acceptable is that each one names the SAME FOLDER, at the
    same anchor, as a resource the base already named.

    **Admitted by shape, derived from the BASE.** Removing the one ``system_settings/`` segment
    must land on a string the base actually held — so a sibling hung under the wrong anchor is
    still a widening. An exemption written as a list of file names would instead have vouched for
    whatever those files did next.

    **And restricted to the three folders that are actually moving.** Without that clause the
    exemption admitted a second home for any path the base mentioned in any statement at all:
    ``…/system_settings/user_settings/*`` reduces to ``…/user_settings/*``, which the base names in
    a DENY, so an ``Allow`` at the new location was admitted as a twin of a refusal. That folder is
    not moving and the spec puts a second home for it out of scope; found by review, planted, and
    confirmed to pass every guard on this branch before this clause existed.

    What this deliberately does NOT check is the Effect — a resource set carries no Effects. The
    statement's Effect and actions are checked where statements are read whole, by the Sid-keyed
    content tests in ``test_portal_role_preservation``, which is also why a statement without a Sid
    is refused there.

    The second home is temporary: once the folders move, the OLD halves come off, which this guard
    does not see because a removal is not a gain.

    Args:
      resource: A resource string present now and absent at the base.
      base: Every resource the same template named at the base.

    Returns:
      True when the resource is an admitted twin.

    Raises:
      None.
    """
    marker = f"/{SYSTEM_SETTINGS}/"
    if marker not in resource:
        return False
    folder = resource.split(marker, 1)[1].split("/")[0]
    if folder not in MOVING_FOLDERS:
        return False
    return resource.replace(marker, "/", 1) in base


def test_the_twin_exemption_admits_ONLY_a_twin_of_something_already_held() -> None:
    """The exemption's own guard: it must not be a hole a real widening can walk through.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the exemption admits a resource with no counterpart at the base, or
        refuses a genuine twin.
    """
    # The base deliberately mirrors the REAL one: the templates on this branch name user_settings
    # and the bare user prefix beside the moving folders, and a fixture that omitted them would
    # make every negative below pass for want of a counterpart rather than on the rule.
    base = {
        "arn:aws:s3:::bucket/*/archive/*",
        "arn:aws:s3:::bucket/*/user_settings/*",
        "arn:aws:s3:::bucket/*/DO_NOT_DELETE.txt",
        "arn:aws:s3:::bucket/*/*",
    }

    assert _is_admitted_twin("arn:aws:s3:::bucket/*/system_settings/archive/*", base)
    assert not _is_admitted_twin("arn:aws:s3:::bucket/*/archive/*", base), "a non-twin is not exempt"
    assert not _is_admitted_twin("arn:aws:s3:::other/*/system_settings/archive/*", base), "another bucket"
    assert not _is_admitted_twin("arn:aws:s3:::bucket/alice/system_settings/archive/*", base), "another anchor"
    assert not _is_admitted_twin("arn:aws:s3:::bucket/*/system_settings/saved_queries/*", base), (
        "a folder the base never protected"
    )
    assert not _is_admitted_twin("arn:aws:s3:::bucket/*/system_settings/user_settings/*", base), (
        "user_settings is NOT moving, so a second home for it is out of scope however the base "
        "happens to name it — this is the case that passed before the moving-folder clause"
    )
    assert not _is_admitted_twin("arn:aws:s3:::bucket/*/system_settings/DO_NOT_DELETE.txt", base), (
        "the marker is not a moving folder"
    )


def test_the_sweep_reaches_the_templates_it_claims_to() -> None:
    """Guard-the-guard: an empty population agrees with every possible change.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the pattern resolves onto nothing, or misses the three the spec names.
    """
    found = _templates()

    # Four, down from eleven: the seven per-plane enqueue grants are retired, because the browser
    # no longer writes a queue. The floor is what stops the sweep going silently empty, so it
    # tracks the real population rather than a number that was true once.
    assert len(found) >= 4, f"the sweep resolved onto {len(found)} templates"
    for named in (
        "portal-role-analytics",
        "portal-role-permissions",
        "portal-role-shared-space",
    ):
        assert any(named in path for path in found), named


def test_this_branch_names_no_new_catalog_ACTION() -> None:
    """A widening survives a re-baselined byte pin; this does not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any template gains an ``athena:``, ``glue:`` or ``lakeformation:``
        action it did not have at the branch's base, beyond what ``ADMITTED_ACTIONS`` names for
        that template.
    """
    added: dict[str, set[str]] = {}
    for path in _templates():
        gained = _actions((REPO / path).read_text()) - _actions(_at_base(path))
        gained -= ADMITTED_ACTIONS.get(path, frozenset())
        if gained:
            added[path] = gained

    assert added == {}, added


def test_this_branch_names_no_new_RESOURCE() -> None:
    """The other half: an action already held, pointed at something new, is also a widening.

    The one admitted widening is a ``system_settings/`` TWIN — see ``_is_admitted_twin``. It is
    admitted by SHAPE against the base, not by a list of file names, so the exemption cannot
    quietly cover anything else.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any template gains a resource that is not the system-settings twin of one
        it already named at the branch's base.
    """
    added: dict[str, set[str]] = {}
    for path in _templates():
        base = _resources(_at_base(path))
        gained = {
            resource
            for resource in _resources((REPO / path).read_text()) - base
            if not _is_admitted_twin(resource, base)
        }
        if gained:
            added[path] = gained

    assert added == {}, added


def test_the_comparison_can_actually_FAIL() -> None:
    """The assertion above is worthless if the reader returns nothing for every template.

    A base read that silently produced the empty string would make "gained nothing" true by
    accident for a file that gained everything — so the base is confirmed to hold real content,
    and the extractors are confirmed to find something in it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the base content or the extraction is empty.
    """
    analytics = next(path for path in _templates() if "portal-role-analytics" in path)
    base = _at_base(analytics)

    assert base.strip(), "the branch base carries no analytics template"
    assert _actions(base), "the action extractor found nothing to compare"
    assert _resources(base), "the resource extractor found nothing to compare"
    assert any(action.startswith(CATALOG_PREFIXES) for action in _actions(base)), (
        "the analytics template names no catalog action, so this guard has no subject"
    )


def _repo_with_a_non_ascii_template(work: str) -> pathlib.Path:
    """Build a throwaway repository holding three portal-role templates, one non-ASCII.

    Args:
      work: An existing empty directory to build in.

    Returns:
      pathlib.Path: The repository root, with one commit.

    Raises:
      subprocess.CalledProcessError: If any git command fails.
    """
    root = pathlib.Path(work)
    names = (
        "infra/modules/base/policies/portal-role-plain.json.tftpl",
        "infra/modules/base/policies/portal-role-café.json.tftpl",
        "infra/modules/café/policies/portal-role-a.json.tftpl",
    )
    for name in names:
        written = root / name
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text("{}\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)  # noqa: S603
    subprocess.run([*git, "add", "-A"], check=True)  # noqa: S603
    subprocess.run([*git, "commit", "-qm", "fixture"], check=True)  # noqa: S603
    return root


def test_the_enumeration_reads_paths_raw_rather_than_quoted():
    """A guard cannot protect a template git spelled in a way its pattern refuses.

    ``ls-files`` C-quotes any path that is not plain ASCII, and the quoted spelling fails
    ``POLICY_PATTERN``. The template then drops out of the population silently, which is the
    direction that reads as a clean guard. Three shapes, two of them non-ASCII: without ``-z``
    this keeps one of three.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a non-ASCII template is not enumerated.
    """
    with tempfile.TemporaryDirectory() as work:
        root = _repo_with_a_non_ascii_template(work)
        found = _templates(root=root)
    assert len(found) == 3, (
        f"the enumeration kept {len(found)} of 3 templates, so a non-ASCII path was quoted out "
        f"of the population this guard protects: {found}"
    )
