"""The folders the app manages inside a space, and the builders for the prefixes each occupies.

Two of these folders now live under a real ``system_settings/`` prefix, and the move is complete:
the objects were copied across and the old homes emptied and their fences removed. Nearly every
rule about them across the fleet is anchored — ``f"{root}{name}/"`` — so moving them by hand would
have left each comparison silently not matching, which is the failure ``fscommon.authz`` already
names in its own docstring. This module is what made that a single edit instead: the names are
declared here and nowhere else, and every anchored construction calls a builder. A CI sweep
refuses a new declaration or construction outside this file.

**Which builder a caller takes is still the design, and it outlived the move.**
``app_managed_prefix`` is where a WRITE goes. ``app_managed_prefixes`` is what every root-anchored
COMPARISON calls, and it answers for every location a folder may occupy — one, now that each has a
single home. They differed only while both homes were admitted; the plural now delegates.

**Nothing here normalizes.** Every builder is a pure string over the arguments it is handed, so
each caller keeps whatever ``normalize_root`` call it already makes and produces exactly the bytes
it produced before — including the API's FIFO group id, which digests one of these prefixes and is
pinned to golden vectors.

**The word ``archive`` names three different facts in this repository**, and exactly one of them
moved. Two are declared here because two packages each need them; the third — the admin bucket's
control-plane scratch prefix, ``arcommon.plan.PREFIX`` — has one consumer and stays in its domain
layer, which owns its constants. A tripwire in ``archive-common`` pins all three equal, and it
still holds: the receipt folder's PARENT changed, its name did not.

Attributes:
  ATHENA_RESULTS_FOLDER: Where Athena writes every query's result set, inside the space's own
    bucket. Visible and browsable; never a write destination. MOVED.
  RECEIPT_FOLDER: **Fact 1 of ``archive``.** The user's receipt folder inside the space's own
    bucket — one folder per archive, named by the request id, holding the receipt the user reads
    an archive id from. Visible on purpose and read-only by IAM. MOVED. Its two siblings are
    ``VAULT_ARCHIVE_SEGMENT`` here and ``arcommon.plan.PREFIX``.
  SHARED_TABLES_FOLDER: Where the table-share pipeline copies tables in, inside the space's own
    bucket. Becomes a shared table's Glue ``LOCATION``. Does NOT move: the tables in it were sent
    to this space and are the user's to edit, which is the opposite of what the app-managed folder
    means. Its contents carry no Deny on either bucket, deliberately.
  DATA_QUALITY_REPORTS_FOLDER: Where the data-quality plane writes each run's manifest and report,
    and the space's runs index, at the space root. Hidden in the browser. Does NOT move. Declared
    here rather than by the plane because refusals on several planes and in the API guard it, and
    each used to hold its own copy of the name: a rename the writer took would have left every
    one of them refusing a folder nobody writes to, with every test still green.
  SPACE_FOLDERS: The four folders above as one tuple — every app-managed folder this module
    declares inside a SPACE's own bucket. The enumerator a plane refusing app-managed destinations
    reads, so its refused set is a superset of what this module declares by construction
    rather than by a list it copies.
  SYSTEM_SETTINGS_FOLDER: The prefix the two moving folders moved INTO. It is not itself
    app-managed content — nothing is written directly under it — but it is reserved on every
    plane and in the browser, so a user can neither paste into it, delete it, nor archive it.
  MOVING_FOLDERS: The folders that live under ``SYSTEM_SETTINGS_FOLDER``. Declared as its
    own tuple rather than aliased to ``SPACE_FOLDERS``, and the two now differ: ``SPACE_FOLDERS``
    is every app-managed folder in a space's own bucket, this is which of them MOVED.
    ``SHARED_TABLES_FOLDER`` is in the first and NOT the second — a shared table is data someone
    sent this space, and the user may edit it, so filing it under the folder the app manages would
    say the opposite of what is true. It stays at the space root. An alias would have hidden that
    distinction behind an equality that held only by coincidence.
  VAULT_ARCHIVE_SEGMENT: **Fact 2 of ``archive``.** The segment after the space in every key of
    the ARCHIVE (Glacier vault) bucket — ``{kind}/{name}/archive/{id}/``. It is the same word as
    the receipt folder by design, so a user reading ``archive/{uuid}/`` in their own space sees the
    id their objects sit under, but it addresses a different bucket and does NOT move. Hashed into
    the FIFO group id by the API. Its siblings are ``RECEIPT_FOLDER`` here and ``arcommon.plan.PREFIX``.
"""

from collections.abc import Sequence

ATHENA_RESULTS_FOLDER = "athenaresults"

RECEIPT_FOLDER = "archive"

SHARED_TABLES_FOLDER = "shared_tables"

DATA_QUALITY_REPORTS_FOLDER = "_data-quality-reports"

VAULT_ARCHIVE_SEGMENT = "archive"

SYSTEM_SETTINGS_FOLDER = "system_settings"

SPACE_FOLDERS = (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    SHARED_TABLES_FOLDER,
    DATA_QUALITY_REPORTS_FOLDER,
)

MOVING_FOLDERS = (ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER)


def app_managed_prefix(root: str, folder: str) -> str:
    """Builds the prefix an app-managed folder occupies under a space root.

    Where a WRITE goes, and nothing else. **The list-driven rules do NOT build here** — reserved
    roots, picker locks, undeletable roots and every other root-anchored comparison call
    ``app_managed_prefixes``, which now delegates here. The split is kept because the two answer
    different questions — where to write, versus every place to refuse — and a rule that reached
    for the singular would be asserting the first while meaning the second.

    **It branches on ``MOVING_FOLDERS``, and that is not optional.** The
    folder argument comes from a domain list as well as from this module's constants, and
    ``rccommon.paths`` calls this for every member of its protected-destinations tuple — most of
    whose members do not move. Unconditional, that call would build
    ``{root}system_settings/user_settings/``, a prefix nothing is stored under. It would not fail
    loudly either: the same predicate's second leg matches the bare folder name at any depth, so the
    refusal would keep working by accident while its prefix arm quietly stopped matching. The
    ``user_settings`` rows in this module's tests are what hold the branch in place.

    Args:
      root: The space root, with its trailing slash, exactly as the caller holds it.
      folder: The folder's name — one of this module's constants, or a member of a domain list.

    Returns:
      ``f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"`` for a folder that moves, else
      ``f"{root}{folder}/"``.

    Raises:
      None.
    """
    if folder in MOVING_FOLDERS:
        return f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"
    return f"{root}{folder}/"


def app_managed_prefixes(root: str, folder: str) -> tuple[str, ...]:
    """Builds every root-anchored location a folder may occupy.

    One element, for every folder name. The old homes are gone — their objects were copied to
    ``system_settings/`` and the sources deleted — so there is no second location left for any
    name, and a depth-one ``{root}archive/`` is an ordinary user path.

    **It delegates to ``app_managed_prefix`` rather than repeating its literal.** While both homes
    were admitted the duplication earned its place: the singular is where a WRITE goes and moved on
    its own, so deriving the plural from it would have dragged every rule's second home to a third
    location instead of leaving it where the data still was. With one home that argument is spent,
    and two literals a few characters apart is a rule written twice — the shape where one copy
    drifts and nothing notices.

    The function survives the shrink instead of being folded into its caller because every
    root-anchored COMPARISON in the fleet loops over it. Keeping it is what made the narrowing an
    edit here and in no rule module, which is why the return type was a variable-length tuple from
    the start.

    Normalizes nothing, exactly as ``app_managed_prefix`` does not, so a caller keeps whatever
    ``normalize_root`` call it already makes and produces the bytes it produced before.

    Args:
      root: The space root, with its trailing slash, exactly as the caller holds it.
      folder: The folder's name — one of this module's constants, or a member of a domain list.

    Returns:
      A one-element tuple holding ``app_managed_prefix(root, folder)``.

    Raises:
      None.
    """
    return (app_managed_prefix(root, folder),)


def athena_results_prefix(root: str) -> str:
    """Builds the Athena results folder's prefix under a space root.

    Args:
      root: The space root, with its trailing slash.

    Returns:
      The results folder's prefix, trailing slash.

    Raises:
      None.
    """
    return app_managed_prefix(root, ATHENA_RESULTS_FOLDER)


def receipt_folder_prefix(root: str) -> str:
    """Builds the archive receipt folder's prefix under a space root — fact 1 of ``archive``.

    Args:
      root: The space root, with its trailing slash.

    Returns:
      The receipt folder's prefix, trailing slash.

    Raises:
      None.
    """
    return app_managed_prefix(root, RECEIPT_FOLDER)


def shared_tables_prefix(root: str) -> str:
    """Builds the shared-tables folder's prefix under a space root.

    Args:
      root: The space root, with its trailing slash.

    Returns:
      The shared-tables folder's prefix, trailing slash.

    Raises:
      None.
    """
    return app_managed_prefix(root, SHARED_TABLES_FOLDER)


def vault_archive_prefix(kind: str, root: str, archive_id: str) -> str:
    """Builds the prefix one archive occupies in the ARCHIVE bucket — fact 2 of ``archive``.

    Shared by the archive plane, which writes under it, and the API, which digests it into the
    FIFO group id of a restore request. Two spellings of one key were how they could drift apart.

    Args:
      kind: The source space kind, ``personal`` or ``shared``.
      root: The space's root, with its trailing slash, exactly as the caller holds it.
      archive_id: The archive's id, already validated where validation is the caller's job.

    Returns:
      ``f"{kind}/{root}archive/{archive_id}/"``.

    Raises:
      None.
    """
    return f"{kind}/{root}{VAULT_ARCHIVE_SEGMENT}/{archive_id}/"


def app_managed_segments(folder: str) -> tuple[str, ...]:
    """Builds the path segments an app-managed folder occupies, for an any-depth scan.

    The companion to ``app_managed_prefixes`` for the rules that are NOT root-anchored. The shared
    bucket's Denies put a wildcard where the space name goes, and an S3 resource wildcard matches
    ``/`` as well, so ``{bucket}/*/system_settings/archive/*`` reaches that folder at any depth
    below a space root. A rule mirroring one of those Denies has to scan segments rather than
    compare a prefix, and this is what it scans FOR.

    **It returns a PAIR for a folder that moved, and that is the whole reason it exists.** Until
    the move, every such mirror looked for the bare folder name, because the Deny was anchored one
    segment deep. Three of them did — in the browser, in ``focommon`` and in the API — each a
    hand-written copy that no builder fed, so each kept refusing at the old depth after the Deny
    narrowed. A folder a user calls ``archive`` inside a shared space is now ordinary, and a rule
    still keyed on the bare name refuses a write IAM permits.

    Args:
      folder: The folder's name — one of this module's constants, or a member of a domain list.

    Returns:
      ``(SYSTEM_SETTINGS_FOLDER, folder)`` for a folder that moved, else ``(folder,)``.

    Raises:
      None.
    """
    if folder in MOVING_FOLDERS:
        return (SYSTEM_SETTINGS_FOLDER, folder)
    return (folder,)


def segments_hold_app_managed(segments: Sequence[str], folder: str) -> bool:
    """Reports whether a key's segments contain an app-managed folder at any depth.

    The scan the shared bucket's wildcard Denies require, in one place rather than in each mirror.
    Consecutiveness is the point: ``system_settings/x/archive/`` is not the app's folder, and a
    membership test over the two names separately would say it is.

    The caller decides which segments to hand over — a file key's last segment is its FILE NAME
    and is dropped, because a file *called* ``archive`` is not a file *inside* one, and no Deny
    whose Resource ends ``/archive/*`` matches it.

    Args:
      segments: The key's segments below the space root, already trimmed by the caller.
      folder: The folder's name.

    Returns:
      True when the folder's segments appear consecutively.

    Raises:
      None.
    """
    wanted = app_managed_segments(folder)
    width = len(wanted)
    return any(
        tuple(segments[at : at + width]) == wanted for at in range(len(segments) - width + 1)
    )
