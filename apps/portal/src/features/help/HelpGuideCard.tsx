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
};

/**
 * One accordion guide card: a header button (feature icon + title + subtitle
 * beneath + chevron) toggling an ordered, numbered step list and an optional
 * single Tip/Careful callout. Cards are independent — open state is local
 * (FR-004). `aria-expanded`/`aria-controls` wire the header to its panel (FR-006).
 *
 * @example
 * <HelpGuideCard guide={guide} iconName="files" defaultOpen />
 */
export function HelpGuideCard({guide, iconName, defaultOpen = false}: HelpGuideCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  const Icon = helpIcons[iconName];

  return (
    <div
      className={cx(
        'overflow-hidden rounded-[10px] border bg-surface',
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
        <span className="min-w-0 flex-1">
          <span className="block text-[15px] font-semibold text-text">{guide.title}</span>
          <span className="mt-0.5 block text-[13px] text-text-2">{guide.subtitle}</span>
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
          <div className="px-[18px] pb-5 pl-[68px] pt-1">
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
        warning ? 'border-[#f6caca] bg-danger-soft' : 'border-accent-border bg-accent-soft'
      )}>
      <Icon className={cx('mt-px h-4 w-4 flex-none', warning ? 'text-danger' : 'text-accent-text')} />
      <span>
        <strong className="font-semibold">{warning ? 'Careful. ' : 'Tip. '}</strong>
        {renderInline(callout.text)}
      </span>
    </div>
  );
}
