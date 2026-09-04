import {useId, useState} from 'react';
import {ChevronDownIcon, InfoIcon, WarningIcon} from '../../components/icons';
import {cx} from '../../lib/cx';
import {helpIcons} from './helpIcons';
import {renderInline} from './inlineMarkup';
import type {HelpGuide, HelpIconName} from './help.types';

type HelpGuideCardProps = {
  guide: HelpGuide;
  iconName: HelpIconName;
  defaultOpen?: boolean;
  /**
   * Hold a CLOSED card's title and subtitle to one line each. For a list of cards in a narrow
   * column that is itself the thing being scrolled — the contextual panel — where a subtitle
   * wrapping to three lines makes the list of headings taller than the panel showing them.
   *
   * Off by default, and `/help` leaves it off deliberately: that page scrolls the whole
   * document, so a wrapped subtitle costs nothing there and clipping one would lose text a
   * reader can otherwise have for free. The panel's own column is ~290px and the page's is
   * ~215px at 375, so the page is where an ellipsis would cut MOST.
   */
  clampHeading?: boolean;
};

/**
 * One accordion guide card: a header button (feature icon + title + subtitle
 * beneath + chevron) toggling an ordered, numbered step list and an optional
 * single Tip/Careful callout. Cards are independent — open state is local
 * `aria-expanded`/`aria-controls` wire the header to its panel
 *
 * @example
 * <HelpGuideCard guide={guide} iconName="files" defaultOpen />
 */
export function HelpGuideCard({guide, iconName, defaultOpen = false, clampHeading = false}: HelpGuideCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  const clamped = clampHeading && !open;
  const Icon = helpIcons[iconName];

  return (
    // `shrink-0` is what makes the panel SCROLL instead of squashing its cards. The drawer
    // body is a scrolling flex column, and a flex item shrinks before its container scrolls —
    // `overflow-hidden` on this card (needed for the rounded corners over the accordion's
    // grid transition) drops its automatic minimum size to zero, so it can be crushed to
    // nothing. Opening a second guide compressed every other card rather than scrolling.
    <div
      className={cx(
        'shrink-0 overflow-hidden rounded-[10px] border bg-surface',
        open ? 'border-accent-border' : 'border-border'
      )}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className={cx(
          'flex w-full items-start gap-[14px] px-[18px] py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent',
          open ? 'bg-accent-soft' : 'hover:bg-surface-2'
        )}>
        <span
          aria-hidden="true"
          className={cx(
            'mt-px flex h-9 w-9 flex-none items-center justify-center rounded-[9px] text-accent-text',
            open ? 'bg-surface' : 'bg-accent-soft'
          )}>
          <Icon className="h-[19px] w-[19px]" />
        </span>
        {/* One line each while CLOSED, wrapping in full once open. A closed card is a row in
            a list of choices, and a subtitle that wraps to three lines makes the list of them
            taller than the panel — the reader is scrolling past headings to find the one they
            want. Open, the same text is the thing they chose to read, so it is shown whole. */}
        <span className="min-w-0 flex-1">
          <span className={cx('block text-[15px] font-semibold text-text', clamped && 'truncate')}>{guide.title}</span>
          <span className={cx('mt-0.5 block text-[13px] text-text-2', clamped && 'truncate')}>{guide.subtitle}</span>
        </span>
        <ChevronDownIcon
          className={cx(
            'mt-[9px] h-[18px] w-[18px] flex-none transition-transform',
            open ? 'rotate-180 text-accent-text' : 'text-text-3'
          )}
        />
      </button>

      <div
        id={panelId}
        aria-hidden={!open}
        className={cx(
          'grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none',
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        )}>
        <div className="overflow-hidden">
          {/* Steps indent under the header icon at ≥ tablet; on mobile they use
              the card's own gutter so narrow widths aren't over-indented. */}
          <div className="px-[18px] pb-5 pt-1 tablet:pl-[68px]">
            {guide.intro && <p className="mb-4 text-sm leading-[1.55] text-text-2">{renderInline(guide.intro)}</p>}
            <ol className="flex list-none flex-col gap-3">
              {guide.steps.map((step, i) => (
                <li
                  key={i}
                  className="relative pl-[34px] text-sm leading-[1.55] text-text">
                  <span
                    aria-hidden="true"
                    className="absolute left-0 top-px flex h-[22px] w-[22px] items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-text">
                    {i + 1}
                  </span>
                  {renderInline(step)}
                </li>
              ))}
            </ol>
            {guide.callout && <Callout callout={guide.callout} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function Callout({callout}: {callout: NonNullable<HelpGuide['callout']>}) {
  const warning = callout.kind === 'warning';
  const Icon = warning ? WarningIcon : InfoIcon;
  return (
    <div
      className={cx(
        'mt-4 flex gap-2.5 rounded-lg border px-3.5 py-3 text-[13px] leading-[1.5] text-text',
        warning ? 'border-danger-border bg-danger-soft' : 'border-accent-border bg-accent-soft'
      )}>
      <Icon className={cx('mt-px h-4 w-4 flex-none', warning ? 'text-danger' : 'text-accent-text')} />
      <span>
        <strong className="font-semibold">{warning ? 'Careful. ' : 'Tip. '}</strong>
        {renderInline(callout.text)}
      </span>
    </div>
  );
}
