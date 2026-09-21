import {useState} from 'react';
import {Button} from '../../components/Button';
import {CopyButton} from '../../components/CopyButton';

export const NO_GENERATED_SQL = 'There’s no statement to show yet.';

export type GeneratedSqlDisclosureProps = {
  /**
   * The statement the exploration ran, from `useExploration` — **the string that was handed
   * to StartQueryExecution**, never a second rendering made for display.
   */
  sql: string | null;
  /**
   * Opens a copy of the statement in a new Query tab. Given only while the `query` flag is on,
   * since the Query workspace is a `query` surface; absent, the button is not rendered at all.
   */
  onOpenInQuery?: (sql: string) => void;
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
 * And is not something to keep on screen, so it costs a toolbar row only when open.
 *
 * `sql` is null in three states and the wording has to be true in all of them: nothing has
 * run yet, the description was REFUSED before it could render, and a history step is being
 * held back (the suspension). Two of those keep the previous rows on screen, so
 * "nothing has been run" would be read as a claim about them.
 * The statement sits in a read-only `<textarea>` (the `ValuePanel` precedent) so it stays
 * selectable with the platform's own shortcuts, with a copy button beside it for the whole
 * statement. The button sits in the body, never in the `<summary>`, where a click would also
 * toggle the disclosure and a control would be nested inside another — and it mounts only while
 * the disclosure is open, so its live region is not a second one on the page the rest of the time.
 *
 * **Open in Query** mounts under the same rule, beside it. The statement is never read back into
 * the exploration: editing happens in Query, on a copy, and this tab is left as it was.
 */
export function GeneratedSqlDisclosure({sql, onOpenInQuery}: GeneratedSqlDisclosureProps) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="flex-none rounded-lg border border-border bg-surface"
      onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-text-2">Generated SQL</summary>
      <div className="px-3 pb-3">
        {sql === null ? (
          <p className="text-sm italic text-text-3">{NO_GENERATED_SQL}</p>
        ) : (
          <div className="flex items-start gap-2">
            <textarea
              readOnly
              aria-label="Generated SQL"
              value={sql}
              rows={Math.min(sql.split('\n').length + 1, 12)}
              className="min-w-0 flex-1 resize-none overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs text-text"
            />
            {open && (
              <div className="flex flex-none flex-col items-end gap-1">
                <CopyButton
                  value={sql}
                  label="SQL"
                />
                {onOpenInQuery && (
                  <Button
                    size="sm"
                    onClick={() => onOpenInQuery(sql)}>
                    Open in Query
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
