"""Where a caller's shared-space memberships come from — two sources, one chosen at cold start.

The session tags are built from ten ``custom:shared_space_k`` claims of the verified ID token,
which is what makes "the API stamps byte-identically what the Identity Pool stamped" provable. In
the successor account those claims do not exist under either identity variant, so something else has
to answer *which shared spaces is this caller in* on the credential-minting path. This module is the
seam: two implementations behind one call, resolved once from configuration.

**The resolution is at IMPORT, deliberately, and it is the one place in this package that reads the
environment eagerly.** ``config.py`` resolves everything lazily because a required value read at
import is a cold start that fails where no test and no deploy can see it. Nothing here is required —
an unset variable is the default — so the only import-time failure is a value that is neither of the
two names, and that must be a dead container rather than a running one silently on the other source.
A misconfigured source does not degrade: it produces a working application with the wrong
authorization model, invisible in every response.

**An empty value is an unset one.** An unset repository variable renders as the empty string, which
satisfies a required Terraform variable and overrides a default — this fleet has paid for that once
already. Empty means "nobody configured this", which is what the default is for.

**The interface is slot to space name, not a set of names.** The claims implementation must keep the
Cognito slot index it read, because renumbering would change which tag name carries which value and
that is the byte-equivalence the whole no-policy-was-rewritten argument rests on. The index implementation has no
slots to keep and numbers positionally over the sorted names; the slot index carries no meaning,
because the portal role's three tag-bearing statements each union one entry per slot inside a single
statement. Returning a bare set would have forced the claims source to renumber too.

Attributes:
  SOURCE_CLAIMS: The default, and what every deployed environment runs today.
  SOURCE_INDEX: The membership index in the admin bucket.
  SOURCE_VARIABLE: The environment variable naming the source.
  SOURCE: The resolved name, read once at import.
  REASON_INDEX_UNREADABLE: Recorded when the index cannot be read or does not parse.
  REASON_INDEX_OVER_CAP: Recorded when an index names more spaces than there are slots.
  REASON_INDEX_UNSAFE_NAME: Recorded when a name in the index is not one the catalog rule admits.
    A space name becomes a principal tag VALUE, which the portal role's policy interpolates into a
    resource ARN — so a name of ``*`` is a wildcard grant over every shared space. The name is
    format-checked nowhere server-side when a space is created, which is exactly why it is checked
    here, at the last point before it becomes an entitlement.
  ACTIVE_STATUS: The one space status that yields a tag.
"""

import os
from collections.abc import Mapping

from cpcommon import observability
from cpcommon.auth import Principal
from cpcommon.config import CATALOG_IDENTIFIER_RE

from . import config

SOURCE_CLAIMS = "claims"
SOURCE_INDEX = "index"
SOURCE_VARIABLE = "MEMBERSHIP_SOURCE"

REASON_INDEX_UNREADABLE = "membership_index_unreadable"
REASON_INDEX_OVER_CAP = "membership_index_over_cap"
REASON_INDEX_UNSAFE_NAME = "membership_index_unsafe_space_name"

ACTIVE_STATUS = "active"

SHARED_SPACE_CLAIM = "custom:shared_space_{}"


class MembershipSourceError(RuntimeError):
    """The configured membership source is not one this API implements.

    Raised at import, so the container never starts. Deliberately not a warning and deliberately
    not a fallback: the two sources disagree about what a caller may reach, and a typo resolving
    silently to the default would be invisible in every response the API gives.
    """


def _from_claims(caller: Principal) -> Mapping[int, str]:
    """Reads the occupied membership slots out of a verified claim set.

    Moved here from the identity layer with no change of behaviour, so the tests written against
    it there still describe it.

    A slot whose claim is absent, empty or not a string contributes NOTHING — it is omitted from
    the mapping rather than carried as an empty value. That is load-bearing rather than tidy: an
    empty-valued tag makes a shared-space resource ARN resolve to a bucket followed by a bare
    slash, which is a live grant on every key beginning with one, and S3 permits such a key. An
    unstamped slot, by contrast, matches nothing.

    Args:
      caller: The verified caller, whose whole claim set is read.

    Returns:
      Slot index to space name, holding only the occupied slots.

    Raises:
      ConfigError: If the slot count is unset or unusable.
    """
    occupied: dict[int, str] = {}
    for slot in range(1, config.max_shared_memberships() + 1):
        value = caller.claims.get(SHARED_SPACE_CLAIM.format(slot))
        if isinstance(value, str) and value:
            occupied[slot] = value
    return occupied


def _from_index(caller: Principal) -> Mapping[int, str]:
    """Reads the caller's spaces out of the membership index in the admin bucket.

    **Absence is an answer.** A caller with no index is a member of no space, which is the correct
    and common state for anyone who has never been added to one — and the plane guarantees the
    object exists whenever a membership does, because the write that creates a membership fails the
    run if it cannot write the index.

    **Every other failure fails the request, and no partial tag set is used.** The tempting
    alternative is to stamp what was resolved and continue: it fails closed in the permissions
    sense, which reads as safe, and it is the worst option available. A session missing a tag
    produces ``AccessDenied`` on a space the caller genuinely belongs to — indistinguishable from a
    real refusal, unactionable, and invisible to every gate. The credential-plane guards beside
    this exist because a wrong credential *succeeds*; this is the same defect with the sign
    flipped.

    **The cap counts the names that would become tags.** An index naming more active spaces than
    there are slots fails the request rather than truncating: an eleventh tag matches nothing
    whatever wrote it, so truncating would silently drop an entitlement the plane believes it
    granted. Unreachable while ``assign_or_find_slot`` is live, and reachable the moment the slots
    retire — which is why it is asserted rather than assumed impossible.

    **The username and every space name are checked against the catalog rule before either
    becomes a key or a tag.** The username is checked first, so a name that cannot be represented
    is refused before any call is issued rather than after one — and it reuses the identity layer's
    own reason for that, so the failure mapping's conditions stay distinguishable. A space name is
    checked because it becomes a principal tag *value* the portal role's policy interpolates into a
    resource ARN, and a shared space's name is format-checked nowhere when the space is created:
    a name of ``*`` would be a wildcard grant over every shared space. The claims source cannot
    enforce either without rewriting the equivalence it exists to preserve, so this is a deliberate
    divergence and the one place the spec's "a space name reaching a key builder has been through
    the catalog rule" premise is actually made true.

    **The non-active record fires per request, not once**, and it is bounded by the slot cap rather
    than by anything the caller controls. It is also rare: an index entry is written from a
    committed registry record, so a non-active one means a space changed status without a
    membership change. Naming the difference between "not a member" and "the space is not ready" is
    worth that, because the two are otherwise identical from outside.

    The slot numbers are positional over the sorted names. They carry no meaning: the portal role's
    three tag-bearing statements each union one resource entry or condition value per slot inside a
    single statement, so which index a name lands on changes nothing. Sorting is what keeps the
    numbering stable between requests, and the credential cache is keyed on the whole tag set.

    Args:
      caller: The verified caller.

    Returns:
      Slot index to space name, for the active spaces the index names.

    Raises:
      IdentityUnavailableError: If the username or a space name fails the catalog rule, if the
        index cannot be read or does not parse, or if it names more spaces than there are slots.
        Never a permission denial — that is what a partial mint would tell the caller, and it
        would be untrue.
      ConfigError: If the slot count or the admin bucket is unset.
    """
    from . import identity

    cap = config.max_shared_memberships()
    if not CATALOG_IDENTIFIER_RE.fullmatch(caller.username):
        raise identity.IdentityUnavailableError(identity.REASON_UNREPRESENTABLE_USERNAME)

    document = identity.membership_index_document(caller.username)
    if document is None:
        return {}

    entries = document.get("spaces")
    if not isinstance(entries, list):
        raise identity.IdentityUnavailableError(REASON_INDEX_UNREADABLE)

    names = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise identity.IdentityUnavailableError(REASON_INDEX_UNREADABLE)
        name, status = entry.get("name"), entry.get("status")
        if not isinstance(name, str) or not name:
            raise identity.IdentityUnavailableError(REASON_INDEX_UNREADABLE)
        if not CATALOG_IDENTIFIER_RE.fullmatch(name):
            raise identity.IdentityUnavailableError(REASON_INDEX_UNSAFE_NAME)
        if status != ACTIVE_STATUS:
            observability.info(
                "membership index names a space that is not active",
                username=caller.username,
                space=name,
                space_status=str(status),
            )
            continue
        names.append(name)

    if len(set(names)) > cap:
        raise identity.IdentityUnavailableError(REASON_INDEX_OVER_CAP)
    return dict(enumerate(sorted(set(names)), start=1))


_SOURCES = {SOURCE_CLAIMS: _from_claims, SOURCE_INDEX: _from_index}

SOURCE = os.environ.get(SOURCE_VARIABLE) or SOURCE_CLAIMS

if SOURCE not in _SOURCES:
    raise MembershipSourceError(
        f"{SOURCE_VARIABLE} must be one of {sorted(_SOURCES)}, not {SOURCE!r}"
    )


def resolve(caller: Principal) -> Mapping[int, str]:
    """Returns the caller's shared-space memberships, from whichever source is configured.

    The one call site for both implementations, so nothing downstream — the tag builder, the
    route-level space check, the parity test — can tell them apart.

    Args:
      caller: The verified caller.

    Returns:
      Slot index to space name.

    Raises:
      IdentityUnavailableError: If the index source cannot answer.
      ConfigError: If the layer's configuration is unusable.
    """
    return _SOURCES[SOURCE](caller)
