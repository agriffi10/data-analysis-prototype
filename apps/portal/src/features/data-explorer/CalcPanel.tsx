import {useMemo} from 'react';
import {Button} from '../../components/Button';
import {IconButton} from '../../components/IconButton';
import {useEscapeKey} from '../../hooks/useEscapeKey';
import {CALC_DEFAULT_FUNCTIONS, CALC_FUNCTIONS, CALC_FUNCTION_LABELS} from './dataExplorer.constants';
import {calcResults, calcScopeText} from './calc';
import type {CalcFunction, CalcPanelState} from './dataExplorer.types';

export const CALC_NO_SELECTION = 'Select cells in the grid to aggregate them.';

export type CalcPanelProps = {
  /** The selected cells' raw values, row-major. `null` is SQL NULL. */
  values: (string | null)[];
  state: CalcPanelState;
  onStateChange: (state: CalcPanelState) => void;
  onClose: () => void;
};

/**
 * Aggregates over the current cell selection, computed in the browser (SPEC-182 FR-001).
 *
 * **It issues no query, and it could not.** A selection is client state — aggregating it
 * server-side would mean a billed execution per selection change, for a gesture as cheap
 * as dragging across ten cells. The Grouping panel beside it looks like a sibling and is
 * the opposite: a `GROUP BY` is SQL and mints an execution like any other query change.
 *
 * It is a side panel rather than a `Drawer` for a reason that is not stylistic: a Drawer
 * traps focus, and a panel that recomputes on every selection change has to leave the user
 * able to reach the grid. Escape closes it through the depth-ordered registry (SPEC-155),
 * so a dialog opened above it still outranks it.
 *
 * With nothing selected it explains itself rather than showing zeroes (FR-002 AC2): a
 * column of `0`s reads as a computed answer to a question nobody asked.
 */
export function CalcPanel({values, state, onStateChange, onClose}: CalcPanelProps) {
  useEscapeKey(onClose, true);
  const results = useMemo(() => calcResults(values, state), [values, state]);

  const toggleFunction = (fn: CalcFunction) =>
    onStateChange({
      ...state,
      // Filtered from the canonical list rather than appended, so the panel's order never
      // depends on the order the checkboxes were clicked in.
      functions: state.functions.includes(fn)
        ? state.functions.filter((f) => f !== fn)
        : CALC_FUNCTIONS.filter((f) => f === fn || state.functions.includes(f))
    });

  return (
    <aside
      aria-label="Calc"
      className="flex flex-none flex-col gap-3 rounded-lg border border-border bg-surface p-3 tablet:w-72">
      <div className="flex flex-none items-center gap-2">
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-text">Calc</h3>
        <IconButton
          label="Close calc panel"
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

      {values.length === 0 ? (
        <p className="text-sm text-text-2">{CALC_NO_SELECTION}</p>
      ) : (
        <>
          <p className="text-xs text-text-3">{calcScopeText(values.length)}</p>
          <dl className="flex flex-col gap-1">
            {results.map((result) => (
              <div
                key={result.fn}
                className="flex items-baseline justify-between gap-2 rounded-md border border-border px-2 py-1">
                <dt className="flex-none text-xs text-text-2">{CALC_FUNCTION_LABELS[result.fn]}</dt>
                <dd className="min-w-0 flex-1 truncate text-right font-mono text-sm text-text">
                  {result.value}
                  {result.skipped > 0 && (
                    // Said beside the value rather than in a footnote: a sum that ignored
                    // half its cells is a different number, and the reader has to be told
                    // where they are looking at it (FR-001 AC3).
                    <span className="ml-1 font-sans text-[10px] text-text-3">{result.skipped} skipped</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}

      <label className="flex items-center gap-2 text-xs text-text-2">
        <input
          type="checkbox"
          checked={state.includeStrings}
          onChange={() => onStateChange({...state, includeStrings: !state.includeStrings})}
        />
        Include text values
      </label>

      <fieldset className="flex flex-col gap-1">
        <legend className="text-xs font-semibold text-text-2">Functions</legend>
        {CALC_FUNCTIONS.map((fn) => (
          <label
            key={fn}
            className="flex items-center gap-2 text-xs text-text-2">
            <input
              type="checkbox"
              checked={state.functions.includes(fn)}
              onChange={() => toggleFunction(fn)}
            />
            {CALC_FUNCTION_LABELS[fn]}
          </label>
        ))}
      </fieldset>

      <Button
        size="sm"
        onClick={() => onStateChange({...state, functions: CALC_DEFAULT_FUNCTIONS})}>
        Reset functions
      </Button>
    </aside>
  );
}
