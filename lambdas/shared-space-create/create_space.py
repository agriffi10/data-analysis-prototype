"""create-space verb: provisions a new shared space owned by the actor.

Atomically reserves the globally unique name, assigns the creator a membership slot, creates the
shared prefix marker and Glue database, grants the shared portal role on the database, and
writes the registry, the creator's cache and the creator's membership index. Every step tolerates an already-exists result, so
the verb is replay-safe. Creating is creator-only: it provisions the actor as the sole member
and takes no member list — members are added later.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.

Attributes:
  _GENERIC_REASON: The user-facing clause for an unexpected AWS failure. The raw text is kept in
    the logs and the registry's failed record for operators, and never shown.
  PORTAL_MANAGED_TAG_KEY: The Lake Formation tag key stamped on every shared-space database, so
    the control-plane execution roles get table-creation rights via tag-based access control —
    they are granted on the tag, not per database. It must match the tag Terraform declares.
    Note this is not the dotted table property recording that the portal created a table, which
    grants nothing.
  PORTAL_MANAGED_TAG_VALUE: The tag value.
"""

import logging

import cache
import membership
import membership_index
import registry as reg
from cpcommon import clients, errors, observability
from cpcommon import config as cpconfig
from notify import emit_notification

import config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")

_GENERIC_REASON = "please try again or contact the Administrator"

PORTAL_MANAGED_TAG_KEY = "portal-managed"
PORTAL_MANAGED_TAG_VALUE = "true"


def _user_reason(exc):
    """Chooses the user-facing failure reason for an exception.

    Keeps the deliberate, already-friendly provisioning text such as a taken name or a reached
    limit, and replaces any raw AWS text with a generic clause, so no raw cloud text reaches the
    notification or the cache reason the connections card shows.

    Args:
      exc: The failure.

    Returns:
      The user-facing clause.

    Raises:
      None.
    """
    return str(exc) if isinstance(exc, reg.ProvisioningError) else _GENERIC_REASON


def _ensure_marker(name):
    """Creates the space's prefix marker object. Idempotent.

    Args:
      name: The space name, which is also its prefix.

    Returns:
      None.

    Raises:
      ClientError: On any S3 fault.
    """
    clients.s3().put_object(
        Bucket=cpconfig.SHARED_SPACE_BUCKET,
        Key=f"{name}/DO_NOT_DELETE.txt",
        Body=b"This object marks a shared space. Do not delete.\n",
    )


def _ensure_database(name):
    """Creates the space's Glue database if it is absent.

    A routine Glue transient would otherwise propagate as a bare client error the state machine's
    Retry does not name, permanently failing a create that would very likely have succeeded on
    the next attempt.

    Args:
      name: The space name, which is also its database name.

    Returns:
      None.

    Raises:
      TransientError: On a retryable Glue fault.
      ClientError: On any deterministic Glue fault other than the database already existing.
    """
    glue = clients.glue()
    try:
        glue.create_database(DatabaseInput={"Name": name})
    except glue.exceptions.AlreadyExistsException:
        pass
    except Exception as err:
        errors.raise_if_transient(err, f"glue create_database {name}")
        raise


def _tag_database(name):
    """Attaches the portal-managed Lake Formation tag to the shared database.

    This is what grants the control-plane execution roles table-creation rights, since they are
    granted on the tag rather than per database. Idempotent.

    Args:
      name: The space name, which is also its database name.

    Returns:
      None.

    Raises:
      RuntimeError: When the tagging call reports per-tag failures. The API reports those in a
        list rather than raising, so they are turned into an exception the create path records as
        a terminal failure.
      ClientError: On any other Lake Formation fault.
    """
    resp = clients.lf().add_lf_tags_to_resource(
        Resource={"Database": {"Name": name}},
        LFTags=[{"TagKey": PORTAL_MANAGED_TAG_KEY, "TagValues": [PORTAL_MANAGED_TAG_VALUE]}],
    )
    failures = resp.get("Failures") or []
    if failures:
        raise RuntimeError(f"failed to tag database {name} {PORTAL_MANAGED_TAG_KEY}: {failures}")


def _grant_portal_role(name):
    """Grants the shared portal role full database and table access on the space.

    Idempotent — re-granting an existing permission succeeds. Data-location access on the shared
    bucket is a one-time Terraform grant, not per database.

    Args:
      name: The space name, which is also its database name.

    Returns:
      None.

    Raises:
      ClientError: On any Lake Formation fault.
    """
    lf = clients.lf()
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": config.PORTAL_ROLE_ARN},
        Resource={"Database": {"Name": name}},
        Permissions=config.DATABASE_PERMISSIONS,
    )
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": config.PORTAL_ROLE_ARN},
        Resource={"Table": {"DatabaseName": name, "TableWildcard": {}}},
        Permissions=config.TABLE_PERMISSIONS,
    )


def create_space(name, actor, request_id):
    """Provisions a new shared space owned by the actor, recording any failure durably.

    The reservation is handled outside the provisioning guard on purpose: a name collision must
    not rewrite the registry, because the name belongs to the space's real owner. The actor's own
    cache is theirs to correct — the validator wrote a provisioning entry, so it is marked failed
    or the actor is left with a stuck phantom they cannot clear.

    **The membership index is written after the registry reaches active, and INSIDE the guard.**
    After, because ``reserve`` writes ``provisioning`` and only an active space yields a session
    tag, so an index written mid-create entitles nobody and is immediately wrong. Inside, because
    the alternative leaves an active space whose owner holds no index entry — and once membership
    is sourced from the index, that owner can neither reach the space nor delete it, since delete
    is gated on membership. Inside the guard the ordinary rollback runs and the owner gets a
    failed card they can retry or forget.

    A provisioning failure is recorded in three independent best-effort steps, because a failure
    in one must not skip the others: the membership slot is rolled back so a failed create does
    not leak one toward the actor's cap, the registry records the raw reason, and the cache
    records the friendly one — that cache entry is what the browser reads, so a failed create
    must never silently vanish. The notification is emitted after the terminal status is
    recorded, and never changes the outcome.

    Args:
      name: The requested space name.
      actor: The verified creator.
      request_id: The run's request id.

    Returns:
      The verb result, flagged as a replay when the space was already active.

    Raises:
      ProvisioningError: When the name is taken or the actor has reached their membership limit.
      RuntimeError: When database tagging reports failures, or a CAS is exhausted.
      TransientError: On a retryable Glue fault.
      ClientError: On any other S3, Glue, Lake Formation or Cognito fault.
    """
    try:
        outcome = reg.reserve(name, actor, request_id)
    except Exception as exc:
        reason = str(exc)
        friendly = _user_reason(exc)
        logger.error("create %s reserve failed for %s: %s", name, actor, reason)
        try:
            cache.upsert_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:
            logger.exception("failed to mark reserve-collision failure in cache for %s", name)
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {friendly}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    if outcome == "replay" and (reg.load(name) or {}).get("status") == "active":
        observability.info(
            "create replayed",
            space=name,
            actor=actor,
            store="registry",
            already=True,
            provisioned=False,
        )
        return {"status": "active", "space": name, "owner": actor, "replay": True}
    try:
        membership.assign_or_find_slot(actor, name)
        _ensure_marker(name)
        _ensure_database(name)
        _tag_database(name)
        _grant_portal_role(name)
        created_at = (reg.load(name) or {}).get("createdAt")
        cache.write_owner_projection(actor, name, [actor], [], created_at)
        reg.finalize(name, actor, request_id, "active")
        membership_index.record(actor, name, "active")
    except Exception as exc:
        reason = str(exc)
        friendly = _user_reason(exc)
        logger.error("create %s failed for %s: %s", name, actor, reason)
        try:
            membership.clear_slot(actor, name)
        except Exception:
            logger.exception("failed to roll back membership slot for %s", name)
        try:
            reg.finalize(name, actor, request_id, "failed", reason)
        except Exception:
            logger.exception("failed to record registry failure for %s", name)
        try:
            cache.upsert_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:
            logger.exception("failed to record cache failure for %s", name)
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {friendly}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    emit_notification(
        actor,
        f'Your shared workspace "{name}" is ready.',
        dedup_id=f"{request_id}:create-active:{actor}",
    )
    return {"status": "active", "space": name, "owner": actor}


@observability.traced("create")
def handler(event, context):
    """Step Functions entry point for the create verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    The four stores this verb writes are named in order in the record, because the plane's
    characteristic bug is two of them disagreeing and the characteristic debugging session is
    reconstructing which writes landed.

    Args:
      event: The validated context from the validator, carrying the space, actor and request id.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      ProvisioningError: When the name is taken or the actor is at their membership limit.
      KeyError: When the validated context is missing a required field.
    """
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    result = create_space(space, actor, request_id)
    logger.info("create %s by %s -> %s", space, actor, result["status"])
    observability.info(
        "space created",
        space=space,
        actor=actor,
        status=result["status"],
        replayed=bool(result.get("replay")),
        stores=["registry", "glue", "lakeformation", "cache", "membership-index"],
    )
    return result
