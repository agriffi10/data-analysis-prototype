# The zone id is a VARIABLE, never a lookup: `data "aws_route53_zone"` needs
# route53:ListHostedZonesByName, which the deploy role does not hold, and the failure reads as
# a mysterious AccessDenied on the first plan.
resource "aws_route53_record" "api" {
  zone_id = var.route53_zone_id
  name    = var.api_host
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
