"""What a handler receives. Not the event, and not the Authorization header.

A handler is given the caller's verified identity, the two facts it needs to log, and — since the
object routes need it — the request's own **validated** body and query.

**That last part costs a structural guarantee, and pretending otherwise would be worse than
losing it.** This type used to carry no request data at all, which made "a handler cannot read a
username the caller asserted" true by shape: there was nothing to read. Routes taking
``{space, key}`` cannot work that way. So the guarantee is now upheld by two things that are not
the shape — the identity a handler is *given* is still the only one it can act on, since
``acting_as`` is built here from verified claims and no handler may assemble one; and a test
asserts the resolved identity is unchanged against a body and a query each naming a different
user. A handler reading ``context.body["username"]`` is possible, and it is the test and the
sweep over ``routes/`` that stop it, not the type.

Body and query are the VALIDATED values — ``router`` has already checked them against the route's
declaration. A handler that re-parses is a second validator, and the second one is what rots.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cpcommon.auth import Principal

from .identity import UserIdentity


@dataclass(frozen=True)
class Redacted:
    """A value that cannot be rendered, only revealed on purpose.

    The enqueue routes need the caller's raw bearer transitionally — the control planes still
    verify a token out of the message body — which reopens the trap a token-handling service is
    most likely to fall into: a bearer reaching a log record or a stack trace by being interpolated
    into a message somewhere far from here. Every rendering path answers ``<redacted>`` instead, so
    the token can only escape through a deliberate call that a sweep counts.

    The guarantee is over RENDERING, not over reflection: ``dataclasses.asdict``, ``astuple``,
    ``vars`` and pickling all reach the wrapped value, and the sweep counts calls to ``reveal``
    rather than those. Nothing in this function takes any of those paths — the logging layer
    renders an unknown object as a type-name placeholder rather than through ``repr`` — but a
    debug helper that reached for ``asdict`` would not be caught.

    Attributes:
      _value: The wrapped secret. Read it through ``reveal``, never directly.
    """

    _value: str

    def __str__(self) -> str:
        """Renders the placeholder rather than the secret.

        Args:
          None.

        Returns:
          The literal ``<redacted>``.

        Raises:
          None.
        """
        return "<redacted>"

    def __repr__(self) -> str:
        """Renders the placeholder for ``%r`` and for every debugger and traceback.

        Args:
          None.

        Returns:
          The literal ``<redacted>``.

        Raises:
          None.
        """
        return "<redacted>"

    def __format__(self, spec: str) -> str:
        """Renders the placeholder for an f-string, including one carrying a format spec.

        Defined because ``__format__`` does not fall back to ``__str__`` once a spec is present:
        without it, ``f"{bearer:>10}"`` would render the wrapped value with the padding applied.

        Args:
          spec: The format spec, ignored.

        Returns:
          The literal ``<redacted>``.

        Raises:
          None.
        """
        return "<redacted>"


def reveal(secret: Redacted) -> str:
    """Unwraps a redacted value. The only way to read one, and the only call site is the sender.

    Args:
      secret: The wrapped value.

    Returns:
      The wrapped string.

    Raises:
      None.
    """
    return secret._value


@dataclass(frozen=True)
class RequestContext:
    """One authenticated request, as a handler sees it.

    Attributes:
      principal: The verified caller. The only source of identity anywhere downstream.
      acting_as: The AWS identity built from that caller's verified claims — what a handler
        passes to the user-plane door. Handed over rather than built per route, so no handler
        has an opportunity to assemble one from something the caller said about themselves.
      route: The method and path this request matched, for the log record.
      request_id: The gateway's id for this request, for correlating a refusal with a report.
      body: The validated request body, or None for a route declaring none. Never the raw event.
      query: The validated query string, or an empty mapping for a route declaring none.
      path_params: The segments the route's own template named, extracted by the matcher. Every
        value is caller-controlled and none of them is an identity, which is worth restating
        because a path segment reads more like routing than like input.

        **Unlike ``body`` and ``query``, these are NOT validated against a declared type** — a
        route declares no shape for them, so a handler receives whatever survived matching: one
        non-empty segment, of any length, holding any characters the gateway passed through. A
        handler that needs more than that checks it itself. Said plainly because the neighbouring
        two fields arrive checked, and a reader who assumes the third does would be wrong.
      bearer: The caller's raw credential, wrapped so it cannot be rendered. Present because the
        enqueue routes must put a token in the message body until the planes stop verifying one.
        It is transitional: the field, its wrapper and the sweep counting its one reader all go
        when the planes take their identity from the message's identity block instead.
    """

    principal: Principal
    acting_as: UserIdentity
    route: str
    request_id: str
    body: object = None
    query: Mapping[str, str] = MappingProxyType({})
    path_params: Mapping[str, str] = MappingProxyType({})
    bearer: Redacted = Redacted("")
