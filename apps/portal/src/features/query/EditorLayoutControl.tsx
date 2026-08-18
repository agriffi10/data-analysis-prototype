import {cx} from '../../lib/cx';
import type {EditorLayoutPreset} from './query.constants';

const OPTIONS: ReadonlyArray<{value: EditorLayoutPreset; label: string; description: string}> = [
  {value: 'even', label: 'Default', description: 'Default layout: split editor and results evenly'},
  {value: 'editor', label: 'Query Editor', description: 'Query Editor layout: grow the editor'},
  {value: 'results', label: 'Results', description: 'Results layout: grow the results'}
];

/**
 * Layout-preset segmented control: three toggle buttons in a labeled
 * group snapping the editor/results vertical split (Default 50/50 / Query
 * Editor ~90% / Results ~90%). The active option carries `aria-pressed` so the
 * selection is never conveyed by styling alone (same pattern as the
 * notifications filter).
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
