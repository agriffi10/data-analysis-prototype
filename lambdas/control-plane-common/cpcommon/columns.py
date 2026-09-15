"""The rule for a data column name that will work in Athena without a workaround.

Column names are the one part of a table's schema this portal does not choose: they are read
out of a file's own header or Parquet footer, so they arrive as user data and have to be
judged before they become catalog identifiers. Table and database names do not come through
here — those are typed into a dialog and held to ``config.CATALOG_IDENTIFIER_RE``.

Partition-key names are split: table-builder's are declared in that same dialog and validated
with it, but data-quality DETECTS its own from S3 path segments, which makes them a name the
user wrote by naming a folder. Those go through ``check_names`` at the verb that renders them.

**WHAT THE RULE REFUSES, AND WHY EACH ONE IS NOT MERELY UNTIDY.** Athena lowercases every
identifier as it runs a statement, and AWS Glue accepts a column name this repo's renderers
will then quote. Between them, a bad name does not produce a failed build — it produces a
table that is created, appears in the rail, and fails or returns nothing when read. Each
refusal below is a case that reaches the user later rather than now:

* An **empty name**, which a blank cell in a CSV header row produces routinely, renders as an
  empty backtick pair and is a DDL syntax error.
* **Leading or trailing whitespace** is accepted by Glue and is invisible everywhere the name
  is displayed, so the column exists under a name nobody can retype.
* Any character outside ``[a-z0-9_]`` after the fold. Backticks make a great deal of this
  parse, which is exactly the problem: the table builds and the trouble surfaces later, in a
  complex type (where AWS permits only alphanumerics, underscore and period), in a SerDe that
  reads the name differently, or in a query the user writes by hand without the quoting this
  app applies for them. A **backtick** in the name is the sharp case — ``ddl.quote`` does not
  escape what it wraps, so a header cell carrying one closes the quote and the rest of the
  cell becomes DDL.
* Two names that **fold to the same lowercase string**. This is the one that reads as a bug in
  the portal rather than in the file: ``Total`` and ``TOTAL`` are two columns to every tool the
  user has, and one column to Athena.
* A name over ``MAX_COLUMN_NAME_LENGTH``, which Glue refuses on its own, with an error naming
  neither the column nor the limit.

**WHAT IT DELIBERATELY ALLOWS.** A leading digit, a leading underscore and a reserved word are
all fine, and refusing them would be this app inventing a restriction AWS does not have: DDL
here goes through ``ddl.quote`` (backticks) and DML through ``ddl.quote_dml`` and the browser's
``sqlLiteral`` (double quotes), which is precisely the escaping AWS documents for all three.
Mixed case is allowed too, with its consequence stated rather than glossed: Athena lowercases
the name when it creates the column, so a header of ``Castle`` becomes the column ``castle`` and
the file itself is never rewritten. That is surprising but harmless on its own. Only a fold
*collision* — two headers that become one column — is refused.

Attributes:
  MAX_COLUMN_NAME_LENGTH: Glue's own ceiling on a column name, which AWS documents in BYTES.
    Characters and bytes are the same number here only because ``is_valid`` rejects non-ASCII
    before measuring — see the note there on U+212A.
  MAX_NAMED_IN_REFUSAL: How many offending names a refusal spells out before summarising the
    rest. A wide file can carry hundreds, and the refusal is read in a notification.
  MAX_NAME_CHARS_IN_REFUSAL: How much of one name is shown. A count bound alone still permits
    ten names of ``MAX_COLUMN_NAME_LENGTH`` each, which is a 2.5 KB sentence.
  COLUMN_NAME_RE: The rule itself, applied to the LOWERCASED name.
"""

import re
from collections.abc import Iterable

MAX_COLUMN_NAME_LENGTH = 255

MAX_NAMED_IN_REFUSAL = 10

MAX_NAME_CHARS_IN_REFUSAL = 60

COLUMN_NAME_RE = re.compile(rf"^[a-z0-9_]{{1,{MAX_COLUMN_NAME_LENGTH}}}$")


class InvalidColumnNamesError(ValueError):
    """One or more inferred column names will not work in Athena.

    Carries the offending names so a caller can put them in front of the user — a refusal that
    does not say which column is the one thing the user cannot work out for themselves.

    Attributes:
      names: The offending names, in the order the schema declared them, deduplicated.
      summary: A ready-made phrase naming them, bounded by ``MAX_NAMED_IN_REFUSAL``.
    """

    def __init__(self, names: list[str]) -> None:
        """Builds the error from the offending names.

        Args:
          names: The offending column names, in schema order.

        Returns:
          None.

        Raises:
          None.
        """
        self.names = names
        self.summary = describe(names)
        super().__init__(self.summary)


def _clip(name: str) -> str:
    """Shortens one name for display, marking that it was shortened.

    Args:
      name: The name to show.

    Returns:
      The name, truncated to ``MAX_NAME_CHARS_IN_REFUSAL`` with an ellipsis when it was longer.

    Raises:
      None.
    """
    return name if len(name) <= MAX_NAME_CHARS_IN_REFUSAL else name[:MAX_NAME_CHARS_IN_REFUSAL] + "…"


def describe(names: list[str]) -> str:
    """Renders a bounded, quoted list of column names for a user-facing refusal.

    Args:
      names: The offending column names, in schema order.

    Returns:
      A phrase naming up to ``MAX_NAMED_IN_REFUSAL`` of them, with a count for any remainder.

    Raises:
      None.
    """
    shown = ", ".join(f'"{_clip(name)}"' for name in names[:MAX_NAMED_IN_REFUSAL])
    extra = len(names) - MAX_NAMED_IN_REFUSAL
    return f"{shown} and {extra} more" if extra > 0 else shown


def fold(name: str) -> str:
    """The name Athena gives a column: the name lowercased, and never case-folded.

    A create's collision rule, a refresh's diff, the names its write lands and the read-back that
    verifies them all ask whether two names are one column through here, so they cannot disagree.
    AWS documents that Athena lowers a name, and Hive normalises an identifier with Java's
    ``toLowerCase``, which, like Python's ``str.lower``, is Unicode lowercasing and keeps ``ß``.
    ``str.casefold`` is a different operation. It also maps ``ß`` to ``ss``, so it merges
    ``Straße`` and ``STRASSE``, which Athena keeps as two columns. The two differ only outside
    ASCII, which is why only a refresh, which skips the name rule, can tell them apart.

    Args:
      name: A column name as a header, a footer or the catalog spells it.

    Returns:
      The name as Athena would store it.

    Raises:
      None.
    """
    return name.lower()


def is_valid(name: object) -> bool:
    """Is one column name usable in Athena on its own terms?

    Says nothing about collisions, which are a property of the whole schema rather than of any
    one name in it. Use :func:`check` for a schema.

    The ASCII check is not redundant beside the pattern. ``str.lower`` maps U+212A KELVIN SIGN
    to ``k``, so a three-byte character reached ``[a-z]`` and passed a length bound documented in
    BYTES — the one claim the ceiling rests on.

    Args:
      name: The candidate name.

    Returns:
      True when the name is a non-empty ASCII ``[a-z0-9_]`` string within the length ceiling,
      judged after lowercasing — so ``Total`` passes and ``Order ID`` does not.

    Raises:
      None.
    """
    return isinstance(name, str) and name.isascii() and COLUMN_NAME_RE.fullmatch(fold(name)) is not None


def invalid_names(names: Iterable[object]) -> list[str]:
    """The names in a schema that no quoting will make work, in declaration order.

    Deduplicated by the raw name so a column list that repeats one offender reports it once.

    Args:
      names: The column names, in declaration order.

    Returns:
      The offending names.

    Raises:
      None.
    """
    seen: dict[str, None] = {}
    for name in names:
        if not is_valid(name):
            seen.setdefault(name if isinstance(name, str) else repr(name), None)
    return list(seen)


def folded_duplicates(names: Iterable[object]) -> list[str]:
    """The names a schema declares more than once once Athena has lowercased them.

    Every name that takes part in a collision is returned, not just the second one: the user
    has to change one of them and cannot be told which without seeing both.

    Args:
      names: The column names, in declaration order.

    Returns:
      Every colliding name, in declaration order.

    Raises:
      None.
    """
    counts: dict[str, int] = {}
    for name in names:
        if isinstance(name, str):
            counts[fold(name)] = counts.get(fold(name), 0) + 1
    return [n for n in names if isinstance(n, str) and counts[fold(n)] > 1]


def check_names(names: Iterable[object]) -> None:
    """Refuses a set of names that would not survive Athena.

    Args:
      names: The names, in declaration order.

    Returns:
      None.

    Raises:
      InvalidColumnNamesError: When any name is unusable or any two fold together.
    """
    offenders = invalid_names(names)
    for name in folded_duplicates(names):
        if name not in offenders:
            offenders.append(name)
    if offenders:
        raise InvalidColumnNamesError(offenders)


def check(columns: Iterable[dict]) -> None:
    """Refuses a schema whose column names would not survive Athena.

    Both failures are reported through one error because they are one question to the user —
    "which columns do I have to rename?" — and a caller that raised them separately would show
    a name-shape refusal, take the fix, and only then reveal the collision underneath it.

    Args:
      columns: The inferred columns, each a dict carrying ``name``.

    Returns:
      None.

    Raises:
      InvalidColumnNamesError: When any name is unusable or any two fold together.
    """
    check_names([column.get("name") for column in columns])
