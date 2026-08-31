"""The membership index, and the sweep that keeps its writer list complete.

Two kinds of check live here and they fail for different reasons. The behavioural ones drive the
module against the plane's fakes. The **enumeration** one walks the verb tree and derives which
verbs move a Cognito membership slot, so a seventh such verb cannot be added with no index write
— a review samples, and what is wanted for an "is anything missing" question is a sweep. What it
does NOT catch is a verb that changes a roster by some other mechanism entirely; that would be
invisible to it, and the narrowing is stated rather than left to be discovered.

The population is derived from the two functions that move a Cognito membership slot, because a
session tag is built from those slots today: a verb that assigns or clears one has changed what its
subject may reach, and the index has to say the same thing. That is exactly six verbs today, and
``acknowledge-membership`` falls out by construction rather than by name — it calls neither,
because access is granted at add time.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda tree.
  VERB_GLOB: The directories the sweep walks.
  LAYER_DIRECTORY: The layer beside the verbs, excluded because it is where the slot functions are
    DEFINED. Left in, it would join the population the day a helper there named one.
  SLOT_MODULE: The module owning the Cognito slots.
  SLOT_FUNCTIONS: The two calls that move one.
  INDEX_MODULE: The module a membership-changing verb must also write through.
  EXPECTED_WRITERS: The six verbs as they stand, pinned so a verb LEAVING the population is as
    loud as one joining it — a verb that stops calling the slot functions has not stopped changing
    membership, it has moved to some other mechanism, and this file needs to hear about it.
  ADMIN: The admin bucket the fakes install.
"""

import ast
import inspect
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
VERB_GLOB = "shared-space-*"
LAYER_DIRECTORY = "shared-space-common"
SLOT_MODULE = "membership"
SLOT_FUNCTIONS = frozenset({"assign_or_find_slot", "clear_slot"})
INDEX_MODULE = "membership_index"
ADMIN = "admin-bkt"

EXPECTED_WRITERS = {
    "shared-space-add-members",
    "shared-space-create",
    "shared-space-delete",
    "shared-space-forget",
    "shared-space-leave",
    "shared-space-remove-members",
}

sys.path.insert(0, str(LAMBDAS / LAYER_DIRECTORY))

import membership_index as index
from cpcommon.cas import CasExhausted
from fakes import FakeClientError, install

# ── The sweep ─────────────────────────────────────────────────────────────────


def _verb_modules():
    """Every production module under a shared-space VERB directory.

    Args:
      None.

    Returns:
      An iterator of ``(directory name, parsed module)`` pairs.

    Raises:
      None.
    """
    for path in sorted(LAMBDAS.glob(f"{VERB_GLOB}/*.py")):
        directory = path.parent.name
        if directory == LAYER_DIRECTORY or path.name.startswith(("test_", "conftest.")):
            continue
        yield directory, ast.parse(path.read_text(encoding="utf-8"))


def _reaches(tree, module, functions):
    """Whether a module calls one of ``functions`` from ``module``, in either import spelling.

    Both spellings are counted deliberately. ``import membership`` followed by
    ``membership.clear_slot(...)`` is what every verb writes today, and a scan for that shape
    alone is blind to ``from membership import clear_slot`` — the mirror of an undercount this
    repo has already paid for once, in the other direction.

    Args:
      tree: The parsed module.
      module: The module the names would come from.
      functions: The function names of interest.

    Returns:
      True when the module reaches one of them.

    Raises:
      None.
    """
    aliases, direct = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == module}
        if isinstance(node, ast.ImportFrom) and (node.module or "") == module:
            direct |= {a.asname or a.name for a in node.names if a.name in functions}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in functions
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            return True
        if isinstance(node, ast.Name) and node.id in direct:
            return True
    return False


def index_writes():
    """The index module's own public writers, read off the module rather than listed.

    A listed set would go stale the day a fifth writer is added and the sweep would keep vouching
    for verbs that call none of them.

    **Functions only, and that is not tidiness.** The module's public surface also carries its
    exception class, and a verb that merely names it in an ``except`` clause — with the write
    forgotten — would satisfy a sweep looking for any public callable. That is precisely the shape
    a seventh verb is likeliest to be written in.

    Args:
      None.

    Returns:
      The public function names this module defines.

    Raises:
      None.
    """
    return frozenset(
        name
        for name in dir(index)
        if not name.startswith("_")
        and inspect.isfunction(getattr(index, name))
        and getattr(index, name).__module__ == INDEX_MODULE
    )


def _by_directory():
    """The verb modules grouped by directory, so a directory holding two is not collapsed.

    Every verb directory holds exactly one production module today, and a dict comprehension over
    the pairs would silently keep only the last of any that did not — which is the shape a helper
    module added beside a verb would take.

    Args:
      None.

    Returns:
      Directory name to the list of parsed modules in it.

    Raises:
      None.
    """
    grouped: dict[str, list] = {}
    for directory, tree in _verb_modules():
        grouped.setdefault(directory, []).append(tree)
    return grouped


def membership_changing_verbs():
    """Every verb directory that moves a Cognito membership slot.

    Args:
      None.

    Returns:
      The set of directory names.

    Raises:
      None.
    """
    return {
        directory
        for directory, trees in _by_directory().items()
        if any(_reaches(tree, SLOT_MODULE, SLOT_FUNCTIONS) for tree in trees)
    }


def test_the_sweep_still_finds_the_verbs_it_was_written_against():
    """Guard the guard: a population that collapsed reads as a clean pass.

    Pinned in BOTH directions. A verb joining the population with no index write is the failure
    this file exists to catch; a verb leaving it silently is how the file comes to check nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derived population is not the six expected verbs.
    """
    assert membership_changing_verbs() == EXPECTED_WRITERS

    writes = index_writes()
    assert writes, "the index module exposes no writer — the sweep below has nothing to look for"
    assert {"record", "drop"} <= writes
    assert "MembershipIndexUnreadable" not in writes, (
        "the exception class is a public callable of this module, and a verb naming it in an "
        "except clause with the write forgotten would read as covered"
    )


def test_every_membership_changing_verb_also_writes_the_index():
    """A verb that moves a slot and not the index leaves a session's tags disagreeing.

    Under the claims source that is invisible, because the tags come from the slot. Under the
    index source it is an entitlement that outlives the membership, or one that never arrives —
    and either way the verb is green, the roster is right, and nothing says so.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a membership-changing verb writes no index.
    """
    writes = index_writes()
    grouped = _by_directory()
    missing = sorted(
        directory
        for directory in membership_changing_verbs()
        if not any(_reaches(tree, INDEX_MODULE, writes) for tree in grouped[directory])
    )
    assert missing == [], (
        f"{missing} move a Cognito membership slot and write no membership index. The tag set a "
        "session carries and the index it is built from would then disagree, silently"
    )


def test_acknowledge_membership_is_excluded_by_construction_not_by_name():
    """The one verb correctly outside the population, and the reason is checkable.

    Acknowledging is display-only: access is granted at add time, so the verb moves no slot. If it
    ever does, it joins the population automatically — which is the difference between a derived
    set and a hand-kept exemption.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If it is in the population, or if it has stopped existing.
    """
    assert "shared-space-acknowledge-membership" in _by_directory()
    assert "shared-space-acknowledge-membership" not in membership_changing_verbs()


# ── The document ──────────────────────────────────────────────────────────────


def _stored(username):
    """Reads one index document out of the fake bucket.

    Args:
      username: The index owner.

    Returns:
      The parsed document.

    Raises:
      KeyError: If nothing was written for that user.
    """
    return json.loads(index.clients.s3().store[(ADMIN, f"memberships/{username}.json")])


def test_a_first_record_creates_the_document_conditionally():
    """The happy path, and the shape every reader is written against.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the document is absent or malformed.
    """
    install()
    index.record("bob", "sales", "active")

    document = _stored("bob")
    assert document["version"] == index.SCHEMA_VERSION
    assert document["username"] == "bob"
    assert document["spaces"] == [{"name": "sales", "status": "active"}]
    assert document["updatedAt"]


def test_a_second_space_is_added_and_a_repeat_replaces_rather_than_duplicates():
    """Entries are keyed by name, so a replayed verb does not double an entitlement.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a repeat duplicates the entry.
    """
    install()
    index.record("bob", "sales", "active")
    index.record("bob", "finance", "active")
    index.record("bob", "sales", "active")

    names = [entry["name"] for entry in _stored("bob")["spaces"]]
    assert sorted(names) == ["finance", "sales"]


def test_a_drop_leaves_an_empty_list_and_never_deletes_the_object():
    """A user who leaves their last space holds an empty index, not no index.

    A deleted document and a user who was never a member are indistinguishable, and one of those
    is reached by a path allowed to fail.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the object is removed.
    """
    s3, _glue, _lf, _cognito = install()
    index.record("bob", "sales", "active")
    index.drop("bob", "sales")

    assert (ADMIN, "memberships/bob.json") in s3.store
    assert _stored("bob")["spaces"] == []


def test_dropping_a_space_the_index_does_not_name_writes_nothing():
    """A true no-op, so a replayed removal does not churn the object.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a write happened.
    """
    s3, _glue, _lf, _cognito = install()
    index.drop("bob", "sales")

    assert (ADMIN, "memberships/bob.json") not in s3.store


def test_a_losing_write_retries_against_the_freshly_read_document():
    """Compare-and-swap, driven rather than assumed.

    Two executions can touch one user's index — the Pipe is fire-and-forget — so a plain
    read-then-write loses one of two concurrent adds. The conflicting writer here commits
    ``finance`` between this caller's read and its write; the retry must carry both names, not
    just its own.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the conflicting write is lost.
    """
    s3, _glue, _lf, _cognito = install()
    index.record("bob", "sales", "active")

    original = s3.put_object
    fired = []

    def put_once_conflicting(**kwargs):
        """Commits a competing write before the first attempt, then behaves normally."""
        if not fired:
            fired.append(True)
            s3.put_object = original
            index.record("bob", "finance", "active")
            s3.put_object = put_once_conflicting
            raise FakeClientError("PreconditionFailed")
        return original(**kwargs)

    s3.put_object = put_once_conflicting
    index.record("bob", "legal", "active")
    s3.put_object = original

    names = sorted(entry["name"] for entry in _stored("bob")["spaces"])
    assert names == ["finance", "legal", "sales"]


def test_an_exhausted_compare_and_swap_raises_rather_than_giving_up_quietly():
    """The index is an authorization input, so a write that did not land must fail the run.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the exhaustion is swallowed.
    """
    s3, _glue, _lf, _cognito = install()

    def always_conflict(**kwargs):
        """Refuses every write on its precondition."""
        raise FakeClientError("PreconditionFailed")

    s3.put_object = always_conflict
    with pytest.raises(CasExhausted, match="membership-index/bob"):
        index.record("bob", "sales", "active")


def test_a_denial_is_not_read_as_absence():
    """The one tolerance ``cache.py`` takes and this module must not.

    A denied read treated as absence would overwrite a real index with an empty one — and the
    write that follows is create-if-absent, so it would fail rather than corrupt only because the
    object exists. What actually protects the caller is that the denial rises.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the denial takes the absent branch.
    """
    s3, _glue, _lf, _cognito = install()

    def denied(**kwargs):
        """Refuses every read the way S3 does for a caller that cannot list."""
        raise FakeClientError("AccessDenied")

    s3.get_object = denied
    with pytest.raises(FakeClientError, match="AccessDenied"):
        index.record("bob", "sales", "active")


def test_an_unreadable_document_is_refused_by_its_own_type():
    """Malformed is not absent, and the two must not share a branch.

    Asserted by the exception's own type AND by which refusal fired. The three share a type, so
    matching on the username alone would let one fixture be caught by a neighbour's branch — the
    ``ValueError`` ``json.loads`` raises unaided would satisfy a check for any exception, and a
    version check that had stopped running would be covered by the parse check beside it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an unreadable document is treated as a fresh one.
    """
    s3, _glue, _lf, _cognito = install()

    refusals = {
        b"{ not json": "does not parse",
        json.dumps({"version": 99, "spaces": []}).encode(): "unknown schema",
        json.dumps({"version": 1, "spaces": {"sales": "active"}}).encode(): "no space list",
    }
    for body, reason in refusals.items():
        s3.store[(ADMIN, "memberships/bob.json")] = body
        with pytest.raises(index.MembershipIndexUnreadable, match=reason):
            index.record("bob", "sales", "active")


def test_a_fan_out_failure_names_the_member_and_the_space_before_it_raises():
    """The record is what says WHICH member's index is wrong.

    The notifier downstream is handed the execution's error and never the member, so without this
    a failed run says a space's membership write failed and not whose.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the failure is swallowed, or recorded without the member.
    """
    s3, _glue, _lf, _cognito = install()
    recorded = []
    original = index.observability.error
    index.observability.error = lambda message, **fields: recorded.append((message, fields))

    def denied(**kwargs):
        """Refuses every read."""
        raise FakeClientError("AccessDenied")

    s3.get_object = denied
    try:
        with pytest.raises(FakeClientError, match="AccessDenied"):
            index.record_for_all(["bob", "carol"], "sales", "active")
    finally:
        index.observability.error = original

    assert len(recorded) == 1, "the fan-out must stop at the first failure, not sweep on"
    _message, fields = recorded[0]
    assert fields["member"] == "bob"
    assert fields["space"] == "sales"
    assert fields["reason"] == index.REASON_WRITE_FAILED
