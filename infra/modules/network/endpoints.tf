# ── The endpoints: every AWS service the task reaches, kept off the NAT gateway ──
#
# Four interface endpoints and two gateway endpoints. Task startup (the image pull, the log
# stream, the secret ECS injects) travels only these, so a task starts whether or not the NAT
# gateway works. EVERY ONE OF THEM APPLIES GREEN WHEN IT IS WRONG. The S3 gateway endpoint is NOT an optimisation — ECR serves image layers from S3, and
# without it the pull fails as `CannotPullContainerError`, which reads like authorization and is
# not. README.md.

resource "aws_security_group" "endpoints" {
  name        = "${local.name_prefix}-vpc-endpoints"
  description = "The interface endpoints. Ingress on 443 from the task security group only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-vpc-endpoints" }
}

# FROM THE TASK GROUP, never from the VPC CIDR — a CIDR rule would also admit anything else
# that ever lands in these subnets.
resource "aws_vpc_security_group_ingress_rule" "endpoints_from_tasks" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS from the SPA tasks"
}

# NO EGRESS RULE, deliberately — security groups are stateful, so the endpoint's replies travel
# the connection the task opened. Do not add a placeholder. README.md.

# `private_dns_enabled` needs the VPC's two DNS settings. Without them the endpoints exist,
# apply green, and nothing uses them. README.md.
resource "aws_vpc_endpoint" "interface" {
  for_each = toset(["ecr.api", "ecr.dkr", "logs", "ssm"])

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for subnet in aws_subnet.private : subnet.id]
  security_group_ids  = [aws_security_group.endpoints.id]

  tags = { Name = "${local.name_prefix}-${each.key}" }
}

# THE ASSOCIATION SET IS THE WHOLE POINT — a gateway endpoint on the wrong route table applies
# green and does nothing. Derived from the resource, never listed, so a later AZ cannot be
# forgotten.
#
# NO ENDPOINT POLICY, deliberately. TIGHTEN THIS TO THE STARPORT BUCKET the moment a task has a
# reason to reach S3 on its own behalf — the task role holding nothing is what bounds it today,
# and that bound disappears at exactly that point. README.md.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for table in aws_route_table.private : table.id]

  tags = { Name = "${local.name_prefix}-s3" }
}

# The session store's traffic. A GATEWAY endpoint, so DynamoDB is reached without the NAT gateway
# and without its per-gigabyte charge; the prefix-list route it adds is more specific than the
# default route, so it wins. Route tables derived, never listed, exactly as S3's.
#
# NO ENDPOINT POLICY: the task role names the one table it may use, which is the bound.
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for table in aws_route_table.private : table.id]

  tags = { Name = "${local.name_prefix}-dynamodb" }
}
