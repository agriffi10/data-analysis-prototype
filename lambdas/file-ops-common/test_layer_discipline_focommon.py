"""The layer's own discipline: cpcommon owns the algorithm, this layer owns the tables and wording.

An AST sweep rather than a grep, because the thing being forbidden has a syntactic signature and a
substring search would fire on every docstring that mentions it. Each rule below names the algorithm
it forbids a second copy of, and the sweep carries a guard against going trivially green.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

_PACKAGE = pathlib.Path(__file__).parent / "focommon"

#: Names that would mean an algorithm was re-implemented here rather than called.
#:
#: ``item_name`` is deliberately ABSENT, and that exemption is the one worth stating: it IS a copy
#: of ``fscommon.paths.item_name``, argued in this plane's own paths module — two domain layers are
#: packaged and attached separately, so importing one from the other would merge them to save nine
#: lines. It is nine lines of leaf-name arithmetic with no state, no retry and no conditional write;
#: the rules below are about the algorithms where a divergent second copy is a live defect.
_FORBIDDEN_CALLS = {
    "cas_mutate": "the CAS retry loop belongs to cpcommon.cas",
    "parse_sqs_request": "the SQS envelope parse belongs to cpcommon.events",
    "verified_username": "token verification belongs to cpcommon.auth",
    "copy_batch": "the transfer engine belongs to cpcommon.transfer",
    "write_manifest": "the transfer engine belongs to cpcommon.transfer",
}

#: Attribute chains that would mean this layer talks to AWS directly where a shared module already
#: does. The lock's own reader is the deliberate exception and is asserted separately.
#:
#: ``put_object`` is deliberately ABSENT, and what replaced it is stricter rather than looser. The
#: rule was never "this layer does not write" — it was that a CONDITIONAL write is the lock
#: protocol and belongs to ``cpcommon.lock``. The plan module writes this plane's own artifact at a
#: key that is a pure function of the request id, unconditionally, exactly as the file-send layer
#: owns its own copy-plan write. So the rule below asserts the thing that actually matters: no
#: module here passes a precondition to S3.
_FORBIDDEN_ATTRS = {
    "delete_objects": "this layer performs no deletion",
    "start_execution": "this layer starts nothing",
}

#: The arguments that turn a write into a compare-and-set. One of these anywhere in this layer means
#: the lock protocol has been re-implemented beside the module that binds it.
_CONDITIONAL_WRITE_ARGS = ("IfNoneMatch", "IfMatch", "CopySourceIfMatch")


def _modules():
    """Every module in the layer, parsed.

    Args:
      None.

    Returns:
      A list of ``(path, tree)`` pairs.

    Raises:
      None.
    """
    return [(path, ast.parse(path.read_text())) for path in sorted(_PACKAGE.glob("*.py"))]


def _called_names(tree):
    """Every simple and attribute call name in a module.

    Args:
      tree: The parsed module.

    Returns:
      The set of names called.

    Raises:
      None.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_the_sweep_actually_parsed_the_layer():
    """Guard-the-guard. Every assertion below is a negative, so a glob that stopped matching would
    make the whole file pass while checking nothing."""
    modules = _modules()

    assert len(modules) >= 7, f"only found {len(modules)} modules in {_PACKAGE}"
    assert any(_called_names(tree) for _, tree in modules)


@pytest.mark.parametrize("forbidden,why", sorted(_FORBIDDEN_CALLS.items()))
def test_no_algorithm_is_forked_into_this_layer(forbidden, why):
    """A second copy of a shared algorithm is a second place its bug can be introduced — and for
    the ones named here, the bug is a cross-tenant read, a lost lock or a spoofed actor."""
    for path, tree in _modules():
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

        assert forbidden not in defined, f"{path.name} defines {forbidden!r} — {why}"


@pytest.mark.parametrize("forbidden,why", sorted(_FORBIDDEN_ATTRS.items()))
def test_this_layer_does_not_reach_for_aws_where_a_shared_module_already_does(forbidden, why):
    for path, tree in _modules():
        assert forbidden not in _called_names(tree), f"{path.name} calls {forbidden!r} — {why}"


def test_no_module_makes_a_write_CONDITIONAL():
    """The rule ``put_object`` used to stand in for, asserted directly.

    A plain write of this plane's own artifact is this layer's business; a write carrying a
    precondition is the compare-and-set that decides who holds a space's lock, and a second copy of
    that is a second place a lock can be lost. Asserted over the arguments rather than the call, so
    the plan module's unconditional write passes and a CAS hidden inside it does not.
    """
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            named = {keyword.arg for keyword in node.keywords}

            assert not named.intersection(_CONDITIONAL_WRITE_ARGS), (
                f"{path.name} makes a conditional write — that protocol belongs to cpcommon.lock"
            )


def test_the_only_module_that_writes_is_the_one_that_owns_an_artifact():
    """Guard-the-guard for the rule above: it is a negative, so a layer where nothing writes at all
    would satisfy it while proving nothing. One module writes, it is the plan, and a second one
    appearing is a decision rather than an accident."""
    writers = {path.name for path, tree in _modules() if "put_object" in _called_names(tree)}

    assert writers == {"plan.py"}, f"unexpected writers in this layer: {sorted(writers)}"


def test_the_lock_module_binds_the_shared_protocol_rather_than_repeating_it():
    """The one module that could plausibly have been a copy, and the reason the protocol was
    extracted in the first place. It reads the lock object — that is its injected seam — and does
    nothing else with S3."""
    tree = ast.parse((_PACKAGE / "lock.py").read_text())
    called = _called_names(tree)

    assert "get_object" in called
    assert "acquire" in called and "release" in called
    assert "put_object" not in called


def test_the_package_init_imports_nothing():
    """A shared layer's import-time cost runs for every attaching function whether or not it uses
    the module, and an import-time FAILURE surfaces only at cold start, where no test and no deploy
    can see it."""
    tree = ast.parse((_PACKAGE / "__init__.py").read_text())

    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def test_no_module_reads_the_environment_at_import():
    """This layer cannot fail at import. The shared core reads the environment lazily; a module
    here that called ``os.environ`` at module scope would crash every attaching verb at cold
    start."""
    for path, tree in _modules():
        for node in tree.body:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and inner.attr == "environ":
                    assert isinstance(node, ast.FunctionDef | ast.ClassDef), (
                        f"{path.name} reads the environment at import time"
                    )


def test_no_module_names_a_spec_or_pull_request_number():
    """A reader is standing in the file, not in the project's history: the reason belongs in the
    text, the citation does not."""
    import re

    for path in _PACKAGE.glob("*.py"):
        text = path.read_text()

        assert not re.search(r"SPEC-\d+", text), f"{path.name} cites a spec number"
        assert not re.search(r"\(#\d+\)", text), f"{path.name} cites a PR number"
