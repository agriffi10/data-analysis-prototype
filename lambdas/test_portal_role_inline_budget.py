"""The portal role's THREE inline policies share one 10,240-character budget, and nothing else says so.

IAM's inline-policy limit is an AGGREGATE over a role, not a per-document one, and the portal role
carries three inline policies written in three different modules — ``analytics`` and
``shared-spaces`` attach theirs by ``var.portal_role_name``, ``data`` by ``aws_iam_role.portal.id``.
Nothing in the Terraform makes that sharing visible from any one of them, so each module's author
sees a small document and the ceiling is somewhere else entirely.

**It is enforced at ``PutRolePolicy``, which means a plan cannot see it.** ``tofu validate`` passes,
the plan is green, and the apply fails with ``LimitExceeded`` after the merge —
``infra/modules/base/README.md`` records this happening once already, when an inline second policy
pushed the aggregate over. The deploy role has had a guard for its own aggregate since; this is the
portal role's, added when a change began adding statements to all three of these documents at once.

**A budget, not a pin.** The measured total is deliberately not asserted: a test that pins today's
number fails on every legitimate addition and teaches people to edit the number. What is asserted
is the ceiling, and a floor under the remaining headroom so that the aggregate cannot be quietly
consumed to the point where the next real grant has nowhere to go.

**The renderer was calibrated against the deployed role rather than trusted**, and the calibration
is a METHOD rather than a number here, because a number written down goes stale silently while
still reading as current. Re-derive it whenever this looks wrong::

    for p in $(aws iam list-role-policies --role-name <portal role> --query 'PolicyNames[]' --output text); do
      aws iam get-role-policy --role-name <portal role> --policy-name "$p" --query PolicyDocument --output json \\
        | python3 -c 'import json,re,sys; print(len(re.sub(r"\\s","",json.dumps(json.loads(sys.stdin.read()),separators=(",",":")))))'
    done

Compared that way when this was written, the renderer below reproduced the deployed aggregate and
every one of its three parts to the character. A first version substituted every interpolation with
one generic ARN and overstated the total by 1,354 — enough to have reported a headroom crisis that
did not exist, which is how a budget guard loses its reader.

The shared-space document is sized by ``max_shared_memberships``, so it is rendered at that
variable's declared default rather than at a guessed slot count — reading the number from the
Terraform is what keeps this measuring the policy that actually ships.

Attributes:
  INFRA: The Terraform tree.
  INLINE_AGGREGATE_LIMIT: IAM's limit on the total size of one role's inline policies, whitespace
    excluded.
  HEADROOM_FLOOR: How much of that aggregate must stay unspent. Sized in STATEMENTS, which is the
    unit a grant actually arrives in — the statements this arc added measure 200-400 characters
    each — so it reserves room for several more and asks the question while there is still room to
    act on the answer. It is deliberately NOT sized in whole documents: the smallest of the three
    is larger than the headroom that remains, so a document-sized floor would fire today and the
    only way to clear it would be the refactor it exists to give warning of.
  TEMPLATES: The inline policy documents attached to the portal role. Hand-written so the
    measurement is a stated claim, and reconciled against what the Terraform actually attaches by
    ``test_the_budget_measures_EVERY_inline_policy_on_the_portal_role`` — an uncounted fourth
    document would otherwise be reported as headroom.
  SUBSTITUTIONS: What each interpolation stands for, at the LENGTH it really renders to. IAM
    measures the rendered document, so substituting every variable with one generic value measures
    a document nobody deploys: a twelve-digit account id and an eight-character tag key are not
    ARNs, and treating them as ARNs overstated this aggregate by 1,354 characters when it was
    written.
  _GENERIC_ARN: What an interpolation this module does not know stands for. A resource ARN is the
    conservative guess, being longer than most of the alternatives.
"""

import json
import pathlib
import re

from tf_blocks import argument, blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

INLINE_AGGREGATE_LIMIT = 10_240

HEADROOM_FLOOR = 1_000

TEMPLATES = (
    "modules/analytics/policies/portal-role-analytics.json.tftpl",
    "modules/data/policies/portal-role-permissions.json.tftpl",
    "modules/shared-spaces/policies/portal-role-shared-space.json.tftpl",
)

SUBSTITUTIONS = {
    "user_space_bucket_arn": "arn:aws:s3:::dat-prod-user-space",
    "shared_space_bucket_arn": "arn:aws:s3:::dat-prod-shared-space",
    "bucket_arn": "arn:aws:s3:::dat-prod-user-space",
    "workgroup_arn": "arn:aws:athena:us-east-1:696000197480:workgroup/dat-prod-workgroup",
    "aws_region": "us-east-1",
    "account_id": "696000197480",
    "principal_tag_key": "username",
}

_GENERIC_ARN = "arn:aws:service:us-east-1:696000197480:resource/dat-prod-name"

_ESCAPE = "\x00ESCAPED_INTERPOLATION\x00"
_VARIABLE = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")
_FOR = re.compile(r"%\{\s*for\s+(\w+)\s+in\s+range\(1,\s*max_shared_memberships \+ 1\)\s*~\}(.*?)%\{\s*endfor\s*~\}", re.DOTALL)
_TERNARY = re.compile(r"\$\{\w+ < max_shared_memberships \? \"(,?)\" : \"(,?)\"\}")


def _slots() -> int:
    """Reads ``max_shared_memberships``' declared default out of the root variables.

    Args:
      None.

    Returns:
      The slot count the shared-space policy is sized by.

    Raises:
      AssertionError: If the variable or its default is gone, which would make every measurement
        below a guess.
    """
    source = (INFRA / "variables.tf").read_text()
    block = re.search(r'variable "max_shared_memberships" \{(.*?)\n\}', source, re.DOTALL)
    assert block, "root no longer declares max_shared_memberships"
    default = re.search(r"default\s*=\s*(\d+)", block.group(1))
    assert default, "max_shared_memberships has no default"
    return int(default.group(1))


def _render(text: str, slots: int) -> str:
    """Expands a portal-role template the way Terraform would, for measurement.

    Handles the one directive shape these documents use — a ``for`` over the membership slots with
    a trailing-comma ternary — then substitutes the remaining interpolations for values of a
    realistic length, because IAM measures the RENDERED document and an ARN is far longer than the
    ``${…}`` that stands for it.

    Args:
      text: The template's source.
      slots: How many membership slots to expand the loop to.

    Returns:
      The rendered document.

    Raises:
      None.
    """

    def expand(match: re.Match) -> str:
        """Repeats one loop body once per slot, resolving its separator ternary.

        Args:
          match: The ``for``/``endfor`` match, carrying the loop variable and its body.

        Returns:
          The expanded text.

        Raises:
          None.
        """
        variable, body = match.group(1), match.group(2)
        rendered = []
        for index in range(1, slots + 1):
            separator = 1 if index < slots else 2
            once = _TERNARY.sub(lambda ternary, group=separator: ternary.group(group), body)
            rendered.append(once.replace(f"${{{variable}}}", str(index)))
        return "".join(rendered)

    expanded = _FOR.sub(expand, text)
    protected = expanded.replace("$${", _ESCAPE)
    substituted = _VARIABLE.sub(lambda m: SUBSTITUTIONS.get(m.group(1), _GENERIC_ARN), protected)
    return substituted.replace(_ESCAPE, "${")


def _stripped_length(text: str) -> int:
    """Measures a policy the way IAM measures it: without whitespace.

    Args:
      text: A rendered policy document.

    Returns:
      The count of non-whitespace characters.

    Raises:
      None.
    """
    return len(re.sub(r"\s", "", text))


def _rendered_sizes() -> dict[str, int]:
    """Renders all three inline documents and measures each.

    Args:
      None.

    Returns:
      Template path to its rendered, whitespace-stripped length.

    Raises:
      AssertionError: If a document no longer renders to parseable JSON, which would mean this
        measurement is of something other than a policy.
    """
    slots = _slots()
    sizes = {}
    for relative in TEMPLATES:
        rendered = _render((INFRA / relative).read_text(), slots)
        json.loads(rendered)
        sizes[relative] = _stripped_length(rendered)
    return sizes


def _declared_portal_inline_templates() -> set[str]:
    """Finds every inline policy the Terraform attaches to the portal role.

    The budget is an AGGREGATE, so a fourth inline policy attached anywhere in the tree spends it
    too. Hand-listing the three would measure a subset and report the difference as headroom —
    silently, and in the direction that reads as safe.

    The role is named two ways in this tree: modules that receive it take ``var.portal_role_name``,
    and the module that creates it uses ``aws_iam_role.portal.id``. Both are recognised, because
    recognising only one would leave the creator's own policy uncounted.

    Args:
      None.

    Returns:
      The template paths, relative to the infra tree.

    Raises:
      None.
    """
    found = set()
    for path in sorted(INFRA.rglob("*.tf")):
        for body in blocks(path.read_text(), "aws_iam_role_policy").values():
            role = argument(body, "role").strip()
            if role not in ("var.portal_role_name", "aws_iam_role.portal.id"):
                continue
            template = re.search(r'templatefile\(\s*"\$\{path\.module\}/([^"]+)"', argument(body, "policy"))
            if template:
                found.add(f"{path.parent.relative_to(INFRA).as_posix()}/{template.group(1)}")
    return found


def test_the_slot_count_this_measures_is_the_slot_count_that_DEPLOYS() -> None:
    """The largest of the three documents is sized per membership slot, and a repo variable can move it.

    ``_slots`` reads ``max_shared_memberships``' declared default, which is only the deployed value
    while nothing overrides it. ``TF_VAR_max_shared_memberships`` in a workflow's environment would
    raise the real slot count without touching ``variables.tf``, so the budget would keep reporting
    headroom computed at a number the plan no longer uses — and the variable's own description names
    enlarging the portal-role policy as the consequence of raising it, which makes this the
    documented route to overspending the one thing this module measures.

    So the override is refused rather than followed: a run that needs more slots has to come here
    and re-derive the budget. The per-slot cost is what makes that a decision rather than a guess —
    it is printed in the failure below rather than pinned, because pinning it would be a second
    measurement to keep in step with the first.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any workflow sets the variable this module reads from ``variables.tf``.
    """
    workflows = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
    setters = sorted(
        path.name
        for path in workflows.glob("*.yml")
        if "TF_VAR_max_shared_memberships" in path.read_text()
    )

    slots = _slots()
    one_fewer = sum(_stripped_length(_render((INFRA / rel).read_text(), slots - 1)) for rel in TEMPLATES)
    per_slot = sum(_rendered_sizes().values()) - one_fewer

    assert setters == [], (
        f"{setters} set TF_VAR_max_shared_memberships, so the deployed slot count is not the "
        f"{slots} this module measures at. Each slot costs about {per_slot} characters of the "
        f"{INLINE_AGGREGATE_LIMIT:,} aggregate; re-derive the budget here before raising it."
    )


def test_the_budget_measures_EVERY_inline_policy_on_the_portal_role() -> None:
    """The aggregate is shared, so an uncounted document is headroom this test would invent.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the Terraform attaches an inline policy to the portal role that the
        measurement below does not read.
    """
    declared = _declared_portal_inline_templates()

    assert declared, "no inline policy resolves to the portal role — the scan has stopped matching"
    assert declared == set(TEMPLATES), {
        "attached but unmeasured": sorted(declared - set(TEMPLATES)),
        "measured but not attached": sorted(set(TEMPLATES) - declared),
    }


def test_the_three_inline_portal_policies_fit_the_shared_iam_aggregate() -> None:
    """The ceiling. Exceeding it fails the apply, after the plan and every local gate went green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the three documents together exceed IAM's aggregate.
    """
    sizes = _rendered_sizes()
    total = sum(sizes.values())

    assert total <= INLINE_AGGREGATE_LIMIT, (
        f"the portal role's inline policies render to {total:,} non-whitespace characters against "
        f"IAM's {INLINE_AGGREGATE_LIMIT:,} aggregate: {sizes}. This fails at PutRolePolicy, on the "
        "apply, with a green plan behind it. Move a grant into a customer-managed policy, which "
        "carries its own separate budget."
    )


def test_the_aggregate_keeps_room_for_another_grant() -> None:
    """The floor under the headroom, so the ceiling cannot be reached one statement at a time.

    A budget that is only ever checked against the hard limit reports success right up to the point
    where the next legitimate addition has nowhere to go, and by then the answer is a refactor
    rather than an edit. This says so while there is still room to act on it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If less than the reserved headroom remains.
    """
    sizes = _rendered_sizes()
    remaining = INLINE_AGGREGATE_LIMIT - sum(sizes.values())

    assert remaining >= HEADROOM_FLOOR, (
        f"only {remaining:,} characters of the portal role's inline aggregate remain, under the "
        f"{HEADROOM_FLOOR:,} this reserves: {sizes}. The next grant will not fit, so decide now "
        "which of these documents becomes a customer-managed policy rather than at the apply that "
        "refuses it."
    )


def test_the_measurement_reads_all_three_documents_and_expands_the_loops() -> None:
    """Guard the guard: a renderer returning something tiny would make both budgets pass by accident.

    The shared-space document's size is dominated by its per-slot loops, so a renderer that failed
    to expand them would under-measure the largest of the three by most of its content — and would
    do it silently, in the direction that reads as headroom.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a document is missing, empty, or unexpanded.
    """
    slots = _slots()

    shared = _render((INFRA / TEMPLATES[2]).read_text(), slots)
    assert "%{" not in shared and "${k}" not in shared, (
        "the membership loops were not expanded, so the largest of the three documents is measured "
        "at a fraction of its real size — silently, and in the direction that reads as headroom"
    )
    assert shared.count("shared_space_1") >= 1 and shared.count(f"shared_space_{slots}") >= 1, (
        f"the loops did not expand to all {slots} slots, so the largest document is under-measured"
    )

    sizes = _rendered_sizes()

    assert set(sizes) == set(TEMPLATES), f"the measurement read {sorted(sizes)}"
    assert all(size > 200 for size in sizes.values()), f"a document measured implausibly small: {sizes}"
