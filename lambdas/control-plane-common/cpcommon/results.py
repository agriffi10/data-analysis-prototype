"""Where a control plane's Athena statements write their output.

``tbcommon/results.py`` said why this must exist exactly once, and was then copied twice
anyway:

    a results prefix that differed between them is the kind of divergence that only shows up
    as a Lake Formation denial on whichever path is exercised less.

That is the whole risk. The workgroup has one static result location, so every plane routes
its own output per query; the prefix is inside a user's or a space's own tree, which means it
is covered by the same Lake Formation grant as the data — and a prefix built one character
differently is a grant that does not apply, discovered on the least-travelled path.

The three copies were not identical, and the differences are parameters rather than accidents:
the table-builder and table-share prefixes end at the actor and carry a trailing slash, while
data-quality routes a whole request under a fixed ``data-quality`` actor segment and appends
the request id. ``sub`` is that difference.

``user_results_prefix`` is a DIFFERENT fact and is deliberately not merged with the one above:
it is where a USER's own queries write, the prefix the API hands Athena on every start and the
one an execution's output must sit under to be that user's. A plane's DDL writes under a
database root; a user's query writes under their own space root. Two builders because the two
shapes are not the same shape, and one function because the API carried the user rule alone
until a plane needed to read it back.

``owned_results_key`` is the read-back: the proof that an execution is the caller's own, from
the output location Athena recorded for it. Athena authorizes its reads by WORKGROUP, and there
is one, so this prefix is the only execution-to-owner record the deployment has. The API's
query routes and results-conversion's validate-authorize both call it, so the rule has one copy
and a location one accepts is a location the other accepts.
"""

from .app_managed import athena_results_prefix
from .paths import has_dot_segment


def results_location(bucket: str, database: str, actor: str, *, sub: str | None = None) -> str:
    """Builds the Athena results prefix for one actor under one database root.

    Args:
      bucket: The bucket the space lives in.
      database: The space's root segment — its Glue database for a personal or shared space,
        which is also its prefix.
      actor: The verified username the results belong to, or a plane's own fixed segment when
        the output is per request rather than per user.
      sub: A final segment appended without a trailing slash. Its presence is what separates
        the per-request layout from the per-actor one; omitting it ends the prefix at the
        actor, with the trailing slash Athena expects for a folder.

    Returns:
      An ``s3://`` prefix, ending in a slash unless ``sub`` was supplied.

    Raises:
      None.
    """
    base = f"s3://{bucket}/{athena_results_prefix(f'{database}/')}{actor}/"
    return f"{base}{sub}" if sub else base


def user_results_prefix(bucket: str, username: str) -> str:
    """Builds the prefix a user's own Athena queries write their result sets under.

    The API starts every query with this as its output location, so an execution is the
    user's exactly when Athena's recorded output location begins with it. Both the API and
    the plane that checks ownership call this one function; a prefix built one character
    differently on either side is an execution nobody owns.

    Args:
      bucket: The user-space bucket.
      username: The VERIFIED username, never a value from a request body.

    Returns:
      An ``s3://`` prefix ending in a slash.

    Raises:
      None.
    """
    return f"s3://{bucket}/{athena_results_prefix(f'{username}/')}"


def owned_results_key(location: object, bucket: str, username: str) -> str | None:
    """Proves an execution's recorded output location is the user's own, and names its key.

    **The prefix test is a ``startswith``, and that alone is not containment.** A location of
    ``…/athenaresults/../../bob/x.csv`` begins with alice's prefix while naming bob's object, so
    a dot segment in the key refuses it too. Nothing writes such a location today — the API builds
    every one from the verified username — but a rule that holds only while every producer stays
    careful is not a rule.

    Args:
      location: The ``OutputLocation`` Athena reported for the execution, which may be absent or
        not a string.
      bucket: The user-space bucket.
      username: The VERIFIED username, never a value from a request body.

    Returns:
      The result object's key inside the bucket when the location is the user's own, and None
      otherwise, so an unknown execution and someone else's can be answered alike.

    Raises:
      None.
    """
    prefix = user_results_prefix(bucket, username)
    if not isinstance(location, str) or not location.startswith(prefix):
        return None
    key = location[len(f"s3://{bucket}/") :]
    return None if has_dot_segment(key) else key
