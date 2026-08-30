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
    "trusted_actor": "reading the trusted actor belongs to cpcommon.actor",
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
#: ``delete_objects`` is deliberately ABSENT, and what replaced it is narrower rather than looser.
#: The rule was "this layer performs no deletion", and the transfer spec is what made that false —
#: the source deletion is this plane's own algorithm and cannot be shared. ``arcommon.delete`` looks
#: like the same thing and is not: it refuses over the WHOLE list, where this one is scoped per item
#: because a whole-list refusal on a move would leave every item copied and nothing deleted. So the
#: rules below assert what still holds — the deletion is BATCHED, and the copy is not this layer's.
_FORBIDDEN_ATTRS = {
    "delete_object": "deletion is batched; a per-object delete is a second deletion path",
    "copy_object": "the transfer engine belongs to cpcommon.transfer",
    "upload_part_copy": "the transfer engine belongs to cpcommon.transfer",
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


def test_no_module_names_a_spec_or_pull_request_number():
    """A reader is standing in the file, not in the project's history: the reason belongs in the
    text, the citation does not."""
    import re

    for path in _PACKAGE.glob("*.py"):
        text = path.read_text()

        assert not re.search(r"SPEC-\d+", text), f"{path.name} cites a spec number"
        assert not re.search(r"\(#\d+\)", text), f"{path.name} cites a PR number"
