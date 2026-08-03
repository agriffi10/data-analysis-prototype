# ── Origin Access Control ────────────────────────────────────────────────────

resource "aws_cloudfront_origin_access_control" "static_assets" {
  name                              = "${var.project_name}-oac"
  description                       = "OAC for ${var.project_name} static assets"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── Response Headers Policy ───────────────────────────────────────────────────
# SPEC-140. Closes Checkov CKV2_AWS_32 and every Medium plus six of eight Low
# findings from the 2026-08-03 ZAP baseline — two scanners reporting one gap.
#
# The CSP is assembled from variables, never literals: a hardcoded region or
# bucket would have to be found and edited by hand during the client-environment
# transition (docs/transition_plan.md).
#
# NOTE ON THE PHASING: the CSP ships as Content-Security-Policy-REPORT-ONLY
# first, as a custom header, because CloudFront's first-class
# `content_security_policy` field emits the enforcing header only. A CSP that is
# wrong about `worker-src` or `style-src` breaks the Monaco editor in production
# and nowhere else — no unit test observes a CSP. Promotion to enforcing is a
# separate change (SPEC-140 Phase 4) so it can be reverted on its own.

locals {
  # Every AWS endpoint the SPA talks to directly. There is no backend, so this
  # list IS the app's network surface — anything missing here is a broken
  # feature, not a hardened one.
  csp_connect_src = join(" ", [
    "'self'",
    "https://cognito-idp.${var.aws_region}.amazonaws.com",
    "https://cognito-identity.${var.aws_region}.amazonaws.com",
    "https://${var.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://${var.shared_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://athena.${var.aws_region}.amazonaws.com",
    "https://glue.${var.aws_region}.amazonaws.com",
    "https://sqs.${var.aws_region}.amazonaws.com",
  ])

  content_security_policy = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    # 'unsafe-inline' is for STYLES ONLY, and it is monaco-editor's requirement:
    # it injects <style> elements at runtime for theming. Scripts get no such
    # allowance, which is the allowance that matters.
    #
    # fonts.googleapis.com is NOT optional: src/index.css line 1 is
    # `@import url('https://fonts.googleapis.com/css2?family=Inter…')`, and Vite
    # leaves remote @imports in the built CSS. Without this the app loses its
    # typeface site-wide — caught by the Phase 3 harness, which is the entire
    # reason the CSP ships report-only first.
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data:",
    # The Google stylesheet above serves its actual font files from gstatic.
    "font-src 'self' data: https://fonts.gstatic.com",
    # Monaco's worker is a Vite `?worker` import (SqlEditor.tsx). Vite emits a
    # same-origin chunk, but its worker shim can fall back to a blob: URL.
    "worker-src 'self' blob:",
    "connect-src ${local.csp_connect_src}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ])
}

resource "aws_cloudfront_response_headers_policy" "portal" {
  name    = "${var.project_name}-security-headers"
  comment = "Security response headers for the ${var.project_name} SPA (SPEC-140)"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      # `preload` is deliberately NOT set, and this FAILS Checkov CKV_AWS_259 —
      # the only thing that check objects to (max-age, include_subdomains and
      # override all satisfy it; verified against checkov 3.3.9).
      #
      # Accepted rather than silenced. The directive is a declaration of intent
      # to be submitted to hstspreload.org, which we are not doing; this is a
      # shared-suffix *.cloudfront.net name that a custom domain will replace
      # (CKV2_AWS_42 is already accepted for that same reason); and preload is
      # close to irreversible once granted. Asserting it here would make the
      # header say something untrue to buy a green check.
      #
      # Revisit when a custom domain lands — at that point preload becomes a
      # real choice rather than a scanner-appeasing one.
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
  }

  custom_headers_config {
    # Phase 2 ships the CSP in report-only form. Phase 4 moves this value into
    # security_headers_config.content_security_policy and drops this header.
    items {
      header   = "Content-Security-Policy-Report-Only"
      value    = local.content_security_policy
      override = true
    }

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
