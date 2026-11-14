import {describe, expect, inject, it} from 'vitest';

describe('the module cache', () => {
  // The cache skips a module holding the literal `import.meta.glob(`, but freezes the file list of a
  // glob spelled any other way, so a page added after one run stayed invisible to `renderApp`.
  it('is off for this run, as the global setup resolved it', () => {
    expect(
      inject('fsModuleCache'),
      'fsModuleCache must stay off in vite.config.ts: it freezes the file list of a glob not spelled import.meta.glob('
    ).toBe(false);
  });
});
