// SPEC-106 — the single source of truth for user-facing error wording.
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
  // ── App codes our file-browser/query services already author (SPEC-106
  // FR-002). Trigger: a service returned this code with user-safe, often
  // parameterized text (filename / size / validation reason). User-fixable —
  // the wording tells them what to change. Passed through unchanged. ──
  {code: 'Collision', userFixable: true, passthrough: true}, // dest name already exists (carries the name)
  {code: 'ProtectedObject', userFixable: false, passthrough: true}, // storage marker can't be deleted/moved
  {code: 'InvalidName', userFixable: true, passthrough: true}, // folder-name validation reason
  {code: 'InvalidDestination', userFixable: true, passthrough: true}, // e.g. folder into itself
  {code: 'TooLarge', userFixable: true, passthrough: true}, // upload exceeds the max size (carries the limit)

  // ── Data-quality report reads (SPEC-113 FR-005). Deliberately NOT folded into
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

// ── Athena engine-message patterns (SPEC-106 FR-004/005). ───────────────────
// Query failures surface as {code: 'FAILED', message: stateChangeReason}; there
// is no app code, so we match the raw engine text. Ordered by specificity: the
// unqualified-table case is checked before generic not-found, which is checked
// before the syntax catch-all.

const UNQUALIFIED_FIX = 'Add a database to each table, like `mydb.sales`.';

/** True when Athena reported a missing table referenced WITHOUT a `database.` prefix. */
function isUnqualifiedTable(msg: string): boolean {
  // SPEC-077: queries carry no active database, so an unqualified `FROM sales`
  // fails as "Table <name> does not exist" / "Schema/Database does not exist".
  const m = msg.match(/table\s+(\S+?)\s+(?:does not exist|not found)/i);
  if (m && !m[1].includes('.')) return true; // bare table name → they omitted the db
  return /(schema|database)\b.*does not exist/i.test(msg);
}

const MATCH_RULES: readonly ErrorRule[] = [
  // Trigger: unqualified base table under SPEC-077 (no active database).
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

function fromRule(rule: ErrorRule, serviceMessage: string | undefined): UserFacingMessage {
  // Passthrough: the service authored user-safe text (possibly parameterized).
  // Guard against an empty/absent message so we still never surface nothing.
  if (rule.passthrough) {
    return {title: rule.title, message: serviceMessage?.trim() || GENERIC.message};
  }
  return {title: rule.title, message: rule.message ?? GENERIC.message};
}
