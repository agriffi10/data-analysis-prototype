import {describe, expect, it} from 'vitest';

/**
 * What the resolver may reach, read from its source. The Next.js server imports it, so anything it
 * reaches is evaluated on the server: the network, React or the browser's configuration would each
 * fail there, or tie the server's answer to something the browser's never sees.
 */
const SOURCE = Object.values(
  import.meta.glob('./resolveFeatureFlags.ts', {query: '?raw', import: 'default', eager: true})
)[0] as string;

/** The modules it may import, as written. */
const ALLOWED = ['./featureFlags.types', './featureFlagDefaults', '../../lib/serviceResult'];

/**
 * Every specifier a source imports, statically or dynamically, other than the allowed three.
 *
 * @param source - A module's text.
 * @returns The specifiers outside the allowance.
 */
function outsideTheAllowance(source: string): string[] {
  const written = [
    ...[...source.matchAll(/^(?:import|export)\s[^'"(=;]*['"]([^'"]+)['"]/gm)].map(([, specifier]) => specifier),
    ...[...source.matchAll(/\bimport\(\s*['"]([^'"]+)['"]/g)].map(([, specifier]) => specifier)
  ];
  return written.filter((specifier) => !ALLOWED.includes(specifier));
}

describe('the resolver’s reach', () => {
  it('names a planted import of the network, a type import of React and a dynamic import', () => {
    const planted = [
      "import {apiRequest} from '../../lib/apiClient';",
      "import type {ReactNode} from 'react';",
      "const later = () => import('../../lib/runtimeConfig');"
    ].join('\n');

    expect(outsideTheAllowance(planted)).toEqual(['../../lib/apiClient', 'react', '../../lib/runtimeConfig']);
  });

  it('imports nothing but the flag types, the defaults and the result helpers', () => {
    expect(SOURCE).toContain('export function resolveFeatureFlagDocument');
    expect(outsideTheAllowance(SOURCE)).toEqual([]);
  });

  it('reaches no authorization surface', () => {
    // Its only inputs are the document and the environment name, on either side of the wire.
    expect(SOURCE).not.toMatch(/PrincipalTag|fetchAuthSession|assumeRole|IamPolicy|idToken|session/i);
  });
});
