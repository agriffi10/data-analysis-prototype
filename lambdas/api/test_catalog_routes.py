"""The two Glue routes, and the two shapes a Lake Formation denial takes.

**Both shapes are asserted in this one file, and that is the point of the file.** An
implementation that maps every Lake Formation denial to a 403 handles the Glue half perfectly and
silently converts the Athena half — a FAILED execution whose reason names Lake Formation, on a
200 — into an error envelope. That loses the authored sentence the browser chooses from the
reason, and every test of the first shape still passes.

What cannot be settled here is whether Lake Formation still authorizes the assumed-role session
at all: LF is not modelled by the IAM policy simulator, and every fixture below supplies its own
botocore answer, so these can only prove what they were told. That is a live check, run against
the deployed API, and the spec records it as such.
"""

import json

import pytest
import router
from apicommon import identity
from conftest import bearer

LF_DENIAL = "Insufficient Lake Formation permission(s): Required DESCRIBE on database alice"


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    ``botocore`` is provided by the Lambda runtime and declared as a dependency nowhere, so it is
    absent in CI.
    """

    def __init__(self, code, message=""):
        """Builds the error.

        Args:
          code: The service error code.
          message: The service's own message, which must reach no response body.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": message}}


class StubGlue:
    """A Glue client recording every call and answering from what a test programmed.

    Attributes:
      calls: Each call as ``(operation, kwargs)``, so a test can assert the request and the count.
    """

    def __init__(self, **answers):
        """Builds the stub.

        Args:
          **answers: Operation name to its response, or to an exception it raises.

        Returns:
          None.

        Raises:
          None.
        """
        self._answers = answers
        self.calls = []

    def _answer(self, operation, kwargs):
        """Records one call and produces its answer.

        Args:
          operation: The botocore operation name.
          kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        self.calls.append((operation, kwargs))
        answer = self._answers.get(operation, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get_database(self, **kwargs):
        """Reads one database.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_database", kwargs)

    def get_tables(self, **kwargs):
        """Reads one page of a database's tables.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_tables", kwargs)


class StubAthenaFailure:
    """An Athena client whose execution reached FAILED for a Lake Formation reason.

    The second denial shape. It is a client rather than a fixture constant so the assertion runs
    through the real status route, which is where the shape either survives or does not.
    """

    def __init__(self, reason):
        """Builds the stub.

        Args:
          reason: The engine text the execution failed with.

        Returns:
          None.

        Raises:
          None.
        """
        self._reason = reason

    def get_query_execution(self, **kwargs):
        """Reports the failed execution, written under the bearer's own results prefix.

        The location is the root conftest's user-space bucket, because the route proves the
        execution is the caller's before it answers, and this suite sets no bucket of its own.

        Args:
          **kwargs: The call's arguments.

        Returns:
          A FAILED execution carrying the reason.

        Raises:
          None.
        """
        return {
            "QueryExecution": {
                "Status": {"State": "FAILED", "StateChangeReason": self._reason},
                "ResultConfiguration": {
                    "OutputLocation": "s3://user-bkt/alice/system_settings/athenaresults/e-1.csv"
                },
            }
        }


@pytest.fixture
def glue(monkeypatch):
    """Installs a stub client as the user plane.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      A function taking the stub to install and returning it.

    Raises:
      None.
    """

    def _install(stub):
        """Installs one stub.

        Args:
          stub: The client to serve.

        Returns:
          The stub.

        Raises:
          None.
        """
        monkeypatch.setattr(identity, "user_client", lambda service, acting_as: stub)
        return stub

    return _install


def _body(answer):
    """The parsed response body.

    Args:
      answer: The router's response.

    Returns:
      The decoded body.

    Raises:
      None.
    """
    return json.loads(answer["body"])


class TestTheTwoDenialShapes:
    """FR-008 AC4 — and they are here together because separating them hides the second."""

    def test_a_glue_denial_is_a_403_naming_nothing(self, glue) -> None:
        """Envelope-shaped, with no AWS text in ``detail``."""
        glue(StubGlue(get_database=_ServiceError("AccessDeniedException", LF_DENIAL)))

        answer = router.route("GET", "/v1/catalog/databases/alice", bearer(), "rq")

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"
        assert "Lake Formation" not in answer["body"]
        assert "alice" not in _body(answer)["error"].get("detail", "")

    def test_an_athena_denial_is_a_200_carrying_the_reason(self, glue) -> None:
        """The shape an implementation that maps every LF denial to 403 destroys.

        The call does not fail: the execution reaches FAILED and the reason names Lake Formation,
        which is what the browser reads to choose "You don't have permission to run that query."
        Converted into an error envelope, that sentence becomes unreachable and every such query
        says "Contact the Administrator" instead.
        """
        reason = "Insufficient Lake Formation permission(s): Required SELECT on table x"
        glue(StubAthenaFailure(reason))

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["state"] == "FAILED"
        assert _body(answer)["stateChangeReason"] == reason

    def test_a_denial_on_the_tables_route_is_also_a_403(self, glue) -> None:
        """The forgiving arm below is for an ABSENT database, not for a refused one."""
        glue(StubGlue(get_tables=_ServiceError("AccessDeniedException", LF_DENIAL)))

        answer = router.route("GET", "/v1/catalog/databases/alice/tables", bearer(), "rq", None, {})

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"


class TestGetDatabase:
    """FR-008 AC1."""

    def test_it_returns_the_name(self, glue) -> None:
        """The only field the browser reads."""
        glue(StubGlue(get_database={"Database": {"Name": "alice"}}))

        answer = router.route("GET", "/v1/catalog/databases/alice", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {"name": "alice"}

    def test_an_absent_database_is_a_404(self, glue) -> None:
        """A lookup of one named thing that is not there has nothing else to say."""
        glue(StubGlue(get_database=_ServiceError("EntityNotFoundException", "not found")))

        answer = router.route("GET", "/v1/catalog/databases/nope", bearer(), "rq")

        assert answer["statusCode"] == 404
        assert _body(answer)["error"]["code"] == "NotFound"

    def test_the_name_reaches_glue_exactly_as_the_path_carried_it(self, glue) -> None:
        """No format check and no membership check: this route adds neither.

        A shared space's name is checked on the create path only, and was checked nowhere
        before that, so a rule invented here
        would refuse names the rest of the product accepts.
        """
        stub = glue(StubGlue(get_database={"Database": {"Name": "project_alpha"}}))

        router.route("GET", "/v1/catalog/databases/project_alpha", bearer(), "rq")

        assert stub.calls == [("get_database", {"Name": "project_alpha"})]


class TestListTables:
    """FR-008 AC2 and AC3."""

    def test_an_absent_database_is_an_EMPTY_200_not_a_404(self, glue) -> None:
        """A not-yet-created database is an empty schema browser, never an error banner.

        The workspace lists a space's tables before anything has created any, so the forgiving
        semantics are the shipped behaviour and are moved rather than re-decided.
        """
        glue(StubGlue(get_tables=_ServiceError("EntityNotFoundException", "not found")))

        answer = router.route("GET", "/v1/catalog/databases/nope/tables", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert _body(answer) == {"items": [], "nextToken": None}

    def test_it_maps_a_table_onto_the_wire_shape(self, glue) -> None:
        """Columns, type and location; absent optional fields travel as null."""
        glue(
            StubGlue(
                get_tables={
                    "TableList": [
                        {
                            "Name": "sales",
                            "TableType": "EXTERNAL_TABLE",
                            "StorageDescriptor": {
                                "Columns": [{"Name": "id", "Type": "bigint"}],
                                "Location": "s3://bucket/alice/sales/",
                            },
                        },
                        {"Name": "bare"},
                    ]
                }
            )
        )

        body = _body(
            router.route("GET", "/v1/catalog/databases/alice/tables", bearer(), "rq", None, {})
        )

        assert body["items"][0] == {
            "name": "sales",
            "columns": [{"name": "id", "type": "bigint"}],
            "tableType": "EXTERNAL_TABLE",
            "location": "s3://bucket/alice/sales/",
        }
        assert body["items"][1] == {
            "name": "bare",
            "columns": [],
            "tableType": None,
            "location": None,
        }

    def test_ONE_call_per_request_and_the_walk_stays_in_the_browser(self, glue) -> None:
        """The distinguishing case for the whole surface.

        A server-side ``NextToken`` walk would satisfy every other behavioural test in this file
        and quietly make the API a loop over a user-controlled collection, under a 29-second
        ceiling.
        """
        stub = glue(StubGlue(get_tables={"TableList": [], "NextToken": "more"}))

        body = _body(
            router.route("GET", "/v1/catalog/databases/alice/tables", bearer(), "rq", None, {})
        )

        assert len(stub.calls) == 1
        assert body["nextToken"] == "more"

    def test_the_continuation_token_round_trips_unmodified(self, glue) -> None:
        """Opaque, stored and returned as received."""
        awkward = "a+b/c=="
        stub = glue(StubGlue(get_tables={"TableList": []}))

        router.route(
            "GET", "/v1/catalog/databases/alice/tables", bearer(), "rq", None, {"nextToken": awkward}
        )

        assert stub.calls[0][1]["NextToken"] == awkward
