# ── The front door ────────────────────────────────────────────────────────────
# Internet-facing, in the PUBLIC subnets, forwarding to tasks in the private ones. In the
# private subnets it applies green and yields an address nothing can reach. README.md.

resource "aws_lb" "spa" {
  name               = local.spa_name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  # Reject rather than forward with the header silently dropped — this matters wherever a
  # header carries an identity.
  drop_invalid_header_fields = true

  # A ONE-WAY DOOR while on: the name is ForceNew, so a rename or teardown fails at
  # DeleteLoadBalancer until this is turned off in a SEPARATE apply first. README.md.
  enable_deletion_protection = true

  access_logs {
    bucket  = var.admin_bucket_name
    prefix  = var.access_logs_prefix
    enabled = true
  }

  # ALB validates the bucket policy AND writes a test object. The bucket is named by NAME, so
  # Terraform builds no implicit edge — both orders are legal and one is a 403 on create.
  depends_on = [aws_s3_bucket_policy.alb_access_logs]

  tags = { Name = local.spa_name }
}

# THE PORT IS ForceNew AND THIS GROUP CANNOT BE REPLACED IN ONE APPLY — a listener forwards to
# it, so DeleteTargetGroup returns ResourceInUse. name_prefix + create_before_destroy does not
# match the deploy role's grant. Changing the port is TWO APPLIES. README.md.
resource "aws_lb_target_group" "spa" {
  name = "${local.spa_name}-tg"

  # ELBv2 caps this at 32 characters and refuses a longer one at CREATE, with a
  # ValidationError naming nothing about this file. This moves the refusal to plan.
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

  # From the VALIDATION, not the certificate: same ARN, but only that one creates the edge
  # stopping a clean rebuild from attaching a still-pending certificate.
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

# ── The admin bucket's first and ONLY policy ──────────────────────────────────
# aws_s3_bucket_policy is whole-document, so "the only policy" is a property a TEST pins.
#
# THE SERVICE-PRINCIPAL FORM, not aws_elb_service_account: that form delivers through an ACL
# grant, which this bucket at BucketOwnerEnforced does not accept at all.
#
# NO `Deny` IN IT — one would stop the deploy role's refresh read and make every later plan
# propose a destructive recreate of the bucket holding the structured logs. README.md.
resource "aws_s3_bucket_policy" "alb_access_logs" {
  bucket = var.admin_bucket_name

  # NO CONDITIONS, AND TWO PRINCIPALS — both measured, on three failed applies. ELB validates
  # this policy with its own PutObject, and a condition on a key that call does not populate
  # FAILS CLOSED. Do not re-add SourceAccount or SourceArn.
  #
  # What still bounds it: the Resource pins the account id as a path SEGMENT, and a balancer
  # writes under its OWN account's id. Narrowing to one principal is OWED. README.md.
  policy = templatefile("${path.module}/policies/alb-access-logs-bucket-policy.json.tftpl", {
    # NEVER wildcarded — it is a segment of the key ALB writes to, and a wildcard would
    # accept another account's balancer's logs into this bucket.
    bucket_arn         = "arn:aws:s3:::${var.admin_bucket_name}"
    access_logs_prefix = var.access_logs_prefix
    account_id         = var.account_id
    # Read at ROOT and passed in: a data source here would be deferred to apply by this
    # module's own depends_on.
    elb_account_arn = var.elb_account_arn
  })
}
