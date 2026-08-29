"""Who may write a control-plane request queue, enumerated from the filesystem.

The access model here is identity-based and nothing else: there is no ``aws_sqs_queue_policy``
anywhere in the tree, so "only the API may write" is achieved by adding one grant and removing
eight. That makes the enumeration below the whole guard — a hand-kept list is exactly what would
miss the ninth plane.

Attributes:
  REPO: The repository root.
  INFRA: The IaC tree.
  QUEUE_MODULES: The eight modules that own a request queue, enumerated from the filesystem.
  NOTIFYING_ROLES: Every execution role that sends a notification, which this change must leave
    holding its grant.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"

QUEUE_MODULES = sorted(
    path.parent.name
    for path in INFRA.glob("modules/*/sqs.tf")
    if "requests" in path.read_text()
)

NOTIFYING_ROLES = (
    "shared-spaces",
    "table-builder",
    "table-share",
    "data-quality",
    "file-send",
    "archive",
    "file-ops",
    "control-plane-dlq-drain",
)


def _portal_templates() -> list[pathlib.Path]:
    """Every policy template attached to the portal role, from the filesystem.

    Returns:
      The templates.

    Raises:
      None.
    """
    return sorted(INFRA.glob("modules/*/policies/portal-role-*.json.tftpl"))


def test_the_enumeration_reaches_the_eight_queues_it_claims_to():
    """A glob that found nothing would make every sweep below vacuously clean.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the queue modules are not the eight this arc knows about.
    """
    assert len(QUEUE_MODULES) == 8, QUEUE_MODULES
    assert _portal_templates(), "no portal-role templates found — the glob is broken"


def test_no_policy_on_the_portal_role_can_write_a_request_queue():
    """The browser's eight enqueue grants are gone, and the sweep is enumerated, not listed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any portal-role template still carries a queue send.
    """
    offenders = [
        str(path.relative_to(REPO))
        for path in _portal_templates()
        if "sqs:SendMessage" in path.read_text()
    ]

    assert offenders == [], (
        f"the portal role can still write a queue: {offenders}. The API is the only writer, and "
        "a browser credential that can write one can forge the actor the planes are about to trust."
    )


def test_every_execution_role_that_notifies_still_holds_its_grant():
    """The shape a reader reaches for here silences every one of them, and silently.

    The notifications request queue has eight writers and this change removes exactly one — the
    portal role. The other seven are execution roles that notify, plus the dead-letter drain. A
    blanket ``Deny`` with a ``StringNotEquals`` on the API's role ARN would be the obvious way to
    say "only the API writes", and it would stop every outcome notification this product sends:
    the shared-spaces producer runs with ``ResultPath: null`` and a ``Catch`` leading onward so it
    deliberately cannot fail its run, and the other planes notify best-effort. Archives, shares
    and sends would all complete, and no user would ever be told.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a notifying role lost its send.
    """
    missing = []
    for role in NOTIFYING_ROLES:
        templates = list(INFRA.glob(f"modules/{role}/policies/*.json.tftpl"))
        sends = [
            path
            for path in templates
            if "sqs:SendMessage" in path.read_text()
            and "notifications" in path.read_text()
        ]
        assert templates, (
            f"no policy template found for {role} — a renamed module would otherwise drop out of "
            "this sweep silently, and an empty population agrees with every possible change"
        )
        if not sends:
            missing.append(role)

    assert missing == [], f"these roles can no longer notify: {missing}"


def test_the_api_grant_names_the_eight_queues_and_no_wildcard():
    """One grant, eight ARNs, rendered from a list the module refuses at any other length.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the grant is missing, reaches a wildcard, or names a DLQ.
    """
    policy = (
        INFRA / "modules" / "api" / "policies" / "api-execution-policy.json.tftpl"
    ).read_text()
    variables = (INFRA / "modules" / "api" / "variables.tf").read_text()

    assert '"Sid": "EnqueueControlPlaneRequests"' in policy
    assert "${request_queue_arns_json}" in policy
    assert re.search(r"length\(var\.request_queue_arns\) == 8", variables), (
        "the module must refuse a list that is not the eight — a shorter one is a plane that "
        "lost its route, and the grant would simply be smaller"
    )

    # The ARNs arrive through the variable, so the only thing to assert about the TEMPLATE is
    # that it interpolates the list rather than carrying literals. What the list holds is checked
    # against the wiring below, where the values actually are — an assertion over the template
    # text here would inspect a string that structurally cannot contain an ARN.
    wiring = (INFRA / "main.tf").read_text()
    block = wiring[wiring.index("request_queue_arns = [") :]
    block = block[: block.index("]")]
    arns = re.findall(r"module\.([a-z_]+)\.([a-z_]+)", block)

    assert len(arns) == 8, f"the wiring names {len(arns)} queues, not eight"
    assert all(not output.endswith("dlq_arn") for _module, output in arns), (
        f"the grant names a dead-letter queue: {arns}"
    )
    assert '"*"' not in block, "the grant reaches a wildcard"



def test_the_lambda_environment_and_the_wiring_agree_with_the_contract_registry():
    """Three places name the eight queues, and two of the three disagreements are silent.

    The contract's registry says which variable each queue's URL arrives in; the module's
    environment block sets those variables; the root wiring says which module's output each one
    takes. A renamed variable is a ``ConfigError`` on every request to that one plane, forever,
    reported to the user as "contact the administrator". A SWAPPED pair is worse: both variables
    are set, both are read, and the messages simply go to the wrong plane's queue and dead-letter.
    Neither shows up in ``tofu validate``, in a plan, or in any other test.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a queue's variable is missing from the environment, or its wired output
        does not name the same plane.
    """
    import sys

    sys.path.insert(0, str(REPO / "lambdas" / "api"))
    from apicommon import contract

    lambda_tf = (INFRA / "modules" / "api" / "lambda.tf").read_text()
    wiring = (INFRA / "main.tf").read_text()

    for queue in contract.QUEUES:
        assigned = re.search(
            rf"^\s*{queue.env_var}\s*=\s*var\.([a-z_]+)$", lambda_tf, re.MULTILINE
        )
        assert assigned, f"{queue.env_var} is not set in the API function's environment"

        wired = re.search(
            rf"^\s*{assigned.group(1)}\s*=\s*module\.([a-z_]+)\.([a-z_]+)$",
            wiring,
            re.MULTILINE,
        )
        assert wired, f"{assigned.group(1)} is not wired at the root"

        module, output = wired.groups()
        # `shared-space` is the queue id and `shared_spaces` the module; compare on the stem both
        # agree about rather than on a mapping table that would be a third place to get it wrong.
        stem = queue.id.replace("-", "_").rstrip("s")
        assert stem in module.rstrip("s") or module.rstrip("s") in stem, (
            f"{queue.env_var} takes its value from module.{module}, which is not the "
            f"{queue.id} plane — a swapped pair sends one plane's requests to another's queue"
        )
        assert not output.endswith("dlq_url"), (
            f"{queue.env_var} names a dead-letter queue"
        )
