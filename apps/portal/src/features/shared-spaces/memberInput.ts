import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';

/**
 * Parse single-or-bulk member input (comma / whitespace / newline separated) into a
 * de-duplicated, lowercased username list. Tokens failing the catalog-safe username
 * rule are dropped client-side, but the pipeline is the final authority — it validates
 * each name against the User Pool.
 *
 * An unknown name is NOT silently ignored there: `add_members.py` notifies the space
 * OWNER by name, and table-share reports unresolved recipients. This docstring said
 * otherwise and had been wrong since the notification landed (corrected under SPEC-146).
 * The real cost is that the report is late, asynchronous and owner-only.
 */
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
