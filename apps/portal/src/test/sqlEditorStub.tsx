import {forwardRef, useImperativeHandle, useRef} from 'react';
import {vi} from 'vitest';

/**
 * The query workspace suites' stand-in for the Monaco editor — the sanctioned heavy-child
 * exception: Monaco needs a real DOM editor and workers, which jsdom has neither of. A
 * textarea drives value/onChange, forwards the selection handle so statement-resolution
 * tests can position a cursor, and exposes each run scope as a button so an unwired scope is
 * an absent button rather than a dead one.
 *
 * @example
 * vi.mock('./SqlEditor', () => import('../../test/sqlEditorStub'));
 */
/** Monaco's re-measure after a pane resize; one spy shared by the stub and the cases that assert on it. */
export const monacoLayout = vi.fn();

type MockProps = {
  value: string;
  onChange: (v: string) => void;
  onRun?: () => void;
  onRunScriptSingle?: () => void;
  onRunScriptTabs?: () => void;
};
export const SqlEditor = forwardRef<import('../features/query/SqlEditor').SqlEditorHandle, MockProps>(
  function MockSqlEditor({value, onChange, onRun, onRunScriptSingle, onRunScriptTabs}, ref) {
    const taRef = useRef<HTMLTextAreaElement>(null);
    useImperativeHandle(ref, () => ({
      focus: () => taRef.current?.focus(),
      layout: monacoLayout,
      getSelectionRange: () => {
        const ta = taRef.current;
        if (!ta || ta.selectionStart === ta.selectionEnd) return null;
        return {start: ta.selectionStart, end: ta.selectionEnd};
      },
      getCursorOffset: () => taRef.current?.selectionStart ?? 0
    }));
    return (
      <>
        <textarea
          ref={taRef}
          aria-label="SQL editor"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {/* Named in the editor's own run-scope vocabulary. Present only when the prop is wired, so
            an unwired scope is an absent button rather than a dead one. */}
        {onRun && <button onClick={onRun}>editor: Run Statement</button>}
        {onRunScriptSingle && <button onClick={onRunScriptSingle}>editor: Run Script → single result</button>}
        {onRunScriptTabs && <button onClick={onRunScriptTabs}>editor: Run Script → tab per statement</button>}
      </>
    );
  }
);
