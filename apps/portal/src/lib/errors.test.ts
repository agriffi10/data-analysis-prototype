import {afterEach, describe, expect, it, vi} from 'vitest';
import {logBackgroundFailure, toUserMessage, toUserText} from './errorMessages';
import {isNotFound} from './s3Errors';
import {toServiceError, unwrap} from './serviceResult';

// ─── from errorMessages.test.ts ───
describe('errorMessages', () => {
  const RAW_AWS = 'AccessDenied: User: arn:aws:sts::123:assumed-role/portal is not authorized to perform s3:GetObject';

  describe('toUserMessage', () => {
    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllEnvs();
    });

    it('passes a recognized app code through with its authored message', () => {
      const {message} = toUserMessage({code: 'Collision', message: '"reports/q4.csv" already exists.'});
      expect(message).toBe('"reports/q4.csv" already exists.');
    });

    it('maps a recognized AWS error name to friendly non-fixable text, ignoring the raw message', () => {
      const {message} = toUserMessage({code: 'AccessDenied', message: RAW_AWS});
      expect(message).toBe("You don't have permission to do that. Contact the Administrator.");
      expect(message).not.toContain('arn:aws');
    });

    it('maps an expired-credential code to a sign-in fix', () => {
      expect(toUserMessage({code: 'ExpiredToken', message: 'The provided token has expired.'}).message).toBe(
        'Your session expired. Sign in again.'
      );
    });

    it('maps an unqualified-table Athena failure to the add-database fix (FR-005)', () => {
      const {message} = toUserMessage({
        code: 'FAILED',
        message: 'line 1:15: Table sales does not exist'
      });
      expect(message).toBe('Add a database to each table, like `mydb.sales`.');
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

    it('maps an Athena syntax error', () => {
      expect(toUserMessage({code: 'FAILED', message: 'SYNTAX_ERROR: mismatched input'}).message).toContain(
        'syntax error'
      );
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
      // so the write was refused rather than overwriting it. Both must say "nothing
      // was changed" — a bare "Something went wrong" would leave the user assuming
      // the opposite of what happened.
      for (const code of ['SavedQueriesQuarantineFailed', 'QueryHistoryQuarantineFailed']) {
        const {message} = toUserMessage({code, message: 'Unexpected token } in JSON at position 4'});
        expect(message).toContain('nothing was changed');
        expect(message).not.toBe('Something went wrong. Contact the Administrator.');
        // Never the raw parser text.
        expect(message).not.toContain('JSON');
      }
    });

    it('sends a NEWER settings document to the one fix that works — reload, not the administrator', () => {
      // The refusal here is deliberate and the document is fine: a newer tab wrote
      // it. "Contact the Administrator" would be false advice, and quarantining it
      // would be the downgrade the refusal exists to prevent (SPEC-159 FR-001).
      for (const code of ['SavedQueriesNewerVersion', 'QueryHistoryNewerVersion']) {
        const {message} = toUserMessage({code, message: 'version 2 is not readable'});
        expect(message).toMatch(/reload/i);
        expect(message).not.toContain('Contact the Administrator');
        expect(message).not.toBe('Something went wrong. Contact the Administrator.');
      }
    });

    it('says what became of the data when a write RECOVERED from an unreadable document', () => {
      // The one outcome of the three that is a success, and the only channel the
      // user has for learning that the list in front of them is not the one they
      // had. Silence here reads as an ordinary save (SPEC-159 FR-004).
      const saved = toUserMessage({code: 'SavedQueriesRecovered'}).message;
      expect(saved).toMatch(/copy was kept/i);
      expect(saved).toMatch(/earlier saved queries aren’t in the list/i);
      expect(saved).not.toBe('Something went wrong. Contact the Administrator.');
      // Both saving and DELETING a query reach this message, so it may not claim a
      // save happened — on the delete path that would be a plain lie.
      expect(saved).not.toMatch(/this query was saved/i);

      const history = toUserMessage({code: 'QueryHistoryRecovered'}).message;
      expect(history).toMatch(/copy was kept/i);
      expect(history).not.toBe('Something went wrong. Contact the Administrator.');
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

    it('logs the original error to the console in a dev build', () => {
      vi.stubEnv('DEV', true);
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      toUserMessage({code: 'AccessDenied', message: RAW_AWS});
      expect(warn).toHaveBeenCalled();
      expect(warn.mock.calls[0].join(' ')).toContain('AccessDenied');
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

    it('accepts the {code, message} pair the six manual rebuilds used to construct', () => {
      expect(toUserText({code: 'AccessDenied', message: 'Access Denied'})).toBe(
        toUserMessage({code: 'AccessDenied', message: 'Access Denied'}).message
      );
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

// ─── from s3Errors.test.ts ───
describe('s3Errors', () => {
  describe('isNotFound', () => {
    it.each([
      {label: 'GetObject on a missing key', err: {name: 'NoSuchKey'}},
      {label: 'HeadObject on a missing key', err: {name: 'NotFound'}},
      {label: 'a 404 in $metadata', err: {name: 'SomethingElse', $metadata: {httpStatusCode: 404}}}
    ])('is true for $label', ({err}) => {
      expect(isNotFound(err)).toBe(true);
    });

    it.each([
      {label: 'a denial', err: {name: 'AccessDenied', $metadata: {httpStatusCode: 403}}},
      {label: 'an ordinary Error', err: new Error('network down')}
    ])('is false for $label', ({err}) => {
      expect(isNotFound(err)).toBe(false);
    });

    // A non-object throw must be answered, not re-thrown: this is a predicate a
    // catch block calls before deciding what the error means (SPEC-150 FR-009).
    it.each([
      {label: 'null', value: null},
      {label: 'undefined', value: undefined},
      {label: 'a string', value: 'NoSuchKey'},
      {label: 'a number', value: 404}
    ])('returns false for $label rather than throwing', ({value}) => {
      expect(() => isNotFound(value)).not.toThrow();
      expect(isNotFound(value)).toBe(false);
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

    it('takes message and code from a normal Error', () => {
      const err = Object.assign(new Error('Access Denied'), {name: 'AccessDenied'});

      expect(toServiceError(err, 'Failed to list files')).toEqual({
        success: false,
        error: {message: 'Access Denied', code: 'AccessDenied'}
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

    it('falls back when an object carries no message', () => {
      expect(toServiceError({name: 'Weird'}, 'Failed to read').error.message).toBe('Failed to read');
    });
  });

  describe('unwrap', () => {
    it('returns the data on success', () => {
      expect(unwrap({success: true, data: ['a']})).toEqual(['a']);
    });

    it('throws an Error carrying the message and code on failure', () => {
      expect(() => unwrap({success: false, error: {message: 'Sign in required', code: 'NotAuthenticated'}})).toThrow(
        'Sign in required'
      );

      try {
        unwrap({success: false, error: {message: 'Sign in required', code: 'NotAuthenticated'}});
      } catch (err) {
        expect((err as {code?: string}).code).toBe('NotAuthenticated');
      }
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
        .filter((literal) => !/(?:^|[{,\s])code\s*\??:/.test(literal) && !DELEGATES.test(literal))
        .map((literal) => ({path, literal: literal.replace(/\s+/g, ' ').slice(0, 120)}))
    )
    .filter(({path, literal}) => !ALLOWLIST.some((a) => a.path === path && literal.includes(a.snippet)));

  describe('every authored service failure carries an error code', () => {
    it('found source files to check (the glob is not silently empty)', () => {
      // Without this, a broken glob would make the invariant below vacuously true —
      // the "did not run is never clean" rule, applied to a test.
      const subjects = Object.keys(MODULES).filter(isSubject);
      expect(subjects.length).toBeGreaterThan(50);
      expect(subjects.some((p) => p.endsWith('/enqueueFifo.ts'))).toBe(true);
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

    it('flags a plain codeless failure', () => {
      expect(flagged(`return {success: false, error: {message: 'nope'}};`)).toHaveLength(1);
    });

    it('accepts one that carries a code', () => {
      expect(flagged(`return {success: false, error: {message: 'nope', code: 'NotFound'}};`)).toHaveLength(0);
    });

    it('accepts a delegation to an adapter that sets the code', () => {
      expect(flagged(`return {success: false, error: toServiceError(err, 'nope')};`)).toHaveLength(0);
    });

    it('is NOT fooled by a `code:` inside a comment', () => {
      expect(flagged(`return {success: false, /* no code: internal */ error: {message: 'nope'}};`)).toHaveLength(1);
      expect(
        flagged(`return {\n  success: false,\n  // no code: internal\n  error: {message: 'nope'}\n};`)
      ).toHaveLength(1);
    });

    it('is NOT fooled by a `code:` inside a message string', () => {
      expect(flagged('return {success: false, error: {message: `Athena returned code: ${x}`}};')).toHaveLength(1);
    });

    it('still matches when the colon is spaced', () => {
      expect(flagged(`return {success : false, error: {message: 'nope'}};`)).toHaveLength(1);
    });
  });
});
