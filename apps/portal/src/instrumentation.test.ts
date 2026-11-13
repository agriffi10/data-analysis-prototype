import {afterEach, describe, expect, it, vi} from 'vitest';

const refuse = vi.hoisted(() => vi.fn());
vi.mock('./server/runtimeDocument', () => ({refuseToStartWithoutConfiguration: refuse}));

afterEach(() => {
  vi.unstubAllEnvs();
  refuse.mockClear();
});

describe('the start-time hook', () => {
  it('checks the configuration on the Node runtime, and only there', async () => {
    const {register} = await import('./instrumentation');

    vi.stubEnv('NEXT_RUNTIME', 'edge');
    await register();
    expect(refuse).not.toHaveBeenCalled();

    vi.stubEnv('NEXT_RUNTIME', 'nodejs');
    await register();
    expect(refuse).toHaveBeenCalledOnce();
  });
});
