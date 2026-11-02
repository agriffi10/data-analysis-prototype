resource "aws_route53_record" "portal" {
  zone_id = var.route53_zone_id
  name    = var.spa_host
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.portal.domain_name
    zone_id                = aws_cloudfront_distribution.portal.hosted_zone_id
    evaluate_target_health = false
  }
}
