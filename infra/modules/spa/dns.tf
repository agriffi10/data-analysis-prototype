# The zone id is a VARIABLE, never a lookup: `data "aws_route53_zone"` needs
# route53:ListHostedZonesByName, which the deploy role does not hold, and the failure reads as
# a mysterious AccessDenied on the first plan.
resource "aws_route53_record" "spa" {
  zone_id = var.route53_zone_id
  name    = var.spa_host
  type    = "A"

  alias {
    name    = aws_lb.spa.dns_name
    zone_id = aws_lb.spa.zone_id

    # With this ON, a service scaled to zero — exactly how this ships — takes the record out
    # of DNS and turns a deliberate state into a resolution failure.
    evaluate_target_health = false
  }
}
