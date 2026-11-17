import {isValidElement, type ReactElement, type ReactNode} from 'react';
import {headers} from 'next/headers';
import {afterEach, describe, expect, it, vi} from 'vitest';
import RootLayout from './layout';
import {PortalMount} from './PortalMount';
import {serverFeatureFlags} from '../server/featureFlags';
import {FEATURE_FLAG_DEFAULTS} from '../features/feature-flags/featureFlagDefaults';

vi.mock('next/headers', () => ({headers: vi.fn(async () => new Headers({'x-nonce': 'n'}))}));
vi.mock('../server/featureFlags', () => ({serverFeatureFlags: vi.fn()}));

/** The first element of `type` in a tree the layout returned, walked through `children` props. */
function find(node: ReactNode, type: unknown): ReactElement<Record<string, unknown>> | undefined {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = find(child, type);
      if (found) return found;
    }
    return undefined;
  }
  if (!isValidElement<{children?: ReactNode}>(node)) return undefined;
  if (node.type === type) return node as ReactElement<Record<string, unknown>>;
  return find(node.props.children, type);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('the root layout', () => {
  it('sends the held flag set with the page, as the mount’s prop', async () => {
    const seeded = {flags: {...FEATURE_FLAG_DEFAULTS, query: false}, readAt: 1};
    vi.mocked(serverFeatureFlags).mockResolvedValue(seeded);

    const mount = find(await RootLayout({children: <p>the page</p>}), PortalMount);

    expect(mount?.props.flags).toBe(seeded);
    expect(headers).toHaveBeenCalled();
  });

  it('sends no set when the server holds none for this request', async () => {
    vi.mocked(serverFeatureFlags).mockResolvedValue(undefined);

    const mount = find(await RootLayout({children: <p>the page</p>}), PortalMount);

    expect(mount).toBeDefined();
    expect(mount?.props.flags).toBeUndefined();
  });
});
