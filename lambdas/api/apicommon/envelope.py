"""Serialisation for every response the router emits, success and failure alike.

**A success body is the payload itself; the failure envelope is the only wrapped shape.** That
asymmetry is deliberate: a ``{data: …}`` wrapper adds a level every ported service would have to
strip and buys nothing the status code does not already carry.

**A failure carries a machine code and operator text nobody renders.** The browser owns every
user-facing sentence, resolved from the code. An API that returns a sentence for the browser to
display reverses that quietly, because the sentence looks fine in every screenshot — so ``detail``
is authored at the raise site, in English, for a devtools panel and the log store, and there is no
field here a client is expected to show a user.

**No 204 and no 3xx.** A route producing no data answers 200 with an empty object, so the client
has exactly one parse path and never has to ask whether a body is there.

Attributes:
  JSON_CONTENT_TYPE: The content type every response carries. The charset is explicit because a
    client reading bytes should not have to guess, and every body here is UTF-8.
  NO_STORE: Sent on every response. These are authorized reads, so a cache between the browser and
    the API is a cross-user disclosure — and the failure is silent, because the first user sees
    exactly the right answer.
  LAMBDA_RESPONSE_BYTES: Lambda's 6 MiB synchronous response payload ceiling, which binds before
    API Gateway's 10 MB. It is measured on the proxy response the runtime serializes, not on the
    payload a route returns, and a response over it is an invocation fault the caller sees as a
    bare gateway 5xx — never as an envelope.
"""

import json
from collections.abc import Mapping
from typing import Any

from .contract import ERROR_STATUS

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
NO_STORE = "no-store"
LAMBDA_RESPONSE_BYTES = 6 * 1024 * 1024


class ApiError(Exception):
    """A failure with a defined answer on the wire.

    The one way a handler asks for a status. Raising this is how a route says "refuse the caller
    with this code"; anything else it raises is an unpredicted fault and becomes an InternalError
    naming only the exception type.

    Attributes:
      code: The machine code, which decides the status.
      detail: Optional operator text, authored here rather than derived from an exception.
      params: Optional typed values the client composes its own wording from.
    """

    def __init__(
        self, code: str, detail: str | None = None, params: Mapping[str, Any] | None = None
    ) -> None:
        """Builds the failure.

        Args:
          code: The machine code. Must be one the contract declares.
          detail: Optional operator text. Never a stringified exception.
          params: Optional typed values for the client's own wording. Never a sentence.

        Returns:
          None.

        Raises:
          KeyError: If the code is not one the contract declares, so an undeclared code cannot
            reach the wire even by being raised.
        """
        super().__init__(code)
        self.status = ERROR_STATUS[code]
        self.code = code
        self.detail = detail
        self.params = params


def _headers() -> dict[str, str]:
    """The headers every response carries.

    Args:
      None.

    Returns:
      A fresh header dict, so no caller can mutate a shared one.

    Raises:
      None.
    """
    return {"content-type": JSON_CONTENT_TYPE, "cache-control": NO_STORE}


def success(body: dict[str, Any]) -> dict[str, Any]:
    """Serialises a 200.

    The body is SERIALIZED here rather than handed over as an object. API Gateway infers a
    response only when the function returns JSON and no status; the moment a status is set the
    envelope is read literally and ``body`` must be a string. An object there is a malformed proxy
    response — a 500 the caller sees and no offline assertion does, because a dict body is still
    perfectly serializable.

    Args:
      body: The payload object. Always an object, never a bare array or scalar.

    Returns:
      The payload-format-2.0 response.

    Raises:
      None.
    """
    return {"statusCode": 200, "headers": _headers(), "body": json.dumps(body)}


def served_bytes(body: dict[str, Any]) -> int:
    """How many bytes ``success(body)`` puts on the wire, measured the way the runtime sends it.

    **The payload is serialized twice, and the second pass is not free.** ``success`` renders it
    at ``ensure_ascii=True``, so the envelope's ``body`` is pure ASCII; the runtime's
    ``awslambdaric`` then encodes the whole proxy response again, escaping every quote and
    backslash the first pass wrote. Per stored UTF-8 byte of a string, that is one
    for plain ASCII, three for a newline or tab, four for a quote or backslash and seven for any
    other control character. Non-ASCII text goes out at seven bytes a BMP character and fourteen an
    astral one, so two-byte scripts such as Cyrillic or Greek grow 3.5x, three-byte CJK 2.33x and
    four-byte emoji 3.5x. A stored-size cap cannot know which of those a document is, so a route
    that must fit measures.

    The runtime's own ``ensure_ascii`` follows its bootstrap's ``AWS_EXECUTION_ENV``, and neither
    setting moves this number, because nothing non-ASCII survives the first pass for it to act on.

    Args:
      body: The payload a route is about to return.

    Returns:
      The byte length of the serialized proxy response.

    Raises:
      None.
    """
    return len(json.dumps(success(body), ensure_ascii=False).encode("utf-8"))


def servable(body: dict[str, Any], detail: str) -> dict[str, Any]:
    """Returns a payload whose response fits under Lambda's ceiling, and refuses one that does not.

    A route whose payload grows with what a user stored calls this rather than trusting a cap on
    the stored size, so the caller receives the ``PayloadTooLarge`` the route promises instead of
    a fault the runtime raises after the route has already succeeded.

    The refusal carries no ``limit``: the bound it enforced is on the response, and no stored size
    corresponds to it, so any number sent would name a size the document is not over.

    Args:
      body: The payload a route is about to return.
      detail: Operator text naming what was too large.

    Returns:
      The payload, unchanged.

    Raises:
      ApiError: ``PayloadTooLarge`` when the serialized response would exceed
        ``LAMBDA_RESPONSE_BYTES``.
    """
    if served_bytes(body) > LAMBDA_RESPONSE_BYTES:
        raise ApiError("PayloadTooLarge", detail)
    return body


def failure(
    code: str,
    request_id: str,
    detail: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialises a failure into the one wrapped shape.

    Args:
      code: The machine code, which decides the status.
      request_id: The gateway's id for this request, echoed so a reported failure is findable.
      detail: Optional operator text. Omitted from the body entirely when absent, rather than
        carried as null — an absent key and a null one are the same fact, and one of them is
        a field a client can start reading.
      params: Optional typed values, omitted on the same rule.

    Returns:
      The payload-format-2.0 response.

    Raises:
      KeyError: If the code is not one the contract declares.
    """
    error: dict[str, Any] = {"code": code, "requestId": request_id}
    if detail is not None:
        error["detail"] = detail
    if params:
        error["params"] = dict(params)
    return {
        "statusCode": ERROR_STATUS[code],
        "headers": _headers(),
        "body": json.dumps({"error": error}),
    }
