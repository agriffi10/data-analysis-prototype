"""The ten handlers that put a request on a control plane's queue.

Each is the same three steps — find the route's declaration, hand the validated body to the sender,
answer with what the sender returned — so they are built from one factory rather than written ten
times. Ten copies of a body-assembling handler is ten places for the identity block, the token
field or a FIFO key to be got wrong, and only one of those failures is loud.

A handler here makes no AWS call of its own, reads no membership and builds no message. Every
authorization question belongs to the plane's own validate-authorize verb, where it is today: the
day one of these checks membership, two authorities exist for one question and they will diverge.

Attributes:
  None.
"""

from collections.abc import Callable
from typing import Any, cast

from apicommon import contract
from apicommon.context import RequestContext
from apicommon.enqueue import enqueue


def _handler_for(route_id: str) -> Callable[[RequestContext], dict[str, Any]]:
    """Builds the handler serving one enqueue route.

    Args:
      route_id: The route's id.

    Returns:
      A handler that sends the request's validated body to that route's queue.

    Raises:
      StopIteration: If no enqueue route carries that id. It fires at import rather than per
        request, so a misspelling is a cold-start failure for every route this function serves
        rather than a 500 on one of them.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == route_id)

    def handler(ctx: RequestContext) -> dict[str, Any]:
        """Sends one request to its queue.

        Args:
          ctx: The request, carrying the verified caller and its validated body.

        Returns:
          The accepted response.

        Raises:
          ApiError: If the message is too large, or the send fails.
        """
        return enqueue(ctx, route, cast("dict[str, Any]", ctx.body or {}))

    handler.__name__ = route_id.replace(".", "_")
    return handler


shared_space = _handler_for("sharedSpace.enqueue")
notifications = _handler_for("notifications.enqueue")
table_build = _handler_for("tableBuild.create")
table_refresh = _handler_for("tableBuild.refresh")
table_share = _handler_for("tableShare.enqueue")
data_quality = _handler_for("dataQuality.enqueue")
file_send = _handler_for("fileSend.enqueue")
archive = _handler_for("archive.archive")
restore = _handler_for("archive.restore")
file_ops = _handler_for("fileOps.enqueue")
