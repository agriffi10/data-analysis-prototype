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
