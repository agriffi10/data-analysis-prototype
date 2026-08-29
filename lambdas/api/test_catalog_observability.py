"""What the catalog spans record, and the two values that must never be among them.

The field rule is *user metadata in, file contents out*, and it binds unusually hard here because
**two** of this surface's values routinely carry a user's own data. A ``WHERE name = 'O''Brien'``
statement IS file contents — the browser interpolates user values into SQL — and Athena quotes the
offending value straight back in ``stateChangeReason`` (``Cannot cast VARCHAR 'O''Brien' to
INTEGER``). Both look exactly like good telemetry, which is why they are asserted absent rather
than trusted to stay absent.

The sweeps in this file are the other half of the spec's claim that the API understands no SQL.
A route that split a statement, scanned it for a semicolon or matched a keyword would be the
second SQL lexer this product has refused to grow.
"""

import ast
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import handler as api_handler
from apicommon import identity
from conftest import bearer
from test_athena_routes import StubAthena

API_DIR = pathlib.Path(__file__).parent
ROUTE_MODULES = sorted((API_DIR / "routes").glob("*.py"))

CELL_SENTINEL = "o-brien-9f3a2c7e"
SQL_SENTINEL = "customer_secret_column"

SQL_KEYWORDS = (
    "SELECT",
    "INSERT",
    "UPDATE ",
    "DELETE FROM",
    "CREATE TABLE",
    "CREATE VIEW",
    "DROP TABLE",
    "ALTER TABLE",
    "UNION",
    "WHERE",
)

STATEMENT_METHODS = frozenset(
    {
        "split",
        "rsplit",
        "splitlines",
        "partition",
        "rpartition",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "upper",
        "lower",
        "startswith",
        "endswith",
        "find",
        "index",
        "count",
    }
)


@pytest.fixture(autouse=True)
def _athena_environment(monkeypatch):
    """The start route's two required values.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("ATHENA_WORKGROUP", "dat-prod-portal-wg")
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")


def _event(method, path, body=None, query=None):
    """One API Gateway payload-format-2.0 request.

    Args:
      method: The HTTP method.
      path: The request path.
      body: The request body, or None.
      query: The query string parameters, or None.

    Returns:
      The event.

    Raises:
      None.
    """
    event = {
        "requestContext": {"http": {"method": method, "path": path}, "requestId": "rq"},
        "headers": bearer(),
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = query
    return event


def test_the_sql_statement_is_never_a_field_value(monkeypatch, captured_events) -> None:
    """Only its length is. The obvious wrong implementation stamps the request body.

    It would look like good telemetry, and it would put every value a user typed into a filter —
    a name, an account number, a free-text note — into a store retained forever.

    Args:
      monkeypatch: Pytest's patcher.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If the statement reaches any record, or its length reaches none.
    """
    monkeypatch.setattr(
        identity, "user_client", lambda service, acting_as: StubAthena(
            start_query_execution={"QueryExecutionId": "e-1"}
        )
    )
    statement = f"SELECT {SQL_SENTINEL} FROM t WHERE name = '{CELL_SENTINEL}'"

    api_handler.handler(_event("POST", "/v1/queries", {"sql": statement}), None)

    serialised = json.dumps(captured_events.events)
    assert SQL_SENTINEL not in serialised
    assert CELL_SENTINEL not in serialised
    assert '"sql_bytes": ' in serialised


def test_the_engine_reason_is_never_a_field_value(monkeypatch, captured_events) -> None:
    """Athena quotes the offending value back, so the reason is file contents by the same rule.

    The span carries ``state`` alone. The reason still travels on the response body, where the
    browser needs it — this is about what is written to the operator store, not about what the
    caller receives.

    Args:
      monkeypatch: Pytest's patcher.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If the reason reaches any record, or the state reaches none.
    """
    reason = f"Cannot cast VARCHAR '{CELL_SENTINEL}' to INTEGER"
    monkeypatch.setattr(
        identity,
        "user_client",
        lambda service, acting_as: StubAthena(
            get_query_execution={
                "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": reason}}
            }
        ),
    )

    answer = api_handler.handler(_event("GET", "/v1/queries/e-1"), None)

    assert CELL_SENTINEL in answer["body"]
    serialised = json.dumps(captured_events.events)
    assert CELL_SENTINEL not in serialised
    assert '"state": "FAILED"' in serialised


def test_result_cells_and_column_names_are_never_field_values(
    monkeypatch, captured_events
) -> None:
    """Counts, not contents — on the precedent the directory route set with ``username_count``.

    Args:
      monkeypatch: Pytest's patcher.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If a cell or a column name reaches a record, or the counts do not.
    """
    monkeypatch.setattr(
        identity,
        "user_client",
        lambda service, acting_as: StubAthena(
            get_query_results={
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": SQL_SENTINEL, "Type": "varchar"}]},
                    "Rows": [{"Data": [{"VarCharValue": CELL_SENTINEL}]}],
                }
            }
        ),
    )

    api_handler.handler(_event("GET", "/v1/queries/e-1/results", query={}), None)

    serialised = json.dumps(captured_events.events)
    assert CELL_SENTINEL not in serialised
    assert SQL_SENTINEL not in serialised
    assert '"row_count": 1' in serialised
    assert '"column_count": 1' in serialised


def test_each_catalog_request_stamps_the_actor_the_route_and_its_execution(
    monkeypatch, captured_events
) -> None:
    """The attribution that IS the mitigation for the preserved ownership exposure.

    Athena authorizes by workgroup and this deployment has one, so a caller holding another
    user's execution id can read it. No ownership check is added here — a real one needs a record
    that does not exist — so a cross-user read being attributable in the log store is the entire
    mitigation this ships, and saying so is the point.

    Args:
      monkeypatch: Pytest's patcher.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three fields is missing.
    """
    monkeypatch.setattr(
        identity, "user_client", lambda service, acting_as: StubAthena(stop_query_execution={})
    )

    api_handler.handler(_event("POST", "/v1/queries/e-42/stop"), None)

    fields = [event.get("fields", {}) for event in captured_events.events]
    assert any(field.get("actor") == "alice" for field in fields)
    assert any(field.get("route_id") == "athena.stop" for field in fields)
    assert any(field.get("execution_id") == "e-42" for field in fields)


def test_no_record_carries_an_email_address(monkeypatch, captured_events) -> None:
    """On any path. The username is the identifier everywhere; an email is never one.

    Args:
      monkeypatch: Pytest's patcher.
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If anything email-shaped reaches a record.
    """
    monkeypatch.setattr(
        identity,
        "user_client",
        lambda service, acting_as: StubAthena(start_query_execution={"QueryExecutionId": "e-1"}),
    )

    api_handler.handler(_event("POST", "/v1/queries", {"sql": "SELECT 1"}), None)

    assert "@" not in json.dumps(captured_events.events)


def _docstrings(tree: ast.AST) -> set[int]:
    """Every string constant that is a docstring, by node id.

    Excluded from the scan below because **a sweep that fires on prose gets loosened rather than
    heeded** — this repo has already had one report a clean tree while a comment tripped it, and
    the first version of this one flagged its own module docstring for containing the word SELECT.

    Args:
      tree: The parsed module.

    Returns:
      The ids of the docstring nodes.

    Raises:
      None.
    """
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _statement_names(tree: ast.AST) -> set[str]:
    """Every local name a module binds the request's SQL to.

    The receiver rules below key on a name, so a module that renames the statement escapes them:
    ``statement = c.body["sql"]`` then ``statement.strip()`` reads as ordinary string handling.
    Tracking the assignment closes that, and it is the bypass this sweep was found to have.

    Args:
      tree: The parsed module.

    Returns:
      The names that hold the statement, always including ``sql`` itself.

    Raises:
      None.
    """
    names = {"sql"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        source_of = ast.dump(node.value)
        if "'sql'" not in source_of and '"sql"' not in source_of:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def sql_inspection_offenders(source: str, name: str) -> list[str]:
    """Every place one module looks INTO a SQL statement.

    Three shapes, and two of them are narrowed to the STATEMENT rather than stated in general.
    The routes legitimately lowercase an AWS error message to classify it, and a bare "no
    semicolon in any string" rule — which the requirement's own wording invites — flags the
    presigned download's ``Content-Disposition`` header. A sweep that fires on something innocent
    is one somebody loosens rather than heeds, so each rule here names the statement it is about.

    **What this does NOT catch, stated rather than left to be discovered.** A module that reaches
    the statement through something other than a local binding — a function parameter, an
    attribute, a dict passed along — escapes the receiver rules, and a keyword this list does not
    carry escapes the literal rule. It is a tripwire over the shape a port would actually take,
    not a proof. The proof that the API parses no SQL is that it has no reason to: every caller
    that needs to understand a statement is in the browser or on a control plane.

    Args:
      source: The module's source.
      name: The module's name, for the message.

    Returns:
      The offences found, empty when there are none.

    Raises:
      SyntaxError: If the source does not parse.
    """
    tree = ast.parse(source)
    skip = _docstrings(tree)
    held_in = _statement_names(tree)
    offenders: list[str] = []

    def _touches_statement(node: ast.AST) -> bool:
        """Whether an expression reads the statement.

        Args:
          node: The expression to inspect.

        Returns:
          True if it names the statement or subscripts a body for it.

        Raises:
          None.
        """
        rendered = (ast.get_source_segment(source, node) or "").lower()
        return "sql" in rendered or any(
            isinstance(part, ast.Name) and part.id in held_in for part in ast.walk(node)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attribute = getattr(node.func, "attr", None)
            if attribute in STATEMENT_METHODS and _touches_statement(node.func.value):
                offenders.append(f"{name}:{node.lineno} calls {attribute} on the statement")
            if attribute in {"split", "match", "search", "findall", "sub"} and any(
                _touches_statement(argument) for argument in node.args
            ):
                offenders.append(f"{name}:{node.lineno} runs a pattern over the statement")
        if isinstance(node, ast.Subscript) and _touches_statement(node.value):
            offenders.append(f"{name}:{node.lineno} slices the statement")
        if (
            isinstance(node, ast.Compare)
            and any(isinstance(operator, ast.In) for operator in node.ops)
            and _touches_statement(node.comparators[0])
        ):
            offenders.append(f"{name}:{node.lineno} scans the statement")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and any(keyword in node.value.upper() for keyword in SQL_KEYWORDS)
        ):
            offenders.append(f"{name}:{node.lineno} names SQL")

    return offenders


def test_no_route_module_inspects_sql() -> None:
    """FR-002 AC7 and FR-010 AC1 — the API understands no SQL, and a sweep says so.

    Anything that needs to understand a statement lives in the browser or in a control plane. A
    server-side splitter or keyword matcher would be the second SQL lexer this product has
    refused to grow, and the first one nobody could see.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a route module splits, trims or matches a statement.
    """
    assert len(ROUTE_MODULES) >= 8, f"the sweep resolved onto {len(ROUTE_MODULES)} modules"

    offenders = [
        offence
        for module in ROUTE_MODULES
        for offence in sql_inspection_offenders(module.read_text(), module.name)
    ]

    assert offenders == [], offenders


@pytest.mark.parametrize(
    "source",
    [
        "def h(c):\n    return c.body['sql'].split(';')\n",
        "def h(c):\n    sql = c.body['sql']\n    return sql.strip()\n",
        "def h(c):\n    return 'SELECT 1'\n",
        "def h(c):\n    return c.body['sql'].replace(';', '')\n",
        "def h(c):\n    return ';' in c.body['sql']\n",
        "def h(c):\n    statement = c.body['sql']\n    return statement.strip()\n",
        "def h(c):\n    statement = c.body['sql']\n    return statement.split(';')\n",
        "def h(c):\n    return c.body['sql'].partition(';')[0]\n",
        "def h(c):\n    return c.body['sql'].upper().startswith('SEL')\n",
        "def h(c):\n    return c.body['sql'][:6]\n",
        "import re\n\n\ndef h(c):\n    return re.split(';', c.body['sql'])\n",
        "def h(c):\n    return c.body['sql'].find(';')\n",
        "def h(c):\n    return 'ALTER TABLE x'\n",
    ],
    ids=[
        "splits the statement",
        "trims the statement",
        "names a keyword",
        "rewrites the statement",
        "scans the statement for a separator",
        "renames it, then trims",
        "renames it, then splits",
        "partitions it",
        "folds case and matches a prefix",
        "slices it",
        "runs a regex over it",
        "searches it for a separator",
        "names a keyword the first list missed",
    ],
)
def test_the_sql_sweep_catches_every_shape_it_claims_to(source) -> None:
    """Guard-the-guard: a sweep that resolves onto the right files and matches nothing looks green.

    Args:
      source: A planted violation.

    Returns:
      None.

    Raises:
      AssertionError: If the planted violation goes unnoticed.
    """
    assert sql_inspection_offenders(source, "planted.py") != []


def test_the_sweep_does_not_fire_on_prose_or_on_classifying_an_aws_message() -> None:
    """The other half: a sweep that fires on a comment is one somebody loosens.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a docstring naming SQL, or a lowercased AWS message, is reported.
    """
    innocent = (
        '''"""A module that mentions SELECT and a semicolon; in prose."""\n'''
        "def h(exc):\n"
        '    message = str(exc.response["Error"]["Message"]).lower()\n'
        '    header = "attachment; filename=x"\n'
        "    return message, header\n"
    )

    assert sql_inspection_offenders(innocent, "innocent.py") == []


def test_every_catalog_response_forbids_a_cache(monkeypatch) -> None:
    """FR-010 AC3 — the API caches nothing, and nothing between it and the browser may either.

    A cached status makes the poll lie about a terminal state. A cached result page is a
    cross-user disclosure whose first reader sees exactly the right answer, which is what makes it
    silent.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If any catalog response omits ``no-store``.
    """
    monkeypatch.setattr(
        identity,
        "user_client",
        lambda service, acting_as: StubAthena(
            start_query_execution={"QueryExecutionId": "e-1"},
            get_query_execution={"QueryExecution": {}},
            get_query_results={"ResultSet": {}},
            stop_query_execution={},
        ),
    )
    requests = [
        _event("POST", "/v1/queries", {"sql": "SELECT 1"}),
        _event("GET", "/v1/queries/e-1"),
        _event("GET", "/v1/queries/e-1/results", query={}),
        _event("POST", "/v1/queries/e-1/stop"),
    ]

    for event in requests:
        answer = api_handler.handler(event, None)
        assert answer["headers"]["cache-control"] == "no-store", event["requestContext"]["http"]
