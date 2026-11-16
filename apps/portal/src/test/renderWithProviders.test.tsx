import {screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {useLocation, useNavigate, useParams} from '../lib/navigation';
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

  it('reaches it from one page to another through renderApp', async () => {
    const {user, location} = renderApp('/', {
      auth: authenticated('alice'),
      pages: {'page.tsx': GoesToHelp, '(signed-in)/help/page.tsx': () => <h1>Help stand-in</h1>}
    });

    await user.click(await screen.findByRole('button', {name: 'Go to help'}));

    expect(await screen.findByRole('heading', {name: 'Help stand-in'})).toBeInTheDocument();
    expect(location().pathname).toBe('/help');
  });
});

/** Reads the report's params through the seam, as the report page does. */
function ReportParams() {
  const {space, requestId} = useParams<{space: string; requestId: string}>();
  return <output aria-label="params">{JSON.stringify({space, requestId})}</output>;
}

describe('a pattern and the routes beside it', () => {
  // Percent-encoded by Next, decoded once by the seam: a second decode would read `50%` and a URIError.
  it('hands `path`’s params over as Next does, so the seam decodes them once', () => {
    renderWithProviders(<ReportParams />, {
      route: '/data-quality/50%2525/r1',
      path: '/data-quality/:space/:requestId'
    });

    expect(screen.getByLabelText('params')).toHaveTextContent(JSON.stringify({space: '50%25', requestId: 'r1'}));
  });

  it('renders the route a navigation reaches', async () => {
    const {user} = renderWithProviders(<GoesToHelp />, {
      route: '/files',
      path: '/files',
      routes: {'/help': <h1>Help route</h1>}
    });

    await user.click(screen.getByRole('button', {name: 'Go to help'}));

    expect(await screen.findByRole('heading', {name: 'Help route'})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Go to help'})).not.toBeInTheDocument();
  });
});
