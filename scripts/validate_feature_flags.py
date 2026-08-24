"""Validate ``config/feature-flags.json`` before it can reach a bucket (SPEC-162 FR-002).

A feature flag is presentation-only, so a malformed document cannot break authorization —
but it can silently do nothing, which is worse than failing. A typo'd flag key resolves to
the compiled-in default, an environment block nobody publishes never takes effect, and both
look exactly like a healthy all-on environment. Every one of those is a hard error here.

Runs twice: on every pull request (``ci.yml``) and again in ``deploy-config.yml`` immediately
before the upload, so a document that was edited between the two still cannot land. It takes
no arguments and depends on nothing outside the standard library, because the publish
workflow runs it before any package install.

THE UPLOAD TARGETS ARE READ FROM THE PUBLISH WORKFLOW, not passed in. FR-002 requires the
check in both directions — an environment block with no upload target, and an upload target
with no environment block — and a target list handed to this script by the same workflow that
declares it would be comparing a copy of the answer with itself. The workflow's matrix is the
single declaration; this reads it.

Attributes:
  SUPPORTED_VERSIONS: The document versions this validator (and the browser reader) understand.
  FLAG_KEYS: Every flag. A key outside this set is a typo, never a new flag — adding one is a
    code change here, in the browser's key list, and in the document. Five are primary features;
    `asyncFileOperations` is a kill switch over the file browser's copy/move/delete routing.
  DOCUMENT: The one file a flag value may be edited in.
  PUBLISH_WORKFLOW: The workflow whose matrix declares where the document is published.
  TARGET_RE: Matches one ``environment_name:`` entry in that matrix. Deliberately not
    ``environment:`` — that is a GitHub Actions job keyword, and matching it would let an
    unrelated deployment-environment block masquerade as an upload target.
  BUCKET_VAR_RE: Matches the ``bucket_var:`` key that must accompany each target. Anchored to
    the start of a line so the ``vars[matrix.bucket_var]`` reference in the steps below the
    matrix cannot stand in for a missing declaration.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

SUPPORTED_VERSIONS = frozenset({1})
FLAG_KEYS = frozenset(
    {"files", "query", "sharedWorkspaces", "dataQuality", "dataExplorer", "asyncFileOperations"}
)
DOCUMENT = ROOT / "config" / "feature-flags.json"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-config.yml"
TARGET_RE = re.compile(r"^\s*-?\s*environment_name:\s*(\S+)\s*$", re.MULTILINE)
BUCKET_VAR_RE = re.compile(r"^\s*bucket_var:\s*(\S+)\s*$", re.MULTILINE)


class ValidationError(Exception):
    """A document, or the coupling between it and the publish workflow, is unusable."""


def read_upload_targets(workflow_text: str) -> set[str]:
    """Read the environment names the publish workflow's matrix uploads to.

    Guards the guard: a matrix that parses to nothing would make the bidirectional target
    check below vacuous in the one direction that matters most — every environment block
    would look published. A reformat that breaks this regex must fail loudly rather than
    quietly stop checking.

    Each entry must also name the repository variable holding its destination bucket. An
    entry without one is caught at publish time by the workflow's own empty-bucket guard,
    which is a correct but late failure — an incomplete matrix is a document-time defect and
    belongs here, where it costs a PR check rather than a red deploy.

    Args:
      workflow_text: The publish workflow's source.

    Returns:
      The declared environment names.

    Raises:
      ValidationError: If the matrix declares no targets at all, or an entry names no bucket.
    """
    entries = TARGET_RE.split(workflow_text)[1:]
    targets = {name for name, _rest in zip(entries[::2], entries[1::2], strict=True)}
    if not targets:
        raise ValidationError(
            f"{PUBLISH_WORKFLOW.name} declares no `environment_name:` upload targets — "
            "the matrix was renamed or reformatted, and the cross-check below would pass vacuously"
        )

    incomplete = sorted(
        name for name, rest in zip(entries[::2], entries[1::2], strict=True) if not BUCKET_VAR_RE.search(rest)
    )
    if incomplete:
        raise ValidationError(
            f"{PUBLISH_WORKFLOW.name} matrix entries {incomplete} name no `bucket_var:` — "
            "they declare a destination that does not exist"
        )
    return targets


def validate_document(document: object, targets: set[str]) -> list[str]:
    """Check one parsed document against the flag contract and the declared upload targets.

    Collects every problem rather than raising on the first, so one run names everything
    that has to change.

    Args:
      document: The parsed ``feature-flags.json``.
      targets: The environment names the publish workflow uploads to.

    Returns:
      Every problem found, each a complete sentence; empty when the document is valid.
    """
    if not isinstance(document, dict):
        return ["the document must be a JSON object"]

    problems: list[str] = []
    problems.extend(_version_problems(document.get("version")))
    problems.extend(_defaults_problems(document.get("defaults")))
    problems.extend(_environments_problems(document.get("environments"), targets))
    return problems


def _version_problems(version: object) -> list[str]:
    """Checks the document version is one this build understands.

    Args:
      version: The document's ``version`` field, whatever it holds.

    Returns:
      The problems found; empty when the version is supported.
    """
    # `isinstance(True, int)` is True and `hash(True) == hash(1)`, so a bare membership test
    # ACCEPTS `"version": true` — which the browser then refuses, because `true !== 1` in JS.
    # A document that passes here and is refused there is the exact silent failure this
    # validator exists to prevent, so the bool is excluded before the membership test.
    if isinstance(version, bool) or not isinstance(version, int) or version not in SUPPORTED_VERSIONS:
        known = ", ".join(str(v) for v in sorted(SUPPORTED_VERSIONS))
        return [f"unknown version {version!r} — this validator understands {known}"]
    return []


def _defaults_problems(defaults: object) -> list[str]:
    """Checks ``defaults`` names every flag exactly once, each an explicit boolean.

    ``defaults`` is total where an environment block is partial: it is the value in force
    for an environment that overrides nothing, so an omission there is a missing answer
    rather than an inherited one.

    Args:
      defaults: The document's ``defaults`` block, whatever it holds.

    Returns:
      The problems found; empty when the block is complete and well-typed.
    """
    if not isinstance(defaults, dict):
        return ["`defaults` must be an object naming every flag"]

    problems = [f"`defaults` is missing the {key!r} flag" for key in sorted(FLAG_KEYS - set(defaults))]
    problems.extend(_flag_problems(defaults, "defaults"))
    return problems


def _environments_problems(environments: object, targets: set[str]) -> list[str]:
    """Checks every environment block, and that blocks and upload targets correspond exactly.

    A block with no target is never published, and a target with no block publishes nothing
    but the defaults under an environment name someone believed they had configured. Both
    are defects rather than defaults, so both fail.

    Args:
      environments: The document's ``environments`` map, whatever it holds.
      targets: The environment names the publish workflow uploads to.

    Returns:
      The problems found; empty when every block is valid and the two sets match.
    """
    if not isinstance(environments, dict):
        return ["`environments` must be an object mapping an environment name to its overrides"]

    problems: list[str] = []
    for name in sorted(environments):
        block = environments[name]
        if not isinstance(block, dict):
            problems.append(f"environment {name!r} must be an object of flag overrides")
            continue
        problems.extend(_flag_problems(block, f"environments.{name}"))

    problems.extend(
        f"environment {name!r} has no upload target in {PUBLISH_WORKFLOW.name} — it would never be published"
        for name in sorted(set(environments) - targets)
    )
    problems.extend(
        f"{PUBLISH_WORKFLOW.name} uploads to {name!r}, which the document does not name"
        for name in sorted(targets - set(environments))
    )
    return problems


def _flag_problems(block: dict[str, object], where: str) -> list[str]:
    """Checks one block's keys are known flags and its values are real booleans.

    A string ``"true"`` is not a flag value. It is truthy in every language the document
    passes through, so accepting it would make the one spelling that cannot be turned off
    look like the one that can.

    Args:
      block: The ``defaults`` block or one environment's overrides.
      where: Dotted path to the block, for the message.

    Returns:
      The problems found; empty when every key is known and every value is a boolean.
    """
    problems = [f"`{where}` has unknown flag {key!r}" for key in sorted(set(block) - FLAG_KEYS)]
    problems.extend(
        f"`{where}.{key}` must be true or false, not {block[key]!r}"
        for key in sorted(set(block) & FLAG_KEYS)
        if not isinstance(block[key], bool)
    )
    return problems


def main() -> int:
    """Validate the checked-in document and report every problem on stderr.

    Args:
      None.

    Returns:
      ``0`` when the document is valid, ``1`` otherwise.
    """
    try:
        targets = read_upload_targets(PUBLISH_WORKFLOW.read_text())
        document = json.loads(DOCUMENT.read_text())
    except (OSError, ValidationError, json.JSONDecodeError) as err:
        print(f"feature-flags: {err}", file=sys.stderr)
        return 1

    problems = validate_document(document, targets)
    if problems:
        for problem in problems:
            print(f"feature-flags: {problem}", file=sys.stderr)
        return 1

    print(f"feature-flags: {DOCUMENT.relative_to(ROOT)} is valid for {', '.join(sorted(targets))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
