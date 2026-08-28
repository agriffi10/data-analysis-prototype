# ── Origin Access Control ────────────────────────────────────────────────────

resource "aws_cloudfront_origin_access_control" "static_assets" {
  name                              = "${var.project_name}-oac"
  description                       = "OAC for ${var.project_name} static assets"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── Response Headers Policy ───────────────────────────────────────────────────
# Closes Checkov CKV2_AWS_32 and the 2026-08-03 ZAP baseline's Mediums.
#
# THE CSP STRING IS NOT BUILT HERE — it arrives assembled from root, so one computation feeds
# both delivery paths and a root-level check can read it. README.md.

resource "aws_cloudfront_response_headers_policy" "portal" {
  name    = "${var.project_name}-security-headers"
  comment = "Security response headers for the ${var.project_name} SPA"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      # Satisfies CKV_AWS_259, and is INERT on its own — browsers act on the preload list,
      # which we have not submitted to. Do NOT submit this domain to hstspreload.org:
      # preload is close to irreversible and this name is temporary. README.md.
      preload  = true
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

    # ENFORCING, after a signed-in report-only pass reported no violations.
    content_security_policy {
      content_security_policy = var.content_security_policy
      override                = true
    }
  }

  custom_headers_config {
    # No first-class CloudFront field exists for these three.
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

    # DELIBERATELY ABSENT: Cross-Origin-Embedder-Policy. ZAP alert 90004 stays open BY
    # DECISION (docs/security-baseline.md). Do not "fix" it here — README.md.
  }

  remove_headers_config {
    # The S3 origin's banner reaches the viewer as `server: AmazonS3`.
    items {
      header = "Server"
    }
    # Leaks the origin's encryption mode to anyone running curl.
    items {
      header = "x-amz-server-side-encryption"
    }
  }
}

# ── CloudFront Distribution ───────────────────────────────────────────────────
# Serves the SPA over HTTPS. Custom error responses for 403/404 return index.html
# so that SPA client-side routes work on direct load or browser refresh.

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

# The runtime configuration document must NEVER be answered from an edge cache, and
# CachingOptimized cannot express that — CloudFront applies its MinTTL even when the origin
# sends `no-store`. 0/0/0 makes the guarantee a property of the distribution rather than a
# flag on one upload step. README.md.
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_cloudfront_distribution" "portal" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${var.project_name} SPA"

  origin {
    domain_name              = aws_s3_bucket.static_assets.bucket_regional_domain_name
    origin_id                = "static-assets-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.static_assets.id
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "static-assets-origin"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.portal.id
  }

  # `ResponseHeadersPolicyId` is per-behaviour and is NOT inherited from the default one.
  # Omitting it serves config.json with no CSP and no HSTS, on a URL any scanner finds.
  ordered_cache_behavior {
    path_pattern               = "config.json"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "static-assets-origin"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.portal.id
  }

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
    cloudfront_default_certificate = true
  }
}
