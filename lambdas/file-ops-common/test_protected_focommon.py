"""The portal's own folders, refused per (side x operation) and never by a union.

The browser enforces all of this today and nothing else does. These tests are the server side of
that pair, and two of them exist specifically to fail if someone "tidies" the three divergent
lists into one.
"""

import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from focommon import config, protected

_BROWSER = (
    pathlib.Path(__file__).resolve().parents[2]
    / "apps"
    / "portal"
    / "src"
    / "features"
    / "file-browser"
)


def _ts_list(source: str, name: str) -> list:
    """Reads one exported string-array constant out of a TypeScript source file.

    Args:
      source: The file's text.
      name: The exported constant's name.

    Returns:
      The list's string members, in order.

    Raises:
      AssertionError: If the constant is not found, which means the browser renamed it and this
        cross-runtime check has silently stopped comparing anything.
    """
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.DOTALL)
    assert match, f"{name} not found — the browser's list was renamed and this test went blind"
    return re.findall(r"'([^']+)'", match.group(1))


# ── The lists agree across the two runtimes ──────────────────────────────────


def test_the_folder_lists_match_the_browsers():
    """Python and TypeScript cannot share a list, so this is the only thing keeping the two
    runtimes' answers the same. Without it the plane and the browser drift one folder at a time,
    and the drift shows up as a request the browser would never send being accepted."""
    source = (_BROWSER / "protectedFolders.ts").read_text()

    assert _ts_list(source, "PICKER_LOCKED_FOLDERS") == list(config.PICKER_LOCKED_FOLDERS)
    assert _ts_list(source, "UNDELETABLE_ROOT_FOLDERS") == list(config.UNDELETABLE_ROOT_FOLDERS)


def test_the_archive_folder_name_matches_the_browsers_write_lock():
    """The bucket asymmetry lives in a DIFFERENT browser file from the lists — it is a rule about
    the prefix the user is standing in, not about a folder's name at a root — so this reads
    ``writeLockedPrefix.ts`` rather than the lists file. Reading the wrong one would compare
    nothing.

    Note there is no browser predicate for ``athenaresults/`` at any depth: that half of the source
    rule has no counterpart here and is held against the rendered IAM instead.
    """
    source = (_BROWSER / "writeLockedPrefix.ts").read_text()

    assert "ARCHIVE_FOLDER" in source
    assert "spaceKind !== 'shared'" in source, (
        "the browser's archive rule is no longer bucket-asymmetric — this plane mirrors it, so "
        "the two must move together"
    )


# ── As a destination ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", config.PICKER_LOCKED_FOLDERS)
def test_every_picker_locked_folder_is_refused_as_a_destination(folder):
    """Including the two a folder-name list tends to omit — ``_data-quality-reports`` and
    ``shared_tables`` — whose absence would let this plane accept a destination the browser's own
    picker refuses."""
    refusal = protected.destination_refusal("alice/", f"alice/{folder}/", "personal")

    assert refusal is not None
    assert folder in refusal.detail


def test_an_ordinary_destination_is_allowed():
    assert protected.destination_refusal("alice/", "alice/reports/2026/", "personal") is None


def test_a_nested_folder_sharing_a_locked_name_is_ordinary():
    """The picker rule is anchored at the SPACE root, so a user's own ``alice/backups/archive/``
    is a normal folder in the personal bucket."""
    assert protected.destination_refusal("alice/", "alice/backups/shared_tables/", "personal") is None


def test_the_archive_destination_rule_is_MIRRORED_not_averaged():
    """Root-anchored in a personal space, any depth in a shared one — because that is what each
    bucket's own Deny says. Anchoring both at the root would offer a destination IAM refuses;
    applying any-depth to both would refuse a personal folder IAM permits writing."""
    assert protected.destination_refusal("alice/", "alice/backups/archive/", "personal") is None
    assert protected.destination_refusal("sales/", "sales/backups/archive/", "shared") is not None


# ── As a source ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("operation", ["delete", "move"])
@pytest.mark.parametrize("folder", config.UNDELETABLE_ROOT_FOLDERS)
def test_every_undeletable_root_folder_is_refused_as_a_delete_or_move_source(operation, folder):
    refusal = protected.source_refusal("alice/", f"alice/{folder}/", operation, "personal")

    assert refusal is not None
    assert refusal.reason == "source_folder_undeletable"


def test_saved_queries_contents_are_ORDINARY_and_the_other_twos_are_not():
    """"The folder itself, never its contents" is true for ``saved_queries/`` ALONE.

    Its contents are deliberately ordinary — visible, deletable, a valid destination. But the role
    policy denies deletes beneath ``athenaresults/`` and IAM denies writes and deletes beneath
    ``archive/``, so accepting those would mean the plane takes requests its own IAM refuses
    mid-operation.
    """
    assert protected.source_refusal("alice/", "alice/saved_queries/q.sql", "delete", "personal") is None
    assert protected.source_refusal("alice/", "alice/athenaresults/r.csv", "delete", "personal") is not None
    assert protected.source_refusal("alice/", "alice/archive/2026/receipt.json", "delete", "personal") is not None


def test_COPYING_OUT_OF_a_protected_folder_stays_allowed():
    """``athenaresults/`` is picker-locked and undeletable and copying out of it works in the
    browser today. Refusing it here would silently remove a working capability, and doing it by
    folder name would be exactly the union the browser's own note forbids.

    This is the test that fails if the three lists are ever collapsed into one.
    """
    for key in ("alice/athenaresults/r.csv", "alice/athenaresults/", "alice/archive/2026/x.json"):
        assert protected.source_refusal("alice/", key, "copy", "personal") is None


def test_the_ATHENARESULTS_source_rule_carries_the_asymmetry_too():
    """The rule that was wrong, and the input the spec names verbatim.

    ``alice/reports/athenaresults/x`` is an ordinary user folder: the personal Deny is
    ``{bucket}/{principalTag}/athenaresults/*``, root-anchored, so IAM permits deleting it and the
    browser offers it. The shared Deny is ``{bucket}/*/athenaresults/*`` and an S3 wildcard matches
    ``/``, so the same key in a shared space is denied at any depth.

    Applying the shared rule to both refuses a delete the browser and IAM both allow — which is the
    "averaging removes working capability" failure, arrived at by hard-coding one bucket's kind.
    """
    assert protected.source_refusal("alice/", "alice/reports/athenaresults/x.csv", "delete", "personal") is None
    assert protected.source_refusal("sales/", "sales/reports/athenaresults/x.csv", "delete", "shared") is not None
    assert protected.source_refusal("alice/", "alice/athenaresults/x.csv", "delete", "personal") is not None


@pytest.mark.parametrize("folder", config.PICKER_LOCKED_FOLDERS)
def test_a_destination_BENEATH_a_locked_folder_is_refused_too(folder):
    """The browser's picker filters locked folders out of the navigable list, so a user can never
    enter one and never target a descendant. A root-only rule here accepts a destination the picker
    makes unreachable — and for ``shared_tables/`` the harm is concrete: a table's files acquiring
    neighbours is how a later projection read starts returning rows nobody wrote."""
    assert protected.destination_refusal("alice/", f"alice/{folder}/sub/deeper/", "personal") is not None


def test_a_FILE_named_like_a_protected_folder_is_not_that_folder():
    """``alice/archive`` — an extension-less file — is matched by no bucket Deny, and the browser
    only ever asks this of a folder. Treating it as one refuses a delete both permit."""
    assert protected.source_refusal("alice/", "alice/archive", "delete", "personal") is None
    assert protected.source_refusal("alice/", "alice/saved_queries", "delete", "personal") is None
    assert protected.source_refusal("alice/", "alice/archive/", "delete", "personal") is not None


@pytest.mark.parametrize("operation", ["copy", "move", "delete"])
def test_the_marker_is_refused_for_EVERY_operation_including_copy(operation):
    """The one place a copy is not free on this plane, and the reason is asymmetric to every other
    rule: copying a marker MINTS A NEW PERMANENTLY UNDELETABLE OBJECT, because both bucket policies
    deny deleting the basename at any depth. Elsewhere a copy takes nothing away; here it leaves
    litter no user and no plane can remove."""
    assert protected.marker_refusal(f"alice/reports/{config.MARKER_BASENAME}") is not None


def test_the_source_rule_carries_the_SAME_bucket_asymmetry_as_the_destination_rule():
    """It is the same predicate asked from the other side, so it must not be simplified to
    "at any depth" for both: in the personal bucket the prefix IS the principal tag, so
    ``alice/backups/archive/x`` is an ordinary user file IAM permits deleting."""
    assert protected.source_refusal("alice/", "alice/backups/archive/x", "delete", "personal") is None
    assert protected.source_refusal("sales/", "sales/backups/archive/x", "delete", "shared") is not None


@pytest.mark.parametrize("operation", ["copy", "move", "delete"])
def test_the_settings_folder_is_refused_as_a_source_for_EVERY_operation(operation):
    """Stated as this plane's own rule rather than by list membership: ``user_settings`` is hidden
    and picker-locked but deliberately NOT undeletable, so no existing list reaches it. Hiding is
    not enforcement, and this plane accepts a hand-crafted envelope."""
    refusal = protected.settings_source_refusal("alice/", f"alice/{config.USER_SETTINGS_FOLDER}/x.json")

    assert refusal is not None
    assert refusal.reason == "settings_folder_not_a_source"


def test_the_marker_is_refused_by_BASENAME_at_any_depth():
    """Both bucket policies deny it by name at any depth and an S3 wildcard matches ``/``, so a
    selected marker can only ever fail."""
    assert protected.marker_refusal(f"alice/a/b/{config.MARKER_BASENAME}") is not None
    assert protected.marker_refusal("alice/a/b/notes.txt") is None


def test_every_refusal_carries_its_own_reason_code():
    """One distinct code per rule, so the notifier can word it without re-deriving which rule
    fired — and so a later spec cannot collapse them all into one outcome and lose the signal."""
    reasons = {
        protected.destination_refusal("alice/", "alice/athenaresults/", "personal").reason,
        protected.destination_refusal("sales/", "sales/deep/archive/", "shared").reason,
        protected.source_refusal("alice/", "alice/saved_queries/", "delete", "personal").reason,
        protected.source_refusal("alice/", "alice/athenaresults/r.csv", "delete", "personal").reason,
        protected.source_refusal("alice/", "alice/archive/r.json", "delete", "personal").reason,
        protected.settings_source_refusal("alice/", "alice/user_settings/x").reason,
        protected.marker_refusal(f"alice/{config.MARKER_BASENAME}").reason,
    }

    assert len(reasons) == 7
