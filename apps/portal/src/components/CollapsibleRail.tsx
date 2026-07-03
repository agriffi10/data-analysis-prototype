import {useId, type ReactNode} from 'react';
import {cx} from '../lib/cx';
import {IconButton} from './IconButton';
import {ChevronLeftIcon, ChevronRightIcon} from './icons';
import {useRailCollapsed} from './useRailCollapsed';

type CollapsibleRailProps = {
  /** Accessible name for the rail region (e.g. "Your spaces navigation", "Schema browser"). */
  ariaLabel: string;
  /** Optional uppercase section label shown in the rail header next to the collapse control. */
  title?: ReactNode;
  /** The rail body — the existing Sidebar list / SchemaBrowser tree. */
  children: ReactNode;
};

/**
 * Shared chrome for the two authenticated left rails (Files `Sidebar` + Query
 * `SchemaBrowser`, SPEC-085): the 248px panel (hidden below `md` as before) plus a
 * header **collapse** control and, when collapsed, a slim **reopen** handle at the
 * content's left edge.
 *
 * Collapsing sets the panel to `display:none` — removed from the flex row so `<main>`
 * fills the freed width — WITHOUT unmounting it, so in-rail expansion/selection state
 * is preserved and both controls' `aria-controls` stay valid. The collapsed choice is
 * remembered per browser via `useRailCollapsed` (shared across both rails).
 */
export function CollapsibleRail({ariaLabel, title, children}: CollapsibleRailProps) {
  const {collapsed, setCollapsed} = useRailCollapsed();
  const railId = useId();

  return (
    <>
      <aside
        id={railId}
        aria-label={ariaLabel}
        className={cx(
          'w-[248px] shrink-0 flex-col overflow-y-auto border-r border-border bg-surface',
          collapsed ? 'hidden' : 'hidden md:flex'
        )}>
        <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-3">
          {title ? (
            <span className="text-xs font-semibold uppercase tracking-[.04em] text-text-3">{title}</span>
          ) : (
            <span aria-hidden="true" />
          )}
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
      </aside>

      {collapsed && (
        <button
          type="button"
          aria-label="Show sidebar"
          aria-expanded={false}
          aria-controls={railId}
          onClick={() => setCollapsed(false)}
          className="hidden w-7 shrink-0 items-start justify-center border-r border-border bg-surface pt-3 text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent md:flex">
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      )}
    </>
  );
}
