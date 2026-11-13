import {useEffect} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, render} from '@testing-library/react';
import type {GlueTableSummary} from '../catalog/catalog.types';
import {CONTRAST_PAIRS, PALETTE} from '../../lib/palette';
import {resetThemeForTest, setThemePreference} from '../../lib/useTheme';

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
  // The per-tab models, by the path each is keyed under; `Uri.parse` hands the path straight back.
  const models = new Map<string, {dispose: () => void}>();
  const monacoMock = {
    editor: {defineTheme: vi.fn(), getModel: (uri: string) => models.get(uri) ?? null},
    Uri: {parse: (path: string) => path},
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
  // What the editor was RENDERED with, and how many times it was created. A theme switch has
  // to change the first and leave the second alone: `@monaco-editor/react` applies a changed
  // `theme` through `editor.setTheme` in an effect, so a remount would be a regression that
  // costs the user their buffer.
  const rendered: {theme?: string; value?: string; path?: string; saveViewState?: boolean}[] = [];
  const created = vi.fn();
  return {registerCompletionItemProvider, addCommand, monacoMock, models, rendered, created};
});

vi.mock('monaco-editor', () => h.monacoMock);
vi.mock('@monaco-editor/react', () => ({
  loader: {config: vi.fn()},
  default: ({
    onMount,
    beforeMount,
    theme,
    value,
    path,
    saveViewState
  }: {
    onMount: (editor: unknown, m: unknown) => void;
    beforeMount?: (m: unknown) => void;
    theme?: string;
    value?: string;
    path?: string;
    saveViewState?: boolean;
  }) => {
    h.rendered.push({theme, value, path, saveViewState});
    onMount({addCommand: h.addCommand, getModel: () => null}, h.monacoMock);
    return <MonacoStub onCreate={() => beforeMount?.(h.monacoMock)} />;
  }
}));

/** Stands in for the editor instance, so a REMOUNT is observable rather than inferred. */
function MonacoStub({onCreate}: {onCreate: () => void}) {
  useEffect(() => {
    // `beforeMount` runs once for the editor's lifetime in the real component too, which is
    // why both themes have to be defined there rather than lazily on a switch.
    onCreate();
    h.created();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

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

/** A workspace with a single tab, for the cases that are not about tabs. */
const ONE_TAB = {tabId: 'a', tabIds: ['a']} as const;

beforeEach(() => {
  h.registerCompletionItemProvider.mockClear();
  h.addCommand.mockClear();
  h.monacoMock.editor.defineTheme.mockClear();
  h.created.mockClear();
  h.rendered.length = 0;
  h.models.clear();
  resetThemeForTest();
});
afterEach(cleanup);

describe('each query tab keeps its own buffer', () => {
  it('edits each tab in a model of its own, so Undo after a switch cannot reach the other tab', () => {
    const {rerender} = render(
      <SqlEditor
        tabId="a"
        tabIds={['a', 'b']}
        value="select 'a'"
        onChange={() => {}}
      />
    );

    rerender(
      <SqlEditor
        tabId="b"
        tabIds={['a', 'b']}
        value="select 'b'"
        onChange={() => {}}
      />
    );

    // One shared model took the switch as an edit onto its own undo stack.
    expect(h.rendered[0]?.path).toBe('query-tab-a.sql');
    expect(h.rendered.at(-1)).toMatchObject({path: 'query-tab-b.sql', saveViewState: true});
  });

  it('disposes a closed tab’s model and keeps the open ones', () => {
    const modelA = {dispose: vi.fn()};
    const modelB = {dispose: vi.fn()};
    h.models.set('query-tab-a.sql', modelA);
    h.models.set('query-tab-b.sql', modelB);
    const {rerender} = render(
      <SqlEditor
        tabId="a"
        tabIds={['a', 'b']}
        value=""
        onChange={() => {}}
      />
    );

    rerender(
      <SqlEditor
        tabId="a"
        tabIds={['a']}
        value=""
        onChange={() => {}}
      />
    );

    expect(modelB.dispose).toHaveBeenCalledTimes(1);
    expect(modelA.dispose).not.toHaveBeenCalled();
  });
});

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
        {...ONE_TAB}
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
        {...ONE_TAB}
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
        {...ONE_TAB}
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
        {...ONE_TAB}
        value=""
        onChange={() => {}}
      />
    );
    // Re-rendering (e.g. a tab switch changing value) must not re-register.
    rerender(
      <SqlEditor
        {...ONE_TAB}
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
    const props = {
      ...ONE_TAB,
      value: '',
      onChange: () => {},
      completionSchemas: [{database: 'alice', tables: [orders]}]
    };

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
    // The provider reads the statement at the cursor, so the stub answers an empty buffer with the
    // cursor at its start. This test is about the WIRING — one live provider, latest schemas.
    const model = {
      getValue: () => '',
      getOffsetAt: () => 0,
      getPositionAt: () => ({lineNumber: 1, column: 1}),
      getWordUntilPosition: () => ({word: '', startColumn: 1, endColumn: 1})
    };
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
        {...ONE_TAB}
        value=""
        onChange={() => {}}
      />
    );
    const b = render(
      <SqlEditor
        {...ONE_TAB}
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
        {...ONE_TAB}
        value=""
        onChange={() => {}}
        completionSchemas={undefined}
      />
    );
    const provider = h.registerCompletionItemProvider.mock.calls[0][1] as {
      provideCompletionItems: (model: unknown, pos: unknown) => {suggestions: Array<{label: string}>};
    };
    // The provider reads the statement at the cursor, so the stub answers an empty buffer with the
    // cursor at its start. This test is about the WIRING — one live provider, latest schemas.
    const model = {
      getValue: () => '',
      getOffsetAt: () => 0,
      getPositionAt: () => ({lineNumber: 1, column: 1}),
      getWordUntilPosition: () => ({word: '', startColumn: 1, endColumn: 1})
    };
    const pos = {lineNumber: 1, column: 1};

    expect(provider.provideCompletionItems(model, pos).suggestions).toEqual([]);

    rerender(
      <SqlEditor
        {...ONE_TAB}
        value=""
        onChange={() => {}}
        completionSchemas={[{database: 'alice', tables: [orders]}]}
      />
    );
    expect(provider.provideCompletionItems(model, pos).suggestions.map((s) => s.label)).toEqual(['alice.orders', 'id']);
  });
});

describe('the editor follows the app theme', () => {
  afterEach(resetThemeForTest);

  it('defines both themes up front, from the palette rather than from its own copy', () => {
    render(
      <SqlEditor
        {...ONE_TAB}
        value=""
        onChange={() => {}}
      />
    );

    const defined = h.monacoMock.editor.defineTheme.mock.calls as [string, MonacoTheme][];
    expect(defined.map(([name]) => name)).toEqual(['file-portal-sql', 'file-portal-sql-dark']);

    // Every colour traceable to a token, so the fork that kept the pre-fix hexes for strings,
    // numbers and comments long after `index.css` had darkened them cannot come back.
    for (const [name, theme] of defined) {
      const palette = PALETTE[name.endsWith('-dark') ? 'dark' : 'light'];
      const values = new Set(Object.values(palette).map((hex) => hex.slice(1)));
      for (const rule of theme.rules) expect(values, `${name} ${rule.token}`).toContain(rule.foreground);
      expect(theme.colors['editor.background']).toBe(palette.surface);
      expect(theme.colors['editorLineNumber.foreground']).toBe(palette['text-3']);
      expect(theme.colors['editorGutter.background']).toBe(palette['surface-2']);
    }
  });

  it('uses only tokens the contrast harness measures against the editor background', () => {
    // FR-006 AC5. Without this the rules are merely "some palette value": pointing `comment` at
    // `border-2` renders SQL comments at ~1.1:1 on white and every other test here stays green,
    // because the harness measures only the pairings it is DECLARED, and a decorative token is
    // declared against no floor at all.
    //
    // Read back out of what Monaco was GIVEN rather than from the module's own map, so this
    // needs no internal exported for it and cannot drift from what the editor actually renders.
    render(
      <SqlEditor
        {...ONE_TAB}
        value=""
        onChange={() => {}}
      />
    );
    const paired: Set<string> = new Set(
      CONTRAST_PAIRS.flatMap((pair) => (pair.kind === 'token' && pair.bg === 'surface' ? [pair.fg] : []))
    );

    for (const [name, theme] of h.monacoMock.editor.defineTheme.mock.calls as [string, MonacoTheme][]) {
      // A loop over an empty rule set passes by finding nothing to disagree with — the same shape
      // the stylesheet check guards with its own size assertion.
      expect(theme.rules.length, `${name} defines no syntax rules at all`).toBeGreaterThan(5);
      const palette = PALETTE[name.endsWith('-dark') ? 'dark' : 'light'];
      for (const rule of theme.rules) {
        // One value can belong to more than one token (light `accent-text` and `accent-hover`
        // are the same hex), so any token carrying it may be the one that is measured.
        const tokens = Object.entries(palette).filter(([, hex]) => hex.slice(1) === rule.foreground);
        expect(tokens.length, `${name} ${rule.token}: #${rule.foreground} is in no token`).toBeGreaterThan(0);
        expect(
          tokens.some(([token]) => paired.has(token)),
          `${name} ${rule.token} (${tokens.map(([t]) => t).join('/')}) is measured against no editor background`
        ).toBe(true);
      }
    }
  });

  it('switches theme without re-creating the editor or losing the buffer', async () => {
    // Driven through the store's own setter, which is what the menu item calls — the control
    // itself is covered where it lives, and reaching for it here would import a component this
    // test is not about.
    render(
      <SqlEditor
        {...ONE_TAB}
        value="select 1"
        onChange={() => {}}
      />
    );

    expect(h.rendered.at(-1)?.theme).toBe('file-portal-sql');
    expect(h.created).toHaveBeenCalledTimes(1);

    await act(async () => setThemePreference('dark'));

    expect(h.rendered.at(-1)?.theme).toBe('file-portal-sql-dark');
    expect(h.rendered.at(-1)?.value).toBe('select 1');
    // A COUNT, because "it was created" cannot see a second creation — and a second creation
    // is exactly what would drop the buffer, the cursor and the scroll position.
    expect(h.created).toHaveBeenCalledTimes(1);
  });
});

type MonacoTheme = {
  rules: {token: string; foreground: string}[];
  colors: Record<string, string>;
};
