"""The fixture corpus for the PR queue's ``pre-push`` gate.

Why this exists. The hook decides whether a push reaches the remote, and every way it can go wrong
is silent: a pattern that stops matching, a check that stops firing, a fail-open that swallows a
refusal. A queue enforcing nothing looks exactly like a queue enforcing everything — which is not
hypothetical, because the first deployment of this hook enforced the branch prefixes of five specs,
those specs closed, and it then exited 0 for every branch anyone pushed while still looking
installed. Nothing noticed, because there was nothing to notice with.

How it works. Each case builds a throwaway checkout, runs ``install.sh`` into a throwaway queue
beside it, sets the queue's state, and executes the hook the way git does: argv of remote name and
remote URL, and the refs on stdin. Nothing here pushes anything anywhere, and nothing here touches
a real queue.

It drives the WRAPPER in ``.git/hooks``, not the hook file directly, and that is load-bearing
rather than incidental. ``pre-push`` lives inside the queue directory, so a deleted queue deletes
the hook too and its own ``[ -d "$Q" ]`` guard can never run; the wrapper's exec-if-present is what
actually lets a push through when the queue is gone. Driving the hook directly would leave the
first thing this gate promises asserted nowhere, and the fixture for it would pass vacuously.

Cases whose name ends ``_ok`` assert SILENCE — exit 0 and not one byte on stderr. Half of what a
gate gets wrong is refusing something legitimate, and a corpus of only-refusals cannot see it.

The mutation sweep is the other half. Every check in the hook is broken in turn, in a copy, and
each plant DECLARES the cases it must break — reddening somewhere is not reddening in the right
place, and a plant that also happens to break a neighbour would otherwise satisfy a sweep while
leaving its own fixture vacuous. Each plant also asserts its substitution landed exactly once: an
edit that silently matched nothing reads identically to a guard that was already dead.

One thing this corpus cannot cover, said out loud rather than left to be discovered: CI runs it on
GNU ``grep`` and ``awk`` while the hook it guards only ever executes on the developer's machine.
A green run here is not evidence about the deployed hook's ``grep``.

Usage: ``python3 scripts/pr-queue/pre_push_test.py`` — takes no arguments, imports nothing outside
the standard library, and exits non-zero if any case does not behave as declared.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

QUEUE_SRC = pathlib.Path(__file__).resolve().parent
ZERO = "0" * 40
SOME = "a" * 40
OTHER = "b" * 40


def push(local_ref: str, remote_ref: str) -> str:
    """Render the stdin line git writes for a ref it is about to update.

    Args:
      local_ref: The local ref being pushed, as git spells it.
      remote_ref: The ref that will be updated on the remote.

    Returns:
      One stdin line, newline-terminated.

    Raises:
      None.
    """
    return f"{local_ref} {SOME} {remote_ref} {ZERO}\n"


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
    return f"(delete) {ZERO} {remote_ref} {OTHER}\n"


class Case(NamedTuple):
    """One fabricated push against one queue state.

    Attributes:
      name: Identifies the case in the report. A ``_ok`` suffix asserts silence.
      stdin: The ref lines git would hand the hook.
      want_rc: The exit status the hook must produce.
      must_say: Substrings the hook's stderr must contain. Ignored for a silence case.
      pattern: What to write to ``enforce-branches``; ``None`` removes the file entirely.
      holder: ``(spec, branch)`` for the lock, or ``None`` for a free lock.
      queue: ``False`` moves the whole queue directory away before the push.
      remote: ``origin`` pushes to the configured origin, anything else to a foreign remote.
      trunk: What to write to ``main-branch``; ``None`` removes it. Anything but ``main`` proves the
        hook READ it, since ``main`` is also the hook's own fallback and a case using it cannot
        tell the two apart.
      pushurl: Sets ``remote.origin.pushurl`` to the origin or the foreign bare repo, or leaves it
        unset. The hook reads both spellings of origin and only this distinguishes them.
      origin: ``False`` removes the origin remote, so neither spelling can be read at all.
      env: Extra environment for the hook.
    """

    name: str
    stdin: str
    want_rc: int
    must_say: tuple[str, ...] = ()
    pattern: str | None = "."
    holder: tuple[str, str] | None = None
    queue: bool = True
    remote: str = "origin"
    trunk: str | None = "main"
    pushurl: str | None = None
    origin: bool = True
    env: dict[str, str] = {}  # noqa: RUF012


CASES: tuple[Case, ...] = (
    # ---- refusals ---------------------------------------------------------------------------
    # Every one asserts the branch is NAMED. A refusal that does not say which ref it refused
    # sends the reader to the bypass, and an exit status alone cannot tell these five apart.
    Case("refused_when_the_lock_is_free",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("PUSH REFUSED", "spec-9/x", "(free)")),
    Case("refused_when_the_lock_is_held_on_another_branch",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1,
         ("spec-9/x", "OTHER-SPEC", "spec-9/other", "re-stamps"),
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
         ("spec-9/queue",),
         holder=("MINE", "spec-9/qu")),
    # Keys on the REMOTE ref, which is the one that decides what appears on the remote. The local
    # side being the trunk is irrelevant, and a check written against it would pass this wrongly.
    Case("refused_when_the_trunk_is_pushed_onto_a_topic_branch",
         push("refs/heads/main", "refs/heads/topic"), 1, ("topic",)),

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
    Case("the_trunk_ok",
         push("refs/heads/main", "refs/heads/main"), 0),
    Case("a_branch_pushed_onto_the_trunk_ok",
         push("refs/heads/topic", "refs/heads/main"), 0),
    Case("a_deletion_ok",
         delete("refs/heads/spec-9/x"), 0),
    Case("a_tag_ok",
         push("refs/tags/v1", "refs/tags/v1"), 0),
    Case("a_remote_that_is_not_origin_ok",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 0, remote="elsewhere"),
    Case("a_push_with_no_refs_ok",
         "", 0),

    # ---- the trunk is READ, not assumed -------------------------------------------------------
    # `install.sh` writes `main` into a fixture whose origin has no HEAD to resolve, which is the
    # same string the hook falls back to. So every case above is blind to whether `main-branch` is
    # read at all: delete the read and they stay green. These two configure a trunk that is NOT
    # the fallback, and only a hook that reads the file gets both of them right.
    Case("a_configured_trunk_that_is_not_the_default_ok",
         push("refs/heads/trunk", "refs/heads/trunk"), 0, trunk="trunk"),
    Case("refused_when_the_branch_is_only_the_default_trunk_name",
         push("refs/heads/main", "refs/heads/main"), 1, ("main",), trunk="trunk"),
    # The fallback, which every case above reaches only when the file already says `main`.
    Case("an_absent_main_branch_file_still_exempts_the_trunk_ok",
         push("refs/heads/main", "refs/heads/main"), 0, trunk=None),

    # ---- which spelling of origin counts ------------------------------------------------------
    # Two URLs are read, and until these cases only one of them was exercised: a push to the
    # configured pushurl IS a push to origin, and exempting it would let the queue be walked
    # around by a setting nobody thinks of as a remote.
    Case("refused_when_pushing_to_the_configured_pushurl",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, ("spec-9/x",),
         remote="elsewhere", pushurl="elsewhere"),
    Case("refused_when_origin_is_spelled_with_a_trailing_slash",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, ("spec-9/x",),
         remote="origin-respelled"),
    # A checkout whose origin cannot be read is enforced rather than exempted. The hook's comment
    # claims this; nothing asserted it, and the two directions look identical from outside.
    Case("refused_when_the_origin_cannot_be_read_at_all",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, ("spec-9/x",),
         remote="elsewhere", origin=False),

    # ---- the ref test reads the REMOTE ref ----------------------------------------------------
    # Both of these are silent-or-refused purely on which side of the refspec is inspected, so a
    # check moved from `$rref` to `$lref` — a defect no value-changing plant can produce — has to
    # get one of them wrong.
    Case("refused_when_a_detached_head_refspec_names_a_branch",
         push("HEAD", "refs/heads/spec-9/x"), 1, ("spec-9/x",)),
    Case("a_branch_pushed_to_a_tag_ref_ok",
         push("refs/heads/v1", "refs/tags/v1"), 0),

    # Two refused refs, so the accumulator is asserted rather than just the first write to it.
    # A pattern grep cannot compile is not a pattern that matches nothing — grep exits 2, and
    # reading that as "no match" exempts every branch while `enforcing: spec-[` sits in the banner
    # looking configured.
    Case("refused_when_the_pattern_is_not_a_compilable_ere",
         push("refs/heads/spec-9/x", "refs/heads/spec-9/x"), 1, ("spec-9/x",), pattern="spec-["),

    Case("refused_names_every_ref_that_lacks_the_lock",
         push("refs/heads/spec-9/a", "refs/heads/spec-9/a")
         + push("refs/heads/spec-9/b", "refs/heads/spec-9/b"), 1,
         ("Refused ref(s): spec-9/a spec-9/b\n",)),
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


SILENCE_AFTER_THE_LOOP = (
    "the_branch_holding_the_lock_ok", "a_branch_outside_the_pattern_ok", "the_trunk_ok",
    "a_branch_pushed_onto_the_trunk_ok", "a_deletion_ok", "a_tag_ok", "a_push_with_no_refs_ok",
    "a_configured_trunk_that_is_not_the_default_ok",
    "an_absent_main_branch_file_still_exempts_the_trunk_ok", "a_branch_pushed_to_a_tag_ref_ok",
)

# Both lists are maintained by hand and that is safe here, because getting one wrong is LOUD: name
# a case that does not break and the sweep says "still passed", omit one that does and it says
# "also broke". The sweep corrects these lists rather than trusting them.
REFUSALS = (
    "refused_when_the_lock_is_free", "refused_when_the_lock_is_held_on_another_branch",
    "refused_names_only_the_ref_that_lacks_the_lock",
    "refused_when_the_holder_branch_is_a_prefix_of_the_pushed_one",
    "refused_when_the_trunk_is_pushed_onto_a_topic_branch",
    "refused_when_the_branch_is_only_the_default_trunk_name",
    "refused_when_pushing_to_the_configured_pushurl",
    "refused_when_origin_is_spelled_with_a_trailing_slash",
    "refused_when_the_origin_cannot_be_read_at_all",
    "refused_when_a_detached_head_refspec_names_a_branch",
    "refused_when_the_pattern_is_not_a_compilable_ere",
    "refused_names_every_ref_that_lacks_the_lock",
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
    Plant("the_deletion_exemption",
          '[ "$lref" = "(delete)" ] && continue', '[ "$lref" = "(nope)" ] && continue',
          ("a_deletion_ok",)),
    Plant("the_trunk_exemption",
          '[ "$branch" = "$MAIN" ] && continue', '[ "$branch" = "$MAIN-nope" ] && continue',
          ("the_trunk_ok", "a_branch_pushed_onto_the_trunk_ok",
           "a_configured_trunk_that_is_not_the_default_ok",
           "an_absent_main_branch_file_still_exempts_the_trunk_ok")),
    Plant("the_participation_test",
          'echo "$branch" | grep -qE "$PATTERN"', 'echo "$branch" | grep -qE ""',
          ("a_branch_outside_the_pattern_ok",)),
    # grep answers 2 for a pattern it cannot compile, and reading that as "no match" is what turns
    # one bad character in a config file into a queue that enforces nothing.
    Plant("a_pattern_grep_cannot_compile_fails_closed",
          "    *) ;;                                            "
          "# grep could not answer — fail closed",
          "    *) continue ;;",
          ("refused_when_the_pattern_is_not_a_compilable_ere",)),
    Plant("the_holder_comparison",
          '[ "$branch" = "$holder_branch" ] && continue', '[ -n "$holder_branch" ] && continue',
          ("refused_when_the_lock_is_held_on_another_branch",
           "refused_names_only_the_ref_that_lacks_the_lock",
           "refused_when_the_holder_branch_is_a_prefix_of_the_pushed_one")),
    Plant("the_nothing_to_refuse_exit",
          '[ -n "$refused" ] || exit 0', '[ -n "$refused" ] || :',
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
          ("refused_when_pushing_to_the_configured_pushurl",)),
    Plant("an_unreadable_origin_is_enforced",
          '[ -n "${2:-}" ] && [ -n "$ORIGINS" ]; then', '[ -n "${2:-}" ]; then',
          ("refused_when_the_origin_cannot_be_read_at_all",)),
    Plant("the_origin_spelling_is_normalised",
          "norm_url() { printf '%s' \"$1\" | sed -e 's#/*$##' -e 's#\\.git$##' -e 's#/*$##'; }",
          "norm_url() { printf '%s' \"$1\"; }",
          ("refused_when_origin_is_spelled_with_a_trailing_slash",)),
    Plant("the_ref_test_reads_the_remote_ref",
          'case "$rref" in refs/heads/*)', 'case "$lref" in refs/heads/*)',
          ("refused_when_a_detached_head_refspec_names_a_branch",
           "a_branch_pushed_to_a_tag_ref_ok")),
    Plant("the_refused_accumulator",
          'refused="$refused $branch"', 'refused=" $branch"',
          ("refused_names_every_ref_that_lacks_the_lock",)),
)


def git(repo: pathlib.Path, *args: str, check: bool = True) -> None:
    """Run a git command in a fixture repository.

    Args:
      repo: The checkout to run in.
      *args: The git arguments.
      check: ``False`` for the resets, which must tolerate removing what is not there.

    Returns:
      None.

    Raises:
      subprocess.CalledProcessError: If git fails and ``check`` is set, which means the fixture is
        broken rather than the hook.
    """
    # S603/S607: every operand is ours — a literal argument list and a path this module created
    # moments earlier under a temporary directory. None of it comes from input.
    subprocess.run(["git", "-C", str(repo), *args], check=check,  # noqa: S603, S607
                   capture_output=True, text=True)


class Fixture(NamedTuple):
    """A built checkout, its queue and the remotes a case can push to.

    Attributes:
      repo: The fixture checkout, whose ``.git/hooks/pre-push`` wrapper the cases execute.
      queue: The queue directory ``install.sh`` wrote.
      origin: The URL configured as the checkout's origin.
      elsewhere: A URL that is a valid remote but is not origin.
    """

    repo: pathlib.Path
    queue: pathlib.Path
    origin: str
    elsewhere: str


def build(root: pathlib.Path) -> Fixture:
    """Install a real queue into a throwaway checkout.

    ``install.sh`` is run rather than imitated, so the wrapper under test is the one a real
    install writes. No commit is made: nothing in the installer or the hook needs one, and a
    commit would need an author identity the environment may not have.

    Args:
      root: An empty directory to build in.

    Returns:
      The paths and URLs the cases need.

    Raises:
      RuntimeError: If ``install.sh`` does not report success.
    """
    repo, queue = root / "repo", root / "queue"
    origin, elsewhere = root / "origin.git", root / "elsewhere.git"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True,  # noqa: S603, S607
                   capture_output=True, text=True)
    for bare in (origin, elsewhere):
        subprocess.run(["git", "init", "-q", "--bare", str(bare)],  # noqa: S603, S607
                       check=True, capture_output=True, text=True)
    git(repo, "remote", "add", "origin", str(origin))

    done = subprocess.run(  # noqa: S603
        ["/bin/sh", str(QUEUE_SRC / "install.sh")],
        cwd=str(repo), capture_output=True, text=True,
        env={**os.environ, "PR_QUEUE_DIR": str(queue)})
    # Exit 3 means the queue installed but a foreign hook was already in place; a fresh `git init`
    # has none, so here it would mean the fixture is wrong rather than the installer.
    if done.returncode != 0:
        raise RuntimeError(f"install.sh exited {done.returncode}: {done.stdout}{done.stderr}")
    return Fixture(repo, queue, str(origin), str(elsewhere))


def apply_state(fixture: Fixture, case: Case) -> None:
    """Put the queue into the state a case declares.

    Args:
      fixture: The built fixture.
      case: The case whose ``pattern``, ``holder`` and ``queue`` fields are applied.

    Returns:
      None.

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
        git(fixture.repo, "remote", "add", "origin", fixture.origin)
        if case.pushurl is not None:
            url = fixture.origin if case.pushurl == "origin" else fixture.elsewhere
            git(fixture.repo, "config", "remote.origin.pushurl", url)

    lock = fixture.queue / "lock"
    shutil.rmtree(lock, ignore_errors=True)
    if case.holder is not None:
        lock.mkdir()
        spec, branch = case.holder
        (lock / "holder").write_text(f"spec {spec}\nbranch {branch}\nsince 2026-01-01T00:00:00Z\n")

    if not case.queue:
        fixture.queue.rename(away)


def run(fixture: Fixture, case: Case) -> tuple[int, str]:
    """Execute the installed wrapper exactly as git would.

    Args:
      fixture: The built fixture.
      case: The case supplying argv, stdin and environment.

    Returns:
      The exit status and everything the hook wrote to stderr.

    Raises:
      None.
    """
    apply_state(fixture, case)
    # `origin-respelled` is the same repository with a trailing slash, which git accepts and a
    # session plausibly types. It must still be enforced, so this is a spelling of origin rather
    # than a foreign remote.
    urls = {"origin": fixture.origin,
            "origin-respelled": fixture.origin + "/",
            "elsewhere": fixture.elsewhere}
    url = urls.get(case.remote, fixture.elsewhere)
    done = subprocess.run(  # noqa: S603
        [str(fixture.repo / ".git" / "hooks" / "pre-push"), case.remote, url],
        cwd=str(fixture.repo), input=case.stdin, capture_output=True, text=True,
        env={**os.environ, **case.env})
    return done.returncode, done.stderr


def judge(case: Case, rc: int, err: str) -> str | None:
    """Say why a case did not behave as declared.

    Args:
      case: The case that ran.
      rc: The exit status it produced.
      err: What it wrote to stderr.

    Returns:
      One sentence, or ``None`` when the case behaved.

    Raises:
      None.
    """
    if rc != case.want_rc:
        return f"exit {rc}, wanted {case.want_rc}"
    if case.name.endswith("_ok"):
        return f"expected silence, got {err.strip()[:120]!r}" if err.strip() else None
    missing = [text for text in case.must_say if text not in err]
    if missing:
        return f"stderr lacked {missing!r}"
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

    problems = []
    for case in CASES:
        rc, err = run(fixture, case)
        noticed = judge(case, rc, err) is not None
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
            cwd=str(fixture.repo), input=push(f"refs/heads/{branch}", f"refs/heads/{branch}"),
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
    went stale, a banner that printed it as though it had been chosen, an upgrade that truncated a
    script under a running peer, a bare re-run that repointed the hook at an empty queue. Each of
    those looks exactly like a successful install from the outside, which is why they belong in a
    corpus rather than in a procedure someone follows carefully.

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

    # An existing pattern is kept, and the banner has to say so — this is the deploy that silently
    # does nothing, and the only thing standing between it and a success message is this line.
    fx = build(root / "kept")
    (fx.queue / "enforce-branches").write_text("^spec-\n")
    done = install(fx)
    check("a_kept_pattern_says_so", "KEPT" in done.stdout and "^spec-" in done.stdout,
          f"banner did not say the pattern was kept: {done.stdout.strip()[-200:]!r}")
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
        cwd=str(fx.repo), input=push("refs/heads/spec-9/x", "refs/heads/spec-9/x"),
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
    rc, err = run(fixture, CASES[0])
    if rc != 1 or "PUSH REFUSED" not in err:
        problems.append(f"upgrade: after re-installing, a push holding no lock exited {rc} — the "
                        f"upgrade left the hook not enforcing")
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
        rc, err = run(fixture, control)
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
