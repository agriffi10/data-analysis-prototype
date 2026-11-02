---
type: Decision
title: "`??` does not fall back on `''`, and a helper returning `''` is a trap for every consumer"
description: "`cx()` returns `undefined` when nothing is truthy and `Modal` falls back with `||`, because `??` does not fall back on `''`: a shared helper returning an empty string defeats every consumer's default."
---

`cx()` returned `string` — never `undefined` — so `FormDialog`'s
`cx(scrollBody && '…', className)` handed `Modal` an **empty string** whenever its caller passed
neither prop, and `Modal`'s `className ?? 'max-w-md'` took that as a deliberate choice to have no
width. The panel's `w-full` then filled the viewport. **Nine dialogs**, one line: `New folder` and
`New shared connection` measured 1372px in a 1400px viewport with `max-width: none`, against
`Create table`'s correct 448px.

Fixed in the shared layer **twice**, deliberately: `cx` returns `undefined` when nothing is truthy
(so the trap is gone for the next `??` consumer anywhere in the app), and `Modal` uses `||` (so a
caller composing its own class string is still safe, which is what the AC's `className=""` test
requires). Widening `cx`'s return type to `string | undefined` type-checked at every call site with
no change — the two that wanted a string for `aria-describedby` already coerced with
`|| undefined`.

**Note the direction of the bypass.** The four dialogs that hand-roll their chrome pass an explicit
`max-w-lg` and were therefore *unaffected*; the nine that correctly used the abstraction were the
broken ones. That is an argument for fixing the shared layer, not for copying more.

## History

### 2026-08-14

- **Settled:** entered the register.
