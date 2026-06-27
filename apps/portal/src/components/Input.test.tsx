import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {Input} from './Input';

describe('Input', () => {
  it('renders a label wired to the input', () => {
    render(
      <Input
        id="name"
        label="Your name"
      />
    );
    expect(screen.getByLabelText('Your name')).toBeInTheDocument();
  });

  it('shows the error message and marks the input invalid', () => {
    render(
      <Input
        id="name"
        label="Name"
        error="Required"
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Required');
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not render an error or aria-invalid when error is absent', () => {
    render(
      <Input
        id="name"
        label="Name"
      />
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name')).not.toHaveAttribute('aria-invalid');
  });
});
