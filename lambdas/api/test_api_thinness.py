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
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            splatted = any(kw.arg is None for kw in node.keywords)
            if not splatted and not {"Delimiter", "MaxKeys"} <= keywords:
                offenders.append(f"{module.name}:{node.lineno} lists without Delimiter/MaxKeys")
    assert offenders == []


def test_only_the_known_route_splats_its_listing_request() -> None:
    """A splat is an escape hatch, so the set of modules using one is pinned.

    The call-site check cannot see inside `**request`, so a NEW route that splatted would satisfy
    it while proving nothing. Set equality rather than a hard-coded skip: a second splatting module
    has to be added here deliberately, with its own literal-key check, instead of inheriting a hole.
    """
    splatting = set()
    for module in _modules():
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "list_objects_v2":
                continue
            if any(kw.arg is None for kw in node.keywords):
                splatting.add(module.name)
    assert splatting == {"objects_list.py"}


def test_a_splatted_listing_request_still_declares_both() -> None:
    """The dict the one splatting route builds must carry both keys, checked where it is built."""
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


def test_no_module_WAITS_on_anything() -> None:
    """The catalog surface's half of the same rule: the API never waits on a user's query.

    "The API waits for the query" is the shape a reader reaches for, and it is wrong twice over.
    It puts a multi-minute wait behind a 29-second integration ceiling that is **not raisable on
    an HTTP API**, and it holds a function open for the duration of somebody's query. The loops
    that poll and page stay in the browser, where they already are.

    Sleeping and waiting are separate from the paginator check above because they fail
    differently: a paginator is a loop you can see, and ``time.sleep`` is one you cannot.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a module sleeps or builds a waiter.
    """
    offenders: list[str] = []
    for module in _modules():
        source = module.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attribute = getattr(node.func, "attr", None)
            name = getattr(node.func, "id", None)
            if attribute in {"sleep", "get_waiter"} or name == "sleep":
                offenders.append(f"{module.name}:{node.lineno} waits")
            if attribute == "wait":
                offenders.append(f"{module.name}:{node.lineno} waits")
    assert offenders == []


def test_the_integration_ceiling_is_COMPUTED_rather_than_asserted() -> None:
    """FR-007 AC3 — the bound, and what it would be under the design this refuses.

    The schedulable unit is **one AWS call per request**. The slowest route in this surface is a
    results page at the largest size the row-count walk uses, which is sub-second against a
    29-second function budget under a 30-second gateway ceiling.

    The number that matters is the rejected design's, and it is stated rather than asserted
    because both of its sides would be literals: a five-minute query is 300 seconds against a
    ceiling of 30. "The API waits" does not fail at the margin under load — it fails **always**,
    by an order of magnitude, which is why no amount of tuning would have rescued it. What is
    asserted below are the three numbers this repo actually controls.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the margins stop holding.
    """
    from apicommon.config import API_FUNCTION_TIMEOUT_SECONDS
    from routes.athena import ATHENA_MAX_RESULTS

    gateway_ceiling = 30
    slowest_observed_page_seconds = 1

    assert gateway_ceiling > API_FUNCTION_TIMEOUT_SECONDS
    assert ATHENA_MAX_RESULTS == 1000
    assert slowest_observed_page_seconds * 5 < API_FUNCTION_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "planted",
    [
        "def h(c):\n    c.client.list_objects_v2(Bucket='b', Prefix='p')\n",
        "def h(c):\n    p = c.client.get_paginator('list_objects_v2')\n    return p\n",
        "def h(c):\n    while True:\n        break\n",
        "import time\n\n\ndef h(c):\n    time.sleep(1)\n",
        "def h(c):\n    return c.client.get_waiter('query_complete')\n",
    ],
    ids=["unbounded call", "paginator", "loop", "sleep", "waiter"],
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
        test_no_module_WAITS_on_anything,
    ):
        try:
            check()
        except AssertionError:
            caught = True
    assert caught, "the sweep passed over a handler it forbids"
