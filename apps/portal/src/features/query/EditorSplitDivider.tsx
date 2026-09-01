import type {HTMLAttributes} from 'react';
import {EDITOR_SPLIT_DIVIDER_HEIGHT} from './query.constants';

type EditorSplitDividerProps = HTMLAttributes<HTMLDivElement> & {
  /** Moves the split one step: -1 shrinks the editor, 1 grows it. */
  onStep: (direction: -1 | 1) => void;
};

function StepButton({direction, label, onStep}: {direction: -1 | 1; label: string; onStep: (d: -1 | 1) => void}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => onStep(direction)}
      className="flex h-[24px] w-[24px] flex-none items-center justify-center rounded-sm text-text-3 hover:bg-surface hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="h-3 w-3"
        aria-hidden="true">
        <path d={direction === -1 ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} />
      </svg>
    </button>
  );
}

/**
 * The draggable boundary between the editor pane and the results region.
 *
 * The split has one owner — the role, the ARIA value and the
 * pointer/keyboard/reset handlers all arrive as `useEditorSplit`'s
 * `dividerProps`, spread onto the separator itself.
 *
 * The band around it is why this is not one element. The separator is
 * focusable, so it is a widget, and a widget may not contain focusable
 * descendants — but the two step buttons have to be there: a drag is not
 * operable by everyone, and without a click path the only way to choose a split
 * would be dragging. So the band is a plain wrapper holding three children: the
 * buttons are the separator's SIBLINGS, not its descendants, which is what keeps
 * them out of its gestures without any event-target filtering. They step by the
 * same amount the arrow keys do, and they are sized in PX rather than Tailwind's
 * rem spacing — the root font-size is 14px, so `h-6` draws 21px and misses the
 * 24px minimum pointer target with nothing to say so.
 *
 * @example
 * const split = useEditorSplit(username, columnHeight);
 * <EditorSplitDivider {...split.dividerProps} onStep={split.step} />
 */
export function EditorSplitDivider({onStep, ...props}: EditorSplitDividerProps) {
  return (
    <div
      style={{height: EDITOR_SPLIT_DIVIDER_HEIGHT}}
      className="flex flex-none items-center justify-center gap-1 border-y border-border bg-surface-2">
      <StepButton
        direction={-1}
        label="Give the results more room"
        onStep={onStep}
      />
      <div
        {...props}
        className="group/split flex h-full flex-1 cursor-row-resize touch-none select-none items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent">
        <span
          aria-hidden="true"
          className="h-1 w-10 rounded-full bg-border transition-colors group-hover/split:bg-accent group-focus/split:bg-accent"
        />
      </div>
      <StepButton
        direction={1}
        label="Give the editor more room"
        onStep={onStep}
      />
    </div>
  );
}
