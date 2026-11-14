"""The API module's front door, asserted over the Terraform that builds it.

Three scenarios: what the function must NOT be attached to, what the browser must be able to
reach, and the provider block the verifier reads. The reasoning behind each — which failures
apply green, and which one broke fresh sign-in for a day — is in
``infra/modules/api/README.md``.

Attributes:
  INFRA: The IaC tree.
  API: The API module's directory.
  ROOT_MAIN: The composition that builds the origins and the connect-src.
  AUTH_COGNITO: The app client whose callback list gains the container origin.
  CSP_CONNECT_SRC_TERMS: Every term the deployed connect-src must carry, named independently.
  FORBIDDEN_IN_API_MODULE: Block types whose presence means a network attachment was started.
  API_ROLE_ALLOWED_ACTIONS: The whole of the API function's permissions. The two S3 actions are
    the membership index and nothing else, and they are scoped by the two statements
    ``test_the_membership_index_grant_is_narrow`` pins: a read by exact key, and the list that
    makes an ABSENT index answerable rather than a denial. S3 tells a caller an object is missing
    only when that caller can list the bucket, so a read-only grant would answer AccessDenied for
    every user who belongs to no shared space — which is the common case, and a fault the user
    cannot act on.
  MEMBERSHIP_INDEX_PREFIX: The one prefix those two statements may touch.
  API_ROLE_FORBIDDEN_SERVICES: Services whose arrival would mean a server-side login flow.
  REQUIRED_ENVIRONMENT_KEYS: The configuration the function cannot start without.
  OIDC_KEYS: The provider block — the five values the verifier reads, and the only five.
  PRESIGN_PROBE_REGIONS: Two regions, and BOTH are required. botocore presigns against the legacy
    global host everywhere by default, but the setting that corrects it differs:
    ``us_east_1_regional_endpoint`` moves only ``us-east-1`` and ``addressing_style`` moves only
    the others. A guard probing one region passes on half a fix, and the half it cannot see is
    the transition environment — where the same outage would return with this test still green.
    Neither is read from the deployment: the point is to hold the config correct for a region
    move, which a probe of today's region cannot do.
  PRESIGN_PROBE_BUCKET: An arbitrary bucket name. It is substituted into both halves of the
    comparison, so its value carries no meaning beyond being the same on each side.
  REGIONAL_ENDPOINT_ENV: The environment variable that sets the same endpoint style the code
    sets, and the reason the presign guard clears its environment. A developer who has fought
    this default before may have it exported, and with it set the guard passes against code that
    has no endpoint configuration at all — green locally, broken for every user. The shared
    config file is the third source of the same value, which is why ``AWS_CONFIG_FILE`` is
    pointed at nothing rather than merely left alone.
"""

import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse

from cpcommon.jwks import (
    API_FUNCTION_TIMEOUT_SECONDS,
    API_GATEWAY_INTEGRATION_CEILING_SECONDS,
    JWKS_HTTP_TIMEOUT_SECONDS,
)
from tf_blocks import (
    argument,
    lambda_declaration,
    lambda_environment,
    lambda_input,
    strip_noise,
)

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
API = INFRA / "modules" / "api"
ROOT_MAIN = INFRA / "main.tf"
AUTH_COGNITO = INFRA / "modules" / "auth" / "cognito.tf"
API_CLIENT = INFRA.parent / "apps" / "portal" / "src" / "lib" / "apiClient.ts"

CSP_CONNECT_SRC_TERMS = (
    "'self'",
    "https://cognito-idp.${var.aws_region}.amazonaws.com",
    "https://${local.cognito_hosted_ui_domain}",
    "https://${local.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "https://${local.shared_space_bucket_name}.s3.${var.aws_region}.amazonaws.com",
    "local.api_origin",
)

# Gone, and asserted gone by the set equality this tuple feeds: athena, glue and sqs left with
# the SDK clients that called them, and cognito-identity with the Identity Pool. The last is the
# one worth naming — it looks like a sign-in host and is not one, and leaving it would be a live
# permission for the exact call the retirement exists to make impossible. Both Cognito hosts
# above STAY: Amplify still runs in the tab, and the code exchange is a fetch, not a navigation.

PRESIGN_PROBE_REGIONS = ("us-east-1", "eu-west-1")
PRESIGN_PROBE_BUCKET = "probe-user-space"
REGIONAL_ENDPOINT_ENV = "AWS_S3_US_EAST_1_REGIONAL_ENDPOINT"

FORBIDDEN_IN_API_MODULE = ("vpc_config", "aws_security_group", "aws_subnet", "subnet_ids")

API_ROLE_ALLOWED_ACTIONS = frozenset(
    {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "s3:GetObject",
        "s3:ListBucket",
        "sqs:SendMessage",
        "sts:AssumeRole",
        "sts:TagSession",
    }
)

MEMBERSHIP_INDEX_PREFIX = "memberships/"

API_ROLE_FORBIDDEN_SERVICES = (
    "dynamodb:",
    "kms:",
    "secretsmanager:",
    "cognito-idp:",
    "cognito-identity:",
)

REQUIRED_ENVIRONMENT_KEYS = (
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
    "OIDC_AUDIENCE": '["a-client-id", "another-client-id"]',
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


def _connect_src_terms() -> tuple[str, ...]:
    """The connect-src source list, read out of root's Terraform as written.

    Interpolations are left unresolved: a caller comparing against a literal wants them intact,
    and a caller resolving them says which ones it resolved. Read once here rather than sliced at
    each use, so two readers cannot disagree about where the list ends.

    Args:
      None.

    Returns:
      One entry per source, in file order, without quotes, commas or comment lines.

    Raises:
      ValueError: If the local is no longer a `join(` over a list literal, which means the shape
        every caller slices for has changed and the silent answer would be an empty list.
    """
    root = ROOT_MAIN.read_text()
    start = root.index("csp_connect_src = join(")
    block = root[start : root.index("\n  ])", start)]
    return tuple(
        line.strip().rstrip(",").strip('"')
        for line in block.splitlines()[1:]
        if line.strip() and not line.strip().startswith("#")
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
    function = lambda_declaration((API / "lambda.tf").read_text(), "api")
    body = lambda_environment(function)
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
        .replace("${admin_bucket_arn}", "arn:aws:s3:::dat-prod-athena-admin")
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
    # ONE log group is declared in this module: the API Gateway access log. The function's own
    # belongs to the container module it calls, which is what stops a function and its log group
    # being declared in two places and disagreeing — so this counts the module's, and the
    # function's retention is asserted where it is set.
    assert set(re.findall(r'resource\s+"aws_cloudwatch_log_group"\s+"(\w+)"', source)) == {
        "access",
    }
    assert len(re.findall(r"retention_in_days\s*=\s*\d+", source)) == 1, (
        "the access-log group needs a retention"
    )
    assert "retention_in_days" in (
        (INFRA / "modules" / "docker-lambda" / "main.tf").read_text(encoding="utf-8")
    ), "the container module must still manage the function log group's retention"
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
        "BUILD_VERSION must NOT be set by Terraform — the stamp travels in the artefact (the "
        "zip's package or the image's task root), and an env-borne one would name the last "
        "infra commit rather than the running code"
    )
    # There is no placeholder artefact any more: the image is valid from the first apply. What
    # CI owns is now the image REFERENCE, and the ignore that protects it lives in the module
    # this function calls — so the assertion follows it there rather than being dropped.
    call = lambda_declaration(source, "api")
    assert argument(call, "source") == '"../docker-lambda"', (
        "the API function is no longer a call to the fleet's container module"
    )
    # Comments blanked first. That module's own comment explains why a stale
    # `ignore_changes = [layers]` would be a fossil, and a raw scan reads the explanation as the
    # declaration — a failure sentence describing something the file does not do.
    module_source = strip_noise(
        (INFRA / "modules" / "docker-lambda" / "main.tf").read_text(encoding="utf-8")
    )
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", module_source)
    assert ignored, "the container module must ignore changes to what CI owns"
    assert ignored.group(1).strip() == "image_uri", (
        f"ignore_changes is [{ignored.group(1).strip()}] — an apply would drag the whole fleet "
        "back to whatever tag Terraform was last handed, and a stale `layers` entry would be a "
        "fossil that reads as meaningful on a function that has none"
    )

    declared_timeout = int(lambda_input(call, "timeout"))
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


def test_the_membership_index_grant_is_narrow() -> None:
    """The two S3 statements, read back from the rendered template, exactly.

    The identity layer reads one caller's membership index before that caller's credentials
    exist, so the read runs on the execution role — a privilege held on behalf of every caller,
    which is why it is pinned by resource and not only by action.

    **The list statement is what makes an absence answerable, and its condition is what keeps it
    from being an inventory.** Unconditioned, it would hand the one role every request runs
    through the ability to enumerate the admin bucket — every shared space's name, and then every
    roster, which is the disclosure this project declines by publishing no shared-space directory
    at all. Conditioned to this prefix it admits the membership objects and nothing else.

    A write is absent and asserted absent: the API projects the index, it never owns it. The
    plane that owns membership is the only writer.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either statement widens beyond the membership prefix, if the list is
        unconditioned, or if the role gains a write.
    """
    policy = _rendered_execution_policy()
    statements = {
        statement["Sid"]: statement
        for statement in policy["Statement"]
        if statement["Sid"] in ("MembershipIndexRead", "MembershipIndexList")
    }
    assert set(statements) == {"MembershipIndexRead", "MembershipIndexList"}

    read = statements["MembershipIndexRead"]
    assert read["Action"] == "s3:GetObject"
    assert read["Resource"].endswith(f"/{MEMBERSHIP_INDEX_PREFIX}*")
    assert "Condition" not in read, (
        "a condition on the read would be a second place the prefix is stated, and the resource "
        "already says it"
    )

    listing = statements["MembershipIndexList"]
    assert listing["Action"] == "s3:ListBucket"
    assert listing["Resource"] == read["Resource"].rsplit("/", 1)[0].rsplit("/", 1)[0], (
        "the list is on the bucket, not on a key"
    )
    assert listing["Condition"] == {
        "StringLike": {"s3:prefix": f"{MEMBERSHIP_INDEX_PREFIX}*"}
    }

    for statement in policy["Statement"]:
        actions = (
            [statement["Action"]]
            if isinstance(statement["Action"], str)
            else statement["Action"]
        )
        assert not any(action.startswith("s3:") for action in actions) or statement["Sid"] in (
            "MembershipIndexRead",
            "MembershipIndexList",
        ), f"{statement['Sid']} names S3 outside the two membership-index statements"
        assert "s3:PutObject" not in actions and "s3:DeleteObject" not in actions, (
            "the API reads the membership index and never writes it — the plane that owns "
            "membership is its only writer"
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

    assert re.search(r"allow_origins\s*=\s*compact\(\[var\.spa_origin\]\)", source), (
        "allow_origins must be the one exact origin, compacted so an unset spa_origin drops out "
        "rather than reaching the gateway as an empty string. It was two through the cutover; "
        "the second was CloudFront's and went with the distribution"
    )
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

    found_terms = set(_connect_src_terms())
    assert found_terms == set(CSP_CONNECT_SRC_TERMS), (
        f"root's connect-src is {sorted(found_terms)}; expected {sorted(CSP_CONNECT_SRC_TERMS)}. "
        "A term dropped here breaks one feature, only in a browser, and nothing offline sees it"
    )
    # Terraform computes connect-src and nothing else of the policy: every other directive is
    # the Next.js server's, held against a recorded literal in its own test. So no Terraform file
    # may assemble a whole policy again — checked across the whole tree rather than against a
    # single file, since the next one to try would be a different file.
    assemblers = [
        path
        for path in INFRA.rglob("*.tf")
        if ".terraform" not in path.parts and "content_security_policy = join(" in path.read_text()
    ]
    assert assemblers == [], (
        f"{[str(p) for p in assemblers]} assembles a Content-Security-Policy. The server builds "
        "the policy from connect-src alone, so a second assembly is a second policy nothing "
        "compares and nothing serves"
    )

    callbacks = re.search(
        r"callback_urls\s*=\s*distinct\(compact\(\[([^\]]*)\]\)\)", AUTH_COGNITO.read_text()
    )
    assert callbacks, (
        "the callback list must be distinct(compact([...])) — compact so an unset origin drops "
        "out rather than reaching Cognito as an empty string, distinct because Cognito rejects "
        "a duplicated URL rather than deduplicating it"
    )
    entries = [entry.strip() for entry in callbacks.group(1).split(",") if entry.strip()]
    assert entries == ['"http://localhost:5173"', "var.spa_origin"], (
        f"the callback list is {entries}. EQUALITY, not containment: the CloudFront entry was "
        "removed with the distribution, and a list that merely CONTAINS the two right entries "
        "would still pass while admitting an origin nothing serves"
    )


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
    assert re.search(
        r"oidc_audience\s*=\s*\[\s*module\.auth\.user_pool_client_id\s*,\s*"
        r"module\.auth\.server_client_id\s*\]",
        root_call,
    ), (
        "the audience must be both app clients, the SPA's and the portal server's, never the pool"
    )
    assert environment["OIDC_AUDIENCE"] == 'join(",", var.oidc_audience)', (
        "the list must reach the function comma-joined, which is the one form the verifier parses"
    )
    assert "OIDC_" not in (INFRA.parent / "apps" / "portal" / ".env.example").read_text(), (
        "these five are server-side; a copy in the SPA's dev fallback is a second, unchecked home"
    )

    # This used to cross-check Terraform's issuer against one the verifier built for itself, so a
    # trailing slash on either side could not silently fail every `iss` check. There is no second
    # construction left to disagree with: the control planes stopped verifying, and the Cognito
    # arm that built an issuer from `USER_POOL_ID` went with them. What replaces it is the reason
    # the cross-check was needed at all — exactly one place decides the issuer, and it is the root.
    terraform_issuer = re.search(r'cognito_issuer\s*=\s*"([^"]+)"', ROOT_MAIN.read_text())
    assert terraform_issuer, "root no longer builds a Cognito issuer"
    assert "cognito-idp" not in (
        pathlib.Path(__file__).resolve().parent
        / "control-plane-common" / "cpcommon" / "auth.py"
    ).read_text(), (
        "the verifier names a provider again — the issuer is configuration, and a second "
        "construction here is what the cross-check this replaced existed to catch"
    )
    issuer_sites = re.findall(r'cognito_issuer\s*=\s*"', ROOT_MAIN.read_text())
    assert len(issuer_sites) == 1, (
        f"the issuer is built at {len(issuer_sites)} sites in root — a provider swap must have one"
    )

    # One variable empty per plan: a list variable that cannot parse stops OpenTofu before it
    # reports any other, so a single all-empty plan would name only the first.
    for key in OIDC_KEYS:
        refused_empty = _plan_provider_variables({**_VALID_PROVIDER_BLOCK, key: ""})
        assert key.lower() in refused_empty, (
            f"{key.lower()} accepted an empty value — an unset repo variable reaches the "
            "function as an empty string and fails far from its cause"
        )
    for value in ("[]", '[""]', '["a,b"]', '["a", " "]'):
        assert "oidc_audience" in _plan_provider_variables(
            {**_VALID_PROVIDER_BLOCK, "OIDC_AUDIENCE": value}
        ), (
            f"oidc_audience accepted {value!r} — an empty set refuses every token, and an empty "
            "or comma-holding id renders a list the verifier refuses as a server fault"
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


def test_a_presigned_url_names_the_s3_host_the_csp_admits(monkeypatch) -> None:
    """The minted host and the admitted host, derived from opposite sides and compared.

    **This is the assertion the term list cannot make.** ``CSP_CONNECT_SRC_TERMS`` says the policy
    names ``s3.${var.aws_region}.amazonaws.com``, and that has always been true; what it cannot say
    is whether the presigner emits that host. botocore's default is the legacy global
    ``s3.amazonaws.com``, so both halves read correct while disagreeing, and the browser blocked
    every upload before sending it — reported to the user as a generic network error. Downloads
    went on working, because a navigation is not governed by ``connect-src``, which is what let the
    divergence look like health.

    Nothing else could have caught it. The presign suites drive a fake signer, so no offline test
    ever built a real client; the CSP suites compare Terraform against Terraform; and a review of
    either half reads a correct sentence. Only a comparison spanning the two can fail.

    **Both regions are probed because the corrections are region-split**, and a fix that moves one
    of them looks complete. See ``PRESIGN_PROBE_REGIONS``.

    Args:
      monkeypatch: pytest's patcher, for the region botocore resolves the endpoint from.

    Returns:
      None.

    Raises:
      AssertionError: If a presigned host is not the host the policy admits for that region, or if
        the policy no longer names the user-space bucket at all — the second would make the first
        vacuous.
    """
    import sys

    sys.path.insert(0, str(INFRA.parent / "lambdas" / "api"))
    from apicommon import identity

    monkeypatch.delenv(REGIONAL_ENDPOINT_ENV, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", os.devnull)

    admitting = [term for term in _connect_src_terms() if "user_space_bucket_name" in term]
    assert len(admitting) == 1, (
        f"expected exactly one connect-src term for the user-space bucket, found {admitting} — "
        "the substitution below would compare against the wrong term or against nothing"
    )

    for region in PRESIGN_PROBE_REGIONS:
        monkeypatch.setenv("AWS_REGION", region)
        monkeypatch.setenv("AWS_DEFAULT_REGION", region)

        minted = urllib.parse.urlparse(
            identity._client(
                "s3",
                identity.AssumedCredentials(
                    access_key_id="AKIAIOSFODNN7EXAMPLE",
                    secret_access_key="s" * 40,
                    session_token="token",
                    expires_at=datetime.datetime.now(datetime.UTC),
                ),
            ).generate_presigned_url(
                "put_object",
                Params={"Bucket": PRESIGN_PROBE_BUCKET, "Key": "a/b.csv"},
                ExpiresIn=900,
            )
        ).netloc

        admitted = urllib.parse.urlparse(
            admitting[0]
            .replace("${local.user_space_bucket_name}", PRESIGN_PROBE_BUCKET)
            .replace("${var.aws_region}", region)
        ).netloc

        assert minted == admitted, (
            f"in {region} the API presigns against {minted!r} and the SPA's connect-src admits "
            f"{admitted!r}. Every upload is blocked in the browser before it is sent, and reaches "
            "the user as 'Can't reach the server' — while downloads, listings and every "
            "server-side call keep working"
        )
