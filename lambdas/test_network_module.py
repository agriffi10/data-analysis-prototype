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
  ROOT_MAIN: The root composition, which owns the availability-zones read — the module's own
    depends_on would defer it to apply, and the subnets' for_each cannot take a deferred value.
  GRANT: The deploy-role policy that scopes the flow-logs role by name — the other half of an
    agreement whose breach is refused at ``CreateRole`` and reads as a missing permission.
  ENDPOINTS: Its four VPC endpoints.
  INTERFACE_ENDPOINT_SERVICES: The three interface endpoints a Fargate task needs to start and
    log with no route to the internet.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
NETWORK = INFRA / "modules" / "network"
MAIN = NETWORK / "main.tf"
ROOT_MAIN = INFRA / "main.tf"
GRANT = INFRA / "modules" / "base" / "policies" / "github-actions-deploy-platform-frontdoor.json.tftpl"
ENDPOINTS = NETWORK / "endpoints.tf"

INTERFACE_ENDPOINT_SERVICES = ("ecr.api", "ecr.dkr", "logs")


def _blocks(text: str, kind: str) -> dict[str, str]:
    """Splits Terraform source into top-level resource blocks of one type.

    A brace-counting split rather than a regex over the whole block, because a resource body
    contains nested braces and a non-greedy match stops at the first inner one — which would
    quietly hide whatever came after it.

    **Strings and comments are skipped, and that is not fastidiousness.** A naive count ends the
    block at the ``}`` inside ``tags = { Name = "closes early }" }``, so everything after it —
    including a default route to a NAT gateway — falls outside the body and every assertion below
    reports clean. The reverse, an unbalanced brace inside a ``#`` comment, swallows the next
    resource whole and produces a failure naming the wrong one.

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
            char = text[index]
            if char == "#" or text[index : index + 2] == "//":
                index = text.find("\n", index)
                if index == -1:
                    break
            elif char == '"':
                index += 1
                while index < len(text) and text[index] != '"':
                    index += 2 if text[index] == "\\" else 1
            else:
                depth += {"{": 1, "}": -1}.get(char, 0)
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
    text = "\n".join(path.read_text() for path in sorted(NETWORK.rglob("*.tf")))
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

    assert re.search(r'vpc_endpoint_type\s*=\s*"Gateway"', body), (
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
    assert re.search(r'vpc_endpoint_type\s*=\s*"Interface"', body)
    assert "private_dns_enabled = true" in body, (
        "private_dns_enabled must be true, and the VPC must have DNS support and hostnames on — "
        "without all three the endpoint exists and nothing resolves to it."
    )
    assert "aws_subnet.private" in body, "The interface endpoints must sit in the private subnets."
    assert "aws_security_group.endpoints.id" in body

    ingress = _blocks(text, "aws_vpc_security_group_ingress_rule")
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

    # THE KEY ITSELF, not just that for_each reads local.subnets. Re-keying the comprehension by
    # its index satisfies every assertion above while making `availability_zone` a number.
    assert re.search(r"for\s+\w+,\s*(\w+)\s+in\s+local\.azs\s*:\s*\1\s*=>", text), (
        "local.subnets must be keyed by the availability-zone NAME — the comprehension's own AZ "
        "variable — not by its index. Keyed by index, a reordering renames every subnet."
    )
    assert re.search(r"azs\s*=\s*slice\(sort\(", text), (
        "The availability-zone list must be sorted before it is sliced. Without it the CIDR "
        "assignment depends on the API's ordering, and a reordering recreates every subnet."
    )
    root = ROOT_MAIN.read_text()
    assert re.search(r'name\s*=\s*"opt-in-status"', root), (
        "The availability-zones data source must filter on opt-in-status. Local and Wavelength "
        "zones sort BEFORE the ordinary ones, so opting into any of them would move this network "
        "into two zones Fargate does not run in. The source reads at ROOT, because a module-level "
        "depends_on defers a data source to apply and this one feeds a for_each, where deferral "
        "is a hard error rather than a deferred value."
    )
    assert re.search(
        r"availability_zone_names\s*=\s*data\.aws_availability_zones\.available\.names", root
    ), (
        "module.network must take the availability zones from the filtered data source. A literal "
        "list at the call site satisfies every other assertion here while bypassing the "
        "opt-in-status filter entirely — and it pins the network to two named zones, so the CIDR "
        "pairing stops being derived at all."
    )
    assert not re.search(r'data\s+"aws_availability_zones"', text), (
        "The availability-zones data source must NOT move back into the module: module.network "
        "carries depends_on, which defers it and breaks the subnets' for_each on any change to "
        "the module it depends on."
    )
    # Comment lines dropped first: the module explains at length why this filter is wrong, and
    # naming the thing you are forbidding is not the same as doing it.
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert 'state = "available"' not in code, (
        "Do not filter the availability zones by state: it makes membership depend on AZ HEALTH, "
        "so an impaired zone recreates the whole network during an availability-zone event."
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
    assert re.search(r'name\s*=\s*"\$\{local\.name_prefix\}-vpc-flow-logs-role"', body), (
        "The flow-logs role's NAME must be ${local.name_prefix}-vpc-flow-logs-role. Asserted on "
        "the name attribute rather than on the body, which a tag value would also satisfy."
    )
    grant = GRANT.read_text()
    assert "vpc-flow-logs-role" in grant and "vpc-flow-logs.amazonaws.com" in grant, (
        "The deploy grant no longer scopes a role pattern and a PassedToService for flow logs. "
        "Both sides of this agreement are read here so a rename on either one reddens."
    )
