/** An opaque colour, `#rgb` or `#rrggbb`. */
export type Hex = `#${string}`;

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/**
 * The three channels of an opaque hex colour, 0–255.
 *
 * Refuses anything that is not `#rgb` or `#rrggbb` rather than computing on it. A permissive
 * parse is worse than useless here: `parseInt` returns `NaN` for `'zzz'`, the `NaN` propagates
 * through the ratio, and the comparison against a threshold comes back false — so a typo'd
 * colour clears every floor with nothing red, which is the failure the contrast harness exists
 * to prevent. A five-digit hex is the same trap wearing a plausible number.
 *
 * @param hex - The colour to parse.
 * @returns Its red, green and blue channels.
 * @throws Error naming the offending value when it is not an opaque hex colour.
 */
function channels(hex: string): [number, number, number] {
  if (!HEX.test(hex)) throw new Error(`not an opaque hex colour: ${JSON.stringify(hex)}`);
  const full = hex.length === 4 ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}` : hex;
  const n = parseInt(full.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * `fg` painted at `alpha` over `bg`, as the browser composites it.
 *
 * Alpha is spent in sRGB, before the luminance curve, which is why this cannot be folded into
 * the ratio: a translucent colour is a DIFFERENT colour, and measuring its token at full
 * strength overstates every ratio it appears in. What decides the result is whatever happens to
 * be behind it, so a pairing that uses one has to name that too — a translucent bar reads
 * safely over the page and not over a saturated band scrolling under it.
 *
 * @param fg - The colour being painted.
 * @param bg - What it is painted over, opaque.
 * @param alpha - The foreground's opacity, 0 to 1.
 * @returns The opaque colour the two produce.
 * @throws Error when either colour is not an opaque hex, or `alpha` is outside 0–1.
 */
export function composite(fg: Hex, bg: Hex, alpha: number): Hex {
  if (!(alpha >= 0 && alpha <= 1)) throw new Error(`alpha outside 0–1: ${JSON.stringify(alpha)}`);
  const front = channels(fg);
  const back = channels(bg);
  const mix = (i: number) => Math.round(alpha * front[i] + (1 - alpha) * back[i]);
  return `#${[0, 1, 2].map((i) => mix(i).toString(16).padStart(2, '0')).join('')}`;
}

/**
 * WCAG 2.2 relative luminance of an opaque colour, 0 (black) to 1 (white).
 *
 * @param hex - The colour to measure.
 * @returns Its relative luminance.
 * @throws Error when `hex` is not an opaque hex colour.
 */
export function relativeLuminance(hex: Hex): number {
  const [r, g, b] = channels(hex);
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * WCAG 2.2 contrast ratio between two opaque colours, 1 to 21.
 *
 * Symmetric: which colour is the foreground makes no difference to the number.
 *
 * @param a - One colour.
 * @param b - The other.
 * @returns Their contrast ratio.
 * @throws Error when either is not an opaque hex colour.
 */
export function contrastRatio(a: Hex, b: Hex): number {
  const [high, low] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}
