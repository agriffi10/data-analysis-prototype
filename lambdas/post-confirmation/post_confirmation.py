"""Cognito post-confirmation trigger: provisions a confirmed user's analytics workspace.

Three steps. First, create a Glue database named exactly as the username — the pre-signup
trigger has already enforced that it is a catalog-safe identifier, so it is used verbatim, and
it must equal the username for the portal role's IAM policy to scope Glue by the username
principal tag. That principal-tag scoping is the per-user isolation gate.

Second, a Lake Formation grant giving the shared portal role full use of that database and its
tables. This does not isolate users — every user shares the role — it merely lets the role use
the database at all under Lake Formation enforcement. The IAM principal tag is still the gate,
so the role can only ever touch its own session's database.

Third, tag the database so the shared control-plane execution roles get table-creation rights
via tag-based access control: those roles are granted on the tag, not per database, and a table
created in the database inherits the tag. This runs last, so a tagging failure never costs the
user their own portal-role grant — only control-plane access, which the backfill reconciles.

Provisioning is idempotent, every step tolerating an already-exists or already-granted result,
and non-fatal: the handler always returns the event, so a transient AWS error never blocks
sign-up. Only a real sign-up confirmation is acted on; password-reset confirmations are ignored.
No tables are created — the database is empty until the user runs DDL.

The reusable logic lives in ``provision_user`` so the backfill script can run the exact same
sequence for a pre-existing user. The service name is ``auth``, shared with pre-signup, because
one signup touches both triggers.

Attributes:
  PORTAL_ROLE_ARN: The shared portal role the Lake Formation grant targets, set in Terraform.
  PORTAL_MANAGED_TAG_KEY: The Lake Formation tag key stamped on every user database. It must
    match the tag Terraform declares. Note this is not the dotted table property recording that
    the portal created a table, which grants nothing.
  PORTAL_MANAGED_TAG_VALUE: The tag value.
  _DATABASE_PERMISSIONS: Read metadata plus define, alter and drop tables, enabling both
    external-table creation and create-table-as-select.
  _TABLE_PERMISSIONS: Read, writes and table DDL on all tables in the database. Row-level
    delete is deliberately not granted.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from cpcommon import observability

observability.init(service="auth")

glue = boto3.client("glue")
lf = boto3.client("lakeformation")

PORTAL_ROLE_ARN = os.environ["PORTAL_ROLE_ARN"]

PORTAL_MANAGED_TAG_KEY = "portal-managed"
PORTAL_MANAGED_TAG_VALUE = "true"

_DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]

_TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]


def _ensure_database(db):
    """Creates the user's Glue database if it is absent.

    Args:
      db: The database name, which is the username.

    Returns:
      None.

    Raises:
      ClientError: On any Glue fault other than the database already existing, which is
        tolerated so a concurrent or prior create is a no-op.
    """
    try:
        glue.create_database(DatabaseInput={"Name": db})
        logger.info("Created Glue database %s", db)
    except glue.exceptions.AlreadyExistsException:
        logger.info("Glue database %s already exists; skipping create", db)


def _tag_database(db):
    """Attaches the portal-managed Lake Formation tag to the user's database.

    This is what grants the control-plane execution roles table-creation rights, since they are
    granted on the tag rather than per database. Idempotent: re-assigning the same tag value is
    a no-op.

    Args:
      db: The database name.

    Returns:
      None.

    Raises:
      RuntimeError: When the tagging call reports per-tag failures. The API reports those in a
        list rather than raising, so they are turned into an exception and the caller decides
        how to react — the handler swallows it to avoid blocking sign-up, the backfill lets it
        surface.
      ClientError: On any other Lake Formation fault.
    """
    resp = lf.add_lf_tags_to_resource(
        Resource={"Database": {"Name": db}},
        LFTags=[{"TagKey": PORTAL_MANAGED_TAG_KEY, "TagValues": [PORTAL_MANAGED_TAG_VALUE]}],
    )
    failures = resp.get("Failures") or []
    if failures:
        raise RuntimeError(f"failed to tag database {db} {PORTAL_MANAGED_TAG_KEY}: {failures}")
    logger.info("Tagged database %s %s=%s", db, PORTAL_MANAGED_TAG_KEY, PORTAL_MANAGED_TAG_VALUE)


def _grant_role_full_access(db):
    """Grants the shared portal role full database and table access via Lake Formation.

    Granting is idempotent — re-granting an existing permission succeeds — so this is safe to
    re-run from a retry or the backfill.

    Args:
      db: The database name.

    Returns:
      None.

    Raises:
      ClientError: On any Lake Formation fault.
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
    """Creates the user's Glue database, grants the portal role on it, and tags it.

    Idempotent, and reused verbatim by the backfill script.

    Args:
      username: The confirmed username, which is also the database name.

    Returns:
      None.

    Raises:
      RuntimeError: When tagging reports failures.
      ClientError: On a genuine, non-already-exists AWS error, so the caller decides how to
        react — the Lambda handler swallows it to avoid blocking sign-up, the backfill script
        lets it surface.
    """
    _ensure_database(username)
    _grant_role_full_access(username)
    _tag_database(username)


@observability.traced("post-confirmation")
def handler(event, context):
    """Cognito post-confirmation trigger: provisions the confirmed user's Glue database.

    A user who signed up successfully and has no Glue database is the whole reason the backfill
    script exists, and the failure is swallowed on purpose, so it is recorded explicitly —
    without that the only trace would be a CloudWatch line in a log group nobody is watching.

    The username is permitted metadata: it is the Glue database name. The trigger event itself
    is never recorded, because it carries the user's email address.

    Args:
      event: The Cognito trigger event, or the daily keep-warm payload, whose trigger source is
        not a sign-up confirmation and so returns before provisioning.
      context: The Lambda context, unused.

    Returns:
      The event unchanged, which is the trigger contract. Password-reset confirmations return
      immediately without provisioning.

    Raises:
      None. A provisioning failure is recorded rather than raised, so it never blocks sign-up;
      the operator re-runs the backfill to reconcile.
    """
    if event.get("triggerSource") != "PostConfirmation_ConfirmSignUp":
        return event

    username = event["userName"]
    try:
        provision_user(username)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to provision user=%s: %s", username, exc)
        observability.error(
            "provisioning failed; user has no database",
            username=username,
            error_type=type(exc).__name__,
            reason="provisioning-failed",
            remediation="backfill",
        )
        return event

    observability.info("user provisioned", username=username, database=username)
    return event
