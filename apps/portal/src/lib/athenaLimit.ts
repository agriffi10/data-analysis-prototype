/**
 * The longest statement `StartQueryExecution` accepts.
 *
 * Athena's own documented bound on `QueryString`. It is the REAL limit on how many values
 * a list filter can carry — `EXPLORER_FILTER_VALUES_MAX` bounds the count, and a thousand
 * long values exceed this where a thousand short ones do not. It lives in `lib/` because a
 * saved query's view line is measured against it as well as a rendered statement.
 */
export const ATHENA_QUERY_STRING_MAX = 262_144;

/**
 * Whether a statement is too long for Athena to be asked to run it.
 *
 * Counted in UTF-8 BYTES. The API reference does not say whether its bound is characters
 * or bytes, and a string's byte count is never below its character count — so a statement
 * this admits is under the limit in either unit, where counting characters would admit one
 * that is over it in bytes.
 *
 * @param sql - The statement.
 * @returns True when it must not be started.
 */
export function exceedsAthenaQueryLimit(sql: string): boolean {
  return new TextEncoder().encode(sql).length > ATHENA_QUERY_STRING_MAX;
}
