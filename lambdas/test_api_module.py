"""The API module's front door, asserted over the Terraform that builds it.

Three scenarios: what the function must NOT be attached to, what the browser must be able to
reach, and the provider block the verifier reads. The reasoning behind each — which failures
apply green, and which one broke fresh sign-in for a day — is in
``infra/modules/api/README.md``.

Attributes:
  INFRA: The IaC tree.
  API: The API module's directory.
  ROOT_MAIN: The composition that builds the origins and the connect-src.
  APP_CLOUDFRONT: The CloudFront policy that READS the connect-src instead of building it.
  AUTH_COGNITO: The app client whose callback list gains the container origin.
  CSP_CONNECT_SRC_TERMS: Every term the deployed connect-src must carry, named independently.
  FORBIDDEN_IN_API_MODULE: Block types whose presence means a network attachment was started.
  API_ROLE_ALLOWED_ACTIONS: The whole of the API function's permissions.
  API_ROLE_FORBIDDEN_SERVICES: Services whose arrival would mean a server-side login flow.
  REQUIRED_ENVIRONMENT_KEYS: The configuration the function cannot start without.
  OIDC_KEYS: The provider block — the five values the verifier reads, and the only five.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from cpcommon.jwks import (
    API_FUNCTION_TIMEOUT_SECONDS,
    API_GATEWAY_INTEGRATION_CEILING_SECONDS,
    JWKS_HTTP_TIMEOUT_SECONDS,
)
from tf_blocks import blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
API = INFRA / "modules" / "api"
ROOT_MAIN = INFRA / "main.tf"
APP_CLOUDFRONT = INFRA / "modules" / "app" / "cloudfront.tf"
AUTH_COGNITO = INFRA / "modules" / "auth" / "cognito.tf"
API_CLIENT = INFRA.parent / "apps" / "portal" / "src" / "lib" / "apiClient.ts"

CSP_CONNECT_SRC_TERMS = (
    "'self'",
    "https://cognito-idp.${var.aws_region}.amazonaws.com",
    "https://cognito-identity.${var.aws_region}.amazonaws.com",
    "https://${local.cognito_hosted_ui_domain}",
    "https://${local.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://${local.shared_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://athena.${var.aws_region}.amazonaws.com",
    "https://glue.${var.aws_region}.amazonaws.com",
    "https://sqs.${var.aws_region}.amazonaws.com",
    "local.api_origin",
)

FORBIDDEN_IN_API_MODULE = ("vpc_config", "aws_security_group", "aws_subnet", "subnet_ids")

API_ROLE_ALLOWED_ACTIONS = frozenset(
    {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "sqs:SendMessage",
        "sts:AssumeRole",
        "sts:TagSession",
    }
)

API_ROLE_FORBIDDEN_SERVICES = (
    "dynamodb:",
    "kms:",
    "secretsmanager:",
    "cognito-idp:",
    "cognito-identity:",
)

REQUIRED_ENVIRONMENT_KEYS = (
    "COGNITO_USER_POOL_ID",
    "COGNITO_APP_CLIENT_ID",
    "ADMIN_BUCKET",
    "USER_SPACE_BUCKET",
    "SHARED_SPACE_BUCKET",
    "ATHENA_WORKGROUP",
    "LOGS_QUEUE_URL",
    "ENV_NAME",
)

OIDC_KEYS = (
    "OIDC_ISSUER",
    "OIDC_AUDIENCE",
    "OIDC_JWKS_URI",
    "OIDC_USERNAME_CLAIM",
    "OIDC_REQUIRED_CLAIMS",
)

_VALID_PROVIDER_BLOCK = {
    "OIDC_ISSUER": "https://provider.example/tenant",
    "OIDC_AUDIENCE": "a-client-id",
    "OIDC_JWKS_URI": "https://provider.example/keys",
    "OIDC_USERNAME_CLAIM": "preferred_username",
    "OIDC_REQUIRED_CLAIMS": '{"token_use":"id"}',
}


def _api_source(strip_comments: bool = True) -> str:
    """Concatenates the API module's Terraform.

    Args:
      strip_comments: Drop full-line comments. The module explains at length why it is not in
        the VPC, and a raw scan reads those sentences as violations.

    Returns:
      The module's source.

    Raises:
      None.
    """
    text = "\n".join(path.read_text() for path in sorted(API.glob("*.tf")))
    if not strip_comments:
        return text
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _root_module_block(name: str) -> str:
    """Extracts one module block from the root composition.

    Anchored on the block's own closing brace rather than on the next module's opening one:
    sliced between two named modules, reordering them yields an empty string and every
    ``not in`` assertion over it passes trivially.

    Args:
      name: The module's name.

    Returns:
      The block's source.

    Raises:
      AssertionError: If the module is not composed at root.
    """
    text = ROOT_MAIN.read_text()
    marker = f'module "{name}" {{'
    assert marker in text, f"root does not compose module {name}"
    start = text.index(marker)
    return text[start : text.index("\n}\n", start)]


def _api_environment() -> dict[str, str]:
    """Reads the function's environment map as key to raw Terraform expression.

    Args:
      None.

    Returns:
      Each environment key mapped to the expression assigned to it.

    Raises:
      None.
    """
    function = blocks((API / "lambda.tf").read_text(), "aws_lambda_function")["api"]
    body = re.search(r"environment\s*\{(.*?)\n  \}", function, re.DOTALL).group(1)
    return {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$", body, re.MULTILINE)
    }


def _rendered_execution_policy() -> dict:
    """Renders the execution-policy template so a placeholder cannot hide a grant.

    Args:
      None.

    Returns:
      The parsed policy document.

    Raises:
      None.
    """
    rendered = (
        (API / "policies" / "api-execution-policy.json.tftpl")
        .read_text()
        .replace(
            "${log_group_arn}",
            "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api",
        )
        .replace("${logs_queue_arn}", "arn:aws:sqs:us-east-1:696000197480:dat-prod-logs.fifo")
        .replace("${portal_role_arn}", "arn:aws:iam::696000197480:role/dat-portal-user-role")
        .replace(
            "${request_queue_arns_json}",
            json.dumps([f"arn:aws:sqs:us-east-1:696000197480:q{n}.fifo" for n in range(8)]),
        )
    )
    return json.loads(rendered)


def _plan_provider_variables(values: dict[str, str]) -> set[str]:
    """Plans the five provider variable declarations and reports what OpenTofu refused.

    Runs the validations rather than checking a validation block is present: a block can be
    present with its condition weakened to something that accepts anything, and a presence
    check passes against every one of those.

    The declarations are extracted into a scratch module that declares no provider, so the
    init is offline and no credentials are involved.

    Args:
      values: Environment key to the value to plan with.

    Returns:
      The lowercased names of the variables OpenTofu refused. Empty means all were accepted.

    Raises:
      AssertionError: If the declarations cannot be extracted, or tofu is unavailable — a skip
        here would read as coverage this suite would not have.
    """
    tofu = shutil.which("tofu")
    assert tofu, "OpenTofu is not on PATH — this assertion cannot be skipped into passing"

    source = (API / "variables.tf").read_text()
    declarations = []
    for match in re.finditer(r'variable\s+"(oidc_[a-z_]+)"\s*\{', source):
        index, depth = source.index("{", match.start()), 0
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        declarations.append(source[match.start() : index + 1])

    assert len(declarations) == len(OIDC_KEYS), (
        f"extracted {len(declarations)} provider variables, expected {len(OIDC_KEYS)}"
    )

    with tempfile.TemporaryDirectory() as scratch:
        pathlib.Path(scratch, "variables.tf").write_text("\n\n".join(declarations) + "\n")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "TF_IN_AUTOMATION": "1",
            **{f"TF_VAR_{key.lower()}": value for key, value in values.items()},
        }
        setup = subprocess.run(  # noqa: S603
            [tofu, "init", "-backend=false", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )
        assert setup.returncode == 0, (
            f"tofu init failed in the scratch module:\n{setup.stdout}\n{setup.stderr}"
        )
        plan = subprocess.run(  # noqa: S603
            [tofu, "plan", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )

    if plan.returncode == 0:
        return set()
    return {
        name
        for name in (key.lower() for key in OIDC_KEYS)
        if f'variable "{name}"' in plan.stderr + plan.stdout
    }


def test_the_function_is_an_isolated_front_door_holding_only_what_it_needs() -> None:
    """Every violation here applies green and surfaces a spec later, so each is an absence.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the function gains a network attachment, an unscoped permission, an
        incomplete environment, or a timeout that outlives its integration.
    """
    source = _api_source()
    declared_variables = (API / "variables.tf").read_text()
    root_call = _root_module_block("api")
    policy = _rendered_execution_policy()
    environment = _api_environment()

    for forbidden in FORBIDDEN_IN_API_MODULE:
        assert forbidden not in source, (
            f"modules/api names {forbidden!r} — the VPC exists for the container, and a function "
            "attached to it stops verifying tokens after the provider swap with nothing to blame"
        )
    for network_shaped in ("vpc_id", "subnet", "security_group", "private_route"):
        assert network_shaped not in declared_variables, (
            f"modules/api declares a {network_shaped!r} variable — it takes no network input"
        )
    assert "module.network" not in root_call, "root passes a network output into module.api"

    assert re.search(
        r'source_arn\s*=\s*"\$\{aws_apigatewayv2_api\.api\.execution_arn\}/\*/\*"', source
    ), "the invoke permission must be scoped to this API's execution ARN"
    assert re.search(r"disable_execute_api_endpoint\s*=\s*true", source), (
        "the execute-api hostname must be disabled — the custom domain is the only front door"
    )
    assert "aws_api_gateway_account" not in source, (
        "an HTTP API needs no account-level CloudWatch Logs role"
    )
    assert set(re.findall(r'resource\s+"aws_cloudwatch_log_group"\s+"(\w+)"', source)) == {
        "api", "access",
    }
    assert len(re.findall(r"retention_in_days\s*=\s*\d+", source)) == 2, (
        "both the function's log group and the access-log group need a retention"
    )
    assert re.search(r'endpoint_type\s*=\s*"REGIONAL"', source)
    assert "aws_acm_certificate_validation.api.certificate_arn" in root_call, (
        "the certificate must come from the validation, not from aws_acm_certificate.api.arn"
    )

    granted: set[str] = set()
    for statement in policy["Statement"]:
        declared = statement["Action"]
        granted.update([declared] if isinstance(declared, str) else declared)
    assert granted == set(API_ROLE_ALLOWED_ACTIONS), (
        f"the API role grants {sorted(granted)} — anything beyond logs, the logs queue and the "
        "one assume belongs to the spec that needs it"
    )
    serialised = json.dumps(policy)
    for service in API_ROLE_FORBIDDEN_SERVICES:
        assert service not in serialised, (
            f"the API role names {service} — a session store, its key, a secrets store and the "
            "identity provider all belong to a login flow this API does not perform"
        )
    sts_statements = [
        statement
        for statement in policy["Statement"]
        if any(
            action.startswith("sts:")
            for action in (
                [statement["Action"]]
                if isinstance(statement["Action"], str)
                else statement["Action"]
            )
        )
    ]
    assert len(sts_statements) == 1, (
        f"{len(sts_statements)} statements name STS — the API acts as its caller through exactly "
        "one door. sts:AssumeRole without sts:TagSession applies green and fails at runtime "
        "naming neither the tag nor the missing action"
    )
    assert set(sts_statements[0]["Action"]) == {"sts:AssumeRole", "sts:TagSession"}
    assert sts_statements[0]["Resource"] == (
        "arn:aws:iam::696000197480:role/dat-portal-user-role"
    ), "the assume is not scoped to the portal role alone"
    assert '"*"' not in json.dumps(policy["Statement"]), "no wildcard resource"

    for key in REQUIRED_ENVIRONMENT_KEYS:
        assert key in environment, f"the function environment omits {key}"
    assert "BUILD_VERSION" not in source, (
        "BUILD_VERSION must NOT be set by Terraform — the stamp travels in the package, and an "
        "env-borne one would name the last infra commit rather than the running code"
    )
    assert 'data "archive_file" "api_placeholder"' in source
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", source)
    assert ignored, "the function must ignore changes to the attributes CI owns"
    for attribute in ("filename", "source_code_hash", "layers"):
        assert attribute in ignored.group(1), (
            f"ignore_changes omits {attribute} — an apply would revert what CI deployed"
        )

    declared_timeout = int(
        re.search(r"^\s*timeout\s*=\s*(\d+)", source, re.MULTILINE).group(1)
    )
    declared_ceiling = (
        int(re.search(r"timeout_milliseconds\s*=\s*(\d+)", source).group(1)) // 1000
    )
    assert declared_timeout == API_FUNCTION_TIMEOUT_SECONDS
    assert declared_ceiling == API_GATEWAY_INTEGRATION_CEILING_SECONDS
    assert declared_ceiling <= 30, "the HTTP API integration ceiling is a hard 30s"
    assert JWKS_HTTP_TIMEOUT_SECONDS < declared_timeout < declared_ceiling, (
        "a JWKS fetch must finish inside the function's budget, and the function must answer "
        "before the integration gives up — otherwise the caller gets a 504 while the invocation "
        "keeps running and keeps billing. Equal is not ordered; which one answers is then a race"
    )


def test_the_browser_is_admitted_by_cors_the_csp_and_the_callback_list() -> None:
    """The three allowlists a request crosses, each of which fails only in a real browser.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a header, method, origin or connect-src term the browser needs is
        not admitted, or the client's timeout copies have drifted.
    """
    source = _api_source()
    gateway = (API / "apigateway.tf").read_text()
    client = API_CLIENT.read_text()
    root = ROOT_MAIN.read_text()
    connect_src_block = root[
        root.index("csp_connect_src = join(") : root.index(
            "\n  ])", root.index("csp_connect_src = join(")
        )
    ]

    assert re.search(
        r"allow_origins\s*=\s*compact\(\[var\.spa_origin,\s*var\.app_url\]\)", source
    ), "allow_origins must be the two exact origins, compacted so an unset app_url drops out"
    assert '"*"' not in source.split("cors_configuration")[1].split("}")[0]
    assert re.search(r"allow_credentials\s*=\s*false", source), (
        "allow_credentials must be explicitly false, not merely absent"
    )
    assert re.search(r"max_age\s*=\s*[1-9]", source), "max_age must be non-zero"

    admitted_headers = {
        value.strip().strip('"').lower()
        for value in re.search(r"allow_headers\s*=\s*\[([^\]]*)\]", gateway).group(1).split(",")
        if value.strip()
    }
    sent_headers = {
        match.group(1).lower()
        for match in re.finditer(
            r"^\s*'?([a-zA-Z-]+)'?:\s*(?:`Bearer|requestId\(\)|'application/json')",
            client,
            re.MULTILINE,
        )
    }
    assert {"x-request-id", "authorization"} <= sent_headers, (
        "the client no longer sends the headers this admits — the scan went trivial"
    )
    assert sent_headers <= admitted_headers, (
        f"the browser sends {sorted(sent_headers - admitted_headers)}, which the preflight does "
        "not admit — the request never reaches the API and the browser reports a generic network "
        "error, indistinguishable from the API being down"
    )

    import sys

    sys.path.insert(0, str(INFRA.parent / "lambdas" / "api"))
    from apicommon import contract

    allowed_methods = {
        value.strip().strip('"').upper()
        for value in re.search(r"allow_methods\s*=\s*\[([^\]]*)\]", gateway).group(1).split(",")
        if value.strip()
    }
    declared_methods = {route.method for route in contract.ROUTES}
    assert declared_methods <= allowed_methods, (
        f"the contract declares {sorted(declared_methods - allowed_methods)}"
    )
    assert "OPTIONS" in allowed_methods, "the preflight's own method must be allowed"

    copies = {
        name: int(value)
        for name, value in re.findall(
            r"export const (API_FUNCTION_TIMEOUT_SECONDS|API_GATEWAY_INTEGRATION_CEILING_SECONDS)"
            r"\s*=\s*(\d+);",
            client,
        )
    }
    assert copies == {
        "API_FUNCTION_TIMEOUT_SECONDS": API_FUNCTION_TIMEOUT_SECONDS,
        "API_GATEWAY_INTEGRATION_CEILING_SECONDS": API_GATEWAY_INTEGRATION_CEILING_SECONDS,
    }, f"the browser's copies drifted from cpcommon.jwks: {copies}"

    found_terms = {
        line.strip().rstrip(",").strip('"')
        for line in connect_src_block.splitlines()[1:]
        if line.strip() and not line.strip().startswith("#")
    }
    assert found_terms == set(CSP_CONNECT_SRC_TERMS), (
        f"root's connect-src is {sorted(found_terms)}; expected {sorted(CSP_CONNECT_SRC_TERMS)}. "
        "A term dropped here breaks one feature, only in a browser, and nothing offline sees it"
    )
    app_source = APP_CLOUDFRONT.read_text()
    assert "csp_connect_src = join(" not in app_source
    assert "content_security_policy = join(" not in app_source, (
        "modules/app must not assemble the policy — root does, so one computation feeds both the "
        "distribution and the container, and this module's retirement orphans nothing"
    )
    assert "content_security_policy = var.content_security_policy" in app_source

    callbacks = re.search(
        r"callback_urls\s*=\s*distinct\(compact\(\[([^\]]*)\]\)\)", AUTH_COGNITO.read_text()
    )
    assert callbacks, (
        "the callback list must be distinct(compact([...])) — compact so an unset origin drops "
        "out, distinct because the cutover re-points app_url AT the container origin before it "
        "removes the entry, and Cognito rejects a duplicated URL rather than deduplicating it"
    )
    for required in ('"http://localhost:5173"', "var.app_url", "var.spa_origin"):
        assert required in callbacks.group(1), f"the callback list omits {required}"


def test_the_provider_block_is_complete_and_cannot_be_silently_disabled() -> None:
    """Rendered empty, the whole thing still deploys and a Cognito ACCESS token is accepted.

    The validations are RUN rather than checked for presence, because a weakened condition
    passes a presence check. An unset repo variable renders as the empty string, which
    satisfies a required variable and overrides a default, so "no default" guards nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a key is missing, an empty or non-object value is accepted, or the
        issuer Terraform sends is not the one the verifier builds.
    """
    environment = _api_environment()
    root_call = _root_module_block("api")

    assert not [key for key in OIDC_KEYS if key not in environment], (
        f"the function environment omits {[k for k in OIDC_KEYS if k not in environment]}"
    )
    assert environment["OIDC_REQUIRED_CLAIMS"] == "var.oidc_required_claims", (
        "the module must pass the value through, so root stays the single wiring site"
    )
    rendered_claims = re.search(
        r"oidc_required_claims\s*=\s*jsonencode\((.+?)\)\n", root_call
    )
    assert rendered_claims, "root does not render oidc_required_claims with jsonencode"
    assert re.fullmatch(r"\{\s*token_use\s*=\s*\"id\"\s*\}", rendered_claims.group(1).strip()), (
        f"the deployed required claims are {rendered_claims.group(1).strip()} — an empty or "
        "altered map stops the token-type check running at all, and a Cognito access token "
        "would be accepted"
    )

    assert "well-known" not in _api_source(), (
        "the API module builds a JWKS URL — it must receive one, so the provider assumption "
        "stays at the root where a swap will find it"
    )
    assert environment["OIDC_JWKS_URI"] == "var.oidc_jwks_uri"
    jwks_assignment = re.search(r"^\s*oidc_jwks_uri\s*=\s*(.+)$", root_call, re.MULTILINE)
    assert jwks_assignment and not jwks_assignment.group(1).strip().startswith("var."), (
        "root must be the place oidc_jwks_uri is decided, so a provider swap has one site"
    )
    assert re.search(r'oidc_username_claim\s*=\s*"cognito:username"', root_call), (
        "the username claim is not cognito:username — every request would be attributed to "
        "whatever this names instead"
    )
    assert re.search(r"oidc_audience\s*=\s*module\.auth\.user_pool_client_id", root_call), (
        "the audience must be the app client the SPA's ID token is issued to, not the pool"
    )
    assert "OIDC_" not in (INFRA.parent / "apps" / "portal" / ".env.example").read_text(), (
        "these five are server-side; a copy in the SPA's dev fallback is a second, unchecked home"
    )

    terraform_issuer = re.search(r'cognito_issuer\s*=\s*"([^"]+)"', ROOT_MAIN.read_text())
    python_issuer = re.search(
        r'issuer = f"([^"]+)"',
        (
            pathlib.Path(__file__).resolve().parent
            / "control-plane-common" / "cpcommon" / "auth.py"
        ).read_text(),
    )
    assert terraform_issuer and python_issuer, "one side no longer builds a Cognito issuer"
    normalise = lambda text: re.sub(r"\$?\{[^}]+\}", "{}", text)  # noqa: E731
    assert normalise(terraform_issuer.group(1)) == normalise(python_issuer.group(1)), (
        f"Terraform sends {terraform_issuer.group(1)!r} and the verifier builds "
        f"{python_issuer.group(1)!r} — a trailing slash on either makes every token fail `iss`"
    )

    refused_empty = _plan_provider_variables(dict.fromkeys(OIDC_KEYS, ""))
    for key in OIDC_KEYS:
        assert key.lower() in refused_empty, (
            f"{key.lower()} accepted an empty value — an unset repo variable reaches the "
            "function as an empty string and fails far from its cause"
        )
    for value in ("null", '"id"', "[]"):
        assert "oidc_required_claims" in _plan_provider_variables(
            {**_VALID_PROVIDER_BLOCK, "OIDC_REQUIRED_CLAIMS": value}
        ), (
            f"oidc_required_claims accepted {value!r} — jsondecode accepts a bare scalar and "
            "tomap accepts a literal null, and either stops the token-type check running"
        )
    assert not _plan_provider_variables(_VALID_PROVIDER_BLOCK), (
        "a valid provider block was refused — the validations are over-tight, and the refusals "
        "asserted above would pass for the wrong reason"
    )
