# ── Origin Access Control ────────────────────────────────────────────────────

resource "aws_cloudfront_origin_access_control" "static_assets" {
  name                              = "${var.project_name}-oac"
  description                       = "OAC for ${var.project_name} static assets"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── Response Headers Policy ───────────────────────────────────────────────────
# Closes Checkov CKV2_AWS_32 and every Medium plus six of eight Low
# findings from the 2026-08-03 ZAP baseline — two scanners reporting one gap.
#
# THE POLICY STRING ITSELF IS NOT BUILT HERE. It arrives assembled from root, so
# that one computation feeds both delivery paths — this distribution and the
# container — and so that a root-level check has something it can read. A local
# inside a module is invisible to one, and this module is deleted when the
# distribution is retired, which would orphan the computation the container
# depends on.

resource "aws_cloudfront_response_headers_policy" "portal" {
  name    = "${var.project_name}-security-headers"
  comment = "Security response headers for the ${var.project_name} SPA"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      # `preload` satisfies Checkov CKV_AWS_259, which objects to nothing else
      # (max-age, include_subdomains and override all pass it already).
      #
      # It is INERT on its own: browsers act on the preload list, and entry to
      # that list requires a manual submission at hstspreload.org that we have
      # not made and are not making. So this directive changes no behaviour
      # today — it states an intent, and the cost of stating it is that someone
      # could act on it later.
      #
      # THE ONE THING TO KNOW: preload is close to irreversible once granted,
      # and this is a shared-suffix *.cloudfront.net name that a custom domain
      # will eventually replace (see CKV2_AWS_42). Do NOT submit this domain to
      # hstspreload.org. When the custom domain lands, decide submission there
      # on its own merits.
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

    # ENFORCING, after a signed-in pass against the
    # report-only deploy reported no violations — sign-in and the Query editor
    # running a statement included, which is the path exercising Monaco's
    # worker, its runtime style injection and the Athena/Glue endpoints.
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

    # DELIBERATELY ABSENT: Cross-Origin-Embedder-Policy.
    #
    # `require-corp` exists to enable cross-origin isolation. This app has no use
    # for it — no SharedArrayBuffer, no high-resolution timers — so it would buy
    # a scanner Low in exchange for a real risk of breaking subresource loads.
    # ZAP alert 90004 therefore stays open BY DECISION; it is recorded as
    # accepted in docs/security-baseline.md. Do not "fix" it by adding the
    # header here without revisiting that decision.
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

# The runtime configuration document must never be answered from an edge cache.
#
# CachingOptimized cannot express that. Its MinTTL is 1 second, and CloudFront applies
# the MinTTL EVEN WHEN the origin sends `no-store` — so the header alone never gets to
# zero. The larger numbers bite only if the object ever reaches the edge WITHOUT a
# Cache-Control header, which is one forgotten flag away: the 24-hour DefaultTTL then
# applies, and the 365-day MaxTTL lets an unreachable origin keep serving the last
# document it saw. Any of those serves one environment's account ids to another
# environment's users, as a portal that looks entirely healthy.
#
# 0/0/0 makes the guarantee a property of the distribution instead of a flag on one
# upload step.
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

  # `ResponseHeadersPolicyId` is per-behaviour and is NOT inherited from the default one:
  # omitting it here would serve this path with no CSP, no HSTS, no frame or content-type
  # options — and without the `Server` / encryption header stripping — on a URL any
  # scanner finds immediately.
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
