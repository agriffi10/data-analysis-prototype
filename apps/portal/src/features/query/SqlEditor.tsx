import {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
import Editor, {loader, type OnMount} from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import {createSqlCompletionProvider} from './sqlCompletions';
import type {GlueTableSummary} from './query.types';

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

// Schema-aware completions. The provider is registered exactly once for the
// `sql` language (module-guarded), not per editor mount — re-mounting or
// switching tabs must not stack duplicate providers. It reads the active
// database's schema through this module-level ref, so it always sees the
// latest tables without rebinding. Disposed when the editor unmounts.
const completionSchemaRef: {current: GlueTableSummary[] | undefined} = {current: undefined};
let completionDisposable: monaco.IDisposable | null = null;

function registerSqlCompletionsOnce(m: typeof monaco) {
  if (completionDisposable) return;
  completionDisposable = m.languages.registerCompletionItemProvider(
    'sql',
    createSqlCompletionProvider(m, completionSchemaRef)
  );
}

export type SqlEditorHandle = {
  /** Inserts text at the current cursor/selection (schema-browser click-to-insert); refocuses the editor. */
  insertAtCursor: (text: string) => void;
  /** Focuses the editor (used after re-opening a history entry). */
  focus: () => void;
};

type SqlEditorProps = {
  value: string;
  onChange: (value: string) => void;
  /** ⌘/Ctrl+Enter in the editor triggers Run; optional so the shell can mount the editor before the run handler is wired. */
  onRun?: () => void;
  /**
   * The active database's tables/views feeding the schema-aware completion
   * provider. Undefined while no schema is loaded — completions then fall
   * back to Monaco's built-in keywords only.
   */
  completionTables?: GlueTableSummary[];
};

/**
 * Monaco SQL editor. Forwards a ref exposing insertAtCursor/focus; React.lazy
 * forwards the ref through to this inner forwardRef component once the chunk
 * loads.
 */
export const SqlEditor = forwardRef<SqlEditorHandle, SqlEditorProps>(function SqlEditor(
  {value, onChange, onRun, completionTables},
  ref
) {
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  // Keep the latest onRun without rebinding the Monaco command each render.
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;
  // Feed the latest active-database schema to the (singleton) completion
  // provider each render, mirroring the onRunRef pattern.
  completionSchemaRef.current = completionTables;

  // Dispose the singleton completion provider when the editor tears down.
  useEffect(() => {
    return () => {
      completionDisposable?.dispose();
      completionDisposable = null;
    };
  }, []);

  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const editor = editorRef.current;
      if (!editor) return;
      const selection = editor.getSelection();
      if (!selection) return;
      editor.executeEdits('schema-insert', [{range: selection, text, forceMoveMarkers: true}]);
      editor.focus();
    },
    focus() {
      editorRef.current?.focus();
    }
  }));

  const handleMount: OnMount = (editor, m) => {
    editorRef.current = editor;
    editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.Enter, () => {
      onRunRef.current?.();
    });
    registerSqlCompletionsOnce(m);
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
