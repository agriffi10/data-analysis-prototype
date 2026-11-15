import {ESLint} from 'eslint';
import {describe, expect, it} from 'vitest';

/**
 * The page fence, asserted by LINTING an import: an App Router page may import lib/ and hooks/
 * statically, so neither may import components/ or routes/, which a page reaches only client-only.
 * Linting a planted import as each tree's file asks which clause matches it last, which a shape test
 * over the config entries cannot.
 */
// The suite runs from apps/portal, as every file-reading test here assumes.
const PORTAL = `${process.cwd()}/`;
const eslint = new ESLint({cwd: PORTAL});

/** The rule's messages for one planted import, linted as if it lived at `file`. */
async function fenceMessages(file: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport {x};\n`, {filePath: `${PORTAL}${file}`});
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').map((m) => m.message);
}

describe('lib/ and hooks/ stay off what a page reaches only client-only', () => {
  it.each([
    ['src/hooks/probe.ts', "import {x} from '../components/LoadingState';"],
    ['src/lib/probe.ts', "import {x} from '../routes/table';"],
    ['src/lib/nested/probe.ts', "import {x} from '../../components/LoadingState.js';"],
    ['src/lib/navigation/probe.ts', "import {x} from '../../routes/areas/files';"]
  ])('refuses the import in %s', async (file, source) => {
    const messages = await fenceMessages(file, source);

    expect(messages.join('\n')).toContain('what an App Router page may import statically');
  });

  it('lets a type-only import through, and leaves components/ and tests to their own rules', async () => {
    expect(await fenceMessages('src/hooks/probe.ts', "import type {x} from '../components/LoadingState';")).toEqual([]);
    expect(await fenceMessages('src/components/probe.tsx', "import {x} from './LoadingState';")).toEqual([]);
    expect(await fenceMessages('src/hooks/probe.test.ts', "import {x} from '../components/LoadingState';")).toEqual([]);
  });
});

/** The rule's messages for one planted source file, linted as if it lived at `file`. */
async function attributeMessages(file: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(source, {filePath: `${PORTAL}${file}`});
  return result.messages.map((m) => `${m.ruleId}: ${m.message}`);
}

describe('no import under src/ carries an attribute, which would pass for next/dynamic’s', () => {
  const refused = `no-restricted-syntax: No import attributes under src/: Turbopack reads a turbopack-transition attribute as next/dynamic's mark, which hides an eager import from the page check, and no source here needs any. Reach a view through next/dynamic itself.`;

  it.each([
    [
      'src/app/(signed-in)/files/page.tsx',
      "void import('../../../features/x', {with: {'turbopack-transition': 'next-dynamic'}});\nexport {};"
    ],
    ['src/hooks/probe.ts', "import x from '../lib/x.json' with {type: 'json'};\nexport {x};"],
    ['src/lib/probe.mts', "export * from '../features/x' with {type: 'json'};\nexport const y: number = 1;"],
    ['src/lib/probe.mjs', "export {x} from '../features/x' with {type: 'json'};"]
  ])('refuses the attribute in %s', async (file, source) => {
    expect(await attributeMessages(file, source)).toEqual([refused]);
  });

  it('lets a plain lazy import through', async () => {
    expect(await attributeMessages('src/hooks/probe.ts', "void import('../lib/cx');\nexport {};")).toEqual([]);
  });
});
