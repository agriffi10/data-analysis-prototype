import type {ReactNode} from 'react';
import {render, screen} from '@testing-library/react';
import {useQueryClient} from '@tanstack/react-query';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {AppFrame} from './AppFrame';
import {seedServerFlags} from './features/feature-flags';
import {FEATURE_FLAG_DEFAULTS} from './features/feature-flags/featureFlagDefaults';

const events = vi.hoisted(() => [] as string[]);

vi.mock('./features/feature-flags', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/feature-flags')>()),
  seedServerFlags: vi.fn(() => events.push('seed'))
}));

// The chrome's sign-in gate and the provider's session read are not this test's subject: the frame's
// own order is, so both are passed through.
vi.mock('./AppChrome', () => ({AppChrome: ({children}: {children: ReactNode}) => <>{children}</>}));
vi.mock('./features/auth', () => ({AuthProvider: ({children}: {children: ReactNode}) => <>{children}</>}));

/** Records its first render, and whether the frame's query client is the one the seed was handed. */
function Probe() {
  const client = useQueryClient();
  events.push(vi.mocked(seedServerFlags).mock.calls.some(([seeded]) => seeded === client) ? 'render' : 'render-other');
  return <p>the page</p>;
}

afterEach(() => {
  events.length = 0;
  vi.clearAllMocks();
});

describe('the frame', () => {
  it('seeds its own query client with the server’s set before its first render', () => {
    const seeded = {flags: {...FEATURE_FLAG_DEFAULTS, query: false}, readAt: 1};

    render(
      <AppFrame flags={seeded}>
        <Probe />
      </AppFrame>
    );

    expect(screen.getByText('the page')).toBeInTheDocument();
    expect(events[0]).toBe('seed');
    expect(events).toContain('render');
    expect(events).not.toContain('render-other');
    expect(vi.mocked(seedServerFlags).mock.calls[0][2]).toBe(seeded);
  });

  it('seeds nothing when the server sent no set', () => {
    render(
      <AppFrame>
        <Probe />
      </AppFrame>
    );

    expect(screen.getByText('the page')).toBeInTheDocument();
    expect(seedServerFlags).not.toHaveBeenCalled();
  });
});
