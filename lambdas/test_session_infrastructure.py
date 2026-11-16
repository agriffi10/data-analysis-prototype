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
  SIGN_IN_SETTINGS: The sign-in settings both clients carry, whitespace and trailing commas removed. A
    scope or flow beyond these widens what a token allows, and `LEGACY` user-existence errors let a
    caller enumerate accounts.
  CLIENT_FLOOR: The number of app clients the IaC declares today. The revocation sweep must find at
    least this many, so a sweep that reads the wrong tree, or a parser that stops recognising a
    header, fails instead of passing over nothing.
"""

import fnmatch
import json
import pathlib
import re

import yaml
from tf_blocks import argument as top_level_argument
from tf_blocks import (
    blocks,
    module_calls,
    output_blocks,
    span,
    strip_comments,
    strip_noise,
)

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
ROOT_MAIN = INFRA / "main.tf"
ROOT_OUTPUTS = INFRA / "outputs.tf"
AUTH = INFRA / "modules" / "auth" / "cognito.tf"
AUTH_OUTPUTS = INFRA / "modules" / "auth" / "outputs.tf"
STORE = INFRA / "modules" / "session-store" / "main.tf"
SPA = INFRA / "modules" / "spa"
DEPLOY_INFRA = INFRA.parent / ".github" / "workflows" / "deploy-infra.yml"

SIGN_IN_SETTINGS = {
    "allowed_oauth_flows_user_pool_client": "true",
    "allowed_oauth_flows": '["code"]',
    "allowed_oauth_scopes": '["openid","email","profile"]',
    "supported_identity_providers": '["COGNITO"]',
    "prevent_user_existence_errors": '"ENABLED"',
    "explicit_auth_flows": '["ALLOW_USER_SRP_AUTH","ALLOW_REFRESH_TOKEN_AUTH"]',
}

CLIENT_FLOOR = 2


def _argument(body: str, name: str) -> str | None:
    """Reads one top-level argument's raw value from a resource body, whitespace collapsed.

    Read with every comment form blanked, so an assignment kept for reference inside a ``/* */``
    comment is not the one found, and a trailing comment is not part of the value.

    Args:
      body: The resource's body.
      name: The argument.

    Returns:
      The value as written, or None when the argument is absent.

    Raises:
      None.
    """
    match = re.search(rf"^\s*{name}\s*=\s*(\[[^\]]*\]|[^\n]+)", strip_comments(body), re.MULTILINE)
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


def _without_urls(body: str) -> str:
    """A client body with its comments, its name and its two URL lists removed, whitespace collapsed.

    The dev client is the server client with a localhost callback, so what is left must be equal.
    Comments go through the shared reader, so a ``//`` or ``/* */`` comment on one client is not a
    difference between them, exactly as a ``#`` one is not.

    Args:
      body: A ``aws_cognito_user_pool_client`` body.

    Returns:
      The remaining settings as one whitespace-collapsed string.

    Raises:
      None.
    """
    code = re.sub(r"^\s*(name|callback_urls|logout_urls)\s*=.*$", "", strip_comments(body), flags=re.MULTILINE)
    return " ".join(code.split())


def _names_localhost(text: str) -> bool:
    """Whether Terraform source names ``localhost`` anywhere but a comment.

    An absence check, so string contents stay searched: a callback URL is a string, and it is the
    thing this looks for. Comments go through the shared reader, so a ``/* */`` comment explaining
    the dev origin is skipped exactly as a ``#`` one is.

    Args:
      text: A Terraform file's source.

    Returns:
      True when ``localhost`` appears outside a comment.

    Raises:
      None.
    """
    return "localhost" in strip_comments(text)


def _rotation_bodies(text: str) -> list[str]:
    """Every ``refresh_token_rotation`` block's body in one Terraform file, braces excluded.

    Located over ``strip_noise`` so a block kept inside a comment, or the name inside a string, is
    not a block, and each body is read to its own closing brace by the shared counter rather than
    to the first ``}``, which a comment or a string inside the block would supply early.

    Args:
      text: A Terraform file's source.

    Returns:
      Each block's body, comments blanked, in file order.

    Raises:
      None.
    """
    code = strip_comments(text)
    return [
        span(code, match.end() - 1)[1:-1]
        for match in re.finditer(r"(?<![\w-])refresh_token_rotation\s*\{", strip_noise(text))
    ]


def _states_grace_period(body: str) -> bool:
    """Whether a rotation block assigns ``retry_grace_period_seconds`` a whole number of seconds.

    Args:
      body: A ``refresh_token_rotation`` body, comments blanked.

    Returns:
      True when the argument is assigned a bare integer on its own line.

    Raises:
      None.
    """
    return bool(re.search(r"^[ \t]*retry_grace_period_seconds[ \t]*=[ \t]*\d+[ \t]*$", body, re.MULTILINE))


def test_the_dev_client_mirrors_the_server_client_and_only_it_names_localhost() -> None:
    """A setting the two clients do not share is a sign-in that works on a laptop and not deployed.

    The dev client is the server client with a localhost callback: a laptop signs in through the same
    routes, so any other difference changes what one client's tokens carry or allow. The public client
    is gone, so localhost is admitted by the dev client alone.
    """
    clients = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")
    assert set(clients) == {"server", "dev"}, f"the clients are {sorted(clients)}"
    server, dev = clients["server"], clients["dev"]

    for setting, expected in SIGN_IN_SETTINGS.items():
        value = _argument(server, setting)
        assert value is not None, f"the server client no longer declares {setting}"
        assert "".join(value.split()).replace(",]", "]") == expected, f"the server client's {setting} is {value}"
    for client in (server, dev):
        assert "read_attributes" not in client and "write_attributes" not in client, (
            "an attribute list that omits a custom:shared_space_k slot drops that claim"
        )
    assert _argument(server, "generate_secret") == "true"
    assert _argument(server, "callback_urls") == '["${var.spa_origin}/auth/callback"]'
    assert _argument(server, "logout_urls") == "[var.spa_origin]"
    assert _argument(server, "enable_token_revocation") == "true"
    assert re.search(r'refresh_token_rotation\s*\{\s*feature\s*=\s*"DISABLED"', strip_comments(server))

    assert _without_urls(dev) == _without_urls(server), "the dev client differs from the server client beyond its URLs"
    assert _argument(dev, "callback_urls") == '["${var.dev_origin}/auth/callback"]'
    assert _argument(dev, "logout_urls") == "[var.dev_origin]"
    assert not _names_localhost(AUTH.read_text()), "the auth module names localhost; only root's dev_origin may"
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
    dynamic = [
        str(path.relative_to(INFRA))
        for path in files
        if re.search(r'dynamic\s+"refresh_token_rotation"', strip_comments(path.read_text()))
    ]
    assert dynamic == [], f"a dynamic refresh_token_rotation block escapes this sweep: {dynamic}"
    rotations = [(path.relative_to(INFRA), body) for path in files for body in _rotation_bodies(path.read_text())]
    assert rotations, "no refresh_token_rotation block found; the sweep reads nothing"
    missing = [str(path) for path, body in rotations if not _states_grace_period(body)]
    assert missing == [], f"refresh_token_rotation without a numeric retry_grace_period_seconds in {missing}"


def test_every_app_client_in_the_tree_turns_token_revocation_on() -> None:
    """A client without revocation applies green and silently loses replay protection.

    Cognito puts a ``jti`` on its tokens only while revocation is on, and Identity Center's replay
    protection was confirmed only on assertions carrying one. ``false`` plans and applies green, and
    an omitted line leaves the client on whatever default it was created with, so the test requires
    the line to say ``true`` rather than trusting either. The sweep covers every ``.tf`` file in
    root and every module rather than a named list, so a client added anywhere is held too.
    """
    json_sources = [str(p.relative_to(INFRA)) for p in INFRA.rglob("*.tf.json") if ".terraform" not in p.parts]
    assert json_sources == [], f"a client in JSON syntax escapes this sweep: {json_sources}"
    files = sorted(path for path in INFRA.rglob("*.tf") if ".terraform" not in path.parts)
    clients: dict[str, str] = {}
    for path in files:
        for name, body in blocks(path.read_text(), "aws_cognito_user_pool_client").items():
            clients[f"{path.relative_to(INFRA)}:{name}"] = body

    assert len(clients) >= CLIENT_FLOOR, (
        f"the sweep found only {sorted(clients)}; the tree, the parser or CLIENT_FLOOR is wrong"
    )

    def revocation(body: str) -> str | None:
        try:
            return "".join(top_level_argument(body, "enable_token_revocation").split())
        except ValueError:
            return None

    read = {client: revocation(body) for client, body in clients.items()}
    off = {client: value for client, value in read.items() if value != "true"}
    assert off == {}, f"clients without enable_token_revocation = true (value read: None is absent): {off}"


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
    assert named == ["cognito_server_client_id", "cognito_dev_client_id"]
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


def test_a_block_comment_is_not_a_difference_between_the_clients() -> None:
    """A ``/* */`` note on one client neither splits it from the other nor hides a real difference.

    The comparison once dropped only ``#`` lines, so a block comment on the dev client reported
    the two clients as different. The reader blanks it, and a setting that really differs, or an
    assignment kept only inside a comment, is still seen.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a comment counts as a setting, or a real difference is missed.
    """
    server = '  name = "server"\n  generate_secret = true\n  callback_urls = ["a"]\n'
    dev = '  name = "dev"\n  /* a laptop signs in here,\n     enable_token_revocation = false */\n  generate_secret = true\n  callback_urls = ["b"]\n'

    assert _without_urls(dev) == _without_urls(server), "a block comment made the clients differ"
    assert _without_urls(dev.replace("generate_secret = true", "generate_secret = false")) != _without_urls(server)
    assert _argument(dev, "enable_token_revocation") is None, "an assignment inside a block comment was read"


def test_localhost_in_a_block_comment_is_not_named_but_in_a_string_is() -> None:
    """The absence check skips a ``/* */`` comment and still reads a string.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a comment trips the check, or a callback URL slips past it.
    """
    assert not _names_localhost("/* dev_origin is http://localhost:5173 */\nx = 1 // localhost\n"), (
        "a comment explaining the dev origin was read as the module naming localhost"
    )
    assert _names_localhost('callback_urls = ["http://localhost:5173/auth/callback"]\n'), (
        "a localhost callback URL inside a string slipped past the absence check"
    )


def test_the_rotation_sweep_reads_each_block_to_its_own_brace_and_skips_comments() -> None:
    """A rotation block kept in a comment is not a block, and a ``}`` in a comment or string does not end one.

    Read with a bare ``refresh_token_rotation {[^}]*}``, a commented-out block without a grace
    period failed the sweep, and a ``}`` inside a comment or an interpolation in a live block cut
    the body before its grace period, failing a client that states one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a commented block is swept, or a live body is cut short or missed.
    """
    text = (
        "/* refresh_token_rotation {\n  feature = \"ENABLED\"\n} */\n"
        "refresh_token_rotation {\n"
        "  feature = \"${local.rotation}\" /* not } yet */\n"
        "  retry_grace_period_seconds = 0\n"
        "}\n"
        'note = "refresh_token_rotation {}"\n'
    )

    bodies = _rotation_bodies(text)

    assert len(bodies) == 1, f"expected the one live block, found {len(bodies)}: {bodies}"
    assert _states_grace_period(bodies[0]), f"the live block was cut short: {bodies[0]!r}"
    assert not _states_grace_period(bodies[0].replace("retry_grace_period_seconds = 0", ""))
