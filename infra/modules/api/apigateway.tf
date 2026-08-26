# ── The HTTP API ──────────────────────────────────────────────────────────────
# A $default route to one AWS_PROXY integration, reached through a regional custom
# domain. One function serves every path, so the route table is in the code — a
# per-route integration would put it in two places, and the authorization a later spec
# adds resolves a principal once, before dispatch.

resource "aws_apigatewayv2_api" "api" {
  name          = local.function_name
  protocol_type = "HTTP"

  # The API is reached through the custom domain and nowhere else. Left enabled, it also
  # answers on https://{api-id}.execute-api.{region}.amazonaws.com — a second front door
  # outside the CSP, outside the alias record, and one that makes a CORS preflight check
  # ambiguous about which host it actually proved.
  disable_execute_api_endpoint = true

  # CORS is the API's alone. AWS ignores CORS headers returned by the integration, so a
  # header emitted in the handler would not reach the browser at all — but the rule stands
  # on its own ground: two places able to answer the same question is how they come to
  # disagree, and the one that wins here is not the one a reader is looking at.
  cors_configuration {
    # Exact origins, never "*". Both are real for the length of the arc: the container is
    # where ported features are proved, CloudFront is the rollback, and a list naming one
    # of them leaves the other an app that loads and can do nothing.
    allow_origins = compact([var.spa_origin, var.app_url])

    allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers = ["content-type", "authorization"]

    # False, and not merely unset. The arc sends the ID token as an Authorization bearer,
    # which is not a credential in the CORS sense — so true would grant a capability
    # nothing uses while making the exact-origin echo load-bearing for a browser rule that
    # no longer applies. It is also the half of the credentials/"*" pairing that every
    # browser rejects while applying green.
    allow_credentials = false

    max_age = 300
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"

  # Stated rather than inherited. The ceiling is a hard 30s on an HTTP API and is not
  # raisable; naming it here keeps it beside the function timeout it has to outlive.
  timeout_milliseconds = 29000
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
  # will look for one and must not add it: the delivery permissions live on the deploy
  # role, not on an apigateway.amazonaws.com account setting.
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

# Scoped to this API's own executions. "*" here would let any API Gateway in the account
# invoke the function, which is a grant nobody would write on purpose and one that reads
# as boilerplate in a diff.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# REGIONAL, with a certificate in this module's own region. The us-east-1-only
# certificate rule belongs to CloudFront and does not apply here.
resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = var.api_host

  domain_name_configuration {
    certificate_arn = var.api_certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

# Mapped at the empty path, so what reaches the handler is already the path the router
# expects — no stage prefix to strip, and no disagreement between the two hostnames
# about what a request's path is.
resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.default.id
}
