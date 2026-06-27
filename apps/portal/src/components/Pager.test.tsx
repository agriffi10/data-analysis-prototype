import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Pager } from './Pager';

describe('Pager', () => {
  it('renders the label and wires Prev/Next', () => {
    const onPrev = vi.fn();
    const onNext = vi.fn();
    render(<Pager hasPrev hasNext onPrev={onPrev} onNext={onNext} label="1–7 of 23" />);
    expect(screen.getByText('1–7 of 23')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(onPrev).toHaveBeenCalled();
    expect(onNext).toHaveBeenCalled();
  });

  it('disables Prev/Next per the flags', () => {
    render(<Pager hasPrev={false} hasNext={false} onPrev={vi.fn()} onNext={vi.fn()} label="1–5 of 5" />);
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows a loading Next and disables it when nextBusy', () => {
    render(<Pager hasPrev hasNext nextBusy onPrev={vi.fn()} onNext={vi.fn()} label="x" />);
    expect(screen.getByRole('button', { name: 'Loading…' })).toBeDisabled();
  });
});
