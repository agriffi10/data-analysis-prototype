# ── The HTTP API ──────────────────────────────────────────────────────────────
# A $default route to one AWS_PROXY integration. The route table lives in the CODE.
# `$default` matches OPTIONS, so the ROUTER must answer a preflight before auth. README.md.

resource "aws_apigatewayv2_api" "api" {
  name          = local.function_name
  protocol_type = "HTTP"

  # Left enabled, the API answers on execute-api.* too — a second front door outside the CSP
  # and the alias record, making a preflight check ambiguous about what it proved.
  disable_execute_api_endpoint = true

  # CORS is the API's alone — AWS IGNORES CORS headers returned by the integration.
  cors_configuration {
    # Exact origins, never "*". This was two entries through the cutover — naming one would
    # have left the other an app that loads and can do nothing — and it narrows to one with
    # the origin that needed the second.
    allow_origins = compact([var.spa_origin])

    allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

    # A header the preflight does not admit FAILS the preflight, and the browser reports a
    # generic network error indistinguishable from the API being down. Asserted against the
    # client's own header list, never inferred from the app working.
    allow_headers = ["content-type", "authorization", "x-request-id"]

    # False, and not merely unset: a bearer is not a credential in the CORS sense, and this
    # is the half of the credentials/"*" pairing browsers reject WHILE APPLYING GREEN.
    allow_credentials = false

    # Every request carries Authorization, so EVERY request is preflighted.
    max_age = 600
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"

  # AT API Gateway's hard 30s ceiling, and deliberately ABOVE the function's 29s. The order
  # is the point — set equal, which one answers is a race. README.md.
  timeout_milliseconds = 30000
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${local.function_name}"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # HTTP APIs need NO account-level CloudWatch Logs role. A reader arriving from REST APIs
  # will look for one and MUST NOT add it.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      path             = "$context.path"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

# Scoped to this API's own executions. "*" would let ANY API Gateway in the account invoke
# the function — a grant that reads as boilerplate in a diff.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# REGIONAL. The us-east-1-only certificate rule belongs to CloudFront and not here.
resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = var.api_host

  domain_name_configuration {
    certificate_arn = var.api_certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

# Mapped at the EMPTY path, so no stage prefix reaches the router.
resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.default.id
}
