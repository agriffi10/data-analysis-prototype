"""Every reason code the results-conversion plane can return, as one closed set.

The verbs raise these; ``messages`` words them; a test holds the two equal so a code can neither
be raised unworded nor worded unraised.

Attributes:
  FORBIDDEN: The destination space is not one the actor may write — the same sentence whether
    it does not exist or excludes them, so the refusal is not a directory of space names.
  INVALID_REQUEST: A shape or cap the plane refuses: a bad file name or folder, a key escaping
    the space, an unknown format or conflict answer.
  PROTECTED_LOCATION: The destination sits in a folder the portal manages.
  EXECUTION_NOT_FOUND: Athena knows no such execution, or its output is not under the actor's
    own results prefix — one code for both, so it cannot say whether another user's execution
    exists.
  EXECUTION_NOT_FINISHED: The execution is still queued or running.
  EXECUTION_FAILED: The execution failed or was cancelled.
  NO_RESULT_SET: The execution was not a DML statement, so it wrote no rows.
  RESULTS_TOO_LARGE: The result object is over the converter's cap.
  DUPLICATE_COLUMN: Two result columns share a name once case-folded.
  INVALID_COLUMN_NAME: A result column has an empty name.
  UNSUPPORTED_COLUMN_TYPE: A result column has an Athena type this plane has no answer for.
    The vocabulary is closed and does not fall back to text, so an unmodelled type refuses
    rather than becoming the wrong column in a file the user then trusts.
  RESULTS_UNREADABLE: A value in the result set does not parse as the type Athena declared for
    its column. The whole conversion refuses and no partial file is written.
  EXCEL_ROW_LIMIT: The result set has more rows than a worksheet can hold.
  EXCEL_COLUMN_LIMIT: The result set has more columns than a worksheet can hold.
  DESTINATION_OCCUPIED: The destination name was taken between the browser's pre-flight and the
    write, and the request asked to be refused rather than to overwrite.
  MALFORMED_EVENT: The queue message could not be read as a request.
  UNEXPECTED: A fault nobody predicted.
  CONVERSION_TIMED_OUT: The machine's own ceiling stopped the run — the timeout door's code.
  REASONS: All of the above.
"""

FORBIDDEN = "forbidden"
INVALID_REQUEST = "invalid_request"
PROTECTED_LOCATION = "protected_location"
EXECUTION_NOT_FOUND = "execution_not_found"
EXECUTION_NOT_FINISHED = "execution_not_finished"
EXECUTION_FAILED = "execution_failed"
NO_RESULT_SET = "no_result_set"
RESULTS_TOO_LARGE = "results_too_large"
DUPLICATE_COLUMN = "duplicate_column"
INVALID_COLUMN_NAME = "invalid_column_name"
UNSUPPORTED_COLUMN_TYPE = "unsupported_column_type"
RESULTS_UNREADABLE = "results_unreadable"
EXCEL_ROW_LIMIT = "excel_row_limit"
EXCEL_COLUMN_LIMIT = "excel_column_limit"
DESTINATION_OCCUPIED = "destination_occupied"
MALFORMED_EVENT = "malformed_event"
UNEXPECTED = "unexpected"
CONVERSION_TIMED_OUT = "conversion_timed_out"

REASONS = frozenset(
    {
        FORBIDDEN,
        INVALID_REQUEST,
        PROTECTED_LOCATION,
        EXECUTION_NOT_FOUND,
        EXECUTION_NOT_FINISHED,
        EXECUTION_FAILED,
        NO_RESULT_SET,
        RESULTS_TOO_LARGE,
        DUPLICATE_COLUMN,
        INVALID_COLUMN_NAME,
        UNSUPPORTED_COLUMN_TYPE,
        RESULTS_UNREADABLE,
        EXCEL_ROW_LIMIT,
        EXCEL_COLUMN_LIMIT,
        DESTINATION_OCCUPIED,
        MALFORMED_EVENT,
        UNEXPECTED,
        CONVERSION_TIMED_OUT,
    }
)
