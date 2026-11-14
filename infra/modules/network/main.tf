# ── The VPC the container runs in, and the one way out of it ──────────────────
#
# Private subnets carry the ECS tasks. AWS services are reached through endpoints; the portal
# server's two internet destinations (the Cognito domain's token endpoint and the API's custom
# domain) go out through ONE NAT gateway, which exists only while the web tier is switched on.
# Flow logs record what the tasks reached. README.md.
#
# The AZ list is filtered on `opt-in-not-required`, NOT on `state`. A state filter ties
# membership to AZ health and recreates every subnet during a zone event; the opt-in filter also
# excludes Local and Wavelength Zones, which sort BEFORE ordinary ones. README.md.
locals {
  name_prefix = "${var.project_name}-${var.environment}"

  # BUILT, not read from the log group: on a plan that creates the group its ARN is unknown, and
  # the plan-time IAM scan cannot read a policy that names it.
  flow_log_group_name = "/aws/vpc/${local.name_prefix}-flow-logs"
  flow_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.flow_log_group_name}"

  # SORTED, which is what makes the CIDR assignment stable. The sort fixes the ORDER; the
  # filter fixes the MEMBERSHIP. Both are load-bearing.
  azs = slice(sort(var.availability_zone_names), 0, 2)

  subnets = {
    for index, az in local.azs : az => {
      public  = cidrsubnet(var.vpc_cidr, 4, index)
      private = cidrsubnet(var.vpc_cidr, 4, index + 8)
    }
  }
}

# Both DNS settings are REQUIRED, not advisable: `private_dns_enabled` silently resolves to
# nothing without them, and every call still tries a route that does not exist.
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = local.name_prefix }
}

# Adopted with no rules so the VPC's default permissive group cannot be used.
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-default-do-not-use" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = local.name_prefix }
}

resource "aws_subnet" "public" {
  for_each = local.subnets

  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = each.value.public

  # The load balancer brings its own addresses; nothing else launches here.
  map_public_ip_on_launch = false

  tags = { Name = "${local.name_prefix}-public-${each.key}" }
}

resource "aws_subnet" "private" {
  for_each = local.subnets

  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = each.value.private

  tags = { Name = "${local.name_prefix}-private-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# ONE PER AZ. Each gains the two gateway endpoints' prefix-list routes by association, and one
# default route, to the NAT gateway, declared below as its own resource and never inline.
resource "aws_route_table" "private" {
  for_each = local.subnets

  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-private-${each.key}" }
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

# ── The NAT gateway: the server's way to Cognito and the API ──────────────────
# ONE, zonal, in the first sorted zone's public subnet. The tier has no users and is on only while
# someone works, so a zone outage costs what switching the tier off costs. The pinned provider has
# no regional mode.
#
# BOTH WAIT FOR THE INTERNET GATEWAY. A public NAT gateway created before the gateway is attached
# fails (`Gateway.NotAttached`), and nothing in either argument list orders them; a switch-on from
# nothing is the only apply that can hit it, and no check runs one. README.md.
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = { Name = "${local.name_prefix}-nat" }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[local.azs[0]].id

  tags = { Name = "${local.name_prefix}-nat" }

  depends_on = [aws_internet_gateway.main]
}

# Every private table's one default route, derived from the tables so a later zone cannot be left
# without one.
resource "aws_route" "private_default" {
  for_each = aws_route_table.private

  route_table_id         = each.value.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}

# ── Security groups ───────────────────────────────────────────────────────────
# The task group lives HERE because the endpoint group's ingress rule references it. Its own
# rules live with the LOAD BALANCER, and are not duplicated here.
#
# THIS GROUP PERMITS NOTHING ON ITS OWN, AND THAT IS CORRECT. Every leg of task startup travels
# this ENI, so a pull attempted with the load balancer module's rules absent WILL time out. Do
# not read such a timeout as an endpoint defect. README.md.
#
# Its description predates the NAT gateway, and the egress rules in `spa` now also reach HTTPS on
# the internet. It is not reworded: a description is ForceNew, and replacing a group that running
# tasks' interfaces hold fails the apply.
resource "aws_security_group" "task" {
  name        = "${local.name_prefix}-spa-task"
  description = "The SPA container. Ingress from the load balancer only; egress to the VPC endpoints only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-spa-task" }
}

# ── Flow logs ─────────────────────────────────────────────────────────────────
# A connect timeout leaves nothing behind. These are the only record of a rejected packet.

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = local.flow_log_group_name
  retention_in_days = 14
}

resource "aws_iam_role" "flow_logs" {
  name = "${local.name_prefix}-vpc-flow-logs-role"
  assume_role_policy = templatefile("${path.module}/policies/flow-logs-trust.json.tftpl", {
    account_id = var.account_id
    aws_region = var.aws_region
  })
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "flow-logs"
  role = aws_iam_role.flow_logs.id

  # AWS publishes this with all five actions on `Resource: "*"`. Three are scoped to the group
  # here; the wildcard holds only `logs:DescribeLogGroups`, which has no resource type.
  # `logs:CreateLogGroup` is left out on purpose: delivery outlives the flow log by seconds and
  # IAM honours a deleted grant as long, so destroy order cannot stop the role recreating this
  # group after a switch-off. Reasoning in the README.
  policy = templatefile("${path.module}/policies/flow-logs-permissions.json.tftpl", {
    log_group_arn = local.flow_log_group_arn
  })
}

resource "aws_flow_log" "main" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn         = aws_iam_role.flow_logs.arn
  # 60, not AWS's default 600 — ten minutes of aggregation is long enough that the person
  # debugging gives up and adds a NAT gateway.
  max_aggregation_interval = 60

  tags = { Name = local.name_prefix }

  depends_on = [aws_iam_role_policy.flow_logs]
}
