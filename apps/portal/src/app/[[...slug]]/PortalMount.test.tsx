import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {PortalMount} from './PortalMount';

vi.mock('../../PortalBoot', () => ({
  PortalBoot: function PortalBootMock() {
    return <div data-testid="boot" />;
  }
}));

describe('the catch-all mount', () => {
  it('loads the boot in the browser', async () => {
    render(<PortalMount />);

    expect(await screen.findByTestId('boot')).toBeInTheDocument();
  });
});
