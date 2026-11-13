import {ESLint} from 'eslint';
import {describe, expect, it} from 'vitest';

/**
 * The server fence, asserted by LINTING an import rather than by reading the config.
 *
 * Flat config replaces a rule's value at the last entry matching a file, so whether a file is
 * fenced depends on which clause matches it last, and a shape test over the entries can agree
 * with a config that fences nothing. Linting a planted import as each tree's file asks the only
 * question that matters, and the server's own tree is the negative control: without it, a rule
 * that refused every import would pass too.
 */
// The suite runs from apps/portal, as every file-reading test here assumes.
const PORTAL = `${process.cwd()}/`;
const eslint = new ESLint({cwd: PORTAL});

/** The rule's messages for one planted import, linted as if it lived at `file`. */
async function fenceMessages(file: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport {x};\n`, {filePath: `${PORTAL}${file}`});
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').map((m) => m.message);
}

describe('nothing under features/, components/, lib/ or hooks/ imports src/server/', () => {
  it.each([
    ['src/lib/probe.ts', "import {x} from '../server/runtimeDocument';"],
    ['src/lib/probe.test.ts', "import {x} from '../server/runtimeDocument';"],
    ['src/components/probe.tsx', "import {x} from '../server/runtimeDocument';"],
    ['src/hooks/probe.ts', "import {x} from '../server/runtimeDocument';"],
    ['src/features/query/probe.ts', "import {x} from '../../server/runtimeDocument';"],
    ['src/features/file-browser/probe.ts', "import {x} from '../../server/runtimeDocument';"],
    ['src/features/query/nested/probe.ts', "import {x} from '../../../server/contentSecurityPolicy';"]
  ])('refuses the import in %s', async (file, source) => {
    const messages = await fenceMessages(file, source);

    expect(messages.join('\n')).toContain("src/server/ is the Next.js server's alone");
  });

  it('lets the server side import it', async () => {
    // The proxy, a route handler and the server's own modules are what src/server/ exists for.
    expect(await fenceMessages('src/proxy.ts', "import {x} from './server/runtimeDocument';")).toEqual([]);
    expect(
      await fenceMessages('src/app/config.json/route.ts', "import {x} from '../../server/runtimeDocument';")
    ).toEqual([]);
  });

  it('does not mistake a package for the server tree', async () => {
    expect(await fenceMessages('src/lib/probe.ts', "import {x} from 'react-dom/server';")).toEqual([]);
  });
});
