"""The private subnets must have no way out, and the endpoints must replace it exactly.

Every failure guarded here applies green, and the no-NAT assertion is repo-wide rather than
module-scoped on purpose. The reasoning, and what only the acceptance script can settle, is in
``infra/modules/network/README.md``.

Attributes:
  INFRA: The IaC tree, swept whole by the no-NAT assertion.
  NETWORK: The network module's directory.
  MAIN: Its VPC, subnets, route tables, security groups and flow logs.
  ROOT_MAIN: The root composition, which owns the availability-zones read — the module's own
    depends_on would defer it to apply, and the subnets' for_each cannot take a deferred value.
  GRANT: The deploy-role policy that scopes the flow-logs role by name.
  ENDPOINTS: Its four VPC endpoints.
  FLOW_LOG_PERMISSIONS: The flow-log delivery role's permissions, which must not let it create
    its own log group.
  INTERFACE_ENDPOINT_SERVICES: The three interface endpoints a Fargate task needs to start and
    log with no route to the internet.
"""

import fnmatch
import json
import pathlib
import re

from tf_blocks import blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
NETWORK = INFRA / "modules" / "network"
MAIN = NETWORK / "main.tf"
ROOT_MAIN = INFRA / "main.tf"
GRANT = INFRA / "modules" / "base" / "policies" / "github-actions-deploy-platform-frontdoor.json.tftpl"
ENDPOINTS = NETWORK / "endpoints.tf"
FLOW_LOG_PERMISSIONS = NETWORK / "policies" / "flow-logs-permissions.json.tftpl"

INTERFACE_ENDPOINT_SERVICES = ("ecr.api", "ecr.dkr", "logs")


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
    text = "\n".join(path.read_text() for path in sorted(NETWORK.rglob("*.tf")))
    private_tables = blocks(text, "aws_route_table")
    assert "private" in private_tables, "No private route table found — the parse went trivial."

    for name, body in private_tables.items():
        if "private" in name:
            assert "0.0.0.0/0" not in body and "::/0" not in body, (
                f"aws_route_table.{name} declares an inline default route."
            )

    for name, body in blocks(text, "aws_route").items():
        if "0.0.0.0/0" in body or "::/0" in body:
            assert "aws_route_table.public" in body, (
                f"aws_route.{name} sends a default route somewhere other than the public table. "
                "Only the public subnets reach the internet."
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
    endpoints = blocks(text, "aws_vpc_endpoint")
    assert "interface" in endpoints, "No interface endpoints found."
    body = endpoints["interface"]

    for service in INTERFACE_ENDPOINT_SERVICES:
        assert f'"{service}"' in body, (
            f"No interface endpoint for {service}. A Fargate task with no route to the internet "
            "needs all three of ecr.api, ecr.dkr and logs; the S3 gateway endpoint is separate."
        )
    assert re.search(r'vpc_endpoint_type\s*=\s*"Interface"', body)
    assert "private_dns_enabled = true" in body, (
        "private_dns_enabled must be true, and the VPC must have DNS support and hostnames on — "
        "without all three the endpoint exists and nothing resolves to it."
    )
    assert "aws_subnet.private" in body, "The interface endpoints must sit in the private subnets."
    assert "aws_security_group.endpoints.id" in body

    ingress = blocks(text, "aws_vpc_security_group_ingress_rule")
    assert ingress, "The endpoint security group has no ingress rule."

    # ON the endpoint group and FROM the task group, checked as two separate attributes. Merely
    # finding both names somewhere in the body passes with the two transposed — which leaves the
    # endpoint group with no ingress at all, and every task-to-endpoint connection black-holing
    # as the connect timeout this whole module exists to make legible.
    on_endpoints = {
        name: body
        for name, body in ingress.items()
        if re.search(r"security_group_id\s*=\s*aws_security_group\.endpoints\.id", body)
    }
    assert on_endpoints, (
        "No ingress rule names aws_security_group.endpoints.id as its security_group_id. Check "
        "that security_group_id and referenced_security_group_id are not transposed."
    )
    assert any(
        re.search(r"referenced_security_group_id\s*=\s*aws_security_group\.task\.id", body)
        and "443" in body
        for body in on_endpoints.values()
    ), "No rule on the endpoint group admits 443 from the task group."

    cidr_rules = sorted(
        name for name, body in on_endpoints.items() if "cidr_ipv4" in body or "cidr_ipv6" in body
    )
    assert not cidr_rules, (
        f"Ingress rule(s) {cidr_rules} admit a CIDR to the endpoint group. It must be reachable "
        "from the task group alone — a CIDR rule also admits anything else that ever lands in "
        "these subnets, which is the whole difference between the two."
    )


def test_the_flow_log_role_cannot_create_its_own_log_group() -> None:
    """No action the flow-log role holds, wildcards included, covers ``logs:CreateLogGroup``.

    Delivery outlives a destroyed flow log by seconds and IAM honours a deleted grant for as long,
    so a role that can create its group recreates it just after a switch-off removes it, and the
    next switch-on fails on a group that already exists. Re-adding the action applies green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any statement's action pattern matches ``logs:CreateLogGroup``.
    """
    policy = json.loads(FLOW_LOG_PERMISSIONS.read_text())
    actions = [
        action
        for statement in policy["Statement"]
        for action in ([statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"])
    ]
    assert actions, "The flow-log role's policy grants no actions; the template did not parse as expected."
    granting = [a for a in actions if fnmatch.fnmatchcase("logs:createloggroup", a.lower())]
    assert not granting, (
        f"The flow-log role holds {granting}, which covers logs:CreateLogGroup. Terraform owns the "
        "group; with this grant the delivery service recreates it after a switch-off, and the "
        "next switch-on stops at ResourceAlreadyExistsException."
    )
