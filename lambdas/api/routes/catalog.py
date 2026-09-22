"""The two Glue reads behind the schema browser, and where Lake Formation does its work.

**Lake Formation grants attach to a PRINCIPAL, and the principal has not changed** — it is the
same portal role, assumed by this function instead of vended to the browser. So every grant keeps
enforcing without being rewritten, and these two routes are where that stops being an argument and
becomes something a live check can observe.

**A denial takes two different shapes and both must survive.** A Glue read the caller has no
``DESCRIBE`` on raises ``AccessDeniedException`` naming Lake Formation, and is a 403 whose body
names nothing. An Athena query the caller has no ``SELECT`` on does not fail the call at all — the
execution reaches FAILED and the reason names Lake Formation, on a 200 status body. An
implementation that maps every LF denial to 403 handles the first and silently converts the second
into an error envelope, losing the authored sentence the browser chooses from that reason.

**A missing database is not an error on the tables route.** A not-yet-created database is an empty
schema browser, never a banner: the query workspace lists a space's tables before anything has
created any. The database route answers 404 for the same absence, because a lookup of one named
thing that is not there has nothing else to say.

**Neither route checks membership or existence itself.** It passes the caller's database name to
Glue and maps what comes back. Whether a foreign database and an absent one are distinguishable is
Lake Formation's property to have, and it is measured live rather than asserted here, where the
fixtures would only prove what they were told.

Attributes:
  ENTITY_NOT_FOUND: What Glue answers for a database that is not there. It means opposite things
    on the two routes — a 404 on the lookup, an empty 200 on the listing — so it is named once
    and each site says which it means.
"""

from typing import Any

from apicommon import identity
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from cpcommon import observability

ENTITY_NOT_FOUND = "EntityNotFoundException"


def _client(context: RequestContext) -> Any:
    """The Glue client for this caller.

    Args:
      context: The authenticated request.

    Returns:
      A Glue client carrying the caller's session tags, which is what Lake Formation reads.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    return identity.user_client("glue", context.acting_as)


def _database(context: RequestContext) -> str:
    """The database this request named.

    Passed to Glue as it arrived. No format check and no membership check, and the create path
    taking the catalog rule does not license one here: that refusal is create-only,
    so a space named before it is still reachable and still answers 200 through this route.
    Applying the rule here would refuse a database the rest of the product accepts, which is the
    one thing this route must not do.

    Args:
      context: The authenticated request.

    Returns:
      The database name from the path.

    Raises:
      None. The matcher refuses an empty segment, so a route that dispatched has one.
    """
    return context.path_params["database"]


def get_database(context: RequestContext) -> dict[str, Any]:
    """Confirms one database exists and is readable.

    Args:
      context: The authenticated request.

    Returns:
      The database's name.

    Raises:
      ApiError: ``NotFound`` when Glue reports no such database.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: A denial or any other Glue failure, for the classifier above — a Lake Formation
        refusal becomes the 403 whose body names nothing.
    """
    database = _database(context)
    observability.stamp(database=database)

    try:
        response = _client(context).get_database(Name=database)
    except Exception as exc:
        if identity.aws_error_code(exc) == ENTITY_NOT_FOUND:
            raise ApiError("NotFound", "no such database") from exc
        raise

    return {"name": str((response.get("Database") or {}).get("Name") or database)}


def list_tables(context: RequestContext) -> dict[str, Any]:
    """Returns one page of a database's tables.

    **One ``GetTables`` call per request.** The continuation walk stays in the browser, where it
    already lives: a server-side walk over a user-controlled collection would satisfy every
    behavioural test here and put an unbounded loop under a 29-second ceiling.

    Args:
      context: The authenticated request, carrying an optional ``nextToken``.

    Returns:
      The tables on this page and the continuation token.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: A denial or any other Glue failure, for the classifier above.
    """
    database = _database(context)
    token = context.query.get("nextToken")
    observability.stamp(database=database)

    request: dict[str, Any] = {"DatabaseName": database}
    if token:
        request["NextToken"] = token

    try:
        response = _client(context).get_tables(**request)
    except Exception as exc:
        if identity.aws_error_code(exc) == ENTITY_NOT_FOUND:
            observability.stamp(table_count=0)
            return {"items": [], "nextToken": None}
        raise

    items = [_table(table) for table in response.get("TableList") or []]
    observability.stamp(table_count=len(items))
    return {"items": items, "nextToken": response.get("NextToken")}


def _table(table: dict[str, Any]) -> dict[str, Any]:
    """Maps one Glue table onto the wire shape.

    Args:
      table: Glue's table object.

    Returns:
      The table's name, columns, type and location.

    Raises:
      None.
    """
    storage = table.get("StorageDescriptor") or {}
    return {
        "name": str(table.get("Name") or ""),
        "columns": [
            {"name": str(column.get("Name") or ""), "type": str(column.get("Type") or "")}
            for column in storage.get("Columns") or []
        ],
        "tableType": table.get("TableType"),
        "location": storage.get("Location"),
    }
