---
type: Decision
title: "The data-quality reports folder is declared once per tree, in the app-managed owners"
description: "`_data-quality-reports/` is declared once per tree, as `DATA_QUALITY_REPORTS_FOLDER` in the app-managed owners; the writer and every refusal list take it from there, the sweep refuses a new declaration or construction, and the IAM templates still spell the name."
---

`_data-quality-reports/` never moved, but the data-quality plane's writer spelled it and so did
every refusal guarding it — the check-source and archive-source lists, the conversion and file-ops
destination lists, the API's object-route write refusal, and the browser's hidden, picker-locked and
archive-reserved lists. Some pairs were already held equal (the browser's lists against the planes',
the conversion list against its role's Deny), but nothing held any refusal to the WRITER. A rename
the writer took would have left every refusal matching the old name and denying nobody, and no test
would have reddened, because each list's own test asserts its own copy.

**The fix is the owner, not a guard over the copies.** `cpcommon.app_managed` and
`lib/appManagedPaths.ts` declare `DATA_QUALITY_REPORTS_FOLDER`, every list imports it, the writer
builds its prefix through `app_managed_prefix` and the browser's report keys through
`appManagedPrefix`, and the name joined the sweep's path-shaped names so a new declaration or construction in either
tree is refused. An equality test was the alternative and was not taken: it can only hold equal the
copies it was told about, and a new one is exactly what it would miss. The sweep refuses only what it
can parse as a declaration or a construction — it cannot see the name inside a longer string, a
format string or a regex, nor through a renamed import or a local alias — which is the same limit it
has for every name it guards.

It joined `SPACE_FOLDERS` too, since that tuple is every app-managed folder the owner declares in a
space bucket, and the conversion plane's own literal came out of `PROTECTED_DESTINATIONS` so the
member is not listed twice. It is not in `MOVING_FOLDERS`, and a row in each tree pins its depth-one
home. The IAM templates still spell the name. The conversion role's write Deny is held to the owner
anyway, because its test builds the expected Resources from `PROTECTED_DESTINATIONS`; the
data-quality role's write grant is held by nothing, and a rename that missed it would fail loudly as
a denied write rather than quietly.

## History

### 2026-09-16

- **Settled:** entered the register.
