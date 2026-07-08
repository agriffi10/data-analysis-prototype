import {type ReactNode} from 'react';

export type MobileActionBarProps = {
  /** Primary mobile actions (caller-supplied; each should be a ≥44px target). */
  children: ReactNode;
  /** Accessible name for the toolbar. Default "Actions". */
  ariaLabel?: string;
};

/**
 * Mobile-only bar fixed to the bottom of the viewport (`tablet:hidden`),
 * safe-area-inset aware so controls clear the home indicator. Surfaces mount
 * their primary mobile actions here (Files → New folder + Upload). This is the
 * shell only — the consuming page pads its scroll region by the bar height so
 * the bar never occludes the last row (SPEC-095).
 *
 * @example
 * <MobileActionBar ariaLabel="File actions">
 *   <Button className="flex-1">New folder</Button>
 *   <Button variant="primary" className="flex-1">Upload</Button>
 * </MobileActionBar>
 */
export function MobileActionBar({children, ariaLabel = 'Actions'}: MobileActionBarProps) {
  return (
    <div
      role="toolbar"
      aria-label={ariaLabel}
      className="fixed inset-x-0 bottom-0 z-30 flex items-center gap-2 border-t border-border bg-surface px-4 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] tablet:hidden">
      {children}
    </div>
  );
}
