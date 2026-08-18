import {useId, type ReactNode} from 'react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {ChevronLeftIcon, ChevronRightIcon} from './icons';
import {useRailCollapsed} from './useRailCollapsed';
import {SECTION_CAPTION} from './fieldStyles';

type CollapsibleRailProps = {
  /** Accessible name for the rail region (e.g. "Your spaces navigation", "Schema browser"). */
  ariaLabel: string;
  /** Optional uppercase section label shown in the rail header next to the collapse control. */
  title?: ReactNode;
  /**
   * Width utilities for the expanded panel — static classes only, so a host can
   * narrow the rail per breakpoint (the Query rail is `w-[220px] desktop:w-[248px]`,
   * Applied to the panel and its fixed-width inner content alike.
   */
  widthClass?: string;
  /** The rail body — the existing Sidebar list / SchemaBrowser tree. */
  children: ReactNode;
};

/**
 * Shared chrome for the two authenticated left rails (Files `Sidebar` + Query
 * `SchemaBrowser`): the 248px panel (`widthClass` narrows it per host;
 * hidden below `tablet` as before) plus a header **collapse** control and, when
 * collapsed, a slim **reopen** handle at the content's left edge.
 *
 * Collapsing eases the panel's width to `0` (border removed) so `<main>` fills the
 * freed width, WITHOUT unmounting it, so in-rail expansion/selection state is preserved
 * and both controls' `aria-controls` stay valid. The inner content keeps the panel's
 * expanded width so it doesn't reflow as the panel narrows, and a `visibility` transition removes
 * it from the accessibility tree once collapsed (matching the previous `display:none`).
 * The collapsed choice is remembered per browser via `useRailCollapsed` (shared across
 * both rails).
 */
export function CollapsibleRail({ariaLabel, title, widthClass = 'w-[248px]', children}: CollapsibleRailProps) {
  const {collapsed, setCollapsed} = useRailCollapsed();
  const railId = useId();

  return (
    <>
      <aside
        id={railId}
        aria-label={ariaLabel}
        className={cx(
          'hidden shrink-0 flex-col overflow-hidden bg-surface transition-[width] duration-200 ease-out motion-reduce:transition-none tablet:flex',
          collapsed ? 'w-0 border-r-0' : cx(widthClass, 'border-r border-border')
        )}>
        <div
          className={cx(
            'flex flex-1 flex-col overflow-y-auto transition-[visibility] duration-200 motion-reduce:transition-none',
            widthClass,
            collapsed ? 'invisible' : 'visible'
          )}>
          <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-3">
            {title ? <span className={SECTION_CAPTION}>{title}</span> : <span aria-hidden="true" />}
            <IconButton
              label="Collapse sidebar"
              size="sm"
              aria-expanded={!collapsed}
              aria-controls={railId}
              onClick={() => setCollapsed(true)}>
              <ChevronLeftIcon className="h-4 w-4" />
            </IconButton>
          </div>
          <div className="flex flex-col gap-1 px-3 pb-4">{children}</div>
        </div>
      </aside>

      {collapsed && (
        <button
          type="button"
          aria-label="Show sidebar"
          aria-expanded={false}
          aria-controls={railId}
          onClick={() => setCollapsed(false)}
          className="hidden w-7 shrink-0 items-start justify-center border-r border-border bg-surface pt-3 text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent tablet:flex">
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      )}
    </>
  );
}
