"""The archive key layout, and the inverse that makes a restore robust against a lost record.

**The archived key encodes its own origin.** An object at
``personal/alice/archive/{uuid}/reports/q1.csv`` came from ``alice/reports/q1.csv``, and
``origin_key`` reconstructs that with no lookup at all. That is what lets SPEC-170 rebuild every
destination from one ``ListObjectsV2`` over the archive prefix rather than trusting the receipt
— the receipt is a **report, not a record**, exactly as SPEC-143 judges a table by its shape
rather than by the marker it also writes.

**THE LEADING ``personal/`` / ``shared/`` SEGMENT IS NOT COSMETIC, and this is the module that
would be wrong without it.** Receipts sit in each space's own bucket, where the two namespaces
cannot meet. The archive bucket is the first place they do. Shared-space names are made unique
against the shared-space registry only — **nothing anywhere checks a proposed space name against
the User Pool** — so a user ``alice`` and a space ``alice`` can both exist today. Flat, they
would share one archive prefix; and since SPEC-170 authorizes a restore by SPACE and then reads
whatever sits at that prefix, a member of space ``alice`` could restore user ``alice``'s files
into the shared space. The kind segment is the entire fix and costs nothing else.

The alternative fix — refusing to create a shared space whose name matches an existing username
— is rejected: it changes a shipped, unrelated control plane, it cannot repair names that
already exist, and it would make space creation depend on the User Pool for a reason unrelated
to space creation.

Containment (``assert_inside_root``, ``has_dot_segment``, ``normalize_root``) is **not** here —
it is ``cpcommon.paths``, shared with file-send since SPEC-168, because it is an algorithm and a
second copy of it is a second place a cross-tenant read can be introduced.

Attributes:
  _UUID_V4: The request-id form accepted before any concatenation. **Validated BEFORE the id is
    ever put into an S3 key** (FR-004): the id is browser-supplied and becomes a path segment in
    two buckets, so anything that is not exactly a UUID v4 — a slash, a ``..``, an empty string —
    is refused here rather than normalised into something that resolves.

    **the pasted archive id is held to the SAME pattern, deliberately, and this is the
    one regex either mode may use.** A restore's ``archiveId`` is the more dangerous of the two
    — the user types it, where a request id is minted by the browser — so a second, laxer copy
    of the rule would be a second door into the same key. ``validated_archive_id`` differs from
    ``validated_request_id`` in its refusal's WORDING and in nothing else.
"""

import re

from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root

from .config import ARCHIVE_FOLDER, RECEIPT_NAME, SPACE_KINDS

_UUID_V4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


def validated_request_id(request_id) -> str:
    """Returns the request id, or fails terminally if it is not a well-formed UUID v4.

    Called by every builder below rather than once at the front door, because the front door is
    not the only caller and a helper that trusts its input is a helper that will one day be
    given something else.

    Args:
      request_id: The browser-supplied request id.

    Returns:
      The id, lowercased so one archive has exactly one prefix — S3 keys are case-sensitive, and
      a re-submitted id in different case would silently open a second archive under a name that
      reads identically in every message and every listing.

    Raises:
      TerminalError: ``invalid_request`` when the id is missing or is not a UUID v4.
    """
    if not isinstance(request_id, str) or not _UUID_V4.match(request_id):
        raise TerminalError("invalid_request", f"request id {request_id!r} is not a UUID v4")
    return request_id.lower()


def validated_archive_id(archive_id) -> str:
    """Returns the pasted archive id, or fails terminally if it is not a well-formed UUID v4.

    SPEC-170 FR-002. **The archive id is the only part of a restore request that is both typed
    by a human and used to build an S3 key**, so it is matched against the pattern rather than
    sanitised into one: a value carrying ``/``, ``..``, a percent escape or a trailing space is
    refused as malformed and never normalised, the same discipline SPEC-151 applied to DDL
    literals after a raw interpolation turned out to be the defect.

    It shares ``validated_request_id``'s regex on purpose — one rule, so the id that opened an
    archive and the id that reopens it cannot be judged differently — and differs only in the
    refusal's wording, because "the archive id you pasted" and "this run's id" are different
    things to the person reading the message.

    Args:
      archive_id: The archive id the user pasted from a receipt.

    Returns:
      The id, lowercased, so a receipt read back in upper case still resolves the prefix the
      archive was written under.

    Raises:
      TerminalError: ``invalid_request`` when the id is missing or is not a UUID v4.
    """
    if not isinstance(archive_id, str) or not _UUID_V4.match(archive_id):
        raise TerminalError("invalid_request", f"archive id {archive_id!r} is not a UUID v4")
    return archive_id.lower()


def archive_root(kind: str, name: str, request_id) -> str:
    """Builds the prefix one archive occupies in the ARCHIVE bucket.

    ``{kind}/{name}/archive/{uuid}/`` — the kind segment first, for the namespace reason in this
    module's own docstring.

    Args:
      kind: The source space kind, ``personal`` or ``shared``.
      name: The space's name — a username, or a shared space's name.
      request_id: The browser-supplied request id, which becomes the archive's permanent
        identity.

    Returns:
      The archive prefix, ending in a slash.

    Raises:
      TerminalError: ``invalid_request`` for a bad request id, or ``forbidden`` for an unknown
        kind or an empty name. It fails rather than defaulting to a kind, because guessing wrong
        puts one namespace's data where the other's restore will read it.
    """
    if kind not in SPACE_KINDS:
        raise TerminalError("forbidden", f"unknown source space kind {kind!r}")
    root = normalize_root(name)
    return f"{kind}/{root}{ARCHIVE_FOLDER}/{validated_request_id(request_id)}/"


def receipt_root(name: str, request_id) -> str:
    """Builds the prefix the receipt occupies in the SPACE's own bucket.

    ``{name}/archive/{uuid}/`` — the space's own root, then the archive folder. It carries no
    kind segment and needs none: personal and shared spaces are different buckets, so the two
    cannot collide here. That asymmetry with ``archive_root`` is the whole point of both.

    Args:
      name: The space's name, which is also its root prefix.
      request_id: The browser-supplied request id.

    Returns:
      The receipt prefix, ending in a slash.

    Raises:
      TerminalError: ``invalid_request`` for a bad request id, ``forbidden`` for an empty name.
    """
    return f"{normalize_root(name)}{ARCHIVE_FOLDER}/{validated_request_id(request_id)}/"


def receipt_key(name: str, request_id) -> str:
    """Builds the receipt object's full key in the space's own bucket.

    Args:
      name: The space's name.
      request_id: The browser-supplied request id.

    Returns:
      The receipt's key.

    Raises:
      TerminalError: ``invalid_request`` for a bad request id, ``forbidden`` for an empty name.
    """
    return f"{receipt_root(name, request_id)}{RECEIPT_NAME}"


def archived_key(archive_prefix: str, source_root: str, source_key: str) -> str:
    """Builds the archive-bucket key one source object is copied to.

    The source key keeps everything below its own space root: ``alice/reports/q1.csv`` under
    root ``alice/`` becomes ``{archivePrefix}reports/q1.csv``. **Keeping the origin in the key is
    what makes ``origin_key`` below possible**, and it is why nothing here flattens or renames.

    Args:
      archive_prefix: The archive prefix from ``archive_root``.
      source_root: The authorized source space root.
      source_key: The absolute key of an object inside that root.

    Returns:
      The absolute key in the archive bucket.

    Raises:
      TerminalError: ``forbidden`` when the object does not sit inside the source root. A
        listing cannot normally produce one; it fails rather than slicing the wrong length,
        because a mis-sliced key re-roots the object and its restore would put it back
        somewhere else.
    """
    root = normalize_root(source_root)
    if not source_key.startswith(root):
        raise TerminalError("forbidden", f"{source_key!r} is not inside {root!r}")
    return f"{archive_prefix}{source_key[len(root):]}"


def origin_key(archive_key: str, archive_prefix: str, source_root: str) -> str:
    """Reconstructs where an archived object came from, with no lookup at all.

    The exact inverse of ``archived_key``, and **the reason the receipt is a report rather than
    a record**: SPEC-170 rebuilds every restore destination by listing the archive prefix and
    running each key through this, so a lost, truncated or hand-edited receipt cannot make a
    restore wrong. The manifest exists as a cross-check that can only fire when something is
    already broken.

    Args:
      archive_key: An object's absolute key in the archive bucket.
      archive_prefix: The archive prefix it was listed under.
      source_root: The space root it is being restored into.

    Returns:
      The absolute key in the space's own bucket.

    Raises:
      TerminalError: ``forbidden`` when the key does not sit under the prefix, or when the
        reconstructed remainder is empty. The prefix itself is a legal listing result (a
        zero-byte folder placeholder), and reconstructing it would name the space root — a
        destination that is a whole space rather than an object.
    """
    if not archive_key.startswith(archive_prefix):
        raise TerminalError("forbidden", f"{archive_key!r} is not inside {archive_prefix!r}")
    relative = archive_key[len(archive_prefix) :]
    if not relative:
        raise TerminalError("forbidden", f"{archive_key!r} has no origin below {archive_prefix!r}")
    return f"{normalize_root(source_root)}{relative}"
