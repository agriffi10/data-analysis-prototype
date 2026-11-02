---
type: Decision
title: "At `tablet` the words stay and the decoration waits — the top bar and the selection toolbar (2026-09-10)"
description: "Between `tablet` and `desktop` the top bar and selection toolbar keep every word and drop the decoration; labels never wrap, and a new tab, control or action owes the band sweep."
---

`tablet` is where the top bar's tab strip, its three control labels and the username switch on, and
where the Files selection toolbar's six action labels do; neither row had anything that could
shrink. Squeezed, each wrapped first and overflowed second. On `c4ea4413`, in Chromium with a
classic 15px scrollbar, the bar needed 1029px of `clientWidth` against 885 at an `innerWidth` of
900: it wrapped *Data Explorer* and *Data quality* onto two lines up to about 1044 and overflowed
the page below 960. The toolbar was about 164px short at 900: it wrapped three labels up to about
1064, pushed Delete out of its own border below about 944 and widened the page below about 915.
The header's overflow hid the toolbar's, which is why the 2026-09-10 sweep reported one defect.

**The user chose, from three options for each row, the one that keeps every word and drops what
nothing depends on.** The username text and the tab icons wait for `desktop` beside the wordmark
(the dark-palette entry's *What paid for the room is the WORDMARK* ranks the tab strip and the
labels as what stays); the toolbar's glyphs go at
`tablet` and come back at `desktop`, mobile staying glyph-only, and its gap and button padding
tighten between the two. Declined: making Help, Notifications and Theme icon-only below `desktop`,
which reverses that ranking; tightening the toolbar's spacing alone, which fits at 900 only because
the wrapping absorbs it; and withholding every toolbar label until `desktop`, which loses the words
at 1024 and 1280.

**No label wraps in either row any more** (`whitespace-nowrap`), so a row that is short of room
overflows where a width sweep sees it rather than wrapping where it looks almost right. The two
terms that grow with data are bounded instead: the username is capped with an ellipsis at `desktop`,
and from `tablet` up the selection count truncates. Below `tablet` it still wraps, because a
truncated "128 selected" reads as "12…" — a wrong number is worse than a second line. What is left
in the band no longer depends on who is signed in or what they selected, only on the layout and the
font. On the commit that added this entry, at 900 with the scrollbar showing, that was 14px in the
bar under Inter (21 under the `system-ui` fallback) and 38px in the toolbar with *Select all*. A new
tab, control or toolbar action spends it, and owes the band sweep in `docs/testing/e2e.md` §4.15.

**The cost, stated as the wordmark's is in the dark-palette entry:** between 900 and 1299 the
signed-in user's own name is on the bar only as the avatar's two letters, and in the account
trigger's `aria-label`.

## History

### 2026-09-10

- **Settled:** entered the register.
