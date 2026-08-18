import {useState} from 'react';
import {cx} from '../../lib/cx';
import {Button} from '../../components/Button';
import {DatabaseRowIcon} from '../../components/icons';
import {useSchema} from '../catalog/useSchema';
import {spaceDatabase} from './exploreSources';
import type {ExploreTarget} from './exploreSources';
import type {QuerySpace} from '../catalog/catalog.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

export type SourcePickerProps = {
  /** Spaces to offer, ALREADY filtered by the caller's `sharedWorkspaces` gate. */
  spaces: readonly QuerySpace[];
  username: string;
  onChoose: (target: ExploreTarget) => void;
  /** Offered only when there is somewhere to go back to — i.e. a tab is already open. */
  onCancel?: () => void;
};

/**
 * Pick what to explore: a space on the left, its tables and views on the right (FR-005).
 *
 * **There is no database step**, and its absence is a decision rather than an omission: a
 * space maps to exactly one Glue database here (see `spaceDatabase`), so a database control
 * would offer one option — the one-option control the gating rule declines to render for the share
 * dialog's recipient kind. The database is shown, beside the space it belongs to.
 *
 * Views are offered alongside tables. A view is a perfectly good thing to explore and the
 * renderer does not care which it is reading.
 *
 * @example
 * <SourcePicker spaces={spaces} username="alice" onChoose={openTab} />
 */
export function SourcePicker({spaces, username, onChoose, onCancel}: SourcePickerProps) {
  const [selectedId, setSelectedId] = useState(spaces[0]?.id ?? '');
  const selected = spaces.find((s) => s.id === selectedId) ?? spaces[0];
  const database = selected ? spaceDatabase(selected, username) : null;
  const {data, isPending, isError} = useSchema(database);

  // FR-005 AC6: no usable space is a state that explains itself. Rendering an empty picker
  // would leave a user clicking at nothing with no idea whose fault it is.
  if (spaces.length === 0) {
    return (
      <section
        aria-label="Choose a table to explore"
        className="mx-auto flex max-w-lg flex-col gap-3 p-8 text-center">
        <h2 className="text-lg font-semibold text-text">Nothing to explore yet</h2>
        <p className="text-sm leading-relaxed text-text-2">
          The Data Explorer reads tables from your own space and from shared spaces you are a member of. Sign in, or ask
          an administrator to add you to a space, and its tables will appear here.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Choose a table to explore"
      className="flex min-h-0 flex-1 flex-col tablet:flex-row">
      <div className="flex flex-none flex-col gap-1 border-b border-border p-3 tablet:w-64 tablet:border-b-0 tablet:border-r">
        <h2 className={`px-2 pb-1 ${SECTION_CAPTION}`}>Space</h2>
        {spaces.map((space) => (
          <button
            key={space.id}
            type="button"
            aria-pressed={space.id === selected?.id}
            onClick={() => setSelectedId(space.id)}
            className={cx(
              'flex items-center gap-2 rounded-md px-2 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              space.id === selected?.id ? 'bg-surface-2 font-medium text-text' : 'text-text-2 hover:bg-surface-2'
            )}>
            <DatabaseRowIcon />
            <span className="min-w-0 flex-1 truncate">{space.label}</span>
            <span className="flex-none font-mono text-xs text-text-3">{spaceDatabase(space, username)}</span>
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col p-3">
        <div className="flex items-center gap-3 px-2 pb-2">
          <h2 className={SECTION_CAPTION}>Tables and views</h2>
          {onCancel && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
        {isPending && (
          <p
            role="status"
            className="px-2 py-2 text-sm text-text-3">
            Loading tables&hellip;
          </p>
        )}
        {isError && (
          <p
            role="status"
            className="px-2 py-2 text-sm leading-relaxed text-text-3">
            This space&rsquo;s tables aren&rsquo;t available right now. Try another space, or contact an administrator.
          </p>
        )}
        {data && data.tables.length === 0 && <p className="px-2 py-2 text-sm text-text-3">No tables or views yet.</p>}
        {data && data.tables.length > 0 && (
          <ul className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            {data.tables.map((table) => (
              <li key={table.name}>
                <button
                  type="button"
                  onClick={() => onChoose({spaceId: selected.id, database: database as string, table: table.name})}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-text hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                  <span className="min-w-0 flex-1 truncate">{table.name}</span>
                  {table.tableType === 'VIRTUAL_VIEW' && (
                    <span className="flex-none rounded border border-border px-1.5 py-0.5 text-xs text-text-3">
                      View
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
