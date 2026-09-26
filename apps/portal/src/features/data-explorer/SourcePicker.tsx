import {useEffect, useRef, useState} from 'react';
import {cx} from '../../lib/cx';
import {Button} from '../../components/Button';
import {DatabaseRowIcon} from '../../components/icons';
import {useSchema} from '../catalog/useSchema';
import {partitionSchema} from '../catalog/schema.partition';
import type {PartitionedSchema} from '../catalog/schema.partition';
import {spaceDatabase} from './exploreSources';
import type {ExploreTarget} from './exploreSources';
import type {QuerySpace} from '../catalog/catalog.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

/**
 * The two groups the object list is split into, in the one order they are ever offered.
 * Tables first: a view is derived from them, so it reads as the second thing.
 */
const SOURCE_GROUPS: readonly {key: keyof PartitionedSchema; heading: string}[] = [
  {key: 'tables', heading: 'Tables'},
  {key: 'views', heading: 'Views'}
];

export type SourcePickerProps = {
  /** Spaces to offer, ALREADY filtered by the caller's `sharedWorkspaces` gate. */
  spaces: readonly QuerySpace[];
  username: string;
  onChoose: (target: ExploreTarget) => void;
  /** Offered only when there is somewhere to go back to — i.e. a tab is already open. */
  onCancel?: () => void;
  /** Opens the list of saved queries to reopen as a view. Absent where the store is off. */
  onOpenSaved?: () => void;
  /**
   * Takes focus as it mounts: set when the picker replaces the control that held it — the last
   * tab, closed from the keyboard — so focus does not fall back to the top of the page.
   */
  takeFocus?: boolean;
};

/**
 * Pick what to explore: a space on the left, its tables and views on the right.
 *
 * **There is no database step**, and its absence is a decision rather than an omission: a
 * space maps to exactly one Glue database here (see `spaceDatabase`), so a database control
 * would offer one option — the one-option control the gating rule declines to render for the share
 * dialog's recipient kind. Every space's label is its database name, the personal space's
 * included, so the one name on each row is the one a query types.
 *
 * Views are offered alongside tables. A view is a perfectly good thing to explore and the
 * renderer does not care which it is reading.
 *
 * The picker only picks. Building a table is done from the Files screen, where the folder in
 * view is the answer to the question a folder chooser would otherwise have to ask.
 *
 * @example
 * <SourcePicker spaces={spaces} username="alice" onChoose={openTab} />
 */
export function SourcePicker({
  spaces,
  username,
  onChoose,
  onCancel,
  onOpenSaved,
  takeFocus = false
}: SourcePickerProps) {
  const sectionRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (takeFocus) sectionRef.current?.focus();
  }, [takeFocus]);
  const [selectedId, setSelectedId] = useState(spaces[0]?.id ?? '');
  const selected = spaces.find((s) => s.id === selectedId) ?? spaces[0];
  const database = selected ? spaceDatabase(selected, username) : null;
  const {data, isPending, isError} = useSchema(database);
  const partitioned = partitionSchema(data?.tables ?? []);

  // no usable space is a state that explains itself. Rendering an empty picker
  // would leave a user clicking at nothing with no idea whose fault it is.
  if (spaces.length === 0) {
    return (
      <section
        ref={sectionRef}
        tabIndex={-1}
        aria-label="Choose a table to explore"
        className="mx-auto flex max-w-lg flex-col gap-3 p-8 text-center focus:outline-none">
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
      ref={sectionRef}
      tabIndex={-1}
      aria-label="Choose a table to explore"
      className="flex min-h-0 flex-1 flex-col focus:outline-none tablet:flex-row">
      <div className="flex flex-none flex-col gap-1 border-b border-border p-3 tablet:min-h-0 tablet:w-64 tablet:overflow-y-auto tablet:border-b-0 tablet:border-r">
        <h2 className={`px-2 pb-1 ${SECTION_CAPTION}`}>Space</h2>
        {/* ONE name per row, and it is the database: every space's label is its database
            name now, the personal one included, so the row reads as the name a query types.
            Showing a label beside its database printed "My files alice", which testers
            reported as a doubled name. */}
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
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col p-3">
        {/* No title over the list. "Tables and views" restated what the two headings below
            already say, and it took the prominence they needed: the group a name is in is the
            thing a reader is actually scanning for. Rendered only for its buttons, so the list
            starts at the top of the column when there is nothing to put there. */}
        {(onCancel || onOpenSaved) && (
          <div className="flex items-center justify-end gap-2 px-2 pb-2">
            {onOpenSaved && (
              <Button
                variant="default"
                size="sm"
                onClick={onOpenSaved}>
                Open saved view
              </Button>
            )}
            {onCancel && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onCancel}>
                Cancel
              </Button>
            )}
          </div>
        )}
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
        {data && data.tables.length === 0 && (
          // No how-to here. The control that builds a table follows the `query` flag and this
          // component can no longer see it, so any sentence naming that control is one the flag
          // can falsify — pointing a user at a button the same flag has just hidden. The Tables
          // help section carries the instructions and is registered under that flag.
          <p className="px-2 py-2 text-sm text-text-3">No tables or views yet.</p>
        )}
        {data && data.tables.length > 0 && (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            {/* Grouped rather than one interleaved list: Glue returns tables and views in one
                order, and a view answers a question someone else already framed, so which of
                the two a name is changes what you expect from it. A section with no members
                is omitted, not rendered empty — an always-present "Views (0)" is a heading
                that never says anything. */}
            {SOURCE_GROUPS.map(({key, heading}) => {
              const members = partitioned[key];
              if (members.length === 0) return null;
              return (
                // The gap between one group and the next belongs on the SECTION, not the
                // heading: each heading is the first child of its own section, so `first:`
                // on the heading matches in every group and separates none of them.
                <section
                  key={key}
                  className="pt-4 first:pt-0">
                  <h2 className="px-2 pb-1 text-base font-semibold text-text">
                    {heading} ({members.length})
                  </h2>
                  <ul className="flex flex-col">
                    {members.map((table) => (
                      <li key={table.name}>
                        <button
                          type="button"
                          onClick={() =>
                            onChoose({spaceId: selected.id, database: database as string, table: table.name})
                          }
                          className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-text hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent">
                          <span className="min-w-0 flex-1 truncate">{table.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
