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
  STORE_POLICIES: The session-store module's two key-policy templates.
  SPA: The spa module's directory.
  DEPLOY_INFRA: The infrastructure deploy workflow.
  SIGN_IN_SETTINGS: The sign-in settings both clients carry, whitespace and trailing commas removed. A
    scope or flow beyond these widens what a token allows, and `LEGACY` user-existence errors let a
    caller enumerate accounts.
  CLIENT_FLOOR: The number of app clients the IaC declares today. The revocation sweep must find at
    least this many, so a sweep that reads the wrong tree, or a parser that stops recognising a
    header, fails instead of passing over nothing.
  RENDERED: The values root's names are resolved with, as the deployed account has them.
  KEY_ADMINISTRATION: The actions the deployed session key lets the deploy role administer it with.
    None is cryptographic, so none reads a token.
  KEY_METADATA: The reads the deployed session key allows the account root, which a security
    reviewer, AWS Config and a local plan make, and which neither use nor change the key.
"""

import fnmatch
import json
import pathlib
import re

import yaml
from plane_grants import render
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
STORE_POLICIES = INFRA / "modules" / "session-store" / "policies"
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

RENDERED = {
    "project_name": "dat",
    "environment": "prod",
    "aws_region": "us-east-1",
    "account_id": "111122223333",
}

KEY_ADMINISTRATION = {
    "kms:DescribeKey",
    "kms:GetKeyPolicy",
    "kms:PutKeyPolicy",
    "kms:GetKeyRotationStatus",
    "kms:EnableKeyRotation",
    "kms:DisableKeyRotation",
    "kms:EnableKey",
    "kms:DisableKey",
    "kms:UpdateKeyDescription",
    "kms:ListResourceTags",
    "kms:TagResource",
    "kms:UntagResource",
    "kms:ScheduleKeyDeletion",
    "kms:CancelKeyDeletion",
    "kms:CreateAlias",
    "kms:DeleteAlias",
    "kms:UpdateAlias",
}

KEY_METADATA = {
    "kms:DescribeKey",
    "kms:GetKeyPolicy",
    "kms:GetKeyRotationStatus",
    "kms:ListResourceTags",
}


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
    match = re.search(
        rf"^\s*{name}\s*=\s*(\[[^\]]*\]|[^\n]+)", strip_comments(body), re.MULTILINE
    )
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
    block = re.search(
        r"^  session_environment = \{\n(.*?)^  \}$",
        ROOT_MAIN.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    assert block, "root no longer writes session_environment as a block"
    return re.findall(r"^\s{4}([A-Z_]+)\s*=", block.group(1), re.MULTILINE)


def _resolve(expression: str) -> str:
    """Resolves the variables, the caller identity and root locals in one of root's string locals.

    Args:
      expression: The string as root writes it, without its quotes.

    Returns:
      The string as the deployed account renders it.

    Raises:
      AssertionError: If a local it interpolates is not one root writes as a single string.
    """
    for name, value in RENDERED.items():
        expression = expression.replace("${var." + name + "}", value).replace(
            "${" + name + "}", value
        )
    expression = expression.replace(
        "${data.aws_caller_identity.current.account_id}", RENDERED["account_id"]
    )
    return re.sub(
        r"\$\{local\.([a-z_]+)\}", lambda match: _root_local(match.group(1)), expression
    )


def _root_local(name: str) -> str:
    """Reads one of root's single-string locals and resolves it as the deployed account would.

    Args:
      name: The local's name.

    Returns:
      Its resolved value.

    Raises:
      AssertionError: If root no longer builds the local as one string.
    """
    match = re.search(
        rf'^\s*{name}\s*=\s*"([^"]+)"\s*$',
        strip_comments(ROOT_MAIN.read_text()),
        re.MULTILINE,
    )
    assert match, f"root no longer builds {name}"
    return _resolve(match.group(1))


def _deployed_key_policy() -> dict:
    """Renders the deployed session key's policy from its template with root's values.

    Returns:
      The policy document.

    Raises:
      ValueError: If the template interpolates a variable this call does not pass, as
        ``templatefile()`` would refuse it.
    """
    values = {
        "account_id": RENDERED["account_id"],
        "aws_region": RENDERED["aws_region"],
        "table_name": _root_local("session_table_name"),
        "deploy_role_arn": _root_local("deploy_role_arn"),
        "task_role_arn": _root_local("web_task_role_arn"),
    }
    return json.loads(
        render((STORE_POLICIES / "key-named.json.tftpl").read_text(), values),
        object_pairs_hook=_refusing_duplicates,
    )


def _refusing_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Builds a JSON object, refusing a key written twice in it.

    ``json.loads`` keeps the last of two equal keys, so a second ``Condition`` written before the
    one these tests assert would be read as absent while the policy carries it.

    Args:
      pairs: The object's members, in order.

    Returns:
      The object.

    Raises:
      AssertionError: If a key appears twice.
    """
    keys = [key for key, _value in pairs]
    assert len(keys) == len(set(keys)), f"a policy object repeats a key: {keys}"
    return dict(pairs)


def _listed(value: object) -> list[str]:
    """Reads a policy element that may be one string or a list of them.

    Args:
      value: An ``Action``, a principal or a condition value.

    Returns:
      Its strings, as a list.

    Raises:
      None.
    """
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def _effective_principals(statement: dict) -> list[str]:
    """The principals a key-policy statement admits, reading a "*" principal through its condition.

    A ``"*"`` principal bound by ``aws:PrincipalArn`` admits the ARNs the condition names; one not
    bound by it admits everyone, and is returned as ``"*"`` so no set equality can pass over it.

    Args:
      statement: One statement of a key policy.

    Returns:
      The principal ARNs, or ``["*"]``. A principal that is not an ``AWS`` one (a service, a
      federated provider) is returned as its JSON, so it appears in a set equality rather than
      being dropped.

    Raises:
      None.
    """
    principal = statement.get("Principal")
    if isinstance(principal, dict) and set(principal) != {"AWS"}:
        return [json.dumps(principal, sort_keys=True)]
    named = (
        _listed(principal["AWS"]) if isinstance(principal, dict) else _listed(principal)
    )
    if named != ["*"]:
        return named
    bound = (
        statement.get("Condition", {}).get("StringEquals", {}).get("aws:PrincipalArn")
    )
    return _listed(bound) if bound is not None else ["*"]


def test_the_session_store_sits_outside_the_switch_and_reads_nothing_inside_it() -> (
    None
):
    """Switching the tier off must neither schedule the key for deletion nor drop every session."""
    calls = module_calls(ROOT_MAIN.read_text())
    for name in ("session_store", "dev_session_store"):
        call = calls[name]
        assert not re.search(r"^\s*(count|for_each)\s*=", call, re.MULTILINE), (
            f"{name} is on a switch"
        )
        assert "module.network" not in call and "module.spa" not in call, (
            f"{name} reads a module the web tier's switch removes"
        )


def test_the_table_is_under_its_own_key_with_rotation_and_no_backup() -> None:
    """A table on the AWS-owned key, or one with a backup of its refresh tokens, fails later."""
    text = STORE.read_text()
    key = blocks(text, "aws_kms_key")["session"]
    assert _argument(key, "enable_key_rotation") == "true"
    assert _argument(key, "policy") == "local.key_policy", (
        "the key's policy is not the one the module chooses"
    )

    table = blocks(text, "aws_dynamodb_table")["sessions"]
    assert re.search(r"kms_key_arn\s*=\s*aws_kms_key\.session\.arn", table), (
        "not under the session key"
    )
    assert re.search(
        r'ttl\s*\{\s*attribute_name\s*=\s*"expiresAt"\s*enabled\s*=\s*true', table
    )
    assert re.search(r"point_in_time_recovery\s*\{\s*enabled\s*=\s*false", table), (
        "a backup would keep refresh tokens past their sessions"
    )
    assert _argument(table, "deletion_protection_enabled") == "true"


def test_the_deployed_key_names_exactly_the_deploy_role_and_the_task_role() -> None:
    """A key that admits a principal it does not name lets that principal read every refresh token.

    Checkov cannot read a ``templatefile()`` policy, so this is the only check on its principals.
    An action outside the administration and metadata sets counts as cryptographic, so one this
    test does not know is held to the two roles rather than passed over.
    """
    policy = _deployed_key_policy()
    deploy_role = _root_local("deploy_role_arn")
    task_role = _root_local("web_task_role_arn")
    account_root = f"arn:aws:iam::{RENDERED['account_id']}:root"
    statements = policy["Statement"]

    assert [s.get("Sid") for s in statements] == [
        "TheDeployRoleAdministersTheKey",
        "TheDeployRoleUsesTheKeyThroughDynamoDB",
        "TheTaskRoleUsesTheKeyForTheSessionTable",
        "TheTaskRoleDescribesTheKeyThroughDynamoDB",
        "TheAccountReadsTheKeysMetadata",
    ], "the key's policy carries a statement this test does not assert"
    assert [s["Effect"] for s in statements if s["Effect"] != "Allow"] == [], (
        "the key's policy carries a Deny"
    )
    assert not [
        s for s in statements if {"NotAction", "NotPrincipal", "NotResource"} & set(s)
    ]
    granted: dict[str, set[str]] = {}
    for statement in statements:
        actions = set(_listed(statement["Action"]))
        assert not actions & {"kms:*", "*"}, (
            f"{statement.get('Sid')} allows every KMS action"
        )
        for principal in _effective_principals(statement):
            granted.setdefault(principal, set()).update(actions)

    assert set(granted) == {deploy_role, task_role, account_root}, (
        f"the key's policy names {sorted(granted)}"
    )
    cryptographic = {
        p
        for p, actions in granted.items()
        if actions - KEY_ADMINISTRATION - KEY_METADATA
    }
    assert cryptographic == {deploy_role, task_role}, (
        f"principals that can use the key: {cryptographic}"
    )
    assert granted.get(account_root) == KEY_METADATA, (
        f"the account root may {granted.get(account_root)}"
    )
    administration = [
        s for s in statements if s.get("Sid") == "TheDeployRoleAdministersTheKey"
    ]
    assert len(administration) == 1, (
        "the deploy role's administration is not one statement"
    )
    extra = set(_listed(administration[0]["Action"])) ^ KEY_ADMINISTRATION
    assert not extra, (
        f"the administration statement differs from the listed actions by {sorted(extra)}"
    )
    assert (
        _effective_principals(administration[0]) == [deploy_role]
        and "Condition" not in administration[0]
    )
    use = [
        s
        for s in statements
        if s.get("Sid") == "TheDeployRoleUsesTheKeyThroughDynamoDB"
    ]
    assert len(use) == 1 and _effective_principals(use[0]) == [deploy_role]
    assert set(_listed(use[0]["Action"])) == {
        "kms:CreateGrant",
        "kms:DescribeKey",
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey*",
        "kms:ReEncrypt*",
    }
    assert use[0].get("Condition") == {
        "StringEquals": {
            "kms:ViaService": f"dynamodb.{RENDERED['aws_region']}.amazonaws.com"
        }
    }, "the deploy role can use the key, and mint grants on it, outside DynamoDB"


def test_the_task_role_uses_the_deployed_key_for_the_session_table_alone() -> None:
    """Without the table's name, the task role could decrypt through DynamoDB for any table."""
    task_role = _root_local("web_task_role_arn")
    via_dynamodb = {
        "aws:PrincipalArn": task_role,
        "kms:CallerAccount": RENDERED["account_id"],
        "kms:ViaService": f"dynamodb.{RENDERED['aws_region']}.amazonaws.com",
    }
    by_sid = {
        s["Sid"]: s
        for s in _deployed_key_policy()["Statement"]
        if task_role in _effective_principals(s)
    }

    assert set(by_sid) == {
        "TheTaskRoleUsesTheKeyForTheSessionTable",
        "TheTaskRoleDescribesTheKeyThroughDynamoDB",
    }
    use = by_sid["TheTaskRoleUsesTheKeyForTheSessionTable"]
    assert use["Principal"] == {"AWS": "*"}
    assert set(_listed(use["Action"])) == {
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey*",
        "kms:ReEncrypt*",
    }
    assert use["Condition"] == {
        "StringEquals": {
            **via_dynamodb,
            "kms:EncryptionContext:aws:dynamodb:tableName": _root_local(
                "session_table_name"
            ),
        }
    }
    describe = by_sid["TheTaskRoleDescribesTheKeyThroughDynamoDB"]
    assert describe["Principal"] == {"AWS": "*"} and _listed(describe["Action"]) == [
        "kms:DescribeKey"
    ]
    assert describe["Condition"] == {"StringEquals": via_dynamodb}


def test_root_names_the_principals_of_the_deployed_store_and_not_the_dev_store() -> (
    None
):
    """Rendering the two templates alone would pass with the module calls swapped."""
    calls = module_calls(ROOT_MAIN.read_text())
    deployed, dev = (
        strip_comments(calls["session_store"]),
        strip_comments(calls["dev_session_store"]),
    )
    principals = re.search(r"named_principals\s*=\s*\{([^}]*)\}", deployed)
    assert principals, "the deployed store's key does not name its principals"
    assert re.findall(
        r"^\s*(\w+)\s*=\s*(\S+)\s*$", principals.group(1), re.MULTILINE
    ) == [
        ("deploy_role_arn", "local.deploy_role_arn"),
        ("task_role_arn", "local.web_task_role_arn"),
    ]
    assert "named_principals" not in dev, (
        "the dev store's key names principals a developer is not"
    )
    for call, table, alias in (
        (deployed, "local.session_table_name", "local.session_key_alias"),
        (dev, "local.dev_session_table_name", "local.dev_session_key_alias"),
    ):
        assert (
            _argument(call, "table_name") == table
            and _argument(call, "key_alias") == alias
        )

    module = " ".join(strip_comments(STORE.read_text()).split())
    chosen = re.search(
        r'key_policy = \( var\.named_principals == null \? templatefile\("\$\{path\.module\}/policies/([\w.-]+)"'
        r'.*? : templatefile\("\$\{path\.module\}/policies/([\w.-]+)"',
        module,
    )
    assert chosen and chosen.groups() == (
        "key-delegated.json.tftpl",
        "key-named.json.tftpl",
    ), "the module does not pick the named policy exactly when named_principals is set"
    delegated = json.loads(
        render(
            (STORE_POLICIES / "key-delegated.json.tftpl").read_text(),
            {"account_id": "1"},
        )
    )
    assert [(s["Principal"], s["Action"]) for s in delegated["Statement"]] == [
        ({"AWS": "arn:aws:iam::1:root"}, "kms:*")
    ]


def test_the_task_role_arn_root_builds_names_the_role_the_spa_module_creates() -> None:
    """A rename on either side would leave the key naming a role nobody runs as: a session outage."""
    spa_call = module_calls(ROOT_MAIN.read_text())["spa"]
    for name in ("project_name", "environment"):
        assert _argument(spa_call, name) == f"var.{name}", (
            f"the spa module's {name} is not root's"
        )
    names = strip_comments((SPA / "names.tf").read_text())
    role = blocks((SPA / "iam.tf").read_text(), "aws_iam_role")["task"]
    assert _argument(role, "path") is None, (
        "the task role carries a path the constructed ARN omits"
    )

    name = _argument(role, "name").strip('"')
    for local in ("spa_name", "name_prefix"):
        value = re.search(rf'^\s*{local}\s*=\s*"([^"]+)"', names, re.MULTILINE).group(1)
        name = name.replace("${local." + local + "}", value)
    name = _resolve(name)
    assert (
        _root_local("web_task_role_arn")
        == f"arn:aws:iam::{RENDERED['account_id']}:role/{name}"
    )


def test_the_two_keys_carry_descriptions_and_names_built_from_their_alias() -> None:
    """Two keys described alike cannot be told apart in the console or a security review."""
    key = blocks(STORE.read_text(), "aws_kms_key")["session"]
    assert "${var.key_alias}" in _argument(key, "description")
    assert re.search(r'Name\s*=\s*trimprefix\(var\.key_alias,\s*"alias/"\)', key)
    assert _root_local("session_key_alias") != _root_local("dev_session_key_alias")
    assert _root_local("session_table_name") != _root_local("dev_session_table_name")


def test_the_task_role_reads_and_writes_only_the_session_table() -> None:
    """A wider item grant on the task role reaches past the sessions it serves."""
    policy = json.loads(
        render(
            (SPA / "policies" / "task-session-policy.json.tftpl").read_text(),
            {
                "aws_region": RENDERED["aws_region"],
                "account_id": RENDERED["account_id"],
                "session_table_arn": "TABLE_ARN",
                "session_table_name": "TABLE",
            },
        )
    )
    dynamodb = [
        s
        for s in policy["Statement"]
        if any(a.startswith("dynamodb:") for a in _listed(s["Action"]))
    ]
    assert dynamodb == [
        {
            "Sid": "UseTheSessionTable",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
            ],
            "Resource": "TABLE_ARN",
        }
    ]


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
    code = re.sub(
        r"^\s*(name|callback_urls|logout_urls)\s*=.*$",
        "",
        strip_comments(body),
        flags=re.MULTILINE,
    )
    return " ".join(code.split())


def _disables_rotation(body: str) -> bool:
    """Whether a client body turns refresh-token rotation off, read with its comments blanked.

    A ``feature = "DISABLED"`` kept in a comment above a block that says ``ENABLED`` is not the
    client's setting.

    Args:
      body: A ``aws_cognito_user_pool_client`` body.

    Returns:
      True when a live ``refresh_token_rotation`` block opens with ``feature = "DISABLED"``.

    Raises:
      None.
    """
    return (
        re.search(
            r'refresh_token_rotation\s*\{\s*feature\s*=\s*"DISABLED"',
            strip_comments(body),
        )
        is not None
    )


def _has_dynamic_rotation(text: str) -> bool:
    """Whether Terraform source generates a rotation block with ``dynamic``, read with comments blanked.

    A dynamic block has no literal body for the grace-period sweep to read, so it escapes it; one
    mentioned in a comment does not exist.

    Args:
      text: A Terraform file's source.

    Returns:
      True when ``dynamic "refresh_token_rotation"`` appears outside a comment.

    Raises:
      None.
    """
    return (
        re.search(r'dynamic\s+"refresh_token_rotation"', strip_comments(text))
        is not None
    )


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
        for match in re.finditer(
            r"(?<![\w-])refresh_token_rotation\s*\{", strip_noise(text)
        )
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
    return bool(
        re.search(
            r"^[ \t]*retry_grace_period_seconds[ \t]*=[ \t]*\d+[ \t]*$",
            body,
            re.MULTILINE,
        )
    )


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
        assert "".join(value.split()).replace(",]", "]") == expected, (
            f"the server client's {setting} is {value}"
        )
    for client in (server, dev):
        assert "read_attributes" not in client and "write_attributes" not in client, (
            "an attribute list that omits a custom:shared_space_k slot drops that claim"
        )
    assert _argument(server, "generate_secret") == "true"
    assert _argument(server, "callback_urls") == '["${var.spa_origin}/auth/callback"]'
    assert _argument(server, "logout_urls") == "[var.spa_origin]"
    assert _argument(server, "enable_token_revocation") == "true"
    assert _disables_rotation(server), (
        "the server client's refresh-token rotation is not DISABLED"
    )

    assert _without_urls(dev) == _without_urls(server), (
        "the dev client differs from the server client beyond its URLs"
    )
    assert _argument(dev, "callback_urls") == '["${var.dev_origin}/auth/callback"]'
    assert _argument(dev, "logout_urls") == "[var.dev_origin]"
    assert not _names_localhost(AUTH.read_text()), (
        "the auth module names localhost; only root's dev_origin may"
    )
    assert re.search(
        r'^\s*dev_origin\s*=\s*"http://localhost:5173"\s*$',
        ROOT_MAIN.read_text(),
        re.MULTILINE,
    )


def test_every_variable_the_server_requires_is_one_the_infrastructure_renders() -> None:
    """A variable the start check requires and the task does not carry stops every container.

    The portal refuses to start without any session variable, so a name added to the server's list and
    not to the task definition passes every offline gate and takes the deployed portal down.
    """
    config = (
        INFRA.parent / "apps" / "portal" / "src" / "server" / "session" / "config.ts"
    ).read_text()
    listed = re.search(
        r"export const SESSION_VARIABLES = \[(.*?)\] as const;", config, re.DOTALL
    )
    assert listed, (
        "the server no longer lists SESSION_VARIABLES in the form this test reads"
    )
    required = set(re.findall(r"'([A-Z_]+)'", listed.group(1)))
    assert len(required) > 10, f"read only {sorted(required)}"
    optional_list = re.search(
        r"export const OPTIONAL_SESSION_VARIABLES = \[(.*?)\] as const;",
        config,
        re.DOTALL,
    )
    assert optional_list, (
        "the server no longer lists OPTIONAL_SESSION_VARIABLES in the form this test reads"
    )
    optional = set(re.findall(r"'([A-Z_]+)'", optional_list.group(1)))
    assert optional == {"OIDC_USERNAME_CLAIM", "OIDC_IDENTITY_PROVIDER"}, (
        f"the optional list is {sorted(optional)}: moving a variable there stops the server refusing to start "
        "without it, so it is a deliberate edit to this line"
    )
    assert not optional & required, (
        f"optional {sorted(optional)} overlaps the required list"
    )

    rendered = set(_session_environment_keys())
    assert re.search(
        r'name\s*=\s*"OIDC_CLIENT_SECRET"', (SPA / "ecs.tf").read_text()
    ), "the task no longer injects the secret"
    assert required <= rendered | {"OIDC_CLIENT_SECRET"}, (
        f"the server requires {sorted(required - rendered - {'OIDC_CLIENT_SECRET'})} that the task does not carry"
    )
    assert rendered <= required | optional, (
        f"the task carries {sorted(rendered - required - optional)} that the server does not read"
    )


def test_the_server_and_the_api_read_the_username_from_one_claim() -> None:
    """The browser builds prefixes from the server's username and the API attributes requests by its own.

    Two readers of one claim, so one value: a copy in each would let a provider change move one reader
    and leave the other naming a different user — every prefix built from one name and every request
    attributed to another.
    """
    root = ROOT_MAIN.read_text()
    local = re.search(r'^\s*oidc_username_claim\s*=\s*"([^"]+)"', root, re.MULTILINE)
    assert local, "root no longer decides the username claim in one local"
    block = re.search(
        r"^  session_environment = \{\n(.*?)^  \}$", root, re.MULTILINE | re.DOTALL
    )
    assert block, "root no longer writes session_environment as a block"
    assert (
        _argument(block.group(1), "OIDC_USERNAME_CLAIM") == "local.oidc_username_claim"
    ), "the portal server must read the username claim from the local the API reads"
    api_call = re.search(r'^module "api" \{\n(.*?)^\}$', root, re.MULTILINE | re.DOTALL)
    assert api_call, "root no longer calls the api module"
    assert (
        _argument(api_call.group(1), "oidc_username_claim")
        == "local.oidc_username_claim"
    ), "the API must read the username claim from the local the portal server reads"
    assert len(re.findall(r'"cognito:username"', root)) == 1, (
        "the claim is written as a literal more than once"
    )


def test_the_dev_parameter_is_the_task_environment_with_the_dev_client() -> None:
    """A local server rendered from other values than the task's works on a laptop and nowhere else.

    Both sides must be built from the same locals, so a literal on either side fails here: the root
    local that becomes the parameter, and the spa module call that becomes the task definition.
    """
    root = ROOT_MAIN.read_text()
    local = re.search(
        r"^\s*dev_session_environment = merge\((.*?)^\s*\)$",
        root,
        re.MULTILINE | re.DOTALL,
    )
    assert local, "root no longer builds dev_session_environment with merge()"
    body = local.group(1)
    for source in (
        "local.spa_runtime_config",
        "local.csp_connect_src",
        "local.session_environment",
        "local.dev_origin",
    ):
        assert source in body, f"the dev environment is not built from {source}"
    assert re.findall(r'"[^"]*"', body) == ['"CONFIG_${key}"', '"OIDC_CLIENT_ID"'], (
        "the dev environment names a literal value"
    )
    assert re.search(r'"CONFIG_\$\{key\}"', (SPA / "ecs.tf").read_text()), (
        "the task renders CONFIG_ keys some other way"
    )
    overrides = re.findall(
        r"^\s*\{\s*([A-Z_]+)\s*=\s*(local\.\w+)\s*\},?\s*$", body, re.MULTILINE
    )
    assert overrides == [
        ("PORTAL_CSP_CONNECT_SRC", "local.csp_connect_src"),
        ("PORTAL_ORIGIN", "local.dev_origin"),
        ("SESSION_TABLE_NAME", "local.dev_session_table_name"),
    ], "the dev environment overrides a key other than the origin and the session table"
    assert body.index("local.session_environment") < body.index("local.dev_origin"), (
        "the task's values are merged over the dev overrides"
    )
    task_table = re.search(
        r"^\s*SESSION_TABLE_NAME\s*=\s*(\S+)\s*$", root, re.MULTILINE
    )
    assert task_table and task_table.group(1) == "local.session_table_name", (
        "the task does not use the deployed table"
    )

    spa_call = module_calls(root)["spa"]
    for argument, source in (
        ("runtime_config", "local.spa_runtime_config"),
        ("csp_connect_src", "local.csp_connect_src"),
        ("session_environment", "local.session_environment"),
    ):
        assert re.search(
            rf"^\s*{argument}\s*=\s*{re.escape(source)}\s*$", spa_call, re.MULTILINE
        ), f"the task definition's {argument} is not {source}"

    parameter = blocks(AUTH.read_text(), "aws_ssm_parameter")["dev_session_environment"]
    assert _argument(parameter, "type") == '"SecureString"'
    assert (
        " ".join(parameter.split()).count(
            "jsonencode(merge(var.dev_session_environment, {"
        )
        == 1
    )
    added = re.findall(r"^\s*([A-Z_]+)\s*=\s*(\S+)$", parameter, re.MULTILINE)
    assert added == [
        ("OIDC_CLIENT_ID", "aws_cognito_user_pool_client.dev.id"),
        ("OIDC_CLIENT_SECRET", "aws_cognito_user_pool_client.dev.client_secret"),
    ]
    for path in (AUTH_OUTPUTS, ROOT_OUTPUTS):
        assert "dev_session_environment" not in path.read_text(), (
            f"{path.name} exposes the dev parameter"
        )


def test_every_rotation_block_states_its_grace_period() -> None:
    """An omitted grace period plans as null and reads back as AWS's 0, which fails the apply.

    The provider marks ``retry_grace_period_seconds`` optional but not computed, so a client created
    without it exists in AWS while the apply fails as an inconsistent result, leaving everything
    that depends on the client unapplied. The plan is green either way, so only this test sees it.
    """
    files = sorted(INFRA.rglob("*.tf"))
    assert len(files) > 20, (
        f"Swept only {len(files)} .tf files — the glob found the wrong tree."
    )
    dynamic = [
        str(path.relative_to(INFRA))
        for path in files
        if _has_dynamic_rotation(path.read_text())
    ]
    assert dynamic == [], (
        f"a dynamic refresh_token_rotation block escapes this sweep: {dynamic}"
    )
    rotations = [
        (path.relative_to(INFRA), body)
        for path in files
        for body in _rotation_bodies(path.read_text())
    ]
    assert rotations, "no refresh_token_rotation block found; the sweep reads nothing"
    missing = [str(path) for path, body in rotations if not _states_grace_period(body)]
    assert missing == [], (
        f"refresh_token_rotation without a numeric retry_grace_period_seconds in {missing}"
    )


def test_every_app_client_in_the_tree_turns_token_revocation_on() -> None:
    """A client without revocation applies green and silently loses replay protection.

    Cognito puts a ``jti`` on its tokens only while revocation is on, and Identity Center's replay
    protection was confirmed only on assertions carrying one. ``false`` plans and applies green, and
    an omitted line leaves the client on whatever default it was created with, so the test requires
    the line to say ``true`` rather than trusting either. The sweep covers every ``.tf`` file in
    root and every module rather than a named list, so a client added anywhere is held too.
    """
    json_sources = [
        str(p.relative_to(INFRA))
        for p in INFRA.rglob("*.tf.json")
        if ".terraform" not in p.parts
    ]
    assert json_sources == [], (
        f"a client in JSON syntax escapes this sweep: {json_sources}"
    )
    files = sorted(
        path for path in INFRA.rglob("*.tf") if ".terraform" not in path.parts
    )
    clients: dict[str, str] = {}
    for path in files:
        for name, body in blocks(
            path.read_text(), "aws_cognito_user_pool_client"
        ).items():
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
    assert off == {}, (
        f"clients without enable_token_revocation = true (value read: None is absent): {off}"
    )


def test_the_session_ceiling_and_the_refresh_token_come_from_one_local() -> None:
    """A session that outlives its refresh token answers 401 on a cookie the user believes is live."""
    server = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")["server"]
    assert (
        _argument(server, "refresh_token_validity")
        == "local.server_token_validity.refresh_days"
    )
    ceiling = output_blocks(AUTH_OUTPUTS.read_text())["server_session_max_age_seconds"]
    assert "local.server_token_validity.refresh_days * 86400" in ceiling
    assert re.search(
        r"SESSION_MAX_AGE_SECONDS\s*=\s*tostring\(module\.auth\.server_session_max_age_seconds\)",
        ROOT_MAIN.read_text(),
    ), "the server's ceiling is not the client's refresh-token lifetime"


def test_the_secret_reaches_the_task_only_through_ssm_and_the_execution_role() -> None:
    """In the environment it would sit in every task definition revision; in an output, in logs."""
    ecs = (SPA / "ecs.tf").read_text()
    assert re.search(
        r'name\s*=\s*"OIDC_CLIENT_SECRET"\s*valueFrom\s*=\s*var\.client_secret_parameter_arn',
        ecs,
    )

    variables = (SPA / "variables.tf").read_text()
    assert (
        'strcontains(upper(key), "SECRET")' in variables
        and '!startswith(key, "CONFIG_")' in variables
    ), (
        "the session environment's validation no longer refuses a secret or a CONFIG_ key"
    )
    session_keys = _session_environment_keys()
    assert len(session_keys) > 10 and not [
        key for key in session_keys if "SECRET" in key or key.startswith("CONFIG_")
    ]

    execution = json.loads(
        (SPA / "policies" / "task-execution-policy.json.tftpl").read_text()
    )

    def actions(statement: dict[str, object]) -> list[str]:
        named = statement["Action"]
        return [str(a) for a in named] if isinstance(named, list) else [str(named)]

    ssm = [
        s
        for s in execution["Statement"]
        if any(a.lower().startswith("ssm:") for a in actions(s))
    ]
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
        assert "client_secret" not in path.read_text(), (
            f"{path.name} exposes the client secret"
        )


def test_the_deploy_brands_every_app_client() -> None:
    """Managed Login's pages fail to render for a client with no branding style."""
    steps = yaml.safe_load(DEPLOY_INFRA.read_text())["jobs"]["apply"]["steps"]
    branding = next(
        step
        for step in steps
        if step.get("name") == "Ensure Managed Login default branding"
    )
    loop = re.search(r"for OUTPUT in ([^;]+);", branding["run"])
    assert loop, "the branding step no longer loops over the clients"
    named = loop.group(1).split()

    declared = set(output_blocks(ROOT_OUTPUTS.read_text()))
    clients = blocks(AUTH.read_text(), "aws_cognito_user_pool_client")
    assert named == ["cognito_server_client_id", "cognito_dev_client_id"]
    read = set(re.findall(r"tofu output -raw ([a-z_]+)", branding["run"])) | set(named)
    assert read <= declared, (
        f"the step reads outputs that do not exist: {read - declared}"
    )
    assert len(named) == len(clients), (
        f"{len(clients)} clients exist and {len(named)} are branded"
    )


def test_the_names_root_builds_are_the_names_the_deploy_grant_admits() -> None:
    """A name the grant does not match applies green in the plan and is denied on the first apply."""
    grant = (
        INFRA
        / "modules"
        / "base"
        / "policies"
        / "github-actions-deploy-session.json.tftpl"
    ).read_text()
    patterns = [_resolve(p) for p in re.findall(r'"(arn:aws:[^"]+)"', grant)]
    region, account = RENDERED["aws_region"], RENDERED["account_id"]

    for arn in (
        f"arn:aws:dynamodb:{region}:{account}:table/{_root_local('session_table_name')}",
        f"arn:aws:dynamodb:{region}:{account}:table/{_root_local('dev_session_table_name')}",
        f"arn:aws:ssm:{region}:{account}:parameter{_root_local('client_secret_parameter_name')}",
        f"arn:aws:ssm:{region}:{account}:parameter{_root_local('dev_session_parameter_name')}",
        f"arn:aws:kms:{region}:{account}:{_root_local('session_key_alias')}",
        f"arn:aws:kms:{region}:{account}:{_root_local('dev_session_key_alias')}",
    ):
        assert any(fnmatch.fnmatchcase(arn, pattern) for pattern in patterns), (
            f"no deploy grant admits {arn}"
        )


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
    server = '  name = "server"\n  generate_secret = true\n  prevent_user_existence_errors = "ENABLED"\n  callback_urls = ["a"]\n'
    dev = (
        '  name = "dev"\n  /* a laptop signs in here,\n     enable_token_revocation = false */\n'
        '  generate_secret = true\n  prevent_user_existence_errors = "ENABLED"\n  callback_urls = ["b"]\n'
    )

    assert _without_urls(dev) == _without_urls(server), (
        "a block comment made the clients differ"
    )
    assert _without_urls(
        dev.replace("generate_secret = true", "generate_secret = false")
    ) != _without_urls(server), "a differing bare value was not seen"
    assert _without_urls(dev.replace('"ENABLED"', '"LEGACY"')) != _without_urls(
        server
    ), "a difference inside a string was blanked, so the clients compared equal"
    assert _argument(dev, "enable_token_revocation") is None, (
        "an assignment inside a block comment was read"
    )


def test_localhost_in_a_block_comment_is_not_named_but_in_a_string_is() -> None:
    """The absence check skips a ``/* */`` comment and still reads a string.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a comment trips the check, or a callback URL slips past it.
    """
    assert not _names_localhost(
        "/* dev_origin is http://localhost:5173 */\nx = 1 // localhost\n"
    ), "a comment explaining the dev origin was read as the module naming localhost"
    assert _names_localhost(
        'callback_urls = ["http://localhost:5173/auth/callback"]\n'
    ), "a localhost callback URL inside a string slipped past the absence check"


def test_the_rotation_sweep_reads_each_block_to_its_own_brace_and_skips_comments() -> (
    None
):
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
        '/* refresh_token_rotation {\n  feature = "ENABLED"\n} */\n'
        "refresh_token_rotation {\n"
        '  feature = "${local.rotation}" /* not } yet */\n'
        "  retry_grace_period_seconds = 0\n"
        "}\n"
        'note = "refresh_token_rotation {}"\n'
    )

    bodies = _rotation_bodies(text)
    parked = _rotation_bodies(
        "refresh_token_rotation {\n  /*\n  retry_grace_period_seconds = 0\n  */\n}\n"
    )

    assert len(bodies) == 1, (
        f"expected the one live block, found {len(bodies)}: {bodies}"
    )
    assert _states_grace_period(bodies[0]), (
        f"the live block was cut short: {bodies[0]!r}"
    )
    assert not _states_grace_period(
        bodies[0].replace("retry_grace_period_seconds = 0", "")
    )
    assert len(parked) == 1 and not _states_grace_period(parked[0]), (
        f"a grace period inside a block comment counted as stated: {parked!r}"
    )


def test_the_rotation_flags_skip_comments() -> None:
    """A ``DISABLED`` or a ``dynamic`` rotation block kept in a comment is not the file's setting.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a commented block is read as live, or a live one is missed.
    """
    enabled = 'refresh_token_rotation {\n  feature = "ENABLED"\n}\n'
    parked = '# refresh_token_rotation { feature = "DISABLED" }\n/* dynamic "refresh_token_rotation" {} */\n'

    assert not _disables_rotation(parked + enabled), (
        "a commented DISABLED was read as the client's setting"
    )
    assert _disables_rotation(enabled.replace("ENABLED", "DISABLED")), (
        "a live DISABLED block was missed"
    )
    assert not _has_dynamic_rotation(parked + enabled), (
        "a commented dynamic block was read as live"
    )
    assert _has_dynamic_rotation('dynamic "refresh_token_rotation" {\n}\n'), (
        "a live dynamic block was missed"
    )
