import {createElement} from 'react';
import {describe, expect, it} from 'vitest';
import {render} from '@testing-library/react';
import {DestinationIcon, type Destination} from '../../components/DestinationIcon';
import {helpIcons} from './helpIcons';
import type {HelpIconName} from './help.types';

describe('helpIcons', () => {
  // A guide drew Data Explorer as an eye while its nav tab drew a grid, and testers noticed.
  it.each<[HelpIconName, Destination]>([
    ['files', 'files'],
    ['query', 'query'],
    ['explore', 'explore'],
    ['connections', 'connections']
  ])('draws the %s guides with the %s nav tab’s own glyph', (section, destination) => {
    const guide = render(createElement(helpIcons[section], {className: 'h-4 w-4'})).container.innerHTML;
    const tab = render(
      <DestinationIcon
        destination={destination}
        className="h-4 w-4"
      />
    ).container.innerHTML;

    expect(guide).toBe(tab);
  });
});
