"""Every queue consumer takes its actor from the identity block, enumerated rather than listed.

A hand-maintained list of planes rots: the ninth plane gets added to the fleet and not to the
list, and the test keeps passing over a set that no longer describes the system. So the population
is DERIVED from two facts neither of which anyone writes down for this test's benefit — the deploy
table, which decides what is a Lambda at all, and the AST, which decides what consumes a queue
message. A plane that does not deploy does not exist; a plane that deploys and parses a queue
message is in the set automatically.

**The population does not reach every call site, and saying so is the point.**
``notifications_writer`` and ``dlq_drain`` both take an actor and neither calls
``parse_sqs_request`` — the writer reads an SQS event-source batch directly and the drain sweeps
queues itself. They are covered by the residual sweep in ``test_one_jwks_path.py``, which fails if
any module outside the API still calls the old verifier, and by their own suites for what they do
instead. Reading this population as "every consumer" would leave both silently unwatched.

Attributes:
  LAMBDAS: The fleet root.
  PARSE_CALL: The call whose presence defines a queue consumer.
  READER_CALL: The call every one of them must obtain its actor through.
  DEGRADING: The consumers that must NOT raise on a refusal — see ``test_a_timeout_door…``.
  FAIL_CLOSED_MARKER: What a plane's own fail-closed test is named after, so this file can check
    every plane still has one without importing eleven handlers into one process.
  EXPECTED_POPULATION: The cardinality measured when this was written, as a tripwire on the
    derivation rather than as the list itself.
"""

import ast
import json
import pathlib

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
FUNCTIONS = LAMBDAS.parent / ".github" / "lambda-functions.json"

PARSE_CALL = "events.parse_sqs_request"
READER_CALL = "trusted_actor"

#: The four timeout doors. They are ordinary members of the population — they call the reader like
#: everyone else — but their refusal SHAPE is the opposite: a raise here is an async Lambda failure
#: that EventBridge retries, turning one unattributable event into three, so every failure degrades
#: to a logged no-op instead. Named rather than detected, because "returns instead of raising" is
#: not a property an AST sweep can distinguish from a bug.
DEGRADING = frozenset(
    {
        "archive-notify-failure",
        "file-ops-notify-failure",
        "file-send-notify-failure",
        "table-share-notify-failure",
    }
)

EXPECTED_POPULATION = 11


def _deployed_names() -> set[str]:
    """Every function name in the deploy table.

    Read as data from the same table ``test_deploy_matrix`` reads, rather than re-derived: two
    readers of one table are two chances to disagree about what the fleet is.

    Args:
      None.

    Returns:
      The function directory names.

    Raises:
      None.
    """
    return {entry["name"] for entry in json.loads(FUNCTIONS.read_text())}


def _calls(path: pathlib.Path) -> set[str]:
    """Names every call in a module, as ``receiver.attribute`` or a bare name.

    Parsed rather than grepped, matching the shape ``test_one_jwks_path`` established: a substring
    scan cannot tell a call from a docstring saying the call is required, and this file's own
    prose would trip one.

    Args:
      path: The module to parse.

    Returns:
      One entry per call site.

    Raises:
      None.
    """
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                found.add(f"{target.value.id}.{target.attr}")
                found.add(target.attr)
            elif isinstance(target, ast.Name):
                found.add(target.id)
    return found


def _population() -> dict[str, pathlib.Path]:
    """The deployed functions whose own module parses a queue message.

    Args:
      None.

    Returns:
      Function directory name to the module that parses.

    Raises:
      None.
    """
    deployed = _deployed_names()
    found = {}
    for path in sorted(LAMBDAS.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        directory = path.parent.name
        if directory not in deployed:
            continue
        if PARSE_CALL in _calls(path):
            found[directory] = path
    return found


POPULATION = _population()


def test_the_derivation_still_selects_a_real_population() -> None:
    """Guard the guard: a detection gone trivial reads exactly like a clean pass.

    Both directions are asserted. Matching nothing means the AST shape changed under the sweep and
    every claim below became vacuous; matching every deployed function means the parse-call test
    stopped discriminating. The cardinality is the number measured when this was written — a
    change to it is a real change to the fleet and should be read, not silently absorbed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derivation collapsed in either direction.
    """
    deployed = _deployed_names()

    assert POPULATION, "the parse-call detection matched nothing"
    assert len(POPULATION) < len(deployed), (
        "the parse-call detection matched every deployed function and no longer discriminates"
    )
    assert len(POPULATION) == EXPECTED_POPULATION, (
        f"the queue-consumer population is now {sorted(POPULATION)}; if a plane was added or "
        f"removed, update EXPECTED_POPULATION deliberately"
    )
    assert set(POPULATION) >= DEGRADING, (
        f"a named timeout door left the population: {sorted(DEGRADING - set(POPULATION))}"
    )


@pytest.mark.parametrize("name", sorted(POPULATION))
def test_every_queue_consumer_takes_its_actor_from_the_identity_block(name) -> None:
    """One reader, every consumer — the collapse this spec exists to make.

    Args:
      name: The function directory in the derived population.

    Returns:
      None.

    Raises:
      AssertionError: If a consumer resolves its actor some other way.
    """
    assert READER_CALL in _calls(POPULATION[name]), (
        f"{name} parses a queue message but does not obtain its actor through "
        f"cpcommon.actor.{READER_CALL}"
    )


def _body_names(tree: ast.AST) -> set[str]:
    """The local names a module binds its PARSED QUEUE BODY to.

    Derived rather than guessed, and the difference is not cosmetic. The timeout doors also hold
    the state machine's own failure object, which carries a validated ``actor`` the machine put
    there — a legitimate read of a different thing that happens to share a field name. A sweep
    over any plausible receiver name flags it, and "fixing" correct code to satisfy a test is a
    worse outcome than the test not existing.

    Args:
      tree: The module's parsed AST.

    Returns:
      The names assigned from ``parse_sqs_request``.

    Raises:
      None.
    """
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        target = node.value.func
        if isinstance(target, ast.Attribute) and target.attr == "parse_sqs_request":
            names.update(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
    return names


@pytest.mark.parametrize("name", sorted(POPULATION))
def test_no_queue_consumer_reads_the_flat_actor_or_a_token_field(name) -> None:
    """The fallback that passes every well-formed fixture and breaks on the first stale message.

    A raw JWT and a username are both non-empty strings, so a consumer reading the flat field
    beside the block cannot be caught by any fixture-based test — it has to be caught by shape.
    ``idToken`` is the same field under its other name on the four planes that use it.

    Scoped to the parsed body's own binding, which is derived per module: the state machine's
    failure object carries an ``actor`` too, and that one IS the trusted value.

    Args:
      name: The function directory in the derived population.

    Returns:
      None.

    Raises:
      AssertionError: If a consumer still reads a top-level token field off the queue body.
    """
    tree = ast.parse(POPULATION[name].read_text(encoding="utf-8"))
    bodies = _body_names(tree)
    assert bodies, f"{name} parses a queue message but binds it to nothing this can follow"

    fields = {"actor", "idToken"}
    offenders = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in bodies
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in fields
        ):
            offenders.append(f"{node.func.value.id}.get({node.args[0].value!r})")
        if (
            isinstance(node, ast.Subscript)
            and getattr(node.value, "id", "") in bodies
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in fields
        ):
            offenders.append(f"{node.value.id}[{node.slice.value!r}]")

    assert not offenders, (
        f"{name} reads {offenders} off the queue body — the identity block is the only source, "
        "and the flat field holds a raw token on four planes during the cutover"
    )


#: The marker a plane's own suite uses to name its fail-closed test. The behavioural assertion
#: lives THERE rather than here: invoking eleven handlers in one process needs eleven different
#: sys.path shapes, two of them do not resolve their domain layer at all, and three modules share
#: a basename — so the first import wins and a later "pass" can be a different plane's handler.
#: A skip would have hidden the first problem and a wrong-module pass would have been worse.
FAIL_CLOSED_MARKER = "no_identity_block"


@pytest.mark.parametrize("name", sorted(POPULATION))
def test_every_consumer_suite_carries_its_own_fail_closed_test(name) -> None:
    """Each plane proves its own refusal, and this asserts none of them stopped.

    Derived over the population, so a ninth plane arrives here without anyone remembering to add
    it. What this cannot check is whether the test is any good — that is what the per-plane
    assertion on the reason code and the exploding client fixture is for, in the suite that can
    actually build one.

    Args:
      name: The function directory in the derived population.

    Returns:
      None.

    Raises:
      AssertionError: If a consumer's suite has no test naming the fail-closed case.
    """
    suite = sorted((LAMBDAS / name).glob("test_*.py"))
    assert suite, f"{name} ships no test file at all"

    named = [
        path.name
        for path in suite
        if FAIL_CLOSED_MARKER in path.read_text(encoding="utf-8")
    ]

    assert named, (
        f"{name} has no test naming {FAIL_CLOSED_MARKER!r} — every queue consumer must prove it "
        "refuses a message carrying no identity block, with no AWS call made on the way out"
    )


@pytest.mark.parametrize("name", sorted(DEGRADING))
def test_a_timeout_door_degrades_rather_than_raising(name) -> None:
    """The doors are in the population and are the one shape exemption, stated rather than skipped.

    A raise on this path is an async Lambda failure EventBridge retries, so one unattributable
    event becomes three notifications about a failure nobody can be told about. Every failure
    therefore returns an empty attribution and is logged. Asserted as the presence of the
    swallowing handler around the reader, because "returns instead of raising" is what the
    module's own suite proves behaviourally and this sweep can only prove structurally.

    Args:
      name: The timeout-door function directory.

    Returns:
      None.

    Raises:
      AssertionError: If the reader is called outside a try block.
    """
    tree = ast.parse(POPULATION[name].read_text(encoding="utf-8"))
    guarded = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if any(READER_CALL in _names_in(child) for child in node.body):
            guarded = True

    assert guarded, (
        f"{name} calls {READER_CALL} outside a try — a raise here is retried by EventBridge and "
        "one unattributable event becomes three"
    )


def _names_in(node) -> set[str]:
    """Every called name inside one AST subtree.

    Args:
      node: The subtree to walk.

    Returns:
      The called names.

    Raises:
      None.
    """
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            target = child.func
            if isinstance(target, ast.Attribute):
                found.add(target.attr)
            elif isinstance(target, ast.Name):
                found.add(target.id)
    return found


#: The verbs that ESTABLISH an actor, and therefore the ones that can stamp one. Derived from the
#: population by excluding the doors, which recover an actor only to address a notification and
#: emit no span a downstream verb would join on.
STAMPING = sorted(set(POPULATION) - DEGRADING)


@pytest.mark.parametrize("name", STAMPING)
def test_the_identity_rides_every_span_the_verb_emits(name) -> None:
    """``assurance`` and ``delegated_by`` beside ``actor``, as baggage rather than a field.

    Baggage rather than a per-call field because a value present on only one side of a join is
    not a join key: ``stamp`` binds these to the boundary span and every child, which is what
    makes "show me everything this principal kind did" answerable at all.

    **The scope is the verb that reads the block, and stating it plainly is the point.** A
    downstream verb receives the validated context, not the identity block, so it cannot stamp
    what it was never given — and threading the block through the state machine would be a new
    plane behaviour, which this change does not have. So this covers the span tree rooted at the
    read, not literally every span the plane ever emits.

    They are user metadata carrying no token, so the field rule permits them.

    Args:
      name: A verb in the derived population that establishes an actor.

    Returns:
      None.

    Raises:
        AssertionError: If the verb resolves an actor without stamping the identity beside it.
    """
    source = POPULATION[name].read_text(encoding="utf-8")
    tree = ast.parse(source)

    stamped = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stamp"
        ):
            stamped.update(kw.arg for kw in node.keywords if kw.arg)

    assert {"actor", "assurance", "delegated_by"} <= stamped, (
        f"{name} stamps {sorted(stamped)} — the principal KIND has to ride beside the actor, or "
        "a machine principal is indistinguishable from a person in every record"
    )
