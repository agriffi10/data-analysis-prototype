import {useId, useState} from 'react';
import {Banner} from '../../components/Banner';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import type {TableRefreshTarget} from './tableRefresh.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

type Props = {
  target: TableRefreshTarget;
  /** In-flight enqueue — locks the dialog and shows progress on the confirm button. */
  busy?: boolean;
  /** An enqueue failure to surface inline (the dialog stays open so the user can retry). */
  submitError?: string | null;
  onConfirm: (allowRemovals: boolean) => void;
  onCancel: () => void;
};

/**
 * The "Refresh table" confirmation. It explains what a refresh does and
 * does not do — the dialog cannot *predict* the outcome, because there is no
 * synchronous inference path — and carries the removals opt-in.
 *
 * The opt-in is always present and always unchecked: a user who knows a column is
 * going away should not have to trigger a refusal to be offered the option. When the
 * dialog was opened from SPEC-144's `columns_removed` notification link it
 * additionally names the columns that link carried, and confirm stays disabled until
 * the box is ticked — arriving here means a removal is already pending, so
 * proceeding without acknowledging it is not a meaningful action.
 */
export function RefreshTableDialog({target, busy = false, submitError, onConfirm, onCancel}: Props) {
  const [allowRemovals, setAllowRemovals] = useState(false);
  const checkboxId = useId();
  const consequenceId = useId();
  const {database, table, pending} = target;
  const qualified = `${database}.${table.name}`;

  return (
    <ConfirmDialog
      title={`Refresh “${table.name}”?`}
      ariaLabel={`Confirm refresh table ${qualified}`}
      confirmLabel="Refresh table"
      busyLabel="Starting…"
      busy={busy}
      confirmDisabled={!!pending && !allowRemovals}
      // SPEC-186 FR-002. The banner above already explains the situation, but the CONTROL said
      // nothing — a natively-disabled button with no title, skipped by the tab order.
      confirmDisabledReason="Tick “Allow columns to be removed” to refresh this table."
      onConfirm={() => onConfirm(allowRemovals)}
      onCancel={onCancel}>
      <p className="mt-3 text-sm leading-relaxed text-text-2">
        This re-reads the files in the table&rsquo;s folder and updates its columns to match what&rsquo;s there now.
      </p>

      <dl className="mt-3 space-y-1.5 rounded-md border border-border bg-surface-2 px-2.5 py-2 text-sm">
        <div className="flex flex-col gap-0.5 tablet:flex-row tablet:gap-2">
          <dt className={`flex-none ${SECTION_CAPTION} tablet:w-16 tablet:pt-0.5`}>Table</dt>
          <dd className="min-w-0 break-all font-mono text-text">{qualified}</dd>
        </div>
        <div className="flex flex-col gap-0.5 tablet:flex-row tablet:gap-2">
          <dt className={`flex-none ${SECTION_CAPTION} tablet:w-16 tablet:pt-0.5`}>Folder</dt>
          <dd className="min-w-0 break-all font-mono text-text-2">{table.location}</dd>
        </div>
      </dl>

      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-relaxed text-text-2">
        <li>Your files are not modified — only the table&rsquo;s list of columns changes.</li>
        <li>Partition keys are not changed. To change those, create the table again.</li>
        {/* SPEC-149 replaced 144's drop-and-recreate with one in-place UpdateTable, so
            there is no window in which the table does not exist. */}
        <li>The table stays queryable throughout — its definition is replaced in one step.</li>
        <li>The result arrives as a notification, not here.</li>
      </ul>

      {pending && (
        <div className="mt-4 rounded-lg border border-warning-soft bg-warning-soft p-3">
          <p className="text-sm font-medium text-warning">A previous refresh was stopped</p>
          <p className="mt-1 text-sm leading-relaxed text-text-2">
            These columns are no longer in the files, so refreshing would remove them from the table:
          </p>
          <ul
            aria-label="Columns that would be removed"
            className="mt-2 max-h-32 overflow-y-auto rounded-md bg-surface px-2.5 py-1.5">
            {/* Keyed by position: a hand-edited URL can repeat a name, and the list
                is display-only. */}
            {pending.columns.map((column, i) => (
              <li
                key={`${i}-${column}`}
                className="break-all py-0.5 font-mono text-sm text-text">
                {column}
              </li>
            ))}
          </ul>
        </div>
      )}

      <label
        htmlFor={checkboxId}
        className="mt-4 flex w-full cursor-pointer items-start gap-2.5 rounded-md py-2 text-sm text-text hover:bg-surface-2">
        <input
          id={checkboxId}
          type="checkbox"
          checked={allowRemovals}
          disabled={busy}
          aria-describedby={consequenceId}
          onChange={(e) => setAllowRemovals(e.target.checked)}
          className="mt-0.5 h-4 w-4 flex-none accent-accent"
        />
        <span className="min-w-0">
          <span className="font-medium">Allow columns to be removed</span>
          <span
            id={consequenceId}
            className="mt-0.5 block leading-relaxed text-text-2">
            A column that is missing from the files is dropped from the table. Any saved query or view that references
            it will stop working.
          </span>
        </span>
      </label>

      {submitError && (
        <Banner
          variant="danger"
          className="mt-4"
          role="alert">
          {submitError}
        </Banner>
      )}
    </ConfirmDialog>
  );
}
