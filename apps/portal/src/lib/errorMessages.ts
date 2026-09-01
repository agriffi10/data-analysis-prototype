// The single source of truth for user-facing error wording.
//
// Every error a user can see (toast, banner, inline) is routed through
// `toUserMessage`. Raw AWS / Cognito / Athena text is NEVER shown to a user:
// the mapper resolves a friendly message from a stable app `code`, a known AWS
// error `name`, or an Athena engine-message pattern, and otherwise returns a
// generic "Contact the Administrator." fallback. The original error is logged to
// the console in dev builds only (see `logOriginal`) so developers can still
// debug — it never reaches the DOM or a production console.

/** What a surface renders: an optional bold title + one short sentence. */
export type UserFacingMessage = {
  title?: string;
  message: string;
};

/** Accepts a thrown value or a `ServiceResult` error object `{message, code}`. */
type MappableError = unknown;

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
// is ordered because several patterns can match one Athena message.

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

  // Trigger: a folder copy, move or delete reached the browser — the file-operations flag is off,
  // or the chosen destination resolved to no known space. The browser has no recursive primitive
  // any more: an operation whose cost grows with object count belongs on the plane and nowhere
  // else, so the flag switches the capability off rather than falling back to a slow copy of it.
  // NOT passthrough: the services raise it per item and the sentence is the same one every time.
  {
    code: 'PlaneRequired',
    message: 'Folders are handled by the file operations service, which is unavailable right now. Try again later.',
    userFixable: false
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
    message: `The portal could not resolve where this space is stored. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  {
    code: 'RuntimeConfigUnavailable',
    title: 'The portal could not start',
    message: `The portal is not configured correctly. ${CONTACT_ADMIN}`,
    userFixable: false
  },

  // Trigger: a send whose selection exceeds the file-send plane's caps, refused by
  // the producer before it reaches SQS. Passthrough for the same reason as the rule above —
  // the sentence is authored by our own service layer and embeds no AWS text. It is genuinely
  // user-fixable, and it has to say so: the alternative to refusing here is a request too
  // large for StartExecution, which dead-letters and reaches the user minutes later as a
  // failure notification for something they could have fixed by selecting less.
  {code: 'SelectionTooLarge', userFixable: true, passthrough: true},

  // Trigger: a saved query's `.sql` file is gone — deleted from the file browser, or by a
  // colleague in a shared space, between the listing and the open. Passthrough because the
  // sentence NAMES the file, which the generic `NotFound` cannot: a user looking at a list of
  // twenty-five queries needs to know which one vanished, not that "that item" did.
  {code: 'SavedQueryNotFound', userFixable: true, passthrough: true},

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

  // Trigger: the temporary AWS credentials / ID token expired mid-session.
  // User-fixable — sign in again to re-mint them. ──
  // Trigger: no Identity Pool credentials / ID token — the user isn't signed in
  // (or the session lapsed). User-fixable — sign in. ──
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

  // Trigger: the request body exceeded the gateway's limit. Distinct from `TooLarge` above,
  // which is our upload path naming the file and the limit; this is the transport's, and it
  // carries neither.
  {
    code: 'PayloadTooLarge',
    message: 'That request was too large. Try again with less selected.',
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
// is no app code, so we match the raw engine text. Ordered by specificity: the
// unqualified-table case is checked before generic not-found, which is checked
// before the syntax catch-all.

const UNQUALIFIED_FIX = 'Add a database to each table, like `mydb.sales`.';

/** True when Athena reported a missing table referenced WITHOUT a `database.` prefix. */
function isUnqualifiedTable(msg: string): boolean {
  // Queries carry no active database, so an unqualified `FROM sales`
  // fails as "Table <name> does not exist" / "Schema/Database does not exist".
  const m = msg.match(/table\s+(\S+?)\s+(?:does not exist|not found)/i);
  if (m && !m[1].includes('.')) return true; // bare table name → they omitted the db
  return /(schema|database)\b.*does not exist/i.test(msg);
}

const MATCH_RULES: readonly ErrorRule[] = [
  // Trigger: an unqualified base table (there is no active database).
  // User-fixable — qualify each table as `database.table`. ──
  {
    match: isUnqualifiedTable,
    message: UNQUALIFIED_FIX,
    userFixable: true
  },
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
  // Trigger: Athena/Lake-Formation permission failure running the query. Not the
  // user's to fix. ──
  {
    match: (m) => /(access denied|not authorized|insufficient (lake formation )?permissions)/i.test(m),
    message: `You don’t have permission to run that query. ${CONTACT_ADMIN}`,
    userFixable: false
  },
  // Trigger: a SQL parse/analysis error. User-fixable — fix the SQL. ──
  {
    match: (m) => /(syntax_error|mismatched input|line \d+:\d+|parse error)/i.test(m),
    message: 'There’s a syntax error in your query. Check the SQL and try again.',
    userFixable: true
  }
];

/** Pull `{name, message, code}` out of a thrown value or a `ServiceResult` error. */
function normalize(error: MappableError): {name?: string; message?: string; code?: string} {
  if (error && typeof error === 'object') {
    const e = error as {name?: string; message?: string; code?: string};
    return {name: e.name, message: e.message, code: e.code};
  }
  return {message: typeof error === 'string' ? error : undefined};
}

/**
 * Log the original error to the console in dev builds only, tagged so it's
 * greppable. Guarded by `import.meta.env.DEV` at the call boundary so it
 * tree-shakes out of the production bundle (process.md §6). Production logs
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
 * Never returns raw AWS/Athena text: the only path that echoes a service
 * message is a `passthrough` app code, whose message our own service layer
 * authored as user-safe. Logs the original to the console in dev only.
 */
export function toUserMessage(error: MappableError): UserFacingMessage {
  const {name, message, code} = normalize(error);
  const key = code ?? name;
  logOriginal(key, {name, message});

  if (key) {
    const rule = CODE_INDEX.get(key);
    if (rule) return fromRule(rule, message);
  }

  if (message) {
    for (const rule of MATCH_RULES) {
      if (rule.match?.(message)) return fromRule(rule, message);
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

function fromRule(rule: ErrorRule, serviceMessage: string | undefined): UserFacingMessage {
  // Passthrough: the service authored user-safe text (possibly parameterized).
  // Guard against an empty/absent message so we still never surface nothing.
  if (rule.passthrough) {
    return {title: rule.title, message: serviceMessage?.trim() || GENERIC.message};
  }
  return {title: rule.title, message: rule.message ?? GENERIC.message};
}
