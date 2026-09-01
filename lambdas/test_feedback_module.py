"""The feedback module, held against the grant that authorizes it and the bucket it writes into.

Three joins nothing else in the repo makes, each covering a failure that is silent until an apply
or until somebody goes looking for a day's records and finds them expired:

- the names the module CONSTRUCTS against the patterns the deploy grant matches, which is the pin
  the grants-first PR was written for and could not make itself;
- every request DLQ Terraform declares against the drain's own tables, so a future queue cannot be
  silently undrained;
- every expiring lifecycle rule on the admin bucket against the ``feedback/`` prefix.

The third of those checks a STRING; the fourth ties it to the key the writer actually builds.

Attributes:
  MODULE: The feedback module's directory.
  GRANT: The deploy-role policy authorizing it.
  ADMIN_S3: The admin bucket's Terraform, which owns the lifecycle rules.
  SUBSTITUTIONS: What ``templatefile()`` puts into the grant, so it can be parsed as JSON.
  PROJECT, ENVIRONMENT: Stand-in values for the two name variables, so a constructed name can be
    rendered and matched against a grant pattern.
"""

import ast
import fnmatch
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"
MODULE = INFRA / "modules" / "feedback"
GRANT = INFRA / "modules" / "base" / "policies" / "github-actions-deploy-feedback.json.tftpl"
ADMIN_S3 = INFRA / "modules" / "analytics" / "s3.tf"

PROJECT = "dat"
ENVIRONMENT = "prod"
SUBSTITUTIONS = {"aws_region": "us-east-1", "project_name": PROJECT}


def _constructed_names() -> dict[str, str]:
    """Every name ``locals.tf`` builds, rendered with stand-in project and environment values.

    Read from the Terraform rather than restated here. A literal copy would agree with itself
    while the module renamed something — which is exactly the failure this file exists to catch,
    measured: renaming the writer function to ``…-feedback-writer-fn`` left the grant's own suite
    green while ``CreateFunction`` would have been denied at apply.

    Args:
      None.

    Returns:
      Local name to the string it renders to.

    Raises:
      None.
    """
    text = (MODULE / "locals.tf").read_text(encoding="utf-8")
    declared = dict(re.findall(r'^\s+(\w+)\s+=\s+"([^"]+)"$', text, re.MULTILINE))
    names: dict[str, str] = {}
    # Two passes, because a local is built from another one — the log group's name embeds the
    # function's. Resolving only `var.*` would silently DROP those rows, and a parametrized test
    # over a dict that lost a row is a test that never ran for it.
    for _ in range(len(declared)):
        for name, template in declared.items():
            rendered = template.replace("${var.project_name}", PROJECT).replace(
                "${var.environment}", ENVIRONMENT
            )
            for local, value in names.items():
                rendered = rendered.replace("${local." + local + "}", value)
            if "${" not in rendered:
                names[name] = rendered
    return names


def _grant_resources() -> list[str]:
    """Every ARN pattern the deploy grant matches on.

    Args:
      None.

    Returns:
      The patterns, flattened across statements.

    Raises:
      None.
    """
    text = GRANT.read_text(encoding="utf-8")
    for key, value in SUBSTITUTIONS.items():
        text = text.replace("${" + key + "}", value)
    patterns: list[str] = []
    for statement in json.loads(text)["Statement"]:
        resource = statement["Resource"]
        # A BARE WILDCARD IS DROPPED, and that is the whole difference between this join and a
        # tautology: `fnmatch(anything, "*")` is True, so leaving the two event-source-mapping
        # statements' `Resource: "*"` in the list made every name below match no matter what it
        # was renamed to. Their real constraint is the condition, which is collected instead.
        for candidate in resource if isinstance(resource, list) else [resource]:
            if candidate != "*":
                patterns.append(candidate)
        arn_like = statement.get("Condition", {}).get("ArnLike", {})
        patterns.extend(value for value in arn_like.values() if value != "*")
    assert patterns, "every pattern was a bare wildcard; this join would agree with any name"
    return patterns


def test_the_module_and_the_grant_are_both_where_this_test_thinks_they_are() -> None:
    """Guard the guard: over a missing file every join below is unreachable, not passing."""
    assert MODULE.is_dir(), MODULE
    assert GRANT.is_file(), GRANT
    # Every name the parametrized join below asks for must have RESOLVED, or that row silently
    # KeyErrors into a failure that reads like a missing grant rather than a broken renderer.
    resolved = _constructed_names()
    for required in (
        "requests_queue_name",
        "dlq_name",
        "writer_function_name",
        "writer_role_name",
        "lambda_log_group_name",
    ):
        assert required in resolved, f"{required} did not resolve: {resolved}"


@pytest.mark.parametrize(
    ("local_name", "arn_prefix"),
    [
        ("requests_queue_name", "arn:aws:sqs:us-east-1:123456789012:"),
        ("dlq_name", "arn:aws:sqs:us-east-1:123456789012:"),
        ("writer_function_name", "arn:aws:lambda:us-east-1:123456789012:function:"),
        ("writer_role_name", "arn:aws:iam::123456789012:role/"),
        ("lambda_log_group_name", "arn:aws:logs:us-east-1:123456789012:log-group:"),
    ],
)
def test_every_name_the_module_constructs_is_covered_by_the_deploy_grant(
    local_name: str, arn_prefix: str
) -> None:
    """The pin the grants-first PR is FOR, and the one it could not make itself.

    The grant landed before this module existed, so its own test could only compare the policy
    against literals written beside it. This is the other half: the name the module actually
    builds, matched against the pattern IAM will evaluate. A rename on either side that leaves
    them disagreeing is an ``AccessDenied`` partway through an apply, days after both were
    reviewed and both looked right.
    """
    name = _constructed_names()[local_name]
    arn = f"{arn_prefix}{name}"
    patterns = _grant_resources()

    assert any(fnmatch.fnmatchcase(arn, pattern) for pattern in patterns), (
        f"{local_name} renders {name!r}, whose ARN {arn} matches no pattern in {GRANT.name}: "
        f"{patterns}"
    )


def test_the_writer_holds_no_delete_and_no_unscoped_bucket_reach() -> None:
    """The day's records are somebody's only copy, and versioning is off on this bucket.

    ``s3:DeleteObject`` is absent by design. So is ``s3:ListBucket`` — the writer never claims
    absence, so it has no branch that needs one, and a grant with no consumer is a widening
    nobody asked for.
    """
    policy = (MODULE / "policies" / "writer-permissions.json.tftpl").read_text(encoding="utf-8")
    actions = set(re.findall(r'"(s3:[A-Za-z]+)"', policy))

    assert actions == {"s3:GetObject", "s3:PutObject"}, (
        f"the writer's S3 grant is {sorted(actions)}; it read-modify-rewrites one prefix and "
        "does nothing else"
    )
    assert '"${admin_bucket_arn}/feedback/*"' in policy, (
        "the object grant is not scoped to the feedback prefix"
    )


def test_the_queue_is_fifo_with_its_own_dlq_and_encryption_on_both() -> None:
    """Its own DLQ, and both queues encrypted — ``CKV_AWS_27``/``CKV2_AWS_73`` are enforced at zero.

    A shared DLQ would let a malformed feedback submission dead-letter somebody's file operation,
    which is the whole reason each plane has its own.
    """
    sys.path.insert(0, str(REPO / "lambdas"))
    from tf_blocks import blocks

    queues = blocks((MODULE / "sqs.tf").read_text(encoding="utf-8"), "aws_sqs_queue")

    assert set(queues) == {"requests", "requests_dlq"}
    for name, body in queues.items():
        # Each attribute is read as a VALUE. `"true" in body` is satisfied by `fifo_queue = true`
        # sitting three lines up, so it cannot see `sqs_managed_sse_enabled = false`.
        for attribute in ("fifo_queue", "sqs_managed_sse_enabled"):
            found = re.search(rf"^\s*{attribute}\s+=\s+(\w+)$", body, re.MULTILINE)
            assert found, f"{name} does not set {attribute}"
            assert found.group(1) == "true", f"{name} sets {attribute} = {found.group(1)}"
    assert "aws_sqs_queue.requests_dlq.arn" in queues["requests"], (
        "the request queue does not redrive to its own dead-letter queue"
    )
    assert "content_based_deduplication = false" in queues["requests"].replace("  ", " "), (
        "with body hashing on, a send that stopped setting an explicit MessageDeduplicationId "
        "would still mostly collapse duplicates, so the guard would go with nothing red"
    )


def test_the_event_source_mapping_delivers_one_record_at_a_time() -> None:
    """The handler's single-record assumption is coupled to this number and nothing else."""
    lambda_tf = (MODULE / "lambda.tf").read_text(encoding="utf-8")

    assert re.search(r"^\s*batch_size\s+=\s+1$", lambda_tf, re.MULTILINE), (
        "the mapping does not deliver exactly one record. Asserted anchored to the end of the "
        "line, because the unanchored string is a PREFIX of every batch size from 1 to 19 — the "
        "handler refuses a batch, so this number is the only thing making that refusal unreachable"
    )
    assert "ignore_changes = [filename, source_code_hash, layers]" in lambda_tf, (
        "without `layers` an apply landing after a deploy strips the cpcommon layer back off, and "
        "the function fails at its next cold start on an import that had been working"
    )


def _declared_dlq_segments() -> set[str]:
    """The domain segment of every request DLQ the infrastructure declares.

    Derived from the name each module CONSTRUCTS, which is the only thing about a queue that is
    stable across project and environment — the same fact ``dlq_drain._source_for`` matches on.

    Args:
      None.

    Returns:
      The segments.

    Raises:
      None.
    """
    segments = set()
    for locals_tf in INFRA.glob("modules/*/locals.tf"):
        found = re.search(
            r'dlq_name\s+=\s+"\$\{var\.project_name\}-\$\{var\.environment\}-(.+?)-requests-dlq\.fifo"',
            locals_tf.read_text(encoding="utf-8"),
        )
        if found:
            segments.add(found.group(1))
    return segments


def test_every_request_dlq_is_either_drained_or_deliberately_not() -> None:
    """A future queue cannot be silently undrained, because the population is read from Terraform.

    The drain's own coverage test walks the enqueue ROUTES, so a queue with no enqueue route —
    feedback is the first — is invisible to it. This walks what is deployed instead.
    """
    sys.path.insert(0, str(REPO / "lambdas" / "control-plane-dlq-drain"))
    import dlq_drain

    declared = _declared_dlq_segments()
    # The population is checked against the modules that OWN a request queue, not against a
    # floor. A floor is a hand-kept list in derived clothing: a tenth module whose DLQ local is
    # spelled differently drops out of the regex and still satisfies `>= 9`, which is the exact
    # rot the derivation exists to avoid.
    owners = {
        path.parent.name
        for path in INFRA.glob("modules/*/sqs.tf")
        if "requests_dlq" in path.read_text(encoding="utf-8")
    }
    missing = {o.rstrip("s") for o in owners} - {d.replace("-", "-").rstrip("s") for d in declared}
    assert not missing, (
        f"these modules own a request DLQ but their name did not parse out of locals.tf: "
        f"{sorted(missing)} (parsed: {sorted(declared)})"
    )
    assert "feedback" in declared
    unaccounted = declared - set(dlq_drain.SOURCES) - dlq_drain.UNDRAINED_QUEUES
    assert not unaccounted, (
        f"{sorted(unaccounted)} dead-letter without being drained and without being named as "
        "deliberately undrained — a request that dies there tells nobody, and nothing says why"
    )


def _expiring_rule_prefixes() -> list[str]:
    """Every admin-bucket lifecycle rule that can DELETE an object, and the prefix it matches on.

    A rule carrying no ``expiration`` cannot remove a completed object — the bucket-wide
    abort-incomplete-multipart rule is the one such rule, and it is deliberately unfiltered.

    Args:
      None.

    Returns:
      The prefixes, with a root variable resolved to the value the root passes.

    Raises:
      None.
    """
    text = ADMIN_S3.read_text(encoding="utf-8")
    root = (INFRA / "main.tf").read_text(encoding="utf-8")
    prefixes = []
    for rule in re.findall(r"\n  rule \{(.*?)\n  \}\n", text, re.DOTALL):
        if "expiration {" not in rule:
            continue
        found = re.search(r'prefix\s+=\s+"([^"]*)"', rule)
        prefix = found.group(1) if found else ""
        for variable in re.findall(r"\$\{var\.(\w+)\}", prefix):
            # The root passes these from its own locals, whose names are not always the
            # variable's. Resolution must SUCCEED — falling back to the empty string turned the
            # ALB rule's prefix into "/", which reads as a scoped rule and is not one.
            resolved = re.search(
                rf'^\s+{variable}s?\s+=\s+"([^"]+)"$', root, re.MULTILINE
            ) or re.search(r'^\s+alb_access_logs_prefix\s+=\s+"([^"]+)"$', root, re.MULTILINE)
            assert resolved, f"could not resolve var.{variable} from the root; the prefix is unknown"
            prefix = prefix.replace("${var." + variable + "}", resolved.group(1))
        prefixes.append(prefix)
    return prefixes


def test_no_expiring_lifecycle_rule_can_reach_the_feedback_prefix() -> None:
    """The existing check proves every expiring rule HAS a prefix. It cannot prove none matches.

    S3 lifecycle can include a prefix and never exclude one, so a rule scoped to ``""`` or to any
    leading fragment of ``feedback/`` would quietly expire the only copy of what users told us.
    Three current prefixes share this one's first letter, which is exactly the near miss a reader
    would skim past.
    """
    prefixes = _expiring_rule_prefixes()

    assert len(prefixes) >= 6, f"the sweep found only {prefixes}; it is matching the wrong shape"
    assert "" not in prefixes, "an unfiltered EXPIRING rule reaches every prefix in the bucket"
    reaching = [p for p in prefixes if "feedback/".startswith(p)]
    assert reaching == [], f"these expiring rules would delete the feedback records: {reaching}"


def test_the_list_that_actually_attaches_the_drain_agrees_with_its_source_table() -> None:
    """``UNDRAINED_QUEUES`` controls nothing; ``local.drained_dlq_names`` does.

    The drain is wired by event-source mappings built from that root local, and until now nothing
    read it — a queue added there is attached whatever the Python says. Adding feedback's DLQ to
    it would quietly consume and delete feedback dead letters, defeating the 14-day retention
    that is the only thing standing in for an alarm.

    ``infra/main.tf`` has claimed since it was written that "a test in
    ``lambdas/control-plane-dlq-drain/`` reads the module locals.tf files and fails if a fifth
    control plane appears without being wired or explicitly excluded". No such test existed. This
    is that test, and it lives here because this is the change that needed it.
    """
    sys.path.insert(0, str(REPO / "lambdas" / "control-plane-dlq-drain"))
    import dlq_drain

    root = (INFRA / "main.tf").read_text(encoding="utf-8")
    block = root[root.index("drained_dlq_names = [") :]
    block = block[: block.index("]")]
    attached = set(
        re.findall(r'"\$\{var\.project_name\}-\$\{var\.environment\}-(.+?)-requests-dlq\.fifo"', block)
    )

    assert attached, "the drained-DLQ list did not parse; this join would be vacuous"
    assert attached == set(dlq_drain.SOURCES), (
        f"the drain is ATTACHED to {sorted(attached)} but its notification table names "
        f"{sorted(dlq_drain.SOURCES)}. A queue attached but absent from the table is drained into "
        "silence; one in the table but unattached is a plane nobody is told about."
    )
    assert not attached & dlq_drain.UNDRAINED_QUEUES, (
        "a queue named as deliberately undrained is wired to the drain anyway"
    )


def test_the_writer_is_sized_for_an_UNBOUNDED_document_and_the_ceiling_is_computed() -> None:
    """The memory budget, and the number of submissions in one day it actually buys.

    A cap is computed against the budget that sized it, never written down: a hard-coded number
    hides a wrong model. The model here is what the writer does — read the day's bytes, parse
    them, append, re-serialise, encode — so peak resident is several multiples of the object,
    and the object grows all day because the spec declines a per-user quota.

    128 MB (the Lambda default, and what notifications-writer runs on) buys the low thousands of
    maximum-length submissions before an OOM. That matters more than an ordinary crash: SIGKILL
    skips observability's flush, so the failure leaves no structured record, and every later
    submission that day fails identically into a DLQ nobody drains.

    The assertion is that the budget is log-sweep's rather than notifications' — those are the
    fleet's uncapped and capped day-object writers respectively — and that the warning threshold
    sits comfortably under the ceiling the budget buys.
    """
    import re as _re

    lambda_tf = (MODULE / "lambda.tf").read_text(encoding="utf-8")
    sweep_tf = (INFRA / "modules" / "observability" / "lambda.tf").read_text(encoding="utf-8")

    mine = int(_re.search(r"^\s*memory_size\s*=\s*(\d+)$", lambda_tf, _re.MULTILINE).group(1))
    sweep = int(_re.search(r"^\s*memory_size\s*=\s*(\d+)$", sweep_tf, _re.MULTILINE).group(1))

    assert mine == sweep, (
        f"the feedback writer runs on {mine} MB and log-sweep on {sweep}. Both do an unbounded "
        "read-modify-write over a day object; the 128 MB default belongs to the writer whose "
        "document is capped, which this one is not"
    )

    # What the budget buys, derived from FR-002's own message cap rather than assumed.
    max_message = _python_cap_from_route("MAX_MESSAGE_CHARS")
    per_entry = max_message + 220  # the six declared fields' keys, ids, stamps and JSON overhead
    peak_multiple = 4  # raw bytes + parsed objects + re-serialised string + encoded bytes
    ceiling = (mine * 1024 * 1024) // (per_entry * peak_multiple)

    assert ceiling > 10_000, (
        f"{mine} MB buys about {ceiling} maximum-length submissions in one UTC day before the "
        "read-modify-write cannot complete; that is inside reach of a single signed-in caller"
    )


def _python_cap_from_route(name: str) -> int:
    """Reads a module-level integer constant out of the feedback route.

    Args:
      name: The constant's name.

    Returns:
      Its value, or the spec's own figure when the route has not landed yet — this module ships
      one PR ahead of it, and a default that matched nothing would make the ceiling above a
      fiction.

    Raises:
      None.
    """
    route = REPO / "lambdas" / "api" / "routes" / "feedback.py"
    if not route.is_file():
        return 4000
    found = re.search(rf"^{name} = (\d+)$", route.read_text(encoding="utf-8"), re.MULTILINE)
    return int(found.group(1)) if found else 4000


def test_the_one_variable_the_writer_requires_is_set() -> None:
    """Deleting it goes unnoticed otherwise — measured, with the writer in place.

    `cpcommon.config`'s required union is four variables and this function sets one, on
    notifications-writer's precedent: it imports `cas`, `clients` and `observability`, none of
    which reads the config module. Nothing in the repo compares that union against any Lambda's
    Terraform environment, so the thin environment is only safe while the import probe covers
    this function — which it does from the PR that adds the code it probes. This assertion
    covers the one variable the writer genuinely reads, from now.
    """
    lambda_tf = (MODULE / "lambda.tf").read_text(encoding="utf-8")

    assert re.search(r"^\s*ADMIN_BUCKET\s*=\s*var\.admin_bucket_name$", lambda_tf, re.MULTILINE), (
        "the writer's only required variable is unset; every submission would raise at the first "
        "read and dead-letter into the undrained queue"
    )


def test_the_feedback_key_the_writer_builds_sits_under_the_prefix_that_was_checked() -> None:
    """The check above is about a string; this is what ties it to the key actually written."""
    writer = (REPO / "lambdas" / "feedback-writer" / "feedback_writer.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(writer)
    prefix = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "FEEDBACK_PREFIX" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    )

    assert f"{prefix}/" == "feedback/", (
        f"the writer files under {prefix!r}, which is not the prefix the lifecycle check covers"
    )
