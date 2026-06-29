import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render} from '@testing-library/react';
import type {GlueTableSummary} from './query.types';

// SPEC-065: exercise the editor's completion-provider wiring without the real
// Monaco runtime (no worker, no DOM editor). The mocks below stand in for the
// three modules SqlEditor imports; the Editor mock invokes onMount synchronously
// with a fake editor + the mocked monaco namespace.

const h = vi.hoisted(() => {
  const registerCompletionItemProvider = vi.fn<(language: string, provider: unknown) => {dispose: () => void}>(() => ({
    dispose: vi.fn()
  }));
  const monacoMock = {
    editor: {defineTheme: vi.fn()},
    languages: {
      registerCompletionItemProvider,
      CompletionItemKind: {Field: 3, Struct: 5, Interface: 7}
    },
    KeyMod: {CtrlCmd: 2048},
    KeyCode: {Enter: 3}
  };
  return {registerCompletionItemProvider, monacoMock};
});

vi.mock('monaco-editor/esm/vs/editor/editor.worker?worker', () => ({default: class {}}));
vi.mock('monaco-editor', () => h.monacoMock);
vi.mock('@monaco-editor/react', () => ({
  loader: {config: vi.fn()},
  default: ({onMount}: {onMount: (editor: unknown, m: unknown) => void}) => {
    onMount({addCommand: vi.fn()}, h.monacoMock);
    return null;
  }
}));

// Imported after the mocks are declared (vi.mock is hoisted regardless).
import {SqlEditor} from './SqlEditor';

const orders: GlueTableSummary = {
  name: 'orders',
  tableType: 'EXTERNAL_TABLE',
  columns: [{name: 'id', type: 'bigint'}]
};

beforeEach(() => {
  h.registerCompletionItemProvider.mockClear();
});
afterEach(cleanup);

describe('SqlEditor completion-provider wiring', () => {
  it('registers the sql completion provider exactly once and disposes on unmount', () => {
    const disposable = {dispose: vi.fn()};
    h.registerCompletionItemProvider.mockReturnValue(disposable);

    const {rerender, unmount} = render(
      <SqlEditor
        value=""
        onChange={() => {}}
      />
    );
    // Re-rendering (e.g. a tab switch changing value) must not re-register.
    rerender(
      <SqlEditor
        value="select 1"
        onChange={() => {}}
      />
    );
    expect(h.registerCompletionItemProvider).toHaveBeenCalledTimes(1);
    expect(h.registerCompletionItemProvider.mock.calls[0][0]).toBe('sql');

    unmount();
    expect(disposable.dispose).toHaveBeenCalledTimes(1);
  });

  it('feeds the provider the latest completionTables via the shared ref', () => {
    const {rerender} = render(
      <SqlEditor
        value=""
        onChange={() => {}}
        completionTables={undefined}
      />
    );
    const provider = h.registerCompletionItemProvider.mock.calls[0][1] as {
      provideCompletionItems: (model: unknown, pos: unknown) => {suggestions: Array<{label: string}>};
    };
    const model = {getWordUntilPosition: () => ({startColumn: 1, endColumn: 1})};
    const pos = {lineNumber: 1, column: 1};

    expect(provider.provideCompletionItems(model, pos).suggestions).toEqual([]);

    rerender(
      <SqlEditor
        value=""
        onChange={() => {}}
        completionTables={[orders]}
      />
    );
    expect(provider.provideCompletionItems(model, pos).suggestions.map((s) => s.label)).toEqual(['orders', 'id']);
  });
});
