import {useRef} from 'react';
import {Button} from '../../components/Button';
import {Menu} from '../../components/Menu';
import {cx} from '../../lib/cx';
import {CheckIcon, CopyIcon, EyeIcon, PlayIcon, SaveIcon, TrashLidIcon} from '../../components/icons';
import {useCopyToClipboard} from '../../lib/useCopyToClipboard';
import {FeatureGate} from '../feature-flags';

// The editor toolbar is icon-only in the tablet band so its
// actions fit the narrower main column; each button keeps its `aria-label`.
const TOOLBAR_LABEL = 'hidden desktop:inline';

type Props = {
  /** The batch hasn't reached a terminal state — the run split button becomes Stop. */
  isInFlight: boolean;
  canRun: boolean;
  canClear: boolean;
  /** Gates Copy, Save query and Create view alike: each is disabled only when the buffer is empty. */
  canSave: boolean;
  /** The active tab's SQL, which Copy writes to the clipboard whole. */
  sql: string;
  onClear: () => void;
  onSave: () => void;
  onCreateView: () => void;
  onStop: () => void;
  onRunStatement: () => void;
  onRunScript: (scope: 'script-single' | 'script-tabs') => void;
};

/**
 * The editor toolbar: Clear, Copy, Save and Create view, and the run split
 * button — which is replaced by a single Stop while a batch is in flight. The
 * actions sit to the right; the editor/results split is dragged at its own
 * divider, not chosen here.
 */
export function QueryToolbar({
  isInFlight,
  canRun,
  canClear,
  canSave,
  sql,
  onClear,
  onSave,
  onCreateView,
  onStop,
  onRunStatement,
  onRunScript
}: Props) {
  const {copied, copy} = useCopyToClipboard();
  const runStopRef = useRef<HTMLButtonElement>(null);
  // A key still held from one press repeats onto this same element after it swaps — Run into
  // Stop, or Stop back into Run once the batch settles — and would stop the query that press
  // started, or run it again. Only a fresh press acts.
  const ignoreHeldKey = (e: React.KeyboardEvent) => {
    if (e.repeat && (e.key === 'Enter' || e.key === ' ')) e.preventDefault();
  };
  // The run scopes in the menu hand focus to Run, which becomes Stop: the menu's trigger, where
  // focus would otherwise return, leaves the page with the rest of the split button.
  const runScript = (scope: 'script-single' | 'script-tabs') => {
    onRunScript(scope);
    runStopRef.current?.focus();
  };
  return (
    <div className="flex min-h-[52px] flex-none flex-wrap items-center gap-3 border-b border-border bg-surface px-5 py-2">
      <div className="flex-1" />
      <Button
        variant="dangerOutline"
        onClick={onClear}
        disabled={!canClear}
        aria-label="Clear query">
        <TrashLidIcon />
        <span className={TOOLBAR_LABEL}>Clear</span>
      </Button>
      <Button
        variant="ghost"
        onClick={() => void copy(sql)}
        disabled={!canSave}
        aria-label="Copy query">
        {copied ? <CheckIcon className="h-4 w-4 text-success" /> : <CopyIcon className="h-4 w-4" />}
        <span className={TOOLBAR_LABEL}>Copy</span>
        <span
          role="status"
          className="sr-only">
          {copied ? 'Query copied' : ''}
        </span>
      </Button>
      <Button
        variant="ghost"
        onClick={onSave}
        disabled={!canSave}
        aria-label="Save query">
        <SaveIcon />
        <span className={TOOLBAR_LABEL}>Save</span>
      </Button>
      {/* registered under the `query` flag, which already removes this whole
          route — the row exists so a future surface inherits the gate, not the bug. */}
      <FeatureGate flag="query">
        <Button
          variant="ghost"
          onClick={onCreateView}
          disabled={!canSave}
          aria-label="Create view">
          <EyeIcon />
          <span className={TOOLBAR_LABEL}>Create view</span>
        </Button>
      </FeatureGate>
      {/* Run and Stop are ONE element whose role changes, so focus on it survives the swap
          (WCAG 2.4.3) — two elements would drop it to <body> as each unmounts. */}
      <div className="inline-flex items-stretch">
        {isInFlight ? (
          <Button
            ref={runStopRef}
            variant="ghost"
            onClick={onStop}
            onKeyDown={ignoreHeldKey}
            aria-label="Stop the running query"
            className="text-danger hover:bg-danger-soft hover:text-danger">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true">
              <rect
                x="6"
                y="6"
                width="12"
                height="12"
                rx="2"
              />
            </svg>
            <span className={TOOLBAR_LABEL}>Stop</span>
          </Button>
        ) : (
          // Three distinct run scopes as a split button.
          // Run Statement stays the primary action (⌘⏎); the two whole-script
          // scopes — which differ only in how results are shown — live in an
          // attached dropdown so the toolbar stays compact.
          <Button
            ref={runStopRef}
            variant="primary"
            onClick={onRunStatement}
            onKeyDown={ignoreHeldKey}
            disabled={!canRun}
            title="Run the selection or the statement under the cursor (⌘⏎)"
            aria-label="Run statement"
            className="rounded-r-none">
            <PlayIcon />
            <span className={TOOLBAR_LABEL}>Run Statement</span>
          </Button>
        )}
        {!isInFlight && (
          <Menu
            ariaLabel="More run options"
            align="right"
            trigger={({open, toggle, ref, menuId}) => (
              <Button
                ref={ref}
                variant="primary"
                onClick={toggle}
                disabled={!canRun}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-controls={open ? menuId : undefined}
                aria-label="More run options"
                title="More run options"
                className="rounded-l-none border-l border-white/25 px-2">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={cx('h-4 w-4 transition-transform', open && 'rotate-180')}
                  aria-hidden="true">
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </Button>
            )}
            items={[
              {
                kind: 'action',
                label: 'Run Query Tab',
                icon: (
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className="h-4 w-4"
                    aria-hidden="true">
                    <path d="M5 4l8 8-8 8" />
                    <path d="M14 20h6" />
                  </svg>
                ),
                onSelect: () => runScript('script-single')
              },
              {
                kind: 'action',
                label: 'Run Multiple Queries',
                icon: (
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className="h-4 w-4"
                    aria-hidden="true">
                    <path d="M4 4l6 8-6 8" />
                    <rect
                      x="13"
                      y="5"
                      width="7"
                      height="5"
                      rx="1"
                    />
                    <rect
                      x="13"
                      y="14"
                      width="7"
                      height="5"
                      rx="1"
                    />
                  </svg>
                ),
                onSelect: () => runScript('script-tabs')
              }
            ]}
          />
        )}
      </div>
    </div>
  );
}
