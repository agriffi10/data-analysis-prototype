import {describe, it, expect} from 'vitest';

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
// The narrower guarantee that buys: this checks that each AUTHORED failure
// literal names a `code`, or delegates to an adapter that sets one
// (`toServiceError` / auth's local `toError`, both of which assign `code:
// e.name`). It cannot prove the code is non-empty at RUNTIME — an AWS error with
// no `name` still yields `code: undefined` through those adapters. Closing that
// would mean giving the adapters a fallback code, which is a behaviour change and
// not this FR's subject.

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

/** Every authored `{success: false, …}` literal in `source`, as source text. */
function failureLiterals(source: string): string[] {
  const literals: string[] = [];
  const re = /success:\s*false/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source)) !== null) {
    const open = source.lastIndexOf('{', match.index);
    if (open === -1) continue;
    literals.push(objectLiteralAt(source, open));
  }
  return literals;
}

/** Adapters that build the error object and assign `code` themselves. */
const DELEGATES = /error:\s*(toServiceError|toError)\(/;

const findings = Object.entries(MODULES)
  .filter(([path]) => isSubject(path))
  .flatMap(([path, source]) =>
    failureLiterals(source)
      // `code?:` matches the TYPE-position form (a return annotation naming the
      // field); a value literal can only ever write `code:`, so accepting both
      // weakens nothing and stops the adapters' own signatures reading as findings.
      .filter((literal) => !/\bcode\??:/.test(literal) && !DELEGATES.test(literal))
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
