# The A-alias record pointing spa_host at this load balancer. It lives with the target rather
# than with the certificate, because this is the only place the target's hosted-zone id and
# its DNS name are both known.
#
# The zone id comes in as a variable and is never looked up: `data "aws_route53_zone"` needs
# route53:ListHostedZonesByName, which the deploy role does not hold, and the failure would
# read as a mysterious AccessDenied on the first plan.
resource "aws_route53_record" "spa" {
  zone_id = var.route53_zone_id
  name    = var.spa_host
  type    = "A"

  alias {
    name    = aws_lb.spa.dns_name
    zone_id = aws_lb.spa.zone_id

    # Health evaluation belongs to the target group, which knows what healthy means here. With
    # this on, a service scaled to zero — which is exactly how this ships — would take the
    # record out of DNS and turn a deliberate state into a resolution failure.
    evaluate_target_health = false
  }
}
