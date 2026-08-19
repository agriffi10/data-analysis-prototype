"""The column-name rule: what it refuses, what it deliberately does not, and why.

Column names are the one part of a schema this portal does not choose — they come out of a
file's own header or Parquet footer — and until now nothing judged them. The failure that made
this necessary is not a failed build: Glue accepts these names and the renderers quote them, so
the table is CREATED, appears in the rail, and fails or returns nothing when read.
"""

import pytest
from cpcommon import columns


class TestOneName:
    """`is_valid` on its own terms, name by name."""

    @pytest.mark.parametrize(
        "name",
        [
            "total",
            "order_id",
            "id",  # Two characters. CATALOG_IDENTIFIER_RE's 3-char floor is a rule about
            # names a user TYPES, and applying it here would refuse the commonest column there is.
            "_id",  # Leading underscore: AWS documents backticks for it, and every DDL path
            # here quotes.
            "2024_total",  # Leading digit: same, with double quotes in DML.
            "select",  # A reserved word, quoted in both dialects by `ddl.quote`/`quote_dml`.
            "Total",  # Mixed case survives as data and folds on read.
            "a" * 255,
        ],
    )
    def test_accepts(self, name):
        assert columns.is_valid(name), name

    @pytest.mark.parametrize(
        ("name", "why"),
        [
            ("", "a blank cell in a CSV header row produces this routinely"),
            ("   ", "whitespace-only is the same case wearing a disguise"),
            (" total", "leading whitespace is invisible wherever the name is displayed"),
            ("total ", "and so is trailing"),
            ("Order ID", "a space is the commonest real-world offender"),
            ("sales-2024", "a hyphen"),
            ("tax%", "punctuation"),
            ("a.b", "a period is legal only inside a complex type's own path"),
            ("col\tname", "a tab"),
            ("col\nname", "a newline"),
            ("naïve", "non-ASCII folds unpredictably and is not [a-z0-9_]"),
            # U+212A KELVIN SIGN. `str.lower` maps it to `k`, so it reached `[a-z]` and passed a
            # length bound AWS documents in BYTES — where it costs three, not one.
            ("\u212a", "a non-ASCII character that lowercases INTO the allowed range"),
            ("a" * 256, "Glue's own ceiling is 255"),
            (None, "a schema with a missing name is not a schema"),
            (42, "nor is one with a non-string name"),
        ],
    )
    def test_refuses(self, name, why):
        assert not columns.is_valid(name), why

    def test_a_backtick_is_refused_and_that_one_is_not_merely_untidy(self):
        """`ddl.quote` wraps in backticks and does NOT escape what it wraps, so a header cell
        carrying one closes the quote and the rest of the cell becomes DDL. The column name is
        user data read out of a file, which makes this the sharpest name in the set."""
        assert not columns.is_valid("a`b")
        assert not columns.is_valid("x` string, `injected")


class TestWholeSchema:
    """`check`, which is about the schema rather than about any one name in it."""

    def test_a_clean_schema_raises_nothing(self):
        columns.check([{"name": "id"}, {"name": "total"}, {"name": "_ts"}])

    def test_names_the_offenders_in_declaration_order(self):
        with pytest.raises(columns.InvalidColumnNamesError) as err:
            columns.check([{"name": "id"}, {"name": "Order ID"}, {"name": "ok"}, {"name": "tax%"}])
        assert err.value.names == ["Order ID", "tax%"]
        assert err.value.summary == '"Order ID", "tax%"'

    def test_a_case_fold_collision_is_refused_and_BOTH_names_are_reported(self):
        """The one that reads as a bug in the portal rather than in the file: `Total` and
        `TOTAL` are two columns to every tool the user has and one column to Athena. Both are
        named because the user has to change one and cannot be told which without seeing both.
        """
        with pytest.raises(columns.InvalidColumnNamesError) as err:
            columns.check([{"name": "Total"}, {"name": "id"}, {"name": "TOTAL"}])
        assert err.value.names == ["Total", "TOTAL"]

    def test_an_exact_duplicate_is_refused_and_named_ONCE(self):
        """A collision between two spellings names both, because the user has to pick one. A
        collision between a name and itself names it once — repeating it in the refusal would
        be telling them to rename `total` to something other than `total`."""
        with pytest.raises(columns.InvalidColumnNamesError) as err:
            columns.check([{"name": "total"}, {"name": "total"}])
        assert err.value.names == ["total"]

    def test_one_error_carries_both_failure_kinds(self):
        """Raised together because they are one question — "which columns do I rename?" — and
        raising them separately would show a shape refusal, take the fix, then reveal the
        collision underneath it."""
        with pytest.raises(columns.InvalidColumnNamesError) as err:
            columns.check([{"name": "Order ID"}, {"name": "Total"}, {"name": "TOTAL"}])
        assert err.value.names == ["Order ID", "Total", "TOTAL"]

    def test_a_repeated_offender_is_named_once(self):
        with pytest.raises(columns.InvalidColumnNamesError) as err:
            columns.check([{"name": "tax%"}, {"name": "tax%"}])
        assert err.value.names == ["tax%"]


class TestRefusalWording:
    """The refusal is read in a notification, so its length is a product concern."""

    def test_bounds_the_named_columns_and_counts_the_rest(self):
        names = [f"bad name {i}" for i in range(25)]
        summary = columns.describe(names)
        assert summary.count('"') == columns.MAX_NAMED_IN_REFUSAL * 2
        assert summary.endswith(f"and {25 - columns.MAX_NAMED_IN_REFUSAL} more")

    def test_says_nothing_about_a_remainder_when_there_is_none(self):
        assert "more" not in columns.describe(["a b", "c d"])

    def test_bounds_each_NAME_too_not_only_how_many(self):
        """A count bound alone still permits ten names of MAX_COLUMN_NAME_LENGTH — a 2.5 KB
        sentence in a notification body."""
        summary = columns.describe(["x" * 400])
        assert len(summary) < 100
        assert summary.endswith('…"')
