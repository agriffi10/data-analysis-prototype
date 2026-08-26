# The A-alias record pointing api_host at this API's regional endpoint. It lives with the
# target rather than with the certificate, because this is the only place the target's
# hosted-zone id and its domain name are both known.
#
# The zone id comes in as a variable and is never looked up: `data "aws_route53_zone"`
# needs route53:ListHostedZonesByName, which the deploy role does not hold, and the
# failure would read as a mysterious AccessDenied on the first plan.
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
