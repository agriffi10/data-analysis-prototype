import {afterEach, describe, expect, it, vi} from 'vitest';
import {logBackgroundFailure, toUserMessage, toUserText} from './errorMessages';
import {toServiceError, unwrap} from './serviceResult';

// ─── from errorMessages.test.ts ───
describe('errorMessages', () => {
  const RAW_AWS = 'AccessDenied: User: arn:aws:sts::123:assumed-role/portal is not authorized to perform s3:GetObject';

  describe('toUserMessage', () => {
    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllEnvs();
    });

    it('names the bound the API refused a field against', () => {
      // The API knows which limit it enforced and now sends it. A static sentence threw that
      // away and told the user to "try again with less selected" — false for the case this
      // refusal is now mostly about, one field over its own bound with nothing selected at all.
      const {message} = toUserMessage({code: 'PayloadTooLarge', params: {limit: 1024}});

      expect(message).toContain('1,024');
      expect(message).not.toContain('less selected');
    });

    it('still answers a PayloadTooLarge that carries no limit', () => {
      // API Gateway's own 413 is produced above the router and carries no envelope, so the
      // static sentence is not dead code — and it must not read as though a number went missing.
      const {message} = toUserMessage({code: 'PayloadTooLarge'});

      expect(message).toBe('That request was too large. Try again with less in it.');
      expect(message).not.toContain('undefined');
    });

    it('answers a document too large to READ without asking the reader to send less', () => {
      // The person opening their history sent nothing, so "make it smaller" is advice nobody can
      // follow. The documents the app writes for itself are an administrator's to fix.
      const {message} = toUserMessage({code: 'DocumentTooLarge', message: 'Failed to load history'});

      expect(message).toBe('This is too large to open. Contact the Administrator.');
    });

    it('sends a saved query too large to read to Files, where a download does not pass the bound', () => {
      const {message} = toUserMessage({code: 'SavedQueryTooLarge', message: '“q” is too large to open.'});

      expect(message).toBe(
        'This saved query is too large to open here. Download it from its space’s saved_queries folder in Files to read it.'
      );
    });

    it('passes a recognized app code through with its authored message', () => {
      const {message} = toUserMessage({code: 'Collision', message: '"reports/q4.csv" already exists.'});
      expect(message).toBe('"reports/q4.csv" already exists.');
    });

    it('answers an identity the API could not assume without blaming the user (SPEC-196 FR-007)', () => {
      // The three AWS-side conditions must stay tellable apart in the WORDING, not just in the
      // status. Signing in again cannot fix this one and neither can asking for access, so it
      // must read as neither. The raw text names a role ARN and an account id, and none of it
      // travels: this code is deliberately not `passthrough`.
      const {message} = toUserMessage({code: 'IdentityUnavailable', message: RAW_AWS});
      expect(message).toBe('Something went wrong on our side. Contact the Administrator.');
      expect(message).not.toContain('arn:aws');
      expect(message).not.toContain('123');

      expect(message).not.toBe(toUserMessage({code: 'SessionExpired'}).message);
      expect(message).not.toBe(toUserMessage({code: 'AccessDenied', message: RAW_AWS}).message);
      expect(toUserMessage({code: 'SessionExpired'}).message).not.toBe(
        toUserMessage({code: 'AccessDenied', message: RAW_AWS}).message
      );
    });

    it('maps a recognized AWS error name to friendly non-fixable text, ignoring the raw message', () => {
      const {message} = toUserMessage({code: 'AccessDenied', message: RAW_AWS});
      expect(message).toBe("You don't have permission to do that. Contact the Administrator.");
      expect(message).not.toContain('arn:aws');
    });

    it('answers a missing table without asserting the user forgot a database (FR-005)', () => {
      // FR-005's advice — qualify each table — is now carried only by the catalog refusal that
      // actually means it. A rule here used to offer it for any bare table token, which Athena
      // produces for tables that ARE qualified: `Table nope not found in database agriffith`
      // puts the database in a clause of its own, so the token has no dot and the user who wrote
      // `agriffith.nope` was told to add a prefix.
      expect(toUserMessage({code: 'FAILED', message: 'line 1:15: Table sales does not exist'}).message).toMatch(
        /table wasn’t found/i
      );
      expect(
        toUserMessage({code: 'FAILED', message: 'Table nope_xyz not found in database agriffith'}).message
      ).not.toBe('Add a database to each table, like `mydb.sales`.');
    });

    // Captured from production Athena on 2026-09-15 by running each statement as `agriffith` and
    // reading `stateChangeReason` off `GET /v1/queries/{id}`. Pasted verbatim, trailing space
    // included: these are the bytes the rules are graded against, and a hand-written
    // approximation is what let the unqualified-table rule above sit dead behind a green test.
    const DENIED_ON = (database: string) =>
      `Insufficient permissions to execute the query. User: arn:aws:sts::696000197480:assumed-role/dat-portal-user-role/agriffith is not authorized to perform: glue:GetDatabase on resource: arn:aws:glue:us-east-1:696000197480:database/${database} because no identity-based policy allows the glue:GetDatabase action `;

    it('tells a user who omitted the database prefix to add one, not to contact an admin', () => {
      // A statement naming no database resolves against `default`, which nobody is a member of, so
      // Athena refuses it at the catalog with the same wording as a real permissions failure — and
      // the user, who simply typed `FROM sales`, was told they lacked permission.
      const {message} = toUserMessage({code: 'FAILED', message: DENIED_ON('default')});

      expect(message).toBe('Add a database to each table, like `mydb.sales`.');
    });

    it('tells a user who named an unreachable database something else entirely', () => {
      // The counter-case, and the reason the rule reads the database NAME rather than merely
      // classifying the message: the two arrive identical apart from it, and "add a database
      // prefix" is wrong advice for someone who already wrote one. Compared against the other
      // rule's own output, so the pair stays discriminating while either sentence is reworded.
      const denied = toUserMessage({code: 'FAILED', message: DENIED_ON('nodb_xyz')}).message;

      expect(denied).not.toBe(toUserMessage({code: 'FAILED', message: DENIED_ON('default')}).message);
      expect(denied).toMatch(/isn’t available to you/i);
    });

    it('does not tell a user to check a name they never typed', () => {
      // The Data Explorer builds its own SQL from a table picked out of the rail, and maps the
      // failed execution through this module — so this rule is reached by people who typed no
      // database name at all. The access half has to lead, and the name check has to be
      // conditional, or the sentence sends them hunting for a typo that cannot exist.
      const {message} = toUserMessage({code: 'FAILED', message: DENIED_ON('marketing')});

      const lower = message.toLowerCase();

      expect(lower).toContain('ask the administrator for access');
      expect(lower.indexOf('ask the administrator for access')).toBeLessThan(lower.indexOf('if you typed it'));
    });

    it('reads the database of the denied action, not the first one in the message', () => {
      // A message carrying two denials. A name grabbed by a separate search takes whichever
      // `:database/` comes first, which may belong to another action — and picks the opposite
      // sentence for it.
      const twoDenials =
        'User: arn:aws:sts::696000197480:assumed-role/r/u is not authorized to perform: glue:GetTable on resource: arn:aws:glue:us-east-1:696000197480:database/default because no identity-based policy allows; ' +
        'User: arn:aws:sts::696000197480:assumed-role/r/u is not authorized to perform: glue:GetDatabase on resource: arn:aws:glue:us-east-1:696000197480:database/salesdb because no identity-based policy allows';

      const {message} = toUserMessage({code: 'FAILED', message: twoDenials});

      expect(message).toMatch(/isn’t available to you/i);
      expect(message).not.toBe('Add a database to each table, like `mydb.sales`.');
    });

    it('does not read a LONGER name as the implicit one', () => {
      // The comparison is exact, so a capture that stops early makes it a prefix test: bounding
      // the name to `[A-Za-z0-9_]` stopped at the hyphen and answered `default-archive` as though
      // the user had named no database at all. A hyphen is legal in a Glue database name; it is
      // this project's own identifier rule, not Glue's, that keeps portal-made names clear of one.
      const {message} = toUserMessage({code: 'FAILED', message: DENIED_ON('default-archive')});

      expect(message).toMatch(/isn’t available to you/i);
      expect(message).not.toBe('Add a database to each table, like `mydb.sales`.');
    });

    it.each([['.'], [')'], ['"']])('is not inverted by a %s after the database name', (punctuation) => {
      // The name is compared exactly, so any character absorbed into it flips the two sentences.
      // One period after `default` used to be enough to tell someone who wrote no database at all
      // to go and check the name.
      const message = DENIED_ON(`default${punctuation}`);

      expect(toUserMessage({code: 'FAILED', message}).message).toBe('Add a database to each table, like `mydb.sales`.');
    });

    it('sends a missing SCHEMA to the user-SQL rule, so Athena names the schema itself', () => {
      // `isUnqualifiedTable` used to match any "schema … does not exist", which outranks the
      // catalog-refusal pair — so a user who HAD qualified their table was told to add a prefix.
      //
      // The SENTENCE is asserted, not merely that it is not the old one: `detail` is attached by
      // `queryFailureDetail` whatever rule fired, so a `detail` assertion alone stays green with
      // this rule disabled and the message reading "there's a syntax error in your query".
      const {message, detail} = toUserMessage({
        code: 'FAILED',
        message: "SCHEMA_NOT_FOUND: line 1:15: Schema 'awsdatacatalog.nodb' does not exist"
      });

      expect(message).toBe('Athena couldn’t run this query. Check the SQL and try again.');
      expect(detail).toContain("Schema 'awsdatacatalog.nodb' does not exist");
    });

    it('shows no Details for a message that reaches the permission check carrying LF text', () => {
      // The existing "no Details for a Lake Formation refusal" case exits at the FIRST gate —
      // an unprefixed message is not a user-SQL error — so it stays green with the permission
      // check deleted and proves nothing about it. This one opens with an allowlisted class and
      // carries no ARN, account id or `Service:`, so it passes both earlier gates and the
      // permission check is the only thing standing between Athena's text and the reader.
      const composite =
        'COLUMN_NOT_FOUND: line 1:8: Column x cannot be resolved. Insufficient Lake Formation permission(s) on teamspace.revenue';

      expect(toUserMessage({code: 'FAILED', message: composite}).detail).toBeUndefined();
    });

    it('still shows Details for an ordinary missing column, whose text always carries an authz clause', () => {
      // The counter-case, and the reason the check strips that clause first: Athena appends
      // "or requester is not authorized…" to EVERY COLUMN_NOT_FOUND, so testing the raw text
      // would suppress Details for every missing column — the case the disclosure exists for.
      const {detail} = toUserMessage({
        code: 'FAILED',
        message:
          "COLUMN_NOT_FOUND: line 1:8: Column 'nope' cannot be resolved or requester is not authorized to access requested resources"
      });

      expect(detail).toContain("Column 'nope' cannot be resolved");
    });

    it('keeps the permission sentence for a Lake Formation denial, which writes "permission(s)"', () => {
      // The plural spelling matched nothing against Lake Formation's own wording — pinned on the
      // other side of the wire by `test_catalog_routes.py` — so a real denial, which IS an
      // administrator's to fix, fell past its own rule to the generic sentence.
      const {message} = toUserMessage({
        code: 'FAILED',
        message: 'Insufficient Lake Formation permission(s): Required SELECT on table x'
      });

      expect(message).toBe('You don’t have permission to run that query. Contact the Administrator.');
    });

    it('treats a qualified missing table as a not-found error, not the unqualified fix', () => {
      const {message} = toUserMessage({
        code: 'FAILED',
        message: 'line 1:15: Table mydb.sales does not exist'
      });
      expect(message).toContain('table wasn’t found');
      expect(message).not.toContain('Add a database');
    });

    it('maps an Athena column-resolution failure', () => {
      expect(
        toUserMessage({code: 'FAILED', message: "SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved"}).message
      ).toContain('column');
    });

    it('maps a results-read-too-early to "still running", not the generic fallback', () => {
      // GetQueryResults against a QUEUED execution. Until 2026-08-15 this reached a user, on an
      // ordinary first load of the Data Explorer, as "Something went wrong. Contact the
      // Administrator." — the app's most alarming sentence, for a transient race of our own.
      //
      // It arrives as a CODE now. The rule that read the engine's text is gone with the path that
      // produced it: the browser no longer calls Athena, so nothing can hand this mapper a raw
      // `InvalidRequestException` again. That rule could never have been a code rule, because the
      // AWS name means two different things and `code` outranks every message rule — the API
      // resolves the ambiguity at the one layer that holds the message.
      const {message} = toUserMessage({code: 'QueryNotFinished'});

      expect(message).toBe('The query is still running. Give it a moment and try again.');
      expect(message).not.toMatch(/Contact the Administrator/i);
    });

    it('gives a rejected statement the SAME sentence as a failed one, never the generic', () => {
      // Athena rejects some statements at submit and accepts others that then fail — the user
      // typed the same mistake either way, so they must read the same sentence. Compared against
      // the match rule's own output rather than a literal: a third copy of a sentence is a third
      // thing to keep in step, and it agrees with itself while the wording moves.
      const viaFailedExecution = toUserMessage({
        code: 'FAILED',
        message: 'SYNTAX_ERROR: line 1:8: mismatched input FROM'
      });

      expect(toUserMessage({code: 'QuerySyntaxError'}).message).toBe(viaFailedExecution.message);
      expect(toUserMessage({code: 'QuerySyntaxError'}).message).not.toMatch(/Contact the Administrator/i);
    });

    it('still reads a syntax error out of a FAILED execution reason', () => {
      // The match rule that survives the port, and the path that keeps it alive: most syntax
      // errors are not rejected at submit at all — Athena accepts the query, the execution
      // reaches FAILED, and the reason travels on a 200 for this rule to read. The submit-time
      // half now arrives as `QuerySyntaxError`, asserted above to say the very same sentence.
      expect(
        toUserMessage({
          code: 'FAILED',
          message: "line 3:36: mismatched input '>'. Expecting: ')', ','"
        }).message
      ).toBe('There’s a syntax error in your query. Check the SQL and try again.');
    });

    it('returns the generic fallback for an unrecognized error and never echoes the raw message', () => {
      const raw = "TypeError: Cannot read properties of undefined (reading 'bucket')";
      const {message} = toUserMessage({code: 'KaboomException', message: raw});
      expect(message).toBe('Something went wrong. Contact the Administrator.');
      expect(message).not.toContain('undefined');
      expect(message).not.toContain('KaboomException');
    });

    it('tells the user a settings write was refused AND that nothing was lost', () => {
      // Reached when the document could not be read AND could not be copied aside,
      // so the write was refused rather than overwriting it. It must say "nothing
      // was changed" — a bare "Something went wrong" would leave the user assuming
      // the opposite of what happened. SPEC-173 retired the saved-queries store, so
      // query history is the one `user_settings/` document left on this path.
      const {message} = toUserMessage({
        code: 'QueryHistoryQuarantineFailed',
        message: 'Unexpected token } in JSON at position 4'
      });
      expect(message).toContain('nothing was changed');
      expect(message).not.toBe('Something went wrong. Contact the Administrator.');
      // Never the raw parser text.
      expect(message).not.toContain('JSON');
    });

    it('sends a NEWER settings document to the one fix that works — reload, not the administrator', () => {
      // The refusal here is deliberate and the document is fine: a newer tab wrote
      // it. "Contact the Administrator" would be false advice, and quarantining it
      // would be the downgrade the refusal exists to prevent (SPEC-159 FR-001).
      const {message} = toUserMessage({code: 'QueryHistoryNewerVersion', message: 'version 2 is not readable'});
      expect(message).toMatch(/reload/i);
      expect(message).not.toContain('Contact the Administrator');
      expect(message).not.toBe('Something went wrong. Contact the Administrator.');
    });

    it('names the saved query that vanished, rather than saying “that item” (SPEC-173)', () => {
      // A user looking at a list of twenty-five queries needs to know WHICH one is
      // gone, which is why this is its own passthrough code and not generic NotFound.
      expect(toUserMessage({code: 'SavedQueryNotFound', message: '“Q1 revenue” no longer exists.'}).message).toBe(
        '“Q1 revenue” no longer exists.'
      );
      // The retired store's three codes are gone with it — nothing maps them any more.
      for (const code of ['SavedQueriesRecovered', 'SavedQueriesNewerVersion', 'SavedQueriesQuarantineFailed']) {
        expect(toUserMessage({code}).message).toBe('Something went wrong. Contact the Administrator.');
      }
    });

    it('preserves service-authored "missed information" text via passthrough codes (FR-005)', () => {
      // InvalidName carries the folder-name validation reason; TooLarge carries the size.
      expect(toUserMessage({code: 'InvalidName', message: 'Folder names cannot contain “/”.'}).message).toBe(
        'Folder names cannot contain “/”.'
      );
      expect(
        toUserMessage({code: 'TooLarge', message: 'File exceeds the maximum upload size of 100 bytes.'}).message
      ).toBe('File exceeds the maximum upload size of 100 bytes.');
    });

    it('maps a not-signed-in credential failure to a sign-in prompt', () => {
      expect(toUserMessage({code: 'NotAuthenticated', message: 'No AWS credentials — sign in required'}).message).toBe(
        'Sign in to continue.'
      );
    });

    it('accepts a thrown Error (name-based) as well as a ServiceResult error', () => {
      const err = Object.assign(new Error('Network request failed'), {name: 'NetworkError'});
      expect(toUserMessage(err).message).toContain('Check your connection');
    });

    it('does not log and returns mapped text with no raw message in a production build (FR-006)', () => {
      vi.stubEnv('DEV', false);
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const {message} = toUserMessage({code: 'AccessDenied', message: RAW_AWS});
      expect(warn).not.toHaveBeenCalled();
      expect(message).not.toContain('arn:aws');
      expect(message).toBe("You don't have permission to do that. Contact the Administrator.");
    });
  });

  describe('a failed query’s own message, shown as Details', () => {
    const failed = (message: string) => toUserMessage({code: 'FAILED', message});

    it.each([
      [
        'a class no sentence names',
        'TYPE_MISMATCH: line 1:28: Cannot apply operator: varchar = integer',
        'Athena couldn’t run this query. Check the SQL and try again.'
      ],
      [
        'a missing column, whose generic authorisation clause is not a permission failure',
        "COLUMN_NOT_FOUND: line 1:8: Column 'amont' cannot be resolved or requester is not authorized to access requested resources",
        'A column in your query wasn’t found. Check the column names.'
      ],
      [
        'a parse error with no class in front',
        "line 3:36: mismatched input '>'. Expecting: ')', ','",
        'There’s a syntax error in your query. Check the SQL and try again.'
      ]
    ])('keeps the sentence friendly and carries the engine text for %s', (_case, engineText, sentence) => {
      const shown = failed(engineText);

      expect(shown.message).toBe(sentence);
      expect(shown.detail).toBe(engineText);
    });

    it.each([
      ['a Lake Formation refusal', 'Insufficient Lake Formation permission(s) on mydb.sales'],
      ['a split error naming an S3 object', 'HIVE_CANNOT_OPEN_SPLIT: Error opening Hive split s3://bucket/alice/a.csv'],
      ['an allowed class carrying an S3 path', 'TYPE_MISMATCH: line 1:1: Cannot read s3://bucket/alice/a.csv'],
      ['an allowed class carrying an account number', 'TYPE_MISMATCH: line 1:1: role in 123456789012 cannot cast'],
      ['an allowed class carrying an ARN', 'SYNTAX_ERROR: line 1:1: arn:aws:glue:us-east-1:table/x'],
      [
        'an allowed class carrying a service cause',
        'SYNTAX_ERROR: line 1:1: failed (Service: AmazonS3; Status Code: 403)'
      ],
      ['an allowed class carrying a request id', 'SYNTAX_ERROR: line 1:1: failed (Request ID: 7F3A)'],
      ['an allowed class with a permission failure', 'SYNTAX_ERROR: line 1:1: Access Denied'],
      ['an allowed class only mid-string', 'Query aborted after SYNTAX_ERROR: line 1:1: x'],
      ['a parse position only mid-string', 'HIVE_BAD_DATA: bad value at line 4:2: x'],
      ['the connectors’ catch-all class', 'NOT_SUPPORTED: line 1:1: unsupported thing']
    ])('shows no Details for %s', (_case, engineText) => {
      expect(failed(engineText).detail).toBeUndefined();
    });

    it('shows no Details for engine text that did not arrive as a FAILED execution', () => {
      const engineText = 'TYPE_MISMATCH: line 1:28: Cannot apply operator: varchar = integer';

      expect(toUserMessage({code: 'CANCELLED', message: engineText}).detail).toBeUndefined();
      expect(toUserMessage({message: engineText}).detail).toBeUndefined();
    });

    it('cuts a long message at the cap rather than hiding it, and judges the whole text first', () => {
      const expected = `SYNTAX_ERROR: line 1:8: mismatched input 'FORM'. Expecting: ${"'ALTER', ".repeat(80)}`;
      const withPathPastTheCap = `${expected}s3://bucket/alice/a.csv`;

      const detail = failed(expected).detail ?? '';

      expect(detail).toHaveLength(501);
      expect(detail.startsWith("SYNTAX_ERROR: line 1:8: mismatched input 'FORM'")).toBe(true);
      expect(detail.endsWith('…')).toBe(true);
      expect(failed(withPathPastTheCap).detail).toBeUndefined();
    });
  });

  describe('toUserText (SPEC-155 FR-008)', () => {
    it('is exactly toUserMessage(...).message', () => {
      // One delegation, no second rule table — the property that makes the 40-site
      // rename safe. Asserted across a coded rule, a match rule and the fallback.
      for (const error of [
        {code: 'AccessDenied', message: 'Access Denied'},
        {name: 'NoSuchKey', message: 'The specified key does not exist.'},
        {message: 'something nobody has a rule for'},
        'a bare string',
        null
      ]) {
        expect(toUserText(error)).toBe(toUserMessage(error).message);
      }
    });

    it('never returns the raw service text for a mapped code', () => {
      expect(toUserText({code: 'AccessDenied', message: 'Access Denied'})).not.toContain('Access Denied');
    });
  });

  describe('logBackgroundFailure (SPEC-155 FR-006)', () => {
    it('tags the scope in dev', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      vi.stubEnv('DEV', true);

      logBackgroundFailure('query-history', new Error('append failed'));

      expect(warn).toHaveBeenCalledOnce();
      expect(warn.mock.calls[0][0]).toContain('[query-history]');
      warn.mockRestore();
      vi.unstubAllEnvs();
    });

    it('says nothing in production — a user console never carries our internals', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      vi.stubEnv('DEV', false);

      logBackgroundFailure('query-history', new Error('append failed'));

      expect(warn).not.toHaveBeenCalled();
      warn.mockRestore();
      vi.unstubAllEnvs();
    });
  });
});

// ─── from serviceResult.test.ts ───
describe('serviceResult', () => {
  // The four values a `throw` can produce that are not objects. `toServiceError`
  // runs INSIDE a catch, in a function documented as never throwing, so a raised
  // TypeError here would replace the error being reported with a different one
  // (SPEC-150 FR-009).
  const NON_OBJECT_THROWS = [
    {label: 'null', value: null},
    {label: 'undefined', value: undefined},
    {label: 'a string', value: 'boom'},
    {label: 'a number', value: 42}
  ];

  describe('toServiceError', () => {
    it.each(NON_OBJECT_THROWS)('returns the fallback failure for $label, without throwing', ({value}) => {
      expect(() => toServiceError(value, 'Failed to list files')).not.toThrow();
      expect(toServiceError(value, 'Failed to list files')).toEqual({
        success: false,
        error: {message: 'Failed to list files', code: undefined}
      });
    });

    it('takes them from an AWS SDK error object too', () => {
      const awsErr = {
        name: 'NoSuchKey',
        message: 'The specified key does not exist.',
        $metadata: {httpStatusCode: 404}
      };

      expect(toServiceError(awsErr, 'Failed to read')).toEqual({
        success: false,
        error: {message: 'The specified key does not exist.', code: 'NoSuchKey'}
      });
    });
  });

  describe('unwrap', () => {
    it('returns the data on success', () => {
      expect(unwrap({success: true, data: ['a']})).toEqual(['a']);
    });
  });
});

// ─── from serviceErrorContract.test.ts ───
describe('serviceErrorContract', () => {
  // SPEC-150 FR-006 — the invariant the whole error-mapping design rests on.
  //
  // `toUserMessage` keys on `code ?? name`. A failure that carries neither falls
  // through every rule to GENERIC ("Something went wrong. Contact the
  // Administrator."), so an authored message is silently discarded and the user is
  // told nothing. That is not a hypothetical: it is exactly what FR-004 (six
  // unreachable "… is not configured" strings) and FR-005 (a lapsed session showing
  // the generic on every S3-backed screen) each turned out to be.
  //
  // ── What this test can and cannot guarantee ────────────────────────────────
  // Service functions cannot be enumerated and CALLED generically — each needs its
  // own AWS boundary mocked and its own arguments — so the subject list is derived
  // from SOURCE TEXT instead: every non-test module under `src/`, loaded eagerly as
  // raw strings by `import.meta.glob`. A new service file is therefore covered the
  // moment it exists, with no edit here, which is the enumerative property the FR
  // asks for.
  //
  // The narrower guarantee that buys, stated in full rather than gestured at —
  // overstating a guard's reach is the defect class this whole spec is about:
  //
  //  1. RUNTIME emptiness is not covered. `toServiceError` / auth's `toError` assign
  //     `code: e.name`, so an AWS error with no `name` still yields `code: undefined`.
  //     Closing that means giving the adapters a fallback code — a behaviour change,
  //     and not this FR's subject.
  //  2. A failure built by a helper OTHER than those two has no literal at the call
  //     site and is invisible here. `DELEGATES` is the allowlist of such helpers; a
  //     new one must be added to it, and adding one is a deliberate act.
  //  3. Comments and string bodies are blanked before scanning (see below), so a
  //     `code:` in either cannot fake compliance. That was a real hole: this codebase
  //     writes explanatory comments INSIDE the returned object.
  //
  // What it does cover is the case that actually bit twice: an authored literal that
  // simply forgot the field.

  const MODULES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
    string,
    string
  >;

  // Mirrors vite.config.ts's coverage `exclude`: tests, type declarations and the
  // test harness author no runtime failures.
  function isSubject(path: string): boolean {
    return !/\.test\.(ts|tsx)$|\.types\.ts$|\.d\.ts$|^\/src\/test\/|^\/src\/test-setup\.ts$/.test(path);
  }

  // Failures whose `code` is deliberately absent. Empty today — an entry needs a
  // one-line reason, and "not got round to it" is not one.
  const ALLOWLIST: {path: string; snippet: string; reason: string}[] = [];

  /** The `{ … }` beginning at `open`, found by brace counting. Ignores nothing clever — the source has no braces in strings at these sites. */
  function objectLiteralAt(source: string, open: number): string {
    let depth = 0;
    for (let i = open; i < source.length; i++) {
      if (source[i] === '{') depth++;
      else if (source[i] === '}') {
        depth--;
        if (depth === 0) return source.slice(open, i + 1);
      }
    }
    return source.slice(open);
  }

  /**
   * Comments and string bodies blanked, so a `code:` written in either cannot satisfy
   * the check below. This codebase habitually explains a failure in a comment INSIDE
   * the returned object (see `query.service.ts`), and `// no code: internal fault`
   * would otherwise read as a compliant literal — the scan would pass on exactly the
   * omission it exists to catch. Blanked rather than removed so offsets are preserved.
   */
  function blankCommentsAndStrings(source: string): string {
    return source
      .replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length))
      .replace(/\/\/[^\n]*/g, (m) => ' '.repeat(m.length))
      .replace(/'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g, (m) => ' '.repeat(m.length));
  }

  /** Every authored `{success: false, …}` literal in `source`, as source text. */
  function failureLiterals(source: string): string[] {
    const scrubbed = blankCommentsAndStrings(source);
    const literals: string[] = [];
    // `\s*` on BOTH sides of the colon: `success : false` is legal TypeScript, and a
    // scan that only Prettier keeps honest is not a guard.
    const re = /success\s*:\s*false/g;
    let match: RegExpExecArray | null;
    while ((match = re.exec(scrubbed)) !== null) {
      const open = scrubbed.lastIndexOf('{', match.index);
      if (open === -1) continue;
      literals.push(objectLiteralAt(scrubbed, open));
    }
    return literals;
  }

  /** Adapters that build the error object and assign `code` themselves. */
  const DELEGATES = /error:\s*(toServiceError|toError)\(/;

  const findings = Object.entries(MODULES)
    .filter(([path]) => isSubject(path))
    .flatMap(([path, source]) =>
      failureLiterals(source)
        // Anchored to a property POSITION — start, or after `{` / `,` / whitespace —
        // so an unrelated nested `details: {code: 500}` still counts (it is inside the
        // literal) but a bare `xcode:` does not. `code?:` is the TYPE-position form (a
        // return annotation naming the field); a value literal can only ever write
        // `code:`, so accepting both weakens nothing and stops the adapters' own
        // signatures reading as findings.
        //
        // `code,` and `code}` are the ES6 SHORTHAND forms, and they were a false
        // NEGATIVE of this scan rather than a loophole in it: `{message: '', code}`
        // names the code as plainly as `code: code` does, and was reported as an
        // omission. Left unfixed, the repair someone reaches for is the allowlist —
        // which would exempt a file wholesale from a rule it actually satisfies. Still
        // anchored to a property position, so `notcode,` does not match.
        .filter((literal) => !/(?:^|[{,\s])code\s*(?:\??:|[,}])/.test(literal) && !DELEGATES.test(literal))
        .map((literal) => ({path, literal: literal.replace(/\s+/g, ' ').slice(0, 120)}))
    )
    .filter(({path, literal}) => !ALLOWLIST.some((a) => a.path === path && literal.includes(a.snippet)));

  describe('every authored service failure carries an error code', () => {
    it('found source files to check (the glob is not silently empty)', () => {
      // Without this, a broken glob would make the invariant below vacuously true —
      // the "did not run is never clean" rule, applied to a test.
      const subjects = Object.keys(MODULES).filter(isSubject);
      expect(subjects.length).toBeGreaterThan(50);
      expect(subjects.some((p) => p.endsWith('/apiClient.ts'))).toBe(true);
    });

    it('finds authored failure literals to assert over', () => {
      const total = Object.entries(MODULES)
        .filter(([path]) => isSubject(path))
        .flatMap(([, source]) => failureLiterals(source)).length;
      expect(total).toBeGreaterThan(20);
    });

    it('no failure omits its code', () => {
      expect(findings).toEqual([]);
    });
  });

  // The scanner is the guard, so the scanner needs its own guard: a scan that quietly
  // stopped detecting anything would report a clean tree, which is this repo's
  // "did not run is never clean" rule pointed at a test.
  describe('the scan itself detects what it claims to', () => {
    const flagged = (source: string) =>
      failureLiterals(source).filter((l) => !/(?:^|[{,\s])code\s*\??:/.test(l) && !DELEGATES.test(l));

    it('accepts one that carries a code', () => {
      expect(flagged(`return {success: false, error: {message: 'nope', code: 'NotFound'}};`)).toHaveLength(0);
    });

    it('accepts a delegation to an adapter that sets the code', () => {
      expect(flagged(`return {success: false, error: toServiceError(err, 'nope')};`)).toHaveLength(0);
    });

    it('is NOT fooled by a `code:` inside a message string', () => {
      expect(flagged('return {success: false, error: {message: `Athena returned code: ${x}`}};')).toHaveLength(1);
    });

    it('still matches when the colon is spaced', () => {
      expect(flagged(`return {success : false, error: {message: 'nope'}};`)).toHaveLength(1);
    });
  });
});
