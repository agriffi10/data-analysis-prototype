import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Banner } from './Banner';

describe('Banner', () => {
  it('renders each variant with its body', () => {
    const variants = ['success', 'warning', 'danger', 'info'] as const;
    variants.forEach((v) => {
      const { unmount } = render(<Banner variant={v}>Body {v}</Banner>);
      expect(screen.getByText(`Body ${v}`)).toBeInTheDocument();
      unmount();
    });
  });

  it('renders the title when provided', () => {
    render(
      <Banner variant="success" title="Done">
        details
      </Banner>
    );
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('shows a Dismiss button only when onDismiss is provided and calls it', () => {
    const onDismiss = vi.fn();
    const { rerender } = render(<Banner variant="danger">x</Banner>);
    expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument();

    rerender(
      <Banner variant="danger" onDismiss={onDismiss}>
        x
      </Banner>
    );
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('defaults role to alert and honours status', () => {
    const { rerender } = render(<Banner variant="info">a</Banner>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    rerender(
      <Banner variant="success" role="status">
        a
      </Banner>
    );
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
