import {useState, type RefObject} from 'react';
import {Button} from '../../components/Button';
import {IconButton} from '../../components/IconButton';
import {useEscapeKey} from '../../hooks/useEscapeKey';
import {emptyGrouping} from './exploration';
import {groupingApplyRefusal} from './explorationQueryOps';
import {aggregateAlias, groupingNameCollision} from './renderExplorationSql';
import type {AggregateFunction, ExplorationQuery, Grouping} from './dataExplorer.types';

/** The five functions, in the one order the picker offers them. Never assembled from text. */
const AGGREGATE_FUNCTIONS: AggregateFunction[] = ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX'];

/** `*` is the COUNT-only column, and the picker is where that rule is enforced for the user. */
const ALL_ROWS = '*';

const SELECT_CLASS =
  'h-9 rounded-md border border-border bg-surface px-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';

export const GROUPING_NO_COLUMNS = 'Drag a column header here, or add one below, to group by it.';

export type GroupingPanelProps = {
  /**
   * The SOURCE's columns — what may be grouped by or aggregated.
   *
   * Deliberately not the current result's: once a grouping is in force the result's
   * columns ARE the grouping columns and the aggregate aliases, so offering them would let
   * a user group by `count_all` — a column that exists only inside the query it would be
   * added to. The region resolves this; below `table` sources it is Glue's list.
   */
  columns: {name: string}[];
  /** The applied description: the draft's starting point, and what the refusal reads. */
  query: ExplorationQuery;
  /** The column a header drag is carrying, read at drop time — see the region for why it is a ref. */
  draggedColumnRef: RefObject<string | null>;
  onApply: (grouping: Grouping | null) => void;
  onClose: () => void;
};

/**
 * Grouping columns and aggregates, staged and applied as `GROUP BY` (SPEC-182 FR-003).
 *
 * The Calc panel beside it looks like a sibling and is the opposite of one: Calc computes
 * in the browser over cells that exist only there, where **this renders SQL and mints an
 * execution like any other query change**. Grouping in the browser would aggregate
 * whichever rows happened to be fetched, which is the scale lie the whole feature is
 * designed to avoid.
 *
 * So the panel STAGES: a draft grouping lives here until Apply, and Apply is one
 * `apply` — one execution, however many columns and aggregates changed (AC4). Cancel-by-
 * closing discards the draft whole, exactly as the settings dialog's does.
 *
 * It is a side panel rather than a `Drawer` for a reason that is not stylistic: a header
 * column is added **by dragging it here** (AC1), and a focus-trapping drawer would put the
 * grid out of reach. Escape closes it through the depth-ordered registry (SPEC-155).
 *
 * Column references reach the SQL through `sqlIdentifier` in the renderer and the function
 * is chosen from a closed list here — nothing in this panel is assembled from user text.
 */
export function GroupingPanel({columns, query, draggedColumnRef, onApply, onClose}: GroupingPanelProps) {
  useEscapeKey(onClose, true);
  const applied = query.grouping;
  const [draft, setDraft] = useState<Grouping>(applied ?? emptyGrouping());
  const [pendingFn, setPendingFn] = useState<AggregateFunction>('COUNT');
  const [pendingColumn, setPendingColumn] = useState<string>(ALL_ROWS);
  const [error, setError] = useState<string | null>(null);

  // Re-seeded during render when the APPLIED grouping changes underneath the panel, the
  // same way `ExpressionBar` re-seeds its text: a history step, Clear all or a second tab
  // rewrites the grouping without going through this draft, and a panel still showing the
  // grouping the user has just stepped away from would re-apply it on the next Apply.
  // Compared on the applied value's identity — an apply from THIS panel replaces the object
  // too, and re-seeding from it is a no-op because the two agree.
  const [previousApplied, setPreviousApplied] = useState(applied);
  if (previousApplied !== applied) {
    setPreviousApplied(applied);
    setDraft(applied ?? emptyGrouping());
    setError(null);
  }

  const names = columns.map((column) => column.name);
  const ungrouped = names.filter((name) => !draft.columns.includes(name));

  const addColumn = (name: string) => {
    // A name the result does not have cannot be grouped by, and a duplicate would render
    // `GROUP BY "a", "a"` — accepted by Trino and meaningless to a reader.
    if (!names.includes(name) || draft.columns.includes(name)) return;
    setDraft((d) => ({...d, columns: [...d.columns, name]}));
  };

  const moveColumn = (name: string, direction: -1 | 1) => {
    setDraft((d) => {
      const at = d.columns.indexOf(name);
      const to = at + direction;
      if (at === -1 || to < 0 || to >= d.columns.length) return d;
      const columns = [...d.columns];
      [columns[at], columns[to]] = [columns[to], columns[at]];
      return {...d, columns};
    });
  };

  const addAggregate = () => {
    // `SUM(*)` is not SQL and an aggregate over no column is nothing — both are refused by
    // making them unreachable in the pickers, and turned back here in case they are not.
    if (pendingColumn === '' || (pendingColumn === ALL_ROWS && pendingFn !== 'COUNT')) return;
    const next = {...draft, aggregates: [...draft.aggregates, {fn: pendingFn, column: pendingColumn}]};
    // Two projections producing one output name make the result's columns
    // indistinguishable and the ordering rule ambiguous — the renderer refuses it, so the
    // panel has to refuse it first (its message is operator text, SPEC-106). The renderer's
    // OWN rule, which also catches an alias colliding with a grouping COLUMN's name.
    const collision = groupingNameCollision(next);
    if (collision !== null) {
      setError(`Something here is already called “${collision}”.`);
      return;
    }
    setError(null);
    setDraft(next);
  };

  // Read from the APPLIED description, because that is the ordering the grouping would
  // have to live with: the draft cannot change a sort.
  const refusal = groupingApplyRefusal(query, draft.columns.length > 0 ? draft : null);

  return (
    <aside
      aria-label="Grouping"
      className="flex flex-none flex-col gap-3 rounded-lg border border-border bg-surface p-3 tablet:w-72"
      onDragOver={(event) => {
        if (draggedColumnRef.current) event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        const dragged = draggedColumnRef.current;
        draggedColumnRef.current = null;
        if (dragged) addColumn(dragged);
      }}>
      <div className="flex flex-none items-center gap-2">
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-text">Grouping</h3>
        <IconButton
          label="Close grouping panel"
          onClick={onClose}>
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4"
            aria-hidden="true">
            <path
              strokeLinecap="round"
              d="M2 2l12 12M14 2L2 14"
            />
          </svg>
        </IconButton>
      </div>

      <section aria-label="Grouping columns">
        {draft.columns.length === 0 ? (
          <p className="text-sm text-text-2">{GROUPING_NO_COLUMNS}</p>
        ) : (
          <ol className="flex flex-col gap-1">
            {draft.columns.map((name, position) => (
              <li
                key={name}
                className="flex items-center gap-1 rounded-md border border-border px-2 py-1">
                <span className="min-w-0 flex-1 truncate text-sm text-text">{name}</span>
                {/* The keyboard path for an order a drag would otherwise own — the
                    rendered GROUP BY follows this list (AC1). */}
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Group by ${name} earlier`}
                  disabledReason={position === 0 ? `“${name}” is already first.` : undefined}
                  onClick={() => moveColumn(name, -1)}>
                  ↑
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Group by ${name} later`}
                  disabledReason={position === draft.columns.length - 1 ? `“${name}” is already last.` : undefined}
                  onClick={() => moveColumn(name, 1)}>
                  ↓
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${name} from grouping`}
                  onClick={() => setDraft((d) => ({...d, columns: d.columns.filter((c) => c !== name)}))}>
                  ✕
                </Button>
              </li>
            ))}
          </ol>
        )}
        <div className="mt-2 flex items-center gap-1">
          <select
            aria-label="Column to group by"
            className={`${SELECT_CLASS} min-w-0 flex-1`}
            value=""
            onChange={(event) => addColumn(event.target.value)}>
            <option value="">Add a column…</option>
            {ungrouped.map((name) => (
              <option
                key={name}
                value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section
        aria-label="Aggregates"
        className="flex flex-col gap-1">
        <ul className="flex flex-col gap-1">
          {draft.aggregates.map((aggregate) => (
            <li
              key={aggregateAlias(aggregate)}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1">
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-text">
                {aggregate.fn}({aggregate.column})
              </span>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Remove ${aggregate.fn} of ${aggregate.column}`}
                onClick={() =>
                  setDraft((d) => ({
                    ...d,
                    aggregates: d.aggregates.filter((a) => aggregateAlias(a) !== aggregateAlias(aggregate))
                  }))
                }>
                ✕
              </Button>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-1">
          <select
            aria-label="Aggregate function"
            className={`${SELECT_CLASS} flex-none`}
            value={pendingFn}
            onChange={(event) => {
              const fn = event.target.value as AggregateFunction;
              // A refusal is about the pair that was proposed, so changing either half
              // retires it — an alert left standing describes a gesture nobody is making.
              setError(null);
              setPendingFn(fn);
              // `*` is COUNT's alone: `SUM(*)` is not SQL, and the renderer refuses it.
              if (fn !== 'COUNT' && pendingColumn === ALL_ROWS) setPendingColumn(names[0] ?? '');
            }}>
            {AGGREGATE_FUNCTIONS.map((fn) => (
              <option
                key={fn}
                value={fn}>
                {fn}
              </option>
            ))}
          </select>
          <select
            aria-label="Aggregate column"
            className={`${SELECT_CLASS} min-w-0 flex-1`}
            value={pendingColumn}
            onChange={(event) => {
              setError(null);
              setPendingColumn(event.target.value);
            }}>
            {pendingFn === 'COUNT' && <option value={ALL_ROWS}>All rows (*)</option>}
            {names.map((name) => (
              <option
                key={name}
                value={name}>
                {name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            onClick={addAggregate}>
            Add
          </Button>
        </div>
        {error !== null && (
          <p
            role="alert"
            className="text-xs text-danger">
            {error}
          </p>
        )}
      </section>

      <label className="flex items-center gap-2 text-xs text-text-2">
        <input
          type="checkbox"
          checked={draft.duplicatesOnly}
          onChange={() => setDraft((d) => ({...d, duplicatesOnly: !d.duplicatesOnly}))}
        />
        Show duplicates only
      </label>
      <label className="flex items-center gap-2 text-xs text-text-2">
        <input
          type="checkbox"
          checked={draft.showPercentage}
          onChange={() => setDraft((d) => ({...d, showPercentage: !d.showPercentage}))}
        />
        Show percentage of the rows on this page
      </label>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          disabledReason={refusal ?? undefined}
          onClick={() => onApply(draft.columns.length > 0 ? draft : null)}>
          Apply grouping
        </Button>
        {query.grouping && (
          <Button
            size="sm"
            onClick={() => {
              // Both halves in one gesture: the draft is emptied so the panel shows what
              // the result now is, and the description leaves grouping mode.
              setDraft(emptyGrouping());
              onApply(null);
            }}>
            Stop grouping
          </Button>
        )}
      </div>
    </aside>
  );
}
