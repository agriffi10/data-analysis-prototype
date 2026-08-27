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
  API_ROLE_FORBIDDEN_SERVICES: The services whose arrival would mean a server-side login flow
    started being built here.
  OIDC_KEYS: The provider block — the five values the verifier reads about who issues
    its tokens, and the only five.
  _VALID_PROVIDER_BLOCK: A provider block satisfying every validation, so one field
    can be varied at a time.
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

#: Services this role must never learn about. The session store, its key and the secrets store
#: belong to a server-side login flow this API deliberately does not perform; the identity
#: provider is something it VERIFIES against and never calls.
API_ROLE_FORBIDDEN_SERVICES = ("dynamodb:", "kms:", "secretsmanager:", "cognito-idp:", "cognito-identity:")


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


def test_the_function_role_grants_logs_the_queue_and_ONE_assume_and_nothing_else() -> None:
    """Rendered, not read as a template — a placeholder can expand into a grant.

    **SPEC-196 owns this edit, and made it in the same commit that added the statement.** Until
    the identity layer landed this asserted zero statements naming STS, which was correct then
    and goes red the moment the API is allowed to act as its caller. Left as it was, the repair a
    builder reaches for is deleting the sweep — which also removes the session-store, key-store,
    secrets-store and identity-provider guards that have nothing to do with this change. So it is
    narrowed rather than dropped: exactly one STS statement, with both actions, on the portal role
    and nothing else.

    Both actions matter and either alone is the trap. ``sts:AssumeRole`` without ``sts:TagSession``
    renders, plans, applies and unit-tests green, then fails at runtime with a refusal naming
    neither the tag nor the missing action.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the role grants anything outside the set, names a forbidden service, or
        reaches STS on more than the portal role.
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
        .replace(
            "${portal_role_arn}", "arn:aws:iam::696000197480:role/dat-portal-user-role"
        )
    )
    document = json.loads(rendered)

    actions: set[str] = set()
    for statement in document["Statement"]:
        declared = statement["Action"]
        actions.update([declared] if isinstance(declared, str) else declared)

    assert actions == set(API_ROLE_ALLOWED_ACTIONS), (
        f"the API role grants {sorted(actions)} — anything beyond logs, the logs queue and the "
        "one assume belongs to the spec that needs it"
    )

    serialised = json.dumps(document)
    for service in API_ROLE_FORBIDDEN_SERVICES:
        assert service not in serialised, (
            f"the API role names {service} — a session store, its key, a secrets store and the "
            "identity provider all belong to a login flow this API does not perform"
        )

    sts_statements = [
        statement
        for statement in document["Statement"]
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
        "one door"
    )
    assert set(sts_statements[0]["Action"]) == {"sts:AssumeRole", "sts:TagSession"}
    assert sts_statements[0]["Resource"] == (
        "arn:aws:iam::696000197480:role/dat-portal-user-role"
    ), "the assume is not scoped to the portal role alone"

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

    call = _root_module_block("api")
    match = re.search(r"oidc_required_claims\s*=\s*jsonencode\((.+?)\)\n", call)
    assert match, "root does not render oidc_required_claims with jsonencode"
    rendered = match.group(1)

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

    # Deliberately NOT asserting the path convention. Cognito publishes under
    # `/.well-known/jwks.json` and Entra does not — so pinning that string here would turn a
    # fact about ONE provider into a repo invariant, and go red on a correct configuration the
    # day the provider changes. What matters is where the value is decided, not its shape.
    call = _root_module_block("api")
    assignment = re.search(r"^\s*oidc_jwks_uri\s*=\s*(.+)$", call, re.MULTILINE)
    assert assignment, "root does not assign oidc_jwks_uri"
    assert not assignment.group(1).strip().startswith("var."), (
        "root is forwarding oidc_jwks_uri from a variable — it must be the place the value is "
        "decided, so a provider swap has one site to change"
    )


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


#: A provider block that satisfies every validation, so a test can vary one field at a time.
_VALID_PROVIDER_BLOCK = {
    "OIDC_ISSUER": "https://provider.example/tenant",
    "OIDC_AUDIENCE": "a-client-id",
    "OIDC_JWKS_URI": "https://provider.example/keys",
    "OIDC_USERNAME_CLAIM": "preferred_username",
    "OIDC_REQUIRED_CLAIMS": '{"token_use":"id"}',
}


def _plan_with(values: dict[str, str]) -> set[str]:
    """Plans the five variable declarations with the given values and reports what was refused.

    The declarations are extracted into a scratch module rather than planned in place: the real
    module needs a dozen other inputs and a provider, and this test is about five validation
    conditions and nothing else. Extracted, the module declares no provider at all, so the init
    is offline and no credentials are involved.

    Args:
      values: Environment key to the value to plan with.

    Returns:
      The lowercased names of the variables OpenTofu refused. Empty means all were accepted.

    Raises:
      AssertionError: If the declarations cannot be extracted, or tofu is unavailable — a
        skip here would read as coverage this suite would not have.
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
        # Asserted rather than `check=True`: a CalledProcessError names the command and hides
        # the reason, and this init runs in an environment (minimal, no wrapper) that differs
        # from the one a developer reproduces in.
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


def test_every_provider_variable_actually_REFUSES_an_empty_value() -> None:
    """Runs the validations rather than checking that a validation block is present.

    The difference is the whole test. A block can be present with its condition weakened to
    something that accepts anything — `length(var.x) >= 0`, or plain `true` — and a presence
    check passes against every one of those. So this extracts the five declarations into a
    scratch module and plans it with each value empty, asserting OpenTofu refuses.

    An unset repo variable renders as the empty string, which satisfies a required variable AND
    overrides a default, so "no default" guards nothing on its own. The condition is the guard,
    and this is what says the condition works.

    The scratch module declares no provider, so the init is offline and needs no credentials.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any provider variable accepts an empty value.
    """
    refused = _plan_with(dict.fromkeys(OIDC_KEYS, ""))
    for key in OIDC_KEYS:
        assert key.lower() in refused, (
            f"{key.lower()} accepted an empty value — an unset repo variable reaches the "
            "function as an empty string and fails far from its cause"
        )


def test_the_required_claims_variable_refuses_what_would_silently_disable_the_check() -> None:
    """A claim map is an object. Everything else here plans clean and breaks in the verifier.

    Each of these was measured rather than reasoned about, and two were surprises: `jsondecode`
    accepts a bare scalar, and `tomap` accepts the literal `null`. A null arriving is exactly
    the "the token-type check never runs" outcome — which means a genuine Cognito ACCESS token
    would be accepted.

    An empty OBJECT is deliberately allowed: a provider that asserts no such claim is not
    thereby misconfigured.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a non-object is accepted, or an empty object is refused.
    """
    for value in ("", "null", "42", '"id"', "[]", '["a"]'):
        refused = _plan_with({**_VALID_PROVIDER_BLOCK, "OIDC_REQUIRED_CLAIMS": value})
        assert "oidc_required_claims" in refused, (
            f"oidc_required_claims accepted {value!r}, which reaches the verifier and stops the "
            "token-type check running at all"
        )

    for value in ("{}", '{"token_use":"id"}'):
        refused = _plan_with({**_VALID_PROVIDER_BLOCK, "OIDC_REQUIRED_CLAIMS": value})
        assert not refused, f"oidc_required_claims refused {value!r}, which is a valid claim map"


def test_the_issuer_terraform_sends_is_the_one_the_verifier_builds() -> None:
    """Two spellings of one string, in two languages, and nothing joined them.

    `cpcommon.auth` derives a Cognito issuer from REGION + USER_POOL_ID for the control planes;
    root Terraform renders one into OIDC_ISSUER for the API. They agree today. A trailing slash
    on either — the likeliest divergence, and invisible to every other test here — makes every
    token fail `iss` verification on the day the API starts reading it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two templates differ once their interpolations are normalised.
    """
    root = ROOT_MAIN.read_text()
    terraform = re.search(r'cognito_issuer\s*=\s*"([^"]+)"', root)
    assert terraform, "root no longer builds a cognito issuer local"

    source = (
        pathlib.Path(__file__).resolve().parent
        / "control-plane-common"
        / "cpcommon"
        / "auth.py"
    ).read_text()
    python = re.search(r'issuer = f"([^"]+)"', source)
    assert python, "cpcommon.auth no longer builds a Cognito issuer"

    normalise = lambda text: re.sub(r"\$?\{[^}]+\}", "{}", text)  # noqa: E731
    assert normalise(terraform.group(1)) == normalise(python.group(1)), (
        f"Terraform sends {terraform.group(1)!r} and the verifier builds {python.group(1)!r} — "
        "these must be the same string or every token fails issuer verification"
    )


def test_the_three_literal_provider_values_are_pinned() -> None:
    """The two that are literals, and the audience, which is the likeliest silent mis-wiring.

    Pointing `oidc_audience` at the pool id rather than the app client id, or naming `sub` as
    the username claim, plans clean and passes every other assertion in this file. The first
    refuses every token; the second attributes every request to an opaque uuid rather than to
    the username this whole product is keyed on.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three has drifted.
    """
    call = _root_module_block("api")
    assert re.search(r'oidc_username_claim\s*=\s*"cognito:username"', call), (
        "the username claim is not cognito:username — every request would be attributed to "
        "whatever this names instead"
    )
    assert re.search(r"oidc_audience\s*=\s*module\.auth\.user_pool_client_id", call), (
        "the audience must be the app client the SPA's ID token is issued to, not the pool"
    )
    assert re.search(r"oidc_issuer\s*=\s*local\.cognito_issuer", call)
