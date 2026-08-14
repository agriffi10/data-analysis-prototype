export type StripingControlProps = {
  /** Every column in display order — the ones a band can be defined over. */
  columns: string[];
  /** The chosen columns. Empty is striping OFF, which is a state and not a default. */
  value: string[];
  onChange: (next: string[]) => void;
};

export const STRIPING_SCOPE_TEXT = 'Bands are worked out from the rows on this page.';
export const STRIPING_OFF_TEXT = 'No columns chosen, so nothing is banded.';

/**
 * Which columns define a band of consecutive equal rows (SPEC-184 FR-004).
 *
 * A checkbox list rather than a single select, because a band is defined over ALL the
 * chosen columns together — an order line is one band per (order, product), not per order.
 *
 * The scope sentence is not decoration. Only one page is ever in memory, so a band touching
 * either end of it may well continue past it and nothing here can know — the same claim the
 * Calc panel and the percentage column each have to make, for the same reason.
 */
export function StripingControl({columns, value, onChange}: StripingControlProps) {
  const toggle = (name: string) => onChange(value.includes(name) ? value.filter((n) => n !== name) : [...value, name]);

  return (
    <fieldset className="rounded-md border border-border px-3 py-2">
      <legend className="px-1 text-sm font-medium text-text">Band rows by</legend>
      <p className="text-xs text-text-3">{STRIPING_SCOPE_TEXT}</p>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {columns.map((name) => (
          <li key={name}>
            <label className="flex items-center gap-1.5 text-xs text-text-2">
              <input
                type="checkbox"
                checked={value.includes(name)}
                onChange={() => toggle(name)}
              />
              {name}
            </label>
          </li>
        ))}
      </ul>
      {value.length === 0 && <p className="mt-2 text-xs text-text-3">{STRIPING_OFF_TEXT}</p>}
    </fieldset>
  );
}
