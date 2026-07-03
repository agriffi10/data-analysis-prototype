import {describe, it, expect} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {HelpGuideCard} from './HelpGuideCard';
import type {HelpGuide} from './help.types';

const guide: HelpGuide = {
  id: 'upload-files',
  title: 'Upload files',
  subtitle: 'Add files from your computer.',
  steps: ['Open the <b>Files</b> tab.', 'Click <b>Upload</b>.'],
  callout: {kind: 'warning', text: 'Use <b>Cancel</b> to back out.'}
};

describe('HelpGuideCard (SPEC-074 FR-004)', () => {
  it('renders a collapsed card by default — title/subtitle visible, steps hidden', () => {
    render(
      <HelpGuideCard
        guide={guide}
        iconName="files"
      />
    );
    const header = screen.getByRole('button', {name: /Upload files/});
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Add files from your computer.')).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('toggles open on click, revealing numbered steps and the callout', () => {
    render(
      <HelpGuideCard
        guide={guide}
        iconName="files"
      />
    );
    const header = screen.getByRole('button', {name: /Upload files/});
    fireEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'true');
    expect(header).toHaveAttribute('aria-controls');
    const steps = screen.getByRole('list');
    expect(steps).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    // Inline <b> is parsed to <strong>, not rendered as literal markup.
    expect(screen.getByText('Files')).toBeInTheDocument();
    expect(screen.queryByText(/<b>/)).not.toBeInTheDocument();
    // Warning callout prefix present.
    expect(screen.getByText(/Careful\./)).toBeInTheDocument();
    // Callout text is parsed too — <b> becomes <strong>, never literal markup.
    const cancel = screen.getByText('Cancel');
    expect(cancel.tagName).toBe('STRONG');
    expect(screen.queryByText(/<b>Cancel<\/b>/)).not.toBeInTheDocument();
  });

  it('honors defaultOpen', () => {
    render(
      <HelpGuideCard
        guide={guide}
        iconName="files"
        defaultOpen
      />
    );
    expect(screen.getByRole('button', {name: /Upload files/})).toHaveAttribute('aria-expanded', 'true');
  });

  it('renders no callout when the guide has none', async () => {
    render(
      <HelpGuideCard
        guide={{...guide, callout: undefined}}
        iconName="files"
        defaultOpen
      />
    );
    expect(screen.queryByText(/Careful\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Tip\./)).not.toBeInTheDocument();
  });
});
