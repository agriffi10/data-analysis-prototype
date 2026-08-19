"""The derived destination, which is what every guard on this plane actually compares.

The prefix a request carries is the folder items are copied INTO. It is not where any of them ends
up, and comparing it instead is how a move deletes a source it copied onto itself.
"""

import os
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
