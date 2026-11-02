# Completed Spec — SPEC-211: Give Feedback — the API Route, the Writer Queue and the Daily Document

## What was completed?

A **Give feedback** control in the header (and in the mobile navigation drawer) opening a modal
with a category and a message. Sending it posts to a new API route, which stamps the submission
and puts it on a FIFO queue; a single-writer Lambda appends it to that day's JSON object in the
admin bucket. Nothing is read back — feedback is write-only from the browser's side.

- **Route:** `POST /v1/feedback` (`feedback.submit`), declared in `apicommon/contract.py`
  (`FeedbackSubmitRequest`, `FeedbackSubmitResponse`), served by `lambdas/api/routes/feedback.py`,
  regenerated into `apps/portal/src/types/apiContract.generated.ts`.
- **Infrastructure:** `infra/modules/feedback/` — FIFO queue, its own DLQ, `feedback-writer` with
  its log group, role and event-source mapping — plus the deploy-role grant
  (`github-actions-deploy-feedback.json.tftpl`).
- **Writer:** `lambdas/feedback-writer/feedback_writer.py`, appending under
  `cpcommon.cas.cas_mutate`.
- **Browser:** `apps/portal/src/features/feedback/` — `FeedbackButton`, `FeedbackDialog`,
  `useSubmitFeedback`, `feedback.service`, and the `actions` slot on `AppNavDrawer`.
- **Shared:** `apicommon/queue_faults.refuse_for` (extracted from `apicommon.enqueue`, which is no
  longer the API's only `SendMessage`); `SELECT_CLASS` moved to `components/fieldStyles.ts` at its
  first consumer outside the Data Explorer.

### Deliberate deviations

- **`FeedbackCategory` is not a standalone generated type.** The spec's Data Model showed one; the
  emitter declares only TypedDicts, and a `Literal` alias renders inline. Growing the emitter's
  closed vocabulary for cosmetics is the one thing its docstring says must not happen casually, so
  the category renders inline and the browser derives its own alias from the generated request
  type. The spec's Data Model was corrected in the same PR.
- **The feedback queue is not in `contract.QUEUES`** and the route is not an `EnqueueRoute`.
  Reasoning in `docs/decisions/control-planes/`. The coverage this costs — the swapped-pair
  wiring guard — is written out explicitly instead.
- **No CloudWatch alarm on DLQ depth**, and no drain. Both named in the spec as decisions; the
  DLQ reason is now also in `dlq_drain.UNDRAINED_QUEUES`' docstring.
- **The mobile control is mount-gated, not CSS-hidden.** FR-007 asks for a test that the header's
  control count is unchanged at mobile width; jsdom loads no Tailwind, so a `tablet:` class would
  make that test pass over a header that gained a control.

### Known behaviours, decided rather than overlooked

- **A scrim click discards the message with no confirmation.** `Modal` dismisses on backdrop
  click, as it does for every dialog in the app — but this is the only field whose content exists
  nowhere else. Left as-is to match the rest of the app; raising it would be a product change, not
  a fix.
- **The `send()` guards are defence in depth.** `FormDialog` already refuses to submit while
  `submitDisabled` or `busy` is set, so neither arm in the handler is reachable from the dialog's
  own controls. Measured, and stated in the code, so the next reader does not take them for the
  enforcement.
- **`FeedbackDialog`'s reset of its own state is unreachable today** — the host unmounts the
  dialog on close. It stays because it is what keeps FR-007's "reopening does not show the last
  submission" true if the dialog is ever kept mounted, and the test says plainly that it cannot
  see the difference.

## What changed from earlier specs?

- `apicommon/enqueue.py` is no longer "the one path to `SendMessage`" — its classifier moved to
  `apicommon/queue_faults.py` and its docstring says what is still true.
- `dlq_drain.UNDRAINED_QUEUES` gains `feedback`; `test_plane_envelope_agreement`'s
  `_TWO_PRODUCER_PLANES` became `_UNDRAINED_BY_DESIGN`, a reason per queue.
- The API's `request_queue_arns` is nine, and `test_queue_writers`' filesystem enumeration follows
  on its own.
- `SELECT_CLASS` moved from `features/data-explorer/dataExplorer.constants.ts` to
  `components/fieldStyles.ts` and is re-exported from its old home, so its six existing consumers
  are untouched.
- Two rotted counts in `infra/modules/base/README.md` ("fourteen managed policies", "three
  propagation guards") became principles, and two dead ceiling constants left
  `test_deploy_platform_policies.py`.

## Verification

Locally green before each push: `format:check`, `lint`, `test` and `build` for the portal;
`ruff`, `mypy`, `pytest lambdas/` and `validate_docs.py`; `tofu validate` and `fmt -check`. The
contract generator produces no diff. Six guards were mutation-verified by planting the failure and
watching it redden — the grant→template join, the action sets, the day-from-submission rule, the
never-overwrite-a-corrupt-document rule, the mount-gated mobile control, and the open-time route
capture.

Deferred to deploy: the apply itself, and the end-to-end submission. A live check needs a
signed-in session **and** an admin-bucket read, which no browser session can do — recorded in
`docs/testing/owed.md` rather than claimed.
