import {screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {useLocation, useNavigate} from '../lib/navigation';
import {renderApp} from './appRouter';
import {authenticated} from './authFixtures';
import {renderWithProviders} from './renderWithProviders';

/** A component that navigates with the seam, and says where it is. */
function GoesToHelp() {
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        onClick={() => navigate('/help')}>
        Go to help
      </button>
      <output aria-label="where">{useLocation().pathname}</output>
    </>
  );
}

describe('renderWithProviders', () => {
  it('refuses flag overrides it would not seed, rather than dropping them', () => {
    // Unseeded, the overrides have nowhere to go: a test asking for `archive: false` would render
    // the all-on app and pass whatever the gate does.
    const render = () => renderWithProviders(<div />, {seedFeatureFlags: false, featureFlags: {archive: false}});

    expect(render).toThrow('featureFlags needs seedFeatureFlags');
  });
});

describe('a component that navigates with the seam', () => {
  it('reaches its destination under renderWithProviders, with no router option', async () => {
    const {user, location} = renderWithProviders(<GoesToHelp />, {route: '/files'});

    await user.click(screen.getByRole('button', {name: 'Go to help'}));

    expect(location().pathname).toBe('/help');
    expect(screen.getByLabelText('where')).toHaveTextContent('/help');
  });

  it('reaches it as a catch-all page through renderApp', async () => {
    const {user, location} = renderApp('/files', {
      auth: authenticated('alice'),
      pages: {'[[...slug]]/page.tsx': GoesToHelp}
    });

    await user.click(await screen.findByRole('button', {name: 'Go to help'}));

    expect(location().pathname).toBe('/help');
    expect(await screen.findByLabelText('where')).toHaveTextContent('/help');
  });
});
