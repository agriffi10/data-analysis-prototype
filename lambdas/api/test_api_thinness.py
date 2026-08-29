"""The API never lists more than one page, and the sweep that keeps it true.

Arc A moved every operation whose cost grows with object count onto a control plane. A route that
walks a subtree recreates that loop inside a Lambda with a 29-second integration ceiling above it —
**and it works, for small folders, in every test anyone writes.** The failure arrives with the
first user who has a big folder, as a timeout.

So this is a derived sweep over the package rather than a review habit: every `list_objects_v2`
call site is parsed and checked, and no module may import a paginator. SPEC-199 and SPEC-200
inherit it.

The sweep is verified by planting a paginating handler and confirming red — a sweep that resolves
onto the right files and matches nothing looks exactly like a sweep that passes.
"""

import ast
import pathlib

import pytest

API_DIR = pathlib.Path(__file__).parent
PACKAGE_DIRS = (API_DIR / "routes", API_DIR / "apicommon")
LISTING_PAGE_SIZE = 25


def _modules() -> list[pathlib.Path]:
    """Every non-test module the sweep covers.

    Args:
      None.

    Returns:
      The module paths.

    Raises:
      None.
    """
    return [
        path
        for directory in PACKAGE_DIRS
        for path in sorted(directory.glob("*.py"))
        if not path.name.startswith("test_")
    ]


def test_the_sweep_reaches_the_modules_it_claims_to() -> None:
    """The guard-the-guard: a sweep over an empty file list passes vacuously."""
    found = _modules()
    assert len(found) >= 10, f"the sweep resolved onto {len(found)} modules"
    assert any(path.name == "objects_list.py" for path in found)


def test_every_listing_call_is_bounded_and_delimited() -> None:
    """`Delimiter='/'` and a bounded `MaxKeys` on every `list_objects_v2` call site."""
    offenders: list[str] = []
    for module in _modules():
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attribute = getattr(node.func, "attr", None)
            if attribute != "list_objects_v2":
                continue
            # The route builds its request as a dict, so the keywords may be splatted. Either
            # spelling has to be checked, or the sweep passes on the one that is used.
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            splatted = any(kw.arg is None for kw in node.keywords)
            if not splatted and not {"Delimiter", "MaxKeys"} <= keywords:
                offenders.append(f"{module.name}:{node.lineno} lists without Delimiter/MaxKeys")
    assert offenders == []


def test_a_splatted_listing_request_still_declares_both() -> None:
    """The dict a route splats must carry both keys, checked where it is built.

    The call-site check above cannot see inside a `**request` splat, so the one route that builds
    its request as a dict is checked by its literal keys. Without this the sweep is satisfied by
    the splat and proves nothing about the route that actually lists.
    """
    source = (API_DIR / "routes" / "objects_list.py").read_text()
    tree = ast.parse(source)
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and {getattr(key, "value", None) for key in node.keys} >= {"Bucket", "Prefix"}
    ]
    assert literals, "objects_list builds no listing request dict"
    keys = {getattr(key, "value", None) for key in literals[0].keys}
    assert {"Delimiter", "MaxKeys"} <= keys


def test_the_page_size_is_bounded() -> None:
    """`MaxKeys` is the listing page size, not an unbounded read."""
    from routes.objects_list import LISTING_PAGE_SIZE as declared

    assert 0 < declared <= LISTING_PAGE_SIZE


def test_no_module_imports_a_paginator_or_loops_a_continuation_token() -> None:
    """A paginator, or a hand-rolled `while` over `NextContinuationToken`, is the same defect."""
    offenders: list[str] = []
    for module in _modules():
        source = module.read_text()
        if "get_paginator" in source:
            offenders.append(f"{module.name} imports a paginator")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                offenders.append(f"{module.name}:{node.lineno} loops")
    assert offenders == []


@pytest.mark.parametrize(
    "planted",
    [
        "def h(c):\n    c.client.list_objects_v2(Bucket='b', Prefix='p')\n",
        "def h(c):\n    p = c.client.get_paginator('list_objects_v2')\n    return p\n",
        "def h(c):\n    while True:\n        break\n",
    ],
    ids=["unbounded call", "paginator", "loop"],
)
def test_the_sweep_catches_a_planted_paginating_handler(tmp_path, monkeypatch, planted) -> None:
    """Each of the three shapes the sweep forbids is confirmed to redden it.

    Planted rather than argued: a sweep is only worth its runtime if it has been seen to fail.
    """
    fake = tmp_path / "routes"
    fake.mkdir()
    (fake / "planted.py").write_text(planted)
    monkeypatch.setattr("test_api_thinness.PACKAGE_DIRS", (fake,))

    caught = False
    for check in (
        test_every_listing_call_is_bounded_and_delimited,
        test_no_module_imports_a_paginator_or_loops_a_continuation_token,
    ):
        try:
            check()
        except AssertionError:
            caught = True
    assert caught, "the sweep passed over a handler it forbids"
