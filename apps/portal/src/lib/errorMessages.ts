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
  {code: 'InvalidDestination', userFixable: true, passthrough: true}, // e.g. folder into itself
  {code: 'TooLarge', userFixable: true, passthrough: true}, // upload exceeds the max size (carries the limit)

  // Trigger: a control plane's queue URL is unset in the runtime configuration, so
  // `enqueueFifo` refused before reaching SQS. Passthrough for exactly the reason the `ErrorRule` doc states —
  // the six "… is not configured" strings are authored by our own service layer
  // and embed no AWS text, they just name which control plane is missing. Not
  // user-fixable (it is a deploy misconfiguration), but the wording has to reach
  // the user: without this rule all six fell through to GENERIC, and the
  // documented deploy gotcha presented as "Something went wrong."
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

  // ── AWS / Cognito error names (services default `code` to the AWS `name`). ──
  // Trigger: scoped credentials denied the S3/Athena/Glue call. Almost always a
  // config/permission issue the user can't fix. ──
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

  {code: 'ExpiredToken', message: 'Your session expired. Sign in again.', userFixable: true},
  {code: 'ExpiredTokenException', message: 'Your session expired. Sign in again.', userFixable: true},
  {code: 'CredentialsProviderError', message: 'Your session expired. Sign in again.', userFixable: true},
  {code: 'NotAuthorizedException', message: 'Your session expired. Sign in again.', userFixable: true}, // Cognito refresh

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
  // Trigger: results were read before the execution finished — Athena's
  // INVALID_QUERY_EXECUTION_STATE, "Query has not yet finished. Current state: QUEUED".
  // Transient and OURS, not the user's: a caller asked for results too early. The gate in
  // `ExplorationResultsRegion` is the real fix; this rule exists so that if one ever slips
  // through again it reads as "still running" instead of the generic
  // "Contact the Administrator", which is what a first load showed until 2026-08-15.
  //
  // Matched on the MESSAGE, deliberately. `InvalidRequestException` is the AWS name for a
  // rejected `StartQueryExecution` — for a MALFORMED_QUERY as much as for this — and a
  // `code` rule wins over every rule here, so keying on the name would have turned a
  // rejected-at-submit syntax error into "still running". (An execution that reaches FAILED
  // arrives as `code: 'FAILED'` and was never at risk.)
  //
  // Two alternatives, not three: `current state: <x>` was dropped after review. It added no
  // coverage — the real message is already caught by the second — and it was the one able to
  // match an unrelated error quoting a user's own value back, e.g.
  // `Cannot cast VARCHAR 'current state: queued' to INTEGER`. ──
  {
    match: (m) => /(invalid_query_execution_state|query has not yet finished)/i.test(m),
    message: 'The query is still running. Give it a moment and try again.',
    userFixable: true
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
