// Shared inline icons. No icon library by design — thin wrappers around the SVG
// path so callers only pass `className` for sizing/color. All are aria-hidden
// (decorative); the host control supplies the accessible name.

type IconProps = {className?: string};

/**
 * Upload arrow (BrandMark, landing-page feature icon).
 *
 * @example
 * <UploadIcon className="h-4 w-4 text-white" />
 */
export function UploadIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M5 20h14" />
    </svg>
  );
}

/**
 * Document / saved-query bookmark (query tab strip, history row, saved-queries drawer).
 *
 * @example
 * <DocumentIcon className="h-4 w-4" />
 */
export function DocumentIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
      <path d="M9 4v5h6" />
    </svg>
  );
}

/**
 * Folder. Outlined by default (nav); `filled` renders the solid treatment the
 * landing page uses.
 *
 * @example
 * <FolderIcon className="h-[18px] w-[18px]" filled />
 */
export function FolderIcon({className, filled = false}: IconProps & {filled?: boolean}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke={filled ? undefined : 'currentColor'}
      strokeWidth={filled ? undefined : 2}
      className={className}
      aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  );
}

/**
 * Overlapping sheets (copy-to-clipboard button).
 *
 * @example
 * <CopyIcon className="h-4 w-4" />
 */
export function CopyIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <rect
        x="9"
        y="9"
        width="11"
        height="11"
        rx="2"
      />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

/**
 * Bell (notifications header link).
 *
 * @example
 * <BellIcon className="h-5 w-5" />
 */
export function BellIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  );
}

/**
 * Checkmark (copy-confirmation state).
 *
 * @example
 * <CheckIcon className="h-4 w-4 text-success" />
 */
export function CheckIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

/**
 * Help / question-mark in a circle (header help link).
 *
 * @example
 * <HelpCircleIcon className="h-5 w-5" />
 */
export function HelpCircleIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="10"
      />
      <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </svg>
  );
}

/** Speech bubble — the Give feedback control, and the Help section for it. */
export function FeedbackIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.9 9.9 0 0 1-3.9-.8L3 21l1.9-4.6A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z" />
    </svg>
  );
}

/**
 * Chevron pointing down (accordion open/close affordance; rotates 180° when open).
 *
 * @example
 * <ChevronDownIcon className="h-[18px] w-[18px]" />
 */
export function ChevronDownIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

/** Chevron pointing left — the rail collapse control. */
export function ChevronLeftIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="m15 18-6-6 6-6" />
    </svg>
  );
}

/** Chevron pointing right — the collapsed-rail reopen handle. */
export function ChevronRightIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

/**
 * Database cylinder (Query feature icon; mirrors the primary-nav Query tab).
 *
 * @example
 * <DatabaseIcon className="h-[18px] w-[18px]" />
 */
export function DatabaseIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <ellipse
        cx="12"
        cy="5"
        rx="9"
        ry="3"
      />
      <path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" />
      <path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" />
    </svg>
  );
}

/**
 * Grid / table (Tables feature icon — create-from-folder + share).
 *
 * @example
 * <TableIcon className="h-[18px] w-[18px]" />
 */
export function TableIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <rect
        x="3"
        y="4"
        width="18"
        height="16"
        rx="2"
      />
      <path d="M3 9h18M3 14.5h18M9 9v11M15 9v11" />
    </svg>
  );
}

/**
 * Three linked nodes (Shared connections feature icon).
 *
 * @example
 * <ConnectionsIcon className="h-[18px] w-[18px]" />
 */
export function ConnectionsIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <circle
        cx="6"
        cy="6"
        r="2.5"
      />
      <circle
        cx="18"
        cy="6"
        r="2.5"
      />
      <circle
        cx="12"
        cy="18"
        r="2.5"
      />
      <path d="M7.5 7.5 10.5 16M16.5 7.5 13.5 16M8 6h8" />
    </svg>
  );
}

/**
 * Info circle (accent "Tip" callout).
 *
 * @example
 * <InfoIcon className="h-4 w-4" />
 */
export function InfoIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="10"
      />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

/**
 * Warning triangle (danger "Careful" callout for irreversible actions).
 *
 * @example
 * <WarningIcon className="h-4 w-4" />
 */
export function WarningIcon({className}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
  );
}

/**
 * Edit / rename (file-browser detail panels).
 *
 * The file browser's own glyphs follow. `PencilIcon`/`DownloadIcon` are 20-grid at 1.7
 * stroke weight, sized to sit inside a row's action button; `TrashIcon` is 24-grid to
 * sit level with text in a toolbar. Kept distinct from the 24-grid set above rather
 * than folded into it — the grids do not render the same shape, and unifying them
 * would move pixels on every file row.
 *
 * @example
 * <PencilIcon className="h-4 w-4" />
 */
export function PencilIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      className={className}
      aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 3.5l3 3L7 16l-3.5.5L4 13z"
      />
    </svg>
  );
}

/**
 * Download — arrow into a tray (file-browser detail panels).
 *
 * @example
 * <DownloadIcon className="h-4 w-4" />
 */
export function DownloadIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      className={className}
      aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M10 3v9m0 0l-3.5-3.5M10 12l3.5-3.5M4 15.5h12"
      />
    </svg>
  );
}

/**
 * Delete (the selection toolbar's bulk action).
 *
 * @example
 * <TrashIcon />
 */
export function TrashIcon({className = 'h-[15px] w-[15px]'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
    </svg>
  );
}

/**
 * The folder glyph on a FILE-LIST ROW — filled and accent-coloured, because colour is
 * what tells a folder from a file at a glance down a long list. Distinct from
 * {@link FolderIcon}, which is the 24-grid navigation/branding folder; three row
 * components had this one copied out.
 *
 * @example
 * <FolderRowIcon />
 */
export function FolderRowIcon({className = 'h-5 w-5'}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className={`${className} shrink-0 text-accent`}
      aria-hidden="true">
      <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

/** The file glyph on a file-list row — outlined and muted, the quiet half of the pair. */
export function FileRowIcon({className = 'h-5 w-5'}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className={`${className} shrink-0 text-text-3`}
      aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 3H7a2 2 0 00-2 2v10a2 2 0 002 2h6a2 2 0 002-2V7.5L13.5 3z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13 3v4.5H17.5"
      />
    </svg>
  );
}

/**
 * Run / execute (the query toolbar's Run buttons). Filled, not stroked — a solid
 * triangle reads as "play" at `h-4` (14px) where an outlined one reads as a stray chevron.
 *
 * @example
 * <PlayIcon />
 */
export function PlayIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="none"
      className={className}
      aria-hidden="true">
      <path d="M7 5v14l11-7z" />
    </svg>
  );
}

/** Save (the query toolbar) — a floppy, still the least ambiguous save glyph there is. */
export function SaveIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
      <path d="M9 4v5h6" />
      <path d="M8 21v-7h8v7" />
    </svg>
  );
}

/** View / preview (the query toolbar's Create view). */
export function EyeIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle
        cx="12"
        cy="12"
        r="3"
      />
    </svg>
  );
}

/**
 * The query toolbar's Clear glyph — a lidded bin, drawn on a wider 24-grid than
 * {@link TrashIcon}'s toolbar variant. The two are NOT the same artwork; unifying them
 * is a visual change and belongs to whoever decides the toolbar's icon set, not to a
 * de-duplication pass.
 */
export function TrashLidIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </svg>
  );
}

/**
 * The schema rail's database glyph — 18px and `flex-none`, sized for a tree row.
 * Distinct from {@link DatabaseIcon} (the nav/landing one) in size only; two rail
 * components had it written out identically.
 */
export function DatabaseRowIcon({className = 'h-[18px] w-[18px] flex-none'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <ellipse
        cx="12"
        cy="6"
        rx="8"
        ry="3"
      />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}

/**
 * Refresh — a circular arrow. Re-reads what is on screen; never a "retry".
 *
 * @example
 * <RefreshIcon className="h-4 w-4" />
 */
export function RefreshIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M16.5 8A6.5 6.5 0 004.6 5.6" />
      <path d="M3.5 12A6.5 6.5 0 0015.4 14.4" />
      <path d="M4.5 2v3.6h3.6" />
      <path d="M15.5 18v-3.6h-3.6" />
    </svg>
  );
}

/**
 * Half-filled circle — the theme control's glyph, in the header and the nav drawer.
 *
 * @example
 * <ThemeIcon className="h-4 w-4" />
 */
export function ThemeIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="9"
      />
      <path
        fill="currentColor"
        stroke="none"
        d="M12 3a9 9 0 0 1 0 18z"
      />
    </svg>
  );
}

/** Sign out — a door with an arrow leaving through it. */
export function SignOutIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

/**
 * Three stacked dots — the affordance that says a control opens a menu, on the account
 * trigger in the header.
 *
 * Filled circles rather than a stroked path: at `h-4` (14px) a stroke round-cap renders as a soft
 * smudge, and the dots have to read as three distinct marks to say "menu" at all.
 *
 * @example
 * <KebabIcon className="h-4 w-4" />
 */
export function KebabIcon({className = 'h-4 w-4'}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true">
      <circle
        cx="12"
        cy="5"
        r="1.75"
      />
      <circle
        cx="12"
        cy="12"
        r="1.75"
      />
      <circle
        cx="12"
        cy="19"
        r="1.75"
      />
    </svg>
  );
}
