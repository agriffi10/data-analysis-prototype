"""The Lambda image registry's retention bound must be computed, not chosen.

A lifecycle policy that keeps "about thirty" images is a number with no model behind it, and the
failure it hides is silent in the direction that matters: too small, and the image a rollback
needs has already expired, which is discovered during the rollback. So the bound here is derived
from two named inputs — how fast this repository merges, and how far back a rollback has to be
able to reach — and this module fails if the Terraform and the derivation disagree.

The registry's other properties are asserted here too, for the reason the bound is: every one of
them is invisible in a plan diff once it is right, and each has a failure mode that looks like
nothing. A mutable tag lets a re-push change what a rolled-back function starts; a missing
untagged rule leaves orphans nothing can reference and nothing expires; two rules sharing a
priority is refused by the API at apply, after the plan is green.

Attributes:
  ROOT: The repository root.
  MODULE: The Lambda image module's registry definition.
  PLATFORM_POLICY: The deploy role's platform grants, which name the repository this module
    creates. The two are written in different files and IAM matches ARNs literally, so a rename
    on either side is a grant that authorizes nothing.
  MEASURED_COMMIT_COUNTS: Pushes to `main` over trailing windows, counted with
    `git rev-list --count --first-parent --since=` on 2026-09-01. Recorded as DATA rather than as
    a rate, so the peak below is derived from a measurement someone would have to falsify rather
    than from a number they could retype. An earlier version stated the rate directly, and a
    reviewer showed the bound could then be halved by editing one constant and the Terraform
    together, with both tests still green.
  MEASURED_PEAK_MERGES_PER_DAY: The busiest of those windows, rounded up. The peak rather than
    the mean, because a bound sized on the average is short during exactly the weeks a rollback
    is most likely.
  ROLLBACK_WINDOW_DAYS: How far back a rollback must be able to reach. Five days is a long
    weekend plus a working day, which is the budget this bound is for: an import that only a
    rare function's cold start reveals can take a day or more to surface, and the image it has
    to roll back to must still exist when it does.
  EXPECTED_RETAINED_IMAGES: The two multiplied. This is the number the Terraform must carry.
"""

import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "infra" / "modules" / "lambda-image" / "ecr.tf"
PLATFORM_POLICY = (
    ROOT / "infra" / "modules" / "base" / "policies" / "github-actions-deploy-platform.json.tftpl"
)

MEASURED_COMMIT_COUNTS = {7: 102, 14: 133, 30: 278, 60: 416, 90: 629}
MEASURED_PEAK_MERGES_PER_DAY = math.ceil(
    max(count / days for days, count in MEASURED_COMMIT_COUNTS.items())
)
ROLLBACK_WINDOW_DAYS = 5
EXPECTED_RETAINED_IMAGES = MEASURED_PEAK_MERGES_PER_DAY * ROLLBACK_WINDOW_DAYS


def _module_text() -> str:
    """Reads the registry module, refusing an empty read.

    Every assertion below is a search over this text, and a search over an empty string finds
    nothing — which reads exactly like a rule that is absent rather than a file that moved.

    Args:
      None.

    Returns:
      The module's source.

    Raises:
      AssertionError: When the file is missing or empty.
    """
    assert MODULE.is_file(), f"{MODULE} is missing — the registry module moved or was renamed."
    text = MODULE.read_text()
    assert text.strip(), f"{MODULE} is empty."
    return text


def _retained_images() -> int:
    """Extracts the count the tagged-image rule retains.

    Keyed on ``imageCountMoreThan`` rather than on ``countNumber``: both rules carry a
    ``countNumber``, and the untagged rule's is a number of DAYS. A parse that took the first
    ``countNumber`` it found would compare the retention bound against one.

    Args:
      None.

    Returns:
      The number of tagged images retained.

    Raises:
      AssertionError: When the rule cannot be located, so a regex matching nothing cannot read
        as agreement.
    """
    match = re.search(
        r'countType\s*=\s*"imageCountMoreThan"\s*\n\s*countNumber\s*=\s*(\d+)', _module_text()
    )
    assert match, (
        "no imageCountMoreThan rule found in the registry's lifecycle policy. Either the policy "
        "lost its retention rule or this parse no longer matches how it is written — and a "
        "search that matches nothing must never read as a bound that agrees."
    )
    return int(match.group(1))


def test_the_retention_bound_is_the_one_the_budget_computes() -> None:
    """The retained-image count must equal the merge rate times the rollback window.

    This is the ONLY assertion over the bound, deliberately. A second one restating the budget
    as a question about days — "the bound covers at least the window" — reads like an independent
    guard and is not one: given this assertion passes, `(peak x window) / peak >= window` is a
    tautology, and two reviewers independently proved it could not fail. A test that cannot fail
    is worse than no test, because three other places then cite it as protection.

    What actually protects the bound is where the peak comes from: `MEASURED_COMMIT_COUNTS` is a
    record of what `git rev-list` returned, so lowering the rate means falsifying a dated
    measurement rather than retyping a number. The window is an argued engineering budget — a
    long weekend plus a working day — and changing it is a visible, deliberate edit to a named
    constant, which is what the requirement asks for.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the Terraform and the derivation disagree.
    """
    assert _retained_images() == EXPECTED_RETAINED_IMAGES, (
        f"the registry retains {_retained_images()} images; "
        f"{MEASURED_PEAK_MERGES_PER_DAY} merges/day over a {ROLLBACK_WINDOW_DAYS}-day rollback "
        f"window computes {EXPECTED_RETAINED_IMAGES}. Change the inputs and say why, rather "
        "than the answer."
    )


def test_untagged_images_expire_and_the_rules_do_not_collide() -> None:
    """An untagged rule must exist, and no two rules may share a priority.

    With immutable tags an untagged image is one a later push orphaned, which nothing can
    reference and which the retention rule does not select — so without this rule they
    accumulate forever. Duplicate priorities are refused by the API at apply, which is after
    the plan is green and after every test that reads the file as text.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the untagged rule is absent or two rules share a priority.
    """
    text = _module_text()
    assert re.search(r'tagStatus\s*=\s*"untagged"', text), (
        "no untagged rule in the registry's lifecycle policy. Untagged images are orphans "
        "nothing can pull and the retention rule does not select them."
    )
    priorities = re.findall(r"rulePriority\s*=\s*(\d+)", text)
    assert priorities, "no rulePriority found — the lifecycle policy is not being read."
    assert len(priorities) == len(set(priorities)), (
        f"lifecycle rules share a priority ({priorities}). PutLifecyclePolicy refuses that at "
        "apply, long after the plan is green."
    )


def test_the_registry_refuses_a_tag_to_be_rewritten() -> None:
    """Tags must be immutable, and scanning must run on push.

    The tag is the commit sha, so mutability is what would let a re-push under an existing sha
    change what a rolled-back function starts with nothing in the state recording it. Both
    settings are also Checkov checks this repository holds at zero, so a regression here fails
    two gates rather than one — but only this test says why.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either setting is absent.
    """
    text = _module_text()
    assert re.search(r'image_tag_mutability\s*=\s*"IMMUTABLE"', text), (
        "the Lambda image registry does not declare IMMUTABLE tags."
    )
    assert re.search(r"scan_on_push\s*=\s*true", text), (
        "the Lambda image registry does not scan on push."
    )


def test_the_repository_name_is_the_one_the_deploy_role_was_granted() -> None:
    """The name this module builds must be matched by the deploy role's registry grants.

    The name is constructed here and the grant's ARN pattern is written in a policy template, in
    another module, in another PR. IAM matches ARNs literally, so a rename on either side yields
    a grant that reads correct to a human and authorizes nothing — and the symptom is a push
    denied for a reason the policy visibly appears to allow.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the constructed name is not covered by a registry statement, or the
        module stops constructing a name at all.
    """
    text = _module_text()
    assert re.search(r"name\s*=\s*local\.image_name", text), (
        "the repository's `name` is no longer built from local.image_name, so the check below "
        "reads a local that nothing uses. Renaming the resource directly is the likelier way to "
        "rename a repository than editing the local, and it is the path this test used to miss."
    )

    names = pathlib.Path(MODULE.parent / "names.tf").read_text()
    match = re.search(r'image_name\s*=\s*"\$\{local\.name_prefix\}-([a-z0-9-]+)"', names)
    assert match, (
        "the registry module no longer builds its name from name_prefix plus a literal suffix, "
        "so this test cannot tell which name the grant has to cover."
    )
    suffix = match.group(1)

    policy = PLATFORM_POLICY.read_text()
    pattern = f'repository/${{project_name}}-*-{suffix}*'
    assert pattern in policy, (
        f"the deploy role has no registry grant covering a repository ending in {suffix!r}. "
        f"Expected an ARN pattern containing {pattern!r} in {PLATFORM_POLICY.name}. The grant "
        "lands in its own PR, before this module."
    )
