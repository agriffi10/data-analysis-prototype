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
    expect(flagged(`return {\n  success: false,\n  // no code: internal\n  error: {message: 'nope'}\n};`)).toHaveLength(
      1
    );
  });

  it('is NOT fooled by a `code:` inside a message string', () => {
    expect(flagged('return {success: false, error: {message: `Athena returned code: ${x}`}};')).toHaveLength(1);
  });

  it('still matches when the colon is spaced', () => {
    expect(flagged(`return {success : false, error: {message: 'nope'}};`)).toHaveLength(1);
  });
});
