"""The private subnets must have no way out, and the endpoints must replace it exactly.

Every failure this file guards against **applies green**. A NAT gateway somebody adds to fix a
timeout, a default route in a private table, a gateway endpoint associated with the wrong route
table, an interface endpoint with private DNS off — Terraform accepts all of them, the plan reads
as an ordinary addition, and the only symptom is an image pull that cannot complete or a task that
silently reaches the internet.

**What this file cannot prove, and what does.** These are text assertions over the module's own
Terraform. They cannot tell you the applied route tables match, that DNS actually resolves to the
endpoint, or that a pull completes — only the live checks can, and the acceptance script pairs the
pull with a `describe-route-tables` read for exactly that reason: a pull that succeeded through a
route somebody added would otherwise read as proof of the endpoints.

**The no-NAT assertion is repo-wide rather than module-scoped**, and that is the point. Scoped to
this module it would be satisfied by adding the gateway somewhere else, which is precisely what a
future "quick fix" for a connect timeout looks like.

Attributes:
  INFRA: The IaC tree, swept whole by the no-NAT assertion.
  NETWORK: The network module's directory.
  MAIN: Its VPC, subnets, route tables, security groups and flow logs.
  ENDPOINTS: Its four VPC endpoints.
  INTERFACE_ENDPOINT_SERVICES: The three interface endpoints a Fargate task needs to start and
    log with no route to the internet.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
NETWORK = INFRA / "modules" / "network"
MAIN = NETWORK / "main.tf"
ENDPOINTS = NETWORK / "endpoints.tf"

INTERFACE_ENDPOINT_SERVICES = ("ecr.api", "ecr.dkr", "logs")


def _blocks(text: str, kind: str) -> dict[str, str]:
    """Splits Terraform source into top-level resource blocks of one type.

    A brace-counting split rather than a regex over the whole block, because a resource body
    contains nested braces and a non-greedy match stops at the first inner one — which would
    quietly hide whatever came after it.

    Args:
      text: The Terraform source to read.
      kind: The resource type to collect, e.g. ``aws_route_table``.

    Returns:
      Each matching resource's local name mapped to its body.

    Raises:
      None.
    """
    found = {}
    for match in re.finditer(rf'resource\s+"{re.escape(kind)}"\s+"([^"]+)"\s*\{{', text):
        depth, index = 1, match.end()
        while depth and index < len(text):
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            index += 1
        found[match.group(1)] = text[match.end() : index - 1]
    return found


def test_no_nat_gateway_or_elastic_ip_exists_anywhere_in_the_iac() -> None:
    """The design's central claim, asserted over the whole tree rather than one module.

    A connect timeout from a private subnet is the slowest failure here to diagnose, and the
    fix that suggests itself is a NAT gateway. This makes reintroducing one a deliberate act
    that has to delete an assertion, rather than a one-line addition in a hurry.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a NAT gateway or Elastic IP appears anywhere under ``infra/``.
    """
    files = sorted(INFRA.rglob("*.tf"))
    assert len(files) > 20, f"Swept only {len(files)} .tf files — the glob found the wrong tree."

    offenders = sorted(
        f"{path.relative_to(INFRA)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r'resource\s+"(aws_nat_gateway|aws_eip)"', line)
    )
    assert not offenders, (
        f"A NAT gateway or Elastic IP is declared at {offenders}. The private subnets reach AWS "
        "through VPC endpoints and reach nothing else, on purpose — if a destination is genuinely "
        "unreachable, add an interface endpoint for it or spec the change. Do not delete this test."
    )


def test_no_private_route_table_carries_a_default_route() -> None:
    """A `0.0.0.0/0` entry on a private table would undo the whole design silently.

    Asserted over every ``aws_route`` and every inline ``route`` block, because the two are
    different mechanisms and a reader who checks one often forgets the other.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any route to the private tables carries a default destination.
    """
    text = MAIN.read_text()
    private_tables = _blocks(text, "aws_route_table")
    assert "private" in private_tables, "No private route table found — the parse went trivial."

    for name, body in private_tables.items():
        if "private" in name:
            assert "0.0.0.0/0" not in body and "::/0" not in body, (
                f"aws_route_table.{name} declares an inline default route."
            )

    for name, body in _blocks(text, "aws_route").items():
        if "0.0.0.0/0" in body or "::/0" in body:
            assert "aws_route_table.public" in body, (
                f"aws_route.{name} sends a default route somewhere other than the public table. "
                "Only the public subnets reach the internet."
            )


def test_the_gateway_endpoint_associates_every_private_route_table() -> None:
    """The association set must be derived, never listed.

    A gateway endpoint associated with the wrong route table applies green and does nothing.
    Deriving ``route_table_ids`` from the resource means an availability zone added later cannot
    be left out of it, which a hand-kept list would permit.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the S3 endpoint is missing, not a gateway, or lists its tables.
    """
    endpoints = _blocks(ENDPOINTS.read_text(), "aws_vpc_endpoint")
    assert "s3" in endpoints, "No S3 VPC endpoint found."
    body = endpoints["s3"]

    assert 'vpc_endpoint_type = "Gateway"' in body, (
        "The S3 endpoint must be a Gateway. An interface endpoint installs no prefix-list route, "
        "so with no default route the pull has no path to it at all."
    )
    assert re.search(r"route_table_ids\s*=\s*\[for\s+\w+\s+in\s+aws_route_table\.private", body), (
        "route_table_ids must be derived from aws_route_table.private, not listed. A literal list "
        "applies green while associating the wrong tables, and the only symptom is a failed pull."
    )


def test_every_interface_endpoint_resolves_privately_and_admits_only_the_tasks() -> None:
    """Private DNS on, in the private subnets, behind the endpoint security group.

    ``private_dns_enabled`` is what makes the endpoint transparent to the SDK; without it the
    task resolves the public hostname and routes to nowhere. The subnet placement and the group
    are the other two halves — an endpoint in the public subnets is reachable and useless.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the interface endpoints are misconfigured or the wrong set.
    """
    text = ENDPOINTS.read_text()
    endpoints = _blocks(text, "aws_vpc_endpoint")
    assert "interface" in endpoints, "No interface endpoints found."
    body = endpoints["interface"]

    for service in INTERFACE_ENDPOINT_SERVICES:
        assert f'"{service}"' in body, (
            f"No interface endpoint for {service}. A Fargate task with no route to the internet "
            "needs all three of ecr.api, ecr.dkr and logs; the S3 gateway endpoint is separate."
        )
    assert 'vpc_endpoint_type   = "Interface"' in body or 'vpc_endpoint_type = "Interface"' in body
    assert "private_dns_enabled = true" in body, (
        "private_dns_enabled must be true, and the VPC must have DNS support and hostnames on — "
        "without all three the endpoint exists and nothing resolves to it."
    )
    assert "aws_subnet.private" in body, "The interface endpoints must sit in the private subnets."
    assert "aws_security_group.endpoints.id" in body

    ingress = _blocks(text, "aws_vpc_security_group_ingress_rule")
    assert ingress, "The endpoint security group has no ingress rule."
    assert any(
        "aws_security_group.task.id" in rule and "443" in rule for rule in ingress.values()
    ), (
        "The endpoint group must admit 443 from the TASK GROUP, never from the VPC CIDR — a CIDR "
        "rule also admits anything else that ever lands in these subnets."
    )


def test_the_vpc_enables_both_dns_settings() -> None:
    """``private_dns_enabled`` silently resolves to nothing without both of them.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either DNS setting is absent or false.
    """
    body = _blocks(MAIN.read_text(), "aws_vpc")["main"]
    assert "enable_dns_support   = true" in body or "enable_dns_support = true" in body
    assert "enable_dns_hostnames = true" in body


def test_subnets_are_keyed_by_availability_zone_name() -> None:
    """Keyed by AZ name so a reordering of the data source cannot recreate them.

    The CIDR still has to come from somewhere, and taking it from the data source's own order
    would reintroduce the recreate the keying exists to prevent — hence the sort.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the subnets are index-keyed, or the AZ list is unsorted.
    """
    text = MAIN.read_text()
    for name in ("public", "private"):
        body = _blocks(text, "aws_subnet")[name]
        assert "for_each = local.subnets" in body, f"aws_subnet.{name} must be keyed by AZ name."
        assert "availability_zone = each.key" in body

    assert re.search(r"azs\s*=\s*slice\(sort\(", text), (
        "The availability-zone list must be sorted before it is sliced. Without it the CIDR "
        "assignment depends on the API's ordering, and a reordering recreates every subnet."
    )


def test_public_subnets_hand_out_no_public_addresses() -> None:
    """The load balancer brings its own; anything else here should not have one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a public subnet auto-assigns public IPs.
    """
    body = _blocks(MAIN.read_text(), "aws_subnet")["public"]
    assert "map_public_ip_on_launch = false" in body


def test_every_log_group_this_module_creates_sets_retention() -> None:
    """An unset retention is infinite, and it is an already-enforced scanner finding.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a log group ships without a retention.
    """
    groups = _blocks(MAIN.read_text(), "aws_cloudwatch_log_group")
    assert groups, "No log group found — the parse went trivial."
    for name, body in groups.items():
        assert "retention_in_days" in body, f"aws_cloudwatch_log_group.{name} sets no retention."


def test_the_flow_logs_role_is_named_the_way_the_deploy_grant_expects() -> None:
    """The grant names this role by pattern, and a rename is denied at ``CreateRole``.

    The deploy role's platform-frontdoor policy scopes role management and ``iam:PassRole`` to
    ``{project}-*-vpc-flow-logs-role``. A name that does not match is refused when the role is
    created, which reads as a missing permission rather than as a naming mismatch.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the role name drifts from the pattern the grant scopes to.
    """
    body = _blocks(MAIN.read_text(), "aws_iam_role")["flow_logs"]
    assert 'name               = "${local.name_prefix}-vpc-flow-logs-role"' in body or (
        "vpc-flow-logs-role" in body
    ), "The flow-logs role must end in -vpc-flow-logs-role; the deploy grant scopes to that."
