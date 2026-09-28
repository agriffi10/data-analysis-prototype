import {useRef} from 'react';
import {cx} from '../../lib/cx';
import type {ResultTab} from './query.types';

type Props = {
  /** One entry per result-producing statement, execution order. */
  tabs: ResultTab[];
  activeIndex: number;
  onSelect: (index: number) => void;
  /** Drops one result tab. Never offered for the last one. */
  onClose: (index: number) => void;
};

/**
 * the result-tab strip shown for a "Run Script (tab per
 * statement)" run — one tab per result-producing statement, labeled by its
 * 1-based statement position and a short statement hint. Same WAI-ARIA tabs
 * keyboard model as QueryTabStrip (roving tabindex; Left/Right/Home/End move
 * focus + selection); the active tab is never indicated by color alone.
 *
 * A tab closes the way an editor tab does: a pointer-only ✕, and Delete or Backspace on the focused
 * tab for keyboard and assistive-technology users. The last tab has neither, so the region always has a
 * result to show. Either way focus lands on the tab shown after the close — the next one when the shown
 * tab closes, the previous when it was the last, and the shown one otherwise — never on <body>.
 */
export function ResultTabs({tabs, activeIndex, onSelect, onClose}: Props) {
  const tabRefs = useRef(new Map<number, HTMLButtonElement>());
  const solo = tabs.length <= 1;

  // Tabs are keyed by execution, so the heir's element survives the close and focus can be handed
  // to it now rather than after the re-render. A click on a ✕ can focus the tab it sits in, which the
  // close then removes, so the pointer path needs this as much as the keyboard one does.
  const close = (index: number) => {
    const heirIndex = index !== activeIndex ? activeIndex : index < tabs.length - 1 ? index + 1 : index - 1;
    const heir = tabRefs.current.get(heirIndex);
    onClose(index);
    heir?.focus();
  };

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    if ((e.key === 'Delete' || e.key === 'Backspace') && !solo) {
      e.preventDefault();
      close(index);
      return;
    }
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    onSelect(next);
    tabRefs.current.get(next)?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Result tabs"
      className="mb-3 flex flex-none items-center gap-1 overflow-x-auto">
      {tabs.map((tab, index) => {
        const active = index === activeIndex;
        return (
          <button
            key={tab.executionId}
            ref={(el) => {
              if (el) tabRefs.current.set(index, el);
              else tabRefs.current.delete(index);
            }}
            type="button"
            id={`result-tab-${index}`}
            role="tab"
            aria-selected={active}
            aria-controls="result-tabpanel"
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(index)}
            onKeyDown={(e) => onTabKeyDown(e, index)}
            title={tab.label}
            className={cx(
              'inline-flex h-7 flex-none cursor-pointer items-center gap-2 whitespace-nowrap rounded-md border pl-3 font-mono text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent',
              solo ? 'pr-3' : 'pr-1',
              active
                ? 'border-border bg-surface text-text shadow-sm'
                : 'border-transparent text-text-2 hover:bg-surface hover:text-text'
            )}>
            <span
              className={cx('h-1.5 w-1.5 flex-none rounded-full bg-accent', active ? 'opacity-100' : 'opacity-0')}
              aria-hidden="true"
            />
            <span className="max-w-56 truncate">{tab.label}</span>
            {/* Decorative and unfocusable rather than a nested button, which axe refuses inside a
                role="tab"; Delete or Backspace on the focused tab is the same action from the keyboard.
                24 CSS px square, the WCAG 2.5.8 minimum pointer target. */}
            {!solo && (
              <span
                role="presentation"
                title={`Close ${tab.label}`}
                onClick={(e) => {
                  e.stopPropagation();
                  close(index);
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
            )}
          </button>
        );
      })}
    </div>
  );
}
