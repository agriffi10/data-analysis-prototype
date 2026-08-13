import {useRef} from 'react';
import {cx} from '../../lib/cx';
import type {ExplorationTab} from './dataExplorer.types';

export type ExplorationTabStripProps = {
  tabs: readonly ExplorationTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  /** Opens the source picker, or raises the cap dialog when there is no room (FR-008 AC2). */
  onNew: () => void;
};

/**
 * The strip of open explorations, above the results (FR-008).
 *
 * Mirrors the Query workspace's tab strip in shape and keyboard model rather than sharing
 * it: `features/query/` is a sibling this feature may not import (SPEC-176), and the two
 * differ where it counts — an exploration tab has no dirty state, and closing the last one
 * is legal here, so the close control is never hidden.
 *
 * The `+` is never disabled. The cap is enforced by refusal and announced by a dialog, so a
 * user at the limit is told why rather than left clicking a dead control.
 */
export function ExplorationTabStrip({tabs, activeTabId, onSelect, onClose, onNew}: ExplorationTabStripProps) {
  const tabRefs = useRef(new Map<string, HTMLDivElement>());

  // WAI-ARIA tabs keyboard model (WCAG 2.1.1): with a roving tabindex only the active tab is
  // in the Tab sequence, so the arrows have to move focus and selection together. Delete
  // closes, because the ✕ is a sibling button rather than a focusable descendant.
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
      onClose(tabs[index].id);
      return;
    }
    if (next === null) return;
    e.preventDefault();
    const nextTab = tabs[next];
    onSelect(nextTab.id);
    tabRefs.current.get(nextTab.id)?.focus();
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
      <div
        role="tablist"
        aria-label="Open explorations"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {tabs.map((tab, index) => {
          const active = tab.id === activeTabId;
          return (
            <div
              key={tab.id}
              className={cx(
                'flex h-7 flex-none items-center gap-1 rounded-md border px-2 text-sm',
                active
                  ? 'border-border bg-surface font-semibold text-text shadow-sm'
                  : 'border-transparent text-text-2 hover:bg-surface hover:text-text'
              )}>
              <div
                role="tab"
                ref={(node) => {
                  if (node) tabRefs.current.set(tab.id, node);
                  else tabRefs.current.delete(tab.id);
                }}
                tabIndex={active ? 0 : -1}
                aria-selected={active}
                onClick={() => onSelect(tab.id)}
                onKeyDown={(e) => onTabKeyDown(e, index)}
                className="max-w-[16rem] cursor-pointer truncate focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                {tab.label}
              </div>
              <button
                type="button"
                aria-label={`Close ${tab.label}`}
                onClick={() => onClose(tab.id)}
                className="grid h-5 w-5 flex-none place-items-center rounded text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3 w-3"
                  aria-hidden="true">
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
