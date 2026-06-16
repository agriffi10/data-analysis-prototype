import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { createRef } from 'react';
import { Button } from './Button';

describe('Button', () => {
  it('renders each variant', () => {
    const variants = ['primary', 'default', 'ghost', 'danger'] as const;
    variants.forEach((v) => {
      const { unmount } = render(<Button variant={v}>{v}</Button>);
      expect(screen.getByRole('button', { name: v })).toBeInTheDocument();
      unmount();
    });
  });

  it('forwards disabled', () => {
    render(<Button disabled>Go</Button>);
    expect(screen.getByRole('button', { name: 'Go' })).toBeDisabled();
  });

  it('forwards onClick', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Click</Button>);
    fireEvent.click(screen.getByRole('button', { name: 'Click' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('appends className additions', () => {
    render(<Button className="custom-x">Styled</Button>);
    expect(screen.getByRole('button', { name: 'Styled' })).toHaveClass('custom-x');
  });

  it('forwards a ref', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Ref</Button>);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });
});
