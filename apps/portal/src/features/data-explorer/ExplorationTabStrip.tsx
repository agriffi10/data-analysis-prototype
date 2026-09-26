import {useEffect, useRef} from 'react';
import {cx} from '../../lib/cx';
import {EXPLORATION_TABPANEL_ID} from './dataExplorer.constants';
import type {ExplorationTab} from './dataExplorer.types';

export type ExplorationTabStripProps = {
  tabs: readonly ExplorationTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  /** Opens the source picker, or raises the cap dialog when there is no room. */
  onNew: () => void;
  /**
   * Whether the tab panel is on screen. The picker takes its place while choosing a source, and
   * a tab must not name a panel that is not in the document.
   */
  panelShown: boolean;
};

/**
 * The strip of open explorations, above the results.
 *
 * Mirrors the Query workspace's tab strip in shape rather than sharing it: `features/query/`
 * is a sibling this feature may not import, and the two differ where it counts — an
 * exploration tab has no dirty state, closing the last one is legal here, so the close
 * control is never hidden, and the arrows only move focus, because opening an exploration
 * runs it.
 *
 * The `+` is never disabled. The cap is enforced by refusal and announced by a dialog, so a
 * user at the limit is told why rather than left clicking a dead control.
 */
export function ExplorationTabStrip({
  tabs,
  activeTabId,
  onSelect,
  onClose,
  onNew,
  panelShown
}: ExplorationTabStripProps) {
  const tabRefs = useRef(new Map<string, HTMLDivElement>());
  const refocusAfterClose = useRef(false);

  // A tab closed from the keyboard takes the focused element with it; hand focus to the tab
  // now showing rather than letting it fall back to the top of the page (WCAG 2.4.3). Closing
  // the last one unmounts this strip, and the picker that replaces it takes the focus instead.
  useEffect(() => {
    if (!refocusAfterClose.current) return;
    refocusAfterClose.current = false;
    tabRefs.current.get(activeTabId)?.focus();
  }, [tabs, activeTabId]);

  // WAI-ARIA tabs keyboard model with MANUAL activation (WCAG 2.1.1): the arrows move focus
  // and Enter or Space opens. Showing an exploration runs it, so selecting on every arrow
  // would start an execution for each uncached tab passed on the way. The active tab keeps the
  // roving tabindex, so Tab back into the strip lands on it. Delete closes, because the ✕ is a
  // sibling button rather than a focusable descendant.
  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(tabs[index].id);
      return;
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      // A held key's repeats are ignored: focus moves to the next tab after a close, so each
      // repeat would close another, and an exploration closes without asking.
      if (e.repeat) return;
      refocusAfterClose.current = true;
      onClose(tabs[index].id);
      return;
    }
    if (next === null) return;
    e.preventDefault();
    tabRefs.current.get(tabs[next].id)?.focus();
  };

  return (
    <div className="flex h-10 flex-none items-center gap-1 border-b border-border bg-surface-2 px-3">
      <button
        type="button"
        aria-label="New exploration"
        title="New exploration"
        onClick={onNew}
        className="grid h-7 w-7 flex-none place-items-center rounded-md border border-transparent text-text-2 hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-4 w-4"
          aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      {/* Only `role="tab"` elements may be tablist children (WCAG 4.1.2,
          aria-required-children), so the `+` sits outside it — and the ✕ below is a
          non-focusable span rather than a nested button, which would trip
          nested-interactive INSIDE the tab. This is the only scrollable region. */}
      <div
        role="tablist"
        aria-label="Open explorations"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {tabs.map((tab, index) => {
          const active = tab.id === activeTabId;
          return (
            <div
              key={tab.id}
              ref={(node) => {
                if (node) tabRefs.current.set(tab.id, node);
                else tabRefs.current.delete(tab.id);
              }}
              id={`exploration-tab-${tab.id}`}
              role="tab"
              aria-selected={active}
              aria-controls={panelShown ? EXPLORATION_TABPANEL_ID : undefined}
              tabIndex={active ? 0 : -1}
              onClick={() => onSelect(tab.id)}
              onKeyDown={(e) => onTabKeyDown(e, index)}
              className={cx(
                // Height is the scale step the + beside it shares; do not raise it to give the ✕
                // room. The ✕ is a 24 CSS px pointer target in a 22.5px content box, so its hover
                // fill overhangs the tab's 1px border by 0.75px a side — measured, invisible below
                // about 8x, and cheaper than putting this strip out of line with its siblings.
                'inline-flex h-7 flex-none cursor-pointer items-center gap-2 whitespace-nowrap rounded-md border pl-3 pr-1 text-sm',
                // Inset: the tablist scrolls horizontally, so an outer ring is clipped on three sides.
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent',
                active
                  ? 'border-border bg-surface font-semibold text-text shadow-sm'
                  : 'border-transparent font-medium text-text-2 hover:bg-surface hover:text-text'
              )}>
              <span className="max-w-[16rem] truncate">{tab.label}</span>
              {/* Decorative and non-focusable, exactly as the Query strip's is: keyboard
                  and AT users close with Delete on the focused tab (`onTabKeyDown`), so
                  the action stays fully operable without this control (WCAG 2.1.1).
                  Unlike that strip, the LAST tab keeps its ✕ — zero explorations is a
                  legal state here, and the picker is what takes its place. */}
              <span
                role="presentation"
                title={`Close ${tab.label}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className="grid h-[24px] w-[24px] flex-none cursor-pointer place-items-center rounded-sm text-text-3 hover:bg-danger-soft hover:text-danger">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3 w-3"
                  aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
