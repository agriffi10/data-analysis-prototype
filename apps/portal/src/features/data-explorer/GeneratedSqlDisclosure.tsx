export const NO_GENERATED_SQL = 'There’s no statement to show yet.';

export type GeneratedSqlDisclosureProps = {
  /**
   * The statement the exploration ran, from `useExploration` — **the string that was handed
   * to StartQueryExecution**, never a second rendering made for display.
   */
  sql: string | null;
};

/**
 * The exploration's current SQL, on request.
 *
 * The Data Explorer writes SQL the user did not, and that SQL is an invoice — so it has to
 * be readable. What makes it trustworthy is where it comes from: `useExploration` renders
 * once, runs THAT string and returns it, and this shows the same value. Re-deriving it here
 * would be one `renderExplorationSql` call away and would drift the moment a caller passed
 * a slightly different description — a disclosure that is right most of the time is worse
 * than none, because it would be believed.
 *
 * A `<details>` rather than a panel: it is available whether or not grouping is active
 * (AC4) and is not something to keep on screen, so it costs a toolbar row only when open.
 *
 * `sql` is null in three states and the wording has to be true in all of them: nothing has
 * run yet, the description was REFUSED before it could render, and a history step is being
 * held back (SPEC-181's suspension). Two of those keep the previous rows on screen, so
 * "nothing has been run" would be read as a claim about them.
 * The statement sits in a read-only `<textarea>` (the `ValuePanel` precedent) so it is
 * selectable and copyable with the platform's own shortcuts — a copy CONTROL is SPEC-185's.
 */
export function GeneratedSqlDisclosure({sql}: GeneratedSqlDisclosureProps) {
  return (
    <details className="flex-none rounded-lg border border-border bg-surface">
      <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-text-2">Generated SQL</summary>
      <div className="px-3 pb-3">
        {sql === null ? (
          <p className="text-sm italic text-text-3">{NO_GENERATED_SQL}</p>
        ) : (
          <textarea
            readOnly
            aria-label="Generated SQL"
            value={sql}
            rows={Math.min(sql.split('\n').length + 1, 12)}
            className="w-full resize-none overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs text-text"
          />
        )}
      </div>
    </details>
  );
}
