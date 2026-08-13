import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';

export type CellValueProps = {
  value: string | null;
  className?: string;
};

/**
 * One cell's value, with **NULL and the empty string told apart** (SPEC-180 FR-003 AC5).
 *
 * Athena hands every value back as a string, so the two arrive looking identical unless
 * something upstream keeps the difference — `getQueryResults` now does, and this is where
 * it becomes visible. Both markers are rendered as text rather than as styling alone, so
 * a screen reader says which one it is.
 */
export function CellValue({value, className}: CellValueProps) {
  if (value === null || value === '') {
    return (
      <span className={className}>
        <span className="italic text-text-3">{value === null ? NULL_DISPLAY : EMPTY_DISPLAY}</span>
      </span>
    );
  }
  return <span className={className}>{value}</span>;
}
