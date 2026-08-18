"""release-refresh-lock — the counterpart that runs on EVERY terminal path, create included.

It sits before both terminal shaping states, which the create branch shares, so it is invoked on
requests that never took a lock. That is deliberate. The alternative is a ``Choice`` guarding each
insertion point, and a ``Choice`` whose Variable path is ABSENT raises ``States.Runtime`` — which
no Catch anywhere can catch. Passing the whole state and deciding in Python
means nothing ever evaluates a JSONPath against a key that may not be there, so the uncatchable
path cannot be reached at all. A request with no ``lock`` is a no-op.

It never fails a request. A release that cannot be written is logged and the state proceeds: the
lock is recoverable by the staleness steal, and a request that did its work and then reported
failure because of its own bookkeeping would be a strictly worse outcome. This verb therefore
carries NO ``notifies_on_failure`` — there is no user-facing failure it can produce.
"""

import logging

from cpcommon import observability
from tbcommon import table_lock

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


@observability.traced("release-refresh-lock")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: frees the target table's refresh lock, if this request held one.

    Args:
      event: The running request object, which carries ``lock.etag`` only on the refresh path.
      context: The Lambda context, unused.

    Returns:
      A small record of what was done, landed under ``$.released`` by the state's ResultPath so
      the terminal shaping states read the same fields they always did.

    Raises:
      None.
    """
    return _release_refresh_lock(event)


def _release_refresh_lock(event: dict) -> dict:
    """Frees the lock when this request holds one, and reports what it did.

    Every field is read defensively rather than through ``events.require``: this runs on the
    failure path, where the state may be a validate-failure seed carrying null identity, and a
    raise here would replace a recorded failure with an unrecorded one.

    Args:
      event: The running request object.

    Returns:
      ``{"released": bool}`` — False when this request held no lock, which is every create.

    Raises:
      None.
    """
    lock = event.get("lock") or {}
    etag = lock.get("etag")
    if not etag:
        observability.info("no refresh lock to release", held=False)
        return {"released": False}

    space = event.get("space") or {}
    database = space.get("database")
    table = event.get("tableName")
    if not isinstance(database, str) or not isinstance(table, str):
        logger.warning("refresh lock held but the request carries no usable table identity")
        observability.warning("refresh lock stranded", held=True, database=database, table=table)
        return {"released": False}

    table_lock.release(database, table, etag)
    return {"released": True}
