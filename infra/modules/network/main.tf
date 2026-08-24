# ── The VPC the container runs in, and the route it deliberately does not have ──
#
# Two availability zones. Public subnets carry the load balancer and reach the internet through
# an internet gateway. Private subnets carry the ECS tasks and have NO DEFAULT ROUTE AT ALL —
# there is no NAT gateway in this design, and the three destinations a task actually needs are
# reached by VPC endpoints instead (endpoints.tf).
#
# THE DECIDING ARGUMENT IS NOT COST. Interface endpoints bill per-AZ-hour plus data processed and
# a NAT gateway bills per-hour plus per-GB; across two AZs at this traffic level the endpoint set
# happens to be cheaper, but that is a fact that could change. What does not change is that "no
# route to the internet" is a property a reviewer reads off a route table, where "a NAT gateway
# nobody uses" is a claim somebody re-argues every year.
#
# THE RESIDUAL, STATED PLAINLY. Any future destination with no VPC endpoint is unreachable from a
# task, and it fails as a CONNECT TIMEOUT rather than a 403 — the slowest failure there is to
# diagnose. Foreclosed today: ECS Exec (ssmmessages, ssm, ec2messages), Secrets Manager, SSM
# Parameter Store, any runtime package fetch, and any non-AWS host. The remedy for an AWS
# destination is another interface endpoint; for a non-AWS one there is none short of a NAT
# gateway, and that is a spec rather than a patch.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  # SORTED, and that is what makes the CIDR assignment stable. Subnets are keyed by AZ NAME so a
  # reordering of the data source cannot recreate them — but the CIDR still has to come from
  # somewhere, and deriving it from the source's own ordering would reintroduce exactly the
  # recreate the keying exists to prevent. Sorting decides the pairing once.
  azs = slice(sort(data.aws_availability_zones.available.names), 0, 2)

  subnets = {
    for index, az in local.azs : az => {
      public  = cidrsubnet(var.vpc_cidr, 4, index)
      private = cidrsubnet(var.vpc_cidr, 4, index + 8)
    }
  }
}

# Both DNS settings are required, not merely advisable: `private_dns_enabled` on an interface
# endpoint silently resolves to nothing without them, so the endpoints would exist, apply green,
# and every call would still try to reach the public endpoint over a route that does not exist.
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = local.name_prefix }
}

# The default security group AWS creates with the VPC allows all traffic between its own members.
# Nothing is placed in it, but adopting it with no rules at all is cheaper than explaining why an
# unused permissive group is harmless.
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

  # The load balancer brings its own public addresses. Nothing else launches here, so an
  # automatic public IP would only ever be given to something that should not have one.
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

# ONE PRIVATE ROUTE TABLE PER AZ, and none of them carries a `0.0.0.0/0` entry of any kind. The
# only route these ever gain is the S3 gateway endpoint's prefix-list route, which the endpoint
# adds by association (endpoints.tf) rather than by a route resource here.
#
# Per-AZ rather than shared: a gateway endpoint associates with route tables, and keeping them
# separate leaves room for an AZ to be treated differently later without moving every subnet.
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
# The task group lives HERE rather than with the service, because the endpoint group's ingress
# rule references it and a module must not depend on a group its own dependent owns. The load
# balancer's group, and the two rules that name both sides, belong to the module that creates the
# load balancer.
#
# No rules are attached here at all. Every one of them names a group from the other module, so
# they are declared there — a rule split across two modules is a rule nobody can read.
resource "aws_security_group" "task" {
  name        = "${local.name_prefix}-spa-task"
  description = "The SPA container. Ingress from the load balancer only; egress to the VPC endpoints only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-spa-task" }
}

# ── Flow logs ─────────────────────────────────────────────────────────────────
# A private subnet with no default route fails as a connect timeout, and a timeout leaves nothing
# behind. Flow logs are the only record of a rejected packet, which is what makes them worth their
# cost in a design whose whole premise is that certain traffic cannot leave.

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/aws/vpc/${local.name_prefix}-flow-logs"
  retention_in_days = 14
}

resource "aws_iam_role" "flow_logs" {
  name               = "${local.name_prefix}-vpc-flow-logs-role"
  assume_role_policy = templatefile("${path.module}/policies/flow-logs-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "flow-logs"
  role = aws_iam_role.flow_logs.id

  policy = templatefile("${path.module}/policies/flow-logs-permissions.json.tftpl", {
    log_group_arn = aws_cloudwatch_log_group.flow_logs.arn
  })
}

resource "aws_flow_log" "main" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn             = aws_iam_role.flow_logs.arn
  max_aggregation_interval = 600

  tags = { Name = local.name_prefix }

  depends_on = [aws_iam_role_policy.flow_logs]
}
