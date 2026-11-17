import {isValidElement, type ReactElement, type ReactNode} from 'react';
import {screen} from '@testing-library/react';
import {headers} from 'next/headers';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {UnavailableMount} from './UnavailableMount';
import {GATED_SURFACES} from '../../features/feature-flags/gatedSurfaces';
import type {FeatureFlagKey, FeatureFlags} from '../../features/feature-flags/featureFlags.types';
import {FEATURE_FLAG_KEYS} from '../../features/feature-flags/featureFlagDefaults';
import {apiRequest} from '../../lib/apiClient';
import {holdFlags} from '../../server/featureFlagsTestSupport';
import {resetServerFeatureFlagsForTests} from '../../server/featureFlags';
import {environmentDeps} from '../../server/session/handlers';
import {renderWithProviders} from '../../test/renderWithProviders';

vi.mock('next/headers', () => ({headers: vi.fn()}));
vi.mock('../../server/session/handlers', () => ({environmentDeps: vi.fn()}));
vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The area layouts, called as Next calls a server component, over a flag set held through the
 * server's real refresh. What renders in the browser after them is each page's own concern.
 */
const LAYOUTS = Object.fromEntries(
  Object.entries(
    import.meta.glob<{default: (props: {children: ReactNode}) => ReactNode}>('./*/layout.tsx', {eager: true})
  ).map(([file, module]) => [file.slice(1, -'/layout.tsx'.length), module.default])
);

/** The one route row the server cannot decide: it gates the report only for a shared space in the address. */
const EXEMPT = 'Shared-space data quality report';

const PAGE = <p>the page</p>;

/** Every flag on but these. */
const only = (on: FeatureFlagKey[]): Partial<FeatureFlags> =>
  Object.fromEntries(FEATURE_FLAG_KEYS.map((key) => [key, on.includes(key)]));

/** The layout's answer, as an element, when it is the unavailable mount. */
function mountOf(
  node: ReactNode
): ReactElement<{flag: FeatureFlagKey; fallback: FeatureFlagKey | undefined}> | undefined {
  return isValidElement(node) && node.type === UnavailableMount ? (node as never) : undefined;
}

afterEach(() => {
  resetServerFeatureFlagsForTests();
  vi.unstubAllGlobals();
  vi.mocked(headers).mockReset();
  vi.mocked(environmentDeps).mockReset();
  vi.clearAllMocks();
});

describe('an area layout with its flag off', () => {
  it('answers /query with the unavailable page for Query, never its page', async () => {
    await holdFlags({query: false});

    const answered = LAYOUTS['/query']({children: PAGE});

    expect(mountOf(answered)?.props).toEqual({flag: 'query', fallback: 'files'});
    renderWithProviders(answered as ReactElement);
    expect(await screen.findByRole('heading', {name: 'Query isn’t available'})).toBeInTheDocument();
    expect(screen.queryByText('the page')).not.toBeInTheDocument();
  });

  it('answers /data-quality, which covers the report route beneath it', async () => {
    await holdFlags({dataQuality: false});

    expect(mountOf(LAYOUTS['/data-quality']({children: PAGE}))?.props.flag).toBe('dataQuality');
  });

  it('offers no link when every flag is off, and Files when only Files is on, reading no flags', async () => {
    await holdFlags(only([]));
    const nothing = LAYOUTS['/query']({children: PAGE});
    expect(mountOf(nothing)?.props.fallback).toBeUndefined();
    const {unmount} = renderWithProviders(nothing as ReactElement);
    expect(await screen.findByRole('heading', {name: 'Query isn’t available'})).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    unmount();

    await holdFlags(only(['files']));
    const files = LAYOUTS['/query']({children: PAGE});
    expect(mountOf(files)?.props.fallback).toBe('files');
    renderWithProviders(files as ReactElement);
    expect(await screen.findByRole('link', {name: 'Go to Files'})).toBeInTheDocument();

    expect(vi.mocked(apiRequest).mock.calls.filter(([route]) => route === 'featureFlags.get')).toEqual([]);
  });
});

describe('an area layout that leaves the decision to the browser', () => {
  it.each(Object.keys(LAYOUTS))('returns %s’s page itself with its flag on, and with no held set', async (area) => {
    await holdFlags({});
    expect(LAYOUTS[area]({children: PAGE})).toBe(PAGE);

    resetServerFeatureFlagsForTests();
    expect(LAYOUTS[area]({children: PAGE})).toBe(PAGE);
  });
});

describe('the registry’s route rows', () => {
  const rows = (Object.entries(GATED_SURFACES) as [FeatureFlagKey, (typeof GATED_SURFACES)['files']][]).flatMap(
    ([flag, surfaces]) => surfaces.filter((surface) => surface.kind === 'route').map((surface) => ({flag, ...surface}))
  );

  it('still name the one row the server leaves to the browser', () => {
    expect(rows.map(({name}) => name)).toContain(EXEMPT);
  });

  it.each(rows.filter(({name}) => name !== EXEMPT).map((row) => [row.name, row] as const))(
    '%s is gated by an area layout on the server',
    async (_name, row) => {
      const area = Object.keys(LAYOUTS).find((path) => row.path === path || row.path.startsWith(`${path}/`));
      expect(area, `no server layout covers ${row.path}`).toBeDefined();

      await holdFlags({[row.flag]: false});
      expect(mountOf(LAYOUTS[area!]({children: PAGE}))?.props.flag).toBe(row.flag);

      await holdFlags({});
      expect(LAYOUTS[area!]({children: PAGE})).toBe(PAGE);
    }
  );
});
