export const URL_PLACEHOLDER = '${value}';

export const URL_TEMPLATE_REFUSAL = `The link needs ${URL_PLACEHOLDER} somewhere in it, for the cell’s value.`;
export const URL_NOT_A_URL = 'That cell doesn’t make a web address.';
export const URL_NOT_HTTPS = 'Only https links are opened from a cell.';

/** What a template resolved to: a link, or a reason there is not one. */
export type ResolvedUrl = {href: string; reason?: undefined} | {href?: undefined; reason: string};

// The one place in this spec where being wrong is a security bug rather
// than an ugly grid: the TEMPLATE is authored by the user, but the value substituted into
// it comes from the table — so a link's destination is partly attacker-controlled wherever
// the data is.
//
// **`isSafeInAppPath` is deliberately not used here, and this is the note recording why.**
// That rule governs IN-APP paths: it asks whether a notification's link is a
// route inside this application, and it answers by refusing anything that is not root-
// relative. Every URL in this file is by definition external and absolute, so that rule
// would reject all of them — and if it were loosened to admit them it would be answering a
// question it was never written for. Reaching for a rule that sounds adjacent is how a
// confident category error ships.

/**
 * Whether a template can be used at all, or null when it can.
 *
 * Checked at ENTRY, so a template with no placeholder is refused where the user can fix it
 * rather than rendering the same static link on every row.
 *
 * @param template - The user's template.
 * @returns The refusal, or null.
 */
export function templateRefusal(template: string): string | null {
  return template.includes(URL_PLACEHOLDER) ? null : URL_TEMPLATE_REFUSAL;
}

/**
 * The link a template and a cell value make, or the reason there is none.
 *
 * Three things happen here in this order, and the order is the requirement:
 *
 * 1. The value is **percent-encoded for the position it lands in** — and the position
 *    genuinely varies, which the first implementation missed. Inside a path or a query
 *    (`https://host/${value}`) it is encoded, so it cannot climb out of its segment, add a
 *    parameter or graft a fragment on. At the very START of the template (`${value}`, the
 *    natural template for a column that already holds links) the value IS the URL, so
 *    encoding it would turn every legitimate `https://…` into `https%3A%2F%2F…` — not a
 *    URL, and that column could never link at all. There it is substituted raw and left to
 *    the two steps below, which is exactly the case FR-006 AC2 describes.
 * 2. The **resolved** URL is parsed, never the template. A template of `${value}` with a
 *    cell holding `javascript:alert(1)` is the case that matters, and a template-only check
 *    passes it happily.
 * 3. Only `https:` survives. Everything else — `javascript:`, `data:`, `vbscript:`,
 *    `file:`, and every scheme nobody has thought of — is a refusal with a reason, rendered
 *    as plain text. An allowlist rather than a blocklist, because the blocklist is the one
 *    that has to be complete.
 *
 * @param template - The user's template, containing `${value}`.
 * @param value - The raw cell value.
 * @returns The href, or the reason there is not one.
 */
export function resolveUrl(template: string, value: string): ResolvedUrl {
  const refusal = templateRefusal(template);
  if (refusal) return {reason: refusal};

  let url: URL;
  try {
    // Assembled part by part rather than with `String.replace`: the replacement string in
    // `replace` reads `$&`, `$'` and `` $` `` as substitution patterns, so a cell value
    // containing one would be expanded into something other than itself before it was ever
    // parsed. It also lets the leading position — where the value supplies the URL — be
    // substituted raw while every later one is encoded.
    //
    // Inside the `try`, because `encodeURIComponent` throws `URIError` on a lone surrogate
    // and a cell holding one would otherwise throw straight through the grid's render.
    const parts = template.split(URL_PLACEHOLDER);
    let resolved = parts[0];
    for (let at = 1; at < parts.length; at += 1) {
      const suppliesTheUrl = at === 1 && parts[0] === '';
      resolved += (suppliesTheUrl ? value : encodeURIComponent(value)) + parts[at];
    }
    url = new URL(resolved);
  } catch {
    // A relative or malformed template — `/reports/${value}`, say. Not a link, and not
    // this feature's job to guess a base for it.
    return {reason: URL_NOT_A_URL};
  }
  if (url.protocol !== 'https:') return {reason: URL_NOT_HTTPS};
  return {href: url.toString()};
}
