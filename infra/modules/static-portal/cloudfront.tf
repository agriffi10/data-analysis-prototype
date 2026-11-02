locals {
  origin_id = "portal-bucket"

  # AWS's managed policies, by id: read by name they need cloudfront:ListCachePolicies on an
  # AWS-owned resource, for a value AWS publishes and does not change.
  caching_optimized_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  caching_disabled_policy_id  = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
}

resource "aws_cloudfront_origin_access_control" "portal" {
  name                              = "${var.project_name}-${var.environment}-portal"
  description                       = "The portal distribution's access to its bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# The same posture the container's security-headers snippet serves. A test compares the values it
# can read from both: nothing offline observes a response header.
resource "aws_cloudfront_response_headers_policy" "portal" {
  name    = "${var.project_name}-${var.environment}-portal-security-headers"
  comment = "Security response headers for the portal"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      # No preload: it claims a submission to hstspreload.org nobody has made, and that grant is
      # close to irreversible.
      preload  = false
      override = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    content_security_policy {
      content_security_policy = var.content_security_policy
      override                = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
      override = true
    }

    items {
      header   = "Cross-Origin-Opener-Policy"
      value    = "same-origin"
      override = true
    }

    items {
      header   = "Cross-Origin-Resource-Policy"
      value    = "same-origin"
      override = true
    }
  }

  remove_headers_config {
    items {
      header = "Server"
    }
    items {
      header = "x-amz-server-side-encryption"
    }
  }
}

resource "aws_cloudfront_distribution" "portal" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${var.project_name} ${var.environment} portal"
  aliases             = [var.spa_host]
  http_version        = "http2and3"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.portal.bucket_regional_domain_name
    origin_id                = local.origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.portal.id
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = local.caching_optimized_policy_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.portal.id
  }

  # A response headers policy is per behaviour and is not inherited from the default one.
  # CachingOptimized cannot keep this document out of the edge cache: it applies its minimum TTL
  # even to `no-store`.
  ordered_cache_behavior {
    path_pattern               = "config.json"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = local.caching_disabled_policy_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.portal.id
  }

  # Client-side routes survive a direct load and a reload. The bucket grants no ListBucket, so S3
  # answers a missing key with 403, not 404. It covers every path: a missing hashed chunk answers
  # the shell as text/html, which a module script refuses anyway.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.spa_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
