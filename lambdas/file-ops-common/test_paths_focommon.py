"""The derived destination, which is what every guard on this plane actually compares.

The prefix a request carries is the folder items are copied INTO. It is not where any of them ends
up, and comparing it instead is how a move deletes a source it copied onto itself.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon.errors import TerminalError
from focommon import messages, paths  # noqa: F401


def _folder(key, target=None):
    item = {"kind": "folder", "key": key}
    if target is not None:
        item["targetName"] = target
    return item


def _file(key, target=None):
    item = {"kind": "file", "key": key}
    if target is not None:
        item["targetName"] = target
    return item


def test_a_folders_derived_key_is_RE_NORMALISED_to_a_trailing_slash():
    """The load-bearing line, and the one a reasonable implementation gets wrong.

    A folder's source key carries a trailing slash; the leaf-name helper strips one. So a naive
    concatenation yields ``alice/reports`` for a source of ``alice/reports/`` — unequal, the
    same-key rule never fires, and a move copies every object onto itself and then deletes the
    source. Versioning is off.
    """
    assert paths.derived_destination_key("alice/", _folder("alice/reports/")) == "alice/reports/"


def test_the_worked_example_the_same_key_rule_depends_on():
    """``move alice/reports/ -> alice/`` derives ``alice/reports/``, which IS the source.

    Comparing the destination PREFIX instead would compare ``alice/`` against ``alice/reports/``,
    find them different, and accept the operation.
    """
    item = _folder("alice/reports/")

    assert paths.derived_destination_key("alice/", item) == item["key"]


def test_a_file_keeps_no_trailing_slash():
    assert paths.derived_destination_key("alice/out/", _file("alice/q1.csv")) == "alice/out/q1.csv"


def test_a_rename_is_expressible_only_through_the_per_item_name():
    """A rename sends the containing folder and a different name. Without the name the operation is
    inexpressible: deriving from the key alone either equals the source — reporting success having
    renamed nothing — or nests the folder inside itself, depending on what the caller sent."""
    assert paths.derived_destination_key("alice/", _folder("alice/reports/", "q4")) == "alice/q4/"


def test_a_same_folder_auto_numbered_copy_has_the_identical_shape():
    assert (
        paths.derived_destination_key("alice/", _file("alice/report.csv", "report (1).csv"))
        == "alice/report (1).csv"
    )


def test_the_fallback_is_on_ABSENCE_not_falsiness():
    """The sharpest hole on this plane.

    An empty ``targetName`` derives to the destination prefix ITSELF, which merges a folder's
    contents into the destination and then, for a move, deletes the source. Substituting the item's
    own name there would turn the request into a successful operation nobody asked for; it is
    refused instead.
    """
    with pytest.raises(TerminalError) as caught:
        paths.derived_destination_key("alice/", _folder("alice/reports/", ""))

    assert caught.value.reason == "invalid_target_name"


@pytest.mark.parametrize(
    "name",
    ["", " ", "a/b", "..", ".", " leading", "trailing ", "with\x00null", "x" * 256],
)
def test_a_name_that_is_not_one_usable_segment_is_refused(name):
    """The browser's leaf rule plus the two it does not carry — dot segments and a length cap —
    because the browser only ever names a folder the user is looking at, and this plane accepts a
    hand-crafted envelope. S3 does not normalise, so a name with a slash or a dot segment produces
    a real object no listing renders and the browser can never reach or delete."""
    with pytest.raises(TerminalError) as caught:
        paths.validate_target_name(name)

    assert caught.value.reason == "invalid_target_name"


@pytest.mark.parametrize("name", ["q4", "report (1).csv", "a" * 255, "spaces inside are fine"])
def test_an_ordinary_name_is_accepted(name):
    assert paths.validate_target_name(name) == name


@pytest.mark.parametrize(
    "item",
    [
        {"key": "alice/reports/"},
        {"kind": "Folder", "key": "alice/reports/"},
        {"type": "folder", "key": "alice/reports/"},
        {"kind": None, "key": "alice/reports/"},
    ],
)
def test_an_UNRECOGNISED_kind_is_refused_rather_than_treated_as_a_file(item):
    """The less obvious half of the same data-loss shape as the empty ``targetName``.

    The trailing slash is applied on ``kind == "folder"``, so anything else — an absent field, a
    capitalised one, a caller that spelled it ``type`` — silently produces the no-slash form. That
    is exactly the key that makes ``move alice/reports/ -> alice/`` derive ``alice/reports``, miss
    the same-key rule, copy every object onto itself and then delete the source.
    """
    with pytest.raises(TerminalError) as caught:
        paths.derived_destination_key("alice/", item)

    assert caught.value.reason == "invalid_items"


def test_an_item_with_no_key_refuses_rather_than_raising_a_KeyError():
    """A bare KeyError surfaces as an unexpected error rather than a refusal, which means the user
    is told to contact an administrator about a malformed request."""
    with pytest.raises(TerminalError) as caught:
        paths.derived_destination_key("alice/", {"kind": "file"})

    assert caught.value.reason == "invalid_items"


def test_the_name_cap_is_applied_to_BYTES_as_well_as_characters():
    """S3's own limit is 1024 BYTES for a whole key, so 255 astral characters is 1020 bytes and
    would leave nothing for the prefix the name sits under."""
    with pytest.raises(TerminalError):
        paths.validate_target_name("\U0001F600" * 200)


def test_containment_is_re_exported_rather_than_re_implemented():
    """A second copy of the containment rule is a second place a cross-tenant read is introduced,
    so this plane does not own one — it uses the shared module's, and this asserts the identity
    rather than the behaviour."""
    from cpcommon import paths as shared

    assert paths.assert_inside_root is shared.assert_inside_root
    assert paths.has_dot_segment is shared.has_dot_segment
    assert paths.normalize_root is shared.normalize_root


def test_a_key_with_no_final_segment_fails_rather_than_deriving_to_the_prefix():
    with pytest.raises(TerminalError):
        paths.item_name("///")


# ── The per-object builder ───────────────────────────────────────────────────


def test_an_objects_destination_keeps_its_key_relative_to_its_ITEM():
    """The relative-key rule: a folder arrives with its structure intact, one level under wherever
    it was dropped."""
    built = paths.destination_key("alice/out/", "reports", "2026/q1.csv", is_folder=True)

    assert built == "alice/out/reports/2026/q1.csv"


def test_the_folder_itself_is_re_normalised_even_with_no_relative_key():
    """The residue that re-opened the data-loss path during review: the leaf-name helper strips the
    slash, so a naive concatenation yields ``alice/out/reports`` — unequal to the source, so the
    same-key rule never fires and a move copies a folder onto itself and then deletes it."""
    assert paths.destination_key("alice/out/", "reports", "", is_folder=True) == "alice/out/reports/"


def test_a_file_lands_as_a_file():
    assert paths.destination_key("alice/out/", "q1.csv", "", is_folder=False) == "alice/out/q1.csv"


def test_the_layout_is_unaffected_by_the_sources_own_depth():
    """Moving ``alice/deep/nested/q1.csv`` into ``alice/out/`` yields ``alice/out/q1.csv``, not a
    rebuilt copy of the path it came from."""
    assert paths.destination_key("alice/out/", "q1.csv", "", is_folder=False) == "alice/out/q1.csv"


def test_the_destination_prefix_is_normalised_rather_than_trusted():
    assert paths.destination_key("alice/out", "r", "a.csv", is_folder=True) == "alice/out/r/a.csv"


@pytest.mark.parametrize("name", [None, "", 0])
def test_a_missing_destination_name_is_refused_rather_than_collapsing_onto_the_prefix(name):
    """An unusable name derives to the destination folder itself, which merges an item's CONTENTS
    into the destination and then, for a move, deletes the source."""
    with pytest.raises(TerminalError):
        paths.destination_key("alice/out/", name, "a.csv", is_folder=True)


def test_the_item_builder_is_the_object_builder_with_no_relative_key():
    """Two functions that agree today are two functions that can stop agreeing, so the item's
    derived key is the object builder called with an empty relative key rather than a second
    composition that happens to match."""
    for item in (_folder("alice/reports/"), _file("alice/q1.csv"), _folder("alice/a/", "r1")):
        expected = paths.destination_key(
            "alice/out/",
            item.get("targetName") or paths.item_name(item["key"]),
            "",
            is_folder=item["kind"] == "folder",
        )

        assert paths.derived_destination_key("alice/out/", item) == expected


def test_a_relative_key_is_measured_from_the_selected_item():
    assert paths.relative_key("alice/reports/", "alice/reports/2026/q1.csv") == "2026/q1.csv"


def test_an_object_outside_its_item_is_refused():
    """The relative key is a SUBSTRING operation, and one taken against the wrong prefix silently
    yields a plausible key rather than an error."""
    with pytest.raises(TerminalError):
        paths.relative_key("alice/reports/", "alice/logs/q1.csv")


# ── Exactly one destination builder ──────────────────────────────────────────

_LAMBDAS = pathlib.Path(__file__).resolve().parents[1]

#: The one module allowed to compose a destination key. Everything else must call it.
_BUILDER = _LAMBDAS / "file-ops-common" / "focommon" / "paths.py"


def _plane_sources():
    """Every production module on this plane, excluding the builder itself and the tests."""
    for directory in sorted(_LAMBDAS.glob("file-ops-*")):
        for path in sorted(directory.rglob("*.py")):
            if path.name.startswith("test_") or path == _BUILDER or "__pycache__" in path.parts:
                continue
            yield path


def _mentions_a_destination(node) -> bool:
    """Reports whether an expression reads anything named for a destination.

    Names, attributes and string subscripts alike, so ``dest_prefix``, ``destination.prefix`` and
    ``item["destKey"]`` are all seen. Matched on ``dest`` alone rather than on ``prefix`` too: this
    plane has a plan PREFIX and a lock PREFIX in the admin bucket that have nothing to do with where
    an object lands, and a sweep that flagged those would be turned off rather than obeyed.
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and "dest" in inner.id.lower():
            return True
        if isinstance(inner, ast.Attribute) and "dest" in inner.attr.lower():
            return True
        if (
            isinstance(inner, ast.Constant)
            and isinstance(inner.value, str)
            and "dest" in inner.value.lower()
        ):
            return True
    return False


def _hand_built_destinations(source: str) -> list:
    """Every place in ``source`` that composes a destination rather than calling the builder.

    TWO RULES, because either alone leaves the hole open.

    (a) No f-string, ``+`` or ``join`` that reads anything named for a destination. That is what a
    hand-rolled ``f"{dest_prefix}{name}/{rel}"`` looks like, and no destination test can catch it:
    they prove the ONE builder is right, and a verb composing its own would pass every one of them
    while writing somewhere else — on a move, with the source deleted afterwards.

    (b) Every ``destKey`` a plan entry carries must be assigned from a CALL. A composition assigned
    through a variable would satisfy (a) only by accident of where the pieces were named.

    **The docstring exemption the precedent for this sweep needed is deliberately absent, and that
    is a consequence of what is being swept.** file-send's rule matches a string CONSTANT — its
    inbox folder name — so its module docstrings tripped it and had to be exempted by node identity.
    This plane's destination has no distinctive literal in it; the rule is over EXPRESSIONS, and an
    f-string or a ``+`` is never a docstring. ``test_the_sweep_would_catch_a_hand_built_key`` is what
    keeps that claim honest.
    """
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        composed = (
            isinstance(node, ast.JoinedStr)
            or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add))
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
            )
        )
        if composed and _mentions_a_destination(node):
            offenders.append(ast.unparse(node))
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names_dest = (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "destKey"
                )
                if names_dest and not isinstance(node.value, ast.Call):
                    offenders.append(ast.unparse(node))
    return offenders


def test_the_sweep_actually_read_the_plane():
    """Guard-the-guard: the rule below is a negative, so a glob that stopped matching would make it
    pass while checking nothing at all."""
    sources = list(_plane_sources())

    assert len(sources) >= 5, f"only found {len(sources)} modules on this plane"
    assert any("destKey" in path.read_text() for path in sources)


def test_no_verb_builds_a_destination_of_its_own():
    for path in _plane_sources():
        offenders = _hand_built_destinations(path.read_text())

        assert not offenders, f"{path.name} composes a destination itself: {offenders}"


@pytest.mark.parametrize(
    "offender",
    [
        'dest_key = f"{dest_prefix}{name}/{rel_key}"',
        'entry["destKey"] = destination["prefix"] + name',
        'x = "/".join([destination_prefix, name])',
        'entry["destKey"] = built',
    ],
)
def test_the_sweep_would_catch_a_hand_built_key(offender):
    """The rule is a negative over code nobody has written yet, so it is worth proving it can fail.
    Each of these is a plausible way a later verb would compose its own destination."""
    assert _hand_built_destinations(offender)
