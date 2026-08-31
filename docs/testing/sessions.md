# Live-check session log

What was actually run against deployed prod, when, and what it returned. **This is the evidence
behind every DISCHARGED row** in [`owed.md`](owed.md) — the scripts say what to assert, this says
what happened.

Add a new section at the top after each session, following [`e2e.md`](e2e.md) §5. Record the
username, the browser and width, and every instrument used — each one is a way the run differed
from a user's.

---

## Live-check session — 2026-08-30 (SPEC-201 step one: the planes stop verifying tokens, §H.1–H.3)

Run against **`https://portal.dataquarry.app`**, the deployed load balancer, signed in as
**`agriffith`** in **Chromium** at desktop width. `main` at **`ff3a76b6`** — confirmed as the
running build by `api.dataquarry.app/healthz`, which reported that exact sha, so the planes under
test were the ones this spec changed.

**Instruments:** `document.visibilityState` pinned `visible` (a hidden window pauses polling and a
healthy request reads as hung); the browser's own network panel for the enqueue status codes.
Nothing else — every action below was taken through the UI as a user would.

**This is a Chromium pass and therefore corroborates rather than discharges** anything
browser-specific; Safari is the browser in use. Nothing here is browser-specific — the claims are
about what the control planes did — so that is recorded rather than limiting.

### §H.1 — one real request per plane, all eight, each producing its normal notification

Every plane reached its normal terminal state. Quoting the notifications, which are the plane's own
words rather than my summary:

| Plane | What was done | What came back |
|---|---|---|
| file-ops | Copied folder `dq-smoke` into `arcb_live` | *Copied 1 item to "arcb_live".* |
| data-quality | Quality check on `agriffith/dq-smoke` | *Data quality check on "agriffith/dq-smoke" finished — open the report for details.* |
| table-builder (create) | Built `spec201_live` from `agriffith/dq151a` | *Table "spec201_live" is ready to query in "agriffith".* |
| table-builder (refresh) | Refreshed it | *Table "spec201_live" is already up to date - no schema changes were found.* |
| file-send | Sent `beta.csv` to `agriffith_three` | *Sent "beta.csv" (1 file) to user "agriffith_three".* |
| shared-space (create) | Created `spec201_live_check` | *Creating shared workspace…* then *Your shared workspace "spec201_live_check" is ready.* |
| shared-space (delete, owner-only) | Deleted it as cleanup | *Deleting shared workspace…* then *You deleted the shared workspace "spec201_live_check".* |
| table-share | Shared `spec201_live` to `agriffith_three` | *Shared "spec201_live" to user "agriffith_three" as "spec201_live".* |
| archive | Archived `arcb_live/dq-smoke` — the copy made above, so nothing pre-existing was swept | *Archived 4 files (773 B). … Archive id: `7150f49c-e375-44d3-8aa6-e546af9ffa0b`* |

Ten verbs across all eight planes. Each was the first invocation of that function since the deploy,
so each was a **cold start** — which is the half no offline gate can reach: this change removed an
import and two required environment variables from a dozen functions at once, and a shared layer's
import-time failure shows only at cold start.

Two corroborating observations, not asked for and worth keeping: the table built above was
immediately **queryable** (5 rows, 35 B scanned) through the Data Explorer, so the catalog and
Athena paths still work under the changed identity; and `spec201_live_check` appeared in the
database rail, so the shared space was **fully provisioned** — Glue database and Lake Formation
grants — not merely recorded.

### §H.3 — notifications, both branches, in one pass

**The user branch:** marking one notification read from the UI dropped the unread count 4 → 3 and
rewrote the inbox. That path carries the identity block and is refused without one.

**The `create` branch:** every row in the table above. Each was written by a control plane's own
execution role, with a body `username`, **no actor and no token**. This is the branch a
`trusted_actor` hoisted above `_resolve_username`'s test silently kills, and the failure would be
invisible — the producers notify best-effort, so the work completes and the user is simply never
told. Both branches in one pass, which is the only way either is evidence.

### §H.2 — partially run, and the half that ran is the one that mattered most

**Sending to a user that does not exist** returned *Couldn't send to user "nosuchuser_spec201":
there is no user with that name.*

That is the recipient-existence check — `cpcommon.cognito.user_exists` → `admin_get_user` — and it
is the riskiest line in this change. `COGNITO_USER_POOL_ID` stopped being a fleet-wide required
variable here and became a **lazy `config.require`** read on the three planes that resolve a user;
a lazily-required variable that is missing raises **mid-request**, not at cold start, so a wrong
Terraform mapping would have surfaced exactly here and nowhere earlier. It came back as a clean,
correctly-worded refusal naming the user.

**The rest of §H.2 is OWED**: a non-member's space, a foreign prefix and an out-of-root key all
need a **second account**, since the point is that the API writes a genuine verified
`identity.actor` for somebody who is not authorized, and a hand-crafted body cannot reach the queue.

### Not run

§H.4 (the staged pre-cutover message) and §H.5 (`assurance` refused live with an `interactive`
neighbour) both hand-enqueue onto a request queue. After SPEC-200 only the **API's execution role**
holds `sqs:SendMessage` there — a laptop identity has no grant, which is the isolation working —
so both stay owed with the recipe recorded. §H.6 and §H.7 belong to step two.

---

## Live-check session — 2026-08-27 (the auth boundary and the identity layer, §D and §E)

Run against **`https://api.dataquarry.app`**, `main` at `951e6a8a`, signed in as **`agriffith_three`**
in **Chrome** (desktop). Instruments: `curl` from the laptop, in-page `fetch` from the deployed
CloudFront origin, and the log objects under `logs/service=api/year=2026/month=08/day=27/`.

**Why now rather than at SPEC-202.** SPEC-197 FR-014 deletes both probe routes, and conditions each
deletion on the verification that route exists for having been run. The arc's 2026-08-27 decision had
moved all live verification to SPEC-202 — which would have deleted the only instruments that can
observe the boundary and the isolation model before either was ever observed. Settled with Andrew:
run §D and §E first, then delete. **This section is what made that deletion legitimate.**

### Passed

| Check | Result |
|---|---|
| §E.0 — the claims are in the token | `cognito:username` and `custom:shared_space_1` both present; RS256, `kid` present, issuer `…/us-east-1_zOlWYrE9K` |
| §D.1 — the happy path | `200 {"username": "agriffith_three"}` — the username, not the `sub` |
| §D.2 — four refusals | no-token / access-token / flipped-payload / foreign-key all **401**, all four bodies `sha256 aebffec4…9261` (one digest, four times), `www-authenticate: Bearer` on all four, body exactly `{"error": "unauthorized", "code": "SessionExpired"}`. A wrong *scheme* (`Basic`) answers identically. |
| §E.1 / §E.2 (username half) / §E.3 | `GET /_identity/self` → `{"username": "agriffith_three", "spaceCount": 1, "ownPrefixListable": true, "foreignPrefixListable": false}` |
| §E.7 — a real `env` and build sha | `env: "prod"` on all 44 of the day's records; `version` a real commit sha, never `0.0.0` |
| The field rule, on real traffic | Across the whole day's records: zero emails, zero `@`, zero `Bearer`, zero `eyJ` |
| CORS negative control | `Origin: https://example.invalid` → **no** `access-control-allow-origin`. Both real origins are echoed, so nothing has been narrowed. |

`ownPrefixListable: true` is the observation that proves the `username` tag was stamped: the portal
role grants `s3:ListBucket` **only** under `"s3:prefix": ["${aws:PrincipalTag/username}/", …]`, so it
is unreachable without it. `foreignPrefixListable: false` is AWS refusing — the isolation model
working, and the negative control that a probe asserting only its own prefix would pass with the
model deleted.

### Failed — and it is fixed in SPEC-197

**Every bearer-carrying request from a browser was impossible.** `infra/modules/api/apigateway.tf`
declares only `$default`, which matches `OPTIONS`; AWS auto-answers a preflight only when no route
matches, so preflights reached the Lambda and were refused deny-by-default:

```
OPTIONS /_auth/whoami  →  401  {"error": "unauthorized", "code": "SessionExpired"}
```

Browsers require a 2xx preflight, so every such `fetch` failed as an opaque `TypeError`. Isolated
from the page: `fetch(API + '/healthz')` (simple, no preflight) → **200**; the same URL with an
`authorization` header → **threw**. So CSP, DNS, TLS and the origin echo were all fine and only the
preflight was wrong — which is exactly the failure mode that reads to a user as "the API is down".

Invisible to every offline test and to `curl`. **SPEC-197 answers `OPTIONS` in the router, before
authentication**, and a browser is the only instrument that can confirm it — recorded as owed below.

### Still owed after this session

- **D.3 — a genuinely expired token.** Needs the app client's ID-token validity temporarily cut to
  its 5-minute minimum and then restored; not run.
- **D.5 in Safari.** Chrome only, and Safari is the browser in use.
- **D.6 — the token-segment scrub against a real refusal.** The flipped-payload call was made; the
  records for that window had not yet been swept when the session ended.
- **§E.2's slot half.** `agriffith_three` belongs to **one** shared space, and `spaceCount` is
  counted from the token's claims — it reads the same with every slot tag dropped. → SPEC-198.
- **§E.4, §E.5, §E.8, §E.9** — untouched by this session.
- **The preflight fix, live.** Only a browser can confirm it.

---

## Live-check session — 2026-08-27 (the SPA container, SPEC-194)

Run against **`https://portal.dataquarry.app`**, the deployed load balancer, immediately after
`Deploy SPA image` reported `desired=1 running=1 rollout=COMPLETED` on the revision it registered
(`main` at `783275d1`, task definition `dat-prod-spa:6`, 20 configuration keys carried).

**The instrument was `curl`, not a browser, and that is the whole limit of this session.** Every
assertion below is about bytes on the wire. **Nothing here discharges a rendering, a script
execution or a sign-in** — which is exactly why §C.1 (fresh sign-in from a private window), §C.2
(the CSP's negative control) and §C.3 (Safari) remain owed rather than being marked off by it.

**Everything checked passed. Nothing was found broken.**

| What | Result |
|---|---|
| The full security header set on **five** response classes — the shell, a deep link, a hashed asset, the honest 404 and `/config.json` | CSP, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP and CORP present on every one. **This is the ALB assertion**: nothing between the container and the client adds or strips a header |
| HSTS | `max-age=31536000; includeSubDomains`, **no `preload`** |
| `Cross-Origin-Embedder-Policy` | absent on every response, by decision |
| `Server` | exactly `nginx`, no version |
| Cache classes | `/` and a deep link `no-cache`; `/assets/<hashed>` `public, max-age=31536000, immutable`; `/config.json` and `/healthz` `no-store` |
| `GET /config.json` | 200 / `application/json` / `no-store`, **21 keys** (`version` + the 20 classified), `version: 1` |
| `GET /healthz` | 200 / `text/plain`, body exactly `ok` |
| `GET /assets/index-DEADBEEF.js` | **404**, `application/javascript`, body `not found` — the honest 404, not the shell |
| A hashed asset with `Accept-Encoding: gzip` | `content-encoding: gzip` + `vary: Accept-Encoding` |
| The same asset with `Accept-Encoding: br` | **no** `content-encoding` — the accepted brotli residual |
| The served `connect-src` | all **ten** terms, including the two whose loss a signed-in tester cannot see: the `cognito-idp` endpoint and the Hosted UI domain |

**Not exercised, and not to be read as passing:** any file operation. Bucket CORS admits the
CloudFront origin and localhost only, so the browser's direct S3 calls fail preflight from this
origin until the presigned-bytes spec widens it. Expected, and stated so it is not diagnosed as a
container defect.

## Live-check session — 2026-08-24 (runtime configuration, SPEC-192)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`) in **Chromium via the agent's browser
tooling**, not Safari and not a user's profile — so this corroborates rendering and cannot discharge
it. Two loads: one after the document was published and read nobody (`main` at `1af1f8bb`), one after
the switchover (`main` at `9a3568de`).

**Everything checked passed.** Nothing was found broken.

### What was run

| Check | Result |
|---|---|
| `GET /config.json` headers | **200**, `content-type: application/json`, `cache-control: no-store`, `x-cache: Miss from cloudfront`, `server: CloudFront` (the S3 banner stripped) |
| Security headers on that path | CSP, HSTS and `x-content-type-options` all present — the response-headers policy really is attached to the new cache behaviour, which is per-behaviour and not inherited |
| Document contents | `version: 1`, all 20 classified keys present, only `apiBaseUrl` empty (correct — no API yet) |
| Edge caching | A second request is **still** `x-cache: Miss from cloudfront`, so `Managed-CachingDisabled` is live |
| After the switchover: fetch count | **Exactly one** `config.json` request per page load — `performance.getEntriesByType('resource')`, 77 ms in, 54 ms duration. The two entries in the network log were two page loads, not a double fetch |
| After the switchover: console | **Zero** errors |
| After the switchover: the values are in USE | **No configuration alert and zero `[role=alert]` nodes.** That is the observable: had the document's four Cognito values not reached `Amplify.configure()`, `isAmplifyConfigured()` would be false and `Header` would render one |
| App shell | `/` returns 200 `text/html`; the landing page renders in full |

### Not run, and still owed

The staged **hard-failure** and **unparseable** paths, the **promotion** check, and a **fresh sign-in
from a private window** — the first three need a deliberately broken or changed document published to
the bucket, the fourth needs a real Hosted UI round trip. All four are written up as
[`arc-b-api-container-e2e.md`](arc-b-api-container-e2e.md) §A.1–A.4 and carried in
[`owed.md`](owed.md).

---

## Live-check session — 2026-08-16 (Data Explorer §2 + copy/export, SPEC-179/183, partitioned refresh, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `94c892b`) as
`agriffith_three`, in **Chrome at 1512×786**. Safari waived for behavioural checks by the
2026-08-15 user decision, now recorded at `e2e.md` §4.15; the CSS list is untouched here.

**Nothing was found broken.** Every check below passed. The two findings at the foot are about the
*instrument*, not the app — and one of them would have let a future session record a pass it never
ran.

### The upload constraint is gone, and it is what unblocked most of this

The script said *"Andrew has to do the upload"* because a laptop IAM user cannot write
`dat-prod-user-space`. That is still true of the CLI, but it is **not** a limit on a live-check
session: the Chrome extension's `file_upload` puts a local file straight into the portal's own
`<input type=file>`, so the upload goes through the **portal role** like any other. Everything
below that needed a fixture — the 150-row table, the partitioned table, the added-column file —
was uploaded that way.

### Data Explorer (`e2e.md`)

Fixture `agriffith_three.explorer150`, built from the committed
`docs/testing/fixtures/explorer-fixture-150.csv` in a new empty folder: 150 rows, `id/region/owner/qty`
all string, nine `O'Brien` rows, two empty `qty` cells. Executions were counted by patching
`window.fetch` and reading `x-amz-target`, as on 2026-08-15.

| Check | Executions | Result |
|---|---|---|
| **§2 paging produces NONE** — Next, Prev, Next | **0** `StartQueryExecution` | PASS — rows 1–100 → 101–150 → back → 101–150, one `GetQueryResults` for the uncached page, total held at **2.9 KB** |
| SPEC-179 step 3 — Query rail ⋮ → *Explore data* | — | PASS — lands on `/explore` with that table open |
| SPEC-179 step 4 — params carried then dropped | — | PASS — `push /explore?space&db&table`, then `replace /explore` with **no** params |
| SPEC-179 step 4 — reload | — | PASS — the 2 tabs I had, **not** a third copy of the linked table |
| SPEC-183 step 4 — save from the Query workspace | 1 PUT | PASS — `workspace-direction` saved to My files, reopened from **Saved queries** with its exact SQL |
| SPEC-183 step 4 — the Explorer offers no way back | — | PASS — the toolbar's 17 controls include *Save as query* and **no** load/open affordance |
| SPEC-183 step 5 — save into a **shared space** | 1 PUT (cross-bucket) | PASS — see below |

**SPEC-183 step 5 in full, because it took two attempts.** The first save (*Save as query* from the
`explorer150` tab, destination `livecheck_186`) wrote `explorer-shared-dest.sql` — a HEAD on the
exact key then one cross-bucket PUT, plus a HEAD+PUT that created `saved_queries/DO_NOT_DELETE.txt`
in that space, and the toast *Saved "explorer-shared-dest" to livecheck_186.* **But the exploration
was unfiltered**, and the step says *"repeat step 1"* — a filtered, ordered exploration. Its **45 B**
body is the tell. So it was repeated properly: *Filter by this value* on `region = west` (1
execution, rows 1–37, 2.9 KB), then *Save as query* → `livecheck_186`. The listing then held
`explorer-shared-dest.sql` **45 B** beside `explorer-shared-filtered.sql` **69 B** — the 24 bytes
being the `WHERE`, which is what "the rendered SQL, not a bare `SELECT *`" looks like from the
outside. **Filtered but not ordered** — step 1 asks for both, and the 24-byte delta is the proof it
was the `WHERE` alone. What step 5 exists to test is the cross-bucket destination, which is
unaffected; the ordering half is covered by SPEC-183's round-trip row, discharged 2026-08-15.

Two incidentals from that: the Save dialog **pre-fills the last name used** and the field is not
selected on focus, so a straight `type` appends (this produced
`explorer-shared-destexplorer-shared-filtered.sql`, renamed afterwards) — and the rename itself
confirms the SPEC-173 pairing, that a `.sql` file **inside** `saved_queries/` is ordinary while the
folder is not.

#### SPEC-185 copy and export

Copy was read by patching `navigator.clipboard.writeText` and recording what the app wrote — the
payload itself, rather than a paste into a spreadsheet.

| Step | Result |
|---|---|
| 1. Rectangle, ⌘C | PASS — `1\tsouth\tJones` / `2\teast\tNakamura`, grid order |
| 1. NULL vs empty | PASS — `796\t796` then `\tNULL`: the empty cell copies empty, the NULL copies as `NULL` |
| 2. ⌘-click two non-adjacent cells | PASS — exactly the bounding rectangle: `1\t\t` / `\t\t` / `\t\tO'Brien` |
| 3. Column header | PASS — **100** rows (1…100), one column, **0** executions — the loaded page, not the table |
| 4. **Copy… → JSON** | PASS — `"qty": ""` beside `"qty_null": null`, distinguishable |
| 5. Export before anything has run | PASS — `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`, reason *"Run a query first — export saves the results Athena returned."* |
| 6. Export → `explorer-export` → My files | PASS — one HEAD then one PUT, success toast, **0** executions |
| 7. **Row count in the exported CSV** | PASS — **151 lines** = header + all **150** rows, header `"id","region","owner","qty"`, last row `id 150`, while the page held 100 |
| 8. Zero executions across 1–7 | PASS — asserted per step; the running total never left 2.9 KB |
| 9. Export again, same name | PASS — *Overwrite "explorer-export.csv"?* before anything was replaced |
| 10. Export into a shared space | PASS — cross-bucket HEAD+PUT, and `explorer-export-shared.csv` (4.1 KB) is in `livecheck_186` |

**How step 7 read the file, since a laptop identity cannot.** `dat-prod-user-space` is closed to the
IAM user, so the object was opened the way a user would: Details → **Download** in the file browser,
with `window.open` and `HTMLAnchorElement.prototype.click` patched to capture the presigned URL, and
the fetch + line count done **inside the page** so the URL itself never left the browser.

**Step 4 needed a NULL and the CSV fixture has none** — the Table Builder makes CSV columns
all-string, so an empty cell is `''` and never SQL NULL. A view supplies one:

```sql
CREATE VIEW agriffith_three.explorer150_nulls AS
SELECT id, region, owner, qty, NULLIF(qty, '') AS qty_null FROM agriffith_three.explorer150
```

Row 7 then renders *(empty)* in `qty` and *NULL* in `qty_null` side by side, which is SPEC-180
FR-003 visible on screen and the pair steps 1 and 4 are actually about.

#### SPEC-185 Help

PASS, all three steps. The **Data Explorer** section carries **five** guides. The filtering guide's
callout reads *"Careful. Every apply runs a real query against Athena and scans data, which is what
it costs."* Nothing in the section mentions a chart, a graph, cell editing, named filters or a
References panel, and the save guide states plainly that a saved exploration opens in the Query tab
as SQL rather than back in the Explorer.

### Table Builder — the partitioned refresh variant (`e2e.md`)

The owed partitioned twin of the FR-010 add/remove sequence. Fixture `agriffith_three.partfix` over
`partfix/year=2025/part1.csv` + `partfix/year=2026/part2.csv`, declared partition key `year`
(string, values `2025, 2026`).

| Step | Result |
|---|---|
| Create — partition projection | PASS — `SELECT * … WHERE year = '2025' LIMIT 5` returned rows, 122 B, **no** load step |
| 1–2. Upload `year=2025/part0.csv` (`id,region,amount,channel`), Refresh | PASS — *Table "partfix" was refreshed in "agriffith_three": **1 column added**.*; rail reads `id, region, amount, channel` |
| **Partition key survives the refresh** | PASS — the same partition-filtered SELECT still returns rows, now with `channel` **and** `year` |
| 3. Delete `part0.csv`, refresh with **no** opt-in | PASS — *Couldn't refresh table "partfix": these columns are no longer in the data and would be removed: **channel**. Nothing was changed…* |
| 4. Follow the notification link | PASS — `/query?refreshTable=…&removed=channel`; the dialog opens **pre-armed** ("A previous refresh was stopped… channel"), opt-in **unchecked**, and *Refresh table* is `aria-disabled="true"` / `disabled` **false** / `tabIndex 0` with *"Tick "Allow columns to be removed" to refresh this table."* |
| 5. Tick the opt-in and submit | PASS — *1 column removed* |
| After the removal | PASS — partition filter still works, `year` still projected, `channel` gone |

`part0.csv` is the load-bearing name: it sorts first **within the first partition**, so it is the
first key in the whole listing and therefore the inference sample.

### Saved queries — the client-side refusal (`e2e.md` §4.7), the owed SHARED half

PASS, byte-exact, with its control. In `livecheck_186` (whose `saved_queries/` folder the SPEC-183
step-5 save had just created):

- Delete — `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`,
  `Saved queries live in this folder, so it can’t be deleted.`
- Move — same, `Saved queries live in this folder, so it can’t be moved or renamed.`
- Clicking Delete opened **zero** dialogs and **zero** alertdialogs, and — with `window.fetch`
  patched to record every request by method and path — issued **zero requests of any kind**. That
  is step 3's third clause, *"no request is sent"*, observed for the shared case directly rather
  than inherited. **The 2026-08-14 trace still stands for what it established** — that the portal
  issues zero `DeleteObject` against the marker, which is the premise `e2e.md` is
  built on. What it cannot carry is the **FR-002 affordance**, because it watched the older
  behaviour where the refusal arrived only after the confirm.
- **Control:** an ordinary `marker_control` folder beside it showed both controls with no
  `aria-disabled` and no reason, its confirm opened (*"…and everything inside it? … This can't be
  undone."*), and it deleted cleanly.

The 2026-08-15 personal half stands; check 2 (the bucket-policy Deny, CLI-only) is still owed.

### Findings — both about the instrument

**1. A Chrome window that is hidden at the OS level pauses the polling, and it looks exactly like a
hung query.** Opening a table sat on **"Running…"** for 35 s having issued exactly **one**
`GetQueryExecution`, 254 ms after the start. `document.hasFocus()` was `true` while
`document.visibilityState` was **`hidden`**, and TanStack Query's focus manager suspends
`refetchInterval` on that. Overriding `visibilityState`/`hidden` to visible and dispatching
`visibilitychange` resumed the poll and the rows arrived in seconds. **This is not an app defect** —
a real user's tab fires `visibilitychange` on return and the poll resumes — but a session that does
not know it will file the app's own >5-minute "Running…" note as a live bug. Every check above was
run with that override in place.

**2. `resize_window` reports success, moves `outerWidth`, and does NOT change the viewport the page
sees.** Asked for 400×800 it answered *"Successfully resized window … to 400x800"* while
`innerWidth`, `documentElement.clientWidth` and every media query stayed at the 1512px desktop
values (`min-width:1300px` still matching). So the tool cannot stage a narrow pass at all — this is
stronger than 2026-08-15's "Chrome's minimum is 606px", because there the layout genuinely changed
and here **nothing does while the call reports success**. The 400px pass stays **owed in full** and
needs DevTools device emulation.

Also worth carrying: the refresh dialog is `role="alertdialog"`, not `dialog`, so a
`querySelector('[role="dialog"]')` finds nothing there — the mirror of the `Drawer` trap recorded
on 2026-08-15.

### Still owed after this session

- The **400px** pass and the **Safari** CSS list (`e2e.md`).
- SPEC-179's shared-space pass as a **non-owner member**, and SPEC-186 FR-008's
  add → acknowledge → roster re-run — both need a second account.
- `owed.md` §2.1 (the `DO_NOT_DELETE.txt` Deny, CLI + portal-role credentials).
- SPEC-157's refresh lock, SPEC-149's `Description`/comment preservation read-back (needs the
  verification role, deliberately not created), and `SaveQueryDialog`'s "nowhere to save" width.
- The whole **archive/restore** arc (`e2e.md`). Deliberately not attempted here:
  archiving removes files from a space and a restore is a 3–5 hour **billed, uncancellable**
  Glacier retrieval, which is not a call to make unattended.

### Fixtures created (deletable once the remaining checks are run)

`agriffith_three`: `explorer150/` + table `explorer150`, view `explorer150_nulls`, `partfix/`
(`year=2025/`, `year=2026/`) + table `partfix`, `explorer-export.csv`,
`saved_queries/workspace-direction.sql`.
`livecheck_186`: `explorer-export-shared.csv`, `saved_queries/explorer-shared-dest.sql` and
`saved_queries/explorer-shared-filtered.sql`.

---

## Live-check session — 2026-08-15 (Data Explorer arc, SPEC-186 dialogs, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `88caf54`) as
`agriffith_three`, in **Chrome at 1400×730**. Safari waived by user decision — see the amendment at
`e2e.md` §4.15.

> **The date.** The session ran on the evening of **2026-08-14 US Eastern**, which is
> **2026-08-15 UTC**. Everything is dated 2026-08-15 here and in the script, matching the UTC
> timestamps on the deploys and log records cited below. Where the script says a thing was
> "measured 2026-08-15", that is this session.

### SPEC-186 FR-005 — `env` and `version` on log records

Read from `s3://dat-prod-athena-admin/logs/service={s}/…/data.jsonl` with the laptop IAM identity
(the admin bucket is readable; the user-space and archive buckets are not).

- **809 post-deploy records** (timestamp > `2026-08-14T20:50Z`) across **four** services —
  `dlq-drain`, `observability`, `notifications`, `auth` — with **zero** carrying an empty `env`,
  an empty `version`, or `version: "0.0.0"`.
- `env` is `"prod"`; `version` is `88caf54e0571580c5ffc9647fef4331855983708`, **equal to HEAD on
  `main`** at the time of the run — so the stamp names the app commit, not a stale or infra one.
- **The boundary is the deploy.** In `logs/service=observability/…/day=14/data.jsonl` the latest
  `version: "0.0.0"` record is `18:44:35Z` and the earliest real-sha record is `18:54:34Z` — the
  SPEC-186 Deploy Lambdas run. Shas observed in order: `0.0.0` → `7d59ca10…` (SPEC-186's own merge)
  → `88caf54e…`.
- CloudTrail on `dat-prod-archive-audit` reports **`IsLogging: true`**, which is the precondition
  the archive script's negative assertion rests on.

**Scope limit, stated because the count invites over-reading:** only those four services have
emitted since the deploy. The other five (`table-builder`, `table-share`, `shared-space`,
`data-quality`, `user-directory`) are idle, so the mechanism is proven and they are **unobserved**,
not verified. Every record in their most recent partitions predates the deploy and legitimately
lacks the fields.

### How executions were counted

**The network panel could not carry these assertions.** `read_network_requests` reports URL,
method and status only — every Athena call is a `POST` to the same host, so it cannot separate
`StartQueryExecution` from `GetQueryExecution`/`GetQueryResults`. Executions were counted by
patching `window.fetch` and reading the **`x-amz-target`** header, with request bodies captured via
`Request.clone().text()` to compare `QueryString` against the disclosed SQL.

**Two instrument traps, both hit and both worth knowing:**

- `read_network_requests` **silently stops capturing after a page navigation**. It reported zero
  Athena *and* zero `cloudfront` requests for a freshly loaded page. A negative from it is
  worthless without a positive control — the same shape as the archive script's trail-is-off
  warning. Every negative below was taken with a positive control in the same window.
- A patched `window.fetch` **does not survive a full page load**. Client-side nav (nav-tab clicks,
  `pushState` + `popstate`) preserves it; `navigate` does not.

### Data Explorer (`e2e.md`)

Fixture `explorer_fixture`: 30 rows, columns `id/region/owner/qty` all **string** (CSV ⇒ all-string
as decided), three `O'Brien` rows, one empty `qty` rendering as *(empty)*.

| Check | Executions | Result |
|---|---|---|
| Open the table | 1 | PASS |
| §1 apply is a new execution + new figure | 1 | PASS — 568 B → 1.1 KB, rows 1–7 |
| §3 cache hit — clear the filter | **0** | PASS — "Loaded from an earlier run in this tab — nothing more scanned", total held |
| §3 cache hit — re-apply the same filter | **0** | PASS — total held |
| §4 `O'Brien` against the real engine | 1 | PASS — rows 1–3, `WHERE "owner" = 'O''Brien'` |
| §5 failed apply | 1 (+retry) | PASS — mapped banner, previous rows kept, toolbar kept |
| §5 history Back | **0** | PASS |
| §5 Forward onto the failed step | **0** | PASS — exact wording + *Run it anyway* |
| SPEC-182 grouping | 1 | PASS — rows 1–4; south 8 / west 7 / east 8 / north 7 |
| SPEC-182 step 4 byte-identity | — | PASS — `identical: true` |
| SPEC-182 percentage absent from SQL, header says `(THIS PAGE)` | — | PASS |
| SPEC-182 Calc | **0** | PASS — across 3 function toggles and 2 reselections |
| SPEC-182 step 6 leaving grouping drops the sort | 1 | PASS — no `ORDER BY "count_all"` |
| SPEC-183 save | 1 PUT | PASS — after a HEAD on the exact key; no sidecar |
| SPEC-183 round trip | — | PASS — reopens with filters + ORDER BY, not a bare `SELECT *` |
| SPEC-179 deep-link refusal | **0** Glue, **0** Athena | PASS — only one S3 read of the user's own space list |

The grouped counts match the fixture exactly, which is what makes the GROUP BY result meaningful
rather than merely present.

### SPEC-186 FR-007 — dialog widths

Root font-size is **14px**, so `max-w-md` (28rem) is **392px** — a checker expecting 448px would
read every pass as a fail. All measured at a 1400px viewport with `max-w-md` present rather than
lost to `w-full`:

CreateFolderDialog, RestoreArchiveDialog, RenameDialog, CreateSharedConnectionDialog,
SaveQueryDialog (normal), CreateViewDialog, FilterValueDialog, AddMembersDialog — **8 of 9 at
392px, PASS**.

**Owed:** `SaveQueryDialog`'s second instance (the "There's nowhere to save this query" state),
which needs the personal space to be unavailable and cannot be staged from the UI.

**Beware:** `Drawer` also carries `role="dialog"`. Measuring `querySelector('[role="dialog"]')`
with a drawer open returns the **drawer** (440px, no `max-w-md`), not the modal. Select by title.

**These are RENDERING assertions, so Chrome corroborates them and Safari is still owed** — the
waiver at the head of the script covers behaviour, and a resolved `max-width` and a clipped listbox
are layout. They are recorded here as measured-in-Chrome, not as discharging the Safari pass.

#### The narrow pass was at 606px, and it is NOT the 400px pass

**Chrome's minimum window width on macOS is 606px**, and the Claude-in-Chrome extension refuses
page-zoom shortcuts (`page zoom keyboard shortcuts are not supported`), so neither route reaches
400px. What was actually observed at **606×657**:

- The below-`tablet` layout is genuinely active — hamburger nav, and the file toolbar
  (Restore Archived Data / New folder / Upload) reflowed to a stacked bar at the foot.
- `CreateFolderDialog`: **392px** wide, centred at left 107 / right 499, `fitsHoriz: true`, and
  `document.documentElement.scrollWidth === clientWidth` (no horizontal page scroll).

Nothing else on the script's CSS list was exercised at this width — no sticky pinned column, no
header-menu clipping, no sheet-vs-panel, no Calc/Grouping stacking, no toolbar wrap, no colour-rule
row wrap, no band boundary, no truncating-cell anchor, no header-drag. **The 400px pass is owed in
full.** Use DevTools device toolbar (⌘⇧M), which changes the viewport the page actually sees.

### SPEC-186 FR-003 — suggestion listbox containment

| Surface | `listbox.bottom` vs `dialog.bottom` | Cap | Result |
|---|---|---|---|
| Add members | 527 = 527, overhang **0px** | 113px | PASS |
| Share table / **Users** | −61px (headroom) | 114.25px | PASS |
| Share table / **Shared spaces** | −135px (headroom) | 114.25px | PASS |

Every cap is a measurement, not the old fixed `max-h-60` (240px); all three scroll, and arrow-key
navigation scrolls the active option into view (`scrollTop` 0 → 81.5) while containment holds.

**Do not misread the visible count.** Three of eight options are visible — the same number the
SPEC-158 failure reported — but the cause is now the opposite: then it overhung the panel by 97px,
now it is capped to fit. The Shared-spaces list offered exactly one option (`livecheck_186`, the
user's own space), which is SPEC-158's "no published directory of spaces" working.

### Saved queries — the client-side refusal (`e2e.md` §4.7), personal half

PASS, byte-exact. Delete and Move both `aria-disabled="true"` with `disabled` **false** and
`tabIndex 0`, so the reason is in the tab order:

- Delete — `Saved queries live in this folder, so it can’t be deleted.`
- Move — `Saved queries live in this folder, so it can’t be moved or renamed.`

Clicking Delete opened **zero** dialogs and **zero** alertdialogs; the folder survived. The control
passed too: an ordinary folder shows both controls enabled with no reason, so the refusal is
specific rather than a generic failure.

**Owed:** the shared half, and check 2 (the bucket-policy Deny, CLI-only).

### Findings

1. **`EXPLORATION_PAGE_SIZE` is 100, so the script's ">25 rows" fixture cannot page.** Both pagers
   render disabled at 30 rows and §2 is unrunnable. Script corrected to ask for 150.
2. **The suspended state is per-mount.** Leaving `/explore` and returning loses the `useRef` set in
   `useExplorationQuery`, so the failed statement is re-submitted and the error banner shows
   instead of "Nothing has been run". **Accepted, not fixed** (user decision) — the promise is
   scoped to history navigation, and persisting the set would add a second writer to the tab's
   `sessionStorage` key that SPEC-181 deliberately kept to one.

   **The "nothing is billed" half of that rationale is narrower than it looks, and the difference
   matters.** For the case staged here — `qty >>> 5`, a parse error — Athena rejects the statement
   **at `StartQueryExecution`**, so no execution is created and nothing is billed; the retry is
   itself the proof it was rejected at submit. But `DataExplorerWorkspace` calls `noteFailure` on
   **any** `exploration.error`, which includes `useExploration`'s `executionFailure` — a **FAILED
   or CANCELLED poll**. Those *did* create an execution, and `useExploration.ts`'s own comment
   records that a CANCELLED query **is** billed for what it scanned before it stopped. SPEC-178's
   Trino type-error case (`WHERE "qty" > '5'` against a bigint) is exactly that shape. So a
   re-submit after a route change is free for the syntax-error class and **not free in general**.
   That does not change the decision — the re-run happens once and the user is watching — but a
   future revisit should weigh the post-submit class, not the parse-error one.
3. **A failing apply issues TWO `StartQueryExecution` calls ~1.1 s apart.** This is `retry: 1` in
   `lib/queryClient.ts`, **not** a double-subscribe. Established by applying once with **no**
   navigation and watching it stop at exactly two and stay there for 20 s — an initial diagnosis
   blaming two subscribers was wrong and was withdrawn. It also proves Athena rejects this SQL at
   submit rather than failing it later, so no execution is created.
4. **Create view refuses through a toast**, not `Button.disabledReason` — the button reports
   `aria-disabled: null` and is genuinely enabled. Worth knowing when auditing FR-002 affordances.
   `Button.disabledReason` *is* in use on the file toolbar and the Explorer toolbar
   ("There are no filters, expressions, sorts or grouping to clear.", "Select some cells first.").

### Also created during this session

`livecheck_186` (shared space, owner `agriffith_three`) and `agriffith_three.explorer_fixture`
(table over `test_fixture_one/`). Both are live-check fixtures and can be deleted once the arc's
remaining checks are run.

---

## Live-check session — 2026-08-14

One session against the deployed portal (`d1kbh4bnvh1je8.cloudfront.net`), driven from the browser
as a **fresh account, `agriffith_three`**, signed up during the session. A clean account was chosen
deliberately: deterministic fixtures, and no risk to existing data.

`CLAUDE.md` carries one line per outcome and points here. This file is the evidence.

---

### Environment and what it can reach

Findings here decide what is checkable at all, so they come first.

| Target | Laptop identity (`user/tofu-deploy-user`) |
|---|---|
| `dat-prod-athena-admin` | **readable** — `logs/service=*/…/data.jsonl`, restore plans |
| `dat-prod-user-space` | explicit deny (bucket policy) |
| `dat-prod-archive` | explicit deny; execution role trusts `lambda.amazonaws.com` only; deploy role is GitHub-OIDC-only |
| Glue / catalog | `Insufficient Lake Formation permission(s): Required Describe` |
| CloudTrail | **no trails exist** |
| `dat-prod-table-builder-requests.fifo` | reachable (`get-queue-url` succeeds) |

Two consequences: **no principal can `head-object` the archive vault**, and **no principal can
`GetTable`**. Both take out owed assertions — see SPEC-186 FR-004.

Logs are swept on a **10-minute schedule**, so an empty partition immediately after an action means
*wait*, not *fail*. `logs/service=archive/` did not exist at all, confirming that plane has never run.

**Uploads cannot be automated** — the browser pane has no file-upload tool and the CLI is denied on
the user-space bucket, so every fixture was placed by hand.

---

### Discharged

#### SPEC-137 Phase 4 — the auth spans

Signing up `agriffith_three` succeeded, which alone rules out the cold-start `ModuleNotFoundError`:
on `pre-signup` that failure blocks sign-up outright. `logs/service=auth/` carried both spans at
`status: "ok"`:

- `pre-signup` — `span.start` + `span.end`, 0.149 ms
- `post-confirmation` — `span.start` + `user provisioned` (`username: agriffith_three`,
  `database: agriffith_three`) + `span.end`, 1381.8 ms

Field rule holds: username and database only, no token, no email.
**Defect found:** every record carries `"version": "0.0.0"` and `"env": ""` → SPEC-186 FR-005.

#### SPEC-146 — the username directory read

Typing one character in **Add members** returned **8 suggestions** (`adamparker`, `admin`,
`agriffith`, `akinwale14`, `denapolia`, `malathi`, `mrag`, `tencalade27`). Suggestions only render
if the portal role's SigV4 `GetObject` on `_directory/usernames.json` succeeded, so seeing them *is*
the end-to-end read confirmation.

The minutes-old `agriffith_three` was correctly **absent** — the document is built daily from S3
prefixes. That is the design, not a miss.

#### SPEC-175 — the cross-bucket `PutObject`

Saving a query into shared space `livecheck_0814a` produced, in order:

```
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 200
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200
```

Two design points confirmed live beyond the write itself: the folder marker is planted **on demand**,
and the name-collision check is a **HEAD on the exact key**, not a scan of the loaded array.

#### The refresh arc — FR-010, end to end

On `agriffith_three.sales_livecheck`, built from a 2-file CSV folder (`id,region,amount`):

| Step | Action | Result |
|---|---|---|
| 1 | Add `part0.csv` (`id,region,amount,channel`), sorting first | `1 column added`; rail → `id, region, amount, channel` |
| 2 | Delete `part0.csv`, refresh **without** opt-in | Refused: *"these columns are no longer in the data and would be removed: **channel**. Nothing was changed - refresh again and confirm the removal to apply it."* |
| 3 | Follow the notification link | `/query?refreshTable=agriffith_three.sales_livecheck&removed=channel` opens the dialog **pre-armed**; banner names `channel`; opt-in **not** pre-checked; submit `disabled` until ticked |
| 4 | Tick opt-in, submit | `1 column removed`; rail → `id, region, amount` |

The opt-in was unchecked on every fresh open — **persisted nowhere**, as specced.

> **The trap that cost a false bug report.** Schema inference probes exactly **one** sample object —
> the first key in listing order (`sample_by_format.setdefault(fmt, key)` in `inspect-source`). A
> column added in a file that sorts *later* is invisible **by design**, and the refresh correctly
> reports `already up to date`. The first attempt used `part3.csv` and read as a defect until the
> code was checked. → SPEC-186 FR-006.

#### The casing premise — now demonstrated, not corroborated

Uploaded `part00.csv` with headers `ID,Region,Amount` so it became the sample, against a stored
schema of `id,region,amount`.

- Refresh reported **`already up to date - no schema changes were found`** → `diff-schema` folds
  case, rather than seeing 3 added + 3 removed
- The rail still reads `id, region, amount` → **nothing was silently re-cased**

That is the mutation CLAUDE.md warned would be reported by no test and no notification. It did not
occur. Still unobserved: `get-table-versions` (that no new version was written), which needs FR-004.

#### SPEC-142 — the disagreeing-files check

Two checks over sibling folders, each 2 files.

| | `dq_agree` | `dq_disagree` |
|---|---|---|
| Verdict | No issues found | Issues found |
| Rows / Files | 4 / 2 | 4 / 2 |
| Disagreement section | **absent** | present, **Exact** |
| Rows with wrong field count | 0 | **0** |
| `qty` null or blank | 0% | 50.0% |

The finding read: *"b.csv is missing the column `qty` that the other 1 file has"*, under **Files that
disagree about their columns**, naming `agriffith_three/dq_disagree/b.csv` and `Missing: qty`.

**The load-bearing assertion is the negative one:** the disagreement did **not** leak into a
ragged-row count. Both runs appeared immediately in the `/data-quality` index (SPEC-123) with correct
badges.

---

### Half done

#### SPEC-125 — shared-space smoke run

**Create and add-member pass**, which is the risky half: a shared layer's import-time `_require`
fails at *cold start* (PR #196), and it did not.

- `livecheck_0814a` went **Active**
- adding `agriffith` showed **Pending** (SPEC-073's join status), with a Remove control
- `logs/service=shared-space/`: `validate` → `validated` (`action: create`, `known_space: false`) →
  `create` → `membership slot assigned` (slot 1, cap 10, store `cognito`)

**Leave PASSES too, run as `agriffith` (2026-08-14).** On signing in, the membership had flipped
**Pending → Active** — SPEC-073's `acknowledge-membership` working. As a non-owner the row offered
only **View members** and **Leave**, never Manage or Delete. The confirm read *"Leave
livecheck_0814a? You'll lose access to its files and tables. They are not deleted — everyone else
keeps access."* After leaving, the space vanished from the list, and revisiting
`/files?space=livecheck_0814a` showed *"That shared space is no longer available, so we switched
back to your personal files"* with **zero S3 requests naming the space** — the fallback resolves
from the connections list, so there is **no existence oracle** (SPEC-113/163's rule, confirmed).

**Delete PASSES, run as the owner — the smoke run is COMPLETE.** The confirm is `role="alertdialog"`,
names exactly what is lost (*"all of its files, all of its tables, the database, and every member's
access"*), and gates on **type-to-confirm**: Delete measured `disabled: true` before typing and
`false` only once the exact space name was entered. Afterwards the connections list was empty **and
`livecheck_0814a` was gone from the Query rail**, so the teardown removed the catalog side and not
merely the registry row — the shape SPEC-151's partial-teardown fix cares about. The owner's row had
also dropped to **"1 member"** after the leave, so `leave` fans out correctly where acknowledge does
not.

Minor, low severity: signing out does **not** purge the prior user's `s3portal.query.tabs.{username}`
sessionStorage key. Namespacing works and nothing is shown cross-user, but that session's SQL
buffers and saved-query pointers persist for the life of the browser tab — relevant only on a
shared machine.

**Defect found while here — the roster contradicts the connections list.** Same page, same moment:
the row read `Member | Active` while the members drawer read `agriffith | Pending` under *"…hasn't
signed in yet"*, to a reader who plainly had. The drawer's Refresh did not reconcile it.
`cache.write_roster_to_all` fans out on add/remove/leave and **not** on acknowledge — visible in
`logs/service=shared-space/` as `roster fanned out` under `add-members` and nothing after — so
roster copies stay frozen at add time. → SPEC-186 FR-008.

#### SPEC-175 — opening a colleague's query

As `agriffith`, the Saved queries panel's space selector listed `livecheck_0814a`; the colleague's
query appeared as *"livecheck shared save · 44 min ago · 85 B"* with Open and Delete. Opening it
fetched `GET dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200`
and opened a tab named for the query with the saved body. **Discharged.**

Side observation: merely opening the panel planted the reader's own marker —
`agriffith/saved_queries/DO_NOT_DELETE.txt` 404 → `PutObject` 200 — so a read path creates the
folder too, not only a save.

#### SPEC-158 — the suggestion pass

**Passes:** 7 chips tokenize on Enter from comma-separated input; the confirm control stays inside
the dialog, in the viewport, and hit-testable. Backspace deliberately does not remove chips.

**Fails:** the list does *not* position inside the panel. Listbox spans y 472→682; dialog ends at
585 — a **97px overhang** clipped by the dialog's `overflow: auto`, leaving **3 of 8** options
visible (still reachable via the listbox's internal scroll: 259px of content in a 208px box).
→ SPEC-186 FR-003. Re-measure after FR-007, since this was measured inside an oversized dialog.

**Owed:** the **Share table** dialog under **both share kinds**, the **400px** pass, and the whole
thing in **Safari** — a Chromium run corroborates but cannot discharge a Safari pass.

---

### Unrunnable as written — the most valuable class

#### SPEC-173's marker check

Asks: delete `{root}saved_queries/DO_NOT_DELETE.txt` through the portal, confirm `AccessDenied`.
**The portal never issues that call.** The marker is hidden **by basename** so it cannot be selected,
and the folder delete is refused **client-side** by `UNDELETABLE_ROOT_FOLDERS` before any S3 request.
A network trace of both attempts shows **zero** `DeleteObject` requests against the marker.

Verified instead — the client-side layer, personal **and** shared:

> "Deleted 0 items. Could not delete 1: **saved_queries — Saved queries live in this folder, so it
> can't be deleted.**"

with the folder surviving, and an ordinary empty folder (`refresh_step2`) deleting cleanly beside it
as the control. The bucket-policy Deny — the second layer — remains unverified. → SPEC-186 FR-001.

#### SPEC-157's concurrency check

Not performable from the UI, and now measured. Two submits **2 seconds apart** — two tabs pre-armed
via the `/query?refreshTable=` deep link, which is the floor two browser clicks allow — **both
returned independently** with no `refresh_already_running`. An earlier pair 9 s apart behaved the
same. A small table's refresh completes inside that window, so the lock is never contended and the
check can neither pass nor fail this way. → SPEC-186 FR-006.

#### The archive arc's `head-object` assertions

SPEC-170's negative assertion (no `Restore` header after a `destination_occupied` refusal), SPEC-169's
`StorageClass: GLACIER` read-back and its empty-archive-prefix check all need `head-object` on
`dat-prod-archive`. No principal can reach it, and with no CloudTrail there is no independent record
of whether `RestoreObject` was called. **Do not proxy from the UI** — the script itself says a
refusal that had already started retrieval looks identical there, and being wrong costs 3–5 billed,
uncancellable hours. → SPEC-186 FR-004.

#### SPEC-149 / SPEC-153's catalog read-backs

`get-database` returns `Insufficient Lake Formation permission(s): Required Describe` — the same wall
that forced 153's docs-transcribed stand-in. → SPEC-186 FR-004.

---

### Defects found

| # | Finding | Where |
|---|---|---|
| 1 | **Nine dialogs render at full viewport width.** `New folder` and `New shared connection` both measured **1372px in a 1400px viewport, `max-width: none`**, against `Create table`'s correct 448px/`max-w-lg`. Root cause: `cx()` returns `''`, `FormDialog` passes it to `Modal`, and `Modal`'s `className ?? 'max-w-md'` does not fall back on an empty string | SPEC-186 FR-007 |
| 2 | Suggestion listbox overhangs its dialog by 97px; 3 of 8 options visible | SPEC-186 FR-003 |
| 3 | `saved_queries` shows Delete/Move **enabled**, raises "This can't be undone", then refuses — the most alarming confirm in the app for an action that cannot happen | SPEC-186 FR-002 |
| 4 | Refresh dialog's submit is natively `disabled` with no reason, where SPEC-172 set `Button.disabledReason` as the fleet-wide pattern | SPEC-186 FR-002 |
| 5 | `version: "0.0.0"` and `env: ""` on every structured log record | SPEC-186 FR-005 |
| 6 | The members roster shows `Pending` — with *"hasn't signed in yet"* — for a member the same page shows as `Active`; Refresh does not reconcile | SPEC-186 FR-008 |
| 7 | Recipient chips are three copied implementations, already drifted: remove target is **20×20** in Share table and Send files against **24×24** in Add members (WCAG 2.2 SC 2.5.8 minimum). Chip width is unbounded — a 63-char username extrapolates to ~610px, wider than its 448px dialog | SPEC-186 FR-009 |


## 2026-08-30 — the registry list grant, verified against the deployed roles

Run from a laptop against production IAM, read-only, immediately after #555's
`Deploy Infrastructure` went green on `main`. This is the **paired-simulation** row that
`owed.md` carried, now discharged; the other two rows it added remain owed.

`s3:ListBucket` on `arn:aws:s3:::dat-prod-athena-admin`, per deployed execution role, each
`allowed` paired with an `implicitDeny` control — an `allowed` alone proves the grant works and
never that it stayed scoped:

| Role | `s3:prefix=shared-spaces/demo.json` | control, `s3:prefix=logs/service=api/` |
|---|---|---|
| `dat-prod-archive-execution-role` | allowed | implicitDeny |
| `dat-prod-data-quality-execution-role` | allowed | implicitDeny |
| `dat-prod-file-ops-execution-role` | allowed | implicitDeny |
| `dat-prod-file-send-execution-role` | allowed | implicitDeny |
| `dat-prod-table-builder-execution-role` | allowed | implicitDeny |
| `dat-prod-table-share-execution-role` | allowed | implicitDeny |

And `dat-portal-user-role` on `arn:aws:s3:::dat-prod-user-space`, simulated with
`aws:PrincipalTag/username=alice`: `_directory/usernames.json` allowed,
`_config/feature-flags.json` allowed, `bob/docs/a.txt` **implicitDeny** — the isolation control,
which is the assertion that matters, since the change added a second list grant beside the one
carrying that isolation.

**What this does NOT settle.** A simulate is not a request. It says IAM would allow the list; it
does not show `cpcommon.registry.load` returning None, and it cannot, because the thing being
fixed is what S3 chooses to *say* on a `GetObject`. The behavioural check — a real request naming
an unregistered space ending at `unknown_space` rather than a failed run — is still owed.

---

### Fixtures

`~/Downloads/portal-live-check-fixtures/` — `sales/` (base table), `refresh_add/part0.csv` (sorts
first, adds `channel`), `refresh_casing/part00.csv` (headers `ID,Region,Amount`), `dq_agree/`,
`dq_disagree/`. Keep `part00.csv`'s name: the sampling rule makes ordering load-bearing.

**Left behind in the account:** shared space `livecheck_0814a` (member `agriffith` pending, one saved
query), table `agriffith_three.sales_livecheck`, and the fixture folders. The space is still needed
for SPEC-125's `leave`/`delete`.

---


## 2026-08-30 — Arc B's first real pass: the API, the catalog, the enqueue paths and an archive

Run from a warm signed-in Chromium session as `agriffith` against the **container origin**
(`portal.dataquarry.app`), deployed sha `726aa448`. Instruments 1–2 from `e2e.md` §1, extended with
an **XMLHttpRequest** patch — without it the upload is invisible, because the transfer is an XHR and
the shipped instrument only wraps `fetch`. Refusal probes were issued **in-page**, using the app's
own bearer, so no token entered the transcript.

### SPEC-199 — the arc's central claim, and the catalog surface

**Lake Formation still authorizes the session the API assumes.** `SELECT employee_id, name FROM
agriffith.employees` returned **2 rows, 112 B scanned, 706 ms**, rendered in the grid. LF grants
attach to a principal, and that principal is now the portal role assumed by the API rather than one
vended to the browser. **This also discharges SPEC-196 Phase 5 item 4**, which that spec recorded as
owed and re-homed here.

The denial half, both shapes **in one sitting**:

| Shape | Probe | Result |
|---|---|---|
| Glue read, no `DESCRIBE` | `GET /v1/catalog/databases/adamparker` | **403** `AccessDenied`, envelope-shaped, **no `detail` at all** |
| Athena query, no `SELECT` | `SELECT * FROM adamparker.employees LIMIT 1` | **200** on the poll, execution reaches **FAILED** |

The FAILED execution's `stateChangeReason` names the principal:
`arn:aws:sts::696000197480:assumed-role/dat-portal-user-role/agriffith`. That is independent live
evidence of two settled claims at once — the role is **reused, not minted**, and the **session name
is the username**. It is a stronger observation than the SPEC-196 probe route gave, and it arrives
from a direction that spec could not reach.

**The engine's current text still matches the wording rules after the JSON round trip** (FR-003):
the browser rendered *"You don't have permission to run that query. Contact the Administrator."* and
`main.innerText` contains **no** `arn:aws`, no `glue:GetDatabase` and no `Insufficient permissions`.
Had the rules stopped matching, every failed query would say only the generic sentence and nothing
would look broken.

| Check | Result |
|---|---|
| Foreign database vs absent database (FR-008 AC9) | **Indistinguishable** — `adamparker` and `nosuchname_xyz123` both **403 `AccessDenied`**, byte-identical apart from the request id; own database 200. **No existence oracle. Not a finding for SPEC-202.** |
| `null` ≠ `''` on the raw body (FR-004 AC2) | `{"columns": [{"name":"a","type":"unknown"},{"name":"b","type":"varchar"}], "rows": [[null, ""]], "nextToken": null}` |
| The 409/400 pair (FR-005 AC2) | Results against a still-running execution → **409 `QueryNotFinished`** (*"the execution has not reached SUCCEEDED"*); a malformed statement at submit → **400 `QuerySyntaxError`** (*"athena rejected the statement"*). One Athena exception name, two codes. |
| The disclosed SQL is byte-identical (FR-009, and `e2e.md` §4.5 row 11) | `aws athena get-query-execution` returned `SELECT employee_id, name FROM agriffith.employees` — byte-identical, and `DataScannedInBytes: 112` matches the cost line. Workgroup `dat-prod-portal-wg`. |
| The browser has stopped talking to Athena and Glue (FR-013 AC5) | **Zero** requests to `athena.*` or `glue.*` across every section run. One `POST /v1/queries`, one poll, results read only after the poll reported SUCCEEDED. |
| Cold start | The first invocation after the deploy succeeded; every record carries the real sha. |

### SPEC-198 — the object surface

| Check | Result |
|---|---|
| One API call per gesture | Folder create is **one** `PUT /v1/objects/content` (`overwrite:false`) plus the listing refetch. Empty name is refused **client-side with zero requests**. |
| The collision path | `overwrite:false` → **409** → banner *"A folder named … already exists"* with **Rename / Cancel / Overwrite**; verified in the listing, not from the dialog. |
| The upload | **One presign per file** — two `POST /v1/objects/upload-url` for two files, minted inside `uploadFile`, never per batch. |
| The transfer is `XMLHttpRequest` | `XHR:PUT dat-prod-user-space.s3.us-east-1.amazonaws.com/…` — a `fetch` would have completed correctly and left the bar at 0%. |
| The presign host | `dat-prod-user-space.s3.**us-east-1**.amazonaws.com` — the regional host, which is the one the CSP admits. Live confirmation of #553. |
| Foreign personal prefix (FR-013 live half) | **403 `AccessDenied`**, `detail: "personal space is not the caller's"` |
| Foreign shared space | **403 `AccessDenied`**, `detail: "no membership claim for that space"` |
| **The paired control** | The same route against the caller's own prefix → **200** with the listing. Without it a denial cannot be told from broken credentials. |
| `PUT` under `archive/` | **403 `AccessDenied`**, `detail: "archived locations are not writable"` — recorded as the **route-layer** refusal it is. |
| The CORS trio on the presign path (FR-011) | SPA origin → `access-control-allow-origin: https://portal.dataquarry.app`; **CloudFront origin `d1kbh4bnvh1je8.cloudfront.net` → its own ACAO**, so the rollback is intact; `example.invalid` → **no ACAO**. `access-control-allow-headers` is exactly `authorization,content-type,x-request-id`. |

**`owed.md` §2.1's marker Deny — run, and only half of it discharged.** `DELETE /v1/objects` on
`saved_queries/DO_NOT_DELETE.txt` is **403 `AccessDenied`** in the **personal** space and in a
**shared** one (`alexis_shared_space`), `detail: "folder markers may not be removed or replaced"`;
the paired control — an ordinary `.sql` file written and deleted in the same folder — is **200 and
200**. But that wording is the **API's own**, not IAM's: the route refuses before S3 is asked, so
what is settled is *the marker cannot be deleted through the API*, **not** that the bucket policy
denies it. The bucket-policy half is unreachable from this API and stays owed.

### SPEC-197 §F — the transport contract

| Item | Result |
|---|---|
| F.1 — suggestions **render**, by name | `SendFilesDialog` on `ad` → `adamparker`, `admin`, `tencalade27`; `AddMembersDialog` on `mi` → `mikec`; `TableShareDialog` on `mi` → `mikec`, `admin`. Real names, not a 200 with an empty array. |
| F.1 — one request, not three | Two dialogs in one page session issued **one** `GET /v1/user-directory` between them; the hour-long `staleTime` is unchanged by the port. The third dialog was opened after a full page load, so its own request is expected and the three-in-one-session claim is **corroborated across two, not three**. |
| F.1 — `AddMembersDialog` on `ad` returned **nothing** | Not a defect: `adamparker`, `admin` and `tencalade27` are all already members of `dwb_testing_all`. Checked against the roster before concluding. |
| F.2 — preflight headers | `OPTIONS` → **200**, `access-control-allow-headers: authorization,content-type,x-request-id`, `access-control-max-age: 600`. Every bearer-carrying cross-origin `fetch` in this session succeeded, which is the browser half — **in Chromium. Safari is still owed.** |
| F.3 — the refusals | No credential → **401** `{"error":{"code":"SessionExpired","requestId":"…"}}`; garbage bearer → the same, byte-identical apart from the id. |
| F.4 — **the correlation key is the gateway's** | `POST /v1/nope` with body `{"requestId":"spoofed"}` logged `request_id: "C6-0Oj1hoAMEZig="` and `client_request_id: null`. The string `spoofed` appears in **none of the 470 records**. |
| F.6 — cold start | The first invocation after the deploy succeeded. |

### SPEC-200 §G — the enqueue paths

**§G.5, the grants, simulated against the DEPLOYED roles.** `sqs:SendMessage` against all eight
request queues:

| Role | Result |
|---|---|
| `dat-portal-user-role` | **`implicitDeny` on all eight** |
| — paired control | `s3:GetObject` under the caller's own prefix (with `aws:PrincipalTag/username=agriffith`) → **`allowed`** |
| `dat-prod-api-role` | **`allowed` on all eight** |

This is the only evidence the browser's grants are actually gone rather than merely absent from the
templates. **Read the per-queue results one call at a time** — `--output text` over a multi-resource
simulate prints the decision on the first row only and the bare ARNs after it, which reads as seven
missing verdicts and cost a re-run to disbelieve.

**§G.1 row 8, archive, end to end** — the arc's first real request through the API on this plane, and
it is judged on the outcome rather than the 200:

- `POST /v1/enqueue/archive` → **200**, one call, body
  `{"requestId":"26c2e82f-…","source":{"space":…,"items":[{"kind":"folder","key":"agriffith/archive_live_0830/"}]}}`
  and **no `actor` and no `identity` field** — the actor is taken from the bearer server-side, which
  is the delegated-actor claim, observed.
- The notification arrived with the specified wording, and the folder left the listing.

**§G.1 row 9, restore** — `restore_started` arrived (below).

**§G.3, one log record per plane** — for the archive plane, every required field is present and every
forbidden one absent:

```
route_id: archive.archive   queue: archive   actor: agriffith
message_group_id: c781a6d5…  dedup_id = body_request_id = 26c2e82f-…
body_bytes: 1763   status: 200   env: prod   version: 726aa448…
```

### The structured log, swept mechanically rather than sampled

470 records in the session's window (215 `span.start` + 215 `span.end` + 40 others; 470 distinct
`log_id`s and **zero duplicate lines in the file** — the pairing is two spans per request, not a
double-write, which is what it looks like until you check).

**Nine absence checks, all zero:** any `eyJ`-shaped JWT substring, any email address,
`x-amz-signature`, any `AKIA`/`ASIA` string, a `usernames` array, raw SQL (`\bselect\b\s+\w`),
`stateChangeReason`, the string `Insufficient permissions`, and `arn:aws` anywhere in the fields.

**And the substitutes are present, which is the half a leak check cannot see:** `username_count`
(not `usernames`), `sql_bytes` (not the statement), `state` (not `stateChangeReason`), and on the
presign route **`key_length: 38`** — the key's *length*, never the key. Every record carries
`env: "prod"` and `version: 726aa448…`; **zero** records carry an empty or `0.0.0` version, which
was defect #5 of the 2026-08-27 session and is now fixed in the deployed build.

### The archive and restore (approval given in session)

Fixture `archive_live_0830/` created this session, two CSVs uploaded through the portal.

**B1 — every assertion passed.** The dialog heading named the folder **relative to the space root**
(`archive_live_0830/`, not `agriffith/archive_live_0830/`); it said the data will be removed and that
a restore takes several hours; it did **not** say "this can't be undone"; `role="alertdialog"`, and
**focus was on Cancel**. **Enter cancelled the dialog and issued zero requests** — the one
irreversible surface refusing the affordance that would fire it, observed for the first time.

The outcome: *"Archived 3 files (489 B). They have been removed from your space. Archive id:
26c2e82f-… - you'll need it to restore them."* — **3**, not 2, because the folder placeholder counts.
The notification's link is `/files?prefix=agriffith/archive/{uuid}/`, so it lands **in the archive
folder, not at the space root**. In that folder: `receipt.txt` (361 B) reads correctly; **Upload** and
**New folder** are `aria-disabled="true"` with `disabled === false`, `tabIndex 0` and the read-only
reason; **Archive is ABSENT, not disabled**. The source folder is gone from the space root.

**B2 — requested 15:16:39 UTC.** A nonsense id was refused inline with *"That doesn't look like an
archive id. Ids look like 3f8a1c2e-…"* and the submit control was **never merely disabled**
(`disabled: false`, `aria-disabled: null`, `tabIndex 0`). Fourteen seconds after submitting, the
receipt already read `Restore requested: 2026-08-30 15:16:39 UTC` with `Restored to: -` — **the
marker really is written before the bill**. The `restore_started` notification arrived — *"Restoring
3 files from long-term storage… Nothing has changed in your space yet."* — and carries **no link**,
as specified.

**Phase D is owed on this archive**, in 3–5 hours: the terminal notification and its link, the files
back at their original paths, `archive/{id}/` still holding its rewritten receipt, and multiple
`retrieval polled` events hours apart with `poll_count` climbing.

### Findings

| # | Finding |
|---|---|
| 1 | **The browser still calls the Identity Pool.** `fetchAuthSession` hits `cognito-identity.us-east-1.amazonaws.com`, and `/config.json` ships a **non-empty `cognitoIdentityPoolId`**. Expected — SPEC-202 is what retires it, and the CloudFront CSP allowlists the host deliberately — but **`CLAUDE.md`'s "the browser's only remaining AWS call is presigned S3 bytes" is false as deployed**, and `arc-b-api-container-e2e.md` §4's load-bearing negative would fail today if run as written. No AWS credentials are persisted (storage holds only oauth/id/access/refresh tokens), and the vended session's grants are the ones §G.5 measured. |
| 2 | **`arc-b-api-container-e2e.md` §F.3 asserted the wrong status.** It expected **404** from two *unauthenticated* `curl`s. The router resolves a principal **before** the route and refuses an unknown path as unauthenticated — its own docstring says so, because "a 404 to an unauthenticated caller tells them which paths exist". Both are **401**. With a valid bearer both are **404 `NotFound`**, envelope-shaped. Fixed in this branch. |
| 3 | The archive receipt's `Original path` reads `s3://dat-prod-user-space/agriffith/` — the **space root**, not the archived folder. The per-file paths live in the plan, so a restore is unaffected, but the receipt alone does not say *what* was archived. Not filed as a defect; worth a decision. |

### Not run, and why

- **F.5, the refresh-once path.** The stored token did age past its hour mid-session, but Amplify
  refreshed **proactively** on the next gesture — `cognito-idp` and `cognito-identity`, then a single
  `GET /v1/objects` **200 with no 401 first**. `apiRequest`'s 401-retry never fired, so the "exactly
  two requests" assertion has still never been observed. It needs the refresh broken, not merely the
  token expired.
- **The multi-GiB upload** (FR-005 AC8) — the premise the whole single-`PUT` design rests on. The
  fixtures here were 235 B and 254 B.
- **An intermediate upload percentage in a real browser** — the transfer is confirmed to be an XHR,
  which is the mechanism, but no progress event was sampled.
- **Safari, and 400 px.** Everything above is Chromium; it corroborates and cannot discharge.
- **§G.1's other eight rows, §G.2's double-submit guard, §G.4's refusals.** Archive and restore are
  two of ten planes.
- **A fresh sign-in.** The session was warm throughout. A second tab was found signed **out** —
  tab-scoped storage working as intended — but signing it in needs a password, which is not mine to
  enter.
