import type {ComponentType} from 'react';
import {DestinationIcon, type Destination} from '../../components/DestinationIcon';
import {BellIcon, FeedbackIcon, HelpCircleIcon, TableIcon} from '../../components/icons';
import type {HelpIconName} from './help.types';

type IconComponent = ComponentType<{className?: string}>;

/** A guide about a page carries that page's own nav glyph, so the two read as one place. */
function destination(name: Destination): IconComponent {
  function HelpDestinationIcon({className}: {className?: string}) {
    return (
      <DestinationIcon
        destination={name}
        className={className}
      />
    );
  }
  return HelpDestinationIcon;
}

/** Maps a section/guide's `HelpIconName` to its inline SVG icon component. */
export const helpIcons: Record<HelpIconName, IconComponent> = {
  files: destination('files'),
  query: destination('query'),
  tables: TableIcon,
  explore: destination('explore'),
  connections: destination('connections'),
  notifications: BellIcon,
  'getting-around': HelpCircleIcon,
  feedback: FeedbackIcon
};
