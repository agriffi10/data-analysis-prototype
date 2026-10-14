# ── The VPC the container runs in, and the route it deliberately does not have ──
#
# Private subnets carry the ECS tasks and have NO DEFAULT ROUTE AT ALL. There is no NAT gateway
# in this design; the residual is that any destination without an endpoint fails as a CONNECT
# TIMEOUT, which is why flow logs are on. README.md.
#
# The AZ list is filtered on `opt-in-not-required`, NOT on `state`. A state filter ties
# membership to AZ health and recreates every subnet during a zone event; the opt-in filter also
# excludes Local and Wavelength Zones, which sort BEFORE ordinary ones. README.md.
locals {
  name_prefix = "${var.project_name}-${var.environment}"

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

# ONE PER AZ, and none carries a `0.0.0.0/0` entry of any kind. The only route these gain is the
# S3 gateway endpoint's prefix-list route, added by association rather than declared here.
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

# ── Security groups ───────────────────────────────────────────────────────────
# The task group lives HERE because the endpoint group's ingress rule references it. Its own
# rules live with the LOAD BALANCER, and are not duplicated here.
#
# THIS GROUP PERMITS NOTHING ON ITS OWN, AND THAT IS CORRECT. Every leg of task startup travels
# this ENI, so a pull attempted with the load balancer module's rules absent WILL time out. Do
# not read such a timeout as an endpoint defect. README.md.
resource "aws_security_group" "task" {
  name        = "${local.name_prefix}-spa-task"
  description = "The SPA container. Ingress from the load balancer only; egress to the VPC endpoints only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-spa-task" }
}

# ── Flow logs ─────────────────────────────────────────────────────────────────
# A connect timeout leaves nothing behind. These are the only record of a rejected packet.

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/aws/vpc/${local.name_prefix}-flow-logs"
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
    log_group_arn = aws_cloudwatch_log_group.flow_logs.arn
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
