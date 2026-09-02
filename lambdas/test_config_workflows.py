"""The deploy workflows' agreements about reading Terraform state.

Two workflows now init the same backend and resolve their configuration from it, and a
third and a fourth already declare an OpenTofu version. Every assertion here is DERIVED
from the workflow directory rather than written against a list: a further consumer is
coming, and a check that counted to three would keep passing while the fourth drifted.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The directory every assertion here derives its subject from.
  RESOLVE_STEP: The resolve step's name, used to find every workflow that has one.
  RETIRED_VARIABLES: Repository variables this spec replaced with Terraform outputs. A
    reference to one that survives in any workflow is reading a value nobody maintains.
  SURVIVING_VARIABLE: A variable that is still a genuine input, used as the positive
    control for the sweep below.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
RESOLVE_STEP = "- name: Resolve the configuration from Terraform state"

RETIRED_VARIABLES = (
    "API_BASE_URL",
    "VITE_COGNITO_USER_POOL_ID",
    "VITE_COGNITO_USER_POOL_CLIENT_ID",
    "VITE_COGNITO_DOMAIN",
    "VITE_S3_USER_SPACE_BUCKET",
    "VITE_S3_SHARED_SPACE_BUCKET",
)
SURVIVING_VARIABLE = "AWS_REGION"


def _workflows() -> list[pathlib.Path]:
    """Every workflow file, refusing an empty directory.

    Returns:
      The workflow paths, sorted.

    Raises:
      AssertionError: If the directory holds no workflow, which would make every sweep
        below report agreement over nothing.
    """
    found = sorted(WORKFLOWS.glob("*.yml"))
    assert found, "no workflows found — every assertion in this module would be vacuous"
    return found


def test_every_workflow_declaring_an_opentofu_version_declares_the_same_one() -> None:
    """The predicate is *declares a version*, not *runs `tofu init`*, and that is load-bearing.

    A workflow can read an output through ``resolve-config.sh`` without an init of its own,
    so an init-based predicate would exclude the very consumer this derivation exists to
    cover. ``ci.yml`` pins a version and runs no deploy at all, and is included for the same
    reason.

    The comparison is over the constraint strings AS DECLARED. They read ``~1.8``, which is a
    constraint and not a version, so "they agree" can only mean the declarations are one
    string — claiming they resolve to one version would be claiming something the workflow
    files cannot state.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If nothing declares a version, or two declarations differ.
    """
    declared: dict[str, set[str]] = {}
    for path in _workflows():
        versions = set(re.findall(r"^\s*tofu_version:\s*(\S+)\s*$", path.read_text(), re.MULTILINE))
        if versions:
            declared[path.name] = versions

    assert declared, "no workflow declares an OpenTofu version — this comparison has no subject"
    assert "deploy-infra.yml" in declared, "the infrastructure workflow stopped declaring a version"

    distinct = set().union(*declared.values())
    assert len(distinct) == 1, f"OpenTofu version declarations disagree: {declared}"


def test_every_tofu_init_names_the_same_backend_configuration() -> None:
    """One state, addressed one way, however many workflows read it.

    Derived rather than counted: the number of init sites is expected to grow, and a test
    asserting how many there are would have to be edited by the change that adds one — which
    is exactly when nobody re-derives what it was protecting.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no init is found, or two of them name different backend keys.
    """
    per_file: dict[str, set[frozenset[str]]] = {}
    for path in _workflows():
        text = path.read_text()
        for block in re.findall(r"tofu init((?:\s*\\\s*\n\s*-backend-config=\"[^\"]+\")+)", text):
            keys = frozenset(re.findall(r'-backend-config="([a-z_]+)=', block))
            per_file.setdefault(path.name, set()).add(keys)

    assert per_file, "no `tofu init` with backend configuration found — no subject"
    assert "deploy-config.yml" in per_file, "deploy-config.yml does not init the backend"

    distinct = {keys for entries in per_file.values() for keys in entries}
    assert len(distinct) == 1, f"backend configurations disagree: {per_file}"
    assert distinct.pop() == frozenset({"bucket", "dynamodb_table", "region"})


def test_no_workflow_reads_a_retired_repository_variable() -> None:
    """The values moved to Terraform state; a surviving reference reads a stale copy.

    The positive control is the point of the second half. A sweep whose matcher had stopped
    matching would report every retired name absent and pass — the same shape as success —
    so it must first prove it can still find a variable that IS there.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the matcher finds nothing at all, or any retired name survives.
    """
    references: dict[str, set[str]] = {}
    for path in _workflows():
        found = set(re.findall(r"vars\.([A-Za-z_][A-Za-z0-9_]*)", path.read_text()))
        if found:
            references[path.name] = found

    seen = set().union(*references.values()) if references else set()
    assert SURVIVING_VARIABLE in seen, (
        f"the sweep did not find {SURVIVING_VARIABLE}, which is still referenced — "
        "the matcher is broken, so its report of absences means nothing"
    )

    surviving = sorted(
        f"{name}:{variable}"
        for name, found in references.items()
        for variable in found
        if variable in RETIRED_VARIABLES
    )
    assert surviving == [], f"retired repository variables still read: {surviving}"


def test_the_resolve_refusal_lands_before_any_aws_write() -> None:
    """A failed resolve must leave every live surface exactly as it was.

    The credentials step moved above the resolve because reading remote state is an AWS
    call, and that is safe only because it is a READ. If a write ever preceded the resolve,
    a job could half-update a bucket and then fail on a value it could have checked first.

    Derived over EVERY workflow that resolves, not written against one. Both deploy
    workflows resolve now and a third is expected, and the one that most needs this is
    ``deploy-config.yml``: it deleted its own empty-bucket guard in favour of the resolver,
    so it has no second line of defence between an unresolved destination and an
    ``aws s3 cp``.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no workflow resolves, if one has no AWS write to order against,
        or if any write precedes its resolve.
    """
    resolvers = {path.name: path.read_text() for path in _workflows() if RESOLVE_STEP in path.read_text()}

    assert resolvers.keys() >= {"deploy-config.yml"}, (
        f"expected the publishing workflow to resolve, found {sorted(resolvers)}"
    )

    early: dict[str, list[str]] = {}
    for name, text in resolvers.items():
        resolve_at = text.find(RESOLVE_STEP)
        writes = [
            (match.start(), match.group(0).strip())
            for match in re.finditer(
                r"^\s+aws (?:s3 (?:cp|sync)|cloudfront create-invalidation)[^\n]*", text, re.MULTILINE
            )
        ]
        assert writes, f"no AWS writes found in {name} — the ordering claim has no subject there"

        preceding = [command for position, command in writes if position < resolve_at]
        if preceding:
            early[name] = preceding

    assert early == {}, f"AWS writes precede the configuration resolve: {early}"
