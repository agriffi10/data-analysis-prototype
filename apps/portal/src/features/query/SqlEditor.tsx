import {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
import Editor, {loader, type OnMount} from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import {createSqlCompletionProvider, type DatabaseSchema} from './sqlCompletions';

// Self-host Monaco: no CDN/runtime external. Vite builds the editor worker
// (?worker), and we point @monaco-editor/react's loader at the bundled
// monaco-editor instead of its default CDN. SQL needs only the core editor
// worker (no language-service worker). This whole module is lazy-loaded by
// QueryWorkspace, so monaco lands in its own async chunk — never in the Files
// or landing bundles.
self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker();
  }
};
loader.config({monaco});

// Token theme mapped onto the design tokens: keywords accent, strings success,
// numbers warning, comments muted italic, functions violet.
const THEME = 'file-portal-sql';
function defineTheme(m: typeof monaco) {
  m.editor.defineTheme(THEME, {
    base: 'vs',
    inherit: true,
    rules: [
      {token: 'keyword', foreground: '4338ca', fontStyle: 'bold'},
      {token: 'keyword.sql', foreground: '4338ca', fontStyle: 'bold'},
      {token: 'operator.sql', foreground: '5b6573'},
      {token: 'string', foreground: '0f9d6e'},
      {token: 'string.sql', foreground: '0f9d6e'},
      {token: 'number', foreground: 'c2820a'},
      {token: 'comment', foreground: '8a93a2', fontStyle: 'italic'},
      {token: 'predefined.sql', foreground: '7c3aed'}
    ],
    colors: {
      'editor.background': '#ffffff',
      'editorLineNumber.foreground': '#8a93a2',
      'editorGutter.background': '#fafbfc'
    }
  });
}

// Schema-aware completions registered on Monaco's `sql` language GLOBAL (shared by
// every editor of that language), ref-counted by mounted SqlEditor instances: it's
// registered when the first editor mounts and disposed only when the LAST unmounts.
// Tying the lifetime to the ref-count — not a single component instance's unmount —
// keeps autocomplete alive across query-tab switches and StrictMode's dev
// mount→unmount→remount (SPEC-084): no disposed-then-never-re-registered gap, and no
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

export type SqlEditorHandle = {
  /** Focuses the editor (used after re-opening a history entry / a table action). */
  focus: () => void;
  /** The selection as buffer offsets, or null when empty (SPEC-078 FR-006). */
  getSelectionRange: () => {start: number; end: number} | null;
  /** The cursor position as a buffer offset (SPEC-078 FR-006). */
  getCursorOffset: () => number;
};

type SqlEditorProps = {
  value: string;
  onChange: (value: string) => void;
  /** ⌘/Ctrl+Enter in the editor triggers Run Statement; optional so the shell can mount the editor before the run handler is wired. */
  onRun?: () => void;
  /** ⌘/Ctrl+Shift+Enter — Run Script, single result (SPEC-078 FR-005). */
  onRunScriptSingle?: () => void;
  /** ⌘/Ctrl+Alt+Enter — Run Script, tab per statement (SPEC-078 FR-005). */
  onRunScriptTabs?: () => void;
  /**
   * The accessible databases' schemas feeding the schema-aware completion
   * provider (SPEC-077 — fully-qualified `database.table` suggestions across
   * every accessible database). Undefined/empty while no schema is loaded —
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
  {value, onChange, onRun, onRunScriptSingle, onRunScriptTabs, completionSchemas},
  ref
) {
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

  useImperativeHandle(ref, () => ({
    focus() {
      editorRef.current?.focus();
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
    // SPEC-078 FR-005: the two whole-script scopes' shortcuts.
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
      theme={THEME}
      beforeMount={defineTheme}
      onMount={handleMount}
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
