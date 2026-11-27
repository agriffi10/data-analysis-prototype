import {describe, expect, it} from 'vitest';
import {parser} from 'typescript-eslint';

/**
 * Holds `package.json`'s `sideEffects` list to the source it describes.
 *
 * The list tells the bundler that every module it does not name can be dropped wherever its exports
 * go unused. That is what keeps a feature's page out of the chunk every page loads when the shell
 * imports one hook through the feature's barrel, and it is a claim about every module: one that
 * does something as it is imported, and is not named, is dropped silently in a production build
 * while this suite, which shakes no tree, stays green.
 *
 * WHAT IT SEES, at module scope: a statement that is not an import, an export or a declaration; an
 * import made for its effects alone; a default export of a call; and a class with a static block or
 * a decorator.
 *
 * WHAT IT DOES NOT: code nested inside a declaration, such as an initializer
 * (`export const x = register()`), a static field or a call in a class's heritage. The corpus pins
 * each as silence so the limit is on record. This is a tripwire for the plain shapes, not a proof.
 *
 * ONE EXEMPTION, BY NAME: `Name.displayName = 'text'`, where the module declares `Name`. It is what
 * a `forwardRef` component needs, it goes with the module, and it is the only property so treated.
 * An earlier form reasoned about which bindings were the module's own and was walked around three
 * times, by an alias, an ambient declaration and a conditional; a rule that names one property has
 * nothing to walk around.
 *
 * AN ENTRY IS NECESSARY AND NOT SUFFICIENT. The bundler skips a barrel it has been told is free of
 * effects, and a named module re-exported through it is skipped with it (measured in a build). A
 * module's import-time code runs only when the module is imported for an export that is used, or by
 * a bare import from a module that is kept.
 */

/** The parts of a parsed statement this guard reads. */
type Node = {
  type: string;
  loc: {start: {line: number}};
  directive?: string;
  specifiers?: unknown[];
  source?: {value: string} | null;
  declaration?: Node | null;
  declarations?: {id: Node; init?: Node | null}[];
  declare?: boolean;
  id?: Node | null;
  name?: string;
  expression?: Node;
  left?: Node;
  right?: Node;
  object?: Node;
  property?: Node;
  decorators?: unknown[];
  body?: {body?: Node[]};
};

/** Statements that only bind or describe, and so do nothing as the module is imported. */
const DECLARATIONS = new Set([
  'VariableDeclaration',
  'FunctionDeclaration',
  'ClassDeclaration',
  'ExportNamedDeclaration',
  'ExportDefaultDeclaration',
  'ExportAllDeclaration',
  'TSTypeAliasDeclaration',
  'TSInterfaceDeclaration',
  'TSEnumDeclaration',
  'TSModuleDeclaration',
  'TSDeclareFunction',
  'EmptyStatement'
]);

/** A source's module-scope statements. */
function statements(path: string, source: string): Node[] {
  const parse = parser.parseForESLint as unknown as (text: string, options: object) => {ast: {body: Node[]}};
  return parse(source, {filePath: path, sourceType: 'module', loc: true, ecmaFeatures: {jsx: path.endsWith('.tsx')}})
    .ast.body;
}

/** What a statement declares, an exported declaration's included. */
const declaredBy = (statement: Node) => (statement.type.startsWith('Export') ? statement.declaration : statement);

/** The names a module declares at module scope, leaving out one it only describes (`declare const`). */
function declaredNames(body: Node[]): Set<string> {
  const names = new Set<string>();
  for (const statement of body) {
    const declared = declaredBy(statement);
    if (!declared || declared.declare) continue;
    if (declared.id?.name) names.add(declared.id.name);
    for (const declarator of declared.declarations ?? []) {
      if (declarator.id.name) names.add(declarator.id.name);
    }
  }
  return names;
}

/** Whether a statement is `Name.displayName = 'text'` for a name the module declares. */
function namesItself(statement: Node, declared: Set<string>): boolean {
  const assignment = statement.expression;
  if (assignment?.type !== 'AssignmentExpression' || assignment.left?.type !== 'MemberExpression') return false;
  const {object, property} = assignment.left;
  if (object?.type !== 'Identifier' || object.name === undefined || !declared.has(object.name)) return false;
  if (property?.type !== 'Identifier' || property.name !== 'displayName') return false;
  return assignment.right?.type === 'Literal';
}

/** What a default export may be without running anything: a name, a function or a class. Anything else is read as code. */
const INERT_DEFAULT_EXPORTS = new Set(['Identifier', 'FunctionDeclaration', 'ClassDeclaration']);

/** Whether a declaration runs code of its own as the module is imported, in a shape this guard reads. */
function actsAsDeclared(statement: Node): boolean {
  const declared = declaredBy(statement);
  if (statement.type === 'ExportDefaultDeclaration' && !INERT_DEFAULT_EXPORTS.has(declared?.type ?? '')) return true;
  if (declared?.type !== 'ClassDeclaration') return false;
  return (
    (declared.decorators ?? []).length > 0 ||
    (declared.body?.body ?? []).some((member) => member.type === 'StaticBlock')
  );
}

/** How this guard reads an entry, or null for a shape it does not model. */
function matcherOf(entry: string): ((path: string) => boolean) | null {
  const suffix = /^\*\*\/\*(\.[a-z]+)$/.exec(entry);
  if (suffix) return (path) => path.endsWith(suffix[1]);
  // The bundler reads an entry as a glob, so a path holding any glob character is not a literal one.
  const folder = /^\.\/([^*?[\]{}!]+\/)\*\*$/.exec(entry);
  if (folder) return (path) => path.startsWith(folder[1]);
  const exact = /^\.\/([^*?[\]{}!]+)$/.exec(entry);
  if (exact) return (path) => path === exact[1];
  return null;
}

/** The file a relative specifier names, among the files that exist. */
function resolve(importer: string, specifier: string, files: ReadonlySet<string>): string | null {
  const parts = importer.split('/').slice(0, -1);
  for (const part of specifier.split('/')) {
    if (part === '..') parts.pop();
    else if (part !== '.') parts.push(part);
  }
  const base = parts.join('/');
  return [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`].find((candidate) => files.has(candidate)) ?? null;
}

/** What one module does as it is imported: the lines that act, and the imports made for effect. */
type Scan = {effects: number[]; bare: {line: number; specifier: string}[]};

/**
 * Reads each module once. Parsing is the whole cost of this guard, a few seconds over the portal's
 * source, and it does not depend on the list, so the list can be judged against one reading.
 *
 * @param sources - Each module's text, by its path from the portal's directory.
 * @returns What each module does as it is imported.
 */
function scan(sources: Record<string, string>): Record<string, Scan> {
  const scanned: Record<string, Scan> = {};
  for (const [path, source] of Object.entries(sources)) {
    const body = statements(path, source);
    const declared = declaredNames(body);
    const found: Scan = {effects: [], bare: []};
    for (const statement of body) {
      const line = statement.loc.start.line;
      if (statement.type === 'ImportDeclaration') {
        const specifier = statement.source?.value ?? '';
        if ((statement.specifiers ?? []).length === 0 && specifier.startsWith('.')) found.bare.push({line, specifier});
        continue;
      }
      if (statement.directive !== undefined) continue;
      if (DECLARATIONS.has(statement.type)) {
        if (actsAsDeclared(statement)) found.effects.push(line);
        continue;
      }
      if (!namesItself(statement, declared)) found.effects.push(line);
    }
    scanned[path] = found;
  }
  return scanned;
}

/**
 * Everything the `sideEffects` list gets wrong about the source.
 *
 * @param scanned - What each module does as it is imported, by its path from the portal's directory.
 * @param others - Paths that exist and are not parsed: the stylesheets.
 * @param entries - `package.json`'s `sideEffects`, or undefined when it declares none.
 * @returns One finding per defect, sorted.
 */
function findings(scanned: Record<string, Scan>, others: string[], entries: string[] | undefined): string[] {
  if (!Array.isArray(entries)) {
    return ['package.json declares no sideEffects list, so the bundler keeps every module a barrel re-exports'];
  }
  const found: string[] = [];
  const files = new Set([...Object.keys(scanned), ...others]);
  const matchers: ((path: string) => boolean)[] = [];
  for (const entry of entries) {
    const matcher = matcherOf(entry);
    if (!matcher) {
      found.push(`sideEffects entry "${entry}" is a shape this guard does not model: ./path, ./dir/** or **/*.ext`);
    } else if (![...files].some(matcher)) {
      found.push(`sideEffects entry "${entry}" names no file`);
    } else {
      matchers.push(matcher);
    }
  }
  const listed = (path: string) => matchers.some((matcher) => matcher(path));

  for (const [path, {effects, bare}] of Object.entries(scanned)) {
    for (const {line, specifier} of bare) {
      const target = resolve(path, specifier, files);
      if (target === null || !listed(target)) {
        found.push(
          `${path}:${line} imports ${specifier} for its effects alone, and no sideEffects entry names that file`
        );
      }
    }
    if (listed(path)) continue;
    for (const line of effects) {
      found.push(
        `${path}:${line} runs as the module is imported, and no sideEffects entry names ${path}: unnamed, the bundler may drop it; named, it still runs only where the module is imported for an export that is used, or by a bare import`
      );
    }
  }
  return found.sort();
}

describe('the sideEffects guard, against sources written to trip it', () => {
  const check = (sources: Record<string, string>, entries: string[] = [], others: string[] = []) =>
    findings(scan(sources), others, entries);

  it.each([
    ['a call', 'register();'],
    ['an assignment to a global', 'self.Environment = {};'],
    ['a branch', 'if (typeof window !== "undefined") window.name = "x";'],
    ['a property set on an imported binding', 'import {Button} from "./Button";\nButton.displayName = "Button";'],
    ['a write through another name for a global', 'const w = window as Window & {x?: number};\nw.x = 1;'],
    [
      'a write to a binding it only describes',
      'declare const Legacy: {displayName?: string};\nLegacy.displayName = "x";'
    ],
    [
      'a property other than its name set on its own binding',
      'export const Menu = {} as {Item?: string};\nMenu.Item = "x";'
    ],
    [
      'a call assigned to a property of its own binding',
      'export const B = {} as {displayName?: string};\nB.displayName = register();'
    ],
    ['a computed property set on its own binding', 'export const B = {} as Record<string, number>;\nB[key()] = 1;'],
    ['a class’s static block', 'export class A { static { register(); } }'],
    ['a decorator', '@register class A {}'],
    ['a default export of a call', 'export default register();'],
    ['a default export of a call behind a type assertion', 'export default register() as Thing;']
  ])('names a module that runs %s as it is imported', (_, source) => {
    const line = source.split('\n').length;
    expect(check({'src/a.ts': source, 'src/Button.ts': 'export const Button = {};'})).toEqual([
      `src/a.ts:${line} runs as the module is imported, and no sideEffects entry names src/a.ts: unnamed, the bundler may drop it; named, it still runs only where the module is imported for an export that is used, or by a bare import`
    ]);
  });

  it.each([
    ['a directive', "'use client';\nexport const a = 1;"],
    ['types alone', 'export type A = string;\ninterface B {}\ndeclare global { interface Window { a: A } }'],
    [
      'a property set on its own binding',
      'export const Button = {} as {displayName?: string};\nButton.displayName = "Button";'
    ],
    ['a function that names itself', 'export function Comp() {}\nComp.displayName = "Comp";'],
    ['a default export of a name', 'const a = 1;\nexport default a;'],
    ['a default export of a function', 'export default function Page() {}'],
    ['a default export of a class', 'export default class Thing {}'],
    ['an effect inside an initializer, which it cannot see', 'export const stop = register();'],
    ['a static field’s initializer, which it cannot see', 'export class A { static x = register(); }'],
    ['a call in a class’s heritage, which it cannot see', 'export class A extends mixin(Base) {}']
  ])('is silent about %s', (_, source) => {
    expect(check({'src/a.tsx': source})).toEqual([]);
  });

  it('is silent about an effect in a file an entry names, by path, by folder or by extension', () => {
    const sources = {'src/a.ts': 'register();', 'src/app/b.ts': 'register();'};
    expect(check(sources, ['./src/a.ts', './src/app/**', '**/*.css'], ['src/index.css'])).toEqual([]);
  });

  it('names an import made for its effects when no entry names the file it loads', () => {
    const sources = {
      'src/a.ts': "import './b';\nimport '../index.css';\nimport 'server-only';",
      'src/b.ts': 'export {};'
    };
    expect(check(sources, ['**/*.css'], ['index.css'])).toEqual([
      'src/a.ts:1 imports ./b for its effects alone, and no sideEffects entry names that file'
    ]);
    expect(check({...sources, 'src/b.ts': 'register();'}, ['**/*.css', './src/b.ts'], ['index.css'])).toEqual([]);
  });

  it('names an import made for its effects that resolves to no file at all', () => {
    expect(check({'src/a.ts': "import './gone';"})).toEqual([
      'src/a.ts:1 imports ./gone for its effects alone, and no sideEffects entry names that file'
    ]);
  });

  it('names a package.json that declares no list, as a finding and not a crash', () => {
    expect(findings(scan({'src/a.ts': 'export {};'}), [], undefined)).toEqual([
      'package.json declares no sideEffects list, so the bundler keeps every module a barrel re-exports'
    ]);
  });

  it('names an entry that matches nothing, and one it cannot read', () => {
    const sources = {'src/a.ts': 'export {};', 'src/[x]/a.ts': 'export {};'};
    const entries = ['./src/gone.ts', '**/*.scss', './src/empty/**', 'src/*/a.ts', './src/[x]/a.ts', './src/[x]/**'];
    expect(check(sources, entries)).toEqual([
      'sideEffects entry "**/*.scss" names no file',
      'sideEffects entry "./src/[x]/**" is a shape this guard does not model: ./path, ./dir/** or **/*.ext',
      'sideEffects entry "./src/[x]/a.ts" is a shape this guard does not model: ./path, ./dir/** or **/*.ext',
      'sideEffects entry "./src/empty/**" names no file',
      'sideEffects entry "./src/gone.ts" names no file',
      'sideEffects entry "src/*/a.ts" is a shape this guard does not model: ./path, ./dir/** or **/*.ext'
    ]);
  });
});

describe('the sideEffects list, against the portal’s source', () => {
  /** A glob key as a path from the portal's directory. */
  const fromPortal = (key: string) => key.replace(/^\.\.\//, 'src/').replace(/^\.\//, 'src/lib/');
  const shipped = (path: string) =>
    !/\.test\.|\.testkit\.|\.d\.ts$/.test(path) && !path.startsWith('src/test/') && path !== 'src/test-setup.ts';

  const sources = Object.fromEntries(
    Object.entries(
      import.meta.glob('../**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
    )
      .map(([key, source]) => [fromPortal(key), source] as const)
      .filter(([path]) => shipped(path))
  );
  const stylesheets = Object.keys(import.meta.glob('../**/*.css')).map(fromPortal);
  const entries = (
    JSON.parse(
      Object.values(
        import.meta.glob('../../package.json', {query: '?raw', import: 'default', eager: true}) as Record<
          string,
          string
        >
      )[0]
    ) as {sideEffects?: string[]}
  ).sideEffects;

  // One reading of the source for both cases. It parses every module the portal ships, which is
  // real work and slower again beside the rest of the suite, so the two cases share it and the
  // first has a budget for it.
  let reading: Record<string, Scan> | undefined;
  const read = () => (reading ??= scan(sources));
  const PARSE_BUDGET_MS = 60_000;

  it(
    'names every module that does something as it is imported',
    () => {
      expect(Object.keys(sources).length).toBeGreaterThan(300);
      expect(findings(read(), stylesheets, entries)).toEqual([]);
    },
    PARSE_BUDGET_MS
  );

  it(
    'would name the SQL editor, the one module here with such a statement, were its entry removed',
    () => {
      // Read for that file alone, so a defect elsewhere fails the case above and not this one too.
      const without = (entries ?? []).filter((entry) => !entry.endsWith('/SqlEditor.tsx'));
      const named = findings(read(), stylesheets, without).filter((finding) => finding.includes('/SqlEditor.tsx'));
      expect(named.map((finding) => finding.replace(/:\d+ /, ' '))).toEqual([
        'src/features/query/SqlEditor.tsx runs as the module is imported, and no sideEffects entry names src/features/query/SqlEditor.tsx: unnamed, the bundler may drop it; named, it still runs only where the module is imported for an export that is used, or by a bare import',
        'src/features/query/SqlEditor.tsx runs as the module is imported, and no sideEffects entry names src/features/query/SqlEditor.tsx: unnamed, the bundler may drop it; named, it still runs only where the module is imported for an export that is used, or by a bare import'
      ]);
    },
    PARSE_BUDGET_MS
  );
});
