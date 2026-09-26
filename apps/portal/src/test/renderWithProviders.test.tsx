import {describe, expect, it} from 'vitest';
import {renderWithProviders} from './renderWithProviders';

describe('renderWithProviders', () => {
  it('refuses flag overrides it would not seed, rather than dropping them', () => {
    // Unseeded, the overrides have nowhere to go: a test asking for `archive: false` would render
    // the all-on app and pass whatever the gate does.
    const render = () => renderWithProviders(<div />, {seedFeatureFlags: false, featureFlags: {archive: false}});

    expect(render).toThrow('featureFlags needs seedFeatureFlags');
  });
});
