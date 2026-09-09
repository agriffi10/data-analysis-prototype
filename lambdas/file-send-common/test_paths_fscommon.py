"""Containment is the one place on this plane where a bug is a cross-tenant read.

SPEC-164 FR-003 requires the rule to be TWO rules with a test each, because either alone leaves
a hole. These are those tests at the module level; the verb's own suite exercises the same rules
through the real handler.

SPEC-165 FR-003 added the destination layout below, plus the sweep that forbids a verb building
one by hand — the layout is what a recipient sees forever, and a second builder would be free to
disagree with this one in a way that shows up as files in the wrong inbox rather than as an error.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon.errors import TerminalError
from fscommon import config, paths


def _refused(root, key):
    with pytest.raises(TerminalError) as caught:
        paths.assert_inside_root(root, key)
    return caught.value.reason


# ── Rule (a): the trailing-slash-normalised root ─────────────────────────────


def test_a_key_inside_the_root_passes():
    assert paths.assert_inside_root("alice/", "alice/reports/q1.csv") == "alice/reports/q1.csv"


def test_a_root_without_its_trailing_slash_is_normalised():
    assert paths.assert_inside_root("alice", "alice/q1.csv") == "alice/q1.csv"


def test_a_sibling_prefix_is_refused():
    """THE alice2/ CASE. A raw `key.startswith("alice")` accepts this, and nothing about the
    two usernames has to be related for one to be a prefix of the other."""
    assert _refused("alice", "alice2/secrets.csv") == "forbidden"


def test_a_sibling_prefix_is_refused_even_when_the_root_carries_its_slash():
    assert _refused("alice/", "alice2/secrets.csv") == "forbidden"


def test_an_unrelated_key_is_refused():
    assert _refused("alice/", "bob/secrets.csv") == "forbidden"


def test_an_empty_root_refuses_rather_than_matching_everything():
    """The dangerous degenerate case: an empty prefix makes every key in the bucket "inside"
    it, so this fails closed rather than normalising to ""."""
    assert _refused("", "bob/secrets.csv") == "forbidden"
    assert _refused("/", "bob/secrets.csv") == "forbidden"


# ── Rule (b): dot segments ───────────────────────────────────────────────────


def test_a_parent_segment_is_refused_despite_starting_with_the_root():
    """`"alice/../bob/secrets.csv".startswith("alice/")` is True. Normalisation does nothing
    about dot segments, which is why this is a separate rule and not a nicety."""
    assert _refused("alice/", "alice/../bob/secrets.csv") == "forbidden"


def test_a_current_segment_is_refused():
    assert _refused("alice/", "alice/./q1.csv") == "forbidden"


def test_a_trailing_parent_segment_is_refused():
    assert _refused("alice/", "alice/reports/..") == "forbidden"


@pytest.mark.parametrize("name", ["..hidden.csv", "q1..csv", "...", "a.b.c"])
def test_a_dot_inside_a_name_is_not_a_dot_segment(name):
    """The rule is about SEGMENTS, and getting that wrong would refuse ordinary user files.
    `...` is a legal S3 object name and is not `..`."""
    key = f"alice/{name}"

    assert paths.assert_inside_root("alice/", key) == key


def test_has_dot_segment_is_exposed_and_agrees():
    assert paths.has_dot_segment("alice/../bob") is True
    assert paths.has_dot_segment("alice/..hidden") is False


# ── Shape ────────────────────────────────────────────────────────────────────


def test_a_missing_key_is_refused():
    assert _refused("alice/", "") == "forbidden"
    assert _refused("alice/", None) == "forbidden"


# ── SPEC-165 FR-003: item names and relative keys ────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("alice/reports/", "reports"),
        ("alice/reports", "reports"),
        ("alice/notes.txt", "notes.txt"),
        ("alice/deep/nested/q1.csv", "q1.csv"),
        ("alice/deep/nested/", "nested"),
    ],
)
def test_an_items_name_is_its_last_segment(key, expected):
    assert paths.item_name(key) == expected


@pytest.mark.parametrize("key", ["", "/", "///"])
def test_a_key_with_no_final_segment_has_no_item_name(key):
    """An empty name would collapse every destination onto the sender's inbox root, merging one
    send into another. Nothing should reach here with such a key, which is exactly why it fails
    rather than depending on a check two modules away staying correct."""
    with pytest.raises(TerminalError) as caught:
        paths.item_name(key)

    assert caught.value.reason == "forbidden"


def test_a_relative_key_is_measured_from_the_selected_item():
    assert paths.relative_key("alice/reports/", "alice/reports/2026/q1.csv") == "2026/q1.csv"


def test_a_file_items_relative_key_is_empty():
    assert paths.relative_key("alice/notes.txt", "alice/notes.txt") == ""


def test_an_object_outside_its_item_is_refused():
    with pytest.raises(TerminalError) as caught:
        paths.relative_key("alice/reports/", "alice/other/q1.csv")

    assert caught.value.reason == "forbidden"


# ── SPEC-165 FR-003: the destination layout ──────────────────────────────────


def test_a_folder_items_object_lands_under_the_senders_inbox():
    assert (
        paths.destination_key("bob/", "alice", "reports", "2026/q1.csv")
        == "bob/shared_files/alice/reports/2026/q1.csv"
    )


def test_a_file_item_lands_as_a_file():
    assert (
        paths.destination_key("bob/", "alice", "notes.txt", "")
        == "bob/shared_files/alice/notes.txt"
    )


def test_the_destination_is_unaffected_by_the_senders_own_folder_depth():
    """FR-003 AC5, stated as the property rather than as a string. A recipient sees WHAT was
    sent, not where it lived — so the two calls below, from a shallow and a deep source, are
    indistinguishable at the destination."""
    shallow = paths.destination_key("bob/", "alice", paths.item_name("alice/q1.csv"), "")
    deep = paths.destination_key(
        "bob/", "alice", paths.item_name("alice/deep/nested/q1.csv"), ""
    )

    assert shallow == deep == "bob/shared_files/alice/q1.csv"


def test_the_target_root_is_normalised():
    assert paths.destination_key("bob", "alice", "notes.txt", "") == (
        "bob/shared_files/alice/notes.txt"
    )


def test_two_senders_never_collide():
    """The whole point of namespacing the inbox by sender. Without it the second send silently
    lands beside the first and a recipient cannot tell whose file is whose."""
    assert paths.destination_key("bob/", "alice", "q1.csv", "") != paths.destination_key(
        "bob/", "carol", "q1.csv", ""
    )


@pytest.mark.parametrize(("root", "sender", "item"), [("", "alice", "q1.csv"), ("bob/", "", "q1.csv"), ("bob/", "alice", "")])
def test_a_destination_missing_any_part_of_its_identity_is_refused(root, sender, item):
    """Each omission folds the key up a level: an empty root reaches the bucket, an empty sender
    puts one person's files where the inbox itself belongs, an empty item name merges every send
    into one folder."""
    with pytest.raises(TerminalError) as caught:
        paths.destination_key(root, sender, item, "")

    assert caught.value.reason == "forbidden"


def test_the_inbox_prefix_is_the_destination_builders_own_base():
    """SPEC-166 FR-001. The conflict guard needs the prefix WITHOUT a key — it asks what names
    the inbox already holds — so the prefix is factored out rather than written a second time.
    Asserted as a relationship, not as two literals: every destination this plane can build must
    sit under the prefix its guard listed, or the guard is checking somewhere else."""
    prefix = paths.inbox_prefix("bob/", "alice")

    assert prefix.endswith("/")
    assert paths.destination_key("bob/", "alice", "reports", "2026/q1.csv").startswith(prefix)
    assert paths.destination_key("bob", "alice", "notes.txt", "").startswith(prefix)


@pytest.mark.parametrize(("root", "sender"), [("", "alice"), ("/", "alice"), ("bob/", "")])
def test_an_inbox_prefix_missing_part_of_its_identity_is_refused(root, sender):
    """Both omissions WIDEN the prefix, which is the dangerous direction for a listing: an empty
    sender lists every sender's inbox, and the guard would then refuse a name somebody else
    used."""
    with pytest.raises(TerminalError) as caught:
        paths.inbox_prefix(root, sender)

    assert caught.value.reason == "forbidden"


def test_the_inbox_folder_is_the_named_constant():
    """FR-003 AC4. A literal repeated across verbs is a layout that can drift one verb at a
    time, so the builder must be composing the constant rather than agreeing with it."""
    assert config.SHARED_FILES_FOLDER in paths.destination_key("bob/", "alice", "q1.csv", "")


# ── SPEC-165 FR-003 AC3: exactly one destination builder ─────────────────────

_LAMBDAS = pathlib.Path(__file__).resolve().parents[1]

#: The one module allowed to compose a destination key. Everything else must call it.
_BUILDER = _LAMBDAS / "file-send-common" / "fscommon" / "paths.py"


def _file_send_sources():
    """Every production module on this plane, excluding the builder itself and the tests."""
    for directory in sorted(_LAMBDAS.glob("file-send-*")):
        for path in sorted(directory.rglob("*.py")):
            if path.name.startswith("test_") or path == _BUILDER or "__pycache__" in path.parts:
                continue
            yield path


def _docstring_nodes(tree):
    """Every string Constant that IS a docstring, by identity.

    Identity, not shape: ``ast.walk`` yields an ``Expr`` and its ``Constant`` child separately,
    so skipping the ``Expr`` leaves the constant in the stream — which is how the first version
    of this sweep flagged two module docstrings that describe the layout. Only the FIRST
    statement of a module, class or function is a docstring; a bare string anywhere else is a
    no-op expression, and one holding the inbox folder is worth flagging.
    """
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _declaration_nodes(tree):
    """The single literal that DECLARES the constant, exempted by identity.

    ``config.SHARED_FILES_FOLDER = "shared_files"`` has to spell the folder out — that is the
    constant existing. Exempting that one assignment rather than the whole of ``config.py``
    keeps every other literal in that module under the sweep, which matters because config is
    exactly where a second layout constant would be tempting to add.
    """
    declared = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if any(isinstance(t, ast.Name) and t.id == "SHARED_FILES_FOLDER" for t in node.targets):
            declared.add(id(node.value))
    return declared


def _destination_builders(source: str):
    """Every place in ``source`` that composes a destination key rather than calling the builder.

    Two shapes, both caught by naming the inbox folder: a string constant holding
    ``shared_files``, and an f-string composing ``SHARED_FILES_FOLDER``. Neither is caught by
    the destination tests above, which only prove the ONE builder is right — a verb
    concatenating its own would pass every one of them while writing somewhere else.
    """
    tree = ast.parse(source)
    exempt = _docstring_nodes(tree) | _declaration_nodes(tree)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if config.SHARED_FILES_FOLDER in node.value and id(node) not in exempt:
                offenders.append(ast.unparse(node))
        elif isinstance(node, ast.JoinedStr) and "SHARED_FILES_FOLDER" in ast.unparse(node):
            offenders.append(ast.unparse(node))
    return offenders


def test_the_sweep_found_this_planes_modules():
    """Guards the guard: a glob that matches nothing makes the sweep below vacuous."""
    found = list(_file_send_sources())

    assert len(found) >= 8, f"only swept {[p.name for p in found]}"
    assert _BUILDER.exists()


@pytest.mark.parametrize("path", list(_file_send_sources()), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_no_verb_builds_a_destination_key_of_its_own(path):
    """FR-003 AC3, as a sweep rather than a convention."""
    offenders = _destination_builders(path.read_text())

    assert not offenders, (
        f"{path.parent.name}/{path.name} composes a destination key of its own ({offenders}) — "
        f"call fscommon.paths.destination_key instead, or the layout drifts one verb at a time"
    )


@pytest.mark.parametrize(
    "violation",
    [
        'key = f"{root}shared_files/{sender}/{item}"',
        'PREFIX = "shared_files"',
        'SHARED_FILES_FOLDER = "shared_files"\nOTHER = "shared_files"',
        'key = f"{root}{SHARED_FILES_FOLDER}/{sender}"',
        'def f():\n    "doc"\n    return "shared_files/" + sender',
    ],
)
def test_the_builder_sweep_fires_on_a_real_violation(violation):
    """Two empty results are equal, so a check that could never fire passes everywhere. Verified
    against deliberate violations rather than trusted — including one placed AFTER a docstring,
    which is where an identity-based exemption could have gone wrong in the other direction."""
    assert _destination_builders(violation)


@pytest.mark.parametrize(
    "documented",
    [
        '"""Writes to {target}shared_files/{sender}/."""',
        'def f():\n    """Lands under shared_files/."""\n    return 1',
        'class C:\n    """Owns the shared_files layout."""',
    ],
)
def test_a_docstring_naming_the_layout_is_not_flagged(documented):
    """The other direction, and the one that matters more: an exemption that swallowed a real
    builder would be worse than no sweep, but a sweep that flagged every doc comment would be
    turned off within a week."""
    assert not _destination_builders(documented)
