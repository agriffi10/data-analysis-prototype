import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render} from '@testing-library/react';
import type {GlueTableSummary} from './query.types';

// Exercise the editor's completion-provider wiring without the real Monaco
// runtime (no worker, no DOM editor). The mocks below stand in for the three
// modules SqlEditor imports; the Editor mock invokes onMount synchronously
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

  it('survives an unmount/remount (tab switch / StrictMode) — one active provider, still functional [SPEC-084]', () => {
    const disposable = {dispose: vi.fn()};
    h.registerCompletionItemProvider.mockReturnValue(disposable);
    const props = {value: '', onChange: () => {}, completionSchemas: [{database: 'alice', tables: [orders]}]};

    // Mount → unmount (switch away) → remount (switch back).
    render(<SqlEditor {...props} />).unmount();
    render(<SqlEditor {...props} />);

    // Exactly one provider is active (registrations minus disposals), so autocomplete
    // is neither dead nor duplicated after the remount.
    const active = h.registerCompletionItemProvider.mock.calls.length - disposable.dispose.mock.calls.length;
    expect(active).toBe(1);

    // The currently-registered provider still produces schema-aware suggestions.
    const provider = h.registerCompletionItemProvider.mock.calls.at(-1)![1] as {
      provideCompletionItems: (model: unknown, pos: unknown) => {suggestions: Array<{label: string}>};
    };
    const model = {getWordUntilPosition: () => ({startColumn: 1, endColumn: 1})};
    expect(provider.provideCompletionItems(model, {lineNumber: 1, column: 1}).suggestions.map((s) => s.label)).toEqual([
      'alice.orders',
      'id'
    ]);
  });

  it('keeps the shared provider alive while another editor instance is still mounted [SPEC-084]', () => {
    const disposable = {dispose: vi.fn()};
    h.registerCompletionItemProvider.mockReturnValue(disposable);

    const a = render(
      <SqlEditor
        value=""
        onChange={() => {}}
      />
    );
    const b = render(
      <SqlEditor
        value=""
        onChange={() => {}}
      />
    );
    // Both share ONE provider on the language global (no duplicate registration).
    expect(h.registerCompletionItemProvider).toHaveBeenCalledTimes(1);

    a.unmount(); // one instance gone, one still mounted
    expect(disposable.dispose).not.toHaveBeenCalled(); // ref-count > 0 → NOT disposed

    b.unmount(); // last instance gone
    expect(disposable.dispose).toHaveBeenCalledTimes(1);
  });

  it('feeds the provider the latest completionSchemas via the shared ref', () => {
    const {rerender} = render(
      <SqlEditor
        value=""
        onChange={() => {}}
        completionSchemas={undefined}
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
        completionSchemas={[{database: 'alice', tables: [orders]}]}
      />
    );
    expect(provider.provideCompletionItems(model, pos).suggestions.map((s) => s.label)).toEqual(['alice.orders', 'id']);
  });
});
