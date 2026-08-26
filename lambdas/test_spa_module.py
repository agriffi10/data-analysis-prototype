"""The container runtime, where almost every mistake applies green.

Three classes of failure live in this module, and none of them shows up in a plan.

**The ones that produce a container that never starts.** A mount set missing one of the two
writable paths under ``readonlyRootFilesystem``, a task security group with no egress to the S3
gateway endpoint's prefix list, a missing log group. Each reports as a generic ECS event —
and ``ResourceInitializationError`` is indistinguishable, during the one verification this arc
turns on, from the ``CannotPullContainerError`` the no-NAT design is being tested by.

**The ones that work and are wrong.** ``appUrl`` carrying the CloudFront origin (it fails only
in a browser, only on a fresh sign-in); a load balancer in the private subnets; a merged task
and execution role, which applies green forever because nothing the container does would fail.

**The ones that are invisible until something else needs them.** Rollback enabled on the
circuit breaker, mutable image tags, a ``Deny`` in the admin bucket's first policy — which
would stop the deploy role's own refresh read and make every later plan propose destroying a
bucket holding the structured logs.

**What this file cannot prove.** These are text assertions over Terraform. That an image pull
completes with no NAT, that the certificate attaches, that the redirect answers, that a task
reaches ``healthy`` — all live checks, owned by the acceptance script.

Attributes:
  INFRA: The IaC tree.
  SPA: The container-platform module.
  ROOT_MAIN: The composition that builds the runtime-configuration map and wires the module.
  ROOT_VARIABLES: Where ``spa_desired_count``'s default lives.
  NETWORK_ENDPOINTS: The endpoints file that owns the reciprocal ingress rule this module must
    not re-declare.
  SPEC_193: This module's own spec, whose mounted-pair criterion is the other half of the
    agreement the mount assertion reads.
  SPEC_194: The image spec, whose writable-path criterion this module's mounts must equal.
  WRITABLE_PATHS: The two paths, named here as the third copy on purpose — the assertion is an
    agreement between two specs and a configuration, so a shared constant would prove nothing.
  ALLOWED_TLS_POLICIES: TLS 1.3-capable ALB policies at or stricter than the spec's.
"""

import json
import pathlib
import re

from tf_blocks import blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
SPA = INFRA / "modules" / "spa"
ROOT_MAIN = INFRA / "main.tf"
ROOT_VARIABLES = INFRA / "variables.tf"
NETWORK_ENDPOINTS = INFRA / "modules" / "network" / "endpoints.tf"
SPEC_193 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "specs"
    / "SPEC-193-network-compute-and-the-front-door.md"
)
SPEC_194 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "specs"
    / "SPEC-194-the-spa-container.md"
)

WRITABLE_PATHS = ("/tmp", "/var/cache/nginx")  # noqa: S108 — container paths, not host temp files

ALLOWED_TLS_POLICIES = frozenset(
    {
        "ELBSecurityPolicy-TLS13-1-2-2021-06",
        "ELBSecurityPolicy-TLS13-1-2-Res-2021-06",
        "ELBSecurityPolicy-TLS13-1-3-2021-06",
    }
)


def _source() -> str:
    """Concatenates every Terraform file in the container-platform module.

    Args:
      None.

    Returns:
      The module's whole source, comments included.

    Raises:
      None.
    """
    return "\n".join(path.read_text() for path in sorted(SPA.glob("*.tf")))


def _source_without_comments() -> str:
    """The module's source with comment lines dropped.

    Naming the thing you forbid is not the same as doing it, and this module explains at length
    why it does NOT use linuxParameters.tmpfs, the awslogs driver's create-group option or the
    legacy load-balancer service account — a raw scan reads those sentences as violations.

    Args:
      None.

    Returns:
      The source with every full-line comment removed.

    Raises:
      None.
    """
    return "\n".join(line for line in _source().splitlines() if not line.lstrip().startswith("#"))


def _container_definition() -> str:
    """Returns the single container definition's body from the task definition.

    Args:
      None.

    Returns:
      The text between ``container_definitions = jsonencode([`` and its closing bracket.

    Raises:
      AssertionError: When the block cannot be found, so no assertion below runs vacuously.
    """
    text = _source()
    start = text.find("container_definitions = jsonencode([")
    assert start > -1, "No container_definitions block — the parse went trivial."
    end = text.find("\n  ])", start)
    assert end > start, "The container_definitions block did not close where expected."
    return text[start:end]


def _root_module_block(name: str) -> str:
    """Returns one ``module "<name>" {…}`` block from the root composition.

    Args:
      name: The module's label.

    Returns:
      The block's body.

    Raises:
      AssertionError: When the block is absent, so no assertion on it runs vacuously.
    """
    text = ROOT_MAIN.read_text()
    start = text.find(f'module "{name}" {{')
    assert start > -1, f'No module "{name}" block at root.'
    end = text.find("\n}", start)
    assert end > start, f'module "{name}" does not close where expected.'
    return text[start:end]


def test_the_module_source_was_found() -> None:
    """Guards every assertion below: an empty read agrees with everything.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the module's files are missing or unexpectedly small.
    """
    text = _source()
    assert len(text) > 5000, f"Read only {len(text)} characters of {SPA} — wrong path?"
    assert 'resource "aws_ecs_service"' in text


def test_the_cluster_reports_container_insights() -> None:
    """The scanner criterion puts this among the fixes, not the dispositions.

    It is also the only view of task-level CPU and memory a design with no host access has. The
    scanner check that would otherwise catch a regression is not yet on the enforce list, so the
    assertion lives here until the re-baseline puts it there too.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When insights are off or the setting is absent.
    """
    cluster = blocks(_source(), "aws_ecs_cluster")["spa"]
    setting = re.search(r'name\s*=\s*"containerInsights"\s*\n\s*value\s*=\s*"([^"]+)"', cluster)
    assert setting, f"No containerInsights setting on the cluster: {cluster}"
    assert setting.group(1) == "enabled", setting.group(1)


def test_the_task_role_and_the_execution_role_are_distinct_and_the_task_role_holds_nothing() -> None:
    """The container makes no AWS call, so its own identity carries no policy.

    Merging the two roles applies green forever — nothing the container does would fail — and
    hands the running container the registry pull and the log write for no reason.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either role is missing, or when anything attaches a policy to the
        task role.
    """
    text = _source()
    roles = blocks(text, "aws_iam_role")
    assert {"task", "task_execution"} <= set(roles), f"Expected two roles, found {sorted(roles)}"

    # EVERY spelling of the reference, not the two that came to mind: `role` also takes
    # `.name`, which is the most ordinary way to write it.
    task_role = re.compile(r"aws_iam_role\.task\.(id|arn|name)\b")
    policies = blocks(text, "aws_iam_role_policy")
    for name, body in policies.items():
        assert not task_role.search(body), (
            f"aws_iam_role_policy.{name} attaches a policy to the TASK role. The container makes "
            "no AWS call; its role holds nothing at all."
        )

    # And an inline_policy or a managed_policy_arns list inside the role itself, which no
    # separate resource would reveal.
    assert "inline_policy" not in roles["task"], roles["task"]
    assert "managed_policy_arns" not in roles["task"], roles["task"]

    assert "aws_iam_role_policy_attachment" not in _source_without_comments(), (
        "A managed-policy attachment appeared. The execution role uses a scoped inline document "
        "on purpose: AmazonECSTaskExecutionRolePolicy grants the pull on every repository in the "
        "account and hides that breadth behind an attachment the rendered-plan scan cannot read."
    )


def test_the_execution_role_scopes_everything_it_can() -> None:
    """One unscopable action, alone in its own statement, and nothing else on ``*``.

    ``ecr:GetAuthorizationToken`` takes no resource type at all. Every other action the
    execution role holds names either the repository or the log group.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a second action shares the wildcard statement, or a scoped action
        is not scoped.
    """
    template = (SPA / "policies" / "task-execution-policy.json.tftpl").read_text()
    document = json.loads(
        template.replace("${repository_arn}", "arn:aws:ecr:us-east-1:1:repository/x").replace(
            "${log_group_arn}", "arn:aws:logs:us-east-1:1:log-group:/ecs/x"
        )
    )

    wildcard = [s for s in document["Statement"] if s["Resource"] == "*"]
    assert len(wildcard) == 1, f"Expected exactly one wildcard statement, found {len(wildcard)}"
    assert wildcard[0]["Action"] == "ecr:GetAuthorizationToken", (
        f"Only ecr:GetAuthorizationToken may sit on '*' — it takes no resource type. Found "
        f"{wildcard[0]['Action']}."
    )

    scoped = [s for s in document["Statement"] if s["Resource"] != "*"]
    assert scoped, "Every pull and log action was granted on '*'."
    for statement in scoped:
        assert statement["Resource"].startswith("arn:aws:"), statement


def test_the_container_runs_read_only_as_a_non_root_user() -> None:
    """Both halves, because either alone leaves the other undone.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the root filesystem is writable or the container runs as root.
    """
    definition = _container_definition()
    assert re.search(r"readonlyRootFilesystem\s*=\s*true", definition), definition[:400]

    user = re.search(r'user\s*=\s*"(\d+)"', definition)
    assert user, "The container definition names no user, so it runs as root."
    assert user.group(1) != "0", "The container runs as uid 0."


def test_the_mounted_paths_equal_the_writable_set_the_image_spec_declares() -> None:
    """An agreement between two specs and one configuration, read from the spec itself.

    The limit is worth stating: this proves the two DOCUMENTS agree. That the image's real
    writable set matches is the image spec's own build matrix, and is recorded there.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the spec's criterion cannot be found (the parse going trivial), or
        when the mounted set differs from it.
    """
    own_spec = SPEC_193.read_text()
    own_anchor = "The mounted pair is exactly"
    assert own_anchor in own_spec, (
        f"{SPEC_193.name} no longer states its mounted-pair criterion at '{own_anchor}'. This test "
        "compares two specs and one configuration; re-point it rather than deleting it."
    )
    own_criterion = own_spec[own_spec.index(own_anchor) : own_spec.index(own_anchor) + 200]
    own_declared = tuple(sorted(set(re.findall(r"`(/[a-z/]+)`", own_criterion))))
    assert len(own_declared) == 2, f"Parsed {own_declared} from this spec — the parse went trivial."

    spec = SPEC_194.read_text()
    anchor = "The writable paths the image needs are exactly"
    assert anchor in spec, (
        f"{SPEC_194.name} no longer states its writable-path criterion at '{anchor}'. This test "
        "compares two specs; if the wording moved, re-point it — do not delete it."
    )
    criterion = spec[spec.index(anchor) : spec.index(anchor) + 400]
    declared = tuple(sorted(set(re.findall(r"`(/[a-z/]+)`", criterion))))
    assert len(declared) == 2, f"Parsed {declared} from the criterion — the parse went trivial."
    assert declared == tuple(sorted(WRITABLE_PATHS)), (
        f"{SPEC_194.name} declares {declared}; this file expects {tuple(sorted(WRITABLE_PATHS))}."
    )
    assert own_declared == declared, (
        f"The two specs disagree: {SPEC_193.name} declares {own_declared}, {SPEC_194.name} "
        f"declares {declared}. One of them was edited alone."
    )

    text = _source()
    mounted = tuple(sorted(set(re.findall(r'containerPath\s*=\s*"?([^"\s,]+)', _container_definition()))))
    volumes = re.search(r"writable_paths\s*=\s*\[([^\]]+)\]", text)
    assert volumes, "No writable_paths local — the volumes and the mounts are no longer derived."
    from_local = tuple(sorted(re.findall(r'"([^"]+)"', volumes.group(1))))

    assert from_local == tuple(sorted(declared)), (
        f"The module mounts {from_local}; the image spec declares {declared}. A mount set missing "
        "one of them produces a container that never starts, reported as a generic "
        "essential-container exit."
    )
    assert mounted in ((), from_local) or "for path in local.writable_paths" in text, (
        "The mountPoints are hand-listed rather than derived from the same local as the volumes."
    )

    assert "linuxParameters" not in _source_without_comments(), (
        "linuxParameters appeared. The mechanism here is task-level volumes with matching "
        "mountPoints, which the image spec depends on."
    )


def test_the_environment_block_is_derived_and_never_hand_lists_a_key() -> None:
    """A hand-written block is how a container ships serving part of its own document.

    The key SET is asserted against the classification by the portal suite, which owns the
    declaration. What is asserted here is the shape that makes a partial block impossible.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the block stops being derived, or when a key is named literally.
    """
    text = _source()
    assert "for key in sort(keys(var.runtime_config))" in text
    assert 'name  = "CONFIG_${key}"' in text

    literal = re.findall(r'"CONFIG_[A-Za-z]', text)
    assert not literal, f"A CONFIG_ key is named literally: {literal}. The block is derived."

    # THE LINK, not just the definition. A derived local that the container definition does not
    # reference is a container carrying NONE of the document — every assertion above still
    # green, and under the image's own entrypoint contract a container that refuses to start.
    definition = _container_definition()
    environment = re.search(r"environment\s*=\s*(.+)", definition)
    assert environment, "The container definition carries no environment block at all."
    assert "local.config_environment" in environment.group(1), (
        f"The environment block does not carry the derived key list: {environment.group(1)!r}"
    )
    assert "PORTAL_CSP_CONNECT_SRC" in definition, (
        "The CSP source list is not in the container's environment."
    )


def test_root_wires_the_runtime_map_and_the_csp_local_into_the_module() -> None:
    """The middle link of the chain, which both key-set assertions read across but neither owns.

    The portal suite compares ``local.spa_runtime_config``'s keys against the classification;
    this module renders whatever map it is given. Nothing between them asserted that the module
    is given THAT map — so a hand-built map here would ship a one-key container, with the key
    set green in one suite and the derivation green in the other.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the module block does not take both locals.
    """
    block = _root_module_block("spa")
    assert re.search(r"runtime_config\s*=\s*local\.spa_runtime_config\b", block), (
        "module.spa does not take local.spa_runtime_config. The classification's key set is "
        "asserted against that local, so anything else here ships a container the tests cannot see."
    )
    assert re.search(r"csp_connect_src\s*=\s*local\.csp_connect_src\b", block), block


def test_the_service_runs_where_and_how_the_design_requires() -> None:
    """Platform version, subnet placement, public-IP assignment and the circuit breaker.

    ``platform_version`` is the one with no symptom: on 1.3.0 the image pull travelled a
    separate Amazon-owned ENI to which VPC endpoints did not apply, so the whole
    endpoints-instead-of-a-NAT design silently does not hold.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any of the four is wrong.
    """
    service = blocks(_source(), "aws_ecs_service")["spa"]

    version = re.search(r'platform_version\s*=\s*"([\d.]+)"', service)
    assert version, "platform_version is not pinned; LATEST is not a version."
    assert tuple(int(part) for part in version.group(1).split(".")) >= (1, 4, 0), version.group(1)

    assert re.search(r"subnets\s*=\s*var\.private_subnet_ids", service), service
    assert re.search(r"assign_public_ip\s*=\s*false", service), service

    breaker = re.search(r"deployment_circuit_breaker\s*\{([^}]*)\}", service)
    assert breaker, "No deployment circuit breaker."
    assert re.search(r"enable\s*=\s*true", breaker.group(1)), breaker.group(1)
    assert re.search(r"rollback\s*=\s*false", breaker.group(1)), (
        "Rollback is enabled. With no previous good task set, a missing image then reads as a "
        "rollback rather than as CannotPullContainerError — the one diagnosis this arc's central "
        "claim is tested by."
    )


def test_the_service_ignores_the_image_and_still_obeys_the_desired_count() -> None:
    """CI owns the task definition; the count stays Terraform's because a step raises it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the image is not ignored, or when the count is.
    """
    service = blocks(_source(), "aws_ecs_service")["spa"]
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", service)
    assert ignored, "Nothing is ignored, so every infra apply reverts the deployed image."

    entries = {entry.strip() for entry in ignored.group(1).split(",") if entry.strip()}
    assert "task_definition" in entries, entries
    assert "desired_count" not in entries, (
        "desired_count is ignored, which makes raising spa_desired_count a silent no-op — and "
        "the verification step that raises it from 0 to 1 reads as a broken service."
    )
    assert re.search(r"desired_count\s*=\s*var\.desired_count", service), service


def test_the_desired_count_defaults_to_zero() -> None:
    """The first apply creates a service before any image exists.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the default is absent or non-zero.
    """
    text = ROOT_VARIABLES.read_text()
    block = re.search(r'variable\s+"spa_desired_count"\s*\{(.*?)\n\}', text, re.DOTALL)
    assert block, "No spa_desired_count variable at root."
    assert re.search(r"default\s*=\s*0\b", block.group(1)), block.group(1)


def test_the_load_balancer_is_internet_facing_in_the_public_subnets() -> None:
    """Both halves. Private subnets apply green and yield an address nothing can reach.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the balancer is internal or placed in the private subnets.
    """
    balancer = blocks(_source(), "aws_lb")["spa"]
    assert re.search(r"internal\s*=\s*false", balancer), balancer
    assert re.search(r"subnets\s*=\s*var\.public_subnet_ids", balancer), balancer
    assert re.search(r"drop_invalid_header_fields\s*=\s*true", balancer), balancer
    assert re.search(r"enable_deletion_protection\s*=\s*true", balancer), balancer
    logs = re.search(r"access_logs\s*\{([^}]*)\}", balancer)
    assert logs, "The load balancer writes no access logs."
    assert re.search(r"enabled\s*=\s*true", logs.group(1)), (
        f"Access logging is declared and switched off: {logs.group(1)!r}"
    )
    assert "var.admin_bucket_name" in logs.group(1), logs.group(1)
    assert re.search(r"prefix\s*=\s*var\.access_logs_prefix", logs.group(1)), (
        "The log prefix is not the one root decides. It is load-bearing three ways: the bucket "
        "policy's Resource, the lifecycle rule that expires the objects, and this destination."
    )


def test_the_load_balancer_waits_for_the_bucket_policy_that_permits_its_logs() -> None:
    """No implicit edge exists: the bucket is named by NAME, so both orders are legal.

    ALB validates the destination policy and writes a test object at create. One of the two
    legal orders is a 403.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the explicit dependency is missing.
    """
    balancer = blocks(_source(), "aws_lb")["spa"]
    assert re.search(r"depends_on\s*=\s*\[[^\]]*aws_s3_bucket_policy\.alb_access_logs", balancer), (
        "aws_lb.spa does not depend on the access-log bucket policy."
    )


def test_the_admin_buckets_first_policy_denies_nothing_and_wildcards_no_account() -> None:
    """A ``Deny`` here would stop the deploy role's own refresh read of the bucket.

    Every later plan would then propose destroying a bucket holding the structured logs. The
    account id is a segment of the key ALB writes to, and wildcarding it would accept another
    account's load balancer's logs.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the policy denies anything, wildcards the account, or delivers
        through the legacy account-principal form.
    """
    template = (SPA / "policies" / "alb-access-logs-bucket-policy.json.tftpl").read_text()
    document = json.loads(
        template.replace("${bucket_arn}", "arn:aws:s3:::admin")
        .replace("${access_logs_prefix}", "alb-access-logs")
        .replace("${account_id}", "111122223333")
        .replace("${load_balancer_arn_pattern}", "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/x/*")
    )

    for statement in document["Statement"]:
        assert statement["Effect"] == "Allow", (
            "The admin bucket's policy contains a Deny. It would also stop the deploy role's "
            "refresh read, and every later plan would propose recreating the bucket."
        )
        assert statement["Principal"] == {
            "Service": "logdelivery.elasticloadbalancing.amazonaws.com"
        }, statement["Principal"]
        assert "/AWSLogs/111122223333/" in statement["Resource"], statement["Resource"]
        assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == "111122223333"
        assert "aws:SourceArn" in statement["Condition"]["ArnLike"]

    assert "aws_elb_service_account" not in _source_without_comments(), (
        "The legacy account-principal form is back. AWS heads its own published version 'Legacy "
        "bucket policy', and it delivers through an ACL grant this BucketOwnerEnforced bucket "
        "does not accept."
    )


def test_the_admin_bucket_carries_exactly_one_policy_across_the_whole_tree() -> None:
    """``aws_s3_bucket_policy`` is whole-document: a second one silently replaces the first.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When another module also writes a policy for the admin bucket.
    """
    offenders = []
    for path in sorted(INFRA.rglob("*.tf")):
        for name, body in blocks(path.read_text(), "aws_s3_bucket_policy").items():
            if "admin_bucket" in body or "athena_admin" in body:
                offenders.append(f"{path.relative_to(INFRA)}:{name}")

    assert offenders == ["modules/spa/alb.tf:alb_access_logs"], (
        f"The admin bucket's policy is written in {offenders}. aws_s3_bucket_policy replaces the "
        "WHOLE document, so a second one drops the load balancer's log delivery with no error."
    )


def test_the_listeners_terminate_modern_tls_and_port_80_only_redirects() -> None:
    """A listener that can serve anything over port 80 is one that can serve the app over it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the TLS policy is weaker than the spec's, or the HTTP listener does
        anything but redirect.
    """
    listeners = blocks(_source(), "aws_lb_listener")
    assert {"https", "http"} <= set(listeners), sorted(listeners)

    policy = re.search(r'ssl_policy\s*=\s*"([^"]+)"', listeners["https"])
    assert policy and policy.group(1) in ALLOWED_TLS_POLICIES, policy

    # From the VALIDATION resource, which root passes in. Taking the certificate's own ARN
    # instead applies green and attaches a PENDING_VALIDATION certificate on a clean rebuild.
    assert re.search(r"certificate_arn\s*=\s*var\.spa_certificate_arn", listeners["https"]), (
        listeners["https"]
    )

    http = listeners["http"]
    assert "redirect" in http and "HTTP_301" in http, http
    assert "forward" not in http and "target_group_arn" not in http, (
        "The HTTP listener can reach a target group. Its only action is the redirect."
    )
    assert 'protocol    = "HTTPS"' in http or 'protocol = "HTTPS"' in http, http


def test_the_target_group_matches_the_container_and_the_health_check() -> None:
    """``ip`` targets, the container's port, the agreed path and a 200 matcher.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any of the four differs.
    """
    group = blocks(_source(), "aws_lb_target_group")["spa"]
    assert re.search(r'target_type\s*=\s*"ip"', group), group
    assert re.search(r"port\s*=\s*var\.container_port", group), group
    assert re.search(r"path\s*=\s*var\.health_check_path", group), group
    assert re.search(r'matcher\s*=\s*"200"', group), group

    variables = (SPA / "variables.tf").read_text()
    port = re.search(r'variable\s+"container_port"\s*\{.*?default\s*=\s*(\d+)', variables, re.DOTALL)
    path = re.search(
        r'variable\s+"health_check_path"\s*\{.*?default\s*=\s*"([^"]+)"', variables, re.DOTALL
    )
    assert port and port.group(1) == "8080", port
    assert path and path.group(1) == "/healthz", path


def test_the_task_group_egresses_to_the_prefix_list_and_only_where_it_must() -> None:
    """A CIDR egress rule does not match gateway-endpoint traffic, and the pull HANGS.

    The three "only"s are asserted together because each alone is satisfiable while another is
    violated: an extra egress rule, an ingress from anything but the load balancer, or an
    egress to a CIDR that looks like S3.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any rule on the task group is wider than the design.
    """
    text = _source()
    own_group = re.compile(r"(?<!referenced_)security_group_id\s*=\s*var\.task_security_group_id")
    egress = {
        name: body
        for name, body in blocks(text, "aws_vpc_security_group_egress_rule").items()
        if own_group.search(body)
    }
    assert set(egress) == {"tasks_to_endpoints", "tasks_to_s3"}, sorted(egress)

    assert "prefix_list_id    = var.s3_prefix_list_id" in egress["tasks_to_s3"].replace(
        "prefix_list_id = ", "prefix_list_id    = "
    ), egress["tasks_to_s3"]
    for name, body in egress.items():
        assert "cidr_ipv4" not in body and "cidr_ipv6" not in body, (
            f"{name} egresses to a CIDR. Gateway-endpoint traffic is matched by PREFIX LIST; a "
            "CIDR rule leaves the image pull hanging rather than refusing."
        )

    ingress = {
        name: body
        for name, body in blocks(text, "aws_vpc_security_group_ingress_rule").items()
        if own_group.search(body)
    }
    assert set(ingress) == {"tasks_from_alb"}, sorted(ingress)
    assert "aws_security_group.alb.id" in ingress["tasks_from_alb"], ingress["tasks_from_alb"]


def test_the_load_balancer_group_admits_the_internet_and_reaches_only_the_tasks() -> None:
    """The other half of the last acceptance criterion, and the half nothing covered.

    An egress rule added here — the ordinary "let it talk to things" edit — gives a group that
    sits in a public subnet a route to everything, and no assertion about the TASK group sees it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the group admits or reaches anything beyond the design.
    """
    text = _source()
    own_group = re.compile(r"(?<!referenced_)security_group_id\s*=\s*aws_security_group\.alb\.id")

    ingress = {
        name: body
        for name, body in blocks(text, "aws_vpc_security_group_ingress_rule").items()
        if own_group.search(body)
    }
    assert set(ingress) == {"alb_https", "alb_http"}, sorted(ingress)
    ports = sorted(
        int(re.search(r"from_port\s*=\s*(\d+)", body).group(1)) for body in ingress.values()
    )
    assert ports == [80, 443], ports

    egress = {
        name: body
        for name, body in blocks(text, "aws_vpc_security_group_egress_rule").items()
        if own_group.search(body)
    }
    assert set(egress) == {"alb_to_tasks"}, (
        f"The load balancer's group has egress rules beyond the tasks: {sorted(egress)}"
    )
    assert "var.task_security_group_id" in egress["alb_to_tasks"], egress["alb_to_tasks"]
    assert "cidr_ipv4" not in egress["alb_to_tasks"], egress["alb_to_tasks"]
    assert "var.container_port" in egress["alb_to_tasks"], egress["alb_to_tasks"]


def test_the_endpoint_groups_ingress_is_not_declared_twice() -> None:
    """It belongs to the network module, beside the endpoints. A duplicate fails the apply.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When this module re-declares the rule the network module owns.
    """
    assert "endpoints_from_tasks" in NETWORK_ENDPOINTS.read_text(), (
        "The network module no longer declares the endpoints' ingress — this test's premise is "
        "gone, so re-point it rather than deleting it."
    )
    for name, body in blocks(_source(), "aws_vpc_security_group_ingress_rule").items():
        assert "var.vpc_endpoint_security_group_id" not in body, (
            f"{name} re-declares the endpoint group's ingress, which the network module already "
            "owns. The apply fails with InvalidPermission.Duplicate."
        )


def test_the_registry_is_immutable_scanned_encrypted_and_bounded() -> None:
    """A mutable tag makes a rolled-back task definition start something else entirely.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any of the four properties is missing.
    """
    text = _source()
    repository = blocks(text, "aws_ecr_repository")["spa"]
    assert re.search(r'image_tag_mutability\s*=\s*"IMMUTABLE"', repository), repository
    assert re.search(r"scan_on_push\s*=\s*true", repository), repository
    assert re.search(r'encryption_type\s*=\s*"AES256"', repository), repository

    lifecycle = blocks(text, "aws_ecr_lifecycle_policy")["spa"]
    assert "expire" in lifecycle and "imageCountMoreThan" in lifecycle, lifecycle


def test_the_task_log_group_is_declared_with_a_retention() -> None:
    """Without the group every task dies at start, and the message reads like the pull failing.

    ``awslogs-create-group`` would produce a group nobody manages, retained forever, and would
    also skip the enforced retention gate.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the group is missing, unretained, or created by the driver.
    """
    text = _source()
    group = blocks(text, "aws_cloudwatch_log_group")["spa"]
    assert re.search(r"retention_in_days\s*=\s*\d+", group), group
    assert "awslogs-create-group" not in _source_without_comments()
    assert "aws_cloudwatch_log_group.spa.name" in text, "The container logs to some other group."
