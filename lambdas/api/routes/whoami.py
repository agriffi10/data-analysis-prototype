"""Answers the caller with their own verified username, and nothing else.

**This route is scaffolding.** Until a real surface is ported there is no way to exercise the
auth boundary against the live provider at all, and a boundary nobody has driven end to end is
a boundary nobody has tested. It exists to be driven and then deleted — the spec that ports the
first real route takes it out, together with the identity layer's equivalent probe, and the
condition on both is that the verification pass has actually been run and recorded.

It discloses nothing about anybody else: no lookup, no existence check, no AWS call. The only
name it can return is the one the caller already proved.
"""

from typing import Any

from apicommon.context import RequestContext


def whoami(context: RequestContext) -> dict[str, Any]:
    """Returns the caller's verified username.

    Takes the request context and not the event, so there is nowhere to read a username the
    caller asserted. A handler reading a body would pass every test that sends a matching
    token and fail only against someone who sent a different one deliberately.

    Args:
      context: The authenticated request.

    Returns:
      The response body, for the router to serialize.

    Raises:
      None.
    """
    return {"username": context.principal.username}
