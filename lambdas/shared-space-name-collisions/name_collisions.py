"""name-collisions: the one-shot, read-only report of what already shares a name.

A username and a shared-space name are both the name of a Glue database, and there is one set of
Glue database names. The session's permissions are written against that name, so whoever holds a
name holds a catalog. The create now refuses a user's name and writes no slot until the database
is the space's own, and no app client can write a slot. This reports what was already there before
those doors shut: a user named after a space, a user's database marked as a space's, a slot no
registry record backs, and a user who inherited a database older than their account.

It is not a verb. Nothing enqueues it and it sits on no state machine: CI invokes it directly from
a manual workflow. It runs under the orchestrator role, which can write, so "writes nothing" rests
on this module making only list and get calls, and on the test that records every call.

**A read that fails is never an empty list.** Each list depends on the reads it is computed from,
and a list whose read failed is ``None`` while the read is named in ``failed_reads``, so a fault
can never be reported as a clean account.

Attributes:
  REGISTRY_PREFIX: Where the registry's control objects live in the admin bucket.
  FAILING_LISTS: The lists whose entries fail the run. The others are for information.
  DEPENDS_ON: For each list, the reads it is computed from. The record of a run logs each
    list's count under its key, and ``-1`` for a list a failed read left uncomputed; the names
    themselves stay in the returned report and out of the logs.
"""

import logging

import membership
import registry as reg
import teardown
from cpcommon import clients, observability
from cpcommon import config as cpconfig

import config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")

REGISTRY_PREFIX = "shared-spaces/"

FAILING_LISTS = (
    "usernames_that_are_spaces",
    "user_databases_marked_as_spaces",
    "unbacked_slots",
    "inherited_databases",
)

DEPENDS_ON = {
    "usernames_that_are_spaces": ("registry", "pool", "glue"),
    "refused_reservations_named_for_users": ("registry", "pool", "glue"),
    "user_databases_marked_as_spaces": ("pool", "glue"),
    "unbacked_slots": ("registry", "pool", "glue"),
    "unmarked_space_databases": ("registry", "glue"),
    "orphan_databases": ("registry", "pool", "glue"),
    "inherited_databases": ("pool", "glue"),
    "lake_formation_opt_ins": ("lakeformation",),
}


def _read_registry():
    """Reads every registry record, walking the listing page by page.

    Args:
      None.

    Returns:
      Each record by space name. A listed key whose record has gone by the time it is read is
      left out, as a space deleted mid-walk.

    Raises:
      ClientError: On any S3 fault.
    """
    s3 = clients.s3()
    records = {}
    token = None
    while True:
        kwargs = {"Bucket": cpconfig.ADMIN_BUCKET, "Prefix": REGISTRY_PREFIX}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith(".json"):
                name = key[len(REGISTRY_PREFIX) : -len(".json")]
                record = reg.load(name)
                if record is not None:
                    records[name] = record
        token = page.get("NextContinuationToken")
        if not token:
            return records


def _read_pool():
    """Reads every user in the pool, with their attributes and creation time.

    Args:
      None.

    Returns:
      Each user's ``{"attributes": {...}, "created": datetime}`` by username.

    Raises:
      ClientError: On any Cognito fault.
    """
    cognito = clients.cognito()
    users = {}
    token = None
    while True:
        kwargs = {"UserPoolId": cpconfig.require("COGNITO_USER_POOL_ID")}
        if token is not None:
            kwargs["PaginationToken"] = token
        page = cognito.list_users(**kwargs)
        for user in page.get("Users", []):
            users[user["Username"]] = {
                "attributes": {a["Name"]: a.get("Value", "") for a in user.get("Attributes", [])},
                "created": user.get("UserCreateDate"),
            }
        token = page.get("PaginationToken")
        if not token:
            return users


def _read_glue():
    """Reads every Glue database in the catalog.

    Args:
      None.

    Returns:
      Each database record by name.

    Raises:
      ClientError: On any Glue fault.
    """
    glue = clients.glue()
    databases = {}
    token = None
    while True:
        kwargs = {"NextToken": token} if token is not None else {}
        page = glue.get_databases(**kwargs)
        for database in page.get("DatabaseList", []):
            databases[database["Name"]] = database
        token = page.get("NextToken")
        if not token:
            return databases


def _read_opt_ins():
    """Reads every Lake Formation opt-in in the account.

    An opted-in principal over either bucket is handed credentials by Lake Formation, so a
    colliding catalog grant would reach the data as well as the catalog.

    Args:
      None.

    Returns:
      The opted-in principals' identifiers, sorted and without repeats.

    Raises:
      ClientError: On any Lake Formation fault.
    """
    lf = clients.lf()
    principals = set()
    token = None
    while True:
        kwargs = {"NextToken": token} if token is not None else {}
        page = lf.list_lake_formation_opt_ins(**kwargs)
        for opt_in in page.get("LakeFormationOptInsInfoList", []):
            principal = (opt_in.get("Principal") or {}).get("DataLakePrincipalIdentifier")
            if principal:
                principals.add(principal)
        token = page.get("NextToken")
        if not token:
            return sorted(principals)


def _is_real_space(name, record, databases):
    """Reports whether a registry record is a space someone could reach, not a refused reservation.

    A refused create leaves a ``failed`` record whose roster is its creator, so a roster alone
    proves nothing: a user who wrote a slot naming someone else's database, and then asked for a
    space of that name, would otherwise read as that space's member.

    Args:
      name: The space name.
      record: Its registry record.
      databases: Every Glue database by name.

    Returns:
      True when the space is active, was ever active, or owns the database under its name.

    Raises:
      None.
    """
    if record.get("status") == "active" or record.get("everActive"):
        return True
    database = databases.get(name)
    return database is not None and teardown.carries_marker(database, name)


def _slots(attributes):
    """Lists a user's non-empty membership slots.

    Args:
      attributes: The user's attributes by name.

    Returns:
      ``(slot attribute, value)`` for each non-empty slot, in slot order.

    Raises:
      None.
    """
    found = []
    for k in range(1, config.MAX_SHARED_MEMBERSHIPS + 1):
        slot = f"custom:shared_space_{k}"
        value = attributes.get(slot, "")
        if value:
            found.append((slot, value))
    return found


def _lists(registry, pool, databases, opt_ins):
    """Computes every list from reads that all succeeded.

    Args:
      registry: Every registry record by space name, or None when its read failed.
      pool: Every user by username, or None when its read failed.
      databases: Every Glue database by name, or None when its read failed.
      opt_ins: The opted-in principals, or None when their read failed.

    Returns:
      Each list by its report key; a list whose reads did not all succeed is absent.

    Raises:
      None.
    """
    out = {}
    if opt_ins is not None:
        out["lake_formation_opt_ins"] = opt_ins
    if pool is not None and databases is not None:
        out["user_databases_marked_as_spaces"] = sorted(
            username
            for username in pool
            if username in databases
            and (databases[username].get("Parameters") or {}).get(config.DATABASE_MARKER_KEY)
        )
        out["inherited_databases"] = sorted(
            username
            for username, user in pool.items()
            if username in databases
            and databases[username].get("CreateTime") is not None
            and user["created"] is not None
            and databases[username]["CreateTime"] < user["created"]
        )
    if registry is not None and databases is not None:
        spaces = {name for name, record in registry.items() if _is_real_space(name, record, databases)}
        out["unmarked_space_databases"] = sorted(
            name for name in spaces if name in databases and not teardown.carries_marker(databases[name], name)
        )
    if registry is not None and pool is not None and databases is not None:
        named = set(pool) & set(registry)
        out["usernames_that_are_spaces"] = sorted(named & spaces)
        out["refused_reservations_named_for_users"] = sorted(named - spaces)
        out["orphan_databases"] = sorted(set(databases) - set(registry) - set(pool))
        out["unbacked_slots"] = [
            {"username": username, "slot": slot, "value": value}
            for username, user in sorted(pool.items())
            for slot, value in _slots(user["attributes"])
            if value not in spaces or username not in membership.roster(registry[value])
        ]
    return out


def report():
    """Reads the registry, the pool, the catalog and the opt-ins, and reports every collision.

    Args:
      None.

    Returns:
      The report: each list, ``None`` where a read it depends on failed; ``failed_reads``; and
      ``passed``, true only when every read succeeded and no failing list has an entry.

    Raises:
      None.
    """
    reads = {
        "registry": _read_registry,
        "pool": _read_pool,
        "glue": _read_glue,
        "lakeformation": _read_opt_ins,
    }
    results = {}
    failed = []
    for name, read in reads.items():
        try:
            results[name] = read()
        except Exception:
            logger.exception("name-collision report: the %s read failed", name)
            results[name] = None
            failed.append(name)
    computed = _lists(results["registry"], results["pool"], results["glue"], results["lakeformation"])
    out = {key: computed.get(key) for key in DEPENDS_ON}
    out["failed_reads"] = failed
    out["passed"] = not failed and all(not out[key] for key in FAILING_LISTS)
    observability.info(
        "name collisions reported",
        passed=out["passed"],
        failed_reads=",".join(failed),
        **{key: -1 if out[key] is None else len(out[key]) for key in DEPENDS_ON},
    )
    return out


@observability.traced("name-collisions")
def handler(event, context):
    """Entry point for the one-shot report, invoked directly from CI rather than by the machine.

    An event with no request id is refused before any read, so a stray or empty invocation, such
    as the deploy's cold-start probe, reads nothing.

    Args:
      event: The invocation payload, carrying a request id.
      context: The Lambda context, unused.

    Returns:
      The report from ``report``.

    Raises:
      ValueError: When the event carries no request id.
    """
    if not (event or {}).get("requestId"):
        raise ValueError("the name-collision report runs only with a requestId")
    return report()
