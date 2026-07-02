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
