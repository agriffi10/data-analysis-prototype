"""The numbers a person reads about an archive, apart from the ones the machinery verifies.

**The plane carries folder placeholders and must keep carrying them**: the portal's New folder
writes a zero-byte key ending in ``/``, and an archived empty folder has to come back. So every
object count the copy, the commit gate and the vault checks compare — ``objectCount``, the plan,
the manifest's item count — counts placeholders, and must. What a person reads must not: one file
inside a New-folder folder is one file, and a sentence saying "2 files" describes something the
user cannot see.

**THE RULE: a placeholder counts toward a number a person reads only when it is the thing that
fell short.** On success the number is the files. On a shortfall the sentence reads "done of
total", and ``shown`` returns ``done = files - files short`` beside ``total = files + folders
short``. The difference between them is every item that fell short, whichever kind it was, so a
sentence can never read "only 1 of 1 file(s) could be copied" over a run that stopped because a
folder did not copy. The one exception is an export that accounts for MORE items than the
manifest listed, a wiring fault the collector marks incomplete with nothing attributable to it:
there ``done`` equals ``total``, where the object counts it replaced read "3 of 2".

**Where the count rides, and why not as a field of its own.** The manifest builders count the
files in the same pass that flags each line, and put the count in the ``transfer`` block every
later state already carries. A new top-level field read by an ASL ``Parameters`` path would be an
uncatchable ``States.Runtime`` whenever the machine's definition reached production before the
verb that writes the field — and the two deploy in parallel, while ``NotifyArchived`` runs after
the source has been deleted. ``$.transfer`` is on the state under old and new code alike, so the
notifies thread the whole block and read the count out of it here.

Attributes:
  FOLDER_FIELD: The manifest-line field that marks a folder placeholder, and the one field the
    copy verb and the collector echo onto a failure record. It is a boolean, so it keeps the
    engine's rule that an echoed field is a bounded name and never a key. **One constant for the
    writer and both readers**, because a name that drifted between them would count every failed
    placeholder as a file and nothing would fail.
  FILE_COUNT_FIELD: The ``transfer`` block's field holding how many of the manifest's lines are
    files.
"""

FOLDER_FIELD = "folder"

FILE_COUNT_FIELD = "fileCount"


def is_folder_placeholder(key: str) -> bool:
    """Reports whether a key names a folder placeholder rather than a file.

    Judged by the key's shape and never by its size, so a genuinely empty file is still a file.
    The same test holds for a relative key, a space key, an archive key and a destination key,
    because each keeps the trailing slash the placeholder was written with.

    Args:
      key: Any object key this plane handles.

    Returns:
      True when the key ends in ``/``.

    Raises:
      None.
    """
    return key.endswith("/")


def count_files(keys) -> int:
    """Counts the keys that name files, leaving out folder placeholders.

    Args:
      keys: Object keys of any one form.

    Returns:
      How many of them are not placeholders.

    Raises:
      None.
    """
    return sum(1 for key in keys if not is_folder_placeholder(key))


def _count(value) -> int | None:
    """Reads a value as a count, refusing everything that is not a non-negative integer.

    ``bool`` is refused explicitly because it is an ``int`` to ``isinstance``, and a flag read as
    a count is 0 or 1 files whatever the run held.

    Args:
      value: The candidate.

    Returns:
      The count, or None when the value cannot be one.

    Raises:
      None.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def file_count(state: dict) -> int:
    """Reads how many files a run holds, off the ``transfer`` block its manifest builder wrote.

    **It falls back to ``objectCount``, which is the wording from before this count existed.**
    The fallback serves a run that straddles a deploy: a restore waits for hours on the machine
    definition it started with, and the Lambdas and the definition deploy in no fixed order, so a
    notify can meet a payload with no ``transfer`` block or a block its builder wrote without the
    count. A count larger than the object count is refused the same way, because it can only come
    from a block that describes some other manifest, and the folders derived from the difference
    would otherwise be clamped silently to none.

    Args:
      state: The running state, or a notify payload that threads the ``transfer`` block.

    Returns:
      The file count, or the object count when no usable file count is present, or 0 when
      neither is.

    Raises:
      None.
    """
    objects = _count(state.get("objectCount"))
    transfer = state.get("transfer")
    files = _count(transfer.get(FILE_COUNT_FIELD)) if isinstance(transfer, dict) else None
    if files is not None and (objects is None or files <= objects):
        return files
    return objects or 0


def shown(files: int, files_short: int, folders_short: int, unknown_short: int = 0) -> tuple:
    """Turns a shortfall into the "done of total" pair a sentence names.

    ``unknown_short`` is shortfall of no known kind — the items an export never accounted for.
    It is attributed to the files first, up to the files there are, and the rest to folders —
    and so is any ``files_short`` beyond the files there are, which only a line flagged against
    its own key could produce. That keeps ``done`` from going below zero and keeps
    ``total - done`` equal to the whole shortfall.

    Args:
      files: How many files the run held.
      files_short: How many files are known to have fallen short.
      folders_short: How many placeholders are known to have fallen short.
      unknown_short: How many items fell short with no kind known.

    Returns:
      ``(done, total)``.

    Raises:
      None.
    """
    short = files_short + folders_short + unknown_short
    counted_as_files = min(files, files_short + unknown_short)
    return files - counted_as_files, files + short - counted_as_files


def shown_outcome(outcome: dict) -> tuple:
    """Reads the counts a person is shown off the collector's verdict.

    **It falls back to the verdict's object counts when the ``shown`` block is absent**, for
    ``file_count``'s reason: a verb reading this can run on newer code than the collector that
    wrote the verdict seconds earlier.

    Args:
      outcome: The collector's ``transferOutcome``.

    Returns:
      ``(done, total, occupied)``.

    Raises:
      None.
    """
    reported = outcome.get("shown")
    source = reported if isinstance(reported, dict) else outcome
    done = source.get("copied") or 0
    total = source.get("total") if isinstance(reported, dict) else source.get("expected")
    return done, total or 0, source.get("occupied") or 0
