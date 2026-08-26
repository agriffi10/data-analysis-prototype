# ── The two groups, and every rule that names one of them ─────────────────────
# The load balancer's group is created here. The TASK group is not: it belongs to the network
# module, which creates it with no rules on purpose, because every rule on it also names the
# load balancer's group and a rule split across two modules is a rule nobody can read.

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

# Port 80 exists ONLY to answer the redirect. The listener's sole action is a 301, so nothing
# is served over it — but the port has to be reachable for a browser that types the bare host
# to be told where to go.
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
# The group itself belongs to the network module, which created it with NO rules on purpose:
# every rule names a group this module also names. Its reciprocal — the endpoints' ingress
# from this group — is declared beside the endpoints and must NOT be repeated here, or the
# apply fails with InvalidPermission.Duplicate.

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

# BY PREFIX LIST, never by CIDR. ECR stores image layers in S3 and the S3 endpoint is a
# GATEWAY: its traffic is matched by the managed prefix list the endpoint installs a route
# for. A CIDR rule naming S3's address ranges does not match it, and the symptom is an image
# pull that hangs rather than one that refuses.
resource "aws_vpc_security_group_egress_rule" "tasks_to_s3" {
  security_group_id = var.task_security_group_id
  prefix_list_id    = var.s3_prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "To S3 through the gateway endpoint: the image layers"
}
