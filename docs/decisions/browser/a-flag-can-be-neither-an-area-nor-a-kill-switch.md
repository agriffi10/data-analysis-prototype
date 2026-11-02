---
type: Decision
title: "A flag can be neither an area nor a kill switch (SPEC-223)"
description: "`resultsConversion` is a presentation flag over the Save-results format choice only: off, the format is always CSV, and a CSV save still goes to the plane when the grid hides or reorders columns."
---

`resultsConversion` is the seventh key and the third kind: a **presentation** flag over one
control — the Save-results dialog's format choice. Off, the dialog offers no format; the enqueue
route is live and ungated either way, so it hides three options and takes nobody's access away.
**It does not gate whether a save copies or converts, and since SPEC-239 that is a distinction
with a case behind it:** off, the format is always CSV, and a CSV save still goes to the plane
when the grid is hiding or reordering columns, because a copy cannot produce that file. The
alternative — reading the flag as a second answer to what a save should WRITE — hands a user who
hid a column a file that still has it, which is the bug the spec exists to close. The taxonomy above is therefore ~~five areas, one kill switch and one
presentation flag~~ **— since SPEC-246, five areas, two kill switches (`asyncFileOperations` and
`archive`) and one presentation flag —** and the sentence naming the first two is not a complete
account of the set.

Its two registry rows are the same control on two routes, and the completion notification's link
gets **none**: that link is a `/files` one, already covered by the notification row's link gate (derived from the
destination since 2026-09-25), on the precedent the archive plane's link set.

## History

### 2026-09-25

- **Changed:** The notification row's link gate, which covers the completion notification's `/files` link, became derived from the destination.

### 2026-09-07

- **Settled:** SPEC-223.
