import type {ReactNode} from 'react';

/** Each primary destination's glyph, drawn once in a 24-unit stroke box. */
const GLYPHS = {
  files: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  query: (
    <>
      <ellipse
        cx="12"
        cy="6"
        rx="8"
        ry="3"
      />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </>
  ),
  explore: (
    <>
      <rect
        x="3"
        y="4"
        width="18"
        height="16"
        rx="2"
      />
      <path d="M3 9h18M9 9v11" />
    </>
  ),
  connections: (
    <>
      <circle
        cx="7"
        cy="7"
        r="3"
      />
      <circle
        cx="17"
        cy="17"
        r="3"
      />
      <path d="M10 7h4a3 3 0 0 1 3 3v4M7 10v4a3 3 0 0 0 3 3h4" />
    </>
  ),
  dataQuality: (
    <>
      <path d="M9 12l2 2 4-4" />
      <path d="M21 12a9 9 0 1 1-3.5-7.1" />
    </>
  )
} satisfies Record<string, ReactNode>;

/** A primary destination the app draws a glyph for. */
export type Destination = keyof typeof GLYPHS;

type DestinationIconProps = {
  destination: Destination;
  className?: string;
};

/**
 * The glyph a primary destination is known by, shared by the top bar, the phone's nav drawer and
 * Help — so a guide carries the same picture as the tab it describes. Decorative: the label beside
 * it names the destination.
 *
 * @example
 * <DestinationIcon destination="explore" className="h-4 w-4" />
 */
export function DestinationIcon({destination, className}: DestinationIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true">
      {GLYPHS[destination]}
    </svg>
  );
}
