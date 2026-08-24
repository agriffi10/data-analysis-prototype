# ── The endpoints that replace the NAT gateway ────────────────────────────────
#
# Three interface endpoints and one gateway endpoint. A Fargate task on platform version 1.4.0 in
# a private subnet with no default route needs exactly these to start and to log, and every one of
# them applies green when it is wrong.
#
# THE S3 GATEWAY ENDPOINT IS NOT AN OPTIMISATION. ECR stores image layers in S3, so with both ECR
# interface endpoints present and this one missing the pull fails with `CannotPullContainerError`
# — a message that reads like an authorization problem and is not. It is also the reason the
# endpoint is a GATEWAY rather than an interface: a gateway endpoint installs a prefix-list route
# in the tables it is associated with, which is how traffic reaches it with no default route at
# all, and a security-group egress rule to a CIDR does not match that traffic.

resource "aws_security_group" "endpoints" {
  name        = "${local.name_prefix}-vpc-endpoints"
  description = "The interface endpoints. Ingress on 443 from the task security group only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-vpc-endpoints" }
}

# FROM THE TASK GROUP, never from the VPC CIDR. A CIDR rule would also admit anything else that
# ever lands in these subnets; naming the group means the endpoint's reachable set is exactly the
# set of things wearing that group.
resource "aws_vpc_security_group_ingress_rule" "endpoints_from_tasks" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS from the SPA tasks"
}

# The endpoints answer on the connection the task opened; they originate nothing.
resource "aws_vpc_security_group_egress_rule" "endpoints_none" {
  security_group_id = aws_security_group.endpoints.id
  cidr_ipv4         = "127.0.0.1/32"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Placeholder. An interface endpoint initiates no outbound connection."
}

# `private_dns_enabled` is what makes this transparent: the task calls the ordinary public
# hostname and DNS resolves it to the endpoint's private address. Without it — or without the
# VPC's two DNS settings, which main.tf explains — the endpoints exist and nothing uses them.
resource "aws_vpc_endpoint" "interface" {
  for_each = toset(["ecr.api", "ecr.dkr", "logs"])

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for subnet in aws_subnet.private : subnet.id]
  security_group_ids  = [aws_security_group.endpoints.id]

  tags = { Name = "${local.name_prefix}-${each.key}" }
}

# THE ASSOCIATION SET IS THE WHOLE POINT. A gateway endpoint associated with the wrong route
# table applies green and does nothing — there is no error, no drift, and the only symptom is a
# pull that cannot complete. `route_table_ids` is therefore every private route table, derived
# from the resource rather than listed, so an AZ added later cannot be forgotten here.
#
# NO ENDPOINT POLICY. The default is full access, and a restrictive one would have to allow
# `prod-us-east-1-starport-layer-bucket`, the AWS-owned bucket ECR serves layers from — omitting
# it breaks the pull with the same unreadable `CannotPullContainerError` the endpoint exists to
# prevent. A policy that must name an undocumented AWS-internal bucket to work is a worse
# guarantee than no policy at all.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for table in aws_route_table.private : table.id]

  tags = { Name = "${local.name_prefix}-s3" }
}
