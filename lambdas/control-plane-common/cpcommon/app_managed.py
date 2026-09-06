"""The folders the app manages inside a space, and one builder per fact for the prefix each occupies.

Three of these folders are about to move under a real ``system_settings/`` prefix. Nearly every
rule about them across the fleet is anchored at depth one — ``f"{root}{name}/"`` — so a move to
depth two would leave each hand-written comparison silently not matching, which is the failure
``fscommon.authz`` already names in its own docstring. This module is the fix's precondition: the
names are declared here and nowhere else, every anchored construction calls a builder, and the
move becomes one edit to ``app_managed_prefix`` rather than a hunt across eleven modules. A CI
sweep refuses a new declaration or construction outside this file.

**Nothing here normalizes.** Every builder is a pure string over the arguments it is handed, so
each caller keeps whatever ``normalize_root`` call it already makes and produces exactly the bytes
it produced before — including the API's FIFO group id, which digests one of these prefixes and is
pinned to golden vectors.

**The word ``archive`` names three different facts in this repository**, and exactly one of them
moves. Two are declared here because two packages each need them; the third — the admin bucket's
control-plane scratch prefix, ``arcommon.plan.PREFIX`` — has one consumer and stays in its domain
layer, which owns its constants. A tripwire in ``archive-common`` pins all three equal today, so
the day the receipt folder moves is the day that test asks to be revisited.

Attributes:
  ATHENA_RESULTS_FOLDER: Where Athena writes every query's result set, inside the space's own
    bucket. Visible and browsable; never a write destination. MOVES.
  RECEIPT_FOLDER: **Fact 1 of ``archive``.** The user's receipt folder inside the space's own
    bucket — one folder per archive, named by the request id, holding the receipt the user reads
    an archive id from. Visible on purpose and read-only by IAM. MOVES. Its two siblings are
    ``VAULT_ARCHIVE_SEGMENT`` here and ``arcommon.plan.PREFIX``.
  SHARED_TABLES_FOLDER: Where the table-share pipeline copies tables in, inside the space's own
    bucket. Becomes a shared table's Glue ``LOCATION``. MOVES.
  SPACE_FOLDERS: The three folders above as one tuple — every app-managed folder that lives
    inside a SPACE's own bucket. The enumerator a plane refusing app-managed destinations
    reads, so its refused set is a superset of what this module declares by construction
    rather than by a list it copies.
  SYSTEM_SETTINGS_FOLDER: The prefix the three moving folders are moving INTO. It is not itself
    app-managed content — nothing is written directly under it — but it is reserved on every
    plane and in the browser, so a user can neither paste into it, delete it, nor archive it.
  MOVING_FOLDERS: The folders that gain a second home while both are admitted, declared as its
    own tuple rather than aliased to ``SPACE_FOLDERS`` even though the two hold the same three
    names today. They answer different questions — ``SPACE_FOLDERS`` is every app-managed folder
    in a space's own bucket, this is which of them MOVE — and an alias would silently hand a
    second home to a future space folder that stays where it is.
  VAULT_ARCHIVE_SEGMENT: **Fact 2 of ``archive``.** The segment after the space in every key of
    the ARCHIVE (Glacier vault) bucket — ``{kind}/{name}/archive/{id}/``. It is the same word as
    the receipt folder by design, so a user reading ``archive/{uuid}/`` in their own space sees the
    id their objects sit under, but it addresses a different bucket and does NOT move. Hashed into
    the FIFO group id by the API. Its siblings are ``RECEIPT_FOLDER`` here and ``arcommon.plan.PREFIX``.
"""

ATHENA_RESULTS_FOLDER = "athenaresults"

RECEIPT_FOLDER = "archive"

SHARED_TABLES_FOLDER = "shared_tables"

VAULT_ARCHIVE_SEGMENT = "archive"

SYSTEM_SETTINGS_FOLDER = "system_settings"

SPACE_FOLDERS = (ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER)

MOVING_FOLDERS = (ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER)


def app_managed_prefix(root: str, folder: str) -> str:
    """Builds the prefix an app-managed folder occupies under a space root.

    The one depth-one anchor in the fleet. Every list-driven rule — reserved roots, picker locks,
    undeletable roots — builds its comparison prefixes here, so relocating the moving folders is a
    change to this function and not to the rules.

    Args:
      root: The space root, with its trailing slash, exactly as the caller holds it.
      folder: The folder's name — one of this module's constants, or a member of a domain list.

    Returns:
      ``f"{root}{folder}/"``.

    Raises:
      None.
    """
    return f"{root}{folder}/"


def app_managed_prefixes(root: str, folder: str) -> tuple[str, ...]:
    """Builds every root-anchored location a folder may occupy, depth-one first.

    Two elements for a member of ``MOVING_FOLDERS`` while both homes are admitted, one for any
    other name — so a folder that is not moving never acquires a phantom second home, and a rule
    looping over a mixed list stays uniform.

    **Both elements are LITERALS, and neither is derived from ``app_managed_prefix``.** That is
    the whole point of the duplication: the singular is where a WRITE goes and moves on its own,
    and if the plural were built from it, moving the singular would drag every rule's second home
    to a third location instead of leaving it where the data actually is. The narrowing shrinks
    this to one element inside this function and touches no caller, which is why the return type
    is a variable-length tuple rather than a pair.

    Normalizes nothing, exactly as ``app_managed_prefix`` does not, so a caller keeps whatever
    ``normalize_root`` call it already makes and produces the bytes it produced before.

    Args:
      root: The space root, with its trailing slash, exactly as the caller holds it.
      folder: The folder's name — one of this module's constants, or a member of a domain list.

    Returns:
      ``(f"{root}{folder}/", f"{root}system_settings/{folder}/")`` for a moving folder, else
      ``(f"{root}{folder}/",)``.

    Raises:
      None.
    """
    if folder in MOVING_FOLDERS:
        return (f"{root}{folder}/", f"{root}system_settings/{folder}/")
    return (f"{root}{folder}/",)


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
