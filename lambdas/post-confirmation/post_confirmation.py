"""Cognito post-confirmation trigger (SPEC-033).

When a user finishes signing up, provision their private analytics workspace:

  1. Create a Glue database named EXACTLY as their username (SPEC-033 FR-002). The
     username is already a catalog-safe identifier (the pre-signup Lambda enforces
     ``^[a-z][a-z0-9_]{2,62}$``, SPEC-033 FR-001), so it is used verbatim and
     unsanitised as the database name — it must equal the username for the portal
     role's IAM policy to scope Glue to ``database/${aws:PrincipalTag/username}``
     (SPEC-032 FR-006). That principal-tag scoping is the per-user isolation gate.

  2. Lake Formation ``GrantPermissions`` giving the SHARED portal role full use of
     that database + its tables. This grant does NOT isolate users (every user shares
     the role) — it merely lets the role use the database at all under LF enforcement
     (SPEC-032 removed the IAMAllowedPrincipals "Super" grant). The IAM principal tag
     is still the gate, so the role can only ever touch its own session's database.

Design rules (FR-002):
  - Idempotent: every step tolerates "already exists / already granted".
  - Non-fatal: the handler ALWAYS returns the event, so a transient AWS error never
    blocks sign-up. Failures are logged at ERROR with the username + step so an
    operator can re-run the backfill (backfill.py, FR-004).
  - Only ``PostConfirmation_ConfirmSignUp`` is acted on; password-reset confirmations
    (``PostConfirmation_ConfirmForgotPassword``) are ignored.
  - No tables are created — the database is empty until the user runs DDL (SPEC-034).

The reusable provisioning logic lives in ``provision_user`` so backfill.py can run
the exact same create-database + grant sequence for a pre-existing user (FR-004).
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

glue = boto3.client("glue")
lf = boto3.client("lakeformation")

# The shared portal role the LF grant targets (set in Terraform, FR-003).
PORTAL_ROLE_ARN = os.environ["PORTAL_ROLE_ARN"]

# Database-level permissions: read metadata + define/alter/drop tables, enabling
# CREATE EXTERNAL TABLE and CREATE TABLE AS SELECT (CTAS).
_DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]

# Table-level permissions on ALL tables in the database: read + writes
# (INSERT INTO / CTAS materialisation) + table DDL. Row-level DELETE is NOT granted
# in v1 (SPEC-033 Resolved open question).
_TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]


def _ensure_database(db):
    """Create Glue database ``db`` if absent. Tolerates a concurrent/prior create."""
    try:
        glue.create_database(DatabaseInput={"Name": db})
        logger.info("Created Glue database %s", db)
    except glue.exceptions.AlreadyExistsException:
        logger.info("Glue database %s already exists; skipping create", db)


def _grant_role_full_access(db):
    """Grant the shared portal role full DB + table access on ``db`` via Lake Formation.

    LF ``GrantPermissions`` is idempotent — re-granting an existing permission
    succeeds — so this is safe to re-run (backfill / retries).
    """
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": PORTAL_ROLE_ARN},
        Resource={"Database": {"Name": db}},
        Permissions=_DATABASE_PERMISSIONS,
    )
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": PORTAL_ROLE_ARN},
        Resource={"Table": {"DatabaseName": db, "TableWildcard": {}}},
        Permissions=_TABLE_PERMISSIONS,
    )
    logger.info("Granted portal role %s access on database %s", PORTAL_ROLE_ARN, db)


def provision_user(username):
    """Create the user's Glue database and grant the portal role on it.

    Idempotent. Reused verbatim by backfill.py (FR-004). Raises on a genuine,
    non-"already exists" AWS error so the caller (handler / backfill) decides how to
    react — the Lambda handler swallows it to avoid blocking sign-up; the backfill
    script lets it surface.
    """
    _ensure_database(username)
    _grant_role_full_access(username)


def handler(event, context):
    # Only act on a real sign-up confirmation; ignore forgot-password confirmations.
    if event.get("triggerSource") != "PostConfirmation_ConfirmSignUp":
        return event

    username = event["userName"]  # already catalog-safe (FR-001); == Glue DB name
    try:
        provision_user(username)
    except Exception as exc:  # noqa: BLE001 - never block sign-up on a provisioning error
        # Logged for the operator to re-run backfill.py; sign-up still completes.
        logger.error("Failed to provision user=%s: %s", username, exc)

    return event
