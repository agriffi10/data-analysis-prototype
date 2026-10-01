# ── Front-door certificates ───────────────────────────────────────────────────
# The two regional ACM certificates fronting the SPA and the API, with their DNS
# validation records and the validations that wait on issuance.
#
# At root rather than in a module because both consumers are different modules —
# the API's custom domain and the SPA's HTTPS listener — so neither can own them.
# The alias records are NOT here: each lives with the target it points at, which
# is the only place the target's zone id and hostname are both known.
#
# THE SPA'S CERTIFICATE IS ON THE WEB TIER'S OFF SWITCH, because ACM renews a public
# certificate only while a service uses it. Kept through an off period that spans its
# renewal window, it would expire, the provider would read the validation as gone, and
# every later apply would fail recreating it. Destroyed with the listener, it is simply
# requested again when the tier comes back. infra/info/web-tier.md.

resource "aws_acm_certificate" "spa" {
  count = local.web_tier_enabled ? 1 : 0

  domain_name       = local.spa_host
  validation_method = "DNS"

  # ACM issues a NEW certificate before the old one is destroyed. Without this a
  # domain-name change destroys the certificate a live listener still references.
  lifecycle {
    create_before_destroy = true

    # Two equal subdomains is the one bad pairing neither variable can refuse on its
    # own, and it fails destructively rather than loudly: two certificates for one
    # host, then two validation records with the same name and type, both overwriting.
    # The second UPSERT replaces the first's token, so one validation can never resolve
    # and waits out its full timeout with the apply already half done.
    precondition {
      condition     = var.spa_subdomain != var.api_subdomain
      error_message = "spa_subdomain and api_subdomain must differ — equal values put the SPA and the API on one host."
    }
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-spa"
  }

  # base grants acm: and route53: — the ONLY place either is granted — and this file is at
  # root, so nothing ordered these against that grant before. Terraform was free to schedule
  # RequestCertificate concurrently with the attachment that authorises it; earlier applies
  # won that race because the grant already existed, which is not the same as being safe.
  depends_on = [module.base]
}

resource "aws_acm_certificate" "api" {
  domain_name       = local.api_host
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-api"
  }

  # base grants acm: and route53: — the ONLY place either is granted — and this file is at
  # root, so nothing ordered these against that grant before. Terraform was free to schedule
  # RequestCertificate concurrently with the attachment that authorises it; earlier applies
  # won that race because the grant already existed, which is not the same as being safe.
  depends_on = [module.base]
}

# One validation record per certificate. for_each over domain_validation_options
# rather than an index: the set is keyed by domain name, so adding a SAN later
# does not renumber the existing records and propose replacing them. The SPA's
# reads its certificate through a conditional, which keeps the same keys while the
# tier is on and yields none while it is off; the index in the branch not taken is
# never reported. NOT flatten(): over a new certificate with a second name it is
# unknown at plan, because a set whose elements are partly unknown has no known
# length, and every switch-on would fail on an invalid for_each.
resource "aws_route53_record" "spa_certificate_validation" {
  for_each = {
    for option in(local.web_tier_enabled ? aws_acm_certificate.spa[0].domain_validation_options : []) :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_route53_record" "api_certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.api.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

# ACM resolves the validation record over PUBLIC DNS, so these wait on the parent
# domain being delegated as well as on the record existing.
#
# The explicit create timeout is the point. The provider's default is 75 minutes
# and both workflow jobs cap at 30, so a validation that cannot resolve is killed
# by the runner MID-APPLY rather than failing as a Terraform error — which strands
# the backend's state lock and blocks every later apply until it is cleared by
# hand. Ten minutes is well clear of the seconds this takes once the record is
# live, and lands the failure inside the job's own budget where it reads as broken
# instead of as stuck.
resource "aws_acm_certificate_validation" "spa" {
  count = local.web_tier_enabled ? 1 : 0

  certificate_arn         = aws_acm_certificate.spa[0].arn
  validation_record_fqdns = [for record in aws_route53_record.spa_certificate_validation : record.fqdn]

  timeouts {
    create = "10m"
  }
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for record in aws_route53_record.api_certificate_validation : record.fqdn]

  timeouts {
    create = "10m"
  }
}
