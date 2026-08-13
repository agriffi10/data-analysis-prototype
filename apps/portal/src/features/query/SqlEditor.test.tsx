import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render} from '@testing-library/react';
import type {GlueTableSummary} from '../catalog/catalog.types';

// Exercise the editor's completion-provider wiring without the real Monaco
// runtime (no worker, no DOM editor). The mocks below stand in for the three
// modules SqlEditor imports; the Editor mock invokes onMount synchronously
// with a fake editor + the mocked monaco namespace.

const h = vi.hoisted(() => {
  const registerCompletionItemProvider = vi.fn<(language: string, provider: unknown) => {dispose: () => void}>(() => ({
    dispose: vi.fn()
  }));
  // SPEC-150 FR-010. These must be DISTINCT and NON-ZERO. The mock previously
  // supplied `{CtrlCmd: 2048}` alone, so `m.KeyMod.Shift` and `m.KeyMod.Alt` were
  // both `undefined`, coerced to 0 by `|`, and all three run scopes registered the
  // identical binding 2051 — dropping one, or swapping two, passed green. The real
  // values are Monaco's own (KeyMod.CtrlCmd = 1<<11, Shift = 1<<10, Alt = 1<<9).
  const monacoMock = {
    editor: {defineTheme: vi.fn()},
    languages: {
      registerCompletionItemProvider,
      CompletionItemKind: {Field: 3, Struct: 5, Interface: 7}
    },
    KeyMod: {CtrlCmd: 2048, Shift: 1024, Alt: 512},
    KeyCode: {Enter: 3}
  };
  // The receiving spy was created inline and discarded, so no registration could be
  // asserted at all. Hoisted here, it survives the mount.
  const addCommand = vi.fn<(keybinding: number, handler: () => void) => void>();
  return {registerCompletionItemProvider, addCommand, monacoMock};
});

vi.mock('monaco-editor/esm/vs/editor/editor.worker?worker', () => ({default: class {}}));
vi.mock('monaco-editor', () => h.monacoMock);
vi.mock('@monaco-editor/react', () => ({
  loader: {config: vi.fn()},
  default: ({onMount}: {onMount: (editor: unknown, m: unknown) => void}) => {
    onMount({addCommand: h.addCommand}, h.monacoMock);
    return null;
  }
}));

const {KeyMod, KeyCode} = h.monacoMock;

// Named in SPEC-078's vocabulary, so the assertions read as the spec's contract
// rather than as the implementation's prop names.
const BINDINGS = {
  /** ⌘⏎ — Run Statement. */
  runStatement: KeyMod.CtrlCmd | KeyCode.Enter,
  /** ⌘⇧⏎ — Run Script → single result. */
  runScriptSingleResult: KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.Enter,
  /** ⌘⌥⏎ — Run Script → tab per statement. */
  runScriptTabPerStatement: KeyMod.CtrlCmd | KeyMod.Alt | KeyCode.Enter
};

// Imported after the mocks are declared (vi.mock is hoisted regardless).
import {SqlEditor} from './SqlEditor';

const orders: GlueTableSummary = {
  name: 'orders',
  tableType: 'EXTERNAL_TABLE',
  columns: [{name: 'id', type: 'bigint'}]
};

beforeEach(() => {
  h.registerCompletionItemProvider.mockClear();
  h.addCommand.mockClear();
});
afterEach(cleanup);

// SPEC-150 FR-010 / SPEC-078 FR-005. These are the primary way users run a query,
// and until now nothing asserted them: with `Shift`/`Alt` missing from the mock all
// three composed to the same number, and the `addCommand` spy was thrown away at the
// mount. Dropping a binding or swapping two scopes passed green.
describe('run-scope keybindings', () => {
  /** The handler Monaco was given for `keybinding`, or undefined if none was. */
  function handlerFor(keybinding: number): (() => void) | undefined {
    return h.addCommand.mock.calls.find(([binding]) => binding === keybinding)?.[1];
  }

  it('registers exactly three commands, under three distinct keybindings', () => {
    render(
      <SqlEditor
        value=""
        onChange={() => {}}
      />
    );

    expect(h.addCommand).toHaveBeenCalledTimes(3);
    const registered = h.addCommand.mock.calls.map(([binding]) => binding);
    expect(new Set(registered).size).toBe(3);
    expect(new Set(registered)).toEqual(
      new Set([BINDINGS.runStatement, BINDINGS.runScriptSingleResult, BINDINGS.runScriptTabPerStatement])
    );
  });

  it.each([
    {scope: 'Run Statement', binding: BINDINGS.runStatement, prop: 'onRun'},
    {scope: 'Run Script → single result', binding: BINDINGS.runScriptSingleResult, prop: 'onRunScriptSingle'},
    {scope: 'Run Script → tab per statement', binding: BINDINGS.runScriptTabPerStatement, prop: 'onRunScriptTabs'}
  ] as const)('$scope invokes $prop and no other handler', ({binding, prop}) => {
    const handlers = {onRun: vi.fn(), onRunScriptSingle: vi.fn(), onRunScriptTabs: vi.fn()};
    render(
      <SqlEditor
        value=""
        onChange={() => {}}
        {...handlers}
      />
    );

    handlerFor(binding)?.();

    // Asserting the OTHERS did not fire is what makes a swapped registration fail —
    // "the right one was called" alone passes when two scopes share a binding.
    expect(handlers[prop]).toHaveBeenCalledOnce();
    for (const [name, spy] of Object.entries(handlers)) {
      if (name !== prop) expect(spy).not.toHaveBeenCalled();
    }
  });

  it('does not throw when a scope has no handler wired (every prop is optional)', () => {
    render(
      <SqlEditor
        value=""
        onChange={() => {}}
      />
    );

    expect(() => handlerFor(BINDINGS.runScriptTabPerStatement)?.()).not.toThrow();
  });
});

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
