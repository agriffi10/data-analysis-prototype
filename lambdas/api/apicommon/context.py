"""What a handler receives. Not the event, and not the Authorization header.

A handler is given the caller's verified identity and the two facts it needs to log, and has no
way to reach anything the caller said about themselves. That is the whole point of the type: a
handler holding the raw event can read a username from a query string or a body, and a handler
that does so passes every test that supplies a matching token.
"""

from dataclasses import dataclass

from cpcommon.auth import Principal


@dataclass(frozen=True)
class RequestContext:
    """One authenticated request, as a handler sees it.

    Attributes:
      principal: The verified caller. The only source of identity anywhere downstream.
      route: The method and path this request matched, for the log record.
      request_id: The gateway's id for this request, for correlating a refusal with a report.
    """

    principal: Principal
    route: str
    request_id: str
