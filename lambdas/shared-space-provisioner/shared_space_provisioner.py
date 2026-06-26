"""Shared-space provisioner (SPEC-056: validate + actor binding; verbs still stubs).

The Step Function invokes this Lambda with the shared-space request (one SQS record,
batch size 1). SPEC-050 made the control plane observable; SPEC-056 adds the REAL
**validate** phase — trusted-actor binding + registry authorization — while the
per-action verbs (create / add_members / remove_members / leave / delete) remain
stubs until SPEC-051-055.

Trusted-actor binding (FR-005, user decision): the request body carries the caller's
Cognito **ID token** (`idToken`). We verify its signature against the User Pool's
JWKS and derive the trusted ``actor`` from the verified ``cognito:username`` claim —
the body's own ``actor`` field is advisory and never trusted. The browser can only
``sqs:SendMessage`` (SPEC-056 FR-002); it cannot forge identity because it cannot
mint a token signed by Cognito.

Authorization (FR-005) is then checked against the S3 control-object **registry**
(``shared-spaces/{space}.json`` in the admin bucket): owner-only actions require
``registry.owner == actor``; ``leave`` requires membership. A forged token or an
unauthorized request raises ``AuthorizationError`` BEFORE any verb runs, so the Step
Function's Catch routes it to the Fail state with no side effects.

Request body contract (FR-004), schemaVersion-guarded:
    { "schemaVersion": 1, "requestId": "uuid", "action": "...",
      "actor": "alice" (advisory), "space": "salesdata", "payload": {...},
      "idToken": "<cognito id token>" }
"""

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset({"create", "add_members", "remove_members", "leave", "delete"})

# Set by Terraform (lambda.tf). AWS_REGION is provided by the Lambda runtime.
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "")

_ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
_JWKS_URL = f"{_ISSUER}/.well-known/jwks.json"

# Lazily-initialised JWKS client, cached across warm invocations.
_jwk_client = None


class AuthorizationError(Exception):
    """Raised when a request can't be trusted/authorized. Caught by the Step
    Function (States.ALL) and routed to Fail — never retried, no side effects."""


def _get_jwk_client():
    # Imported lazily (like boto3) so the authorization logic + handler flow stay
    # unit-testable without PyJWT installed; CI bundles it from requirements.txt.
    global _jwk_client
    if _jwk_client is None:
        from jwt import PyJWKClient

        _jwk_client = PyJWKClient(_JWKS_URL)
    return _jwk_client


def verified_username(id_token):
    """Verify a Cognito ID token and return the trusted ``cognito:username``.

    Verifies the RS256 signature against the pool JWKS and the standard claims
    (issuer, audience = the SPA app client, expiry, ``token_use == "id"``). Any
    failure raises AuthorizationError — the request is treated as forged.
    """
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
    """Return the registry record for ``space`` (dict) or None if it doesn't exist.

    Reads ``shared-spaces/{space}.json`` from the admin bucket. boto3 is imported
    lazily so the authorization logic stays unit-testable without AWS.
    """
    import boto3

    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=ADMIN_BUCKET, Key=f"shared-spaces/{space}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def authorize(action, space, actor, registry):
    """Authorize ``actor`` for ``action`` on ``space`` against the registry.

    Pure function (no I/O) — the security core, unit-tested directly. Raises
    AuthorizationError on any violation; returns None when allowed.

      - create:        any authenticated actor (name uniqueness is SPEC-051's
                       atomic conditional PutObject, not an authorization concern).
      - add/remove/delete (owner-only): the space must exist and actor == owner.
      - leave:         the space must exist and actor is a member but not the owner.
    """
    if action not in VALID_ACTIONS:
        raise AuthorizationError(f"unknown action: {action!r}")

    if action == "create":
        return  # any verified user may request a new space

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


def _extract_record(event):
    """Normalise the Pipe payload (a list of SQS records, batch size 1) to one record."""
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

    # 1) Trusted-actor binding: derive the actor from the verified token, NOT the body.
    actor = verified_username(req.get("idToken"))

    # 2) Authorize against the registry (raises AuthorizationError -> Fail, no verb runs).
    registry = None if action == "create" else load_registry(space)
    authorize(action, space, actor, registry)

    # 3) Dispatch to the per-action verb. STUB until SPEC-051-055 — provisions nothing.
    logger.info(
        "authorized request: action=%s space=%s actor=%s requestId=%s (verb stubbed)",
        action, space, actor, req.get("requestId"),
    )
    return {"status": "authorized", "action": action, "space": space, "actor": actor}
