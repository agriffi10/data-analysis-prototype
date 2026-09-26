import {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
import Editor, {loader, type OnMount} from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/editor/editor.worker?worker';
import {PALETTE, type ColorToken} from '../../lib/palette';
import type {EffectiveTheme} from '../../lib/theme.types';
import {useTheme} from '../../lib/useTheme';
import {createSqlCompletionProvider} from './sqlCompletions';
import type {DatabaseSchema} from '../catalog/catalog.types';

// Self-host Monaco: no CDN/runtime external. Vite builds the editor worker
// (?worker), and we point @monaco-editor/react's loader at the bundled
// monaco-editor instead of its default CDN. SQL needs only the core editor
// worker (no language-service worker). This whole module is lazy-loaded by
// QueryWorkspace, so monaco lands in its own async chunk — never in the Files
// or landing bundles.
//
// The worker path is `monaco-editor/editor/…`, NOT the `monaco-editor/esm/vs/editor/…`
// that every pre-0.56 example shows. monaco-editor 0.56.0 added an `exports` map
// (`"./*": "./esm/vs/*.js"`) that roots every subpath at `esm/vs/` — so the old deep
// path now resolves to `esm/vs/esm/vs/…` and fails at build time.
self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker();
  }
};
loader.config({monaco});

// Monaco's syntax colours, as design tokens. Monaco cannot read a CSS variable, so it is
// given the VALUES — which is why every one is named here rather than written out: a private
// copy of the palette is exactly what this used to be, and it kept the pre-fix hexes for
// strings, numbers and comments long after `index.css` had darkened them.
const SYNTAX: Record<string, ColorToken> = {
  keyword: 'accent-text',
  'keyword.sql': 'accent-text',
  'operator.sql': 'text-2',
  string: 'success',
  'string.sql': 'success',
  number: 'warning',
  comment: 'text-3',
  'predefined.sql': 'syntax-fn'
};

const BOLD = new Set(['keyword', 'keyword.sql']);
const ITALIC = new Set(['comment']);

const THEMES: Record<EffectiveTheme, string> = {
  light: 'file-portal-sql',
  dark: 'file-portal-sql-dark'
};

/**
 * Register both editor themes, from the same expression evaluated twice.
 *
 * Both, not the current one: `beforeMount` runs once for the editor's lifetime, so a theme
 * defined lazily on a switch would not exist when the switch asked for it.
 *
 * @param m - The Monaco namespace the editor is mounting against.
 * @returns Nothing.
 */
function defineThemes(m: typeof monaco) {
  for (const theme of ['light', 'dark'] as const) {
    const palette = PALETTE[theme];
    m.editor.defineTheme(THEMES[theme], {
      base: theme === 'dark' ? 'vs-dark' : 'vs',
      inherit: true,
      rules: Object.entries(SYNTAX).map(([token, colour]) => ({
        token,
        foreground: palette[colour].slice(1),
        ...(BOLD.has(token) ? {fontStyle: 'bold'} : {}),
        ...(ITALIC.has(token) ? {fontStyle: 'italic'} : {})
      })),
      colors: {
        'editor.background': palette.surface,
        'editorLineNumber.foreground': palette['text-3'],
        'editorGutter.background': palette['surface-2']
      }
    });
  }
}

// Schema-aware completions registered on Monaco's `sql` language GLOBAL (shared by
// every editor of that language), ref-counted by mounted SqlEditor instances: it's
// registered when the first editor mounts and disposed only when the LAST unmounts.
// Tying the lifetime to the ref-count — not a single component instance's unmount —
// keeps autocomplete alive across query-tab switches and StrictMode's dev
// mount→unmount→remount: no disposed-then-never-re-registered gap, and no
// stacked duplicate providers. The provider reads the accessible databases' schemas
// through this module-level ref, so it always sees the latest tables without rebinding.
const completionSchemaRef: {current: DatabaseSchema[] | undefined} = {current: undefined};
let completionDisposable: monaco.IDisposable | null = null;
let completionRefCount = 0;

function acquireSqlCompletions(m: typeof monaco) {
  completionRefCount += 1;
  if (!completionDisposable) {
    completionDisposable = m.languages.registerCompletionItemProvider(
      'sql',
      createSqlCompletionProvider(m, completionSchemaRef)
    );
  }
}

function releaseSqlCompletions() {
  completionRefCount = Math.max(0, completionRefCount - 1);
  if (completionRefCount === 0 && completionDisposable) {
    completionDisposable.dispose();
    completionDisposable = null;
  }
}

/**
 * The Monaco model path a query tab's buffer lives under — one model per tab.
 *
 * One model per tab is what gives each tab its own undo stack. With a single shared model a tab
 * switch was applied as an edit, so Undo after switching wrote the previous tab's SQL into this one.
 *
 * @param tabId - The query tab's id.
 * @returns The path `@monaco-editor/react` keys the tab's model by.
 */
function tabModelPath(tabId: string): string {
  return `query-tab-${tabId}.sql`;
}

/**
 * Disposes a query tab's model, unless the editor is still showing it.
 *
 * The one skipped is never leaked: `@monaco-editor/react` disposes the model it is showing when
 * the editor unmounts.
 *
 * @param tabId - The query tab whose model to dispose.
 * @param shown - The model the editor currently shows, if any.
 * @returns Nothing.
 */
function disposeTabModel(tabId: string, shown: monaco.editor.ITextModel | null | undefined): void {
  const model = monaco.editor.getModel(monaco.Uri.parse(tabModelPath(tabId)));
  if (model && model !== shown) model.dispose();
}

export type SqlEditorHandle = {
  /** Focuses the editor (used after re-opening a history entry / a table action). */
  focus: () => void;
  /** Re-measures the editor against its container, after the pane is resized. */
  layout: () => void;
  /** The selection as buffer offsets, or null when empty. */
  getSelectionRange: () => {start: number; end: number} | null;
  /** The cursor position as a buffer offset. */
  getCursorOffset: () => number;
};

type SqlEditorProps = {
  /** The tab whose buffer `value` is; each tab edits its own model, with its own undo history. */
  tabId: string;
  /** Every open tab, so a closed tab's model is disposed rather than kept for the session. */
  tabIds: readonly string[];
  value: string;
  onChange: (value: string) => void;
  /** ⌘/Ctrl+Enter in the editor triggers Run Statement; optional so the shell can mount the editor before the run handler is wired. */
  onRun?: () => void;
  /** ⌘/Ctrl+Shift+Enter — Run Query Tab: every statement, single result. */
  onRunScriptSingle?: () => void;
  /** ⌘/Ctrl+Alt+Enter — Run Multiple Queries: every statement, one result tab each. */
  onRunScriptTabs?: () => void;
  /**
   * The accessible databases' schemas feeding the schema-aware completion
   * provider — fully-qualified `database.table` suggestions across
   * every accessible database. Undefined/empty while no schema is loaded —
   * completions then fall back to Monaco's built-in keywords only.
   */
  completionSchemas?: DatabaseSchema[];
};

/**
 * Monaco SQL editor. Forwards a ref exposing focus; React.lazy
 * forwards the ref through to this inner forwardRef component once the chunk
 * loads.
 */
export const SqlEditor = forwardRef<SqlEditorHandle, SqlEditorProps>(function SqlEditor(
  {tabId, tabIds, value, onChange, onRun, onRunScriptSingle, onRunScriptTabs, completionSchemas},
  ref
) {
  // The `theme` prop is a THEME NAME, and @monaco-editor/react applies a change to it through
  // `editor.setTheme` in an effect — no new model, no new editor — so the buffer, the cursor
  // and the scroll position survive a switch.
  const {effective} = useTheme();
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  // Keep the latest run handlers without rebinding the Monaco commands each render.
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;
  const onRunScriptSingleRef = useRef(onRunScriptSingle);
  onRunScriptSingleRef.current = onRunScriptSingle;
  const onRunScriptTabsRef = useRef(onRunScriptTabs);
  onRunScriptTabsRef.current = onRunScriptTabs;
  // Feed the latest accessible-database schemas to the (singleton) completion
  // provider each render, mirroring the onRunRef pattern.
  completionSchemaRef.current = completionSchemas;

  // Register the shared completion provider for this editor's lifetime, ref-counted
  // so it survives tab-switch/StrictMode unmount→remount and is disposed only when the
  // last editor unmounts. Uses the module `monaco` import (same instance as onMount's
  // `m`), so registration is decoupled from Monaco's editor-creation timing.
  useEffect(() => {
    acquireSqlCompletions(monaco);
    return () => releaseSqlCompletions();
  }, []);

  // A closed tab's model goes with it, and every tab's model goes with the editor: the tabs are
  // the record of each buffer, so a model outliving the editor could only ever be a stale copy.
  const knownTabIdsRef = useRef(tabIds);
  useEffect(() => {
    const open = new Set(tabIds);
    for (const id of knownTabIdsRef.current) {
      if (!open.has(id)) disposeTabModel(id, editorRef.current?.getModel());
    }
    knownTabIdsRef.current = tabIds;
  }, [tabIds]);
  useEffect(
    () => () => {
      for (const id of knownTabIdsRef.current) disposeTabModel(id, editorRef.current?.getModel());
    },
    []
  );

  useImperativeHandle(ref, () => ({
    focus() {
      editorRef.current?.focus();
    },
    layout() {
      editorRef.current?.layout();
    },
    getSelectionRange() {
      const editor = editorRef.current;
      const model = editor?.getModel();
      const selection = editor?.getSelection();
      if (!model || !selection || selection.isEmpty()) return null;
      return {
        start: model.getOffsetAt(selection.getStartPosition()),
        end: model.getOffsetAt(selection.getEndPosition())
      };
    },
    getCursorOffset() {
      const editor = editorRef.current;
      const model = editor?.getModel();
      const position = editor?.getPosition();
      return model && position ? model.getOffsetAt(position) : 0;
    }
  }));

  const handleMount: OnMount = (editor, m) => {
    editorRef.current = editor;
    editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.Enter, () => {
      onRunRef.current?.();
    });
    // The two whole-script scopes' shortcuts.
    editor.addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Shift | m.KeyCode.Enter, () => {
      onRunScriptSingleRef.current?.();
    });
    editor.addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Alt | m.KeyCode.Enter, () => {
      onRunScriptTabsRef.current?.();
    });
  };

  return (
    <Editor
      height="100%"
      defaultLanguage="sql"
      theme={THEMES[effective]}
      beforeMount={defineThemes}
      onMount={handleMount}
      path={tabModelPath(tabId)}
      saveViewState
      value={value}
      onChange={(v) => onChange(v ?? '')}
      options={{
        minimap: {enabled: false},
        fontSize: 13,
        lineNumbersMinChars: 3,
        scrollBeyondLastLine: false,
        padding: {top: 12, bottom: 12},
        renderLineHighlight: 'line',
        fontFamily: '"SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Consolas, monospace'
      }}
    />
  );
});
