"""Who may write a control-plane request queue, enumerated from the filesystem.

The access model here is identity-based and nothing else: there is no ``aws_sqs_queue_policy``
anywhere in the tree, so "only the API may write" is achieved by adding one grant and removing
eight. That makes the enumeration below the whole guard — a hand-kept list is exactly what would
miss the next one — which is not hypothetical: feedback IS that queue, and it arrived without
being a plane.

Attributes:
  REPO: The repository root.
  INFRA: The IaC tree.
  QUEUE_MODULES: The owners of a request queue, enumerated from the filesystem: each plane whose
    root file calls the control-plane module, which creates its queue, plus every module with its
    own request queue — feedback, which is not a plane (one verb and no state machine) but owns a
    request queue on exactly these terms, and notifications.
  EXPECTED_QUEUE_MODULES: The count measured when feedback landed, as a tripwire on the glob
    rather than as the list itself. A glob that found nothing would make every sweep here
    vacuously clean.
  NOTIFYING_ROLES: Every execution role that sends a notification, which this change must leave
    holding its grant.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"

QUEUE_MODULES = sorted(
    [
        path.stem.removeprefix("plane-")
        for path in INFRA.glob("plane-*.tf")
        if 'source = "./modules/control-plane"' in path.read_text()
    ]
    + [path.parent.name for path in INFRA.glob("modules/*/sqs.tf") if "requests" in path.read_text()]
)

EXPECTED_QUEUE_MODULES = 10

NOTIFYING_ROLES = (
    "shared-spaces",
    "table-builder",
    "table-share",
    "data-quality",
    "file-send",
    "archive",
    "file-ops",
    "results-conversion",
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


def test_the_enumeration_reaches_every_queue_it_claims_to():
    """A glob that found nothing would make every sweep below vacuously clean.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the queue modules are not the ones this arc knows about.
    """
    assert len(QUEUE_MODULES) == EXPECTED_QUEUE_MODULES, QUEUE_MODULES
    assert "feedback" in QUEUE_MODULES
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
        "a user-scoped session that can write one can forge the actor the planes are about to trust."
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
        templates = [
            *INFRA.glob(f"planes/{role}/*.json.tftpl"),
            *INFRA.glob(f"modules/{role}/policies/*.json.tftpl"),
        ]
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


def test_the_api_grant_names_every_queue_and_no_wildcard():
    """One grant, one ARN per queue, rendered from a list the module refuses at any other length.

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
    assert re.search(
        rf"length\(var\.request_queue_arns\) == {EXPECTED_QUEUE_MODULES}", variables
    ), (
        "the module must refuse a list of any other length — a shorter one is a queue that lost "
        "its route, and the grant would simply be smaller"
    )

    # The ARNs arrive through the variable, so the only thing to assert about the TEMPLATE is
    # that it interpolates the list rather than carrying literals. What the list holds is checked
    # against the wiring below, where the values actually are — an assertion over the template
    # text here would inspect a string that structurally cannot contain an ARN.
    wiring = (INFRA / "main.tf").read_text()
    block = wiring[wiring.index("request_queue_arns = [") :]
    block = block[: block.index("]")]
    arns = re.findall(r"module\.([a-z_]+)\.([a-z_]+)", block)

    assert len(arns) == EXPECTED_QUEUE_MODULES, (
        f"the wiring names {len(arns)} queues, not {EXPECTED_QUEUE_MODULES}"
    )
    assert all(not output.endswith("dlq_arn") for _module, output in arns), (
        f"the grant names a dead-letter queue: {arns}"
    )
    assert '"*"' not in block, "the grant reaches a wildcard"



def test_the_lambda_environment_and_the_wiring_agree_with_the_contract_registry():
    """Three places name the queues, and two of the three disagreements are silent.

    The contract's registry says which variable each queue's URL arrives in; the module's
    environment block sets those variables; the root wiring says which module's output each one
    takes. A renamed variable is a ``ConfigError`` on every request to that one plane, forever,
    reported to the user as "contact the administrator". A SWAPPED pair is worse: both variables
    are set, both are read, and the messages simply go to the wrong plane's queue instead of their
    own. Neither shows up in ``tofu validate``, in a plan, or in any other test.

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


def test_the_one_queue_outside_the_contract_registry_is_wired_just_as_carefully():
    """Feedback resolves its URL through its own accessor, so the sweep above cannot see it.

    ``contract.QUEUES`` is the registry the ten ENQUEUE ROUTES resolve against, guarded for set
    equality with them in both directions. The feedback route is not one of those ten — its
    message shape is not the family's — so registering its queue would mean loosening that guard
    with a hand-maintained exemption. It reads ``FEEDBACK_QUEUE_URL`` through
    ``apicommon.config.feedback_queue_url`` instead.

    That trade costs exactly one thing: the swapped-pair guard above stops covering it. This is
    that coverage, written out. A renamed variable is a ``ConfigError`` on every submission
    forever; a wired-to-the-wrong-module one sends every submission to another plane's queue.
    Neither shows up in ``tofu validate``, in a plan, or anywhere else. On the wrong queue a
    submission never reaches the feedback writer: a Pipe plane refuses it as unauthorized, because
    it carries no identity block, and the notifications writer refuses it as an unknown action and
    dead-letters it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the variable is unset in the function's environment, unwired at the root,
        wired to another module, or pointed at a dead-letter queue.
    """
    import sys

    sys.path.insert(0, str(REPO / "lambdas" / "api"))
    from apicommon import config, contract

    assert "feedback" not in {queue.id for queue in contract.QUEUES}, (
        "feedback joined the registry, so this test now duplicates the sweep above rather than "
        "covering the gap it was written for"
    )
    assert "FEEDBACK_QUEUE_URL" in config.feedback_queue_url.__code__.co_consts, (
        "the accessor no longer names FEEDBACK_QUEUE_URL, so the wiring below pins nothing"
    )

    lambda_tf = (INFRA / "modules" / "api" / "lambda.tf").read_text()
    wiring = (INFRA / "main.tf").read_text()

    assigned = re.search(
        r"^\s*FEEDBACK_QUEUE_URL\s*=\s*var\.([a-z_]+)$", lambda_tf, re.MULTILINE
    )
    assert assigned, "FEEDBACK_QUEUE_URL is not set in the API function's environment"

    wired = re.search(
        rf"^\s*{assigned.group(1)}\s*=\s*module\.([a-z_]+)\.([a-z_]+)$", wiring, re.MULTILINE
    )
    assert wired, f"{assigned.group(1)} is not wired at the root"

    module, output = wired.groups()
    assert module == "feedback", (
        f"FEEDBACK_QUEUE_URL takes its value from module.{module}, so every submission would go "
        "to another plane's queue and never reach the feedback writer"
    )
    assert not output.endswith("dlq_url"), "FEEDBACK_QUEUE_URL names a dead-letter queue"
