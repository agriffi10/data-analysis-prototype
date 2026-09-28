"""A notification send waits rather than being capped only at the doors where the wait is the point.

Every send is capped in time by default, because nearly all of them run after the outcome they
report and a stall held to the timeout would fail that outcome. Two kinds of caller pass
``bounded=False`` instead, and this holds the set to exactly them, in both directions:

- the DLQ drain, which deletes a message once it has notified, so a stall that holds it to its
  timeout is what leaves the message on its queue for the next sweep;
- every plane's notify-failure, where the run has already failed, so a stall can fail nothing the
  user was told, and on the timed-out door a send held to the timeout fails an asynchronous
  invocation that Lambda retries.

A send anywhere else passing it brings back the stall the cap exists for, and a timed-out door's
send left capped gives up the retry. ``bounded=`` anything but the literal is refused, since it
cannot be read. A door must send through ``emit_notification`` itself: a domain emitter or the
failure decorator would send capped where this cannot see it. **What it cannot see** is a
``**`` splat outside the doors that carries ``bounded=False``.

Attributes:
  LAMBDAS: The tree the sweep reads.
  DRAIN: The DLQ drain's module, relative to ``LAMBDAS``.
"""

import ast
import pathlib

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
DRAIN = "control-plane-dlq-drain/dlq_drain.py"


def waits(source: str) -> list[bool]:
    """Reads, for every ``emit_notification`` call in a module, whether it waits uncapped.

    Args:
      source: The module's text.

    Returns:
      One entry per call, bare or through a module attribute, in source order: True when it
      passes ``bounded=False`` as a literal.

    Raises:
      SyntaxError: If the module does not parse.
    """
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "emit_notification")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "emit_notification")
        )
    ]
    return [
        any(
            k.arg == "bounded" and isinstance(k.value, ast.Constant) and k.value.value is False
            for k in call.keywords
        )
        for call in sorted(calls, key=lambda c: (c.lineno, c.col_offset))
    ]


def other_senders(source: str) -> list[str]:
    """Names every call in a module that could send a notification other than the sender itself.

    Args:
      source: The module's text.

    Returns:
      The name of each call to an ``emit_*`` function other than ``emit_notification``, and of each
      ``notifies_on_failure`` call, decorators included, in source order.

    Raises:
      SyntaxError: If the module does not parse.
    """
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    names = [
        (call, call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", ""))
        for call in sorted(calls, key=lambda c: (c.lineno, c.col_offset))
    ]
    return [
        name
        for _call, name in names
        if (name.startswith("emit_") and name != "emit_notification") or name == "notifies_on_failure"
    ]


def _door_modules():
    """Every production module that belongs to a door.

    Args:
      None.

    Returns:
      Each path relative to ``LAMBDAS``, whether or not it sends.

    Raises:
      None.
    """
    return sorted(
        str(path.relative_to(LAMBDAS))
        for path in LAMBDAS.rglob("*.py")
        if "__pycache__" not in path.parts
        and not path.name.startswith("test_")
        and path.name not in ("conftest.py", "fakes.py")
        and _is_door(str(path.relative_to(LAMBDAS)))
    )


def _sends():
    """Every production module that sends a notification, with whether each send waits.

    Args:
      None.

    Returns:
      ``(path relative to LAMBDAS, [waits per send])`` for each module with at least one send.

    Raises:
      None.
    """
    found = []
    for path in sorted(LAMBDAS.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        if path.name in ("conftest.py", "fakes.py"):
            continue
        sends = waits(path.read_text())
        if sends:
            found.append((str(path.relative_to(LAMBDAS)), sends))
    return found


def _is_door(relative: str) -> bool:
    """Reports whether a module is one whose sends wait.

    Args:
      relative: A module's path relative to ``LAMBDAS``.

    Returns:
      True for the drain and for anything in a ``*-notify-failure`` function's directory.

    Raises:
      None.
    """
    return relative == DRAIN or relative.split("/")[0].endswith("-notify-failure")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("emit_notification(u, m, bounded=False)\n", [True], id="the-literal"),
        pytest.param("notify.emit_notification(u, m, dedup_id=d, bounded=False)\n", [True], id="through-a-module"),
        pytest.param("emit_notification(u, m, bounded=True)\n", [False], id="capped-explicitly"),
        pytest.param("emit_notification(u, m)\n", [False], id="capped-by-default"),
        pytest.param("emit_notification(u, m, bounded=flag)\n", [False], id="a-value-that-cannot-be-read"),
        pytest.param("emit_notifications(u, m, bounded=False)\n", [], id="another-name"),
        pytest.param(
            "emit_notification(a, m)\nemit_notification(b, m, bounded=False)\n", [False, True], id="in-order"
        ),
    ],
)
def test_the_sweep_reads_which_sends_wait(source, expected):
    assert waits(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("notify.emit_failure(event, err, step)\n", ["emit_failure"], id="a-domain-emitter"),
        pytest.param(
            "@notify.notifies_on_failure('x')\ndef h(e, c):\n    return e\n",
            ["notifies_on_failure"],
            id="the-failure-decorator",
        ),
        pytest.param("emit_notification(u, m, bounded=False)\nlog(u)\n", [], id="the-sender-alone"),
    ],
)
def test_the_sweep_names_every_other_way_a_module_could_send(source, expected):
    assert other_senders(source) == expected


def test_every_failure_door_and_the_drain_waits_for_every_send():
    doors = [(path, sends) for path, sends in _sends() if _is_door(path)]

    assert [path for path, sends in doors if not all(sends)] == []


def test_every_door_sends_through_the_sender_and_is_seen_sending():
    """Set equality over the directories, so a door that stopped calling the sender directly — and
    so dropped out of the sweep above — reddens rather than leaving the other doors to pass."""
    sending = {path.split("/")[0] for path, _sends_ in _sends() if _is_door(path)}
    doors = {d.name for d in LAMBDAS.glob("*-notify-failure") if d.is_dir()}

    routed = {path: other_senders((LAMBDAS / path).read_text()) for path in _door_modules()}

    assert {path: names for path, names in routed.items() if names} == {}
    assert DRAIN.split("/")[0] in sending, "the drain no longer sends a notification"
    assert sending == doors | {DRAIN.split("/")[0]}


def test_no_other_send_waits():
    assert [path for path, sends in _sends() if not _is_door(path) and any(sends)] == []
