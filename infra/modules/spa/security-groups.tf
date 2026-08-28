# ── The two groups, and every rule that names one of them ─────────────────────
# The ALB's group is created here; the TASK group belongs to modules/network, which creates it
# with NO rules on purpose. Every rule on it is declared here. README.md.

resource "aws_security_group" "alb" {
  name        = "${local.spa_name}-alb"
  description = "The SPA load balancer. Ingress 80/443 from the internet; egress to the tasks only."
  vpc_id      = var.vpc_id

  tags = { Name = "${local.spa_name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS from the internet"
}

# ONLY to answer the redirect — the listener's sole action is a 301, but the port has to be
# reachable for a browser that types the bare host to be told where to go.
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from the internet, redirected to HTTPS"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_tasks" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = var.task_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  description                  = "To the SPA tasks"
}

# ── The task group's rules ────────────────────────────────────────────────────
# Its reciprocal — the endpoints' ingress from this group — is declared beside the endpoints
# and must NOT be repeated here, or the apply fails with InvalidPermission.Duplicate.

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = var.task_security_group_id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  description                  = "From the load balancer"
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_endpoints" {
  security_group_id            = var.task_security_group_id
  referenced_security_group_id = var.vpc_endpoint_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "To the interface endpoints: the ECR credential fetch, the registry API and the log stream"
}

# BY PREFIX LIST, never by CIDR. The S3 endpoint is a GATEWAY, and a CIDR rule naming S3's
# ranges does not match its traffic — the symptom is an image pull that HANGS.
resource "aws_vpc_security_group_egress_rule" "tasks_to_s3" {
  security_group_id = var.task_security_group_id
  prefix_list_id    = var.s3_prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "To S3 through the gateway endpoint: the image layers"
}
