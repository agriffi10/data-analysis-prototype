import {type ReactNode} from 'react';

export type MobileActionBarProps = {
  /**
   * Primary mobile actions, caller-supplied. Give each the app's mobile touch height, `!h-11`:
   * 38.5px at the 14px root, clear of the 24px AA floor and short of the AAA 44px, which this
   * project does not target.
   */
  children: ReactNode;
  /** Accessible name for the toolbar. Default "Actions". */
  ariaLabel?: string;
};

/**
 * Mobile-only bar fixed to the bottom of the viewport (`tablet:hidden`),
 * safe-area-inset aware so controls clear the home indicator. Surfaces mount
 * their primary mobile actions here (Files → New folder + Upload). This is the
 * shell only — the consuming page pads its scroll region by the bar height so
 * the bar never occludes the last row.
 *
 * @example
 * <MobileActionBar ariaLabel="File actions">
 *   <Button className="!h-11 flex-1">New folder</Button>
 *   <Button variant="primary" className="!h-11 flex-1">Upload</Button>
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
