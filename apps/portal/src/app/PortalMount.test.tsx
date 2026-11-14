import type {ReactNode} from 'react';
import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {PortalMount} from './PortalMount';

vi.mock('../PortalBoot', () => ({
  PortalBoot: function PortalBootMock({children}: {children: ReactNode}) {
    return <div data-testid="boot">{children}</div>;
  }
}));

describe('the root mount', () => {
  it('loads the boot in the browser, and hands it the page', async () => {
    render(
      <PortalMount>
        <p>the page</p>
      </PortalMount>
    );

    expect(await screen.findByTestId('boot')).toHaveTextContent('the page');
  });
});
