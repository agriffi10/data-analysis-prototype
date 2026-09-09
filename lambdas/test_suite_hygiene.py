"""Repo-wide properties of the Lambda SUITES themselves (SPEC-153 FR-007).

A test that asserts "something raised" passes against an ``ImportError`` at cold start, and
this fleet has already paid for that once: SPEC-137 broke sign-up for nine days with a
``ModuleNotFoundError``, in a handler whose own test only demanded that *an* exception
appear. So the assertion has to name what it expects.

Sits beside the other files here that read the repository as data rather than exercising a
behaviour — ``test_fleet_derivation.py`` and ``test_image_layout.py`` among them.
"""

import ast
import io
import os
import pathlib
import re
import tokenize

LAMBDAS = pathlib.Path(__file__).resolve().parent

#: Directories whose contents this repo does not write. pytest skips them by default
#: (``norecursedirs``); ``rglob`` skips nothing, so a local virtualenv or a vendored package
#: under ``lambdas/`` would otherwise redden every check here on code nobody can edit.
#: Shared by the sweep and by its control below — the two walk the tree by DIFFERENT
#: mechanisms on purpose, but they must agree on what is in scope, and a policy written twice
#: is wrong in one copy.
_NOT_OURS = frozenset({"__pycache__", "node_modules", "build", "dist", "venv", ".venv"})


def _is_ours(relative_parts):
    """Whether a path under ``lambdas/`` is repo code rather than something vendored.

    Args:
      relative_parts: The path's parts, relative to ``LAMBDAS``.

    Returns:
      True when every segment is one this repo owns.

    Raises:
      None.
    """
    return not any(
        part in _NOT_OURS or part.startswith(".") for part in relative_parts
    )


#: Every suite file except this one — it documents the offences it refuses, so it would
#: otherwise be its own first offender.
_TEST_FILES = [
    p
    for p in sorted(LAMBDAS.rglob("test_*.py"))
    if p.name != pathlib.Path(__file__).name and _is_ours(p.relative_to(LAMBDAS).parts)
]

#: ``pytest.raises(Exception)`` / ``(BaseException)`` with nothing else inside the
#: parentheses. A ``match=``, a narrower type, or a tuple of types all fall outside it.
#: ``re.DOTALL``-friendly by allowing newlines, so wrapping the call across lines is not a
#: way around the check.
_BARE_RAISES = re.compile(r"pytest\.raises\(\s*(?:Base)?Exception\s*\)")

#: A sentence, for the claim scan. A period ends one only when whitespace follows it, which
#: keeps ``sys.path``, ``cpcommon.clients`` and ``test_x.py`` inside the sentence they sit in.
#: Applied to PROSE ONLY — see ``_prose``. Run over raw file text it would not stop at the
#: ``."""`` ending a one-line docstring, since a quote is not whitespace, and the chunk would
#: swallow the module body: measured, an ``import pytest`` two lines down then supplied the
#: third token and a docstring reading "Runs directly, bypassing the module under test"
#: became an offence.
_SENTENCE = re.compile(r"(?:[^.]|\.(?!\s))+\.?", re.DOTALL)

#: Words that say a file is RUN, in any of the spellings a docstring here has used or would.
_RUN_VERB = re.compile(r"(?i)\b(?:runnable|runs?|executable|execute[ds]?|invoke[ds]?)\b")

#: The alternative to pytest. Naming the modes rather than matching "not pytest" keeps the
#: check off ordinary prose: "tested directly against a fake S3 paginator" has no run verb,
#: and "patched directly on ``cpcommon.clients``" has none either.
_ALT_MODE = re.compile(r"(?i)\b(?:directly|(?:plain|standalone|bare) script|as a script)\b")

#: An instruction to invoke a suite file as a script, with or without a run verb around it.
#: Loose about the interpreter, the path and the spacing — ``python test_x.py``,
#: ``python3  ./test_x.py`` and ``python3 lambdas/x/test_y.py`` are one instruction and all
#: three are now wrong. Horizontal space only: ``\s`` spans newlines, and a line ending on
#: the bare word "python" above a line starting with a filename is not an instruction.
_DIRECT_INVOCATION = re.compile(r"(?i)\bpython[23]?[ \t]+\S*test_\w+\.py")


def _prose(source, label='<module>'):
    """Every docstring and comment in one module, with the line each starts on.

    The claim check reads THIS rather than the file's text, and the distinction is the whole
    point. A claim about how to run a file is something the file SAYS; scanning the text
    instead lets what the file DOES answer for it, and in this tree every suite imports
    pytest, so the token that completes an offence is always two lines below any docstring.

    Args:
      source: The module's source text.

    Yields:
      ``(text, first line)`` for each docstring and each comment.

    Raises:
      SyntaxError: If the source does not parse.
    """
    tree = ast.parse(source, filename=str(label))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            continue
        first = node.body[0]
        yield doc, first.lineno
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            yield token.string, token.start[0]


def _is_runner_guard(node):
    """Whether one AST node is an ``if __name__ == "__main__":`` guard, however spelled.

    Reads the CONDITION rather than comparing its rendered text. ``if "__main__" ==
    __name__:``, ``if __name__ in ("__main__",):`` and a guard with a second clause bolted on
    all branch on the same thing, and all three are invisible to an equality test against one
    rendering.

    Args:
      node: Any AST node; non-``If`` nodes answer False.

    Returns:
      True when the node branches on this module being run as a script.

    Raises:
      None.
    """
    if not isinstance(node, ast.If):
        return False
    names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
    literals = {c.value for c in ast.walk(node.test) if isinstance(c, ast.Constant)}
    return "__name__" in names and "__main__" in literals


def _runner_offences(source, label):
    """Every runner guard in one module, at any nesting depth.

    Args:
      source: The module's source text.
      label: How to name the file in an offence string.

    Returns:
      A list of ``<label>:<line>`` strings, empty when the module ships no runner.

    Raises:
      SyntaxError: If the source does not parse.
    """
    return [
        f"{label}:{node.lineno}"
        for node in ast.walk(ast.parse(source))
        if _is_runner_guard(node)
    ]


def _claim_offences(source, label):
    """Every run-mode claim in one module's prose.

    A sentence offends when it carries a run verb AND ``pytest`` AND an alternative to
    pytest — in any order, since the sentence is the unit rather than a window anchored on
    one of the three. An instruction to invoke a suite file offends on its own, verb or no
    verb, because "The ``python3 test_x.py`` mode" is a claim without being a sentence about
    running anything.

    A sentence that PROHIBITS a run mode offends too, and that is deliberate after trying the
    alternative. An exemption for prohibitions was written, tightened once, and then removed:
    against the 72 real sentences this fleet actually carried it flagged 70, and the two it
    hid were the two that ended "the JS CI does not run Python" — a negator governing a run
    verb, in the middle of an ADVERTISEMENT. It also suppressed the direct-invocation check
    for the whole sentence, so "Do not run this under pytest; use python3 test_x.py instead"
    handed out a live command and passed. Measured the other way, the exemption protected no
    sentence in this tree at all. A file with nothing to say about how it is run says nothing;
    the two places that must discuss the policy — this file and ``conftest.py`` — are both
    outside the population by construction.

    Args:
      source: The module's source text.
      label: How to name the file in an offence string.

    Returns:
      A list of ``<label>:<line>`` strings, empty when the module claims nothing.

    Raises:
      SyntaxError: If the source does not parse.
    """
    offences = []
    for text, start in _prose(source, label):
        for sentence in _SENTENCE.finditer(text):
            body = sentence.group(0)
            claims = (
                _RUN_VERB.search(body)
                and _ALT_MODE.search(body)
                and "pytest" in body.lower()
            )
            if claims or _DIRECT_INVOCATION.search(body):
                head = len(body) - len(body.lstrip())
                line = start + text.count(chr(10), 0, sentence.start() + head)
                offences.append(f"{label}:{line}")
    return offences


def test_the_suite_sweep_found_the_files():
    """Guards the guard: a glob that matches nothing makes the check below vacuous."""
    assert len(_TEST_FILES) >= 50, f"only found {len(_TEST_FILES)} test files under {LAMBDAS}"


def test_no_exception_assertion_accepts_anything_at_all():
    """Every ``pytest.raises(Exception)`` must say WHICH exception it means.

    ``match=`` is the normal answer. Where the assertion is deliberately about the type
    being *wrong* — "whatever propagates, it must not be a TransientError" — the ``match=``
    still pins that the propagated error is the one under test rather than an incidental
    failure on the way to it.
    """
    offenders = []
    for path in _TEST_FILES:
        text = path.read_text()
        offenders += [
            f"{path.relative_to(LAMBDAS)}:{text.count(chr(10), 0, match.start()) + 1}"
            for match in _BARE_RAISES.finditer(text)
        ]

    assert not offenders, (
        "pytest.raises(Exception) with no match= accepts an ImportError at cold start, "
        f"which is how SPEC-137 stayed invisible for nine days: {offenders}"
    )


def test_the_suite_sweep_reaches_every_directory_that_holds_a_suite():
    """Guards the guard, in the direction a count cannot see.

    ``test_the_suite_sweep_found_the_files`` above answers "did the glob find anything", and
    a floor cannot answer "did it find everything": this tree has 240 suite files across 101
    directories, so dropping the ``r`` from ``rglob`` still leaves 63 and still clears any
    floor worth writing. Measured — with that one letter removed, a planted ``__main__``
    block in ``lambdas/api/`` was invisible and every test here stayed green. So the control
    is a SET difference against a walk done a different way, not a number.
    """
    expected = {
        pathlib.Path(directory).resolve()
        for directory, _, files in os.walk(LAMBDAS)
        if _is_ours(pathlib.Path(directory).resolve().relative_to(LAMBDAS).parts)
        and any(f.startswith("test_") and f.endswith(".py") for f in files)
    }
    missed = expected - {p.parent for p in _TEST_FILES}

    assert not missed, (
        "the sweep does not reach every directory holding a suite, so an offence in one of "
        f"these is invisible to every check in this file: {sorted(map(str, missed))}"
    )


def test_no_test_module_ships_its_own_runner():
    """No suite file carries an ``if __name__ == "__main__":`` block.

    pytest is the only runner this repo has, and a second one in the file is not merely
    dead. That matters more here than it would elsewhere: ``ci.yml``'s ``Test (pytest)`` step
    is commented out, so a session's own local run is the only place these suites execute at
    all, and a second runner reporting a pass there is answerable to nothing. Python defines a
    module top to bottom, so a block that loops over ``globals()`` collecting ``test_*``
    cannot see anything defined BELOW itself, and it then exits. Measured before this guard
    existed: ``control-plane-common/test_ddl_cpcommon.py`` printed "2/2 passed" and exited 0
    while the two DDL apostrophe-injection guards defined under the block were never
    collected. A runner that cannot see its own population reports a pass over the half it
    found.

    29 of the 92 blocks removed with this guard were that shape. The other 63 called
    ``pytest.main([__file__])``, which collects the file properly and was merely a second
    way to spell one pytest run — dead by disuse rather than unsound, and gone for the same
    reason: two runners means one of them is the one nobody checks.
    """
    offenders = []
    for path in _TEST_FILES:
        offenders += _runner_offences(path.read_text(), path.relative_to(LAMBDAS))

    assert not offenders, (
        "a suite file branches on being run as a script; pytest is the only runner, and a "
        "second one that loops over globals() reports a pass over the part of the file it "
        f"could see and exits 0 on the rest: {offenders}"
    )


def test_no_suite_advertises_a_run_mode_it_does_not_have():
    """No docstring offers a way to run the file that nothing supports.

    The claim outlived the capability. Each per-file ``sys.path.insert`` adds the file's OWN
    domain package, while the verb under test imports ``cpcommon`` from
    ``control-plane-common`` — which only ``lambdas/conftest.py`` puts on the path, and that
    does not run in direct mode. Measured across the 92 files that carried a runner: 35 died
    at ``ModuleNotFoundError`` before reaching a single assertion, and 72 files advertised
    the mode in their docstrings regardless.
    """
    offenders = []
    for path in _TEST_FILES:
        offenders += _claim_offences(path.read_text(), path.relative_to(LAMBDAS))

    assert not offenders, (
        "a suite that advertises a run mode nobody supports sends the next reader to a "
        f"ModuleNotFoundError, or to a runner that silently skips half the file: {offenders}"
    )


def test_the_runner_check_fires_and_stays_quiet_on_the_right_things():
    """Corpus for the runner check, over both the offences and the silences.

    The offences are four spellings of one guard, because the check reads the CONDITION and
    a check that compared rendered text would pass on three of them. The silences carry the
    other half: this file is the one place a ``__main__`` block may be WRITTEN ABOUT, so a
    check matching text rather than syntax would redden on its own documentation and the
    natural fix would be to weaken it.
    """
    offends = [
        'if __name__ == "__main__":\n    run()\n',
        "if '__main__' == __name__:\n    run()\n",
        'if __name__ in ("__main__",):\n    run()\n',
        'if __name__ == "__main__" and len(sys.argv) > 1:\n    run()\n',
        'def f():\n    pass\n\n\nif __name__ == "__main__":\n    f()\n',
        'with open("f") as h:\n    if __name__ == "__main__":\n        f()\n',
    ]
    for source in offends:
        assert _runner_offences(source, "x.py"), f"missed a runner in {source!r}"

    silent = [
        'DOC = "if __name__ == \'__main__\': is what this guard refuses"\n',
        '"""A docstring naming if __name__ == "__main__": in prose."""\n',
        "if __name__ == 'not_main':\n    pass\n",
        "if OTHER == '__main__':\n    pass\n",
        "def test_x():\n    assert True\n",
    ]
    for source in silent:
        assert not _runner_offences(source, "x.py"), f"false positive on {source!r}"


def test_the_claim_check_fires_and_stays_quiet_on_the_right_things():
    """Corpus for the run-mode claim check, over both the offences and the silences.

    Every case is fed as a MODULE, docstring and all, because the check reads a module's
    prose rather than its text and a bare string would exercise neither the docstring
    extraction nor the boundary that ends one. Each offending sentence is placed in a module
    that also imports pytest, which is what the real files look like.

    The first seven offences are real docstring shapes this repo carried. The rest are shapes
    it does not contain yet — a verb this codebase has not used, an interpreter spelled
    without the 3, a path in front of the filename, and the three tokens in an order no
    docstring here happened to pick. Each was an escape at some point in this check's life,
    and a fence resting on prose that happens not to exist yet is not a fence.

    The silences are the half that keeps the check honest, and three of them exist because
    this check once failed them. one silence is the shape that ends with a period and the
    closing quotes on the same line — a period followed by a quote is not a sentence boundary, so a scan over file TEXT ran the
    chunk on into the module body and borrowed the ``pytest`` from an import two lines down;
    505 docstrings in this tree have that shape and two were one word from reddening. The
    four prohibitions are the sentences a future author is most likely to write about this
    very policy, and refusing those would make the guard argue against its own documentation.
    The rest are real prose from suites that never claimed anything, plus three pinning the
    ``pytest`` requirement, the run-VERB requirement and the sentence boundary — each
    confirmed to be the only thing pinning its clause by deleting the clause and watching the
    rest of this corpus stay green.
    """
    def module(prose):
        return f'"""{prose}"""\n\nimport pytest\n\n\ndef test_x():\n    assert pytest\n'

    offends = [
        "Runnable under pytest or directly: python3 test_guard_arcommon.py.",
        "Runnable under pytest OR directly: ``python3 test_apply_refresh.py``.",
        "Runnable under pytest or directly.",
        "Runs under pytest or as a plain script (`python3 test_x.py`); the JS CI does not.",
        "Runnable as a plain script or under pytest; the layer is added to sys.path.",
        "terminal/transient routing. Runnable under pytest or directly:\npython3 test_a.py.",
        "The `python3 test_infer_schema.py` mode this file used to advertise.",
        "Under pytest this file can also be run directly.",
        "Executable under pytest or directly.",
        "Runs under pytest or as a standalone script.",
        "Invoked directly or under pytest.",
        "Run it with python test_x.py.",
        "Run it with python3 lambdas/table-builder-execute-ddl/test_execute_ddl.py.",
        "Runs under pytest or as a plain script (`python3 test_x.py`); the JS CI does not\nrun Python.",
        "Do not run this file directly; pytest is the only runner.",
        "It does not need pytest; run it directly with python3 test_x.py.",
        "This no longer runs under pytest only; it is runnable directly as well.",
    ]
    for prose in offends:
        assert _claim_offences(module(prose), "x.py"), f"missed a claim in {prose!r}"

    silent = [
        "Runnable under pytest.",
        "Run under pytest, which supplies the cpcommon path and the env baseline.",
        "The shared ignore rules are tested directly against a fake S3 paginator.",
        "`compute_diff` is pure and tested directly against column-list pairs.",
        "``roster`` is also asserted directly against a record that is not a dict.",
        "The readers added for the fleet's second packaging are tested here directly.",
        "The backfill runs directly against the live Glue catalog.",
        "This helper runs directly on the parsed tree, so no file is written.",
        "Under pytest the S3 client is patched directly on ``cpcommon.clients``.",
        "This suite runs under pytest. The fake is patched directly onto the client.",
        "The handler is plain python\ntest_pre_signup.py exercises it end to end.",
    ]
    for prose in silent:
        assert not _claim_offences(module(prose), "x.py"), f"false positive on {prose!r}"


def test_a_one_line_docstring_does_not_borrow_pytest_from_the_code_below_it():
    """The boundary case that a scan over file text gets wrong, kept as its own test.

    A one-line docstring ends with a period and its closing quotes on one line, and a quote
    is not whitespace, so the sentence does not close there. Reading prose rather than text is what fixes it, and this asserts the
    fix at the level it matters: a real module whose docstring says "runs directly" and whose
    body imports pytest two lines down. Separate from the corpus above because it is about
    where a sentence ENDS rather than about what one says, and because the corpus feeds every
    case through the same wrapper, which would hide a regression in the wrapper itself.
    """
    borrowed = '"""Runs directly, bypassing the module under test."""\n\nimport pytest\n'
    assert not _claim_offences(borrowed, "x.py")

    no_period = '"""Runs directly, bypassing the module under test"""\n\nimport pytest\n'
    assert not _claim_offences(no_period, "x.py")

    real_claim = '"""Runnable under pytest or directly."""\n\nimport pytest\n'
    assert _claim_offences(real_claim, "x.py"), "the positive control stopped firing"


def test_the_claim_check_reads_every_prose_surface_it_claims_to():
    """``_prose`` yields docstrings AND comments, at every nesting depth.

    Split out because the corpus above feeds every case as a MODULE docstring, which pins one
    surface and vouches for the rest. Measured before this existed: making ``_prose`` skip
    comments entirely, and making it read module docstrings only, both left all eight tests
    in this file green. A comment is the surface that matters most now — "run it with python3
    test_x.py" is exactly the note a future author leaves beside a fixture, not in a
    docstring.
    """
    claim = "Runnable under pytest or directly."
    surfaces = {
        "module docstring": f'"""{claim}"""\n',
        "comment": f"# {claim}\n",
        "function docstring": f'def f():\n    """{claim}"""\n',
        "method docstring": f'class C:\n    def m(self):\n        """{claim}"""\n',
        "nested function docstring": f'def outer():\n    def inner():\n        """{claim}"""\n',
        "class docstring": f'class C:\n    """{claim}"""\n',
    }
    for name, source in surfaces.items():
        assert _claim_offences(source, "x.py"), f"{name} is not read"

    # The control: the same modules with nothing to find must stay quiet, or the assertions
    # above would pass on a checker that flags every file it is handed.
    for name, source in surfaces.items():
        assert not _claim_offences(source.replace(claim, "Asserts the type rules."), "x.py"), name


def test_an_offence_is_reported_at_the_line_the_sentence_starts_on():
    """The line number has to land on the claim, not near it.

    ``_SENTENCE``'s ``[^.]`` swallows the newline that separates two sentences, so a match
    starts BEFORE the break and a naive newline count is short by one — measured, 38 of the
    70 real offences in this fleet were reported a line or more above the sentence, pointing
    at unrelated prose. Counting to the first non-whitespace character of the match is the
    fix, and this is what says it stayed fixed.
    """
    module_second_sentence = '"""Asserts the type rules.\n\nRunnable under pytest or directly.\n"""\n'
    assert _claim_offences(module_second_sentence, "x.py") == ["x.py:3"]

    deep_in_a_function = (
        'def f():\n    """Summary.\n\n    Some prose about the fake.\n\n'
        '    Runnable under pytest or directly.\n    """\n'
    )
    assert _claim_offences(deep_in_a_function, "x.py") == ["x.py:6"]

    in_a_comment = "x = 1\n\n\n# Runnable under pytest or directly.\n"
    assert _claim_offences(in_a_comment, "x.py") == ["x.py:4"]
