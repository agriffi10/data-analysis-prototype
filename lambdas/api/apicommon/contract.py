"""The wire contract, declared once. Every other statement about the wire is derived from here.

The API is Python and the browser is TypeScript, and something has to hold them in agreement.
Two hand-edited copies rot. A contract test both sides hand-wrote against each other compares a
copy of the answer with itself, and it agrees most confidently exactly when both were written by
the same session on the same afternoon. So this module is the single declaration, and
``scripts/generate_api_contract.py`` emits the TypeScript from it.

Python is the source rather than TypeScript because the runtime request validator and the wire
types must read ONE declaration. A validator written against a separate schema is a third copy,
and the third copy is the one nobody regenerates.

**The type vocabulary is closed, and that is the load-bearing part.** ``walk`` raises on anything
it does not understand rather than falling back, because a fallback type agrees with every
possible value: the day the emitter meets a shape it cannot express is the day the contract stops
being checked, and nothing goes red. The generator and the validator consume the SAME walk of the
SAME annotation, so neither can drift into supporting something the other refuses.

Attributes:
  ErrorCode: The closed set of machine codes a failure may carry. A code outside it never reaches
    the wire, including on an unhandled exception.
  ERROR_STATUS: Every code to the one status it produces. Total by construction, and its image is
    a subset of the statuses the router may emit.
  ROUTE_STATUSES: Every status the router is permitted to emit. The gateway's own 413, 429, 502
    and 504 are produced ABOVE the router, are not envelope-shaped, and are deliberately absent.
  ROUTES: Every route the API serves. The router dispatches from this table, the plane table
    derives from it, and the generated TypeScript is emitted from it — so a route cannot exist
    in one of those places and not the others.
  QueryState: The five execution states this product models. Athena documents a sixth,
    ``CANCELLING``, which the browser has never known — admitting it here would deliver an
    unhandled value to the one surface that reads state.
  PARAMETER_NAME_RE: What a path template's placeholder may be called. A segment wearing braces
    whose name does not match is REFUSED at declaration time rather than read as a literal —
    read as a literal it would match nothing, and every request to that route would be an
    ordinary 404 with no symptom anywhere.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import (
    Any,
    Final,
    Literal,
    NotRequired,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

ErrorCode = Literal[
    "InvalidRequest",
    "SessionExpired",
    "AccessDenied",
    "NotFound",
    "Conflict",
    "PayloadTooLarge",
    "UnsupportedMediaType",
    "RateLimited",
    "IdentityUnavailable",
    "InternalError",
    "ApiUnavailable",
    "QueryNotFinished",
    "QuerySyntaxError",
]

ERROR_STATUS: Final[dict[str, int]] = {
    "InvalidRequest": 400,
    "SessionExpired": 401,
    "AccessDenied": 403,
    "NotFound": 404,
    "Conflict": 409,
    "PayloadTooLarge": 413,
    "UnsupportedMediaType": 415,
    "RateLimited": 429,
    "IdentityUnavailable": 500,
    "InternalError": 500,
    "ApiUnavailable": 503,
    "QueryNotFinished": 409,
    "QuerySyntaxError": 400,
}

ROUTE_STATUSES: Final[frozenset[int]] = frozenset(
    {200, 400, 401, 403, 404, 409, 413, 415, 429, 500, 503}
)

PARAMETER_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][A-Za-z0-9]*\Z")


class ErrorParams(TypedDict, total=False):
    """The typed values a client needs to compose its own sentence for a failure.

    **Never free text, and never the sentence itself.** ``detail`` is operator prose the browser
    renders nowhere; this is the structured half — the colliding name, the bound that was hit —
    from which the SPA mints the wording it already ships. Five of ``errorMessages.ts``'s
    ``passthrough`` codes belong to the object surface and none of them may travel on the wire
    (the disjointness guard forbids it), so the values behind them travel here instead.

    Every key is optional, which is legal by DECLARATION rather than by exception: ``total=False``
    is inside the closed vocabulary and emits ``key?: X``.

    Attributes:
      name: The colliding leaf name, for a Conflict.
      attempts: The bound a free-name search exhausted, for a Conflict.
      limit: The bound that refused a request, for a PayloadTooLarge. **Not always bytes** —
        the enqueue bounds are counted in three units, and for a roster or a recipient list this
        is a count of entries. The wire carries the number and not the unit, so a client's
        wording has to hold for all three.
    """

    name: str
    attempts: int
    limit: int


class ApiErrorDetail(TypedDict):
    """The inner object of every failure body.

    ``detail`` is operator text authored at the raise site, read in a devtools panel and in the
    log store, and rendered nowhere. Nothing here is phrased for a user: the browser owns every
    user-facing sentence, and a server that returns one reverses that quietly, because the
    sentence would look fine in every screenshot.

    Attributes:
      code: The machine code, drawn from the closed set.
      requestId: The gateway's id for the request, so a user-reported failure is findable.
      detail: Optional operator text. Never a stringified exception.
      params: Optional typed values the client composes its own wording from. Absent unless the
        raise site has something structured to hand over.
    """

    code: ErrorCode
    requestId: str
    detail: NotRequired[str]
    params: NotRequired[ErrorParams]


class ApiErrorBody(TypedDict):
    """The only wrapped shape in the API. A success body is the payload itself.

    Attributes:
      error: The failure's code, correlation id and optional operator text.
    """

    error: ApiErrorDetail


class UserDirectoryResponse(TypedDict):
    """The published username directory, as the browser receives it.

    Carries no document version and no count: the document's shape is the server's business now,
    and a field the browser does not read is a field a later change has to keep true.

    Attributes:
      usernames: Catalog-safe usernames, re-checked server-side.
      generatedAt: When the directory was built, or None when it is unavailable or unusable.
    """

    usernames: list[str]
    generatedAt: str | None


class SpaceRef(TypedDict):
    """A space, as a request body names it.

    Body-only. A query string carries strings alone, so a GET route flattens this into
    ``spaceKind``/``spaceName`` rather than sharing the shape — see ``_check_query``.

    Attributes:
      kind: Which sort of space.
      name: The space's name. Checked against the caller's verified claims, never trusted.
    """

    kind: Literal["personal", "shared"]
    name: str


class ObjectEntry(TypedDict):
    """One row of a listing — a folder or a file, travelling in the same array.

    Attributes:
      kind: Whether this row is a folder or a file.
      key: The full object key, or the common prefix for a folder.
      size: The object's size in bytes, or None for a folder.
      lastModified: ISO-8601 UTC, or None for a folder.
    """

    kind: Literal["folder", "file"]
    key: str
    size: int | None
    lastModified: str | None


class ListObjectsResponse(TypedDict):
    """One page of a listing.

    ``nextToken`` is the universal half of the paged contract and ``items`` is not: a page that is
    a bare homogeneous collection names it ``items``, and a tabular one carries ``columns``/``rows``
    beside the same ``nextToken``. Both are conformant.

    Attributes:
      items: The rows, folders and files together.
      nextToken: S3's ``NextContinuationToken``, opaque and UNMODIFIED, or None on the last page.
    """

    items: list[ObjectEntry]
    nextToken: str | None


class ObjectMetadataEntry(TypedDict):
    """One ``x-amz-meta-*`` pair, as a row rather than as a map.

    The vocabulary has no mapping type and is deliberately not widened for this: a list of
    declared objects says the same thing, is generated by the walk that already exists, and keeps
    the closed set closed. The browser folds these back into the ``Record<string, string>`` its
    metadata panel has always rendered.

    Attributes:
      name: The metadata key, with the ``x-amz-meta-`` prefix already stripped by S3.
      value: Its value.
    """

    name: str
    value: str


class ObjectMetadataResponse(TypedDict):
    """What a head reports about one object.

    ``storageClass`` and ``userMetadata`` are here because the details panel renders both, and a
    port that dropped them would have emptied two fields nobody would notice until they looked.

    Attributes:
      key: The object key.
      size: Size in bytes.
      lastModified: ISO-8601 UTC.
      contentType: The stored content type.
      etag: The object's ETag.
      storageClass: The stored class, defaulted to ``STANDARD`` where S3 omits it — which it does
        for every ordinary object.
      userMetadata: The object's own metadata pairs, empty when none were set.
    """

    key: str
    size: int
    lastModified: str
    contentType: str
    etag: str
    storageClass: str
    userMetadata: list[ObjectMetadataEntry]


class ObjectExistsResponse(TypedDict):
    """Whether an object is there.

    **200 for both answers.** Mapping absence onto the error arm would turn every free-name and
    collision check into a failure the caller has to re-interpret.

    Attributes:
      exists: Whether the key resolves to an object.
    """

    exists: bool


class ObjectContentResponse(TypedDict):
    """An object's bytes, decoded as UTF-8 and NEVER parsed.

    Parsing here works for every healthy document and makes an unparseable one a 500 — which puts
    the browser's whole quarantine path out of reach, because the classifier never sees the body it
    must classify as unreadable.

    Attributes:
      body: The object's bytes, decoded as UTF-8.
      etag: The object's ETag.
    """

    body: str
    etag: str


class ObjectWrittenResponse(TypedDict):
    """What a write reports back.

    Attributes:
      key: The key written.
      etag: The new ETag.
    """

    key: str
    etag: str


class ObjectDeletedResponse(TypedDict):
    """What a delete reports back.

    Attributes:
      key: The key deleted.
    """

    key: str



class ListObjectsQuery(TypedDict):
    """The listing query. All strings — a query string carries nothing else.

    Attributes:
      spaceKind: Which sort of space.
      spaceName: The space's name.
      prefix: The folder to list, as a full prefix starting with the space root. Absent means the
        root; a prefix that does not start with it is refused.
      nextToken: A continuation token from a previous page.
    """

    spaceKind: Literal["personal", "shared"]
    spaceName: str
    prefix: NotRequired[str]
    nextToken: NotRequired[str]


class ObjectKeyQuery(TypedDict):
    """A single object, named in a query string.

    Attributes:
      spaceKind: Which sort of space.
      spaceName: The space's name.
      key: The object key.
    """

    spaceKind: Literal["personal", "shared"]
    spaceName: str
    key: str


class ObjectExistsQuery(TypedDict):
    """An existence question about either an object or a whole prefix.

    **Two questions, one route, because they are the same question at two granularities** — and
    the listing route cannot answer the second one. ``objects.list`` drops the prefix's own marker
    object and every ``DO_NOT_DELETE.txt``, which is right for a listing and fatal here: a folder
    made with "New folder" holds exactly the key the listing hides, so asking the listing whether
    it still exists answers *no* about a folder that is plainly there.

    Attributes:
      spaceKind: Which sort of space.
      spaceName: The space's name.
      key: The object key, or the prefix when ``target`` is ``prefix``.
      target: What ``key`` names. Absent means an object, which is what every existing caller
        asks and what keeps the flag off the common path.
    """

    spaceKind: Literal["personal", "shared"]
    spaceName: str
    key: str
    target: NotRequired[Literal["object", "prefix"]]


class WriteContentRequest(TypedDict):
    """A document write.

    Attributes:
      space: The space.
      key: The object key.
      body: The bytes to store, as UTF-8 text. Written BYTE FOR BYTE — never re-serialised.
      contentType: The content type to store.
      overwrite: Whether an existing object may be replaced.
    """

    space: SpaceRef
    key: str
    body: str
    contentType: str
    overwrite: bool


class CopyRequest(TypedDict):
    """A single-object copy or move.

    Attributes:
      source: Where to read from.
      sourceKey: The source object key.
      destination: Where to write to.
      destinationKey: The destination object key.
      overwrite: Whether an occupied destination may be replaced.
    """

    source: SpaceRef
    sourceKey: str
    destination: SpaceRef
    destinationKey: str
    overwrite: bool


class DeleteRequest(TypedDict):
    """A single-object delete.

    Attributes:
      space: The space.
      key: The object key.
    """

    space: SpaceRef
    key: str


class PresignedUrlResponse(TypedDict):
    """A minted URL and when it dies.

    ``url`` is a BEARER TOKEN. It is never logged, never cached, and never returned for a key the
    caller may not reach.

    Attributes:
      url: The signed URL.
      expiresAt: ISO-8601 UTC, never later than the signing session's own expiry — which is what
        stops a URL 403ing at redemption after a long upload has already sent its bytes.
    """

    url: str
    expiresAt: str


class CreateUploadRequest(TypedDict):
    """A request to begin an upload, whichever shape it turns out to take.

    Its route is **not** idempotent: a retried create leaks an upload id nobody will abort, which
    costs storage until the bucket's lifecycle rule reaps it. Every route in this lifecycle sits
    on the **user** plane, so the caller's own assumed session both authorizes and signs — and
    each id keeps the ``objects.`` prefix, which is load-bearing because the user-plane sweep
    selects its population by exactly that prefix.

    Attributes:
      space: The space.
      key: The object key.
      contentType: The content type the upload will carry, which is signed into the URL.
      overwrite: Whether an occupied key may be replaced. With false and the key occupied the
        route creates NOTHING — no url and no upload.
      size: The object's byte length. A **PLANNING input, not a limit**: it is the caller's own
        number and nothing verifies it, so a client that under-declares gets a plan with too few
        parts and fails at ``UploadPart`` 10,001 or at complete. The real ceiling is the
        browser's ``maxUploadBytes()`` and S3's own part limits. No S3 call can supply it,
        because the object does not exist yet. The route refuses an unservable declared size as
        a courtesy, not as enforcement.
    """

    space: SpaceRef
    key: str
    contentType: str
    overwrite: bool
    size: int


class CreateUploadResponse(TypedDict):
    """How an upload should be performed, decided by the SERVER.

    **Optional members plus a discriminant, and it does not narrow in TypeScript.** The type
    vocabulary is closed and carries no union other than ``X | None``, so this emits one object
    type with optional members rather than a discriminated union. The browser therefore checks
    each member its chosen branch needs at runtime and answers a named code when a member is
    absent — the alternative is widening the vocabulary, which is the thing the closed-vocabulary
    rule exists to refuse.

    The browser never learns the threshold. A second copy of a policy number in the SPA would
    drift, and a drifted copy sends files down the wrong path with nothing failing.

    Attributes:
      mode: Which path this upload takes.
      url: Single only — the presigned PUT.
      expiresAt: Single only — when that URL dies.
      uploadId: Multipart only. A **CAPABILITY**, so it appears in no emitted record.
      partSize: Multipart only — every part but the last is exactly this many bytes.
      partCount: Multipart only — how many parts the plan has.
    """

    mode: Literal["single", "multipart"]
    url: NotRequired[str]
    expiresAt: NotRequired[str]
    uploadId: NotRequired[str]
    partSize: NotRequired[int]
    partCount: NotRequired[int]


class SignPartRequest(TypedDict):
    """A request for one part's presigned URL.

    One part per call rather than a batch: a batch ages while the parts ahead of it upload, so
    its last URL is signed long before it is redeemed.

    **The one idempotent route of the four.** Signing is a local SigV4 operation that changes
    nothing at S3, so a retry costs nothing and risks nothing. Declared per route rather than
    derived from the method — and stated as declaration hygiene rather than as protection, since
    the flag is consumed only by the browser's retry policy and the uploader calls the transport
    imperatively.

    Attributes:
      space: The space.
      key: The object key.
      uploadId: The upload this part belongs to. Not evidence of anything — every route
        re-authorizes from claims.
      partNumber: 1-based, as S3 numbers them.
    """

    space: SpaceRef
    key: str
    uploadId: str
    partNumber: int


class UploadedPart(TypedDict):
    """One part, as the browser observed it.

    Attributes:
      partNumber: 1-based.
      etag: What S3 returned for that part, read from the ``ETag`` response header.
    """

    partNumber: int
    etag: str


class CompleteUploadRequest(TypedDict):
    """A request to assemble the parts into the object.

    **The part list is the browser's, and that is safe for a stated reason.** S3 validates every
    ETag, so a wrong list fails the assembly rather than assembling the wrong object; a caller
    completing with a subset truncates their own object in their own prefix, which they could do
    by uploading a shorter file. A server-side audit would cost a ``ListParts`` per upload and
    buy nothing.

    Not idempotent: a retried complete answers against an upload that is already finished, which
    would surface as a failure for an operation that succeeded.

    Attributes:
      space: The space.
      key: The object key.
      uploadId: The upload to assemble.
      parts: Every part, in order.
      overwrite: Whether an occupied key may be replaced. **Carried here rather than remembered
        from create**, because the API keeps no record of an upload — and because the create-time
        check answers about a moment that can be hours before the object is assembled, so
        completing over what arrived in between would report success while destroying it.
    """

    space: SpaceRef
    key: str
    uploadId: str
    parts: list[UploadedPart]
    overwrite: bool


class AbortUploadRequest(TypedDict):
    """A request to abandon an upload and let S3 discard its parts.

    Not idempotent: a retried abort answers ``NoSuchUpload``, which would surface as a failure
    for an operation that succeeded.

    Attributes:
      space: The space.
      key: The object key.
      uploadId: The upload to abandon.
    """

    space: SpaceRef
    key: str
    uploadId: str


class DownloadUrlRequest(TypedDict):
    """A request for a presigned GET.

    Attributes:
      space: The space.
      key: The object key.
      fileName: An optional filename to offer the browser, escaped into the disposition header.
    """

    space: SpaceRef
    key: str
    fileName: NotRequired[str]


class FreeNameRequest(TypedDict):
    """A request for the first unused numbered name under a prefix.

    Attributes:
      space: The space.
      prefix: The folder to search, as a full prefix starting with the space root.
      baseName: The original leaf name a copy is being made of.
      kind: Whether the name is for a file or a folder — a folder has no extension to preserve.
    """

    space: SpaceRef
    prefix: str
    baseName: str
    kind: Literal["file", "folder"]


class FreeNameResponse(TypedDict):
    """The name the route found.

    Attributes:
      name: The free leaf name, without its prefix.
    """

    name: str


QueryState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


class StartQueryRequest(TypedDict):
    """What the browser sends to start a query.

    It carries no username, no bucket and no workgroup: all three are derived server-side, from
    the verified claim and this function's own environment. A body naming any of them is refused
    rather than ignored — an ignored field is a field that comes back.

    Attributes:
      sql: The statement, opaque to this API. Never parsed, split, trimmed or logged, and passed
        to Athena byte-identical: the Data Explorer discloses this string to the user as the
        query it is about to bill them for, and the disclosure is trusted BECAUSE it is the same
        bytes.
      database: The execution context, omitted entirely when absent rather than sent empty —
        queries carry no active database, so every base table is fully qualified and a present
        but empty context would change what resolves.
    """

    sql: str
    database: NotRequired[str]


class StartQueryResponse(TypedDict):
    """The execution the browser polls.

    Attributes:
      queryExecutionId: Athena's id for the execution.
    """

    queryExecutionId: str


class QueryStatusResponse(TypedDict):
    """One poll of an execution.

    **A failed query is a 200.** The execution failing is data about the query, not a failure of
    the request — and the browser's authored wording for six distinct engine conditions is chosen
    by reading ``stateChangeReason``. Mapping a FAILED execution onto an error envelope is the
    change that looks most correct and silently retires all six.

    Attributes:
      queryExecutionId: The execution this describes.
      state: Athena's state, over the five this app models. ``CANCELLING`` is deliberately absent:
        the browser's terminal-state test and switch arms have never known it, so admitting it
        here would deliver an unhandled value to the one surface that reads state.
      stateChangeReason: Athena's engine text, VERBATIM — never truncated, never mapped to a code,
        never merged into ``detail``. It is mapped to authored wording in the browser and rendered
        by nothing on this side.
      dataScannedBytes: Null while non-terminal, never 0 — a confident zero freezes the tab's cost
        figure at zero for the whole run.
      engineExecutionTimeMillis: Null while non-terminal, for the same reason.
      outputLocation: Where Athena wrote the results, present once it reports one.
    """

    queryExecutionId: str
    state: QueryState
    stateChangeReason: str | None
    dataScannedBytes: int | None
    engineExecutionTimeMillis: int | None
    outputLocation: str | None


class QueryResultsQuery(TypedDict, total=False):
    """How a caller asks for one page of results.

    Both values are strings because a query string carries nothing else; the range check on
    ``maxRows`` therefore lives in the route rather than in this declaration.

    Attributes:
      nextToken: Athena's continuation token, opaque — stored and returned unmodified.
      maxRows: How many data rows the page should hold, 1 to 1000.
    """

    nextToken: str
    maxRows: str


class QueryColumnWire(TypedDict):
    """One result column.

    Attributes:
      name: The column's name, as Athena reports it.
      type: Athena's RAW type string. Normalising it is the browser's job and stays there, so the
        wire carries what the engine said rather than an opinion about it.
    """

    name: str
    type: str


class QueryResultsResponse(TypedDict):
    """One page of a succeeded query's results.

    A page that is not a bare collection carries its own payload keys beside ``nextToken`` rather
    than being wrapped as ``items``: a tabular page is two parallel shapes, and wrapping it would
    either lose the column list or nest every row a level deeper for every consumer.

    Attributes:
      columns: The result's columns, in order.
      rows: The cells, aligned to the columns. **``null`` is SQL NULL and ``""`` is the empty
        string, and the two are distinct on the wire** — collapsing them destroys a difference no
        consumer can rebuild, and the Value panel exists to tell them apart.
      nextToken: The continuation token, or None on the last page.
    """

    columns: list[QueryColumnWire]
    rows: list[list[str | None]]
    nextToken: str | None


class QueryRowCountResponse(TypedDict):
    """A succeeded execution's total row count, as Athena counted it.

    **A number is only ever Athena's own count of the rows a SELECT returned**, read from its
    runtime statistics, which scan nothing and ship no row. The browser used to count by fetching
    every page of the result; each page is now a billed call, and a ten-million-row result is ten
    thousand of them. ``rowCount`` is None in two different situations, and ``pending`` says
    which: the statistics have not landed yet (ask again), or Athena does not count this kind of
    statement at all (count it some other way). A statement Athena labels ``EXPLAIN`` is the
    reason the second case exists — it reports one output row over a plan the grid shows as many.

    Attributes:
      rowCount: The rows a succeeded SELECT returned, or None when Athena reports no count.
      pending: True when the statement is a SELECT whose statistics have not landed, so the
        caller should ask again rather than count another way; False otherwise.
    """

    rowCount: int | None
    pending: bool


class StopQueryResponse(TypedDict):
    """What stopping an execution answers.

    Empty, and it stays empty: the poller observes the terminal state either way, so there is
    nothing here a caller would read. It exists because every 200 body is an object.
    """


class DatabaseResponse(TypedDict):
    """One catalog database, as the schema browser needs it.

    Attributes:
      name: The database's name.
    """

    name: str


class TablesQuery(TypedDict, total=False):
    """How a caller asks for one page of a database's tables.

    Attributes:
      nextToken: Glue's continuation token, opaque.
    """

    nextToken: str


class GlueColumnWire(TypedDict):
    """One column of a catalog table.

    Attributes:
      name: The column's name.
      type: The column's type, as the catalog stores it.
    """

    name: str
    type: str


class GlueTableWire(TypedDict):
    """One table in a database.

    Attributes:
      name: The table's name.
      columns: Its columns, empty when the catalog stores none.
      tableType: EXTERNAL_TABLE, VIRTUAL_VIEW and the like, or None.
      location: The S3 location backing it, or None.
    """

    name: str
    columns: list[GlueColumnWire]
    tableType: str | None
    location: str | None


class TablesResponse(TypedDict):
    """One page of a database's tables.

    Attributes:
      items: The tables on this page — a bare homogeneous collection, so it is named ``items``.
      nextToken: The continuation token, or None on the last page.
    """

    items: list[GlueTableWire]
    nextToken: str | None


class EnqueueAccepted(TypedDict):
    """What every enqueue route answers with.

    200 rather than 202: the status set is closed, and "accepted, not processed" is what every one
    of these call sites has always meant by success.

    Attributes:
      requestId: The caller's own id, echoed back. This service mints none — the one id it does
        generate is the notifications queue's dedup key, which never leaves the send. ``None`` on
        the one plane that has no request id.
    """

    requestId: str | None


class SharedSpacePayload(TypedDict, total=False):
    """The optional body of a shared-space request.

    Typed closed rather than as an open record, because the contract's vocabulary has no open
    record and a fallback that agreed with every value would be the day the wire stopped being
    checked. ``members`` is the only key any verb reads.

    Attributes:
      members: The usernames an add or remove names.
      newOwner: The member a transfer hands the space to. They must already be in the roster —
        transfer is not an invitation, and making it one would let a single action grant a
        stranger access.
    """

    members: list[str]
    newOwner: str


class SharedSpaceEnqueueRequest(TypedDict):
    """A shared-space request, minus the token and the advisory actor the sender stamps.

    Attributes:
      requestId: The caller's per-submit id, which is also the dedup key.
      action: Which shared-space verb to run.
      space: The space's name.
      payload: The verb's arguments, if it takes any.
    """

    requestId: str
    action: Literal[
        "create",
        "add_members",
        "remove_members",
        "leave",
        "delete",
        "forget",
        "acknowledge_membership",
        "transfer_ownership",
    ]
    space: str
    payload: SharedSpacePayload


class NotificationsEnqueueRequest(TypedDict):
    """A notification action. The username the browser used to send is now the verified caller.

    Attributes:
      action: Which action to run.
      id: The notification the action names, absent for the all-at-once action.
    """

    action: Literal["markRead", "markAllRead"]
    id: str | None


class PartitionKeyBase(TypedDict):
    """What every declared partition key carries, whichever kind it is.

    Attributes:
      name: The column name, catalog-safe.
      type: Which projection kind it is.
    """

    name: str
    type: Literal["integer", "date", "string"]


class PartitionKeyWire(PartitionKeyBase, total=False):
    """The per-kind fields, FLATTENED into one shape rather than three.

    The browser models these as three variants and the contract's type vocabulary has no union of
    object shapes, so the three are declared as one object whose per-kind fields are optional. The
    consequence is deliberate and bounded: this service no longer refuses a date field on an
    integer key, and the plane's own ``_validate_partition_keys`` — which checks the name, the
    kind, the range shape, the format, the enum contents and duplicate names in full — is the only
    validator of the combination. A wrong combination therefore comes back as a notification rather
    than as an immediate refusal.

    ``range`` is a list of STRINGS for both the integer and the date kind. That is safe rather than
    lossy: the plane accepts bounds that are numbers or strings, and the DDL builder interpolates
    them into one ``lo,hi`` property without arithmetic, so the emitted table property is identical
    either way.

    Attributes:
      range: The projection bounds, low then high.
      format: The date format, for a date key.
      values: The enumerated values, for a string key.
      digits: The zero-padded width, for an integer key.
      interval: The step, for a date key.
      intervalUnit: The step's unit, for a date key.
    """

    range: list[str]
    format: str
    values: list[str]
    digits: int
    interval: int
    intervalUnit: str


class CatalogSpaceRef(TypedDict):
    """A space as the catalog planes name it, carrying the database the tables live in.

    Attributes:
      kind: Which sort of space.
      bucket: The bucket holding it. Sent because the plane requires it; the FIFO derivation
        resolves its own from the kind and never reads this.
      prefix: The folder the table points at.
      database: The Glue database, which is also the table-build FIFO group.
    """

    kind: Literal["personal", "shared"]
    bucket: str
    prefix: str
    database: str


class TableBuildCreateRequest(TypedDict):
    """A create-table request.

    Attributes:
      requestId: The caller's per-submit id.
      space: The target space, whose database is also the FIFO group.
      tableName: The table to create.
      partitionKeys: The partition keys to declare, empty when there are none.
    """

    requestId: str
    space: CatalogSpaceRef
    tableName: str
    partitionKeys: list[PartitionKeyWire]


class TableBuildRefreshBase(TypedDict):
    """A refresh request. ``mode`` is not here: it is the route, and the sender stamps it.

    Attributes:
      requestId: The caller's per-submit id.
      space: The target space.
      tableName: The table to refresh.
      allowRemovals: Whether a column disappearing from the data may be dropped from the table.
        Sent only when the user ticked the opt-in, because an always-present ``false`` is a
        different request from an absent one.
    """

    requestId: str
    space: CatalogSpaceRef
    tableName: str
    partitionKeys: list[PartitionKeyWire]


class TableBuildRefreshRequest(TableBuildRefreshBase, total=False):
    """The opt-in a refresh carries only when the user ticked it.

    Optional rather than nullable: the diff validates the flag rather than coercing it, so an
    always-present ``false`` is a different request from an absent one.

    Attributes:
      allowRemovals: Whether a column disappearing from the data may be dropped from the table.
    """

    allowRemovals: bool


class TableSourceRef(TypedDict):
    """The table a share copies from.

    Attributes:
      database: The source database.
      table: The source table.
    """

    database: str
    table: str


class ShareRecipient(TypedDict):
    """One recipient of a shared table.

    Attributes:
      kind: Whether the recipient is a user or a space.
      name: The recipient's name.
    """

    kind: Literal["user", "space"]
    name: str


class TableShareEnqueueRequest(TypedDict):
    """A share-table request. The plane has no request id, so the dedup digest is the only guard.

    Attributes:
      source: The table to share.
      tableName: The name the copy takes in each recipient's catalog.
      recipients: Who to share with.
    """

    source: TableSourceRef
    tableName: str
    recipients: list[ShareRecipient]


class DataQualitySpaceRef(TypedDict):
    """A space as the data-quality plane names it, which is not how a body route names one.

    It carries the bucket and the root prefix and NOT a name, because the verb requires both and
    resolves nothing itself. The FIFO derivation still takes its bucket from the kind rather than
    from here: what the plane needs on the wire and what a group id may be built from are two
    different questions, and conflating them is how a caller comes to choose their own group.

    Attributes:
      kind: Which sort of space.
      bucket: The bucket holding it.
      prefix: The space root prefix.
    """

    kind: Literal["personal", "shared"]
    bucket: str
    prefix: str


class DataQualityEnqueueRequest(TypedDict):
    """A data-quality check. The bucket is resolved from the kind, never taken from the body.

    Attributes:
      requestId: The caller's per-submit id.
      space: The space the location sits in.
      location: The folder to check.
    """

    requestId: str
    space: DataQualitySpaceRef
    location: str


class SelectionItem(TypedDict):
    """One item in a selection.

    Attributes:
      kind: Whether it names a file or a folder, which is what stops one key arriving as both.
      key: The object or folder key.
    """

    kind: Literal["file", "folder"]
    key: str


class FileOpItem(TypedDict, total=False):
    """One item in a file operation's selection, which may be renamed as it lands.

    ``targetName`` is what makes a rename and a same-folder numbered copy expressible at all: both send
    the containing folder as the destination and a different name. It is optional and an empty
    string is not a shorthand — the plane refuses that.

    Attributes:
      kind: Whether it names a file or a folder.
      key: The absolute object or folder key.
      targetName: The item's name at the destination, defaulting to its own leaf name.
    """

    kind: Literal["file", "folder"]
    key: str
    targetName: str


class FileSendSource(TypedDict):
    """What a send is sending.

    Attributes:
      space: The space the items live in.
      items: The selection.
    """

    space: SpaceRef
    items: list[SelectionItem]


class FileSendEnqueueRequest(TypedDict):
    """A send-files request.

    Attributes:
      requestId: The caller's per-submit id, which is also the dedup key.
      source: The space and selection.
      recipients: Who to send to.
    """

    requestId: str
    source: FileSendSource
    recipients: list[ShareRecipient]


class FileOpDestination(TypedDict):
    """Where a copy or move is going.

    Attributes:
      space: The destination space.
      prefix: The destination folder.
    """

    space: SpaceRef
    prefix: str


class FileOpSource(TypedDict):
    """The space and selection a file operation acts on.

    Attributes:
      space: The space the items live in.
      items: The selection, whose items may each name a destination name.
    """

    space: SpaceRef
    items: list[FileOpItem]


class FileOpsEnqueueBase(TypedDict):
    """One file operation.

    Attributes:
      requestId: The caller's per-submit id, which is also the dedup key.
      operation: Which operation to run.
      source: The space and selection.
      destination: Where it lands. Absent on a delete, which the plane refuses rather than
        ignores, so a stale destination carried over from a re-submitted request refuses the whole
        thing.
      onConflict: What to do about a name already taken at the destination.
      submittedAt: When the browser submitted, which the plane requires on a copy or a move and
        refuses on a delete. Absent on a delete for the same reason the destination is.
    """

    requestId: str
    operation: Literal["copy", "move", "delete"]
    source: FileOpSource


class FileOpsEnqueueRequest(FileOpsEnqueueBase, total=False):
    """The three fields a copy or a move carries and a delete must NOT.

    Optional rather than nullable, and that distinction is the whole point: the plane tests
    whether the key is PRESENT, not whether its value is null, so a delete carrying
    ``"destination": null`` is refused as an unexpected field. A caller sends them or does not.

    Attributes:
      destination: Where the operation lands.
      onConflict: What to do about a name already taken at the destination.
      submittedAt: When the browser submitted.
    """

    destination: FileOpDestination
    onConflict: Literal["refuse", "overwrite"]
    submittedAt: str


class ConversionDestination(TypedDict):
    """Where a converted result set lands.

    Attributes:
      space: The destination space.
      prefix: The destination folder, relative to the space root: empty or slash-terminated.
      filename: The file's name inside that folder, extension included.
    """

    space: SpaceRef
    prefix: str
    filename: str


class ResultsConversionEnqueueRequest(TypedDict):
    """A request to save a finished query's result set in another format, or a subset of it.

    Every key but ``columnIndexes`` is required; the route's validator refuses an unknown one.
    Every length and content cap lives in the plane's validate-authorize verb, which is the one
    authority on the request — this shape is deliberately shape-only. The exception is
    ``columnIndexes``, whose LENGTH is bounded here, because a list is the one field whose size
    the four-link chain cannot be measured without.

    Attributes:
      requestId: The caller's per-submit id, which is also the dedup key.
      queryExecutionId: The Athena execution whose result set is converted. A claim: the plane
        proves it is the caller's by the path Athena wrote to.
      format: The output format. ``csv`` is here and means something narrower than the other
        three: the CSV Athena wrote is still copied by the synchronous path whenever the file
        wanted is that object, and a CSV conversion is asked for only when the file is to carry
        a subset of the result's columns, or the same columns in another order — neither of
        which a copy can produce.
      destination: Where the file lands.
      onConflict: What to do about a name already taken at the destination.
      submittedAt: When the browser submitted, ISO-8601.
      columnIndexes: Which of the result's columns to write, by their position in the
        execution's own column list, in the order the file is to carry them. Absent keeps every
        column in the result's own order. Positions rather than names because the plane already
        refuses a result whose names collide once case-folded, so a position is unambiguous
        where a name would need that refusal to hold at both ends.
    """

    requestId: str
    queryExecutionId: str
    format: Literal["parquet", "json", "xlsx", "csv"]
    destination: ConversionDestination
    onConflict: Literal["refuse", "overwrite"]
    submittedAt: str
    columnIndexes: NotRequired[list[int]]


class ArchiveEnqueueRequest(TypedDict):
    """An archive request. ``mode`` is the route, not a field: it chooses the irreversible half.

    Attributes:
      requestId: The caller's per-submit id, which is also the archive's permanent identity.
      source: The space and selection.
      archiveName: What the user called the archive. Absent when they gave it no name; the plane
        checks the rule again, because this service checks only its size. Not ``name``: a field
        with that leaf is a catalog identifier everywhere else on this contract.
    """

    requestId: str
    source: FileSendSource
    archiveName: NotRequired[str]


class RestoreEnqueueRequest(TypedDict):
    """A restore request. Its field set is the restore contract, not a superset of the archive one.

    Attributes:
      requestId: The caller's per-submit id.
      space: The space the restore lands in, taken from the route the user is standing in.
      archiveId: Which archive to restore.
    """

    requestId: str
    space: SpaceRef
    archiveId: str


class FeedbackSubmitRequest(TypedDict):
    """One piece of feedback, as the browser sends it.

    **There is no username, userId or email field, and that is the requirement rather than an
    omission.** The submitter is the verified username claim, stamped by the route; a
    body that could name a person would let any signed-in caller file feedback against somebody
    else, and no amount of server-side checking makes a field the caller controls into an
    identity.

    ``category`` is a closed literal so the wire refuses a fifth value before any handler runs.
    The browser preselects none of them — the field exists to record a choice somebody made.

    Attributes:
      category: Which kind of feedback this is.
      message: What the user wrote. Bounded server-side; see ``routes.feedback``.
      route: The in-app path the user was on when they opened the dialog. Optional, stored
        verbatim, and interpreted by nothing — it is a breadcrumb for whoever reads the day's
        file, not an instruction to any code.
    """

    category: Literal["bug", "idea", "question", "other"]
    message: str
    route: NotRequired[str]


class FeedbackSubmitResponse(TypedDict):
    """What a caller gets once the submission is on the queue.

    The stamp is echoed back because it is the one fact the user's copy and ours agree on, and
    because a 200 carrying nothing would leave the browser unable to tell a completed submission
    from an empty body it failed to parse.

    Attributes:
      submittedAt: When the API stamped the submission, UTC, ISO 8601. Also the day whose file it
        lands in.
    """

    submittedAt: str


@dataclass(frozen=True)
class Route:
    """One route, declared whole.

    Every field is required, which is the point: a route cannot be added without choosing a
    credential plane and stating whether it may be retried. Both belong to the ROUTE rather than
    to the handler, so a guard can see them without running anything.

    Attributes:
      id: The name every call site uses. A call site names this, never a URL.
      method: The HTTP method.
      path: The path, versioned for the whole API rather than per route.
      idempotent: Whether a caller above the transport may retry. NEVER derived from the method —
        a POST that resolves a free name is a read, and a PUT that appends is not.
      plane: Which credentials the route may reach for. The user plane is the caller's own
        assumed session; the API plane is the function's execution role.
      request: The declared request body type, or None for a route that takes no body.
      query: The declared query-string type, or None for a route that takes no query. Its fields
        are STRINGS ONLY — see ``check_routes``. Required like every other field: a defaulted one
        would let a route be added without deciding, which is the mistake ``plane`` exists not to
        repeat.
      response: The declared 200 body type. Always an object type, so an additive field always
        has somewhere to go.
    """

    id: str
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    idempotent: bool
    plane: Literal["user", "api"]
    request: Any | None
    query: Any | None
    response: Any


@dataclass(frozen=True)
class Queue:
    """One FIFO request queue, as this service reaches it.

    Attributes:
      id: The queue's name in this registry, which every route names.
      env_var: The variable holding its URL. Required with no default, so a missing one raises at
        first read rather than sending nowhere.
      content_based_deduplication: Whether the deployed queue hashes the body when no explicit
        dedup id is given. Recorded so a test can hold it against the Terraform, and NEVER relied
        on: an explicit id is set on every send, because omitting it on the three queues where
        this is true does not error — SQS falls back to hashing the body, which still mostly
        collapses double-submits, so the guard the plane was specified with would be gone with
        nothing going red.
    """

    id: str
    env_var: str
    content_based_deduplication: bool


QUEUES: Final[tuple[Queue, ...]] = (
    Queue("shared-space", "SHARED_SPACE_QUEUE_URL", True),
    Queue("notifications", "NOTIFICATIONS_QUEUE_URL", True),
    Queue("table-builder", "TABLE_BUILD_QUEUE_URL", True),
    Queue("table-share", "TABLE_SHARE_QUEUE_URL", False),
    Queue("data-quality", "DATA_QUALITY_QUEUE_URL", False),
    Queue("file-send", "FILE_SEND_QUEUE_URL", False),
    Queue("archive", "ARCHIVE_QUEUE_URL", False),
    Queue("file-ops", "FILE_OPS_QUEUE_URL", False),
    Queue("results-conversion", "RESULTS_CONVERSION_QUEUE_URL", False),
)


@dataclass(frozen=True)
class EnqueueRoute(Route):
    """A route whose whole job is to put one message on one queue.

    Attributes:
      queue: Which queue, by registry id. Guarded for set equality against the registry in both
        directions, so a queue with no route and a route naming no queue both fail.
      stamped: The top-level keys the sender writes that the caller may not. Declared rather than
        inferred, because the envelope-agreement test needs the term and an escape hatch would let
        a caller be handed a field that chooses behaviour.

        Two kinds sit here and they are worth telling apart. ``mode`` and ``schemaVersion``
        CHOOSE BEHAVIOUR — ``mode`` is the difference between archiving and restoring — so
        handing one to a caller would hand them that branch. ``traceparent`` chooses nothing; it
        is on every enqueue route because a run begins at the API and the trace has to leave with
        the message. It is still declared rather than special-cased, because the four planes that
        refuse an unknown top-level body field are held to set equality against this term: a
        field the sender adds and this set omits is refused by the plane at run time as
        ``malformed_event``, which is a green build and a failed request.
    """

    queue: str
    stamped: frozenset[str]


ROUTES: Final[tuple[Route, ...]] = (
    Route(
        id="userDirectory.get",
        method="GET",
        path="/v1/user-directory",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=UserDirectoryResponse,
    ),
    Route(
        id="featureFlags.get",
        method="GET",
        path="/v1/feature-flags",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=ObjectContentResponse,
    ),
    Route(
        id="objects.list",
        method="GET",
        path="/v1/objects",
        idempotent=True,
        plane="user",
        request=None,
        query=ListObjectsQuery,
        response=ListObjectsResponse,
    ),
    Route(
        id="objects.metadata",
        method="GET",
        path="/v1/objects/metadata",
        idempotent=True,
        plane="user",
        request=None,
        query=ObjectKeyQuery,
        response=ObjectMetadataResponse,
    ),
    Route(
        id="objects.exists",
        method="GET",
        path="/v1/objects/exists",
        idempotent=True,
        plane="user",
        request=None,
        query=ObjectExistsQuery,
        response=ObjectExistsResponse,
    ),
    Route(
        id="objects.readContent",
        method="GET",
        path="/v1/objects/content",
        idempotent=True,
        plane="user",
        request=None,
        query=ObjectKeyQuery,
        response=ObjectContentResponse,
    ),
    Route(
        id="objects.writeContent",
        method="PUT",
        path="/v1/objects/content",
        idempotent=False,
        plane="user",
        request=WriteContentRequest,
        query=None,
        response=ObjectWrittenResponse,
    ),
    Route(
        id="objects.copy",
        method="POST",
        path="/v1/objects/copy",
        idempotent=False,
        plane="user",
        request=CopyRequest,
        query=None,
        response=ObjectWrittenResponse,
    ),
    Route(
        id="objects.move",
        method="POST",
        path="/v1/objects/move",
        idempotent=False,
        plane="user",
        request=CopyRequest,
        query=None,
        response=ObjectWrittenResponse,
    ),
    Route(
        id="objects.delete",
        method="DELETE",
        path="/v1/objects",
        idempotent=False,
        plane="user",
        request=DeleteRequest,
        query=None,
        response=ObjectDeletedResponse,
    ),
    Route(
        id="objects.upload",
        method="POST",
        path="/v1/objects/upload",
        idempotent=False,
        plane="user",
        request=CreateUploadRequest,
        query=None,
        response=CreateUploadResponse,
    ),
    Route(
        id="objects.uploadPart",
        method="POST",
        path="/v1/objects/upload/part",
        idempotent=True,
        plane="user",
        request=SignPartRequest,
        query=None,
        response=PresignedUrlResponse,
    ),
    Route(
        id="objects.uploadComplete",
        method="POST",
        path="/v1/objects/upload/complete",
        idempotent=False,
        plane="user",
        request=CompleteUploadRequest,
        query=None,
        response=ObjectWrittenResponse,
    ),
    Route(
        id="objects.uploadAbort",
        method="POST",
        path="/v1/objects/upload/abort",
        idempotent=False,
        plane="user",
        request=AbortUploadRequest,
        query=None,
        response=ObjectDeletedResponse,
    ),
    Route(
        id="objects.downloadUrl",
        method="POST",
        path="/v1/objects/download-url",
        idempotent=True,
        plane="user",
        request=DownloadUrlRequest,
        query=None,
        response=PresignedUrlResponse,
    ),
    Route(
        id="objects.freeName",
        method="POST",
        path="/v1/objects/free-name",
        idempotent=True,
        plane="user",
        request=FreeNameRequest,
        query=None,
        response=FreeNameResponse,
    ),
    Route(
        id="athena.start",
        method="POST",
        path="/v1/queries",
        idempotent=False,
        plane="user",
        request=StartQueryRequest,
        query=None,
        response=StartQueryResponse,
    ),
    Route(
        id="athena.status",
        method="GET",
        path="/v1/queries/{queryExecutionId}",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=QueryStatusResponse,
    ),
    Route(
        id="athena.results",
        method="GET",
        path="/v1/queries/{queryExecutionId}/results",
        idempotent=True,
        plane="user",
        request=None,
        query=QueryResultsQuery,
        response=QueryResultsResponse,
    ),
    Route(
        id="athena.rowCount",
        method="GET",
        path="/v1/queries/{queryExecutionId}/row-count",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=QueryRowCountResponse,
    ),
    Route(
        id="athena.stop",
        method="POST",
        path="/v1/queries/{queryExecutionId}/stop",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=StopQueryResponse,
    ),
    Route(
        id="catalog.database.get",
        method="GET",
        path="/v1/catalog/databases/{database}",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=DatabaseResponse,
    ),
    Route(
        id="catalog.tables.list",
        method="GET",
        path="/v1/catalog/databases/{database}/tables",
        idempotent=True,
        plane="user",
        request=None,
        query=TablesQuery,
        response=TablesResponse,
    ),
    Route(
        id="feedback.submit",
        method="POST",
        path="/v1/feedback",
        idempotent=False,
        plane="api",
        request=FeedbackSubmitRequest,
        query=None,
        response=FeedbackSubmitResponse,
    ),
    EnqueueRoute(
        id="sharedSpace.enqueue",
        method="POST",
        path="/v1/enqueue/shared-space",
        idempotent=False,
        plane="api",
        request=SharedSpaceEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="shared-space",
        stamped=frozenset({"schemaVersion", "traceparent"}),
    ),
    EnqueueRoute(
        id="notifications.enqueue",
        method="POST",
        path="/v1/enqueue/notifications",
        idempotent=False,
        plane="api",
        request=NotificationsEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="notifications",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="tableBuild.create",
        method="POST",
        path="/v1/enqueue/table-build",
        idempotent=False,
        plane="api",
        request=TableBuildCreateRequest,
        query=None,
        response=EnqueueAccepted,
        queue="table-builder",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="tableBuild.refresh",
        method="POST",
        path="/v1/enqueue/table-refresh",
        idempotent=False,
        plane="api",
        request=TableBuildRefreshRequest,
        query=None,
        response=EnqueueAccepted,
        queue="table-builder",
        stamped=frozenset({"mode", "traceparent"}),
    ),
    EnqueueRoute(
        id="tableShare.enqueue",
        method="POST",
        path="/v1/enqueue/table-share",
        idempotent=False,
        plane="api",
        request=TableShareEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="table-share",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="dataQuality.enqueue",
        method="POST",
        path="/v1/enqueue/data-quality",
        idempotent=False,
        plane="api",
        request=DataQualityEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="data-quality",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="fileSend.enqueue",
        method="POST",
        path="/v1/enqueue/file-send",
        idempotent=False,
        plane="api",
        request=FileSendEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="file-send",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="archive.archive",
        method="POST",
        path="/v1/enqueue/archive",
        idempotent=False,
        plane="api",
        request=ArchiveEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="archive",
        stamped=frozenset({"mode", "traceparent"}),
    ),
    EnqueueRoute(
        id="archive.restore",
        method="POST",
        path="/v1/enqueue/restore",
        idempotent=False,
        plane="api",
        request=RestoreEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="archive",
        stamped=frozenset({"mode", "traceparent"}),
    ),
    EnqueueRoute(
        id="fileOps.enqueue",
        method="POST",
        path="/v1/enqueue/file-ops",
        idempotent=False,
        plane="api",
        request=FileOpsEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="file-ops",
        stamped=frozenset({"traceparent"}),
    ),
    EnqueueRoute(
        id="resultsConversion.enqueue",
        method="POST",
        path="/v1/enqueue/results-conversion",
        idempotent=False,
        plane="api",
        request=ResultsConversionEnqueueRequest,
        query=None,
        response=EnqueueAccepted,
        queue="results-conversion",
        stamped=frozenset({"traceparent"}),
    ),
)


ENQUEUE_ROUTES: Final[tuple[EnqueueRoute, ...]] = tuple(
    route for route in ROUTES if isinstance(route, EnqueueRoute)
)



class UnsupportedTypeError(Exception):
    """Raised when an annotation falls outside the closed vocabulary.

    Deliberately fatal rather than recoverable. The repair a builder reaches for is a fallback
    type, and a fallback agrees with every possible value — so the failure this raises loudly is
    the one that would otherwise be silent forever.
    """


@dataclass(frozen=True)
class TypeNode:
    """One annotation, normalised into the closed vocabulary.

    The single representation both consumers read: the generator renders it to TypeScript, the
    validator interprets it against a value. One walk, two readers — so neither can come to
    support a shape the other refuses.

    Attributes:
      kind: Which of the vocabulary's forms this is.
      of: The contained node, for a list or an optional.
      literals: The permitted string values, for a literal union.
      name: The declared type's name, for an object.
      fields: Name, type and requiredness for each key of an object.
    """

    kind: Literal["str", "int", "float", "bool", "none", "list", "optional", "literal", "object"]
    of: tuple["TypeNode", ...] = ()
    literals: tuple[str, ...] = ()
    name: str = ""
    fields: tuple[tuple[str, "TypeNode", bool], ...] = field(default=())


_SCALARS: Final[dict[Any, TypeNode]] = {
    str: TypeNode(kind="str"),
    int: TypeNode(kind="int"),
    float: TypeNode(kind="float"),
    bool: TypeNode(kind="bool"),
}


def walk(annotation: Any) -> TypeNode:
    """Normalises one annotation, or refuses it.

    The vocabulary is str, int, float, bool, None, list[X], X | None, Literal over strings, a
    reference to another declared TypedDict, and optional keys. X is drawn from the same
    vocabulary, recursively.

    Args:
      annotation: The annotation to normalise.

    Returns:
      The normalised node.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary. Never returns a
        permissive node in its place.
    """
    if annotation is type(None):
        return TypeNode(kind="none")
    if annotation in _SCALARS:
        return _SCALARS[annotation]

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        if not args or not all(isinstance(value, str) for value in args):
            raise UnsupportedTypeError(f"Literal over non-strings: {annotation!r}")
        return TypeNode(kind="literal", literals=tuple(args))

    if origin is list:
        if len(args) != 1:
            raise UnsupportedTypeError(f"list without exactly one argument: {annotation!r}")
        return TypeNode(kind="list", of=(walk(args[0]),))

    if _is_union(origin):
        present = [arg for arg in args if arg is not type(None)]
        if len(present) != 1 or len(args) != 2:
            raise UnsupportedTypeError(f"union that is not X | None: {annotation!r}")
        return TypeNode(kind="optional", of=(walk(present[0]),))

    if _is_typed_dict(annotation):
        return _object_node(annotation)

    raise UnsupportedTypeError(f"outside the contract's type vocabulary: {annotation!r}")


def _is_union(origin: Any) -> bool:
    """Whether an origin is a union, in either spelling.

    Both are checked because the two spellings are not the same object: ``X | None`` produces
    ``types.UnionType`` while ``Optional[X]`` produces ``typing.Union``, and a declaration using
    the one that is not checked would be refused for a reason that reads as a vocabulary gap.

    Args:
      origin: The annotation's origin.

    Returns:
      True if the origin is a union.

    Raises:
      None.
    """
    import types
    import typing

    return origin is types.UnionType or origin is typing.Union


def _is_typed_dict(annotation: Any) -> bool:
    """Whether an annotation is a declared TypedDict.

    Args:
      annotation: The annotation to test.

    Returns:
      True if it is a TypedDict class.

    Raises:
      None.
    """
    return isinstance(annotation, type) and hasattr(annotation, "__required_keys__")


def _object_node(annotation: Any) -> TypeNode:
    """Normalises a TypedDict, in declaration order.

    Order is taken from the annotations rather than from the required and optional key sets,
    which are frozensets and iterate unpredictably — the emitter's output has to be
    byte-identical across runs for the regeneration gate to mean anything.

    Args:
      annotation: The TypedDict class.

    Returns:
      The object node, its fields in declaration order.

    Raises:
      UnsupportedTypeError: If any field's type is outside the vocabulary.
    """
    hints = get_type_hints(annotation)
    required = set(annotation.__required_keys__)
    fields = tuple(
        (name, walk(hints[name]), name in required) for name in annotation.__annotations__
    )
    return TypeNode(kind="object", name=annotation.__name__, fields=fields)


def declared_types() -> tuple[Any, ...]:
    """Every TypedDict the generated TypeScript must carry, in a deterministic order.

    Walks the routes in declaration order and each route's request, then its query, then its
    response, so the emitted file's order is a function of this module alone.

    Args:
      None.

    Returns:
      The TypedDict classes, first-seen order, without duplicates.

    Raises:
      None.
    """
    seen: list[Any] = []
    for route in ROUTES:
        for annotation in (route.request, route.query, route.response):
            for found in _referenced(annotation):
                if found not in seen:
                    seen.append(found)
    for annotation in (ApiErrorDetail, ApiErrorBody):
        for found in _referenced(annotation):
            if found not in seen:
                seen.append(found)
    return tuple(seen)


def _referenced(annotation: Any) -> list[Any]:
    """Every TypedDict reachable from one annotation, dependencies first.

    Args:
      annotation: The annotation to search, or None.

    Returns:
      The TypedDict classes it reaches, each before the type referencing it.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary.
    """
    if annotation is None:
        return []
    if not _is_typed_dict(annotation):
        walk(annotation)
        return []
    found: list[Any] = []
    for nested in get_type_hints(annotation).values():
        for reachable in _nested_typed_dicts(nested):
            if reachable not in found:
                found.append(reachable)
    if annotation not in found:
        found.append(annotation)
    return found


def _nested_typed_dicts(annotation: Any) -> list[Any]:
    """Every TypedDict inside one annotation, dependencies first.

    Args:
      annotation: The annotation to search.

    Returns:
      The TypedDict classes it contains.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary.
    """
    if _is_typed_dict(annotation):
        return _referenced(annotation)
    args = get_args(annotation)
    if get_origin(annotation) is Literal or not args:
        walk(annotation)
        return []
    found: list[Any] = []
    for arg in args:
        if arg is not type(None):
            found.extend(_nested_typed_dicts(arg))
    return found


def check_routes() -> None:
    """Refuses a route declaration the wire contract cannot carry.

    A 200 body is always a JSON object, never a bare array, string or number, so an additive
    field always has somewhere to go — and "additive only within a version" is the whole reason
    a loaded tab survives an API deploy. A route answering ``list[str]`` has nowhere to put the
    next field and would force a new version to add one.

    Args:
      None.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If a route's response, or a declared request, is not an object type,
        or if a path template is malformed or ambiguous against another route's.
    """
    for route in ROUTES:
        if not _is_typed_dict(route.response):
            raise UnsupportedTypeError(
                f"{route.id} answers {route.response!r}; every 200 body is an object"
            )
        if route.request is not None and not _is_typed_dict(route.request):
            raise UnsupportedTypeError(
                f"{route.id} accepts {route.request!r}; every request body is an object"
            )
        if route.query is not None:
            _check_query(route)
        _check_path(route)
    _check_paths_are_unambiguous()


def _check_path(route: "Route") -> None:
    """Refuses a path template that would silently match nothing.

    **A malformed placeholder has no symptom.** ``{query-execution-id}`` does not name a
    parameter, so it can only be read as a literal segment — and a literal segment wearing
    braces matches no request anybody sends. The route then answers 404 to every caller while
    the table, the generated TypeScript and every type-level check stay perfectly green. That is
    why this is refused where a declaration is judged rather than repaired where a request is
    matched.

    A name repeated within one path is refused for the neighbouring reason: the later segment
    would overwrite the earlier one and the route would act on one value believing it had two.

    **Every segment carrying a brace is judged, not only the balanced ones.** ``{database`` and
    ``db-{database}`` are placeholders somebody meant and the matcher cannot see: unbalanced or
    embedded, they read as literals, the route matches nothing, and — measured — the only thing
    that reddens is the regeneration gate, which an author clears by regenerating. The route then
    publishes no parameters at all, so the browser's own compile-time check is off for it too.

    Args:
      route: The route whose path to check.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If a placeholder is malformed, or a name appears twice.
    """
    for segment in route.path.split("/"):
        if _is_placeholder(segment) and PARAMETER_NAME_RE.match(segment[1:-1]):
            continue
        if "{" in segment or "}" in segment:
            raise UnsupportedTypeError(
                f"{route.id} declares the malformed path placeholder {segment!r}; it would be "
                f"read as a literal and the route would match nothing"
            )
    names = path_parameters(route.path)
    if len(set(names)) != len(names):
        raise UnsupportedTypeError(
            f"{route.id} declares a path parameter twice: {route.path!r}"
        )


def _check_paths_are_unambiguous() -> None:
    """Refuses two routes whose templates can both match one concrete path.

    Resolution takes the first row that matches, so an ambiguous pair resolves by DECLARATION
    ORDER — which is to say by an accident of where somebody inserted a row. There is no
    precedence rule here and deliberately none: a rule saying literals win would be a second
    thing to reason about, and refusing the collision outright means it can never arise.

    Args:
      None.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If two routes sharing a method have overlapping templates.
    """
    for index, route in enumerate(ROUTES):
        for other in ROUTES[index + 1 :]:
            if route.method == other.method and _templates_overlap(route.path, other.path):
                raise UnsupportedTypeError(
                    f"{route.id} and {other.id} both match {route.path!r}; resolution would "
                    f"depend on which row was declared first"
                )


def _templates_overlap(one: str, other: str) -> bool:
    """Whether one concrete path could satisfy both templates.

    Args:
      one: A declared path.
      other: Another declared path.

    Returns:
      True if some request path matches both.

    Raises:
      None.
    """
    left = one.split("/")
    right = other.split("/")
    if len(left) != len(right):
        return False
    return all(
        _is_placeholder(expected) or _is_placeholder(given) or expected == given
        for expected, given in zip(left, right, strict=True)
    )


_QUERY_KINDS: Final[frozenset[str]] = frozenset({"str", "literal"})


def _check_query(route: "Route") -> None:
    """Refuses a query declaration a query string cannot carry.

    **A query string is all strings.** API Gateway hands ``queryStringParameters`` over as
    ``dict[str, str]``, so a declaration naming an int, a bool or a nested object type-checks in
    the browser, generates clean TypeScript, and then refuses every real request with a 400 the
    handler never sees. Measured, not predicted: a declaration carrying ``space: SpaceRef`` and
    ``maxKeys: int`` emitted correct TypeScript and 400'd on the exact payload the gateway sends.

    So the vocabulary NARROWS here rather than widening. A route wanting a structured value in a
    query flattens it — ``spaceKind`` and ``spaceName`` rather than a ``SpaceRef`` — and the
    divergence from the body's own shape is deliberate. Refused at declaration time, which is a
    build-time failure, rather than per request, which is an outage.

    Args:
      route: The route whose query declaration to check.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If the query is not an object, or carries a non-string field.
    """
    if not _is_typed_dict(route.query):
        raise UnsupportedTypeError(
            f"{route.id} accepts {route.query!r}; every query is an object"
        )
    for name, node, _required in walk(route.query).fields:
        inner = node.of[0] if node.kind == "optional" else node
        if inner.kind not in _QUERY_KINDS:
            raise UnsupportedTypeError(
                f"{route.id}'s query field {name!r} is {inner.kind}; a query string carries "
                f"only strings, so declare it str or a Literal of strs and flatten what is not"
            )


def route_by_id(route_id: str) -> Route | None:
    """Finds a route by its id.

    Reads ``ROUTES`` on every call rather than an index built at import, so a test that adds a
    route sees it without reaching into a private cache — which is the only way the claim "adding
    a row makes the route reachable with no other edit" can be checked at all.

    Args:
      route_id: The route's id.

    Returns:
      The route, or None if no route carries that id.

    Raises:
      None.
    """
    for route in ROUTES:
        if route.id == route_id:
            return route
    return None


def path_parameters(path: str) -> tuple[str, ...]:
    """The placeholder names in one path template, in the order they appear.

    Read by the emitter as well as by the matcher, so the TypeScript a caller is typed against
    and the segments the server extracts come from one reading of one string.

    Args:
      path: The route's declared path.

    Returns:
      The placeholder names, empty for a fixed path.

    Raises:
      None. A malformed placeholder is not this function's business — it is refused by
        ``check_routes``, which is the one place a declaration is judged.
    """
    return tuple(
        segment[1:-1] for segment in path.split("/") if _is_placeholder(segment)
    )


def _is_placeholder(segment: str) -> bool:
    """Whether one declared segment is a placeholder rather than a literal.

    Judged by the braces alone, NOT by the name inside them. A segment wearing braces whose name
    is malformed must reach ``check_routes`` to be refused; classifying it as a literal here
    would hide it, and the route would then match nothing while looking perfectly ordinary.

    Args:
      segment: One segment of a declared path.

    Returns:
      True if the segment is written as a placeholder.

    Raises:
      None.
    """
    return len(segment) >= 2 and segment.startswith("{") and segment.endswith("}")


def _match_path(template: str, path: str) -> Mapping[str, str] | None:
    """Matches one concrete path against one declared template.

    A placeholder matches exactly one NON-EMPTY segment, so a doubled slash resolves to no route
    rather than to a route holding an empty identifier.

    **The path arrives percent-DECODED.** Measured against the deployed API rather than assumed:
    ``GET /health%7A`` answers 200, having matched ``/healthz``, and ``GET /healthz%20`` answers
    401, having matched nothing. So the client encodes each segment and this is the one decode
    point — nothing here unquotes, because a second decode would turn a caller's literal ``%2F``
    into a separator.

    **A value carrying a slash therefore never reaches the route that named it, and this side
    cannot tell.** By the time the path is matched, a decoded ``%2F`` is indistinguishable from a
    separator the caller typed, so such a request resolves to whichever template has the longer
    segment count — ``/v1/queries/{queryExecutionId}`` asked for ``abc/results`` arrives here as
    ``athena.results`` for execution ``abc`` — or, with no such sibling, to nothing at all. The
    CLIENT refuses such a value before sending it, and the outcomes here are what make that worth
    doing rather than accepting a 404 nobody would mind.

    That refusal is about where the check can WORK, not about safety: both templates sit on the
    user plane under the same assumed identity, so nothing is reachable that a direct request
    would not also reach. Whether ``rawPath`` preserves the encoding and would allow the same
    check on this side is **not measured** — this function is handed
    ``requestContext.http.path``, for the reason ``handler`` gives, and that is the field the
    statement above is about.

    Args:
      template: The route's declared path.
      path: The request's path.

    Returns:
      The extracted parameters, empty for a fixed path that matched; None when the template does
      not match at all.

    Raises:
      None.
    """
    declared = template.split("/")
    actual = path.split("/")
    if len(declared) != len(actual):
        return None

    found: dict[str, str] = {}
    for expected, given in zip(declared, actual, strict=True):
        if _is_placeholder(expected):
            if not given:
                return None
            found[expected[1:-1]] = given
        elif expected != given:
            return None
    return found


def route_for(method: str, path: str) -> tuple[Route, Mapping[str, str]] | None:
    """Resolves a request line to the route serving it and the parameters it carried.

    Args:
      method: The request's HTTP method.
      path: The request's path.

    Returns:
      The route and its extracted path parameters, or None when no route serves that pair.

    Raises:
      None.
    """
    for route in ROUTES:
        if route.method != method:
            continue
        found = _match_path(route.path, path)
        if found is not None:
            return route, found
    return None


def validate_request(route: Route, body: object) -> str | None:
    """Checks a request body against the route's declared type.

    Reads the same walk of the same annotation the generator emits from, so the shape accepted
    here and the shape the browser was typed against cannot disagree.

    Args:
      route: The route the body was sent to.
      body: The parsed request body, or None when none was sent.

    Returns:
      None when the body is acceptable, otherwise the machine code refusing it.

    Raises:
      UnsupportedTypeError: If the route's declared request type is outside the vocabulary,
        which is a defect in the declaration rather than in the request.
    """
    if route.request is None:
        return None if body in (None, {}) else "InvalidRequest"
    if not _matches(walk(route.request), body):
        return "InvalidRequest"
    return None


def validate_query(route: Route, query: Mapping[str, str] | None) -> str | None:
    """Checks a request's query string against the route's declared type.

    The same walk of the same annotation the generator emits from, exactly as ``validate_request``
    uses for the body — so a query the browser was typed against and a query this refuses cannot
    disagree.

    Args:
      route: The route the query was sent to.
      query: The gateway's parsed query string, or None when none was sent.

    Returns:
      None when the query is acceptable, otherwise the machine code refusing it.

    Raises:
      UnsupportedTypeError: If the route's declared query type is outside the vocabulary, which
        is a defect in the declaration rather than in the request.
    """
    if route.query is None:
        return None if not query else "InvalidRequest"
    if not _matches(walk(route.query), dict(query or {})):
        return "InvalidRequest"
    return None


def _matches(node: TypeNode, value: object) -> bool:
    """Whether one value satisfies one normalised node.

    An object refuses an unknown key as firmly as a missing one: a body carrying a field the
    contract does not declare is a caller and a server that disagree about the shape, and
    accepting it silently is how the disagreement survives to the next version.

    Args:
      node: The normalised node.
      value: The value to check.

    Returns:
      True if the value satisfies the node.

    Raises:
      None.
    """
    if node.kind == "none":
        return value is None
    if node.kind == "str":
        return isinstance(value, str)
    if node.kind == "bool":
        return isinstance(value, bool)
    if node.kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if node.kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if node.kind == "literal":
        return isinstance(value, str) and value in node.literals
    if node.kind == "optional":
        return value is None or _matches(node.of[0], value)
    if node.kind == "list":
        return isinstance(value, list) and all(_matches(node.of[0], item) for item in value)
    if node.kind == "object":
        if not isinstance(value, dict):
            return False
        declared = {name for name, _, _ in node.fields}
        if set(value) - declared:
            return False
        for name, child, required in node.fields:
            if name not in value:
                if required:
                    return False
                continue
            if not _matches(child, value[name]):
                return False
        return True
    return False
