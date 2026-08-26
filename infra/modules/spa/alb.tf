# ── The front door ────────────────────────────────────────────────────────────
# An internet-facing load balancer in the PUBLIC subnets, forwarding to tasks in the private
# ones. Both halves matter: an ALB placed in the private subnets applies green and yields an
# address nothing can reach. Its security groups and their rules are in security-groups.tf.

resource "aws_lb" "spa" {
  name               = local.spa_name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  # Reject a request carrying a header the ALB cannot parse rather than forwarding it with the
  # header silently dropped — the difference matters wherever a header carries an identity.
  drop_invalid_header_fields = true

  # A ONE-WAY DOOR while it is on: the balancer's own name is ForceNew, so a rename — or any
  # teardown — fails at DeleteLoadBalancer until this is turned off in a SEPARATE apply first,
  # and Terraform's message names the API refusal rather than this line. The deploy role does
  # hold ModifyLoadBalancerAttributes, so that first apply is CI's to run rather than a human's.
  enable_deletion_protection = true

  access_logs {
    bucket  = var.admin_bucket_name
    prefix  = var.access_logs_prefix
    enabled = true
  }

  # ALB validates the destination bucket's policy AND writes a test object when access
  # logging is enabled. This resource names the bucket by NAME, so Terraform builds no
  # implicit edge to the policy that permits it — both orders are legal and one of them is a
  # 403 on create.
  depends_on = [aws_s3_bucket_policy.alb_access_logs]

  tags = { Name = local.spa_name }
}

# THE PORT IS ForceNew AND THIS GROUP CANNOT BE REPLACED IN ONE APPLY. A listener forwards to
# it, so `DeleteTargetGroup` returns `ResourceInUse` and a destroy-then-create stops half done.
# `name_prefix` + `create_before_destroy` is the usual answer and is NOT available here: the
# deploy role's grant is scoped to `targetgroup/${project}-*-spa*`, and a generated prefix does
# not match it. Changing the container's port is therefore two applies — a second group and a
# listener re-point, then the first group's removal.
resource "aws_lb_target_group" "spa" {
  name = "${local.spa_name}-tg"

  # ELBv2 caps a target-group name at 32 characters and refuses a longer one at CREATE, with a
  # ValidationError naming nothing about this file. project_name is not length-bounded, so the
  # refusal happens at plan instead.
  lifecycle {
    precondition {
      condition     = length("${local.spa_name}-tg") <= 32
      error_message = "The target group's name exceeds ELBv2's 32-character limit. Shorten project_name or environment."
    }
  }
  vpc_id      = var.vpc_id
  target_type = "ip"
  port        = var.container_port
  protocol    = "HTTP"

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = { Name = "${local.spa_name}-tg" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.spa.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  # From the VALIDATION, not the certificate: same ARN, but only this one creates the edge
  # that stops a clean rebuild attaching a still-pending certificate to the listener.
  certificate_arn = var.spa_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.spa.arn
  }
}

# ITS ONLY ACTION IS THE REDIRECT. No forward, no fixed response — a listener that can serve
# anything over port 80 is one that can serve the app over it.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.spa.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      protocol    = "HTTPS"
      port        = "443"
      status_code = "HTTP_301"
    }
  }
}

# ── The admin bucket's first policy ───────────────────────────────────────────
# It lives here, in the module that needs it, rather than beside the bucket: the analytics
# module has no interest in load-balancer logs, and the policy's condition is built from THIS
# module's names. `aws_s3_bucket_policy` is whole-document, so this being the bucket's only
# policy is a property a test pins rather than a convention.
#
# THE SERVICE-PRINCIPAL FORM, not the aws_elb_service_account data source. AWS heads its own
# published account-principal policy "Legacy bucket policy … we recommend that you replace
# it", and that form delivers through an ACL grant — which this bucket, at BucketOwnerEnforced,
# does not accept at all.
#
# NO `Deny` IN IT. One would also stop the deploy role's refresh read of the bucket, and every
# subsequent plan would propose a destructive recreate of a bucket holding the structured logs.
resource "aws_s3_bucket_policy" "alb_access_logs" {
  bucket = var.admin_bucket_name

  policy = templatefile("${path.module}/policies/alb-access-logs-bucket-policy.json.tftpl", {
    # The account id is never wildcarded: it is a segment of the key ALB writes to, and a
    # wildcard there would accept another account's load balancer's logs into this bucket.
    bucket_arn         = "arn:aws:s3:::${var.admin_bucket_name}"
    access_logs_prefix = var.access_logs_prefix
    account_id         = var.account_id
    # ArnLike on a CONSTRUCTED pattern rather than the load balancer's own ARN: the real ARN
    # carries a generated suffix that is unknown at plan, and referencing it here would close a
    # cycle through the depends_on above.
    load_balancer_arn_pattern = "arn:aws:elasticloadbalancing:${var.aws_region}:${var.account_id}:loadbalancer/app/${local.spa_name}/*"
  })
}
