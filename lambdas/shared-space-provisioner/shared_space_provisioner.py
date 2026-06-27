"""Shared-space provisioner.

The Step Function invokes this Lambda with a shared-space request (one SQS record).
Every request is first VALIDATEd (SPEC-056): verify the caller's Cognito ID token,
derive the trusted actor, authorize against the registry. Then the per-action verb
runs. SPEC-051 implements **create**; add_members/remove_members/leave/delete remain
stubs (SPEC-053/054).

Trusted-actor binding (SPEC-056): the request body carries the caller's Cognito ID
token (`idToken`). We verify it against the pool JWKS and derive the trusted ``actor``
from ``cognito:username`` — the body ``actor`` is advisory. A forged/unauthorized
request raises before any verb runs, so the Step Function's Catch routes it to Fail
with no side effects.

create (SPEC-051): validate the name is globally unique (atomic conditional registry
write) and the creator has a free membership slot, then create the shared prefix +
Glue database, grant the shared portal role on the DB (mirrors SPEC-033), assign the
creator a ``custom:shared_space_k`` slot, and write the registry + the creator's
per-user cache. Every step tolerates "already exists" so a replayed request (same
requestId) doesn't double-provision; a mid-way failure records a terminal ``failed``
status (registry + the creator's cache) with a reason — never a half-provisioned
state without a record.
"""

import json
import logging
import os
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset({"create", "add_members", "remove_members", "leave", "delete"})

# Set by Terraform (lambda.tf). AWS_REGION is provided by the Lambda runtime.
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
SHARED_SPACE_BUCKET = os.environ.get("SHARED_SPACE_BUCKET", "")
USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
PORTAL_ROLE_ARN = os.environ.get("PORTAL_ROLE_ARN", "")
MAX_SHARED_MEMBERSHIPS = int(os.environ.get("MAX_SHARED_MEMBERSHIPS", "10"))
REGION = os.environ.get("AWS_REGION", "")

_ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
_JWKS_URL = f"{_ISSUER}/.well-known/jwks.json"

# LF permissions granted to the SHARED portal role per shared DB — identical to the
# personal-DB grant (SPEC-033 post_confirmation): per-user isolation is the IAM
# membership tag, not this grant; LF just lets the role use the DB under enforcement.
_DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]
_TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]

# Lazily-initialised, cached across warm invocations. Module-level so tests patch them.
_jwk_client = None
_s3 = None
_glue = None
_lf = None
_cognito = None


class AuthorizationError(Exception):
    """Untrusted/unauthorized request — Catch -> Fail, never retried, no side effects."""


class ProvisioningError(Exception):
    """A create step failed (e.g. name taken, slot full). Recorded as a terminal
    ``failed`` registry/cache status with the reason, then re-raised -> Fail."""


def _s3c():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def _gluec():
    global _glue
    if _glue is None:
        import boto3

        _glue = boto3.client("glue")
    return _glue


def _lfc():
    global _lf
    if _lf is None:
        import boto3

        _lf = boto3.client("lakeformation")
    return _lf


def _cognitoc():
    global _cognito
    if _cognito is None:
        import boto3

        _cognito = boto3.client("cognito-idp")
    return _cognito


# ── Validate / actor binding (SPEC-056) ──────────────────────────────────────
def _get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        from jwt import PyJWKClient

        _jwk_client = PyJWKClient(_JWKS_URL)
    return _jwk_client


def verified_username(id_token):
    """Verify a Cognito ID token and return the trusted ``cognito:username``."""
    import jwt

    if not id_token:
        raise AuthorizationError("missing idToken")
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APP_CLIENT_ID,
            issuer=_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as exc:  # noqa: BLE001 - any verify failure = untrusted
        raise AuthorizationError(f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise AuthorizationError("not an ID token")
    username = claims.get("cognito:username")
    if not username:
        raise AuthorizationError("token missing cognito:username")
    return username


def load_registry(space):
    """Return the registry record for ``space`` (dict) or None if it doesn't exist."""
    s3 = _s3c()
    try:
        obj = s3.get_object(Bucket=ADMIN_BUCKET, Key=f"shared-spaces/{space}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def authorize(action, space, actor, registry):
    """Authorize ``actor`` for ``action`` on ``space``. Pure; raises on violation."""
    if action not in VALID_ACTIONS:
        raise AuthorizationError(f"unknown action: {action!r}")
    if action == "create":
        return
    if registry is None:
        raise AuthorizationError(f"space {space!r} does not exist")
    owner = registry.get("owner")
    members = registry.get("members", [])
    if action in OWNER_ONLY_ACTIONS:
        if actor != owner:
            raise AuthorizationError(f"{action} on {space!r} is owner-only")
        return
    if action == "leave":
        if actor == owner:
            raise AuthorizationError("owner cannot leave their own space (delete it instead)")
        if actor not in members:
            raise AuthorizationError(f"{actor!r} is not a member of {space!r}")
        return


# ── create verb (SPEC-051) ───────────────────────────────────────────────────
def _registry_key(name):
    return f"shared-spaces/{name}.json"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _reserve_registry(name, actor, request_id):
    """Atomically create the registry object (status=provisioning) to claim the
    globally-unique name. Returns 'created', or 'replay' if this exact request
    already created it (idempotent re-run). Raises ProvisioningError on a genuine
    name collision (a different request already owns the name)."""
    s3 = _s3c()
    record = {
        "version": 1,
        "name": name,
        "owner": actor,
        "members": [actor],
        "status": "provisioning",
        "createdAt": _now_iso(),
        "lastRequestId": request_id,
    }
    try:
        s3.put_object(
            Bucket=ADMIN_BUCKET,
            Key=_registry_key(name),
            Body=json.dumps(record).encode(),
            ContentType="application/json",
            IfNoneMatch="*",  # atomic create-if-absent -> global name uniqueness
        )
        return "created"
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in ("PreconditionFailed", "412"):
            raise
        existing = load_registry(name) or {}
        if existing.get("lastRequestId") == request_id and existing.get("owner") == actor:
            return "replay"
        raise ProvisioningError("name already taken") from exc


def _slot_attr(k):
    return f"custom:shared_space_{k}"


def _assign_or_find_slot(username, name):
    """Return the slot index holding ``name`` for ``username`` (idempotent re-run),
    else assign ``name`` to the next free slot and return it. Raises
    ProvisioningError if the user already holds MAX_SHARED_MEMBERSHIPS spaces."""
    cognito = _cognitoc()
    user = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=username)
    attrs = {a["Name"]: a.get("Value", "") for a in user.get("UserAttributes", [])}
    free = None
    for k in range(1, MAX_SHARED_MEMBERSHIPS + 1):
        value = attrs.get(_slot_attr(k), "")
        if value == name:
            return k  # already assigned (replay-safe)
        if not value and free is None:
            free = k
    if free is None:
        raise ProvisioningError("membership limit reached")
    cognito.admin_update_user_attributes(
        UserPoolId=USER_POOL_ID,
        Username=username,
        UserAttributes=[{"Name": _slot_attr(free), "Value": name}],
    )
    return free


def _ensure_marker(name):
    """Create the space's DO_NOT_DELETE.txt marker (mirrors SPEC-014). Idempotent."""
    _s3c().put_object(
        Bucket=SHARED_SPACE_BUCKET,
        Key=f"{name}/DO_NOT_DELETE.txt",
        Body=b"This object marks a shared space. Do not delete.\n",
    )


def _ensure_database(name):
    glue = _gluec()
    try:
        glue.create_database(DatabaseInput={"Name": name})
    except glue.exceptions.AlreadyExistsException:
        pass


def _grant_portal_role(name):
    """Grant the shared portal role full DB + table access on ``name`` (idempotent —
    LF GrantPermissions re-grants safely). DATA_LOCATION_ACCESS on the shared bucket
    is a one-time Terraform grant (shared-spaces/lakeformation.tf), not per-DB."""
    lf = _lfc()
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": PORTAL_ROLE_ARN},
        Resource={"Database": {"Name": name}},
        Permissions=_DATABASE_PERMISSIONS,
    )
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": PORTAL_ROLE_ARN},
        Resource={"Table": {"DatabaseName": name, "TableWildcard": {}}},
        Permissions=_TABLE_PERMISSIONS,
    )


def _cache_key(username):
    return f"{username}/user_settings/shared-connections.json"


def _upsert_cache_entry(username, entry):
    """Read-modify-write the user's shared-connections cache, upserting ``entry`` by
    name. The privileged orchestrator role may write any user's prefix (SPEC-056)."""
    s3 = _s3c()
    try:
        obj = s3.get_object(Bucket=USER_SPACE_BUCKET, Key=_cache_key(username))
        cache = json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        cache = {"version": 1, "connections": []}
    connections = [c for c in cache.get("connections", []) if c.get("name") != entry["name"]]
    connections.append(entry)
    cache = {"version": 1, "connections": connections}
    s3.put_object(
        Bucket=USER_SPACE_BUCKET,
        Key=_cache_key(username),
        Body=json.dumps(cache).encode(),
        ContentType="application/json",
    )


def _finalize_registry(name, actor, request_id, status, reason=None):
    record = {
        "version": 1,
        "name": name,
        "owner": actor,
        "members": [actor],
        "status": status,
        "lastRequestId": request_id,
        "updatedAt": _now_iso(),
    }
    if reason:
        record["reason"] = reason
    _s3c().put_object(
        Bucket=ADMIN_BUCKET,
        Key=_registry_key(name),
        Body=json.dumps(record).encode(),
        ContentType="application/json",
    )


def create_space(name, actor, request_id):
    """Provision a new shared space owned by ``actor``. Idempotent; records a terminal
    failed status (registry + the owner's cache) on any error before re-raising."""
    outcome = _reserve_registry(name, actor, request_id)  # may raise "name already taken"
    if outcome == "replay" and (load_registry(name) or {}).get("status") == "active":
        return {"status": "active", "space": name, "owner": actor, "replay": True}
    try:
        _assign_or_find_slot(actor, name)  # may raise "membership limit reached"
        _ensure_marker(name)
        _ensure_database(name)
        _grant_portal_role(name)
        _upsert_cache_entry(actor, {"name": name, "role": "owner", "status": "active"})
        _finalize_registry(name, actor, request_id, "active")
    except Exception as exc:  # noqa: BLE001 - record failure, don't leave it dangling
        reason = str(exc)
        logger.error("create %s failed for %s: %s", name, actor, reason)
        try:
            _finalize_registry(name, actor, request_id, "failed", reason)
            _upsert_cache_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": reason}
            )
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record failure for %s", name)
        raise
    return {"status": "active", "space": name, "owner": actor}


def _extract_record(event):
    if isinstance(event, list):
        if not event:
            raise AuthorizationError("empty event")
        return event[0]
    if isinstance(event, dict):
        return event
    raise AuthorizationError("unrecognised event shape")


def _parse_request(record):
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise AuthorizationError("missing message body")
    try:
        req = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise AuthorizationError(f"body is not valid JSON: {exc}") from exc
    if req.get("schemaVersion") != SCHEMA_VERSION:
        raise AuthorizationError(f"unsupported schemaVersion: {req.get('schemaVersion')!r}")
    return req


def handler(event, context):
    record = _extract_record(event)
    req = _parse_request(record)
    action = req.get("action")
    space = req.get("space")

    # 1) Trusted-actor binding (verified token, not the body).
    actor = verified_username(req.get("idToken"))

    # 2) Authorize against the registry (raises -> Fail, no verb runs).
    registry = None if action == "create" else load_registry(space)
    authorize(action, space, actor, registry)

    # 3) Per-action verb.
    if action == "create":
        result = create_space(space, actor, req.get("requestId"))
        logger.info("create %s by %s -> %s", space, actor, result["status"])
        return result

    # add_members / remove_members / leave / delete — stubs (SPEC-053/054).
    logger.info("authorized %s on %s by %s (verb stubbed)", action, space, actor)
    return {"status": "authorized", "action": action, "space": space, "actor": actor}
