"""Every ``lambda:InvokeFunction`` the deploy role holds, swept against the whole fleet.

``test_backfill_grant_population.py`` asserts the same fence for ONE statement, selected by its
Sid, against ONE plane. Both halves of that shape stop working as soon as a second invoke
statement exists: a wider grant under a different Sid leaves it green, and a wider grant on a
DIFFERENT plane was never in its scope at all. This module is the fleet-wide half.

The fence generalises the shared-spaces one, and the reason generalises with it: **an invoke grant
on a verb is an invoke grant on the delete cascade.** A verb's only safety is the state machine's
ordering — archive's `delete-source` runs after a state proves every object was copied, and file-ops'
after a confirmed plan — so a direct invoke bypasses the guarantee entirely. That reasoning is not
special to shared spaces, and neither is this sweep.

The whole assertion is one set equality, in BOTH directions: the functions reachable by an invoke
grant are exactly the declared probe targets. A wider pattern makes something extra reachable and
fails; a probe target that loses its grant fails too.

**There is deliberately no automated "is this verb destructive" test, and the reason is worth
keeping.** One was written and thrown away: it swept each function's own modules for a mutating
call, which reports `archive-delete-source` as harmless — that verb's deletion is
`arcommon.delete.delete_keys`, and shared-space's is `teardown.delete_shared_prefix`, both in a
domain layer the sweep never opened. A detector that clears the delete cascade is worse than none,
because it reads as coverage. Two routed states are NOT what distinguishes a safe target either:
every plane's `validate-authorize` is routed, so a "nothing routed" rule forbids the very probes
FR-006 requires. What is left is the set equality above, plus a written reason per target — which
is a human judgement, stated where it can be read and argued rather than implied by a pattern.

Attributes:
  POLICY_DIR: Every deploy-role policy template, inline and managed alike.
  PROJECT: The rendered project name, matching the deployed function names.
  ENVIRONMENT: The rendered environment segment.
  PROBE_TARGETS: The functions CI is allowed to invoke, and why each is safe. SPEC-213 FR-006
    invokes one function per plane plus the standalone functions against the deployed fleet, to
    catch a cold-start import failure that only the deployed artefact knows about.
"""

import json
import pathlib
import re

import fleet
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "infra" / "modules" / "base" / "policies"
BASE_IAM = ROOT / "infra" / "modules" / "base" / "iam.tf"
LAMBDA_DIRS = ROOT / "lambdas"

PROJECT = "dat"
#: The placeholder account these tests build their probe ARNs with. The templates pin a
#: VARIABLE, so this need not be the real account — but it must be the same value this file
#: renders `${account_id}` as, or every probe ARN lands in a different account from the
#: pattern it is checked against and the coverage assertions all pass vacuously.
ACCOUNT_ID = "123456789012"
ENVIRONMENT = "prod"

#: Every function CI may invoke, mapped to what it actually does on the probe payload. Six of them
#: ARE routed by a state machine — every `validate-authorize` is — which is why "nothing routed" is
#: not the rule; see the module docstring. What each entry claims is inertness on the payload
#: FR-006 sends, and each was RUN to establish it rather than reasoned about, because these
#: sentences are the only thing standing where an automated detector could not.
#: `shared-space-backfill-ever-active` is the plane's probe deliberately: it is NOT a verb, it
#: already carried an invoke grant, and it shares the verbs' environment block — which is the thing
#: a cold-start probe is actually testing, since a plane's verbs differ from one another only by
#: command.
PROBE_TARGETS = {
    "archive-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "data-quality-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "file-ops-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "file-send-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "results-conversion-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "table-builder-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "table-share-validate-authorize": "TerminalError at events.parse_sqs_request, zero AWS calls",
    "shared-space-backfill-ever-active": "mode defaults to report, which writes nothing",
    "shared-space-transfer-reader": "GRANT DELIBERATELY ABSENT — see the owed row",
    "api": "authentication runs first, so an unsigned probe is 401 before any route",
    "pre-signup": "refuses a malformed Cognito event",
    "post-confirmation": "returns the event unchanged on an unrecognised triggerSource",
    "notifications-writer": "no Records is no work",
    "feedback-writer": "no Records is no work",
    "user-directory-build": "rebuilds from S3, idempotent, already on a schedule",
    "log-sweep": "sweeps its own queue; already on a schedule, so a probe is that firing early",
    "control-plane-dlq-drain": "probed with {'Records': []}, which returns before the sweep",
}

#: The one entry above that is named for documentation and is NOT granted. The transfer reader
#: sweeps the operator inbox and ENQUEUES onto the plane's own queue, so an empty payload is not
#: inert by construction — only by the inbox happening to be empty. FR-006's third criterion sends
#: it to `docs/testing/owed.md` instead of buying a grant for it.
UNGRANTED_BY_DESIGN = {"shared-space-transfer-reader"}


def _rendered(path):
    """Substitutes a policy template's interpolations so the document parses.

    One of them (``$${aws_region}``) carries a closing brace, so slicing the raw text on a brace
    truncates a statement before its resource — the failure that made
    ``test_backfill_grant_population.py`` parse rather than slice, where the assertion then passed
    on a policy that said nothing.

    Args:
      path: The ``.tftpl`` policy template.

    Returns:
      The rendered document text.

    Raises:
      None.
    """
    text = path.read_text(encoding="utf-8")
    text = text.replace("${aws_region}", "us-east-1")
    text = text.replace("${project_name}", PROJECT)
    text = text.replace("${environment}", ENVIRONMENT)
    text = text.replace("${account_id}", ACCOUNT_ID)
    return re.sub(r"\$\{\w+\}", "placeholder", text)


def _attached_templates():
    """Every policy template actually attached to the deploy role, read from ``iam.tf``.

    NOT a filename glob. A glob is a population nobody maintains, and a second inline
    ``aws_iam_role_policy`` whose template is named anything else escapes it entirely — measured,
    not assumed: an off-glob inline policy granting invoke on the whole fleet passed the whole
    suite. The role's attachments are the population, so a policy that reaches the role reaches
    this sweep however its file is named.

    Args:
      None.

    Returns:
      The template paths attached to the deploy role.

    Raises:
      AssertionError: When ``iam.tf`` attaches a template that is not on disk, or attaches an
        AWS-managed policy ARN, whose contents this sweep cannot read.
    """
    text = BASE_IAM.read_text(encoding="utf-8")

    managed = re.findall(r'policy_arn\s*=\s*"(arn:aws:iam::aws:policy/[^"]+)"', text)
    assert managed == [], (
        f"the deploy role attaches AWS-managed policies {managed}, whose grants this sweep cannot "
        "read — an invoke grant could arrive inside one and be invisible here"
    )

    paths = []
    for name in re.findall(r'templatefile\(\s*"\$\{path\.module\}/(policies/[^"]+)"', text):
        path = BASE_IAM.parent / name
        assert path.is_file(), f"iam.tf renders {name}, which is not on disk"
        if path.name.startswith("github-actions-deploy"):
            paths.append(path)
    return sorted(set(paths))


def _policies():
    """Every attached deploy-role policy, parsed.

    Args:
      None.

    Returns:
      Pairs of template name and parsed policy document.

    Raises:
      AssertionError: When a template does not parse once rendered.
    """
    documents = []
    for path in _attached_templates():
        try:
            documents.append((path.name, json.loads(_rendered(path))))
        except json.JSONDecodeError as error:  # pragma: no cover - a broken template
            raise AssertionError(f"{path.name} does not parse once rendered: {error}") from error
    return documents


def _iam_pattern(value):
    """Compiles an IAM pattern into the matcher IAM itself applies.

    ``fnmatch`` is deliberately not used: it gives ``[`` and ``]`` character-class meaning that IAM
    does not, which is how a guard of this shape becomes tautological rather than failing. Only
    ``*`` (zero or more) and ``?`` (exactly one) are wildcards; everything else is literal.

    Used for BOTH resources and actions. An action is a pattern too — IAM honours
    ``lambda:Invoke*`` — and treating the action as a literal string is how a wide grant becomes
    invisible to a sweep that reads only the resource.

    Args:
      value: One ``Action`` or ``Resource`` value from a policy statement.

    Returns:
      A compiled, fully anchored, case-insensitive regular expression.

    Raises:
      None.
    """
    pattern = "".join(
        ".*" if part == "*" else "." if part == "?" else re.escape(part)
        for part in re.split(r"([*?])", value)
    )
    return re.compile(f"^{pattern}$", re.IGNORECASE)


def _grants_invoke(statement):
    """Whether a statement's actions reach ``lambda:InvokeFunction``.

    Matched as a pattern rather than by string membership. ``lambda:Invoke*``, ``lambda:In*`` and
    ``LAMBDA:INVOKEFUNCTION`` all authorize the call and none of them equals the literal — a sweep
    that misses them reports a clean fleet while CI can invoke a verb.

    Args:
      statement: One policy statement.

    Returns:
      True when the statement's actions authorize ``lambda:InvokeFunction``.

    Raises:
      AssertionError: When the statement uses ``NotAction``, whose reach this sweep cannot compute
        and must not silently read as "grants nothing".
    """
    for key in ("NotAction", "NotResource"):
        assert key not in statement, (
            f"statement {statement.get('Sid', '<unnamed>')} uses {key}, whose reach this sweep "
            "cannot compute — it would be collected as granting NOTHING while granting nearly "
            "everything. An Allow on lambda:InvokeFunction with NotResource reaches every "
            "function in the account bar one. Rewrite it as an explicit list, or extend this "
            "sweep deliberately."
        )
    actions = statement.get("Action", [])
    actions = [actions] if isinstance(actions, str) else actions
    return any(_iam_pattern(action).match("lambda:InvokeFunction") for action in actions)


def _invoke_statements():
    """Every statement that authorizes an invoke, with the policy it came from.

    Args:
      None.

    Returns:
      Triples of template name, Sid and the list of granted resource patterns.

    Raises:
      None.
    """
    found = []
    for name, document in _policies():
        for statement in document["Statement"]:
            if statement.get("Effect") != "Allow" or not _grants_invoke(statement):
                continue
            resources = statement.get("Resource", [])
            resources = [resources] if isinstance(resources, str) else resources
            found.append((name, statement.get("Sid", "<unnamed>"), resources))
    return found


def _fleet():
    """Every deployed function name, derived from the Terraform that declares the fleet.

    ``test_image_layout.py`` holds that derivation equal to the function directories on disk, so
    this needs no second population of its own.

    Args:
      None.

    Returns:
      The deployed function names.

    Raises:
      None.
    """
    table = set(fleet.function_names(ROOT))
    on_disk = {
        d.name for d in LAMBDA_DIRS.iterdir()
        if d.is_dir() and any(d.glob("*.py")) and not d.name.startswith((".", "docker"))
        and not d.name.endswith("-common") and d.name != "fixtures"
    }
    # The UNION of two independently-derived populations, not one checked against the other. A
    # subset assertion was tried and is wrong in the direction that matters: losing a name from
    # the declaration keeps `declared <= on_disk` true, and the fleet then no longer contains the
    # function a widened grant reaches — the sweep passes having stopped looking. A union cannot
    # shrink unless BOTH sources lose the same name.
    return {f"{PROJECT}-{ENVIRONMENT}-{name}" for name in table | on_disk}


def _reachable():
    """Every fleet function any invoke grant can reach.

    Args:
      None.

    Returns:
      A mapping of deployed function name to the ``(policy, Sid)`` pairs that reach it.

    Raises:
      None.
    """
    reached = {}
    deployed = _fleet()
    for name, sid, resources in _invoke_statements():
        matchers = [_iam_pattern(resource) for resource in resources]
        for function in deployed:
            arn = f"arn:aws:lambda:us-east-1:123456789012:function:{function}"
            # A version- or alias-qualified resource authorizes invoking the function just as an
            # unqualified one does, so both spellings are tested. Matching only the bare ARN reads
            # `…:function:NAME:*` as reaching nothing.
            candidates = (arn, f"{arn}:$LATEST", f"{arn}:live")
            if any(m.match(c) for m in matchers for c in candidates):
                reached.setdefault(function, []).append((name, sid))
    return reached


def test_the_sweep_found_the_fleet_and_the_grants():
    """Controls on both collectors, and a lower bound the strict matcher cannot slip past.

    The bound is a LITERAL read of the same documents: any Allow statement whose action list
    contains the exact string ``lambda:InvokeFunction``. Every such statement must be in the
    strict set, so the pattern matcher can only ever find MORE — it cannot quietly find fewer.
    Deliberately a subset rather than an equality: the strict matcher also catches
    ``lambda:Invoke*`` and ``lambda:*``, which a literal read does not, and demanding equality
    would redden on a correct grant. It filters on ``Effect`` for the same reason — an added
    ``Deny`` on invoke is a safety-increasing edit and must not fail a fence.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a collector is empty, or a literal invoke grant escaped the matcher.
    """
    deployed = _fleet()
    strict = {(name, sid) for name, sid, _ in _invoke_statements()}

    assert len(deployed) >= 80, (
        f"only {len(deployed)} functions read out of the Terraform fleet"
    )
    assert strict, "no invoke statements collected; every assertion below would be vacuous"

    literal = set()
    for name, document in _policies():
        for statement in document["Statement"]:
            if statement.get("Effect") != "Allow":
                continue
            actions = statement.get("Action", [])
            actions = [actions] if isinstance(actions, str) else actions
            if "lambda:InvokeFunction" in actions:
                literal.add((name, statement.get("Sid", "<unnamed>")))

    assert literal, "no statement names lambda:InvokeFunction literally; the bound is vacuous"

    # Statement identity is not enough: a helper that reads only a statement's FIRST resource
    # collects the right statements and hides a wide second element. So the resources are counted
    # here, independently of the helper that collects them.
    declared = 0
    for _, document in _policies():
        for statement in document["Statement"]:
            if statement.get("Effect") != "Allow" or not _grants_invoke(statement):
                continue
            resources = statement.get("Resource", [])
            declared += len([resources] if isinstance(resources, str) else resources)
    collected = sum(len(resources) for _, _, resources in _invoke_statements())
    assert collected == declared, (
        f"the sweep collected {collected} invoke resources but the documents declare {declared}; "
        "a resource nobody swept is a grant nobody checked"
    )

    escaped = sorted(literal - strict)
    assert escaped == [], (
        f"statements naming lambda:InvokeFunction outright that the pattern matcher did not "
        f"collect: {escaped}. The fence rests on the matcher, so it may find more than a literal "
        "read, never fewer."
    )


def test_the_matcher_is_not_tautological():
    """Positive and negative controls on ``_iam_pattern`` itself, for resources and for actions.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the matcher does not behave as IAM does.
    """
    assert _iam_pattern("dat-*-archive-*").match("dat-prod-archive-delete-source")
    assert not _iam_pattern("dat-*-archive-validate-authorize").match("dat-prod-archive-delete-source")
    assert _iam_pattern("*").match("anything-at-all")
    # `?` is one character to IAM. Deleting its branch passed every other control here, so it
    # gets one of its own: `archive-??????-source` is how a widening hides from a `*`-only reader.
    assert _iam_pattern("dat-prod-archive-??????-source").match("dat-prod-archive-delete-source")
    assert not _iam_pattern("dat-prod-archive-?-source").match("dat-prod-archive-delete-source")
    assert not _iam_pattern("dat-[a-z]").match("dat-p")  # `[` is literal to IAM
    # Action forms that authorize the call and are not the literal string.
    for action in ("lambda:InvokeFunction", "lambda:Invoke*", "lambda:*", "*", "LAMBDA:INVOKEFUNCTION"):
        assert _iam_pattern(action).match("lambda:InvokeFunction"), action
    assert not _iam_pattern("lambda:UpdateFunctionCode").match("lambda:InvokeFunction")


def test_the_invoke_grants_reach_exactly_the_probe_targets():
    """Set equality, both directions, over the whole fleet.

    Both directions matter and they catch different things. Something extra reachable is a grant
    nobody narrowed — appending ``lambda:InvokeFunction`` to a plane's existing ``*LambdasManage``
    statement, whose Resource is already the whole plane, is one line and reaches that plane's
    delete verbs. A probe target that is no longer reachable is a cold-start check that will fail
    in CI against a function it cannot call.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the reachable set is not exactly the granted probe set.
    """
    expected = {
        f"{PROJECT}-{ENVIRONMENT}-{name}"
        for name in PROBE_TARGETS
        if name not in UNGRANTED_BY_DESIGN
    }
    reached = _reachable()

    extra = sorted(set(reached) - expected)
    assert extra == [], (
        "invoke grants reach functions that are not probe targets: "
        + "; ".join(f"{f} via {reached[f]}" for f in extra)
        + ". An invoke grant on a verb is an invoke grant on the delete cascade — narrow the "
        "pattern, or add the function to PROBE_TARGETS with the reason it is safe to invoke."
    )
    missing = sorted(expected - set(reached))
    assert missing == [], f"probe targets no grant reaches: {missing}"


@pytest.mark.parametrize(
    ("name", "sid", "resources"), _invoke_statements(), ids=lambda v: str(v)[:60]
)
def test_no_invoke_grant_is_unscoped(name, sid, resources):
    """A bare wildcard reaches every function in the account, probe list or no probe list.

    Args:
      name: The template the statement came from.
      sid: The statement's Sid.
      resources: Its granted resource patterns.

    Returns:
      None.

    Raises:
      AssertionError: When a pattern is a bare wildcard or names no function.
    """
    for resource in resources:
        assert resource != "*", f"{name}/{sid} grants invoke on every function in the account"
        assert ":function:" in resource, f"{name}/{sid} grants invoke on {resource}, not a function"
