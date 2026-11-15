"""The portal server's session infrastructure: the store, the confidential client and its secret.

Every property here applies green when it is wrong and fails later, at a sign-in or on the first
switch-off: a store inside the web tier's switch drops every session, a client that does not mirror
the SPA's loses a claim, a secret in the environment ends up in every task definition revision.

Attributes:
  INFRA: The IaC tree.
  ROOT_MAIN: The root composition.
  ROOT_OUTPUTS: The root outputs the deploy workflow reads.
  AUTH: The auth module's Cognito definitions.
  AUTH_OUTPUTS: The auth module's outputs.
  STORE: The session-store module's resources.
  SPA: The spa module's directory.
  DEPLOY_INFRA: The infrastructure deploy workflow.
  MIRRORED: The sign-in settings the server client must share with the SPA client.
"""

import fnmatch
import json
import pathlib
import re

import yaml
from tf_blocks import blocks, module_calls, output_blocks

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"
ROOT_OUTPUTS = INFRA / "outputs.tf"
AUTH = INFRA / "modules" / "auth" / "cognito.tf"
AUTH_OUTPUTS = INFRA / "modules" / "auth" / "outputs.tf"
STORE = INFRA / "modules" / "session-store" / "main.tf"
SPA = INFRA / "modules" / "spa"
DEPLOY_INFRA = INFRA.parent / ".github" / "workflows" / "deploy-infra.yml"

MIRRORED = (
    "allowed_oauth_flows_user_pool_client",
    "allowed_oauth_flows",
    "allowed_oauth_scopes",
    "supported_identity_providers",
    "prevent_user_existence_errors",
    "explicit_auth_flows",
)


def _argument(body: str, name: str) -> str | None:
    """Reads one top-level argument's raw value from a resource body, whitespace collapsed.

    Args:
      body: The resource's body.
      name: The argument.

    Returns:
      The value as written, or None when the argument is absent.

    Raises:
      None.
    """
    match = re.search(rf"^\s*{name}\s*=\s*(\[[^\]]*\]|[^\n]+)", body, re.MULTILINE)
    return " ".join(match.group(1).split()) if match else None


def _session_environment_keys() -> list[str]:
    """Reads the variable names root's ``session_environment`` local renders into the task.

    The block is read to its own closing line, not to the first ``}``: values interpolate with
    ``${...}``, and a parse that stopped at the first brace read five of the eleven names.

    Args:
      None.

    Returns:
      The names, in the order written.

    Raises:
      AssertionError: If the local is no longer written as a block this can read.
    """
    block = re.search(r"^  session_environment = \{\n(.*?)^  \}$", ROOT_MAIN.read_text(), re.MULTILINE | re.DOTALL)
    assert block, "root no longer writes session_environment as a block"
    return re.findall(r"^\s{4}([A-Z_]+)\s*=", block.group(1), re.MULTILINE)


def test_the_session_store_sits_outside_the_switch_and_reads_nothing_inside_it() -> None:
    """Switching the tier off must neither schedule the key for deletion nor drop every session."""
    call = module_calls(ROOT_MAIN.read_text())["session_store"]
    assert not re.search(r"^\s*(count|for_each)\s*=", call, re.MULTILINE), "the session store is on a switch"
    assert "module.network" not in call and "module.spa" not in call, (
        "the session store reads a module the web tier's switch removes"
    )


def test_the_key_names_only_the_account_and_the_table_is_encrypted_with_it() -> None:
    """A key policy naming a role inside the switch, or a table on the AWS-owned key, fails later."""
    text = STORE.read_text()
    key = blocks(text, "aws_kms_key")["session"]
    principals = re.findall(r"Principal\s*=\s*\{\s*AWS\s*=\s*\"([^\"]+)\"", key)
    assert principals == ["arn:aws:iam::${var.account_id}:root"], f"the key's policy names {principals}"
    assert _argument(key, "enable_key_rotation") == "true"

    table = blocks(text, "aws_dynamodb_table")["sessions"]
    assert re.search(r"kms_key_arn\s*=\s*aws_kms_key\.session\.arn", table), "not under the session key"
    assert re.search(r'ttl\s*\{\s*attribute_name\s*=\s*"expiresAt"\s*enabled\s*=\s*true', table)
    assert re.search(r"point_in_time_recovery\s*\{\s*enabled\s*=\s*false", table), (
        "a backup would keep refresh tokens past their sessions"
    )
    assert _argument(table, "deletion_protection_enabled") == "true"


def test_the_server_and_dev_clients_mirror_the_spa_client_and_differ_only_where_they_must() -> None:
    """A setting a client does not share changes what its tokens carry or allow.

    The dev client is the server client with a localhost callback: a laptop signs in through the same
    routes, so any other difference is a sign-in that works in one place and not the other.
    """
    clients = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")
    assert set(clients) == {"spa", "server", "dev"}, f"the clients are {sorted(clients)}"
    spa, server, dev = clients["spa"], clients["server"], clients["dev"]

    for confidential in (server, dev):
        for setting in MIRRORED:
            assert _argument(confidential, setting) == _argument(spa, setting), f"{setting} differs"
    for client in (spa, server, dev):
        assert "read_attributes" not in client and "write_attributes" not in client, (
            "an attribute list that omits a custom:shared_space_k slot drops that claim"
        )
    assert _argument(spa, "generate_secret") == "false"
    assert _argument(server, "generate_secret") == "true"
    assert _argument(server, "callback_urls") == '["${var.spa_origin}/auth/callback"]'
    assert _argument(server, "logout_urls") == "[var.spa_origin]"
    assert _argument(server, "enable_token_revocation") == "true"
    assert re.search(r'refresh_token_rotation\s*\{\s*feature\s*=\s*"DISABLED"', server)

    def without_urls(body: str) -> str:
        code = re.sub(r"^\s*#.*$", "", body, flags=re.MULTILINE)
        return " ".join(re.sub(r"^\s*(name|callback_urls|logout_urls)\s*=.*$", "", code, flags=re.MULTILINE).split())

    assert without_urls(dev) == without_urls(server), "the dev client differs from the server client beyond its URLs"
    assert _argument(dev, "callback_urls") == '["${var.dev_origin}/auth/callback"]'
    assert _argument(dev, "logout_urls") == "[var.dev_origin]"
    assert "localhost" not in server, "the server client names localhost"
    assert '"http://localhost:5173"' in AUTH.read_text().split("callback_urls = distinct(")[1].split(")")[0], (
        "the public client loses localhost only when the merge that retires it lands"
    )
    assert re.search(r'^\s*dev_origin\s*=\s*"http://localhost:5173"\s*$', ROOT_MAIN.read_text(), re.MULTILINE)


def test_every_variable_the_server_requires_is_one_the_infrastructure_renders() -> None:
    """A variable the start check requires and the task does not carry stops every container.

    The portal refuses to start without any session variable, so a name added to the server's list and
    not to the task definition passes every offline gate and takes the deployed portal down.
    """
    config = (INFRA.parent / "apps" / "portal" / "src" / "server" / "session" / "config.ts").read_text()
    listed = re.search(r"export const SESSION_VARIABLES = \[(.*?)\] as const;", config, re.DOTALL)
    assert listed, "the server no longer lists SESSION_VARIABLES in the form this test reads"
    required = set(re.findall(r"'([A-Z_]+)'", listed.group(1)))
    assert len(required) > 10, f"read only {sorted(required)}"
    optional_list = re.search(r"export const OPTIONAL_SESSION_VARIABLES = \[(.*?)\] as const;", config, re.DOTALL)
    assert optional_list, "the server no longer lists OPTIONAL_SESSION_VARIABLES in the form this test reads"
    optional = set(re.findall(r"'([A-Z_]+)'", optional_list.group(1)))
    assert optional == {"OIDC_USERNAME_CLAIM", "OIDC_IDENTITY_PROVIDER"}, (
        f"the optional list is {sorted(optional)}: moving a variable there stops the server refusing to start "
        "without it, so it is a deliberate edit to this line"
    )
    assert not optional & required, f"optional {sorted(optional)} overlaps the required list"

    rendered = set(_session_environment_keys())
    assert re.search(r'name\s*=\s*"OIDC_CLIENT_SECRET"', (SPA / "ecs.tf").read_text()), "the task no longer injects the secret"
    assert required <= rendered | {"OIDC_CLIENT_SECRET"}, (
        f"the server requires {sorted(required - rendered - {'OIDC_CLIENT_SECRET'})} that the task does not carry"
    )
    assert rendered <= required | optional, f"the task carries {sorted(rendered - required - optional)} that the server does not read"


def test_the_server_and_the_api_read_the_username_from_one_claim() -> None:
    """The browser builds prefixes from the server's username and the API attributes requests by its own.

    Two readers of one claim, so one value: a copy in each would let a provider change move one reader
    and leave the other naming a different user — every prefix built from one name and every request
    attributed to another.
    """
    root = ROOT_MAIN.read_text()
    local = re.search(r'^\s*oidc_username_claim\s*=\s*"([^"]+)"', root, re.MULTILINE)
    assert local, "root no longer decides the username claim in one local"
    block = re.search(r"^  session_environment = \{\n(.*?)^  \}$", root, re.MULTILINE | re.DOTALL)
    assert block, "root no longer writes session_environment as a block"
    assert _argument(block.group(1), "OIDC_USERNAME_CLAIM") == "local.oidc_username_claim", (
        "the portal server must read the username claim from the local the API reads"
    )
    api_call = re.search(r'^module "api" \{\n(.*?)^\}$', root, re.MULTILINE | re.DOTALL)
    assert api_call, "root no longer calls the api module"
    assert _argument(api_call.group(1), "oidc_username_claim") == "local.oidc_username_claim", (
        "the API must read the username claim from the local the portal server reads"
    )
    assert len(re.findall(r'"cognito:username"', root)) == 1, "the claim is written as a literal more than once"


def test_the_dev_parameter_is_the_task_environment_with_the_dev_client() -> None:
    """A local server rendered from other values than the task's works on a laptop and nowhere else.

    Both sides must be built from the same locals, so a literal on either side fails here: the root
    local that becomes the parameter, and the spa module call that becomes the task definition.
    """
    root = ROOT_MAIN.read_text()
    local = re.search(r"^\s*dev_session_environment = merge\((.*?)^\s*\)$", root, re.MULTILINE | re.DOTALL)
    assert local, "root no longer builds dev_session_environment with merge()"
    body = local.group(1)
    for source in ("local.spa_runtime_config", "local.csp_connect_src", "local.session_environment", "local.dev_origin"):
        assert source in body, f"the dev environment is not built from {source}"
    assert re.findall(r'"[^"]*"', body) == ['"CONFIG_${key}"', '"OIDC_CLIENT_ID"'], (
        "the dev environment names a literal value"
    )
    assert re.search(r'"CONFIG_\$\{key\}"', (SPA / "ecs.tf").read_text()), "the task renders CONFIG_ keys some other way"

    spa_call = module_calls(root)["spa"]
    for argument, source in (
        ("runtime_config", "local.spa_runtime_config"),
        ("csp_connect_src", "local.csp_connect_src"),
        ("session_environment", "local.session_environment"),
    ):
        assert re.search(rf"^\s*{argument}\s*=\s*{re.escape(source)}\s*$", spa_call, re.MULTILINE), (
            f"the task definition's {argument} is not {source}"
        )

    parameter = blocks(AUTH.read_text(), "aws_ssm_parameter")["dev_session_environment"]
    assert _argument(parameter, "type") == '"SecureString"'
    assert " ".join(parameter.split()).count("jsonencode(merge(var.dev_session_environment, {") == 1
    added = re.findall(r"^\s*([A-Z_]+)\s*=\s*(\S+)$", parameter, re.MULTILINE)
    assert added == [
        ("OIDC_CLIENT_ID", "aws_cognito_user_pool_client.dev.id"),
        ("OIDC_CLIENT_SECRET", "aws_cognito_user_pool_client.dev.client_secret"),
    ]
    for path in (AUTH_OUTPUTS, ROOT_OUTPUTS):
        assert "dev_session_environment" not in path.read_text(), f"{path.name} exposes the dev parameter"


def test_every_rotation_block_states_its_grace_period() -> None:
    """An omitted grace period plans as null and reads back as AWS's 0, which fails the apply.

    The provider marks ``retry_grace_period_seconds`` optional but not computed, so a client created
    without it exists in AWS while the apply fails as an inconsistent result, leaving everything
    that depends on the client unapplied. The plan is green either way, so only this test sees it.
    """
    files = sorted(INFRA.rglob("*.tf"))
    assert len(files) > 20, f"Swept only {len(files)} .tf files — the glob found the wrong tree."
    dynamic = [str(path.relative_to(INFRA)) for path in files if re.search(r'dynamic\s+"refresh_token_rotation"', path.read_text())]
    assert dynamic == [], f"a dynamic refresh_token_rotation block escapes this sweep: {dynamic}"
    rotations = [
        (path.relative_to(INFRA), match.group(1))
        for path in files
        for match in re.finditer(r"refresh_token_rotation\s*\{([^}]*)\}", path.read_text())
    ]
    assert rotations, "no refresh_token_rotation block found; the sweep reads nothing"
    stated = re.compile(r"^[ \t]*retry_grace_period_seconds[ \t]*=[ \t]*\d+[ \t]*$", re.MULTILINE)
    missing = [str(path) for path, body in rotations if not stated.search(body)]
    assert missing == [], f"refresh_token_rotation without a numeric retry_grace_period_seconds in {missing}"


def test_the_session_ceiling_and_the_refresh_token_come_from_one_local() -> None:
    """A session that outlives its refresh token answers 401 on a cookie the user believes is live."""
    server = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")["server"]
    assert _argument(server, "refresh_token_validity") == "local.server_token_validity.refresh_days"
    ceiling = output_blocks(AUTH_OUTPUTS.read_text())["server_session_max_age_seconds"]
    assert "local.server_token_validity.refresh_days * 86400" in ceiling
    assert re.search(
        r"SESSION_MAX_AGE_SECONDS\s*=\s*tostring\(module\.auth\.server_session_max_age_seconds\)",
        ROOT_MAIN.read_text(),
    ), "the server's ceiling is not the client's refresh-token lifetime"


def test_the_secret_reaches_the_task_only_through_ssm_and_the_execution_role() -> None:
    """In the environment it would sit in every task definition revision; in an output, in logs."""
    ecs = (SPA / "ecs.tf").read_text()
    assert re.search(r'name\s*=\s*"OIDC_CLIENT_SECRET"\s*valueFrom\s*=\s*var\.client_secret_parameter_arn', ecs)

    variables = (SPA / "variables.tf").read_text()
    assert 'strcontains(upper(key), "SECRET")' in variables and '!startswith(key, "CONFIG_")' in variables, (
        "the session environment's validation no longer refuses a secret or a CONFIG_ key"
    )
    session_keys = _session_environment_keys()
    assert len(session_keys) > 10 and not [key for key in session_keys if "SECRET" in key or key.startswith("CONFIG_")]

    execution = json.loads((SPA / "policies" / "task-execution-policy.json.tftpl").read_text())
    def actions(statement: dict[str, object]) -> list[str]:
        named = statement["Action"]
        return [str(a) for a in named] if isinstance(named, list) else [str(named)]

    ssm = [s for s in execution["Statement"] if any(a.lower().startswith("ssm:") for a in actions(s))]
    assert ssm == [
        {
            "Sid": "ReadTheClientSecret",
            "Effect": "Allow",
            "Action": "ssm:GetParameters",
            "Resource": "${client_secret_parameter_arn}",
        }
    ]
    task = (SPA / "policies" / "task-session-policy.json.tftpl").read_text()
    assert "ssm:" not in task, "the task role can read SSM"

    for path in (AUTH_OUTPUTS, ROOT_OUTPUTS):
        assert "client_secret" not in path.read_text(), f"{path.name} exposes the client secret"


def test_the_deploy_brands_every_app_client() -> None:
    """Managed Login's pages fail to render for a client with no branding style."""
    steps = yaml.safe_load(DEPLOY_INFRA.read_text())["jobs"]["apply"]["steps"]
    branding = next(step for step in steps if step.get("name") == "Ensure Managed Login default branding")
    loop = re.search(r"for OUTPUT in ([^;]+);", branding["run"])
    assert loop, "the branding step no longer loops over the clients"
    named = loop.group(1).split()

    declared = set(output_blocks(ROOT_OUTPUTS.read_text()))
    clients = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")
    assert named == ["cognito_user_pool_client_id", "cognito_server_client_id", "cognito_dev_client_id"]
    read = set(re.findall(r"tofu output -raw ([a-z_]+)", branding["run"])) | set(named)
    assert read <= declared, f"the step reads outputs that do not exist: {read - declared}"
    assert len(named) == len(clients), f"{len(clients)} clients exist and {len(named)} are branded"


def test_the_names_root_builds_are_the_names_the_deploy_grant_admits() -> None:
    """A name the grant does not match applies green in the plan and is denied on the first apply."""
    root = ROOT_MAIN.read_text()
    grant = (INFRA / "modules" / "base" / "policies" / "github-actions-deploy-session.json.tftpl").read_text()
    rendered = {"project_name": "dat", "environment": "prod", "aws_region": "us-east-1", "account_id": "111122223333"}

    def resolve(expression: str) -> str:
        for name, value in rendered.items():
            expression = expression.replace("${var." + name + "}", value).replace("${" + name + "}", value)
        return expression.replace("${data.aws_caller_identity.current.account_id}", rendered["account_id"])

    def local(name: str) -> str:
        match = re.search(rf'^\s*{name}\s*=\s*"([^"]+)"', root, re.MULTILINE)
        assert match, f"root no longer builds {name}"
        return resolve(match.group(1))

    table = local("session_table_name")
    parameter = local("client_secret_parameter_name")
    dev_parameter = local("dev_session_parameter_name")
    alias = resolve(re.search(r'key_alias\s*=\s*"([^"]+)"', (INFRA / "modules" / "session-store" / "names.tf").read_text()).group(1))
    patterns = [resolve(p) for p in re.findall(r'"(arn:aws:[^"]+)"', grant)]

    for arn in (
        f"arn:aws:dynamodb:us-east-1:111122223333:table/{table}",
        f"arn:aws:ssm:us-east-1:111122223333:parameter{parameter}",
        f"arn:aws:ssm:us-east-1:111122223333:parameter{dev_parameter}",
        f"arn:aws:kms:us-east-1:111122223333:{alias}",
    ):
        assert any(fnmatch.fnmatchcase(arn, pattern) for pattern in patterns), f"no deploy grant admits {arn}"
