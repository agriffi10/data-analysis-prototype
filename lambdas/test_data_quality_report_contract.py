"""The two facts about a data-quality report that are written in one language and read in another.

**The size cap.** A report is written by one plane and read by another: assemble-report puts the
object, and the API's document route serves it.

A data-quality report is written by one plane and read by another: assemble-report puts the object,
and the API's document route serves it. So the size the writer stops at has to be the size the
reader will carry, and nothing in either plane can see the other — ``dqcommon`` does not import
``apicommon``, and should not: the API ships inside its own function's package, and a layer that
reached into it would couple every data-quality verb to the API's configuration.

That leaves the number written twice, which is exactly the shape that drifts. A writer whose cap
rose above the reader's would produce reports the page refuses with "that report could not be
read" — a check that ran, cost its scan, wrote its findings, and cannot be opened. A writer whose
cap fell below the reader's would drop the samples off reports that would have opened fine.

**The omission sentences, and the two figures beside them.** The report page shows, verbatim, the
sentence this plane wrote when it had no samples to give — and states two of this plane's NUMBERS in
its own prose, one on the page ("Values longer than 200 characters are shortened") and one in the
Help guide ("up to five of the most repeated rows"). Neither is imported; both are typed out.
Raising `MAX_SAMPLE_VALUE_CHARS` or `DQ_DUPLICATE_SAMPLE` would leave the browser stating a figure
no report produces, with every suite on both sides green. ``reportFixtures.ts`` re-declares each one so the page's tests can render
it, and a fixture that drifts does not fail anything on either side: the browser test asserts the
page shows the fixture's sentence, and the browser shows whatever the report actually carries. The
two would disagree only in production, on the one report that took the branch.

This file is the join, and it lives at the fleet level because this is the only place the two
planes may be imported into one process. The cap asserts equality rather than a bound in either
direction: it is not a safety margin under the reader's limit, it IS the reader's limit, and a
one-sided assertion would let the writer drift silently in the direction it happens to permit. The
sentences are read out of the TypeScript by parsing its string literals rather than by importing
anything, since there is no runtime that holds both.

Attributes:
  FIXTURES: The browser module mirroring this plane's report wording.
  PAGE: The report view, which states the value cut in a note beneath the samples table.
  HELP: The in-app guide, which states how many rows the report keeps.
  _SPELLED: Small counts as the Help guide spells them. A value outside it is not a bug in the
    guide — it is a constant this test cannot check, and it says so rather than raising.
  _ESCAPES: The TypeScript string escapes this reader resolves. Deliberately a closed set: an
    escape it does not know is a value it would compare wrongly, so ``_string_literals`` refuses
    one rather than passing the backslash through and failing with a confusing diff.
"""

import os
import pathlib
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# data-quality-common is deliberately absent from conftest's layer roots, and apicommon is not a
# layer at all — it ships inside the API function's package. Both inserts are load-bearing.
sys.path.insert(0, os.path.join(_HERE, "api"))
sys.path.insert(0, os.path.join(_HERE, "data-quality-common"))

from apicommon import s3_config
from dqcommon import config, report

FIXTURES = (
    pathlib.Path(_HERE).parent
    / "apps"
    / "portal"
    / "src"
    / "features"
    / "data-quality"
    / "reportFixtures.ts"
)

PAGE = FIXTURES.parent / "DataQualityReportPage.tsx"
HELP = FIXTURES.parent.parent / "help" / "helpContent.ts"

_ESCAPES = {"'": "'", '"': '"', "\\": "\\", "n": "\n", "t": "\t"}

_SPELLED = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


def _string_literals(declaration: str) -> list[str]:
    """Reads the string literals of one TypeScript declaration, in source order.

    BOTH quote styles, which is the whole reason this is a scanner rather than one regular
    expression. Prettier picks the quote that needs no escaping, so a sentence carrying an
    apostrophe is double-quoted and the one beside it — the same declaration, the same
    concatenation — is single-quoted. A reader that knew one style would silently drop half of a
    split sentence and report a drift that is not there, which is worse than no check: a guard
    that cries wolf is one somebody eventually deletes.

    Args:
      declaration: The source from just past the declaration's name to the end of the file.

    Returns:
      The literals up to the statement's terminating semicolon, unescaped.

    Raises:
      AssertionError: On an escape this reader does not resolve, rather than comparing a value it
        has read wrongly.
    """
    out: list[str] = []
    index = 0
    while index < len(declaration):
        char = declaration[index]
        if char == ";":
            break
        if char not in ("'", '"'):
            index += 1
            continue
        quote, index, buffer = char, index + 1, []
        while index < len(declaration) and declaration[index] != quote:
            if declaration[index] != "\\":
                buffer.append(declaration[index])
                index += 1
                continue
            escape = declaration[index + 1]
            assert escape in _ESCAPES, f"unhandled TypeScript escape \\{escape}"
            buffer.append(_ESCAPES[escape])
            index += 2
        out.append("".join(buffer))
        index += 1
    return out


def _fixture_constant(name: str) -> str:
    """Reads one exported string constant out of the fixtures module.

    Parsed rather than transpiled: the fixtures import types this test cannot resolve, and the
    only thing in question is the text of one literal.

    Args:
      name: The exported constant's name.

    Returns:
      Its value, with the source's line-splitting concatenation joined back up.

    Raises:
      AssertionError: When the fixtures module does not declare it.
    """
    source = FIXTURES.read_text(encoding="utf-8")
    marker = f"export const {name} ="
    assert marker in source, f"{FIXTURES.name} declares no {name}"
    return "".join(_string_literals(source.split(marker, 1)[1]))


def test_the_report_cap_is_the_size_the_browser_can_read_a_document_through():
    """Holds the writer's cap equal to the reader's, in both directions.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert config.DQ_REPORT_MAX_BYTES == s3_config.MAX_DOCUMENT_BYTES


def test_the_report_cap_is_derived_from_lambdas_response_ceiling_and_not_a_round_number():
    """Pins the derivation behind the number, so a coincidence cannot stand in for agreement.

    Equality alone would still hold if both sides were edited to the same wrong figure. The cap is
    half a Lambda synchronous response's 6 MiB — the document routes' line on a stored body, below
    which they measure the escaped response instead — and that is what is asserted: the budget,
    named, rather than the value it currently produces.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert config.DQ_REPORT_MAX_BYTES == 6 * 1024 * 1024 // 2


@pytest.mark.parametrize(
    "name", ["SAMPLES_OMITTED_NESTED", "SAMPLES_OMITTED_TOO_LARGE"]
)
def test_the_browser_spells_an_omitted_sample_sentence_the_way_this_plane_wrote_it(
    name,
):
    """Holds each omission sentence byte-identical between the writer and the page's fixtures.

    Both carry an apostrophe, and the two languages' house styles disagree about which one — the
    browser writes a typographic apostrophe nearly everywhere, this plane writes an ASCII one. A
    fixture that quietly corrected it would leave the page's test asserting a sentence no report
    ever contains.

    Args:
      name: The constant's name, which is the same on both sides.

    Returns:
      None.

    Raises:
      None.
    """
    assert _fixture_constant(name) == getattr(report, name)


def test_the_literal_reader_handles_the_source_the_formatter_actually_produces():
    """The positive control for the reader the pin above is built on.

    Without it a reader that returned nothing and a fixture that matched perfectly would be the
    same green run. The fixture here is the shape Prettier actually emits — it picks whichever
    quote needs no escaping, so one concatenated sentence can carry both styles — plus an escaped
    quote, which is what it emits when a string needs both.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert _string_literals(
        "\n  \"it isn't\" +\n  'plain' +\n  'a \\'quoted\\' word';\nexport const NEXT = 'no';"
    ) == ["it isn't", "plain", "a 'quoted' word"]


@pytest.mark.parametrize(
    ("path_name", "sentence", "expected"),
    [("PAGE", "Values longer than {} characters are shortened.", report.MAX_SAMPLE_VALUE_CHARS)],
    ids=["the page's truncation note"],
)
def test_the_browser_states_this_planes_figures_and_not_its_own(path_name, sentence, expected):
    """Holds each figure the browser TYPES OUT against the constant that actually decides it.

    Two numbers cross the language boundary as prose rather than as values, which is the shape that
    drifts without anything going red: the page's note names ``MAX_SAMPLE_VALUE_CHARS`` and the
    guide names ``DQ_DUPLICATE_SAMPLE``, and raising either constant would leave both sentences
    describing a report the plane no longer writes.

    The sentence is searched for with the expected figure already substituted in, so the assertion
    fails when the CONSTANT moves as well as when the prose does — a search for the sentence with a
    wildcard where the number goes would pass on any number at all.

    Args:
      path_name: Which browser file states it.
      sentence: The sentence, with a placeholder where the figure goes.
      expected: The figure the plane's constant decides, spelled as the browser spells it.

    Returns:
      None.

    Raises:
      None.
    """
    source = {"PAGE": PAGE, "HELP": HELP}[path_name].read_text(encoding="utf-8")

    assert sentence.format(expected) in source


def test_the_help_guides_word_for_the_sample_count_is_the_one_the_config_sets():
    """Reads the guide's spelled-out count THROUGH ``DQ_DUPLICATE_SAMPLE`` rather than beside it.

    The guide writes the figure as an English word, so the number cannot be compared directly and a
    test that pinned the literal "five" would hold the prose still while the constant moved beneath
    it. Spelling the constant and searching for THAT sentence ties the two together in one
    assertion: raise the constant and the search fails, naming the sentence to edit.

    An unspellable value fails with the repair rather than with a ``KeyError`` from inside a
    lookup — a guard whose own failure has to be decoded is one the next reader works around.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    spelled = _SPELLED.get(config.DQ_DUPLICATE_SAMPLE)
    assert spelled is not None, (
        f"DQ_DUPLICATE_SAMPLE is {config.DQ_DUPLICATE_SAMPLE}, which this test has no word for: "
        "add it to _SPELLED, then edit the Help guide's sentence to match"
    )

    assert f"it lists up to {spelled} of the most repeated ones" in HELP.read_text(encoding="utf-8")
