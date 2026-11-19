"""Test helper: what a plane's failure notifier receives when a given state's Catch fires.

A notifier test that builds the failure input by hand proves the notifier reads what the test wrote,
not what the machine sends. This walks the plane's own ASL instead, from a state's ``States.ALL``
Catch to ``NotifyFailure``, applying each state it passes through, so a marker the machine stops
writing — or a seed that stops carrying it — fails the notifier's test rather than passing it.

Only the shapes the failure path uses are interpreted: a Catch's ``ResultPath``, a Pass with a
``Result`` and a ``ResultPath``, a Pass with ``Parameters`` reading ``$.key`` or the context
object's ``$$.Execution.Input``, a Choice whose rules test a top-level ``$.key`` with
``IsPresent`` or ``StringEquals`` (alone or under ``And``), and a Task with ``ResultPath: null``,
which hands its input on unchanged. Anything else raises, so the walk cannot silently skip a state
it does not understand — and so does a read Step Functions would fail on: a comparison on an
absent key is an uncatchable States.Runtime there, so it is a ``KeyError`` here rather than a quiet
no-match.
"""

import copy
import json
import pathlib
import re

_INFRA = pathlib.Path(__file__).resolve().parents[1] / "infra" / "planes"


def machine(plane: str) -> dict:
    """Parses a plane's rendered ASL, substituting the template's placeholders.

    Args:
      plane: The plane's directory under ``infra/planes``.

    Returns:
      The ``States`` map.

    Raises:
      None.
    """
    text = (_INFRA / plane / "state-machine.asl.json.tftpl").read_text()
    return json.loads(re.sub(r"\$\{[^}]+\}", "1", text))["States"]


def _put(state: dict, path: str, value) -> dict:
    """Writes a value at a JSONPath of the ``$.a.b`` form, as a ResultPath does.

    Args:
      state: The state input.
      path: The ResultPath.
      value: What lands there.

    Returns:
      The new state.

    Raises:
      ValueError: For a path this helper does not interpret.
    """
    if path == "$":
        return copy.deepcopy(value)
    if not path.startswith("$."):
        raise ValueError(f"unsupported ResultPath {path!r}")
    out = copy.deepcopy(state)
    node = out
    *parents, leaf = path[2:].split(".")
    for key in parents:
        node = node[key]
    node[leaf] = copy.deepcopy(value)
    return out


def _parameters(params: dict, state: dict, execution_input) -> dict:
    """Evaluates a Pass state's ``Parameters`` against its input.

    Args:
      params: The Parameters block.
      state: The state input.
      execution_input: What ``$$.Execution.Input`` reads.

    Returns:
      The Pass state's output.

    Raises:
      ValueError: For a reference this helper does not interpret.
      KeyError: For a ``$.key`` the input lacks, which is what Step Functions raises as an
        uncatchable States.Runtime.
    """
    out = {}
    for key, value in params.items():
        if not key.endswith(".$"):
            out[key] = copy.deepcopy(value)
        elif value == "$$.Execution.Input":
            out[key[:-2]] = copy.deepcopy(execution_input)
        elif re.fullmatch(r"\$\.[A-Za-z]+", value):
            out[key[:-2]] = copy.deepcopy(state[value[2:]])
        elif value == "$":
            out[key[:-2]] = copy.deepcopy(state)
        else:
            raise ValueError(f"unsupported Parameters reference {value!r}")
    return out


def _matches(rule: dict, state: dict) -> bool:
    """Evaluates one Choice rule against the state.

    Args:
      rule: A Choice rule: ``And`` over sub-rules, or one comparison on a ``$.key`` variable.
      state: The state input the Choice reads.

    Returns:
      Whether the rule holds.

    Raises:
      ValueError: For a rule this helper does not interpret.
      KeyError: For a comparison on a key the state lacks, which Step Functions raises as an
        uncatchable States.Runtime.
    """
    if "And" in rule:
        return all(_matches(sub, state) for sub in rule["And"])
    variable = rule.get("Variable", "")
    if not re.fullmatch(r"\$\.[A-Za-z]+", variable):
        raise ValueError(f"unsupported Choice variable {variable!r}")
    key = variable[2:]
    if "IsPresent" in rule:
        return (key in state) == rule["IsPresent"]
    if "StringEquals" in rule:
        return state[key] == rule["StringEquals"]
    raise ValueError(f"unsupported Choice rule {rule!r}")


def notify_failure_input(plane: str, failing: str, state: dict, error: dict, execution_input):
    """Returns the input ``NotifyFailure`` receives when ``failing``'s Catch fires.

    Args:
      plane: The plane's directory under ``infra/planes``.
      failing: The state whose ``States.ALL`` Catch fires.
      state: That state's input — the running request object.
      error: The ``{Error, Cause}`` object the Catch places.
      execution_input: The execution's own input, which ``RecordFailure`` reads.

    Returns:
      The object the notifier is invoked with.

    Raises:
      ValueError: When the path passes a state this helper does not interpret, or loops.
    """
    states = machine(plane)
    catch = next(
        c for c in states[failing]["Catch"] if "States.ALL" in c["ErrorEquals"]
    )
    current = _put(state, catch.get("ResultPath", "$"), error)
    name = catch["Next"]
    seen = set()
    while name != "NotifyFailure":
        if name in seen:
            raise ValueError(f"the failure path loops at {name}")
        seen.add(name)
        node = states[name]
        unread = {"InputPath", "OutputPath", "ResultSelector"} & set(node)
        if unread:
            raise ValueError(f"{name} carries {sorted(unread)}, which this helper does not apply")
        if node["Type"] == "Choice":
            chosen = next((c for c in node["Choices"] if _matches(c, current)), None)
            name = chosen["Next"] if chosen else node["Default"]
            continue
        if node["Type"] == "Pass" and "Parameters" in node and "ResultPath" not in node:
            current = _parameters(node["Parameters"], current, execution_input)
        elif node["Type"] == "Pass" and "Result" in node:
            current = _put(current, node["ResultPath"], node["Result"])
        elif node["Type"] == "Task" and "ResultPath" in node and node["ResultPath"] is None:
            pass
        else:
            raise ValueError(f"{name} is not a state this helper interprets")
        name = node["Next"]
    return current
