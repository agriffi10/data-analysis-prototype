import {cx} from '../../lib/cx';
import type {EditorLayoutPreset} from './query.constants';

const OPTIONS: ReadonlyArray<{value: EditorLayoutPreset; label: string; description: string}> = [
  {value: 'editor', label: 'Editor', description: 'Editor layout: grow the editor'},
  {value: 'even', label: 'Even', description: 'Even layout: split editor and results evenly'},
  {value: 'results', label: 'Results', description: 'Results layout: grow the results'}
];

/**
 * SPEC-079 layout-preset segmented control: three toggle buttons in a labeled
 * group snapping the editor/results vertical split (Editor ~90% / Even 50/50 /
 * Results ~90%). The active option carries `aria-pressed` so the selection is
 * never conveyed by styling alone (same pattern as the notifications filter).
 */
export function EditorLayoutControl({
  preset,
  onChange
}: {
  preset: EditorLayoutPreset;
  onChange: (next: EditorLayoutPreset) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Editor and results layout"
      className="inline-flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
      {OPTIONS.map(({value, label, description}) => {
        const active = preset === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            aria-label={description}
            title={description}
            onClick={() => onChange(value)}
            className={cx(
              'h-7 rounded-sm px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active ? 'bg-surface font-semibold text-accent-text shadow-sm' : 'text-text-2 hover:text-text'
            )}>
            {label}
          </button>
        );
      })}
    </div>
  );
}
