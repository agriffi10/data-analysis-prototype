"""The fixture corpus for the PR queue's ``pre-push`` gate.

Why this exists. The hook decides whether a push reaches the remote, and every way it can go wrong
is silent: a pattern that stops matching, a check that stops firing, a fail-open that swallows a
refusal. A queue enforcing nothing looks exactly like a queue enforcing everything — which is not
hypothetical, because the first deployment of this hook enforced the branch prefixes of five specs,
those specs closed, and it then exited 0 for every branch anyone pushed while still looking
installed. Nothing noticed, because there was nothing to notice with.

The hook refuses two things. A push of a participating branch by a session that does not hold the
lock, and a push whose commits do not contain the remote's current trunk — the base went stale
while the session waited for the lock, which is exactly when peers merge. The second refusal reads
the remote with ``ls-remote`` and never fetches, so the fixture here has to be a real repository
with a real bare origin: the cases set the remote's trunk to a commit the pushed one does or does
not contain, and the hook is executed against it.

How it works. Each case builds a throwaway checkout with two commits, a bare origin holding the
first of them, runs ``install.sh`` into a throwaway queue beside it, sets the queue's and the
origin's state, and executes the hook the way git does: argv of remote name and remote URL, and
the refs on stdin. The only pushes here go into the throwaway bare repositories while the fixture
is built, before the hook exists; nothing here touches a real queue or a real remote.

It drives the WRAPPER in ``.git/hooks``, not the hook file directly, and that is load-bearing
rather than incidental. ``pre-push`` lives inside the queue directory, so a deleted queue deletes
the hook too and its own ``[ -d "$Q" ]`` guard can never run; the wrapper's exec-if-present is what
actually lets a push through when the queue is gone. Driving the hook directly would leave the
first thing this gate promises asserted nowhere, and the fixture for it would pass vacuously.

Cases whose name ends ``_ok`` assert SILENCE — exit 0 and not one byte on stderr. Half of what a
gate gets wrong is refusing something legitimate, and a corpus of only-refusals cannot see it.
Every refusal asserts the REASON, not only the exit status: a stale base and a missing lock both
exit 1, and a push refused for the wrong reason is "fixed" by changing the wrong thing.

The mutation sweep is the other half. Every check in the hook is broken in turn, in a copy, and
each plant DECLARES the cases it must break — reddening somewhere is not reddening in the right
place, and a plant that also happens to break a neighbour would otherwise satisfy a sweep while
leaving its own fixture vacuous. Each plant also asserts its substitution landed exactly once: an
edit that silently matched nothing reads identically to a guard that was already dead.

One thing this corpus cannot cover, said out loud rather than left to be discovered: CI runs it on
GNU ``grep`` and ``awk`` while the hook it guards only ever executes on the developer's machine.
A green run here is not evidence about the deployed hook's ``grep``. ``scripts/pr-queue-test.sh``
is the same corpus driven through real ``git push`` invocations, for the developer's machine.

Usage: ``python3 scripts/pr-queue/pre_push_test.py`` — takes no arguments, imports nothing outside
the standard library, and exits non-zero if any case does not behave as declared.

Attributes:
  QUEUE_SRC: The directory the hook and installer are taken from — this file's own.
  ZERO: The all-zero object git supplies for a deletion.
  BASE: The sentinel a case's stdin carries for the fixture's first commit, the one the origin's
    trunk starts at. Rendered to the real sha when the case runs.
  WORK: The sentinel for the second commit, a child of ``BASE`` — what an ordinary push carries.
  REBASED: The sentinel for a commit built on top of a MOVED trunk, which only the ``rebased``
    base state produces. Rendered empty in every other state, so a case that uses it elsewhere
    fails loudly rather than pushing nothing.
  MOVED: The peer's commit the origin's trunk moved to, in the states that move it; ``MOVED7`` is
    its first seven characters, which the stale refusal prints so the reader knows which commit
    to look for. Both render empty elsewhere.
"""

import itertools
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

QUEUE_SRC = pathlib.Path(__file__).resolve().parent
ZERO = "0" * 40
BASE = "{BASE}"
WORK = "{WORK}"
REBASED = "{REBASED}"
MOVED = "{MOVED}"
MOVED7 = "{MOVED7}"

_peer_commits = itertools.count(1)


def push(local_ref: str, remote_ref: str, sha: str = WORK) -> str:
    """Render the stdin line git writes for a ref it is about to update.

    Args:
      local_ref: The local ref being pushed, as git spells it.
      remote_ref: The ref that will be updated on the remote.
      sha: The local object, as a sentinel the runner renders to a real commit.

    Returns:
      One stdin line, newline-terminated.

    Raises:
      None.
    """
    return f"{local_ref} {sha} {remote_ref} {ZERO}\n"


def delete(remote_ref: str) -> str:
    """Render the stdin line git writes for a ref it is about to delete.

    git supplies ``(delete)`` as the local ref and an all-zero local object for a deletion; both
    are documented, and the hook keys on the literal because the zero object's width depends on
    the repository's hash algorithm.

    Args:
      remote_ref: The ref that will be removed from the remote.

    Returns:
      One stdin line, newline-terminated.

    Raises:
      None.
    """
    return f"(delete) {ZERO} {remote_ref} {WORK}\n"


class Case(NamedTuple):
    """One fabricated push against one queue and origin state.

    Attributes:
      name: Identifies the case in the report. A ``_ok`` suffix asserts silence.
      stdin: The ref lines git would hand the hook, with sha sentinels.
      want_rc: The exit status the hook must produce.
      must_say: Substrings the hook's stderr must contain. Ignored for a silence case.
      must_not_say: Substrings the hook's stderr must NOT contain — the refusal that fired must
        not also claim a reason that does not apply. Ignored for a silence case.
      pattern: What to write to ``enforce-branches``; ``None`` removes the file entirely.
      holder: ``(spec, branch)`` for the lock, ``None`` for a free lock, or ``("", "")`` for a lock
        whose holder file is present but empty.
      queue: ``False`` moves the whole queue directory away before the push.
      remote: ``origin`` pushes to the configured origin, ``origin-respelled`` to the same
        repository with a trailing slash, ``origin-nosuffix`` to it through a path without the
        ``.git`` suffix, ``gone`` to a path that does not exist, and anything else to a foreign
        remote.
      trunk: What to write to ``main-branch``; ``None`` removes it. Anything but ``main`` proves the
        hook READ it, since ``main`` is also the hook's own fallback and a case using it cannot
        tell the two apart.
      pushurl: Sets ``remote.origin.pushurl`` to the origin or the foreign bare repo, or leaves it
        unset. The hook reads both spellings of origin and only this distinguishes them.
      origin: ``False`` removes the origin remote, so neither spelling can be read at all.
      fetch_from: ``frozen`` points origin's FETCH url at a bare repository whose trunk never
        moves, so a hook measuring against the fetch url and one measuring against the push url
        reach different verdicts.
      base: Where the origin's trunk stands relative to the commit being pushed. ``current`` — at
        ``BASE``, which ``WORK`` contains; ``stale`` — at a peer's commit ``WORK`` does not contain,
        fetched into the checkout; ``unfetched`` — the same, never fetched; ``rebased`` — the same
        peer commit, fetched, with ``REBASED`` built on top of it and the checkout's HEAD moved
        there; ``none`` — the origin has no branches at all; ``trunk-missing`` — the origin has a
        branch, but not the trunk the queue names.
      decoy: Adds a remote branch whose name ENDS in ``refs/heads/<trunk>``, which ``ls-remote``'s
        tail match returns beside the trunk itself.
      env: Extra environment for the hook.
    """

    name: str
    stdin: str
    want_rc: int
    must_say: tuple[str, ...] = ()
    must_not_say: tuple[str, ...] = ()
    pattern: str | None = "."
    holder: tuple[str, str] | None = None
    queue: bool = True
    remote: str = "origin"
    trunk: str | None = "main"
    pushurl: str | None = None
    origin: bool = True
    fetch_from: str = "origin"
    base: str = "current"
    decoy: bool = False
    env: dict[str, str] = {}  # noqa: RUF012


LOCK = "you do not hold the PR queue lock"
STALE = "your base is behind"
UNFETCHED = "never fetched that commit"
DROPS = "would drop every commit"

CASES: tuple[Case, ...] = (
    # ---- the lock ------------------------------------------------------------------------------
    # Every one asserts the branch is NAMED and the reason is the LOCK. A refusal that does not say
    # which ref it refused sends the reader to the bypass, and a stale base exits 1 exactly like
    # a missing lock.
    Case("refused_when_the_lock_is_free",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("PUSH REFUSED", LOCK, "spec-9/x", "Lock holder:   (free)")),
    # The refusal names the holder AND the recovery for a lock taken from the wrong directory —
    # the re-stamp, with the spec id `queue.sh` takes — rather than sending the reader to the
    # bypass.
    Case("refused_when_the_lock_is_held_on_another_branch",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (LOCK, "spec-9/x", "Lock holder:   OTHER-SPEC on spec-9/other",
          "acquire OTHER-SPEC", "re-stamps"),
         holder=("OTHER-SPEC", "spec-9/other")),
    # The holder's own branch appears in the message either way, so this asserts the whole
    # "Refused ref(s)" LINE rather than a substring: the claim is that the held ref was left out.
    Case("refused_names_only_the_ref_that_lacks_the_lock",
         push("refs/heads/spec-9/held", "refs/heads/spec-9/held")
         + push("refs/heads/spec-9/other", "refs/heads/spec-9/other"), 1,
         ("Refused ref(s): spec-9/other\n",),
         holder=("MINE", "spec-9/held")),
    Case("refused_when_the_holder_branch_is_a_prefix_of_the_pushed_one",
         push("refs/heads/spec-9/queue", "refs/heads/spec-9/queue"), 1,
         (LOCK, "spec-9/queue"),
         holder=("MINE", "spec-9/qu")),
    # ...and the other direction: a substring test passes either way round, and one case can only
    # see one of them.
    Case("refused_when_the_pushed_branch_is_a_prefix_of_the_holder",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (LOCK, "spec-9/x"),
         holder=("MINE", "spec-9/xyz")),
    # Keys on the REMOTE ref, which is the one that decides what appears on the remote. The local
    # side being the trunk is irrelevant, and a check written against it would pass this wrongly.
    Case("refused_when_the_trunk_is_pushed_onto_a_topic_branch",
         push("refs/heads/main", "refs/heads/topic"), 1, (LOCK, "topic")),
    # A lock whose holder file parses to nothing is NOT reported as free: the reader would go
    # looking for a race that is not happening, and the wait for the reaper can be indefinite.
    Case("refused_when_the_holder_file_parses_to_nothing",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (LOCK, "parses to nothing"), ("(free)",),
         holder=("", "")),
    # The lock is judged before the base, and must not be reported as staleness: both exit 1, and
    # the wrong reason sends the reader to rebase a branch whose real problem is the lock.
    Case("refused_for_the_lock_not_the_base_when_both_are_wrong",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (LOCK, "spec-9/x"), (STALE,),
         base="stale"),

    # ---- the bypass, which passes but is not silent -------------------------------------------
    Case("the_bypass_lets_the_push_through",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0,
         ("PR_QUEUE_BYPASS=1",),
         env={"PR_QUEUE_BYPASS": "1"}),

    # ---- silence ------------------------------------------------------------------------------
    Case("the_branch_holding_the_lock_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0,
         holder=("MINE", "spec-9/x")),
    Case("a_branch_outside_the_pattern_ok",
         push("refs/heads/docs/x", "refs/heads/docs/x"), 0, pattern="^spec-"),
    Case("an_empty_pattern_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0, pattern=""),
    Case("an_absent_pattern_file_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0, pattern=None),
    Case("an_absent_queue_directory_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0, queue=False),
    # The trunk needs no lock: merging is a push of the trunk, and a lock stamped with it would
    # cover nothing. A peer holds the lock on its own branch; the trunk still goes through.
    Case("the_trunk_ok",
         push("refs/heads/main", "refs/heads/main"), 0, holder=("PEER", "spec-9/z")),
    Case("a_branch_pushed_onto_the_trunk_ok",
         push("refs/heads/topic", "refs/heads/main"), 0),
    Case("a_tag_ok",
         push("refs/tags/v1", "refs/tags/v1"), 0),
    Case("a_remote_that_is_not_origin_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0, remote="elsewhere"),
    Case("a_push_with_no_refs_ok",
         "", 0),

    # ---- the trunk is READ, not assumed -------------------------------------------------------
    # `install.sh` writes `main` into a fixture whose origin HEAD says so, which is the same string
    # the hook falls back to. So every case above is blind to whether `main-branch` is read at
    # all: delete the read and they stay green. These two configure a trunk that is NOT the
    # fallback, and only a hook that reads the file gets both of them right. The second asserts
    # the REASON: under a hook that stopped reading the file, `main` is the trunk again and the
    # push is refused anyway — for a trunk the remote does not have — so an assertion on the ref
    # alone would stay green.
    Case("a_configured_trunk_that_is_not_the_default_ok",
         push("refs/heads/trunk", "refs/heads/trunk"), 0, trunk="trunk"),
    Case("refused_when_the_branch_is_only_the_default_trunk_name",
         push("refs/heads/main", "refs/heads/main"), 1, (LOCK, "main"), trunk="trunk"),
    # The fallback, which every case above reaches only when the file already says `main`.
    Case("an_absent_main_branch_file_still_exempts_the_trunk_ok",
         push("refs/heads/main", "refs/heads/main"), 0, trunk=None),

    # ---- which spelling of origin counts ------------------------------------------------------
    # Two URLs are read, and until these cases only one of them was exercised: a push to the
    # configured pushurl IS a push to origin, and exempting it would let the queue be walked
    # around by a setting nobody thinks of as a remote.
    Case("refused_when_pushing_to_the_configured_pushurl",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x"),
         remote="elsewhere", pushurl="elsewhere"),
    Case("refused_when_origin_is_spelled_with_a_trailing_slash",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x"),
         remote="origin-respelled"),
    # The other spelling the hook normalises. Losing this half is fail-OPEN — a session whose
    # origin is `…/repo.git` pushing to `…/repo` walks around the queue — and it was found by a
    # reviewer's plant that both corpora passed.
    Case("refused_when_origin_is_spelled_without_its_dot_git",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x"),
         remote="origin-nosuffix"),
    # A checkout whose origin cannot be read is enforced rather than exempted. The hook's comment
    # claims this; nothing asserted it, and the two directions look identical from outside.
    Case("refused_when_the_origin_cannot_be_read_at_all",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x"),
         remote="elsewhere", origin=False),

    # ---- the ref test reads the REMOTE ref ----------------------------------------------------
    # Both of these are silent-or-refused purely on which side of the refspec is inspected, so a
    # check moved from `$rref` to `$lref` — a defect no value-changing plant can produce — has to
    # get one of them wrong.
    Case("refused_when_a_detached_head_refspec_names_a_branch",
         push("HEAD", "refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x")),
    Case("a_branch_pushed_to_a_tag_ref_ok",
         push("refs/heads/v1", "refs/tags/v1"), 0),

    # A pattern grep cannot compile is not a pattern that matches nothing — grep exits 2, and
    # reading that as "no match" exempts every branch while `enforcing: spec-[` sits in the
    # summary looking configured. It is a refusal of its own, not a lock refusal in disguise.
    Case("refused_when_the_pattern_is_not_a_compilable_ere",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("not an ERE grep can compile", "spec-["), (LOCK,), pattern="spec-["),

    # Two refused refs, so the accumulator is asserted rather than just the first write to it.
    Case("refused_names_every_ref_that_lacks_the_lock",
         push("refs/heads/spec-9/a", "refs/heads/spec-9/a")
         + push("refs/heads/spec-9/b", "refs/heads/spec-9/b"), 1,
         ("Refused ref(s): spec-9/a spec-9/b\n",)),

    # ---- the base: FRESHNESS -------------------------------------------------------------------
    # The trunk moved and the checkout fetched it, so the object is present and the ancestry test
    # is what refuses — the defect this check was built for: rebase, wait out the queue, push
    # stale. The unfetched wording must not appear, because the remedy differs.
    Case("refused_when_the_base_is_behind_the_remote_trunk",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (STALE, "spec-9/x", f"is at {MOVED7}"), (UNFETCHED, LOCK),
         holder=("MINE", "spec-9/x"), base="stale"),
    # The trunk moved and the checkout never fetched it, so `merge-base` cannot answer and the
    # object test is what refuses. Same verdict, different check, and the message says which.
    Case("refused_when_the_remote_trunk_was_never_fetched",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (STALE, UNFETCHED, "spec-9/x"),
         holder=("MINE", "spec-9/x"), base="unfetched"),
    # The remedy the message prints actually clears the refusal.
    Case("a_branch_rebased_onto_the_moved_trunk_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x", REBASED), 0,
         holder=("MINE", "spec-9/x"), base="rebased"),
    # The check reads the sha BEING PUSHED, not HEAD. The checkout stands on the rebased commit
    # while the ref pushed is the stale one — every other case pushes the commit it stands on, so
    # substituting HEAD for the pushed sha passes the rest of this corpus.
    Case("refused_when_the_stale_branch_is_not_the_checked_out_one",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (STALE, "spec-9/x"),
         holder=("MINE", "spec-9/x"), base="rebased"),
    # EVIDENCE: a remote that cannot be read is never read as "your base is current". Origin is
    # repointed at the unreadable url too, because a url that is not origin's is exempt before it
    # is ever read.
    Case("refused_when_the_remote_cannot_be_read",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("could not read", "spec-9/x"), (STALE, LOCK),
         holder=("MINE", "spec-9/x"), remote="gone"),
    # A trunk the remote does not have is a MISCONFIGURED queue, not an empty repository. Reading
    # the one as the other silently disables the check for the whole repository.
    Case("refused_when_the_remote_has_no_such_trunk",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("has no branch named", "spec-9/x"), (STALE, LOCK),
         holder=("MINE", "spec-9/x"), base="trunk-missing"),
    # An origin with no branches at all has nothing to be behind. Distinguishes "no such ref"
    # (empty output, exit 0) from "the check failed" (non-zero) — conflating them refuses the
    # first push into an empty repository forever.
    Case("an_empty_remote_has_nothing_to_be_behind_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0,
         holder=("MINE", "spec-9/x"), base="none"),
    # `remote.origin.pushurl` makes the fetch url and the push target different repositories. The
    # base must be measured against the one being pushed to: the fetch url's trunk never moves,
    # the push url's has, and only a hook reading the push url refuses this.
    Case("refused_when_the_base_is_measured_against_the_pushurl",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         (STALE, "spec-9/x"),
         holder=("MINE", "spec-9/x"), fetch_from="frozen", pushurl="origin", base="stale"),
    # ls-remote matches a ref pattern by TAIL, so a branch named `decoy/refs/heads/main` answers a
    # query for `refs/heads/main`. Selecting the wrong line refuses a push whose base is current.
    Case("a_decoy_ref_on_the_remote_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0,
         holder=("MINE", "spec-9/x"), decoy=True),

    # ---- the base: the TRUNK is exempt from the lock, not from freshness ------------------------
    # A trunk pushed backwards over commits the remote has is a peer's work being dropped. The
    # ancestry test refuses it for the same reason it refuses a stale branch, with no lock in play.
    Case("refused_when_the_trunk_is_pushed_backwards",
         push("refs/heads/main", "refs/heads/main", BASE), 1,
         (STALE, "main"), (LOCK,),
         base="stale"),
    Case("the_trunk_fast_forwarded_over_a_moved_remote_ok",
         push("refs/heads/main", "refs/heads/main", REBASED), 0,
         base="rebased"),
    # Every stale ref is named, not the last one read. The trunk is the only second ref that can
    # be stale beside the holder's branch, since any other branch is refused for the lock first.
    Case("refused_names_every_stale_ref",
         push("refs/heads/main", "refs/heads/main", BASE)
         + push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("Stale ref(s): main spec-9/x\n",),
         holder=("MINE", "spec-9/x"), base="stale"),
    # The trunk's refusals run AHEAD of the pattern: a pattern narrowed to exclude the trunk must
    # not uncover it. Both pass silently if the pattern test comes first.
    Case("refused_when_the_trunk_is_pushed_backwards_outside_a_narrowed_pattern",
         push("refs/heads/main", "refs/heads/main", BASE), 1,
         (STALE, "main"),
         pattern="^spec-", base="stale"),
    Case("refused_when_the_trunk_is_deleted_outside_a_narrowed_pattern",
         delete("refs/heads/main"), 1, (DROPS, "main"), pattern="^spec-"),

    # ---- deletions: exempt from FRESHNESS, not from the lock ------------------------------------
    # A deletion carries no commit to measure, so the HOLDER may delete after the trunk moved:
    # refusing it would strand the branch cleanup that follows every merge.
    Case("the_holder_deletes_its_own_branch_after_the_trunk_moved_ok",
         delete("refs/heads/spec-9/x"), 0,
         holder=("MINE", "spec-9/x"), base="stale"),
    # But a non-holder deleting the branch under review closes the very PR the lock protects.
    Case("refused_when_a_non_holder_deletes_a_participating_branch",
         delete("refs/heads/spec-9/x"), 1, (LOCK, "spec-9/x", "Lock holder:   (free)")),
    # A deletion of the TRUNK is refused outright: no lock covers it, no commit measures it, and
    # it is the limit case of a trunk pushed backwards over a peer's work.
    Case("refused_when_the_trunk_is_deleted",
         delete("refs/heads/main"), 1, (DROPS, "main"), (LOCK,),
         holder=("MINE", "spec-9/x")),
)


class Plant(NamedTuple):
    """One mutation of the hook, and the cases it is required to break.

    Attributes:
      name: Identifies the plant in the report.
      old: The exact text to replace. Must occur once.
      new: What to replace it with.
      breaks: Case names that must fail once the plant is in. Every other case must still pass.
    """

    name: str
    old: str
    new: str
    breaks: tuple[str, ...]


# The silence cases that reach the hook's LAST decision — everything that did not exit earlier on
# an empty pattern, the bypass, a foreign remote or a missing queue.
SILENCE_AFTER_THE_LOOP = (
    "the_branch_holding_the_lock_ok", "a_branch_outside_the_pattern_ok", "the_trunk_ok",
    "a_branch_pushed_onto_the_trunk_ok", "a_tag_ok", "a_push_with_no_refs_ok",
    "a_configured_trunk_that_is_not_the_default_ok",
    "an_absent_main_branch_file_still_exempts_the_trunk_ok", "a_branch_pushed_to_a_tag_ref_ok",
    "a_branch_rebased_onto_the_moved_trunk_ok", "an_empty_remote_has_nothing_to_be_behind_ok",
    "a_decoy_ref_on_the_remote_ok", "the_trunk_fast_forwarded_over_a_moved_remote_ok",
    "the_holder_deletes_its_own_branch_after_the_trunk_moved_ok",
)

# Every refusal exits through the hook's one `exit 1`, so the plant that turns it into `exit 0`
# must break every case that expects a refusal. Derived from the cases rather than listed, and
# that is safe here because the sweep corrects it: a case that stops breaking is reported.
REFUSALS = tuple(case.name for case in CASES if case.want_rc == 1)

# The cases the lock's trunk exemption decides. Removing it sends the trunk through the pattern
# and the lock: every silent trunk push is refused for a lock it never needed, and every trunk
# refusal that runs ahead of the pattern — or beside a lock held on another branch — is refused
# for the wrong reason or not at all.
TRUNK_EXEMPTION = (
    "the_trunk_ok", "a_branch_pushed_onto_the_trunk_ok",
    "a_configured_trunk_that_is_not_the_default_ok",
    "an_absent_main_branch_file_still_exempts_the_trunk_ok",
    "the_trunk_fast_forwarded_over_a_moved_remote_ok",
    "refused_when_the_trunk_is_pushed_backwards",
    "refused_when_the_trunk_is_pushed_backwards_outside_a_narrowed_pattern",
    "refused_when_the_trunk_is_deleted", "refused_when_the_trunk_is_deleted_outside_a_narrowed_pattern",
    "refused_names_every_stale_ref",
)

PLANTS: tuple[Plant, ...] = (
    Plant("the_empty_pattern_fail_open",
          '[ -n "$PATTERN" ] || exit 0', '[ -n "$PATTERN" ] || :',
          ("an_empty_pattern_ok", "an_absent_pattern_file_ok")),
    Plant("the_bypass",
          '[ "${PR_QUEUE_BYPASS:-}" = "1" ]', '[ "${PR_QUEUE_BYPASS:-}" = "not-1" ]',
          ("the_bypass_lets_the_push_through",)),
    Plant("the_origin_scoping",
          '[ "$matched" = 1 ] || exit 0', '[ "$matched" = 1 ] || :',
          ("a_remote_that_is_not_origin_ok",)),
    Plant("the_tag_exemption",
          "case \"$rref\" in refs/heads/*)", 'case "$rref" in *)',
          ("a_tag_ok", "a_branch_pushed_to_a_tag_ref_ok")),
    # The deletion's exemption from FRESHNESS. Without it the holder's cleanup after a merge is
    # measured against an all-zero object and refused as stale.
    Plant("the_deletion_freshness_exemption",
          '[ "$lref" = "(delete)" ] && continue', '[ "$lref" = "(nope)" ] && continue',
          ("the_holder_deletes_its_own_branch_after_the_trunk_moved_ok",)),
    # The deletion's NON-exemption from the lock: a plant that lets a deletion skip the lock test
    # opens the branch under review to any session.
    Plant("the_lock_on_a_deletion",
          'if [ "$branch" != "$holder_branch" ]; then',
          'if [ "$branch" != "$holder_branch" ] && [ "$lref" != "(delete)" ]; then',
          ("refused_when_a_non_holder_deletes_a_participating_branch",)),
    Plant("the_trunk_exemption",
          'if [ "$branch" = "$MAIN" ]; then', "if false; then",
          TRUNK_EXEMPTION),
    # A hook that stops reading the pattern also stops seeing an uncompilable one, so that case is
    # refused for the lock instead and breaks here too.
    Plant("the_participation_test",
          'echo "$branch" | grep -qE "$PATTERN"', 'echo "$branch" | grep -qE ""',
          ("a_branch_outside_the_pattern_ok", "refused_when_the_pattern_is_not_a_compilable_ere")),
    # grep answers 2 for a pattern it cannot compile, and reading that as "no match" is what turns
    # one bad character in a config file into a queue that enforces nothing.
    Plant("a_pattern_grep_cannot_compile_fails_closed",
          "*) badpat=1; continue ;;", "*) continue ;;",
          ("refused_when_the_pattern_is_not_a_compilable_ere",)),
    Plant("the_holder_comparison",
          'if [ "$branch" != "$holder_branch" ]; then', 'if [ -z "$holder_branch" ]; then',
          ("refused_when_the_lock_is_held_on_another_branch",
           "refused_names_only_the_ref_that_lacks_the_lock",
           "refused_when_the_holder_branch_is_a_prefix_of_the_pushed_one",
           "refused_when_the_pushed_branch_is_a_prefix_of_the_holder")),
    Plant("the_nothing_to_refuse_exit",
          '|| [ "$badpat" -eq 1 ] || exit 0', '|| [ "$badpat" -eq 1 ] || :',
          SILENCE_AFTER_THE_LOOP),
    Plant("the_refusal_itself", "\nexit 1\n", "\nexit 0\n", REFUSALS),
    # The read, not the exemption. Deleting it leaves the fallback, which every other trunk case
    # agrees with — so only the two cases that configure a different trunk can see this one go.
    Plant("the_configured_trunk_is_read",
          'MAIN="$(cat "$Q/main-branch" 2>/dev/null)"', 'MAIN=""',
          ("a_configured_trunk_that_is_not_the_default_ok",
           "refused_when_the_branch_is_only_the_default_trunk_name")),
    Plant("the_trunk_fallback",
          '[ -n "$MAIN" ] || MAIN=main', ":",
          ("an_absent_main_branch_file_still_exempts_the_trunk_ok",)),

    # The five below break a check by moving it to the WRONG VARIABLE or by deleting one half of a
    # condition. Every plant above changes a literal, which proves a fixture reaches its check but
    # not that the check reads the right thing — and a check reading the wrong variable is a defect
    # no literal-changing plant can express.
    Plant("the_push_url_is_read",
          '\n           git remote get-url --push --all origin 2>/dev/null)"', ')"',
          ("refused_when_pushing_to_the_configured_pushurl",
           "refused_when_the_base_is_measured_against_the_pushurl")),
    Plant("an_unreadable_origin_is_enforced",
          '[ -n "${2:-}" ] && [ -n "$ORIGINS" ]; then', '[ -n "${2:-}" ]; then',
          ("refused_when_the_origin_cannot_be_read_at_all",)),
    Plant("the_origin_spelling_is_normalised",
          "norm_url() { printf '%s' \"$1\" | sed -e 's#/*$##' -e 's#\\.git$##' -e 's#/*$##'; }",
          "norm_url() { printf '%s' \"$1\"; }",
          ("refused_when_origin_is_spelled_with_a_trailing_slash",
           "refused_when_origin_is_spelled_without_its_dot_git")),
    # The `.git` half on its own: the plant above removes both halves, and a fixture that only
    # ever re-spells origin with a slash cannot see this one go.
    Plant("the_dot_git_suffix_is_normalised",
          "-e 's#\\.git$##'", "-e 's#\\.git-never$##'",
          ("refused_when_origin_is_spelled_without_its_dot_git",)),
    Plant("the_stale_message_names_the_sha",
          "${main_sha:0:7}", "${main_sha:0:0}",
          ("refused_when_the_base_is_behind_the_remote_trunk",)),
    # A deletion's local ref is the literal `(delete)`, so a hook reading the local side skips
    # every deletion line: the three deletion refusals go silent under this plant as well.
    Plant("the_ref_test_reads_the_remote_ref",
          'case "$rref" in refs/heads/*)', 'case "$lref" in refs/heads/*)',
          ("refused_when_a_detached_head_refspec_names_a_branch",
           "a_branch_pushed_to_a_tag_ref_ok",
           "refused_when_a_non_holder_deletes_a_participating_branch",
           "refused_when_the_trunk_is_deleted",
           "refused_when_the_trunk_is_deleted_outside_a_narrowed_pattern")),
    Plant("the_refused_accumulator",
          'refused="$refused $branch"', 'refused=" $branch"',
          ("refused_names_every_ref_that_lacks_the_lock",)),

    # ---- the freshness check, one plant per way it can stop firing --------------------------------
    Plant("the_ancestry_test",
          '|| stale="$stale $branch"\n', "|| true\n",
          ("refused_when_the_base_is_behind_the_remote_trunk",
           "refused_when_the_stale_branch_is_not_the_checked_out_one",
           "refused_when_the_trunk_is_pushed_backwards",
           "refused_when_the_trunk_is_pushed_backwards_outside_a_narrowed_pattern",
           "refused_names_every_stale_ref")),
    Plant("the_unfetched_object_test",
          'stale="$stale $branch"; unfetched="$unfetched $branch"; continue',
          'unfetched="$unfetched $branch"; continue',
          ("refused_when_the_remote_trunk_was_never_fetched",
           "refused_when_the_base_is_measured_against_the_pushurl")),
    Plant("the_stale_accumulator",
          '|| stale="$stale $branch"\n', '|| stale=" $branch"\n',
          ("refused_names_every_stale_ref",)),
    Plant("the_unreadable_remote_refusal",
          'if [ "$main_readable" -eq 0 ]; then', "if false; then",
          ("refused_when_the_remote_cannot_be_read",)),
    Plant("the_missing_trunk_refusal",
          'if [ "$trunk_missing" -eq 1 ]; then', "if false; then",
          ("refused_when_the_remote_has_no_such_trunk",)),
    Plant("the_trunk_deletion_refusal",
          'then deltrunk="$deltrunk $branch"; continue; fi', "then continue; fi",
          ("refused_when_the_trunk_is_deleted",
           "refused_when_the_trunk_is_deleted_outside_a_narrowed_pattern")),
    # The pushed sha, not HEAD: the hook says so in a comment, and only the case whose checkout
    # stands on a fresh commit while pushing a stale one can tell the difference.
    Plant("the_pushed_sha_is_measured_not_head",
          '"$main_sha" "$lsha"', '"$main_sha" HEAD',
          ("refused_when_the_stale_branch_is_not_the_checked_out_one",)),
    # ls-remote's tail match returns the decoy beside the trunk; the first line is the decoy.
    Plant("the_trunk_ref_is_matched_exactly",
          "awk -v r=\"refs/heads/$MAIN\" '$2 == r { print $1; exit }'", "head -1 | cut -f1",
          ("a_decoy_ref_on_the_remote_ok",)),
    # Message plants: the recovery lines are the difference between a refusal a reader can act on
    # and one that sends them to the bypass.
    Plant("the_holder_file_parse_guard",
          'if [ -d "$Q/lock" ] && [ -z "$holder_spec" ] && [ -z "$holder_branch" ]; then',
          "if false; then",
          ("refused_when_the_holder_file_parses_to_nothing",)),
    Plant("the_restamp_hint_names_the_spec",
          "re-run \\`$Q/queue.sh acquire $holder_spec\\`", "re-run \\`$Q/queue.sh acquire\\`",
          ("refused_when_the_lock_is_held_on_another_branch",)),
    Plant("the_free_lock_is_named",
          'held="(free)"', 'held="(none)"',
          ("refused_when_the_lock_is_free",
           "refused_when_a_non_holder_deletes_a_participating_branch")),
)


def git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    """Run a git command in a fixture repository and hand back its stdout.

    Args:
      repo: The checkout or bare repository to run in.
      *args: The git arguments.
      check: ``False`` for the resets, which must tolerate removing what is not there.

    Returns:
      What the command wrote to stdout, stripped.

    Raises:
      subprocess.CalledProcessError: If git fails and ``check`` is set, which means the fixture is
        broken rather than the hook.
    """
    # S603: every operand is ours — a literal argument list and a path this module created
    # moments earlier under a temporary directory. None of it comes from input.
    command = ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=Tester", *args]
    done = subprocess.run(command, check=check, capture_output=True, text=True)  # noqa: S603
    return done.stdout.strip()


class Fixture(NamedTuple):
    """A built checkout, its queue, the remotes a case can push to, and the commits it holds.

    Attributes:
      repo: The fixture checkout, whose ``.git/hooks/pre-push`` wrapper the cases execute.
      queue: The queue directory ``install.sh`` wrote.
      origin: The URL configured as the checkout's origin.
      elsewhere: A URL that is a valid remote but is not origin.
      frozen: A bare repository whose trunk stays at ``base`` forever, for the pushurl split.
      gone: A path no repository exists at.
      origin_nosuffix: The origin reached through a path without its ``.git`` suffix — a symlink
        to the same bare repository.
      base: The first commit, which the origin's trunk starts at.
      work: The second commit, a child of ``base`` — what an ordinary push carries.
    """

    repo: pathlib.Path
    queue: pathlib.Path
    origin: str
    elsewhere: str
    frozen: str
    gone: str
    origin_nosuffix: str
    base: str
    work: str


def build(root: pathlib.Path, object_format: str | None = None) -> Fixture:
    """Install a real queue into a throwaway checkout that has a real origin to be behind.

    ``install.sh`` is run rather than imitated, so the wrapper under test is the one a real
    install writes. The two commits and the bare repositories exist because the hook now reads
    the remote's trunk and asks whether the pushed commit contains it; a fixture with no history
    could only ever exercise the lock. The pushes below happen BEFORE the hook is installed, into
    bare repositories nothing else can reach.

    Args:
      root: An empty directory to build in.
      object_format: ``sha256`` to build every repository with 64-character object ids; the
        default is git's own.

    Returns:
      The paths, URLs and commits the cases need.

    Raises:
      RuntimeError: If ``install.sh`` does not report success.
    """
    repo, queue = root / "repo", root / "queue"
    origin, elsewhere, frozen = root / "origin.git", root / "elsewhere.git", root / "frozen.git"
    fmt = [f"--object-format={object_format}"] if object_format else []
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", *fmt, str(repo)], check=True,  # noqa: S603, S607
                   capture_output=True, text=True)
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    for bare in (origin, elsewhere, frozen):
        subprocess.run(["git", "init", "-q", "--bare", *fmt, str(bare)],  # noqa: S603, S607
                       check=True, capture_output=True, text=True)
    os.symlink("origin.git", root / "origin")
    git(repo, "remote", "add", "origin", str(origin))

    (repo / "f").write_text("base\n")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "push", "-q", str(frozen), "main")
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "g").write_text("work\n")
    git(repo, "add", "g")
    git(repo, "commit", "-q", "-m", "work")
    work = git(repo, "rev-parse", "HEAD")

    done = subprocess.run(  # noqa: S603
        ["/bin/sh", str(QUEUE_SRC / "install.sh")],
        cwd=str(repo), capture_output=True, text=True,
        env={**os.environ, "PR_QUEUE_DIR": str(queue)})
    # Exit 3 means the queue installed but a foreign hook was already in place; a fresh `git init`
    # has none, so here it would mean the fixture is wrong rather than the installer.
    if done.returncode != 0:
        raise RuntimeError(f"install.sh exited {done.returncode}: {done.stdout}{done.stderr}")
    return Fixture(repo, queue, str(origin), str(elsewhere), str(frozen), str(root / "gone.git"),
                   str(root / "origin"), base, work)


def peer_commit(fixture: Fixture, parent: str) -> str:
    """Write a commit into the ORIGIN that the checkout has never seen, as a peer's merge would.

    Built with ``commit-tree`` inside the bare repository, so no clone is needed and the object
    exists only where a peer's push would have put it. The message carries a counter: two commits
    with the same tree, parent and message in the same second would be the same object, and a
    case that expects an unfetched commit would find one fetched by an earlier case.

    Args:
      fixture: The built fixture.
      parent: The commit to build on.

    Returns:
      The new commit's sha.

    Raises:
      None.
    """
    tree = git(pathlib.Path(fixture.origin), "rev-parse", f"{parent}^{{tree}}")
    return git(pathlib.Path(fixture.origin), "commit-tree", tree, "-p", parent,
               "-m", f"peer {next(_peer_commits)}")


def apply_state(fixture: Fixture, case: Case) -> dict[str, str]:
    """Put the queue, the checkout and the origin into the state a case declares.

    Args:
      fixture: The built fixture.
      case: The case whose queue, remote and base fields are applied.

    Returns:
      The sentinel-to-sha map the case's stdin is rendered with.

    Raises:
      None.
    """
    away = fixture.queue.with_name(fixture.queue.name + "-away")
    if away.is_dir():
        away.rename(fixture.queue)

    enforce = fixture.queue / "enforce-branches"
    if case.pattern is None:
        enforce.unlink(missing_ok=True)
    else:
        enforce.write_text(case.pattern + "\n")
    trunk_file = fixture.queue / "main-branch"
    if case.trunk is None:
        trunk_file.unlink(missing_ok=True)
    else:
        trunk_file.write_text(case.trunk + "\n")

    # The remote's spelling is repository state, not queue state, so it is reset per case too.
    git(fixture.repo, "config", "--unset-all", "remote.origin.pushurl", check=False)
    git(fixture.repo, "remote", "remove", "origin", check=False)
    if case.origin:
        fetch_url = {"frozen": fixture.frozen, "origin": fixture.origin}[case.fetch_from]
        git(fixture.repo, "remote", "add", "origin", fixture.gone if case.remote == "gone" else fetch_url)
        if case.pushurl is not None:
            url = fixture.origin if case.pushurl == "origin" else fixture.elsewhere
            git(fixture.repo, "config", "remote.origin.pushurl", url)

    # The origin's branches, rebuilt from nothing each case so no earlier case's trunk or decoy
    # survives into this one. The checkout's own trunk goes back to the work commit for the same
    # reason: the `rebased` state moves it.
    origin = pathlib.Path(fixture.origin)
    for ref in git(origin, "for-each-ref", "--format=%(refname)", "refs/heads").split():
        git(origin, "update-ref", "-d", ref)
    git(fixture.repo, "update-ref", "refs/heads/main", fixture.work)
    trunk = f"refs/heads/{case.trunk or 'main'}"
    shas = {BASE: fixture.base, WORK: fixture.work, REBASED: "", MOVED: "", MOVED7: ""}
    if case.base == "current":
        git(origin, "update-ref", trunk, fixture.base)
    elif case.base in ("stale", "unfetched", "rebased"):
        moved = peer_commit(fixture, fixture.base)
        shas[MOVED], shas[MOVED7] = moved, moved[:7]
        git(origin, "update-ref", trunk, moved)
        if case.base != "unfetched":
            git(fixture.repo, "fetch", "-q", "origin")
        if case.base == "rebased":
            tree = git(fixture.repo, "rev-parse", f"{fixture.work}^{{tree}}")
            rebased = git(fixture.repo, "commit-tree", tree, "-p", moved, "-m", "rebased")
            git(fixture.repo, "update-ref", "refs/heads/main", rebased)
            shas[REBASED] = rebased
    elif case.base == "trunk-missing":
        git(origin, "update-ref", "refs/heads/other", fixture.base)
    elif case.base != "none":
        raise ValueError(f"{case.name}: unknown base state {case.base!r}")
    if case.decoy:
        git(origin, "update-ref", f"refs/heads/decoy/{trunk}", peer_commit(fixture, fixture.base))

    lock = fixture.queue / "lock"
    shutil.rmtree(lock, ignore_errors=True)
    if case.holder is not None:
        lock.mkdir()
        spec, branch = case.holder
        holder = f"spec {spec}\nbranch {branch}\nsince 2026-01-01T00:00:00Z\n" if spec or branch else ""
        (lock / "holder").write_text(holder)

    if not case.queue:
        fixture.queue.rename(away)
    return shas


def render(stdin: str, shas: dict[str, str]) -> str:
    """Replace the sha sentinels in a case's stdin with the fixture's real commits.

    Args:
      stdin: The ref lines with sentinels.
      shas: The map ``apply_state`` produced.

    Returns:
      The ref lines git would actually write.

    Raises:
      ValueError: If a sentinel renders to nothing — a case using ``REBASED`` outside the
        ``rebased`` state would otherwise push an empty object and be judged on that.
    """
    for sentinel, sha in shas.items():
        if sentinel in stdin and not sha:
            raise ValueError(f"the sentinel {sentinel} has no commit in this state")
        stdin = stdin.replace(sentinel, sha)
    return stdin


def run(fixture: Fixture, case: Case) -> tuple[int, str, dict[str, str]]:
    """Execute the installed wrapper exactly as git would.

    Args:
      fixture: The built fixture.
      case: The case supplying argv, stdin and environment.

    Returns:
      The exit status, everything the hook wrote to stderr, and the sentinel map the case's
      expectations are rendered with.

    Raises:
      None.
    """
    shas = apply_state(fixture, case)
    # `origin-respelled` is the same repository with a trailing slash, and `origin-nosuffix` is
    # the same repository without its `.git` — both spellings git accepts and a session plausibly
    # types. Each must still be enforced, so these are spellings of origin rather than foreign
    # remotes. `gone` is a path with no repository behind it.
    urls = {"origin": fixture.origin,
            "origin-respelled": fixture.origin + "/",
            "origin-nosuffix": fixture.origin_nosuffix,
            "elsewhere": fixture.elsewhere,
            "gone": fixture.gone}
    url = urls.get(case.remote, fixture.elsewhere)
    done = subprocess.run(  # noqa: S603
        [str(fixture.repo / ".git" / "hooks" / "pre-push"), case.remote, url],
        cwd=str(fixture.repo), input=render(case.stdin, shas), capture_output=True, text=True,
        env={**os.environ, **case.env})
    return done.returncode, done.stderr, shas


def judge(case: Case, rc: int, err: str, shas: dict[str, str]) -> str | None:
    """Say why a case did not behave as declared.

    Args:
      case: The case that ran.
      rc: The exit status it produced.
      err: What it wrote to stderr.
      shas: The sentinel map the run used, so an expectation can name a commit.

    Returns:
      One sentence, or ``None`` when the case behaved.

    Raises:
      None.
    """
    if rc != case.want_rc:
        return f"exit {rc}, wanted {case.want_rc}"
    if case.name.endswith("_ok"):
        return f"expected silence, got {err.strip()[:120]!r}" if err.strip() else None
    missing = [text for text in case.must_say if render(text, shas) not in err]
    if missing:
        return f"stderr lacked {missing!r}"
    wrong = [text for text in case.must_not_say if text in err]
    if wrong:
        return f"stderr also claimed {wrong!r}, which is a reason that does not apply"
    return None


def sweep(root: pathlib.Path, plant: Plant) -> list[str]:
    """Break one check and require exactly the declared cases to notice.

    Args:
      root: An empty directory to build a fresh fixture in.
      plant: The mutation and the case names it must break.

    Returns:
      One message per way the plant did not behave, empty when it did.

    Raises:
      None.
    """
    fixture = build(root)
    hook = fixture.queue / "pre-push"
    source = hook.read_text()
    hits = source.count(plant.old)
    if hits != 1:
        return [(f"{plant.name}: the planted text occurs {hits} times, not once — the mutation "
                 f"landed nowhere and every case below would pass for the wrong reason")]
    hook.write_text(source.replace(plant.old, plant.new))
    # A mutant that does not parse refuses everything for a reason no case declares, which reads
    # as "the plant broke its cases" while the check was never reached.
    parsed = subprocess.run(["bash", "-n", str(hook)], capture_output=True, text=True)  # noqa: S603, S607
    if parsed.returncode != 0:
        return [f"{plant.name}: the mutant does not parse, so its cases fail for the wrong reason"]

    problems = []
    for case in CASES:
        noticed = judge(case, *run(fixture, case)) is not None
        if case.name in plant.breaks and not noticed:
            problems.append(f"{plant.name}: {case.name} still passed — that fixture is vacuous")
        elif case.name not in plant.breaks and noticed:
            problems.append(f"{plant.name}: {case.name} also broke — the plant is not specific to "
                            f"the check it names, so a sweep of it proves nothing")
    return problems


def round_trip(root: pathlib.Path) -> list[str]:
    """Let ``queue.sh`` write the holder and the hook read it, with no fixture in between.

    Every case above fabricates the holder file, so the producer and the consumer are each
    measured against a copy of the format rather than against each other — and two sides written
    from a fixture agree with the fixture and with nothing else. If ``acquire`` ever writes a key
    the hook does not read, this is the only thing here that notices.

    It also covers the two ``queue.sh`` behaviours the fixtures cannot reach: the refusal to lock
    the trunk, and the re-stamp that re-points a lock at the worktree it is re-acquired from.

    Args:
      root: An empty directory to build a fresh fixture in.

    Returns:
      One message per way the two ends disagreed, empty when they agree.

    Raises:
      None.
    """
    fixture = build(root)
    # The remote checks are the queue's, not the hook's, and they would reach GitHub. Replace them
    # through the documented override seam rather than mocking anything.
    for name in ("open-prs", "all-prs", "main-green"):
        stub = fixture.queue / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    def on(branch: str) -> None:
        git(fixture.repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")

    def queue(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [str(fixture.queue / "queue.sh"), *args],
            cwd=str(fixture.repo), capture_output=True, text=True)

    def pushes(branch: str) -> bool:
        done = subprocess.run(  # noqa: S603
            [str(fixture.repo / ".git" / "hooks" / "pre-push"), "origin", fixture.origin],
            cwd=str(fixture.repo),
            input=render(push(f"refs/heads/{branch}", f"refs/heads/{branch}"),
                         {BASE: fixture.base, WORK: fixture.work}),
            capture_output=True, text=True)
        return done.returncode == 0

    problems = []
    on("spec-9/a")
    queue("ticket", "ROUNDTRIP")
    acquired = queue("acquire", "ROUNDTRIP")
    if acquired.returncode != 0:
        return [(f"round_trip: acquire failed, so nothing below was measured: "
                 f"{acquired.stdout}{acquired.stderr}")]
    if not pushes("spec-9/a"):
        problems.append("round_trip: the hook refused the very branch `acquire` locked — what "
                        "queue.sh writes and what pre-push reads have diverged")
    if pushes("spec-9/b"):
        problems.append("round_trip: a branch that holds no lock pushed while one was held")

    on("spec-9/b")
    queue("acquire", "ROUNDTRIP")
    if not pushes("spec-9/b"):
        problems.append("round_trip: re-acquiring did not re-stamp the lock onto this worktree's "
                        "branch, so a lock taken from the wrong directory has no recovery")
    if pushes("spec-9/a"):
        problems.append("round_trip: the branch the lock USED to cover still pushes after a "
                        "re-stamp, so the lock now covers two branches")

    queue("release", "ROUNDTRIP")
    on("main")
    refused = queue("acquire", "ROUNDTRIP")
    if refused.returncode == 0 or "REFUSED" not in refused.stdout:
        problems.append("round_trip: acquire took a lock on the trunk, which pre-push never "
                        "enforces — the lock would authorise nothing and say nothing")
    return problems


def install(fixture: Fixture, *args: str, queue: pathlib.Path | None = None,
            ) -> subprocess.CompletedProcess[str]:
    """Run the installer against a fixture and hand back everything it said.

    Args:
      fixture: The built fixture, used for its checkout.
      *args: Arguments to ``install.sh`` — the branch pattern, if any.
      queue: Where to install; defaults to the fixture's own queue.

    Returns:
      The completed process, so a caller can assert on status, stdout and stderr.

    Raises:
      None.
    """
    return subprocess.run(  # noqa: S603
        ["/bin/sh", str(QUEUE_SRC / "install.sh"), *args],
        cwd=str(fixture.repo), capture_output=True, text=True,
        env={**os.environ, "PR_QUEUE_DIR": str(queue or fixture.queue)})


def installer(root: pathlib.Path) -> list[str]:
    """Assert the installer's refusals, because every one of them fails silently otherwise.

    The queue's repeated failure has never been the hook's logic — it is the deploy. A pattern that
    went stale, a summary that printed it as though it had been chosen, an upgrade that truncated
    a script under a running peer, a bare re-run that repointed the hook at an empty queue. Each of
    those looks exactly like a successful install from the outside, which is why they belong in a
    corpus rather than in a procedure someone follows carefully. ``install-test.sh`` beside the
    installer is the fuller corpus for it; these are the refusals the hook's own gate depends on.

    Args:
      root: An empty directory to build fixtures in.

    Returns:
      One message per refusal that did not behave, empty when all of them did.

    Raises:
      None.
    """
    problems = []

    def check(name: str, condition: bool, detail: str) -> None:
        if not condition:
            problems.append(f"installer/{name}: {detail}")

    # A pattern grep cannot compile must not reach the file: at runtime it exempts every branch.
    fx = build(root / "pattern")
    (fx.queue / "enforce-branches").unlink()
    done = install(fx, "spec-[")
    check("an_invalid_pattern_is_refused", done.returncode == 1 and "not an ERE" in done.stderr,
          f"exit {done.returncode}, stderr {done.stderr.strip()[:120]!r}")
    check("an_invalid_pattern_writes_nothing", not (fx.queue / "enforce-branches").exists(),
          "the pattern file was written despite the refusal")

    # An existing pattern is kept, and the summary has to say so — this is the deploy that
    # silently does nothing, and the only thing standing between it and a success message is
    # this line.
    fx = build(root / "kept")
    (fx.queue / "enforce-branches").write_text("^spec-\n")
    done = install(fx)
    check("a_kept_pattern_says_so", "KEPT" in done.stdout and "^spec-" in done.stdout,
          f"summary did not say the pattern was kept: {done.stdout.strip()[-200:]!r}")
    check("a_kept_pattern_is_unchanged",
          (fx.queue / "enforce-branches").read_text().strip() == "^spec-",
          "the kept pattern was rewritten anyway")

    # An upgrade under a held lock is the one operation with no recovery.
    fx = build(root / "locked")
    (fx.queue / "lock").mkdir()
    (fx.queue / "lock" / "holder").write_text("spec HELD\nbranch spec-9/x\nsince now\n")
    done = install(fx, ".")
    check("a_held_lock_refuses_the_upgrade", done.returncode == 1,
          f"exit {done.returncode}, not a refusal")
    check("a_held_lock_names_the_holder", "spec HELD" in done.stderr,
          f"the refusal did not print the holder: {done.stderr.strip()[:200]!r}")
    check("a_held_lock_still_says_what_to_do", "Wait for the holder to release" in done.stderr,
          "the guidance lines were cut off — the refusal exited before printing them")

    # An UNREADABLE holder, which is the only state that makes the refusal's own `sed` fail. With
    # the holder readable the guidance prints either way, so the check above cannot see a missing
    # `|| true` — measured: reverting it left that check green. `sed` is the last command of the
    # branch, so its failure takes the script out under `set -e` before it says what to do, and
    # BSD and GNU disagree on the status it exits with.
    fx = build(root / "unreadable")
    (fx.queue / "lock").mkdir()
    holder = fx.queue / "lock" / "holder"
    holder.write_text("spec HELD\nbranch spec-9/x\nsince now\n")
    holder.chmod(0o000)
    if os.access(holder, os.R_OK):
        # Running with privileges that ignore the mode bits, so the condition cannot be created.
        # Say so rather than reporting a pass: a check that silently could not run reads as one
        # that ran and was satisfied.
        problems.append("installer/an_unreadable_holder_SKIPPED: this process can read a 000 file, "
                        "so the sed-failure path was never exercised")
    else:
        done = install(fx, ".")
        check("an_unreadable_holder_still_says_what_to_do",
              "Wait for the holder to release" in done.stderr,
              f"the refusal died on its own sed before saying what to do; stderr "
              f"{done.stderr.strip()[:200]!r}")
        check("an_unreadable_holder_still_refuses", done.returncode == 1,
              f"exit {done.returncode}, wanted the documented 1 for 'could not install'")
    holder.chmod(0o600)

    # Replace, never truncate: a peer reading a script keeps its offset into the same inode.
    fx = build(root / "swap")
    before = (fx.queue / "queue.sh").stat().st_ino
    install(fx, ".")
    check("an_upgrade_replaces_the_inode", (fx.queue / "queue.sh").stat().st_ino != before,
          "queue.sh kept its inode, so an upgrade rewrites it under any peer executing it")
    check("an_upgrade_keeps_the_previous_generation",
          (fx.queue / ".previous" / "queue.sh").is_file(),
          "no copy of the replaced scripts was kept, and the deployed ones are in no commit")
    check("an_upgrade_leaves_no_staging_directory",
          not list(fx.queue.glob(".staged.*")), "a staging directory was left behind")

    # A wrapper naming another queue must not be repointed — that is a bare re-run taking the
    # hook away from the queue every session is actually using.
    fx = build(root / "steal")
    hook = fx.repo / ".git" / "hooks" / "pre-push"
    before_text = hook.read_text()
    done = install(fx, ".", queue=fx.queue.with_name("other-queue"))
    check("another_queues_wrapper_is_not_stolen", done.returncode == 3,
          f"exit {done.returncode}, wanted 3")
    check("another_queues_wrapper_is_left_intact", hook.read_text() == before_text,
          "the hook was repointed at a different queue")
    check("another_queues_wrapper_says_which", "DIFFERENT queue" in done.stderr,
          f"the message did not name the conflict: {done.stderr.strip()[:150]!r}")

    # A queue path with a SPACE in it. Every fixture path here is well behaved, and that is how an
    # unquoted `Q=$Q` in the wrapper survived being written: the path parsed as an assignment plus
    # a command, `$Q/pre-push` did not exist, and the wrapper exited 0 — installing cleanly, saying
    # so, and enforcing nothing. `$HOME` is not sanitised, so `/Users/First Last` reaches this.
    fx = build(root / "spacey")
    spacey = fx.queue.with_name("queue with a space")
    # A clean install of the spaced queue, not a second one beside the first — the wrapper written
    # by `build` names another queue, and the refusal above would (correctly) block this.
    (fx.repo / ".git" / "hooks" / "pre-push").unlink()
    done = install(fx, ".", queue=spacey)
    check("a_queue_path_with_a_space_installs", done.returncode == 0,
          f"exit {done.returncode}: {done.stderr.strip()[:150]!r}")
    spaced_hook = subprocess.run(  # noqa: S603
        [str(fx.repo / ".git" / "hooks" / "pre-push"), "origin", fx.origin],
        cwd=str(fx.repo),
        input=render(push("refs/heads/spec-9/x", "refs/heads/spec-9/x"),
                     {BASE: fx.base, WORK: fx.work}),
        capture_output=True, text=True)
    check("a_queue_path_with_a_space_still_refuses", spaced_hook.returncode == 1,
          f"the wrapper exited {spaced_hook.returncode} holding no lock — the queue path was not "
          f"quoted, so it installed cleanly and enforces nothing")

    # An empty pattern is a real setting, but not one an argument should be able to reach.
    fx = build(root / "blank")
    done = install(fx, "   ")
    check("a_blank_pattern_is_refused", done.returncode == 1 and "empty or blank" in done.stderr,
          f"exit {done.returncode}: {done.stderr.strip()[:150]!r}")

    # And a hook that is nobody's business stays untouched.
    fx = build(root / "foreign")
    hook = fx.repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho someone elses hook\n")
    done = install(fx, ".")
    check("a_foreign_hook_is_left_alone",
          done.returncode == 3 and "someone elses hook" in hook.read_text(),
          f"exit {done.returncode}; hook now {hook.read_text()[:80]!r}")
    return problems


def upgrade(root: pathlib.Path) -> list[str]:
    """Re-install over a previous generation's wrapper and require the hook to end up live.

    The deployed wrapper predates the ``PR_QUEUE_WRAPPER`` marker and names the queue through a
    ``Q=`` variable, so neither the marker nor the literal ``$Q/pre-push`` appears in it. Refusing
    to replace it prints "the queue works, but nothing enforces it" over a hook that does enforce,
    and an operator cannot tell that from the case where the warning is true.

    Args:
      root: An empty directory to build a fresh fixture in.

    Returns:
      One message per way the upgrade misbehaved, empty when it behaved.

    Raises:
      None.
    """
    fixture = build(root)
    hook = fixture.repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/bash\n"
                    "# Delegates to the PR queue's hook so edits there take effect at once.\n"
                    f"Q={fixture.queue}\n"
                    '[ -x "$Q/pre-push" ] && exec "$Q/pre-push" "$@"\n'
                    "exit 0\n")
    hook.chmod(0o755)

    done = subprocess.run(  # noqa: S603
        ["/bin/sh", str(QUEUE_SRC / "install.sh"), "."],
        cwd=str(fixture.repo), capture_output=True, text=True,
        env={**os.environ, "PR_QUEUE_DIR": str(fixture.queue)})
    problems = []
    if done.returncode != 0:
        problems.append(f"upgrade: re-installing over the previous generation's wrapper exited "
                        f"{done.returncode} — an operator is told nothing enforces the queue while "
                        f"it does: {done.stderr.strip()[:200]}")
    rc, err, _ = run(fixture, CASES[0])
    if rc != 1 or "PUSH REFUSED" not in err:
        problems.append(f"upgrade: after re-installing, a push holding no lock exited {rc} — the "
                        f"upgrade left the hook not enforcing")
    return problems


def hash_width(root: pathlib.Path) -> list[str]:
    """Prove the deletion tests key on git's ``(delete)`` literal, not on the zero object's width.

    The hook says it uses the literal because the all-zero object is 40 or 64 characters depending
    on the repository's hash algorithm, and every fixture above is sha1 — so a hook that keyed on
    forty zeros would pass the whole corpus and misjudge a sha256 repository. Found by a
    reviewer's plant that both corpora passed.

    Args:
      root: An empty directory to build a sha256 fixture in.

    Returns:
      One message per deletion the hook judged wrongly, empty when both were right.

    Raises:
      None.
    """
    try:
        fixture = build(root, object_format="sha256")
    except subprocess.CalledProcessError as failed:
        return [(f"hash_width: this git cannot build a sha256 repository, so the width claim was "
                 f"not measured: {failed.stderr.strip()[:120]}")]
    zero = "0" * 64

    def hook(stdin: str) -> tuple[int, str]:
        done = subprocess.run(  # noqa: S603
            [str(fixture.repo / ".git" / "hooks" / "pre-push"), "origin", fixture.origin],
            cwd=str(fixture.repo), input=stdin, capture_output=True, text=True)
        return done.returncode, done.stderr

    problems = []
    rc, err = hook(f"(delete) {zero} refs/heads/main {fixture.work}\n")
    if rc != 1 or DROPS not in err:
        problems.append(f"hash_width: deleting the trunk of a sha256 repository exited {rc} with "
                        f"{err.strip()[:120]!r} — the deletion test is reading the zero object's "
                        f"width, not git's literal")
    lock = fixture.queue / "lock"
    lock.mkdir()
    (lock / "holder").write_text("spec MINE\nbranch spec-9/x\nsince 2026-01-01T00:00:00Z\n")
    rc, err = hook(f"(delete) {zero} refs/heads/spec-9/x {fixture.work}\n")
    if rc != 0 or err.strip():
        problems.append(f"hash_width: the holder's own deletion in a sha256 repository exited {rc} "
                        f"with {err.strip()[:120]!r} — measured as stale against a 64-zero object")
    return problems


def main() -> int:
    """Run the corpus, then the mutation sweep, and report everything at once.

    Returns:
      ``0`` when every case and every plant behaved as declared, ``1`` otherwise.

    Raises:
      None.
    """
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        fixture = build(pathlib.Path(tmp) / "base")

        # The positive control. Every silence case below claims the hook stayed quiet, and a
        # harness that cannot reach the hook at all — an unexecutable wrapper, stdin not
        # delivered — produces exactly that for every one of them. Prove a refusal is reachable
        # through this exact plumbing before believing any silence it reports.
        # It reports and CONTINUES rather than aborting. A hook that has been broken open fails
        # this control too, and a run that stops here shows zero cases and blames the plumbing for
        # the one defect class that matters most. Running on tells the two apart: the control
        # failing beside every refusal case is a broken hook, the control failing while the
        # silence cases still pass is broken plumbing.
        control = CASES[0]
        rc, err, _ = run(fixture, control)
        if rc != 1 or "PUSH REFUSED" not in err:
            failed.append("harness_control")
            print(f"FAIL  harness_control: {control.name} produced exit {rc} and "
                  f"{err.strip()[:200]!r}. If the refusal cases below also fail, the HOOK is open; "
                  f"if only this and they pass, the corpus cannot drive the hook and nothing it "
                  f"reports about silence means anything.")
        else:
            print("ok    harness_control")

        for case in CASES:
            why = judge(case, *run(fixture, case))
            if why:
                failed.append(f"{case.name}: {why}")
                print(f"FAIL  {case.name}: {why}")
            else:
                print(f"ok    {case.name}")

        inst = installer(pathlib.Path(tmp) / "installer")
        failed.extend(inst)
        for problem in inst:
            print(f"FAIL  {problem}")
        if not inst:
            print("ok    installer_refusals")

        up = upgrade(pathlib.Path(tmp) / "upgrade")
        failed.extend(up)
        for problem in up:
            print(f"FAIL  {problem}")
        if not up:
            print("ok    upgrade_over_the_previous_wrapper")

        trip = round_trip(pathlib.Path(tmp) / "roundtrip")
        failed.extend(trip)
        for problem in trip:
            print(f"FAIL  {problem}")
        if not trip:
            print("ok    round_trip")

        width = hash_width(pathlib.Path(tmp) / "sha256")
        failed.extend(width)
        for problem in width:
            print(f"FAIL  {problem}")
        if not width:
            print("ok    sha256_deletion_keys_on_the_literal")

        for i, plant in enumerate(PLANTS):
            problems = sweep(pathlib.Path(tmp) / f"plant{i}", plant)
            failed.extend(problems)
            for problem in problems:
                print(f"FAIL  {problem}")
            if not problems:
                print(f"ok    mutation:{plant.name}")

    print("----")
    print(f"pre_push_test: {len(CASES)} cases, one round trip, {len(PLANTS)} mutations, "
          f"{len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
