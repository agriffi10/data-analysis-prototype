import {CATALOG_IDENTIFIER_RE} from '../../lib/catalogIdentifier';

/**
 * Parse single-or-bulk member input (comma / whitespace / newline separated) into a
 * de-duplicated, lowercased username list. Tokens failing the catalog-safe username
 * rule are dropped client-side, but the pipeline is the final authority — it validates
 * each name against the User Pool.
 *
 * An unknown name is NOT silently ignored there: `add_members.py` notifies the space
 * OWNER by name, and table-share reports unresolved recipients. This docstring said
 * otherwise and had been wrong since the notification landed.
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

/**
 * {@link parseMemberInput}, but it REPORTS what it rejected instead of dropping it.
 *
 * Same splitting, lowercasing and de-duplication; the difference is that tokens failing the
 * catalog-safe rule come back in `invalid` rather than vanishing. `UsernameChipsField` puts
 * them back in the input with the rule sentence, so a user pasting a mixed list watches the
 * good names become chips and keeps the bad ones to fix — rather than watching half their
 * paste disappear without comment.
 *
 * Added beside `parseMemberInput` rather than replacing it. Since the suggestion source moved
 * `TableShareDialog`'s space entry onto the same combobox, this is the parser every FIELD uses;
 * `parseMemberInput` remains the domain's plain parse of a bulk string, pinned by its own tests
 * and still the baseline these two are checked to agree on.
 *
 * @param raw - Comma / whitespace / newline separated input.
 * @returns `valid` in input order, de-duplicated; `invalid` in input order, as typed.
 *
 * @example
 * // Note `Smith!` and not `Smith`: a bare `Smith` lowercases to the perfectly valid `smith`.
 * parseMemberInputDetailed('bob, Bob Smith!') // {valid: ['bob'], invalid: ['Smith!']}
 */
export function parseMemberInputDetailed(raw: string): {valid: string[]; invalid: string[]} {
  const seen = new Set<string>();
  const valid: string[] = [];
  const invalid: string[] = [];
  for (const token of raw.split(/[\s,]+/)) {
    const trimmed = token.trim();
    if (!trimmed) continue;
    const name = trimmed.toLowerCase();
    if (!CATALOG_IDENTIFIER_RE.test(name)) {
      // Reported AS TYPED, not lowercased: the user has to recognise what they pasted in
      // order to fix it, and `Bob Smith` lowercased to `bob smith` is a different string
      // from the one on their clipboard.
      invalid.push(trimmed);
      continue;
    }
    if (seen.has(name)) continue;
    seen.add(name);
    valid.push(name);
  }
  return {valid, invalid};
}
