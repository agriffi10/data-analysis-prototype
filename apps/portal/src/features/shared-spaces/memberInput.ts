import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';

// Parse a single-or-bulk member input (comma / whitespace / newline separated)
// into a clean, de-duplicated, lowercased username list. Tokens that don't match
// the catalog-safe username rule (SPEC-033) are dropped client-side — but the
// pipeline is the final authority (it validates each name against the User Pool
// and silently ignores unknowns, SPEC-053 FR-002).
export function parseMemberInput(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const token of raw.split(/[\s,]+/)) {
    const name = token.trim().toLowerCase();
    if (!name || seen.has(name) || !CATALOG_IDENTIFIER_RE.test(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}
