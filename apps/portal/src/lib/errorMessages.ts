// The single source of truth for user-facing error wording.
//
// Every error a user can see (toast, banner, inline) is routed through
// `toUserMessage`. Raw AWS / Cognito text is never shown to a user, and Athena's
// is shown only as the `detail` of a failed query whose error is in the user's
// own SQL (see `queryFailureDetail`): the mapper resolves a friendly message from
// a stable app `code`, a known AWS error `name`, or an Athena engine-message
// pattern, and otherwise returns a generic "Contact the Administrator." fallback.
// The original error is logged to the console in dev builds only (see
// `logOriginal`) so developers can still debug.

/** What a surface renders: an optional bold title, one short sentence, and sometimes the engine's own words. */
export type UserFacingMessage = {
  title?: string;
  message: string;
  /**
   * Athena's own message, beneath the sentence behind a closed "Details" disclosure. Present only
   * for a FAILED query whose text {@link queryFailureDetail} judged to describe the user's own SQL.
   */
  detail?: string;
};

/** Accepts a thrown value or a `ServiceResult` error object `{message, code}`. */
type MappableError = unknown;

/** The typed values an error may carry for its rule's sentence: an API bound, or the execution a watch gave up on. */
type RuleParams = {limit?: number; queryExecutionId?: string};

/**
 * One authored entry per known condition. The comment on each rule records the
 * trigger + whether the user can fix it — the "why does a user see this?"
 * answer lives next to the mapping.
 */
type ErrorRule = {
  /** App code or AWS/Cognito error `name` this matches (exact). */
  code?: string;
  /** Or a matcher over the technical message (e.g. Athena "cannot be resolved"). */
  match?: (technicalMessage: string) => boolean;
  /**
   * A sentence built from the typed values the API sent, used in place of `message` when they
   * are present. The API answers a field over its bound with the bound itself, and a static
   * sentence throws that away — which leaves the user guessing at a number the server knows.
   */
  withParams?: (params: RuleParams) => string;
  title?: string;
  /** Authored friendly text. Omitted only for `passthrough` rules. */
  message?: string;
  /**
   * True → the message tells the user how to fix it; false → "Contact the
   * Administrator". Documentation only; drives nothing at runtime.
   */
  userFixable: boolean;
  /**
   * The message was authored by our own service layer and already embeds
   * user-safe specifics (a filename, a byte count, a validation reason), so the
   * mapper returns the service `message` unchanged. Only ever set on app codes
   * our services produce — never on an AWS `name`, so raw AWS text can't leak.
   */
  passthrough?: boolean;
};

/** The generic non-fixable fallback — the only thing an unknown error yields. */
const GENERIC: UserFacingMessage = {
  message: 'Something went wrong. Contact the Administrator.'
};

const CONTACT_ADMIN = 'Contact the Administrator.';

// ── Rules keyed by app code / AWS name ──────────────────────────────────────
// Order within a lookup is irrelevant (exact `code` match); `MATCH_RULES` below
// is ordered because several patterns can match one Athena message. Two orderings there
// are load-bearing rather than incidental: the catalog-refusal pair precedes the permission
// rule, whose pattern the same denial matches, and the user-SQL rule precedes the syntax
// catch-all, which reads any `line N:M` as a syntax error.

const CODE_RULES: readonly ErrorRule[] = [
  // ── App codes our file-browser/query services already author.
  // Trigger: a service returned this code with user-safe, often
  // parameterized text (filename / size / validation reason). User-fixable —
  // the wording tells them what to change. Passed through unchanged. ──
  {code: 'Collision', userFixable: true, passthrough: true}, // dest name already exists (carries the name)
  {code: 'ProtectedObject', userFixable: false, passthrough: true}, // storage marker can't be deleted/moved
  {code: 'InvalidName', userFixable: true, passthrough: true}, // folder-name validation reason
  {code: 'TooLarge', userFixable: true, passthrough: true}, // upload exceeds the max size (carries the limit)
  {code: 'NoFreeName', userFixable: false, passthrough: true}, // 999 numbered names are taken at the destination

  // Trigger: a folder reached the browser's copy, move or delete hook, which happens only through
  // the race `dispatch` in `useFileBrowserDialogs` describes. The service may be off or on in that
  // race, so the sentence names neither cause; a reload shows the real state either way, which is
  // what makes it user-fixable. NOT passthrough: the services raise it per item and the sentence
  // is the same one every time.
  {
    code: 'PlaneRequired',
    message:
      "Folders are handled by the file operations service, which couldn't take this request. Reload the page and try again.",
    userFixable: true
  },

  // NO PRODUCER REMAINS. The enqueue services raised this when a control plane's queue URL was
  // unset in the runtime configuration; the browser no longer reads a queue URL, and an unset one
  // is now a fault the API reports. The rule is kept rather than deleted because `PASSTHROUGH_CODES`
  // is COMPUTED from this list and the disjointness guard is written against it, so removing a
  // code moves it between two derived sets for no reason beyond tidiness. If something mints this
  // again, it must still reach the user as its own sentence rather than "Something went wrong."
  {code: 'NotConfigured', userFixable: false, passthrough: true},

  // Trigger: the runtime configuration document was missing, unreadable, of an
  // unsupported version or incomplete, so the app refused to start. NOT passthrough,
  // unlike the rule above: the loader returns a machine reason, and what a user needs is
  // one sentence that does not name a key, a value or a URL. The operator's diagnostic is
  // the single console line the boot failure writes.
  // Trigger: the file browser resolved no bucket for the space in view, or there is no
  // signed-in user to resolve one for. NOT the boot failure — the app has started, and one
  // surface is unusable. The wording used to name a `VITE_*` variable and tell the reader
  // to edit a .env file, which was dev-only advice shown to everyone.
  {
    code: 'SpaceUnavailable',
    title: 'This space is unavailable',
    message: `Data Quarry could not resolve where this space is stored. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  {
    code: 'RuntimeConfigUnavailable',
    title: 'Data Quarry could not start',
    message: `Data Quarry is not configured correctly. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: a send whose selection exceeds the file-send plane's caps, refused by
  // the producer before it reaches SQS. Passthrough for the same reason as the rule above —
  // the sentence is authored by our own service layer and embeds no AWS text. It is genuinely
  // user-fixable, and it has to say so: the alternative to refusing here is a request too
  // large for StartExecution, which dead-letters and reaches the user minutes later as a
  // failure notification for something they could have fixed by selecting less.
  {code: 'SelectionTooLarge', userFixable: true, passthrough: true},
  // The Data Explorer rendered a statement longer than StartQueryExecution accepts, caught
  // before anything was started. The user's way out is their own filters, so it says which.
  {
    code: 'ExplorationStatementTooLong',
    message: 'This query is too long to run. Use fewer or shorter filter values, or a shorter expression.',
    userFixable: true
  },

  // Trigger: a saved query's `.sql` file is gone — deleted from the file browser, or by a
  // colleague in a shared space, between the listing and the open. Passthrough because the
  // sentence NAMES the file, which the generic `NotFound` cannot: a user looking at a list of
  // twenty-five queries needs to know which one vanished, not that "that item" did.
  {code: 'SavedQueryNotFound', userFixable: true, passthrough: true},

  // Trigger: the API refused to READ a stored document as too large — over the document cap, or
  // too large to send back once escaped. The document reader re-codes the API's `PayloadTooLarge`
  // as this, because that code's sentence asks for less in a request, and a person opening their
  // history sent nothing they could shrink. Not user-fixable: the documents read without a
  // sentence of their own are ones the app writes for itself, and nothing a user can do from the
  // app makes one smaller.
  {code: 'DocumentTooLarge', message: `This is too large to open. ${CONTACT_ADMIN}`, userFixable: false},

  // Trigger: a saved query's `.sql` file is too large to read. A save is refused at the same
  // bounds, so the file arrived through Files, and Files is also the way out: the folder is an
  // ordinary visible one there, and a download goes straight to S3 without passing the bound.
  {
    code: 'SavedQueryTooLarge',
    message:
      'This saved query is too large to open here. Download it from its space’s saved_queries folder in Files to read it.',
    userFixable: true
  },

  // ── Data-quality report reads. Deliberately NOT folded into
  // the generic `NotFound` above: that one says "refresh and try again", which is
  // wrong advice here — a report the user followed a link to is either still being
  // written, or gone for good, and refreshing a deleted one forever is not a plan. ──
  {
    code: 'DataQualityReportNotFound',
    message: 'That report isn’t available. It may still be running, or it may have been deleted.',
    userFixable: true
  },
  {
    code: 'DataQualityReportUnreadable',
    message: `That report couldn’t be read. ${CONTACT_ADMIN}`,
    userFixable: false
  },
  // Not `DocumentTooLarge`, which sends the user to an administrator: a check run now writes a
  // report that leaves out what does not fit, so a new run gives them one that opens.
  {
    code: 'DataQualityReportTooLarge',
    message:
      'This report is too large to open here. Run the check again from Data quality: a new report leaves out what doesn’t fit, and says how much.',
    userFixable: true
  },

  // ── Settings documents whose live body the write path could not use.
  // The read-modify-write path never treats "unreadable" as the empty document,
  // because the write is an unconditional PutObject: an empty misread would be
  // COMMITTED, discarding the whole document. What follows from that splits three
  // ways, and each way owes the user a different sentence — what happened to their
  // data is not the same fact in the three cases. ──
  //
  // Recovered: the write WENT THROUGH. The old document couldn't be read, so it was
  // copied aside and a fresh one written — which means the list the user is now
  // looking at is missing everything that was in it before, and saying so is the
  // whole point. Not user-fixable in the sense of an action to take, but not an
  // administrator's problem either: nothing is broken any more.
  //
  // The saved-queries JSON store is retired, so query history is the one
  // `user_settings/` document this trio still speaks for. ──
  {
    code: 'QueryHistoryRecovered',
    message: 'Your query history couldn’t be read, so a copy was kept and a new history started.',
    userFixable: true
  },

  // Newer: valid JSON from a LATER version of this app — almost certainly another
  // tab that has since been updated. Refused deliberately and left untouched, since
  // overwriting it would downgrade real data. Reloading gets the current build, so
  // this is the one of the three the user can actually fix. ──
  {
    code: 'QueryHistoryNewerVersion',
    message: 'Your query history was updated by a newer version of this app. Reload the page and try again.',
    userFixable: true
  },

  // Quarantine failed: the document couldn't be read AND couldn't be copied aside,
  // so the write was refused rather than overwriting it. Nothing changed — which is
  // the reassurance the user needs, ahead of the cause. ──
  {
    code: 'QueryHistoryQuarantineFailed',
    message: `Your query history couldn’t be read, so nothing was changed. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: user aborted an in-flight upload. Not an error to fix. ──
  {code: 'Cancelled', message: 'Upload cancelled.', userFixable: true},
  // Trigger: an object/table/DDL target was missing (S3 404, Glue table-absent).
  // User-fixable — refresh or pick another item. ──
  {code: 'NotFound', message: 'That item no longer exists. Refresh and try again.', userFixable: true},
  // Trigger: results were asked for before the execution finished. The API resolves what the
  // engine text below could only be matched on — `InvalidRequestException` is also what Athena
  // raises for a malformed query at submit, so the browser could never key on the NAME, and a
  // rule keyed on the message is all it had.
  //
  // The sentence is byte-identical to the match rule's, deliberately: a code rule outranks every
  // message rule, so while both exist the wording cannot move, and the match rule goes when the
  // catalog services stop meeting Athena's own exception. ──
  // Trigger: a service asked for a route whose path parameter could not be put in a URL — a
  // value carrying a separator, or one the URL parser would collapse. The request was never sent.
  // An app bug rather than anything a user or an administrator did, so the wording says only what
  // is true and the code is what a developer reads. ──
  {
    code: 'UnsendableParameter',
    message: `That request couldn’t be built. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: Athena refused the STATEMENT at submit, rather than accepting it and failing the
  // execution. The API resolves it to a code because the engine's own text cannot cross the wire.
  //
  // Its own code rather than the generic `InvalidRequest`, because the generic sentence is for
  // what a user cannot act on and this is the opposite: they can read their SQL and fix it. Most
  // syntax errors still arrive the other way — a FAILED execution whose reason the match rule
  // below reads — and the sentence is asserted equal to that one so the two paths cannot drift. ──
  {
    code: 'QuerySyntaxError',
    message: 'There’s a syntax error in your query. Check the SQL and try again.',
    userFixable: true
  },

  {
    code: 'QueryNotFinished',
    message: 'The query is still running. Give it a moment and try again.',
    userFixable: true
  },

  // ── AWS / Cognito error names (services default `code` to the AWS `name`). ──
  // Trigger: scoped credentials denied the S3/Athena/Glue call. Almost always a
  // config/permission issue the user can't fix. ──
  // Trigger: S3 refused a presigned PUT whose window had already closed. Routine rather than
  // exceptional — the window is clamped to the signing session's remaining life, and a large file
  // can simply outlast it. Reachable on both upload paths: a single PUT has no retry at all, and a
  // multipart part re-mints on each attempt but can still exhaust them. It is user-fixable and the fix is one
  // sentence; the generic "contact the Administrator" would be wrong twice, because nothing is
  // misconfigured and the thing that helps goes unsaid.
  {
    code: 'UploadLinkExpired',
    message: 'That upload ran out of time before it finished. Upload the file again.',
    userFixable: true
  },

  // Trigger: S3 refused the bytes for a reason that is not an expiry and not a permission — a
  // throttle, a checksum mismatch, an outage. Distinct from the generic sentence because the user
  // CAN act: nothing was written, so retrying is safe and is what they should do.
  {
    code: 'UploadFailed',
    message: 'That file could not be uploaded. Nothing was saved — try again.',
    userFixable: true
  },

  // Trigger: every attempt at one part of a multipart upload failed. The wording says nothing was
  // saved, and that is TRUE of multipart in a way it is not of a single PUT: an upload that never
  // completes assembles no object at all, so there is no partial file to find or clean up.
  {
    code: 'UploadPartsExhausted',
    message: 'That file could not be uploaded, and nothing was saved. Try again.',
    userFixable: true
  },

  // Trigger: a part uploaded but its `ETag` response header was unreadable, which in practice means
  // the bucket's CORS stopped exposing it. NOT retryable — the bytes would go again and the header
  // would be absent again — and NOT completable, because an assembly request carrying nulls fails
  // at S3 with an error naming none of this. A deploy fault wearing a user-facing sentence, so it
  // says what happened to their file rather than blaming them.
  {
    code: 'UploadUnverifiable',
    message: `That upload could not be verified, so nothing was saved. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: the upload route answered a shape the chosen branch cannot use — a plan with no
  // upload id, or a single-PUT answer with no url. Only a deploy skew or a contract change reaches
  // it. Named rather than left to fall through, because the generic sentence for a stalled upload
  // row tells the user nothing about a file they can simply try again.
  {
    code: 'UploadPlanUnusable',
    message: `That upload could not be started. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  {code: 'AccessDenied', message: `You don't have permission to do that. ${CONTACT_ADMIN}`, userFixable: false},
  {
    code: 'AccessDeniedException',
    message: `You don't have permission to do that. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: no ID token — the user isn't signed in (or the session lapsed), or a hook was asked
  // to act with no signed-in username. User-fixable — sign in. ──
  {code: 'NotAuthenticated', message: 'Sign in to continue.', userFixable: true},

  // Trigger: the API refused a request as unauthenticated. Every one of its 401s is
  // byte-identical on purpose — no token, a bad one and an expired one are
  // indistinguishable — so this one wording has to cover all of them, and it is the
  // wording that is true of every case: sign in again and it will work. Its pair is
  // AccessDenied above, which is the case where signing in again cannot help. ──
  {code: 'SessionExpired', message: 'Your session expired. Sign in again.', userFixable: true},

  // Trigger: the API could not be reached, answered a 5xx, or is not configured in this
  // build. Not a credential problem, so the wording must not tell the user to sign in. ──
  {
    code: 'ApiUnavailable',
    message: `Can’t reach the server. Check your connection and try again.`,
    userFixable: true
  },

  // Trigger: the API could not act as the caller at all — the role would not assume, or the
  // username cannot be a session name. The user did nothing wrong and can do nothing about it,
  // so this must NOT read as a permission problem (AccessDenied above) or as a stale session
  // (SessionExpired above). Never passthrough: the technical message is AWS's own and names a
  // role ARN and an account id. ──
  {
    code: 'IdentityUnavailable',
    message: `Something went wrong on our side. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // ── The API's remaining machine codes. NONE is passthrough, and that is the point rather
  // than an oversight: the API returns operator text nobody renders, so every sentence a user
  // sees for an API failure is authored here. A guard asserts the API's codes and the
  // passthrough codes below stay disjoint sets. ──

  // Trigger: the API refused a request body as malformed — a key it does not declare, one it
  // requires and did not get, or a value of the wrong type. Not user-fixable: a user cannot edit
  // a request, and every one of these is a defect on our side.
  {code: 'InvalidRequest', message: `Something went wrong. ${CONTACT_ADMIN}`, userFixable: false},

  // Trigger: the request lost a race — the name was taken, the lock was held. Distinct from
  // `Collision` above, which is our own service layer naming the colliding item; this one is the
  // API's, and it can name nothing, so the wording must stand without specifics.
  {code: 'Conflict', message: 'That changed while you were working. Refresh and try again.', userFixable: true},

  // Trigger: the request body, or one field in it, exceeded what the API accepts. Distinct from
  // `TooLarge` above, which is our upload path naming the file and the limit. This one used to
  // carry neither and said "try again with less selected" — false for the case that is now the
  // common one, a single field over its own bound, where nothing is selected at all. The API
  // sends the bound it enforced, so the sentence names it when it is there. Both sentences are for
  // a WRITE: a read refused the same way is re-coded by the document reader as `DocumentTooLarge`,
  // since the person opening a document sent nothing they could make smaller. The one read left on
  // this code is the feature-flag document's, whose failure falls back to defaults and renders
  // nothing.
  {
    code: 'PayloadTooLarge',
    message: 'That request was too large. Try again with less in it.',
    // Unit-neutral on purpose: the API's bounds are counted in three different units — serialized
    // bytes, a string's own bytes, and for a roster or a recipient list a plain count — and the
    // wire carries the number without which of them it is. "Over its limit of 44" is true of all
    // three; "44-byte limit" would be false for the one that means people.
    withParams: ({limit}) =>
      `That request was too large — one field is over its limit of ${limit?.toLocaleString()}. Make it smaller and try again.`,
    userFixable: true
  },
  {code: 'UnsupportedMediaType', message: `Something went wrong. ${CONTACT_ADMIN}`, userFixable: false},

  // Trigger: the API throttled us. Same wording as the AWS throttles below, deliberately — from
  // a user's side it is the same situation and the same action.
  {code: 'RateLimited', message: 'The service is busy. Wait a moment and try again.', userFixable: true},

  // Trigger: an unpredicted fault inside the API. The detail names the exception TYPE and is
  // read in a devtools panel; the user gets the one sentence that is true of all of them.
  {code: 'InternalError', message: `Something went wrong. ${CONTACT_ADMIN}`, userFixable: false},

  // ── The two codes the API client mints. The server can produce neither: both are facts
  // about this browser rather than answers from a server. ──
  {code: 'RequestTimeout', message: 'That took too long. Try again.', userFixable: true},
  {
    code: 'NetworkUnavailable',
    message: 'Can’t reach the server. Check your connection and try again.',
    userFixable: true
  },

  // Cognito's own refresh failure, and the only expiry name left with a producer. The three
  // beside it — ExpiredToken, ExpiredTokenException, CredentialsProviderError — were the
  // browser's AWS-credential expiry names, matched by a retry helper that no longer exists
  // and mintable by nothing the browser now talks to.
  {code: 'NotAuthorizedException', message: 'Your session expired. Sign in again.', userFixable: true},

  // Trigger: the browser couldn't reach AWS (offline, DNS, CORS). User-fixable —
  // check the connection and retry. ──
  {code: 'NetworkError', message: 'Can’t reach the server. Check your connection and try again.', userFixable: true},
  {
    code: 'NetworkingError',
    message: 'Can’t reach the server. Check your connection and try again.',
    userFixable: true
  },

  // Trigger: a client-side wait (query poll) hit its ceiling. User-fixable — retry. ──
  {code: 'Timeout', message: 'That took too long. Try again.', userFixable: true},

  // Trigger: a query watch outlived its ceiling while the execution was still queued or running.
  // Minted by the polling hook, never by the API. Not a failure, so it carries its own title: the
  // query goes on in Athena, and the browser has only stopped waiting. The sentence says where the
  // results land, because nothing in the app reattaches to an execution and that file is the one
  // way to read them without paying for the query again. `limit` is the ceiling in minutes, and
  // the execution id names the file. User-fixable in the sense that matters: it says what to do. ──
  {
    code: 'QueryStillRunning',
    title: 'Still running',
    message:
      'Data Quarry stopped waiting for this query, so its results won’t appear here. When it finishes, they’re saved in your files under system_settings/athenaresults.',
    withParams: ({limit, queryExecutionId}) =>
      `Data Quarry stopped waiting for this query after ${limit} minutes, so its results won’t appear here. When it finishes, they’re saved in your files under system_settings/athenaresults${queryExecutionId ? `, in a file named after its query ID (${queryExecutionId})` : ''}.`,
    userFixable: true
  },

  // Trigger: AWS throttled the request (rate limit). User-fixable — wait and retry. ──
  {code: 'ThrottlingException', message: 'The service is busy. Wait a moment and try again.', userFixable: true},
  {code: 'TooManyRequestsException', message: 'The service is busy. Wait a moment and try again.', userFixable: true},
  {code: 'RequestLimitExceeded', message: 'The service is busy. Wait a moment and try again.', userFixable: true},
  {code: 'SlowDown', message: 'The service is busy. Wait a moment and try again.', userFixable: true}
];

const CODE_INDEX = new Map<string, ErrorRule>(CODE_RULES.map((r) => [r.code as string, r]));

/**
 * Every code whose rule returns the SERVICE's own message unchanged.
 *
 * COMPUTED from the rules, never hand-listed — a second list is a list that stops matching, and
 * the guard reading it would then be comparing two stale copies rather than two derived sets.
 *
 * It exists to be intersected with the API's codes. A passthrough rule renders whatever text the
 * failure carried, so if the API ever returned one of these codes, server-authored text would
 * reach a user through a rule written to prevent exactly that.
 */
export const PASSTHROUGH_CODES: readonly string[] = CODE_RULES.filter((rule) => rule.passthrough).map(
  (rule) => rule.code as string
);

/**
 * Every code whose rule says the user can fix the thing that went wrong.
 *
 * COMPUTED from the rules for the same reason as the set above. It exists so a guard can hold the
 * one rule this module is for: **the generic "Contact the Administrator" sentence is reserved for
 * a failure the user cannot act on.** A code marked `userFixable` that resolves to it is a
 * contradiction — the app knows what is wrong and is telling the reader there is nothing to do —
 * and that is not hypothetical, it is why `QuerySyntaxError` exists.
 */
export const USER_FIXABLE_CODES: readonly string[] = CODE_RULES.filter(
  (rule) => rule.userFixable && rule.code !== undefined && !rule.passthrough
).map((rule) => rule.code as string);

// ── Athena engine-message patterns. ───────────────────
// Query failures surface as {code: 'FAILED', message: stateChangeReason}; there
// is no app code, so we match the raw engine text. Ordered by specificity, and three of the
// orderings are part of the behaviour rather than incidental: the catalog refusal an
// unqualified table really arrives as is read BEFORE the permission rule, whose pattern the
// same denial also matches; the user-SQL rule is read BEFORE the missing-database rule, so a
// classed `SCHEMA_NOT_FOUND` keeps the Details naming the schema; and the syntax catch-all is
// LAST, because `line N:M` appears in plenty of messages that are not syntax errors.

/**
 * Advice with exactly one trigger: the catalog refusal against `default`.
 *
 * A rule used to offer it for any "Table <bare name> does not exist" too, on the reasoning that
 * a name with no dot in it had no database. Athena does not report it that way — a missing table
 * arrives as `Table nope not found in database agriffith`, whose table token has no dot while the
 * database sits in a clause of its own — so the sentence reached people who HAD qualified their
 * table and told them to do the thing they had already done. A missing table is now answered by
 * the not-found rule, which mentions the database without asserting one is absent.
 */
const UNQUALIFIED_FIX = 'Add a database to each table, like `mydb.sales`.';

/** An Athena or Lake Formation refusal on permissions, rather than on what the SQL says. */
const PERMISSION_FAILURE = /(access denied|not authorized|insufficient (lake formation )?permission)/i;

/**
 * The Trino error classes whose message describes the user's own SQL. A pattern such as `[A-Z_]+:`
 * would admit `HIVE_*` split errors, which name S3 objects. `NOT_SUPPORTED` stays out: it is the
 * connectors' catch-all, so its wording is unbounded, and a user cannot act on it anyway.
 */
const USER_SQL_ERROR_CLASSES: readonly string[] = [
  'SYNTAX_ERROR',
  'COLUMN_NOT_FOUND',
  'TABLE_NOT_FOUND',
  'SCHEMA_NOT_FOUND',
  'TYPE_MISMATCH',
  'FUNCTION_NOT_FOUND',
  'AMBIGUOUS_NAME',
  'INVALID_CAST_ARGUMENT',
  'INVALID_FUNCTION_ARGUMENT',
  'INVALID_LITERAL',
  'DIVISION_BY_ZERO',
  'NUMERIC_VALUE_OUT_OF_RANGE',
  'EXPRESSION_NOT_AGGREGATE',
  'EXPRESSION_NOT_SCALAR',
  'INVALID_COLUMN_REFERENCE',
  'MISSING_COLUMN_ALIASES',
  'DUPLICATE_COLUMN_NAME'
];

/** A parse error Athena reports with no class in front of it: `line 1:23: mismatched input …`. */
const BARE_PARSE_POSITION = /^line \d+:\d+: /;

/** What marks a message as carrying more than the user's SQL, whatever its class says. */
const ENGINE_LOCATOR = /s3:\/\/|arn:|\b\d{12}\b|Service:|Request ID/i;

/**
 * The clause Athena appends to every COLUMN_NOT_FOUND. It names no resource, and without removing
 * it before the permission check every missing column would lose its Details.
 */
const COLUMN_NOT_FOUND_AUTHZ_CLAUSE = /\s*or requester is not authorized to access requested resources/i;

/** Long enough for a parse error's expected-token list to start; a message past it is cut, not hidden. */
const DETAIL_MAX_CHARS = 500;

/** The class an engine message opens with, when it opens with one from the closed list. */
function userSqlErrorClass(msg: string): string | undefined {
  const errorClass = /^([A-Z_]+):/.exec(msg)?.[1];
  return errorClass !== undefined && USER_SQL_ERROR_CLASSES.includes(errorClass) ? errorClass : undefined;
}

/** True when an engine message opens with a class from the closed list, or with a bare parse position. */
function isUserSqlError(msg: string): boolean {
  return userSqlErrorClass(msg) !== undefined || BARE_PARSE_POSITION.test(msg);
}

/**
 * A `glue:GetDatabase` denial, with the database it names captured.
 *
 * **The action and the name are matched together, deliberately.** A message can carry more than
 * one denial, and a name grabbed by a separate search takes whichever `:database/` comes first —
 * which may belong to a different action entirely, and would then pick the opposite sentence.
 * **The whole name is captured, then trailing punctuation is trimmed.** Bounding the capture to
 * a character class instead makes the comparison below a PREFIX test: `[A-Za-z0-9_]+` against
 * `database/default-archive` stops at the hyphen, captures `default`, and tells someone who
 * explicitly named `default-archive` to add a database prefix. Glue itself permits almost any
 * UTF-8 string as a database name — it is this project's own `CATALOG_IDENTIFIER_RE`, and the
 * matching username rule, that keep portal-created names to `[a-z][a-z0-9_]{2,62}`, and the rail
 * browses every database the caller can reach, not only the ones the portal made.
 *
 * If Athena rewords this, the pattern stops matching and the message falls through to the
 * permission rule — the sentence it had before this pair existed, which is generic but true,
 * rather than a confidently wrong one.
 */
const GLUE_DATABASE_DENIAL = /glue:GetDatabase on resource: arn:\S*:database\/(\S+)/i;

/** Punctuation a message can put after the name, which is never part of one. */
const TRAILING_PUNCTUATION = /[.,;:)\]}"']+$/;

/**
 * The database named in a `glue:GetDatabase` denial, or null when the message is not one.
 *
 * **This is the shape an unqualified table actually arrives as, and it is a catalog refusal
 * rather than a missing table.** Queries carry no active database, so `FROM sales` resolves
 * against `default`; nobody is a member of `default`, so the role is refused `glue:GetDatabase`
 * on it and the statement never reaches the table. The denial is otherwise indistinguishable
 * from a real permissions failure, which is why the name is read out rather than the message
 * merely classified.
 *
 * **A user who writes `default.sales` explicitly reads the same sentence as one who wrote no
 * database at all.** Glue creates a `default` database in every catalog, and nothing in the
 * denial says whether the name was typed or supplied by resolution, so the two cannot be told
 * apart here. Advising a prefix to someone who wrote one is the lesser wrong of the two.
 */
function glueDeniedDatabase(msg: string): string | null {
  const denied = GLUE_DATABASE_DENIAL.exec(msg);
  return denied ? denied[1].replace(TRAILING_PUNCTUATION, '') : null;
}

/** The database a statement naming none resolves against — nobody is a member of it. */
const IMPLICIT_DATABASE = 'default';

const MATCH_RULES: readonly ErrorRule[] = [
  // Trigger: a genuinely-missing (but qualified) table/view (incl. Athena's
  // TABLE_NOT_FOUND code). User-fixable — check the name. ──
  {
    match: (m) => /(table_not_found|(table|view)\b.*(does not exist|not found))/i.test(m),
    message: 'That table wasn’t found. Check the name and that it includes its database.',
    userFixable: true
  },
  // Trigger: a column reference Athena couldn't resolve (incl. COLUMN_NOT_FOUND).
  // User-fixable — fix the column name. ──
  {
    match: (m) => /(cannot be resolved|column_not_found|column .* (does not exist|not found))/i.test(m),
    message: 'A column in your query wasn’t found. Check the column names.',
    userFixable: true
  },
  // Trigger: a table named with no database, refused at the catalog against `default`.
  // User-fixable — qualify each table. Must precede the permission rule below, which the same
  // message matches on `not authorized`; without this pair an ordinary missing prefix reads as
  // a permissions failure and sends the user to an administrator for their own typo. ──
  {
    match: (m) => glueDeniedDatabase(m)?.toLowerCase() === IMPLICIT_DATABASE,
    message: UNQUALIFIED_FIX,
    userFixable: true
  },
  // Trigger: the same refusal naming some OTHER database — it does not exist, or the user is not
  // a member. The two are deliberately one answer to the caller, so the sentence covers both
  // rather than guessing which.
  //
  // **The sentence may not assume the reader typed the name.** The Data Explorer builds its own
  // SQL from a table picked out of the rail and maps a failed execution through here, so a member
  // whose grant is missing reaches this rule having typed nothing at all; "check the name" is the
  // conditional half for that reason, and the access half leads. ──
  {
    match: (m) => glueDeniedDatabase(m) !== null,
    message:
      'That database isn’t available to you. Ask the Administrator for access, or check the name if you typed it.',
    userFixable: true
  },
  // Trigger: Athena/Lake-Formation permission failure running the query. Not the
  // user's to fix. ──
  {
    match: (m) => PERMISSION_FAILURE.test(m),
    message: `You don’t have permission to run that query. ${CONTACT_ADMIN}`,
    userFixable: false
  },
  // Trigger: any other error class that describes the user's own SQL — a type mismatch, an
  // unknown function, a bad cast. User-fixable, and the Details beneath say how. Ahead of the
  // syntax rule, which reads any `line N:M` as a syntax error and so called a type mismatch one;
  // without either, these fell to the generic sentence, reserved for what a user cannot act on. ──
  {
    match: (m) => {
      const errorClass = userSqlErrorClass(m);
      return errorClass !== undefined && errorClass !== 'SYNTAX_ERROR';
    },
    message: 'Athena couldn’t run this query. Check the SQL and try again.',
    userFixable: true
  },
  // Trigger: a missing DATABASE reported without an error class in front of it — Athena's DDL
  // path words it `SemanticException [Error 10072]: Database does not exist: nodb`. Below the
  // user-SQL rule, so `SCHEMA_NOT_FOUND` keeps the Details that name the schema, and above the
  // syntax catch-all, which would otherwise be the only thing left to match it — and does not,
  // so without this rule a missing database is answered by the sentence reserved for what a user
  // cannot act on. ──
  {
    match: (m) => /(schema|database)\b[^.]{0,80}?(does not exist|not found)/i.test(m),
    message: 'That database wasn’t found. Check the name, and that it is one you can reach.',
    userFixable: true
  },
  // Trigger: a SQL parse/analysis error. User-fixable — fix the SQL. ──
  {
    match: (m) => /(syntax_error|mismatched input|line \d+:\d+|parse error)/i.test(m),
    message: 'There’s a syntax error in your query. Check the SQL and try again.',
    userFixable: true
  }
];

/**
 * Athena's own words for a failed query, when they are safe and useful to show, else undefined.
 *
 * The CLOSED list of classes is the boundary: each one's message echoes only what the user typed
 * or a value their query produced, never an engine locator. A second check fails closed on what a
 * message could still carry beyond its class — Athena appends causes — and runs on the full text
 * before the length cap, so a path past the cap still refuses.
 *
 * @param engineText - The execution's `stateChangeReason`, as the API relayed it.
 * @returns The text, cut to {@link DETAIL_MAX_CHARS}, or undefined.
 */
function queryFailureDetail(engineText: string): string | undefined {
  const text = engineText.trim();
  if (!isUserSqlError(text) || ENGINE_LOCATOR.test(text)) return undefined;
  if (PERMISSION_FAILURE.test(text.replace(COLUMN_NOT_FOUND_AUTHZ_CLAUSE, ''))) return undefined;
  return text.length > DETAIL_MAX_CHARS ? `${text.slice(0, DETAIL_MAX_CHARS)}…` : text;
}

/** Pull `{name, message, code}` out of a thrown value or a `ServiceResult` error. */
function normalize(error: MappableError): {
  name?: string;
  message?: string;
  code?: string;
  params?: RuleParams;
} {
  if (error && typeof error === 'object') {
    const e = error as {name?: string; message?: string; code?: string; params?: RuleParams};
    return {name: e.name, message: e.message, code: e.code, params: e.params};
  }
  return {message: typeof error === 'string' ? error : undefined};
}

/**
 * Log the original error to the console in dev builds only, tagged so it's
 * greppable. Guarded by `import.meta.env.DEV` at the call boundary so it
 * tree-shakes out of the production bundle (docs/process/ci-and-deploy-traps.md). Production logs
 * nothing and never exposes the original error.
 */
function logOriginal(code: string | undefined, original: {name?: string; message?: string}): void {
  if (import.meta.env.DEV) {
    console.warn(
      `[errorMessages] ${code ?? original.name ?? 'unknown'}:`,
      original.message ?? original.name ?? original
    );
  }
}

/**
 * Map any error to friendly, user-safe text. Resolution order:
 *   1. known app `code` (or AWS/Cognito `name`, which services store as `code`)
 *   2. known Athena engine-message pattern
 *   3. generic "Something went wrong. Contact the Administrator." fallback.
 *
 * The `message` never carries raw AWS/Athena text: the only path that echoes a
 * service message is a `passthrough` app code, whose message our own service
 * layer authored as user-safe. Athena's text travels separately, as `detail`,
 * and only for a `FAILED` execution whose error is in the user's own SQL. Logs
 * the original to the console in dev only.
 */
export function toUserMessage(error: MappableError): UserFacingMessage {
  const {name, message, code, params} = normalize(error);
  const key = code ?? name;
  logOriginal(key, {name, message});

  if (key) {
    const rule = CODE_INDEX.get(key);
    if (rule) return fromRule(rule, message, params);
  }

  if (message) {
    for (const rule of MATCH_RULES) {
      if (!rule.match?.(message)) continue;
      const detail = code === 'FAILED' ? queryFailureDetail(message) : undefined;
      return detail === undefined ? fromRule(rule, message) : {...fromRule(rule, message), detail};
    }
  }

  return GENERIC;
}

/**
 * The user-safe SENTENCE for an error — `toUserText(...)`, which is what
 * 40+ call sites actually wanted.
 *
 * Also accepts the `{code?, message?}` pair directly, so the six sites that had been
 * rebuilding an error object by hand (`toUserMessage({code: e.code, message: e.message})`)
 * can pass their parts. `toUserMessage` stays for the one consumer that wants the
 * `title` too — `ErrorBanner`.
 *
 * @example
 * setError(toUserText(result.error));
 * setError(toUserText({code: outcome.code, message: outcome.message}));
 */
export function toUserText(error: MappableError): string {
  return toUserMessage(error).message;
}

/**
 * Report a fire-and-forget failure the user is deliberately NOT being told about.
 *
 * For the background writes whose failure must not interrupt what the user is doing —
 * appending to query history, saving a query — where the choice is between an
 * interruption nobody asked for and a silence nobody can debug. This is the third
 * option: one consistent tag, and dev-only, on the same discipline as `logOriginal`
 * (production never prints, so a user's console never carries our internals).
 *
 * @param scope - The subsystem, e.g. `'query-history'`. Becomes `[scope]` in the log.
 * @param error - The caught value; logged as-is for a developer, never rendered.
 *
 * @example
 * void history.appendEntry(entry).catch((e) => logBackgroundFailure('query-history', e));
 */
export function logBackgroundFailure(scope: string, error: unknown): void {
  if (import.meta.env.DEV) console.warn(`[${scope}] background operation failed:`, error);
}

function fromRule(rule: ErrorRule, serviceMessage: string | undefined, params?: RuleParams): UserFacingMessage {
  // Passthrough: the service authored user-safe text (possibly parameterized).
  // Guard against an empty/absent message so we still never surface nothing.
  if (rule.passthrough) {
    return {title: rule.title, message: serviceMessage?.trim() || GENERIC.message};
  }
  // The typed values the API sent, where the rule knows what to do with them. Never the API's own
  // prose — that stays operator text nobody renders.
  if (rule.withParams && params?.limit !== undefined) {
    return {title: rule.title, message: rule.withParams(params)};
  }
  return {title: rule.title, message: rule.message ?? GENERIC.message};
}
