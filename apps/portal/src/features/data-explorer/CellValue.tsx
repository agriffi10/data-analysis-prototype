import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import type {TransformedValue} from './formatting';

export type CellValueProps = {
  value: string | null;
  className?: string;
  /** How a transformer renders this cell; absent renders the value itself. */
  transformed?: TransformedValue | null;
  /**
   * Whether a resolved URL may render as an anchor here.
   *
   * False wherever the cell is ALREADY inside something interactive — the Record view puts
   * every value in a button — because an anchor inside a button is nested interactive
   * content, which is invalid and which the tab strip already had to correct once
   * strip. There the transformed text renders as text and the Value panel carries the link.
   */
  linkable?: boolean;
};

/**
 * One cell's value, with **NULL and the empty string told apart**.
 *
 * Athena hands every value back as a string, so the two arrive looking identical unless
 * something upstream keeps the difference — `getQueryResults` now does, and this is where
 * it becomes visible. Both markers are rendered as text rather than as styling alone, so
 * a screen reader says which one it is. **They outrank a transformer**: an absence is not
 * a value to render in hex or link to somewhere.
 *
 * A URL transformer's anchor carries `rel="noopener noreferrer"` and `target="_blank"`,
 * and it is only ever built from a resolved `https:` URL — a refused one
 * renders as plain text with its reason on the cell and in the Value panel.
 *
 * **The anchor is not a tab stop**, and that is not an oversight. `role="grid"` promises a
 * SINGLE tab stop with the arrow keys moving within it, which is why every cell but the
 * cursor carries `tabIndex={-1}`; a focusable anchor per row would put a hundred stops
 * inside the grid and Tab would walk the column instead of leaving. The keyboard route to
 * the link is the Value panel, which is already the keyboard route to a cell's full value.
 */
export function CellValue({value, className, transformed, linkable = true}: CellValueProps) {
  if (value === null || value === '') {
    return (
      <span className={className}>
        <span className="italic text-text-3">{value === null ? NULL_DISPLAY : EMPTY_DISPLAY}</span>
      </span>
    );
  }
  if (transformed?.href && linkable) {
    return (
      <a
        href={transformed.href}
        target="_blank"
        rel="noopener noreferrer"
        tabIndex={-1}
        className={className}>
        {transformed.text}
      </a>
    );
  }
  if (transformed) {
    return (
      <span
        className={className}
        title={transformed.reason}>
        {transformed.text}
      </span>
    );
  }
  return <span className={className}>{value}</span>;
}
