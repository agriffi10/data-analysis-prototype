"""The API's front door, and the three allowlists that admit it.

Two very different failure classes live here.

**The absences.** The function is not in the VPC, holds no security group, and its role names
logs and one queue. Every one of those, violated, **applies green**: a `vpc_config` shows up only
as latency until the arc's provider swap turns it into a token verification that times out; a
data-plane grant is invisible until something uses it. They are asserted as absences because there
is no positive symptom to wait for.

**The CSP move.** `connect-src` moved out of `modules/app` to root so the API's origin could join
it, and a term dropped in that move breaks exactly one feature, only in a browser, only for the
surface that uses it — no unit test observes a CSP, and the module's own history records the
Hosted UI domain going missing once and breaking fresh sign-in for a day. So the terms are named
here as data and asserted as a set. That is a second copy by construction, and the second copy is
the point: it is what makes a silent drop impossible, not a way of avoiding transcription.

**What this file cannot prove.** These are text assertions over Terraform. That a preflight
returns one `access-control-allow-origin` header and refuses a foreign origin, that an invocation
produces a span, and that the deployed `connect-src` carries every term — all live checks, owned
by the acceptance script.

Attributes:
  INFRA: The IaC tree.
  API: The API module's directory.
  ROOT_MAIN: The composition that builds the origins and the connect-src.
  APP_CLOUDFRONT: The CloudFront policy that now READS the connect-src instead of building it.
  AUTH_COGNITO: The app client whose callback and logout lists gain the container origin.
  CSP_CONNECT_SRC_TERMS: Every term the deployed connect-src must carry, named independently.
  FORBIDDEN_IN_API_MODULE: Resource and block types whose presence is the first half of an
    attachment somebody started.
  API_ROLE_ALLOWED_ACTIONS: The whole of the API function's permissions.
"""

import json
import pathlib
import re

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
    {"logs:CreateLogStream", "logs:PutLogEvents", "sqs:SendMessage"}
)


def _api_source() -> str:
    """Concatenates every Terraform file in the API module.

    Args:
      None.

    Returns:
      The module's whole source, comments included.

    Raises:
      None.
    """
    return "\n".join(path.read_text() for path in sorted(API.glob("*.tf")))


def _api_source_without_comments() -> str:
    """The module's source with comment lines dropped.

    Naming the thing you forbid is not the same as doing it, and this module explains at
    length why it is not in the VPC — a raw scan reads those sentences as violations.

    Args:
      None.

    Returns:
      The source with every full-line comment removed.

    Raises:
      None.
    """
    return "\n".join(
        line for line in _api_source().splitlines() if not line.lstrip().startswith("#")
    )


def _root_module_block(name: str) -> str:
    """Extracts one module block from the root composition.

    Anchored on the block's own closing brace rather than on the NEXT module's opening one:
    sliced between two named modules, reordering them yields an empty string and every
    `not in` assertion over it passes trivially.

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


def _connect_src_block() -> str:
    """Extracts root's connect-src list.

    Args:
      None.

    Returns:
      The source of the `csp_connect_src` local, from its opening bracket to its close.

    Raises:
      AssertionError: If root does not build the list.
    """
    text = ROOT_MAIN.read_text()
    start = text.index("csp_connect_src = join(")
    return text[start : text.index("\n  ])", start)]


def test_the_api_function_is_not_in_the_vpc_and_holds_no_network_attachment() -> None:
    """Each of these applies green, and the symptom arrives a spec later.

    Args:
      None.

    Returns:
      None.

    Raises:
        AssertionError: If the module names any network attachment.
    """
    source = _api_source_without_comments()

    for forbidden in FORBIDDEN_IN_API_MODULE:
        assert forbidden not in source, (
            f"modules/api names {forbidden!r} — the VPC exists for the container, and a "
            "function attached to it stops verifying tokens after the provider swap with no "
            "code change to blame"
        )


def test_the_api_module_takes_nothing_from_the_network_module() -> None:
    """The two modules are unrelated by construction, not by convention.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the module declares a network-shaped variable, or root passes one.
    """
    declared = (API / "variables.tf").read_text()
    for network_shaped in ("vpc_id", "subnet", "security_group", "private_route"):
        assert network_shaped not in declared, (
            f"modules/api declares a {network_shaped!r} variable — it takes no network input"
        )

    block = _root_module_block("api")
    assert "module.network" not in block, "root passes a network output into module.api"


def test_cors_names_exact_origins_and_refuses_credentials() -> None:
    """A `"*"` origin list passes the echo check and fails only the foreign-origin one.

    `allow_credentials` with `"*"` is refused by every browser while applying green, so the
    pairing is the defect. This configuration avoids it on both counts.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the origins are wildcarded or credentials are allowed.
    """
    source = _api_source_without_comments()

    assert re.search(r"allow_origins\s*=\s*compact\(\[var\.spa_origin,\s*var\.app_url\]\)", source), (
        "allow_origins must be the two exact origins, compacted so an unset app_url drops out"
    )
    assert '"*"' not in source.split("cors_configuration")[1].split("}")[0], (
        "no wildcard may appear in the CORS configuration"
    )
    assert re.search(r"allow_credentials\s*=\s*false", source), (
        "allow_credentials must be explicitly false, not merely absent"
    )
    assert re.search(r"allow_headers\s*=\s*\[[^\]]*\"content-type\"", source)
    assert re.search(r"allow_headers\s*=\s*\[[^\]]*\"authorization\"", source)
    assert re.search(r"max_age\s*=\s*[1-9]", source), "max_age must be non-zero"


def test_the_invoke_permission_is_scoped_to_this_api() -> None:
    """`"*"` would let any API Gateway in the account invoke the function.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the permission is unscoped.
    """
    source = _api_source_without_comments()

    assert re.search(
        r'source_arn\s*=\s*"\$\{aws_apigatewayv2_api\.api\.execution_arn\}/\*/\*"', source
    ), "the invoke permission must be scoped to this API's execution ARN"


def test_the_execute_api_endpoint_is_disabled() -> None:
    """Left enabled, the API answers on a second host outside the CSP and the alias record.

    It also makes a live preflight ambiguous about which hostname it proved.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the default endpoint is left live.
    """
    assert re.search(
        r"disable_execute_api_endpoint\s*=\s*true", _api_source_without_comments()
    ), "the execute-api hostname must be disabled — the custom domain is the only front door"


def test_both_log_groups_set_a_retention() -> None:
    """A group with no retention keeps logs forever and trips a blocking scanner gate.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either group omits retention.
    """
    source = _api_source_without_comments()

    groups = re.findall(r'resource\s+"aws_cloudwatch_log_group"\s+"(\w+)"', source)
    assert set(groups) == {"api", "access"}, f"expected both log groups, found {groups}"
    assert len(re.findall(r"retention_in_days\s*=\s*\d+", source)) == 2, (
        "both the function's log group and the access-log group need a retention"
    )


def test_no_account_level_cloudwatch_logs_role_is_created() -> None:
    """HTTP APIs need none; a reader arriving from REST APIs will look for one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an account-level logging setting appears.
    """
    source = _api_source_without_comments()

    assert "aws_api_gateway_account" not in source, (
        "an HTTP API needs no account-level CloudWatch Logs role"
    )


def test_the_custom_domain_is_regional_and_takes_the_validated_certificate() -> None:
    """The us-east-1-only certificate rule is CloudFront's and does not apply here.

    The certificate must come from the VALIDATION resource: the same ARN, but only that one
    creates the edge stopping a clean rebuild attaching a still-pending certificate.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the endpoint is not regional, or the certificate bypasses validation.
    """
    source = _api_source_without_comments()

    assert re.search(r'endpoint_type\s*=\s*"REGIONAL"', source)
    assert re.search(r"certificate_arn\s*=\s*var\.api_certificate_arn", source)

    block = _root_module_block("api")
    assert "aws_acm_certificate_validation.api.certificate_arn" in block, (
        "the certificate must come from the validation, not from aws_acm_certificate.api.arn"
    )


def test_the_function_role_grants_exactly_logs_and_the_logs_queue() -> None:
    """Rendered, not read as a template — a placeholder can expand into a grant.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the role names any action outside the allowed set.
    """
    rendered = (
        (API / "policies" / "api-execution-policy.json.tftpl")
        .read_text()
        .replace(
            "${log_group_arn}",
            "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api",
        )
        .replace(
            "${logs_queue_arn}", "arn:aws:sqs:us-east-1:696000197480:dat-prod-logs.fifo"
        )
    )
    document = json.loads(rendered)

    actions: set[str] = set()
    for statement in document["Statement"]:
        declared = statement["Action"]
        actions.update([declared] if isinstance(declared, str) else declared)

    assert actions == set(API_ROLE_ALLOWED_ACTIONS), (
        f"the API role grants {sorted(actions)} — it calls no AWS service, so anything beyond "
        "logs and the logs queue belongs to the spec that needs it"
    )
    assert all(statement["Effect"] == "Allow" for statement in document["Statement"])
    assert '"*"' not in json.dumps(document["Statement"]), "no wildcard resource"


def test_the_function_environment_is_complete() -> None:
    """The layer resolves config lazily, so a missing key fails at first read, not at import.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any required key is absent.
    """
    source = _api_source_without_comments()

    for key in (
        "COGNITO_USER_POOL_ID",
        "COGNITO_APP_CLIENT_ID",
        "ADMIN_BUCKET",
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        "ATHENA_WORKGROUP",
        "LOGS_QUEUE_URL",
        "ENV_NAME",
    ):
        assert re.search(rf"{key}\s*=", source), f"the function environment omits {key}"

    assert "BUILD_VERSION" not in source, (
        "BUILD_VERSION must NOT be set by Terraform — the stamp travels in the package, and an "
        "env-borne one would name the last infra commit rather than the running code"
    )


def test_the_function_bootstraps_from_a_placeholder_and_never_reverts_the_deployed_code() -> None:
    """Without the ignore_changes, every apply after the first reverts the function to the stub.

    `layers` belongs in that list beside the code: an apply landing after a deploy would
    otherwise strip the layer off, and the function fails at cold start on an import that
    had been working.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the placeholder or any of the three ignored attributes is missing.
    """
    source = _api_source_without_comments()

    assert 'data "archive_file" "api_placeholder"' in source, (
        "the function needs a placeholder package to be creatable at all"
    )
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", source)
    assert ignored, "the function must ignore changes to the attributes CI owns"
    for attribute in ("filename", "source_code_hash", "layers"):
        assert attribute in ignored.group(1), (
            f"ignore_changes omits {attribute} — an apply would revert what CI deployed"
        )


def test_the_function_timeout_clears_the_integration_ceiling() -> None:
    """The 30s HTTP API ceiling is not raisable, so the function must give up first.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the function could outlive the integration.
    """
    source = _api_source_without_comments()

    function = re.search(r"^\s*timeout\s*=\s*(\d+)", source, re.MULTILINE)
    integration = re.search(r"timeout_milliseconds\s*=\s*(\d+)", source)
    assert function and integration, "both timeouts must be stated, not inherited"

    function_ms = int(function.group(1)) * 1000
    integration_ms = int(integration.group(1))

    assert integration_ms <= 30_000, "the HTTP API integration ceiling is a hard 30s"
    assert function_ms < integration_ms, (
        f"the function ({function_ms}ms) must give up BEFORE the integration ({integration_ms}ms), "
        "or a slow request answers 504 while the invocation keeps running and keeps billing. "
        "Equal is not ordered — which one answers is then a race"
    )


def test_the_connect_src_moved_to_root_carrying_every_term_plus_the_api() -> None:
    """The riskiest edit in this change, and the one nothing else observes.

    Set equality, not containment: containment passes when the move drops a term and
    something else re-adds a superset.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If root's list is not exactly the expected terms.
    """
    block = _connect_src_block()

    found = {
        line.strip().rstrip(",").strip('"')
        for line in block.splitlines()[1:]
        if line.strip() and not line.strip().startswith("#")
    }

    assert found == set(CSP_CONNECT_SRC_TERMS), (
        f"root's connect-src is {sorted(found)}; expected {sorted(CSP_CONNECT_SRC_TERMS)}. "
        "A term dropped here breaks one feature, only in a browser, and nothing offline sees it"
    )


def test_the_app_module_reads_the_policy_and_no_longer_builds_any_of_it() -> None:
    """Two builders would drift, and the deployed one is not the one a reader opens.

    The seam has moved twice. It was four inputs assembled here; then ``connect-src`` at root with
    the policy still assembled here; now the whole policy arrives from root, because the container
    needs the same computation and a check at root cannot read a local inside a module.
    ``test_csp_policy.py`` owns the policy's content — this asserts only that nothing is rebuilt
    here.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the module assembles either local, or stopped reading the input.
    """
    source = APP_CLOUDFRONT.read_text()

    assert "csp_connect_src = join(" not in source, (
        "modules/app must not build connect-src — root does, because the API's origin lives there"
    )
    assert "content_security_policy = join(" not in source, (
        "modules/app must not assemble the policy — root does, so one computation feeds both the "
        "distribution and the container, and so this module's retirement orphans nothing"
    )
    assert "content_security_policy = var.content_security_policy" in source, (
        "the response-headers policy must emit the string root passes in"
    )


def test_the_callback_list_gains_the_container_origin_and_loses_nothing() -> None:
    """Removing either deployed origin is the cutover spec's work; doing it here deletes the rollback.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either origin or localhost is missing from the list.
    """
    source = AUTH_COGNITO.read_text()

    listed = re.search(r"callback_urls\s*=\s*distinct\(compact\(\[([^\]]*)\]\)\)", source)
    assert listed, (
        "the callback list must be distinct(compact([...])) — compact so an unset origin drops "
        "out, distinct because the cutover re-points app_url AT the container origin before it "
        "removes the entry, and Cognito rejects a duplicated URL rather than deduplicating it"
    )

    entries = listed.group(1)
    for required in ('"http://localhost:5173"', "var.app_url", "var.spa_origin"):
        assert required in entries, f"the callback list omits {required}"

    assert "logout_urls   = local.callback_urls" in source or re.search(
        r"logout_urls\s*=\s*local\.callback_urls", source
    ), "the logout list must be the same list — two lists is two things to keep in step"


def test_the_jwks_timeout_is_sized_against_the_timeouts_terraform_actually_sets() -> None:
    """The verifier's HTTP timeout is sized against a budget, so read the budget.

    ``cpcommon.jwks`` names the function timeout and the integration ceiling as constants, and
    a constant hand-copied from Terraform agrees with it only until Terraform changes. Drop the
    function to 3 seconds and a 5-second JWKS fetch silently outlives the invocation it is
    running inside, with every offline assertion still green — the verifier would give up after
    the caller already had.

    So the numbers come from the Terraform, and the constants are checked against them rather
    than trusted. What is asserted is the ORDER: a JWKS fetch finishes inside the function's
    budget, and the function answers before the integration gives up.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the constants have drifted from Terraform, or the order is wrong.
    """
    function = blocks((API / "lambda.tf").read_text(), "aws_lambda_function")["api"]
    integration = blocks((API / "apigateway.tf").read_text(), "aws_apigatewayv2_integration")["api"]

    declared_timeout = int(re.search(r"^\s*timeout\s*=\s*(\d+)", function, re.MULTILINE).group(1))
    declared_ceiling_ms = int(
        re.search(r"^\s*timeout_milliseconds\s*=\s*(\d+)", integration, re.MULTILINE).group(1)
    )
    declared_ceiling = declared_ceiling_ms // 1000

    assert declared_timeout == API_FUNCTION_TIMEOUT_SECONDS, (
        f"cpcommon.jwks says the function times out at {API_FUNCTION_TIMEOUT_SECONDS}s and "
        f"Terraform sets {declared_timeout}s — the JWKS timeout is sized against a number that "
        "no longer exists"
    )
    assert declared_ceiling == API_GATEWAY_INTEGRATION_CEILING_SECONDS

    assert JWKS_HTTP_TIMEOUT_SECONDS < declared_timeout < declared_ceiling, (
        "the order is what matters: a JWKS fetch must finish inside the function's budget, and "
        "the function must answer before the integration gives up — otherwise the caller gets a "
        "504 while the invocation keeps running and keeps billing"
    )


#: The provider block the API verifies tokens against. Five keys, and the verifier reads
#: nothing else about who issues them.
OIDC_KEYS = (
    "OIDC_ISSUER",
    "OIDC_AUDIENCE",
    "OIDC_JWKS_URI",
    "OIDC_USERNAME_CLAIM",
    "OIDC_REQUIRED_CLAIMS",
)


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


def test_the_provider_block_reaches_the_function() -> None:
    """All five, or the verifier cannot say who it is verifying against.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a key is missing from the environment map.
    """
    environment = _api_environment()
    missing = [key for key in OIDC_KEYS if key not in environment]
    assert not missing, f"the function environment omits {missing}"


def test_the_required_claims_value_is_pinned_to_what_makes_a_token_an_id_token() -> None:
    """READ FROM THE TERRAFORM, not restated.

    This is the check that decides whether a Cognito ACCESS token — genuine, correctly signed,
    unexpired, from the same pool — is refused. Rendered as `jsonencode({})` the whole thing
    still deploys, every offline test that stubs its own configuration still passes, and the
    only symptom is that a token type the API should never accept is accepted. So the deployed
    value is asserted rather than assumed, at the one place it is actually decided.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the deployed required-claims map is not exactly the ID-token check.
    """
    expression = _api_environment()["OIDC_REQUIRED_CLAIMS"]
    assert expression == "var.oidc_required_claims", (
        "the module must pass the value through, so root stays the single wiring site"
    )

    call = re.search(r'module\s+"api"\s*\{(.*?)\n\}', ROOT_MAIN.read_text(), re.DOTALL).group(1)
    rendered = re.search(r"oidc_required_claims\s*=\s*jsonencode\((.+?)\)\n", call).group(1)

    assert re.fullmatch(r"\{\s*token_use\s*=\s*\"id\"\s*\}", rendered.strip()), (
        f"the deployed required claims are {rendered.strip()} — an empty or altered map stops "
        "the token-type check running at all, and a Cognito access token would be accepted"
    )


def test_the_module_treats_the_jwks_url_as_opaque() -> None:
    """The provider assumption lives on ONE line of root Terraform, and this says where.

    Cognito publishes its keys under its issuer; other providers do not. So the concatenation
    is a fact about this provider rather than about the verifier, and it belongs at the
    composition root — which already knows which provider it composed. Rebuilding it inside the
    module, or in any Python module downstream, would put the assumption somewhere a provider
    swap does not look.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the module derives the JWKS URL instead of receiving it.
    """
    source = _api_source_without_comments()
    assert "well-known" not in source, (
        "the API module builds a JWKS URL — it must receive one, so the provider assumption "
        "stays at the root where a swap will find it"
    )
    assert _api_environment()["OIDC_JWKS_URI"] == "var.oidc_jwks_uri"

    call = re.search(r'module\s+"api"\s*\{(.*?)\n\}', ROOT_MAIN.read_text(), re.DOTALL).group(1)
    assert "well-known" in call, "root must be where the JWKS URL is built"


def test_the_provider_block_stays_out_of_the_browsers_dev_fallback() -> None:
    """`.env.example` is the SPA's dev fallback and has no non-VITE line.

    These five are server-side and Terraform computes them. A "server-side section" there would
    be a second, unchecked home for a value nothing in the browser may ever read.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a provider-block key appears in the SPA's example environment.
    """
    example = (INFRA.parent / "apps" / "portal" / ".env.example").read_text()
    assert "OIDC_" not in example


def test_every_provider_variable_refuses_the_empty_string() -> None:
    """An unset repo variable renders as "", which satisfies a required variable AND overrides
    a default — so having no default guards nothing. The validation block is the guard.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a provider variable would accept an empty value.
    """
    source = (API / "variables.tf").read_text()
    for key in OIDC_KEYS:
        name = key.lower()
        declaration = re.search(rf'variable\s+"{name}"\s*\{{(.*?)\n\}}', source, re.DOTALL)
        assert declaration, f"{name} is not declared"
        assert "validation {" in declaration.group(1), (
            f"{name} has no validation block, so an unset repo variable reaches the function as "
            "an empty string and fails far from its cause"
        )
