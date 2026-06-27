import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// The route component is a thin wrapper: it sets the page title and renders the
// feature view (covered by features/shared-spaces/ConnectionsPage.test.tsx). Mock
// the view so this stays a focused smoke test of the wrapper.
vi.mock('../features/shared-spaces', () => ({
  ConnectionsPage: () => <div>connections-view</div>,
}));

import ConnectionsPage from './ConnectionsPage';

describe('ConnectionsPage route (SPEC-052)', () => {
  it('renders the connections view and sets the document title', () => {
    render(<ConnectionsPage />);
    expect(screen.getByText('connections-view')).toBeInTheDocument();
    expect(document.title).toContain('Connections');
  });
});
