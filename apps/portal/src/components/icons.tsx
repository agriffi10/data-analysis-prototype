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
 * Help / question-mark in a circle (header help link, SPEC-074).
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

/** Chevron pointing left — the rail collapse control (SPEC-085). */
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

/** Chevron pointing right — the collapsed-rail reopen handle (SPEC-085). */
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
