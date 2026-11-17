import {afterEach, describe, expect, it, vi} from 'vitest';
import {headers} from 'next/headers';
import {heldFeatureFlags, resetServerFeatureFlagsForTests, serverRouteGate} from './featureFlags';
import {holdFlags} from './featureFlagsTestSupport';
import {environmentDeps} from './session/handlers';

vi.mock('next/headers', () => ({headers: vi.fn()}));
vi.mock('./session/handlers', () => ({environmentDeps: vi.fn()}));

// The throw has to come through the import: a mock of the gate's own module cannot reach the call it
// makes. Every read of the registry throws, and so does the fallback's helper.
vi.mock('../features/feature-flags/gatedSurfaces', () => {
  const unreadable = () => {
    throw new Error('the registry could not be read');
  };
  return {
    GATED_SURFACES: new Proxy({}, {get: unreadable, ownKeys: unreadable, getOwnPropertyDescriptor: unreadable}),
    firstEnabledDestination: vi.fn(unreadable)
  };
});

afterEach(() => {
  resetServerFeatureFlagsForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(headers).mockReset();
  vi.mocked(environmentDeps).mockReset();
});

describe('a route gate whose registry cannot be read', () => {
  it('answers open, after one log line, rather than throwing out of a layout', async () => {
    await holdFlags({query: false});
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(heldFeatureFlags()?.flags.query).toBe(false);
    expect(serverRouteGate('/query')).toEqual({kind: 'open'});
    expect(error).toHaveBeenCalledTimes(1);
  });
});
