"""The private subnets have one way out, the NAT gateway, and AWS services are reached by endpoint.

Every failure guarded here applies green, and the one-NAT-gateway assertion is repo-wide rather
than module-scoped on purpose. The reasoning, and what only the acceptance script can settle, is in
``infra/modules/network/README.md``.

Attributes:
  INFRA: The IaC tree, swept whole by the NAT gateway and default-route assertions.
  NETWORK: The network module's directory.
  MAIN: Its VPC, subnets, route tables, security groups and flow logs.
  ROOT_MAIN: The root composition, which owns the availability-zones read — the module's own
    depends_on would defer it to apply, and the subnets' for_each cannot take a deferred value.
  GRANT: The deploy-role policy that scopes the flow-logs role by name.
  ENDPOINTS: Its six VPC endpoints.
  FLOW_LOG_PERMISSIONS: The flow-log delivery role's permissions, which must not let it create
    its own log group.
  INTERFACE_ENDPOINT_SERVICES: The four interface endpoints a Fargate task needs to start, read
    its secret and log without the NAT gateway.
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

INTERFACE_ENDPOINT_SERVICES = ("ecr.api", "ecr.dkr", "logs", "ssm")


def test_the_nat_gateway_and_its_elastic_ip_are_declared_once_and_only_in_the_network_module() -> None:
    """One NAT gateway, on the web tier's switch, asserted over the whole tree.

    Scoped to the network module it would be satisfied by a second gateway somewhere else, which is
    what a quick fix for a connect timeout looks like. Both wait for the internet gateway: a public
    NAT gateway created before the gateway is attached fails, and only a switch-on from nothing can
    hit that, which no check runs.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either resource is declared anywhere else, more than once, or without
        the dependency on the internet gateway.
    """
    files = sorted(INFRA.rglob("*.tf"))
    assert len(files) > 20, f"Swept only {len(files)} .tf files — the glob found the wrong tree."

    declared = sorted(
        (str(path.relative_to(INFRA)), match.group(1), match.group(2))
        for path in files
        for match in re.finditer(r'resource\s+"(aws_nat_gateway|aws_eip)"\s+"([^"]+)"', path.read_text())
    )
    assert declared == [
        ("modules/network/main.tf", "aws_eip", "nat"),
        ("modules/network/main.tf", "aws_nat_gateway", "main"),
    ], f"The NAT gateway and its Elastic IP are declared as {declared}; there is one of each, in network."

    text = MAIN.read_text()
    for kind, name in (("aws_eip", "nat"), ("aws_nat_gateway", "main")):
        body = blocks(text, kind)[name]
        assert re.search(r"depends_on\s*=\s*\[\s*aws_internet_gateway\.main\s*\]", body), (
            f"{kind}.{name} does not wait for the internet gateway"
        )


def test_every_private_route_table_defaults_to_the_nat_gateway_and_nothing_else_defaults() -> None:
    """The one way out of the private subnets is the NAT gateway, and nothing else adds one.

    Asserted over every ``aws_route`` and every inline ``route`` block in the whole tree, because
    the two are different mechanisms and a reader who checks one often forgets the other.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a private table has an inline default route, the private default does
        not cover every private table or target the NAT gateway, or any other route defaults.
    """
    text = "\n".join(path.read_text() for path in sorted(NETWORK.rglob("*.tf")))
    private_tables = blocks(text, "aws_route_table")
    assert "private" in private_tables, "No private route table found — the parse went trivial."
    for name, body in private_tables.items():
        assert "0.0.0.0/0" not in body and "::/0" not in body, (
            f"aws_route_table.{name} declares an inline default route."
        )

    routes = blocks(text, "aws_route")
    private_default = routes.get("private_default", "")
    assert re.search(r"for_each\s*=\s*aws_route_table\.private\b", private_default), (
        "the private default route is not derived from every private table"
    )
    assert re.search(r"nat_gateway_id\s*=\s*aws_nat_gateway\.main\.id", private_default), (
        "the private default route does not target the NAT gateway"
    )

    defaulting = sorted(
        f"{path.relative_to(INFRA)}: aws_route.{name}"
        for path in sorted(INFRA.rglob("*.tf"))
        for name, body in blocks(path.read_text(), "aws_route").items()
        if "0.0.0.0/0" in body or "::/0" in body
    )
    assert defaulting == [
        "modules/network/main.tf: aws_route.private_default",
        "modules/network/main.tf: aws_route.public_internet",
    ], f"Default routes are declared at {defaulting}; only the public table and the NAT path may have one."


def test_both_gateway_endpoints_take_their_route_tables_from_the_private_tables() -> None:
    """A gateway endpoint on the wrong tables applies green and does nothing, so neither lists them.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either gateway endpoint names its route tables any other way.
    """
    endpoints = blocks(ENDPOINTS.read_text(), "aws_vpc_endpoint")
    for name in ("s3", "dynamodb"):
        body = endpoints.get(name, "")
        assert re.search(r'vpc_endpoint_type\s*=\s*"Gateway"', body), f"aws_vpc_endpoint.{name} is not a gateway"
        assert re.search(
            r"route_table_ids\s*=\s*\[\s*for\s+(\w+)\s+in\s+aws_route_table\.private\s*:\s*\1\.id\s*\]", body
        ), f"aws_vpc_endpoint.{name} does not derive its route tables from aws_route_table.private"


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
