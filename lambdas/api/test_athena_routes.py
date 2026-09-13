"""The four Athena routes, and the assertions that moved here from the browser.

Three of this repo's most expensive lessons live in this surface, and each of them ships GREEN when
it is broken. Results read before an execution finished reached users as "Contact the
Administrator" on an ordinary first load. A SQL NULL collapsed to the empty string destroyed a
distinction no consumer can rebuild. The disclosed SQL is trusted because it is the same bytes
Athena received, and a statement mangled by a ``strip()`` still runs and still looks right.

So the assertions here are on the REASON — the mapped code, the raw body text, the byte
comparison — never on "something failed" or on a call count alone.
"""

import json
import typing

import pytest
import router
from apicommon import contract, identity
from conftest import bearer
from routes import athena as athena_routes


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    ``botocore`` is provided by the Lambda runtime and declared as a dependency nowhere, so it is
    absent in CI: importing it passes on a laptop that happens to have boto3 and fails on the
    runner. The classifier reads ``response["Error"]``, which is all the shape this needs.
    """

    def __init__(self, code, message=""):
        """Builds the error.

        Args:
          code: The service error code.
          message: The service's own message, which must reach no response body and no log field.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": message}}


class StubAthena:
    """An Athena client recording every call and answering from what a test programmed.

    Attributes:
      calls: Each call as ``(operation, kwargs)``, so a test can assert what was sent and HOW
        MANY times — the count is on this client rather than on botocore, because the assumed
        session is cached per container and an ``sts:AssumeRole`` fires on some invocations and
        not others.
    """

    def __init__(self, **answers):
        """Builds the stub.

        Args:
          **answers: Operation name to the response it returns, or to an exception it raises.

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

    def start_query_execution(self, **kwargs):
        """Starts a query.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("start_query_execution", kwargs)

    def get_query_execution(self, **kwargs):
        """Reads an execution's status.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_query_execution", kwargs)

    def get_query_results(self, **kwargs):
        """Reads a page of results.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_query_results", kwargs)

    def get_query_runtime_statistics(self, **kwargs):
        """Reads an execution's runtime statistics.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("get_query_runtime_statistics", kwargs)

    def stop_query_execution(self, **kwargs):
        """Stops an execution.

        Args:
          **kwargs: The call's arguments.

        Returns:
          The programmed response.

        Raises:
          Exception: If the programmed answer is an exception.
        """
        return self._answer("stop_query_execution", kwargs)


@pytest.fixture(autouse=True)
def _athena_environment(monkeypatch):
    """The two values the start route derives from, both required.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("ATHENA_WORKGROUP", "dat-prod-portal-wg")
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")


@pytest.fixture
def athena(monkeypatch):
    """Installs a stub Athena client as the user plane.

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


class TestStart:
    """FR-002 — the wire carries no identity, no bucket and no workgroup."""

    def test_the_wire_has_NOWHERE_to_name_a_user_a_bucket_or_a_workgroup(self, athena) -> None:
        """The strongest form of "the request cannot move the identity": it is refused, not ignored.

        The spec asks for a fixture whose body and query disagree with the claim. The contract
        makes that unexpressible — the body's declared shape is ``{sql, database?}`` and the route
        declares no query at all, so both are 400 before a handler runs. Asserted rather than
        left implicit, because "the field is ignored" and "the field cannot be sent" are different
        guarantees and only one of them survives someone adding a key later.
        """
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        with_body = router.route(
            "POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1", "username": "mallory"}
        )
        with_query = router.route(
            "POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1"}, {"username": "mallory"}
        )

        assert with_body["statusCode"] == 400
        assert _body(with_body)["error"]["code"] == "InvalidRequest"
        assert with_query["statusCode"] == 400

    def test_the_results_location_FOLLOWS_the_verified_claim(self, athena) -> None:
        """Two callers, two prefixes, one route.

        A single-token fixture cannot tell a route reading the claim from one that hard-codes a
        prefix or reads a constant — both pass. Driving two different tokens through the same
        route is what makes the source of the username observable.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer("alice"), "rq", {"sql": "SELECT 1"})
        router.route("POST", "/v1/queries", bearer("bob_smith"), "rq", {"sql": "SELECT 1"})

        assert [call[1]["ResultConfiguration"]["OutputLocation"] for call in stub.calls] == [
            "s3://dat-prod-user-space/alice/system_settings/athenaresults/",
            "s3://dat-prod-user-space/bob_smith/system_settings/athenaresults/",
        ]

    def test_the_workgroup_comes_from_the_environment(self, athena) -> None:
        """A defaulted workgroup would send queries to Athena's own ``primary``.

        Its results location is the account default, which is a write outside the isolation model
        by a query that otherwise succeeds.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert stub.calls[0][1]["WorkGroup"] == "dat-prod-portal-wg"

    def test_an_unset_workgroup_is_a_server_fault_rather_than_a_default(
        self, athena, monkeypatch
    ) -> None:
        """Failing loudly here beats succeeding quietly against the wrong workgroup."""
        monkeypatch.delenv("ATHENA_WORKGROUP")
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 503
        assert _body(answer)["error"]["code"] == "ApiUnavailable"

    def test_no_database_means_the_context_is_ABSENT_not_empty(self, athena) -> None:
        """Queries carry no active database, so every base table is fully qualified.

        A present-but-empty context changes what resolves, which is why the key has to be gone
        rather than blank.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert "QueryExecutionContext" not in stub.calls[0][1]

    def test_a_database_is_sent_when_one_is_given(self, athena) -> None:
        """The two callers that send one are View DDL and a user's own DDL run."""
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route(
            "POST", "/v1/queries", bearer(), "rq", {"sql": "SHOW CREATE TABLE a.b", "database": "a"}
        )

        assert stub.calls[0][1]["QueryExecutionContext"] == {"Database": "a"}

    @pytest.mark.parametrize(
        "statement",
        [
            "SELECT 1\n",
            "\nSELECT 1",
            "SELECT * FROM t WHERE name = 'O''Brien'",
            "SELECT 1 -- a comment",
            "SELECT ';' AS semi",
            "SELECT\t1",
            "SELECT 'café' AS accented",
        ],
        ids=["trailing newline", "leading blank", "doubled quote", "comment", "embedded semicolon", "tab", "non-ascii"],
    )
    def test_the_statement_reaches_athena_BYTE_IDENTICAL(self, athena, statement) -> None:
        """FR-009. The disclosure is trusted because it is the same bytes.

        A statement mangled by a ``strip()`` still runs, still returns rows and still looks right
        in the Generated SQL panel — only the byte comparison catches it.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": statement})

        assert stub.calls[0][1]["QueryString"] == statement

    def test_a_body_naming_a_field_the_contract_does_not_declare_is_REFUSED(self, athena) -> None:
        """Ignoring an unknown key is how a field comes back."""
        athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        answer = router.route(
            "POST",
            "/v1/queries",
            bearer(),
            "rq",
            {"sql": "SELECT 1", "outputLocation": "s3://elsewhere/"},
        )

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_athena_returning_no_execution_id_is_an_INTERNAL_error(self, athena) -> None:
        """It replaces a client-minted code that reached the generic sentence by fallthrough."""
        athena(StubAthena(start_query_execution={}))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 500
        assert _body(answer)["error"]["code"] == "InternalError"

    @pytest.mark.parametrize(
        "message",
        [
            "line 1:8: mismatched input 'FROM'",
            "SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved",
            "parse error at line 2",
        ],
        ids=["mismatched input", "syntax_error", "parse error"],
    )
    def test_a_statement_the_USER_can_fix_gets_its_own_code(self, athena, message) -> None:
        """The generic sentence is for what a user cannot act on, and this is the opposite.

        Athena rejects some statements at submit and accepts others that then fail; the user
        typed the same mistake either way. Under a single ``InvalidRequest`` the first group read
        "Something went wrong. Contact the Administrator." while the second read "There is a
        syntax error in your query" — the same mistake, two sentences, and the unhelpful one for
        the case where the app knows exactly what is wrong.
        """
        athena(StubAthena(start_query_execution=_ServiceError("InvalidRequestException", message)))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELEC 1"})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "QuerySyntaxError"
        assert message not in answer["body"]

    @pytest.mark.parametrize(
        "message",
        ["WorkGroup dat-prod-portal-wg is not found", "The request was not valid"],
        ids=["unusable workgroup", "malformed request"],
    )
    def test_a_refusal_the_user_can_do_NOTHING_about_stays_generic(self, athena, message) -> None:
        """The counter-case, and the reason the classifier reads the message rather than the name.

        An unusable workgroup and a malformed request parameter arrive under the same exception
        name as a bad statement and are an operator's to fix, not a user's. Telling someone to
        check their SQL for a workgroup misconfiguration sends them hunting for a mistake that is
        not there — the failure mode of a rule that maps the whole family to the friendlier
        sentence.
        """
        athena(StubAthena(start_query_execution=_ServiceError("InvalidRequestException", message)))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_a_denial_at_submit_is_still_a_denial(self, athena) -> None:
        """The 400 arm is one exception name wide, not "any failure is a bad request"."""
        athena(StubAthena(start_query_execution=_ServiceError("AccessDeniedException", "no")))

        answer = router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    def test_the_route_makes_exactly_one_call_on_the_athena_client(self, athena) -> None:
        """Counted on THIS client, never on botocore as a whole.

        The assumed session is cached per container, so an ``sts:AssumeRole`` fires on a cold
        invocation and not on a warm one — "one botocore call per request" is unsatisfiable on
        the first request and satisfiable on the second.
        """
        stub = athena(StubAthena(start_query_execution={"QueryExecutionId": "e-1"}))

        router.route("POST", "/v1/queries", bearer(), "rq", {"sql": "SELECT 1"})

        assert len(stub.calls) == 1


class TestStatus:
    """FR-003 — the engine's own text travels verbatim, on a 200."""

    def test_a_FAILED_execution_is_a_200_carrying_the_reason(self, athena) -> None:
        """Mapping it to an error envelope is the change that looks most correct.

        It would retire six authored sentences at once: the browser chooses each of them by
        reading this field, and an envelope has nowhere to put it.
        """
        reason = "Insufficient Lake Formation permission(s): Required SELECT on table x"
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {
                        "Status": {"State": "FAILED", "StateChangeReason": reason},
                        "Statistics": {"DataScannedInBytes": 10, "EngineExecutionTimeInMillis": 5},
                        "ResultConfiguration": {"OutputLocation": OWNED_LOCATION},
                    }
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {
            "queryExecutionId": "e-1",
            "state": "FAILED",
            "stateChangeReason": reason,
            "dataScannedBytes": 10,
            "engineExecutionTimeMillis": 5,
            "outputLocation": OWNED_LOCATION,
        }

    def test_the_reason_is_not_truncated_or_rewritten(self, athena) -> None:
        """A reason truncated at 100 characters is present and still breaks the wording rules."""
        reason = "SYNTAX_ERROR: line 1:8: Column 'foo' cannot be resolved" + " " + "x" * 200
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {
                        "Status": {"State": "FAILED", "StateChangeReason": reason},
                        "ResultConfiguration": {"OutputLocation": OWNED_LOCATION},
                    }
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["stateChangeReason"] == reason

    def test_a_non_terminal_execution_reports_NULL_statistics_never_zero(self, athena) -> None:
        """A confident zero freezes the tab's cost figure at zero for the whole run.

        QUEUED carries its output location already — measured, since the poll starts there and a
        proof that refused a user's own queued query would fail the DDL helpers outright.
        """
        athena(StubAthena(get_query_execution=_execution(state="QUEUED")))

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["dataScannedBytes"] is None
        assert _body(answer)["engineExecutionTimeMillis"] is None

    def test_a_missing_state_defaults_to_QUEUED(self, athena) -> None:
        """As the browser has always done."""
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {"ResultConfiguration": {"OutputLocation": OWNED_LOCATION}}
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["state"] == "QUEUED"

    def test_the_output_location_survives_for_a_succeeded_execution(self, athena) -> None:
        """Export copies that object and Save results parses it."""
        athena(StubAthena(get_query_execution=_execution()))

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer)["outputLocation"] == OWNED_LOCATION

    def test_the_execution_id_comes_from_the_path_and_costs_ONE_call(self, athena) -> None:
        """Reaches botocore unchanged, and exactly once — the proof IS this read.

        The count is list equality rather than an index, because ``calls[0]`` is silent about a
        second call — and a second call here is a doubled bill on a route the browser polls
        every 1.5 seconds.
        """
        stub = athena(
            StubAthena(
                get_query_execution=_execution(
                    location="s3://dat-prod-user-space/alice/system_settings/athenaresults/e-99.csv"
                )
            )
        )

        answer = router.route("GET", "/v1/queries/e-99", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert stub.calls == [("get_query_execution", {"QueryExecutionId": "e-99"})]

    def test_someone_elses_execution_and_an_unknown_one_get_one_byte_identical_404(
        self, athena
    ) -> None:
        """The workgroup lets the caller read any execution by id, so the prefix is the proof.

        The foreign execution FAILED with a reason quoting its owner's cell, which is exactly
        what this route used to hand any caller holding the id.
        """
        cell = "alice_would_never_see_bobs_cell"
        foreign = {
            "QueryExecution": {
                "Status": {"State": "FAILED", "StateChangeReason": f"Cannot cast '{cell}'"},
                "Statistics": {"DataScannedInBytes": 10},
                "ResultConfiguration": {"OutputLocation": FOREIGN_LOCATION},
            }
        }
        bodies = []
        for answer_to_get in (foreign, _unknown_id()):
            athena(StubAthena(get_query_execution=answer_to_get))

            answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

            assert answer["statusCode"] == 404
            assert _body(answer)["error"] == {
                "code": "NotFound",
                "requestId": "rq",
                "detail": athena_routes.EXECUTION_NOT_FOUND_DETAIL,
            }
            bodies.append(answer["body"])

        assert bodies[0] == bodies[1]
        assert cell not in bodies[0]
        assert "FAILED" not in bodies[0]

    @pytest.mark.parametrize(
        "result_configuration",
        [{}, {"OutputLocation": "s3://dat-prod-athena-admin/fallback-results/e-1.csv"}],
        ids=["no location recorded", "the workgroup's own fallback location"],
    )
    def test_an_execution_outside_every_users_prefix_is_not_found(
        self, athena, result_configuration
    ) -> None:
        """A query started without a location lands in the admin bucket, which is nobody's."""
        athena(
            StubAthena(
                get_query_execution={
                    "QueryExecution": {
                        "Status": {"State": "SUCCEEDED"},
                        "ResultConfiguration": result_configuration,
                    }
                }
            )
        )

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 404
        assert _body(answer)["error"]["code"] == "NotFound"

    def test_a_denied_read_is_still_a_403_and_never_a_404(self, athena) -> None:
        """The proof's forgiving arm is one exception name wide.

        Folding a denial into NotFound would make a broken grant read as "no such query" on
        every poll.
        """
        athena(StubAthena(get_query_execution=_ServiceError("AccessDeniedException", "no")))

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    def test_a_throttled_read_rises_to_the_outer_classifier(self, athena) -> None:
        """A fault is not an answer about the execution, so it must not become a 404."""
        athena(StubAthena(get_query_execution=_ServiceError("ThrottlingException", "slow down")))

        with pytest.raises(_ServiceError, match="ThrottlingException"):
            router.route("GET", "/v1/queries/e-1", bearer(), "rq")


class TestResults:
    """FR-004 and FR-005 — the page, the NULL, and the read that came too early."""

    def test_a_null_cell_and_an_empty_one_are_distinct_in_the_RAW_body(self, athena) -> None:
        """Asserted on the response TEXT, not on a parsed structure.

        ``d.get("VarCharValue", "")`` is indistinguishable from the right implementation for
        every non-null cell and for every fixture that has no NULLs — and it destroys what the
        Value panel, the null styling and the copy path all read.
        """
        athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {
                            "ColumnInfo": [{"Name": "a", "Type": "varchar"}, {"Name": "b", "Type": "varchar"}]
                        },
                        "Rows": [{"Data": [{}, {"VarCharValue": ""}]}],
                    }
                },
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert '"rows": [[null, ""]]' in answer["body"]

    def test_the_first_page_overfetches_by_one_and_nets_999_at_the_maximum(self, athena) -> None:
        """The existing arithmetic, moved.

        At 1000 the ``+1`` is clamped away, so page one nets 999 data rows after the header goes.
        Callers number rows from actual page lengths and must keep being allowed to see pages
        that are not uniform.
        """
        stub = athena(
            StubAthena(get_query_execution=_execution(), get_query_results={"ResultSet": {}})
        )

        answer = router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": "1000"}
        )

        assert answer["statusCode"] == 200
        assert _call(stub, "get_query_results")["MaxResults"] == 1000

    def test_a_continuation_page_asks_for_exactly_the_page_size(self, athena) -> None:
        """Only the first page carries Athena's repeated header row."""
        stub = athena(
            StubAthena(get_query_execution=_execution(), get_query_results={"ResultSet": {}})
        )

        answer = router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": "20", "nextToken": "t"}
        )

        assert answer["statusCode"] == 200
        assert _call(stub, "get_query_results")["MaxResults"] == 20

    def test_the_header_row_is_dropped_on_the_first_page_only(self, athena) -> None:
        """Athena repeats the column names as row one of page one of a SELECT."""
        result_set = {
            "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar"}]},
            "Rows": [{"Data": [{"VarCharValue": "a"}]}, {"Data": [{"VarCharValue": "1"}]}],
        }
        athena(StubAthena(get_query_execution=_execution(), get_query_results={"ResultSet": result_set}))

        first = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})
        later = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"nextToken": "t"})

        assert (first["statusCode"], later["statusCode"]) == (200, 200)
        assert _body(first)["rows"] == [["1"]]
        assert _body(later)["rows"] == [["a"], ["1"]]

    def test_a_first_data_row_equal_to_the_header_is_ALSO_dropped(self, athena) -> None:
        """Today's accepted foot-gun, preserved rather than quietly fixed.

        Fixing it is a behaviour change and belongs to whichever spec wants the behaviour.
        """
        athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar"}]},
                        "Rows": [{"Data": [{"VarCharValue": "a"}]}],
                    }
                },
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert _body(answer)["rows"] == []

    def test_a_statement_with_no_result_set_is_an_empty_200(self, athena) -> None:
        """A DDL or CTAS statement produced no rows; that is not an error."""
        athena(StubAthena(get_query_execution=_execution(), get_query_results={}))

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert _body(answer) == {"columns": [], "rows": [], "nextToken": None}

    def test_the_column_type_is_athenas_raw_string(self, athena) -> None:
        """Normalising it is the browser's job and stays there."""
        athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_results={
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "a", "Type": "varchar(255)"}]}
                    }
                },
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 200
        assert _body(answer)["columns"] == [{"name": "a", "type": "varchar(255)"}]

    def test_the_continuation_token_round_trips_unmodified(self, athena) -> None:
        """Over the three characters that break a re-encoder."""
        awkward = "a+b/c=="
        stub = athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_results={"ResultSet": {}, "NextToken": awkward},
            )
        )

        answer = router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"nextToken": awkward}
        )

        assert answer["statusCode"] == 200
        assert _call(stub, "get_query_results")["NextToken"] == awkward
        assert _body(answer)["nextToken"] == awkward

    def test_the_route_makes_exactly_TWO_calls_the_proof_then_the_page(self, athena) -> None:
        """Two properties the other tests here are silent about.

        List equality rather than a count, because the order is the point: the proof reads the
        execution before any page is asked for, and a fixed second call is what this costs. The
        denial arm matters because the classifier this route adds sits in front of it: a Lake
        Formation refusal must fall through to the 403, not be swallowed by the not-finished
        branch.
        """
        stub = athena(
            StubAthena(get_query_execution=_execution(), get_query_results={"ResultSet": {}})
        )
        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})
        assert answer["statusCode"] == 200
        assert _operations(stub) == ["get_query_execution", "get_query_results"]

        denied = athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_results=_ServiceError("AccessDeniedException", "no"),
            )
        )
        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert _operations(denied) == ["get_query_execution", "get_query_results"]
        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    @pytest.mark.parametrize("value", ["0", "1001", "-1", "abc", "1.5"], ids=list("abcde"))
    def test_a_page_size_outside_its_range_is_refused(self, athena, value) -> None:
        """The browser never sends one, which is exactly why the check must exist here.

        Refused before Athena is asked anything, the proof included: the size is about the
        request and says nothing about the execution.
        """
        stub = athena(
            StubAthena(get_query_execution=_execution(), get_query_results={"ResultSet": {}})
        )

        answer = router.route(
            "GET", "/v1/queries/e-1/results", bearer(), "rq", None, {"maxRows": value}
        )

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"
        assert stub.calls == []

    def test_someone_elses_execution_and_an_unknown_one_get_one_404_and_no_page(
        self, athena
    ) -> None:
        """S3 keeps another user's rows from the caller already; this is about what else leaks.

        The foreign execution's page is programmed to say "not yet finished", which is exactly
        what a foreign query still running answered before the proof: a 409, where an unknown id
        answered 400. Ownership before state is what makes the two indistinguishable.
        """
        bodies = []
        for answer_to_get in (_execution(state="RUNNING", location=FOREIGN_LOCATION), _unknown_id()):
            stub = athena(
                StubAthena(
                    get_query_execution=answer_to_get,
                    get_query_results=_ServiceError(
                        "InvalidRequestException", "Query has not yet finished. Current state: RUNNING"
                    ),
                )
            )

            answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

            assert answer["statusCode"] == 404
            assert _operations(stub) == ["get_query_execution"]
            bodies.append(answer["body"])

        assert bodies[0] == bodies[1]

    def test_a_read_before_the_execution_finished_is_409_QueryNotFinished(self, athena) -> None:
        """The condition that reached users as "Contact the Administrator" on a first load."""
        athena(
            StubAthena(
                get_query_execution=_execution(state="QUEUED"),
                get_query_results=_ServiceError(
                    "InvalidRequestException",
                    "Query has not yet finished. Current state: QUEUED",
                ),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 409
        assert _body(answer)["error"]["code"] == "QueryNotFinished"

    def test_a_malformed_query_is_400_InvalidRequest(self, athena) -> None:
        """The counter-case, in the same file as the one above.

        ``InvalidRequestException`` is BOTH conditions' exception name. A mapper keyed on the name
        passes whichever of the two it is shown — which is precisely how the original defect
        survived — so the pair has to be asserted together.
        """
        athena(
            StubAthena(
                get_query_execution=_execution(state="FAILED"),
                get_query_results=_ServiceError(
                    "InvalidRequestException", "line 1:8: mismatched input 'FROM'"
                ),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 400
        assert _body(answer)["error"]["code"] == "InvalidRequest"

    def test_no_athena_message_reaches_the_response_body(self, athena) -> None:
        """The route reads the engine's message to classify and hands on none of it."""
        athena(
            StubAthena(
                get_query_execution=_execution(state="QUEUED"),
                get_query_results=_ServiceError(
                    "InvalidRequestException",
                    "Query has not yet finished. Current state: QUEUED for alice_secret_table",
                ),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/results", bearer(), "rq", None, {})

        assert answer["statusCode"] == 409
        assert "alice_secret_table" not in answer["body"]


OWNED_LOCATION = "s3://dat-prod-user-space/alice/system_settings/athenaresults/e-1.csv"


def _execution(state="SUCCEEDED", statement="DML", substatement="SELECT", location=OWNED_LOCATION):
    """One ``GetQueryExecution`` answer, owned by the bearer's user unless told otherwise.

    Args:
      state: The execution's state.
      statement: Athena's ``StatementType``.
      substatement: Athena's ``SubstatementType``.
      location: The recorded output location.

    Returns:
      The response Athena would give.

    Raises:
      None.
    """
    return {
        "QueryExecution": {
            "Status": {"State": state},
            "StatementType": statement,
            "SubstatementType": substatement,
            "ResultConfiguration": {"OutputLocation": location},
        }
    }


def _statistics(output_rows):
    """One ``GetQueryRuntimeStatistics`` answer, nested exactly as botocore returns it.

    Args:
      output_rows: The ``Rows.OutputRows`` figure.

    Returns:
      The response Athena would give.

    Raises:
      None.
    """
    return {"QueryRuntimeStatistics": {"Rows": {"InputRows": 0, "OutputRows": output_rows}}}


def _operations(stub):
    """The operations a stub was asked for, in order.

    Args:
      stub: The stub Athena client.

    Returns:
      The operation names.

    Raises:
      None.
    """
    return [operation for operation, _ in stub.calls]


def _call(stub, operation):
    """The arguments of the one call a stub received for an operation.

    Picked by NAME rather than by position: the ownership proof now precedes every page and every
    stop, so ``calls[0]`` is the proof's read and silently stops meaning the call under test.

    Args:
      stub: The stub Athena client.
      operation: The botocore operation name.

    Returns:
      That call's keyword arguments.

    Raises:
      AssertionError: If the operation was called other than exactly once.
    """
    matching = [kwargs for name, kwargs in stub.calls if name == operation]
    assert len(matching) == 1, stub.calls
    return matching[0]


FOREIGN_LOCATION = "s3://dat-prod-user-space/bob/system_settings/athenaresults/e-1.csv"


def _unknown_id():
    """What Athena raises for an execution id it does not know, measured against the live API.

    Args:
      None.

    Returns:
      A fresh exception, so no test raises an instance another test already raised.

    Raises:
      None.
    """
    return _ServiceError("InvalidRequestException", "QueryExecution e-1 was not found")


class TestRowCount:
    """A succeeded SELECT's count is Athena's own; anything else says so, or is refused."""

    @pytest.mark.parametrize("output_rows", [10_000_000, 0])
    def test_a_succeeded_select_answers_athenas_own_count(self, athena, output_rows) -> None:
        """Zero is a count, not an absence — a truthiness test would turn it into pending.

        The stub is reachable only as ``identity.user_client``, so the calls on it are the proof
        the statistics were read as the caller rather than as the function.
        """
        stub = athena(
            StubAthena(
                get_query_execution=_execution(),
                get_query_runtime_statistics=_statistics(output_rows),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {"rowCount": output_rows, "pending": False}
        assert stub.calls == [
            ("get_query_execution", {"QueryExecutionId": "e-1"}),
            ("get_query_runtime_statistics", {"QueryExecutionId": "e-1"}),
        ]

    @pytest.mark.parametrize(
        "statistics",
        [
            {"QueryRuntimeStatistics": {"Timeline": {"TotalExecutionTimeInMillis": 8242}}},
            _ServiceError(
                "InvalidRequestException", "Query has not yet finished. Current state: RUNNING"
            ),
        ],
        ids=["the rows block has not landed", "athena still calls it unfinished"],
    )
    def test_a_select_whose_count_has_not_landed_is_pending(self, athena, statistics) -> None:
        """Pending means ask again — never a number that might be partial."""
        athena(StubAthena(get_query_execution=_execution(), get_query_runtime_statistics=statistics))

        answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {"rowCount": None, "pending": True}

    @pytest.mark.parametrize(
        ("statement", "substatement"),
        [
            ("DML", "EXPLAIN"),
            ("UTILITY", "SHOW_TABLES"),
            ("DDL", "CREATE_TABLE"),
            ("UTILITY", "SELECT"),
        ],
    )
    def test_anything_but_a_select_is_not_counted_and_athena_is_not_asked(
        self, athena, statement, substatement
    ) -> None:
        """EXPLAIN is the measured case: its statistics say 1 over a plan the grid shows as 20.

        The statistics stub carries that 1, so a route that keyed on ``StatementType`` alone, or
        asked anyway, would answer it.
        """
        stub = athena(
            StubAthena(
                get_query_execution=_execution(statement=statement, substatement=substatement),
                get_query_runtime_statistics=_statistics(1),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {"rowCount": None, "pending": False}
        assert _operations(stub) == ["get_query_execution"]

    @pytest.mark.parametrize(
        ("error", "status", "code"),
        [
            (_ServiceError("AccessDeniedException", "no"), 403, "AccessDenied"),
            (_ServiceError("InvalidRequestException", "Rate exceeded"), 400, "InvalidRequest"),
        ],
        ids=["a denied statistics call", "an unrelated refusal"],
    )
    def test_a_statistics_refusal_other_than_unfinished_is_an_error_not_pending(
        self, athena, error, status, code
    ) -> None:
        """Pending is asked again and then walked, so a lost grant read as pending is a silent cost."""
        athena(StubAthena(get_query_execution=_execution(), get_query_runtime_statistics=error))

        answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

        assert answer["statusCode"] == status
        assert _body(answer)["error"]["code"] == code

    @pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "FAILED", "CANCELLED"])
    def test_an_execution_that_has_not_succeeded_is_a_409_and_athena_is_not_asked(
        self, athena, state
    ) -> None:
        """Only a SUCCEEDED count is whole: a running one is partial, a stopped one is truncated."""
        stub = athena(
            StubAthena(
                get_query_execution=_execution(state=state),
                get_query_runtime_statistics=_statistics(5),
            )
        )

        answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

        assert answer["statusCode"] == 409
        assert _body(answer)["error"]["code"] == "QueryNotFinished"
        assert _operations(stub) == ["get_query_execution"]

    def test_someone_elses_execution_is_indistinguishable_from_an_unknown_one(self, athena) -> None:
        """The workgroup lets the caller read any execution by id, so the prefix is the proof.

        The foreign RUNNING and EXPLAIN executions pin the ORDER: the proof runs before the state
        check and the statement check, so neither can tell the caller that bob's query is still
        running or what kind it is. With the proof moved below either check, those two answer 409
        and 200 and this test fails.
        """
        bob = "s3://dat-prod-user-space/bob/system_settings/athenaresults/e-1.csv"
        bodies = []
        for answer_to_get in (
            _execution(location=bob),
            _execution(state="RUNNING", location=bob),
            _execution(substatement="EXPLAIN", location=bob),
            _execution(
                location="s3://dat-prod-user-space/alice/system_settings/athenaresults/../../bob/e-1.csv"
            ),
            _ServiceError("InvalidRequestException", "QueryExecution e-1 was not found"),
        ):
            stub = athena(
                StubAthena(
                    get_query_execution=answer_to_get,
                    get_query_runtime_statistics=_statistics(5),
                )
            )

            answer = router.route("GET", "/v1/queries/e-1/row-count", bearer(), "rq")

            assert answer["statusCode"] == 404
            assert _operations(stub) == ["get_query_execution"]
            bodies.append(answer["body"])

        assert len(set(bodies)) == 1, bodies


class TestStop:
    """The proof, then the stop — and nothing stopped that is not the caller's."""

    def test_the_caller_own_execution_is_proved_then_stopped_by_the_path_id(self, athena) -> None:
        """Two calls, in this order, both carrying only the path's id.

        Athena authorizes the stop by WORKGROUP and there is one, so without the read in front a
        caller holding another user's execution id could stop that user's query.
        """
        stub = athena(StubAthena(get_query_execution=_execution(state="RUNNING"), stop_query_execution={}))

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 200
        assert _body(answer) == {}
        assert stub.calls == [
            ("get_query_execution", {"QueryExecutionId": "e-7"}),
            ("stop_query_execution", {"QueryExecutionId": "e-7"}),
        ]

    def test_stopping_an_already_terminal_execution_is_a_success(self, athena) -> None:
        """The poller observes the terminal state either way, and today's caller swallows this."""
        athena(
            StubAthena(
                get_query_execution=_execution(),
                stop_query_execution=_ServiceError(
                    "InvalidRequestException", "Query has already completed"
                ),
            )
        )

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 200

    def test_a_denial_is_still_a_denial(self, athena) -> None:
        """The forgiving arm is one exception name wide, not "any failure is fine"."""
        athena(
            StubAthena(
                get_query_execution=_execution(state="RUNNING"),
                stop_query_execution=_ServiceError("AccessDeniedException", "no"),
            )
        )

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 403
        assert _body(answer)["error"]["code"] == "AccessDenied"

    def test_a_denied_proof_is_a_403_and_nothing_is_stopped(self, athena) -> None:
        """A denial on the read is a denial, and it never reaches the stop."""
        stub = athena(
            StubAthena(
                get_query_execution=_ServiceError("AccessDeniedException", "no"),
                stop_query_execution={},
            )
        )

        answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

        assert answer["statusCode"] == 403
        assert _operations(stub) == ["get_query_execution"]

    def test_someone_elses_query_is_never_stopped_and_answers_like_an_unknown_one(
        self, athena
    ) -> None:
        """The exposure this route carried: any holder of the id could cancel the owner's query."""
        bodies = []
        for answer_to_get in (_execution(state="RUNNING", location=FOREIGN_LOCATION), _unknown_id()):
            stub = athena(StubAthena(get_query_execution=answer_to_get, stop_query_execution={}))

            answer = router.route("POST", "/v1/queries/e-7/stop", bearer(), "rq")

            assert answer["statusCode"] == 404
            assert _operations(stub) == ["get_query_execution"]
            bodies.append(answer["body"])

        assert bodies[0] == bodies[1]


EXECUTION_ROUTES = [route for route in contract.ROUTES if "{queryExecutionId}" in route.path]


def _field_names(shape):
    """Every field name a declared request or query shape carries, nested shapes included.

    Args:
      shape: A contract TypedDict, or None for a route that declares none.

    Returns:
      The field names, in no particular order.

    Raises:
      None.
    """
    names = []
    seen = set()

    def walk(hint):
        """Collects one hint's field names and descends into its arguments.

        Args:
          hint: A type hint.

        Returns:
          None.

        Raises:
          None.
        """
        if isinstance(hint, type) and hasattr(hint, "__required_keys__") and hint not in seen:
            seen.add(hint)
            for name, field_hint in typing.get_type_hints(hint).items():
                names.append(name)
                walk(field_hint)
        for argument in typing.get_args(hint):
            walk(argument)

    if shape is not None:
        walk(shape)
    return names


class TestEveryRouteNamingAnExecutionProvesItFirst:
    """Derived from the contract, so a route added later is covered without anyone editing this."""

    def test_the_population_is_the_one_the_guard_claims(self) -> None:
        """A guard over an empty list passes, so the routes it must hold are named.

        A superset rather than equality, so a new route joins by being declared.
        """
        assert {"athena.status", "athena.results", "athena.stop"} <= {
            route.id for route in EXECUTION_ROUTES
        }

    def test_every_query_route_names_its_execution_with_the_one_placeholder(self) -> None:
        """A route spelling it ``{executionId}`` would escape the list above with nothing red."""
        for route in contract.ROUTES:
            segments = route.path.split("/")
            if route.path.startswith("/v1/queries/"):
                placeholders = [segment for segment in segments if segment.startswith("{")]
                assert placeholders in ([], ["{queryExecutionId}"]), route.id

    def test_every_athena_route_but_start_is_in_the_guarded_list(self) -> None:
        """Found by the handler's module, so a route whose PATH hides the execution still counts.

        The list above is found by the placeholder. An Athena route that named its execution any
        other way, or under another prefix, would sit outside it with nothing red; this finds it
        from the other end. A new Athena route that names no execution fails here too, on
        purpose: it is a decision to make, not a default to inherit.
        """
        served_here = {
            route_id
            for route_id, handler in router.HANDLERS.items()
            if handler.__module__ == athena_routes.__name__
        }

        assert "athena.status" in served_here
        assert served_here - {"athena.start"} == {route.id for route in EXECUTION_ROUTES}

    def test_no_other_placeholder_query_or_body_field_names_an_execution(self) -> None:
        """An execution id arriving any other way would reach no proof in this file.

        The one such field is results-conversion's, in a request body; that plane proves the
        execution is the caller's with the same predicate before it reads anything. Equality, so
        a new field naming an execution fails here until someone decides where it is proved.
        """
        found = set()
        for route in contract.ROUTES:
            for segment in route.path.split("/"):
                if segment.startswith("{") and "execution" in segment.lower():
                    found.add((route.id, "path", segment))
            for where, shape in (("query", route.query), ("body", route.request)):
                for name in _field_names(shape):
                    if "execution" in name.lower():
                        found.add((route.id, where, name))

        expected = {(route.id, "path", "{queryExecutionId}") for route in EXECUTION_ROUTES}
        expected.add(("resultsConversion.enqueue", "body", "queryExecutionId"))
        assert found == expected

    @pytest.mark.parametrize(
        "answer_to_get",
        [_execution(location=FOREIGN_LOCATION), _unknown_id()],
        ids=["someone else's execution", "an id athena does not know"],
    )
    def test_an_unset_bucket_is_one_server_fault_before_athena_is_asked(
        self, athena, monkeypatch, answer_to_get
    ) -> None:
        """The same answer for both even when the deployment is broken.

        The bucket is read before the execution, so a missing setting cannot answer an unknown id
        with 404 and a foreign one with a server fault.
        """
        monkeypatch.setenv("USER_SPACE_BUCKET", "")
        stub = athena(StubAthena(get_query_execution=answer_to_get))

        answer = router.route("GET", "/v1/queries/e-1", bearer(), "rq")

        assert answer["statusCode"] == 503
        assert _body(answer)["error"]["code"] == "ApiUnavailable"
        assert stub.calls == []

    @pytest.mark.parametrize("route", EXECUTION_ROUTES, ids=lambda route: route.id)
    def test_a_foreign_execution_is_refused_before_anything_else_is_asked(self, athena, route) -> None:
        """One 404, one body, and no call past the proof — whatever the route goes on to do."""
        path = route.path.replace("{queryExecutionId}", "e-1")
        bodies = []
        for answer_to_get in (_execution(location=FOREIGN_LOCATION), _unknown_id()):
            stub = athena(StubAthena(get_query_execution=answer_to_get))

            answer = router.route(route.method, path, bearer(), "rq", None, {})

            assert answer["statusCode"] == 404, route.id
            assert _body(answer)["error"]["detail"] == athena_routes.EXECUTION_NOT_FOUND_DETAIL
            assert _operations(stub) == ["get_query_execution"], route.id
            bodies.append(answer["body"])

        assert bodies[0] == bodies[1]
