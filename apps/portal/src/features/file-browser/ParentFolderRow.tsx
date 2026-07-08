// Filled indigo folder, matching the sibling folder rows in FileBrowser.
function FolderIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className="h-5 w-5 shrink-0 text-accent"
      aria-hidden="true">
      <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

type Props = {
  /** Navigate to the parent prefix. */
  onNavigateUp: () => void;
  /** Reserve the (empty) checkbox column so the row aligns with selectable rows. */
  selectable: boolean;
  /**
   * Presentation: `grid` (default) = the ≥ tablet table row; `mobile` = the 56px
   * two-line card-list row (SPEC-099 FR-007). Placed in the matching markup.
   */
  variant?: 'grid' | 'mobile';
};

// SPEC-098: the `..` parent-folder row — the first listing row when not at the
// space root. Navigation, not an item: no checkbox (an empty spacer keeps column
// alignment), no type pill, no Details button, and excluded from selection (it's
// never added to the select-all set). The whole row is a button, so it's
// keyboard-focusable and Enter/Space-activatable. The `grid` variant's column
// widths mirror FileBrowser's COL_* constants; the `mobile` variant is a 56px
// two-line row (SPEC-099).
export function ParentFolderRow({onNavigateUp, selectable, variant = 'grid'}: Props) {
  if (variant === 'mobile') {
    return (
      <li className="flex h-14 items-center border-b border-border-2 pl-3 pr-2 last:border-0 hover:bg-surface-2">
        <button
          className="flex min-w-0 flex-1 items-center gap-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
          onClick={onNavigateUp}
          aria-label="Go up to parent folder">
          <FolderIcon />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-base font-medium text-text-2">..</span>
            <span className="block truncate text-xs text-text-3">Up one level</span>
          </span>
        </button>
      </li>
    );
  }

  return (
    <li className="flex h-12 items-center border-b border-border-2 last:border-0 hover:bg-surface-2">
      {selectable && (
        <span
          className="w-10 shrink-0"
          aria-hidden="true"
        />
      )}
      <button
        className="flex min-w-0 flex-1 items-center gap-2.5 px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
        onClick={onNavigateUp}
        aria-label="Go up to parent folder">
        <FolderIcon />
        <span className="truncate text-base font-medium text-text-2">..</span>
      </button>
      <span className="w-24 pr-4 text-right text-sm text-text-3">—</span>
      <span className="w-40 pr-4" />
      <span className="w-28 pr-4" />
      <span className="w-44 pr-4" />
    </li>
  );
}
