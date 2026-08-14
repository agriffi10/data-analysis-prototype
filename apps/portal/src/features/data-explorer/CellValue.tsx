import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import type {TransformedValue} from './formatting';

export type CellValueProps = {
  value: string | null;
  className?: string;
  /** How a transformer renders this cell (SPEC-184 FR-005); absent renders the value itself. */
  transformed?: TransformedValue | null;
};

/**
 * One cell's value, with **NULL and the empty string told apart** (SPEC-180 FR-003 AC5).
 *
 * Athena hands every value back as a string, so the two arrive looking identical unless
 * something upstream keeps the difference — `getQueryResults` now does, and this is where
 * it becomes visible. Both markers are rendered as text rather than as styling alone, so
 * a screen reader says which one it is. **They outrank a transformer**: an absence is not
 * a value to render in hex or link to somewhere.
 *
 * A URL transformer's anchor carries `rel="noopener noreferrer"` and `target="_blank"`
 * (SPEC-184 FR-006), and it is only ever built from a resolved `https:` URL — a refused
 * one renders as plain text, with the reason reachable rather than swallowed.
 */
export function CellValue({value, className, transformed}: CellValueProps) {
  if (value === null || value === '') {
    return (
      <span className={className}>
        <span className="italic text-text-3">{value === null ? NULL_DISPLAY : EMPTY_DISPLAY}</span>
      </span>
    );
  }
  if (transformed?.href) {
    return (
      <a
        href={transformed.href}
        target="_blank"
        rel="noopener noreferrer"
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
