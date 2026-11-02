---
type: Spec
id: SPEC-211
title: "Give Feedback — the API Route, the Writer Queue and the Daily Document"
description: "Adds a Give feedback button and modal in the top bar that sends a category and message through an API route and writer queue, filing one JSON record per day in the admin bucket, for users and operators."
spec_status: Completed
depends_on: [SPEC-195, SPEC-196, SPEC-197, SPEC-058, SPEC-206, SPEC-129, SPEC-127, SPEC-128, SPEC-130, SPEC-131, SPEC-132, SPEC-133, SPEC-134, SPEC-135, SPEC-136, SPEC-137, SPEC-155, SPEC-106, SPEC-032]
---

**Interacts with:** SPEC-207 repoints the existing help control and adds none; SPEC-210 adds a theme
control. **This spec owns the mobile header decision all three depend on** — FR-007.


**Dependency notes:** SPEC-195 (the API's auth boundary), SPEC-196 (the identity layer and the two credential planes), SPEC-197 (the transport contract, `apiRequest`, the generated TypeScript), SPEC-058 (the single-writer FIFO pattern), SPEC-206 (the `SenderId` boundary), SPEC-129 (one object per day, appended under ETag CAS), SPEC-127→137 (`cpcommon.observability`), SPEC-155 (`Modal`, `FormDialog`, the Escape registry), SPEC-106 (`toUserMessage`), SPEC-032 (the admin bucket and its prefix-scoped lifecycle)
## Overview

There is no way for a user to tell us anything. Every signal the portal produces is telemetry — what
people clicked, what failed — and none of it carries what somebody wanted and could not find. A
support address is not an answer either: the moment a user leaves the app to write an email, the
context of what they were doing goes with them.

This spec adds a Give feedback button in the top bar, beside the help button. It opens a modal with
a category and a message, and sending it lands one JSON record in the admin bucket, filed by the day
it arrived. Nothing is rendered back: feedback is write-only from the browser's side, which is what
keeps it out of every rendering and escaping question in the app.

**It is the first feature built API-first.** Every existing enqueue is a browser call straight to
SQS with the caller's scoped credentials, and Arc B is porting all of them. Adding a sixteenth would
be adding work to SPEC-200 in the same breath as writing it. So the browser posts to a route, the
API verifies the caller and enqueues on its **own** identity — which also means the feedback queue is
not writable by the portal role at all, and a user cannot forge a feedback record attributed to
somebody else.

## Scope

### In Scope

- A `POST /v1/feedback` route on the existing HTTP API, declared in the contract and regenerated
  into TypeScript.
- A FIFO feedback queue and its own DLQ, writable only by the API's execution role.
- `feedback-writer`: a single-writer Lambda appending one event to
  `<admin-bucket>/feedback/YYYY/MM/DD.json` under ETag compare-and-swap.
- A Give feedback button in the header and its modal: category, message, auto-captured route.
- Server-side validation of every field, and a success toast.
- Help content.

### Out of Scope

- **Any read surface.** No feedback list, no admin view, no notification, no reply. The records are
  read with the AWS CLI by whoever wants them, and that is the whole retrieval story.
- **Attachments or screenshots.**
- **A control plane.** There is one verb. A queue, a Pipe, a state machine and a fan-out for a single
  append would be the plane shape applied where it earns nothing.
- **Draining the feedback DLQ.** Deliberate, and reasoned in FR-008 rather than left unsaid.
- **A CloudWatch alarm on DLQ depth.** There is no alarm anywhere in `infra/` today; it would be the
  first, a new resource type and its deploy-role IAM. Named here as the thing not built, so that the
  gap is a decision rather than an oversight.
  > **Superseded in part (2026-09-27):** "no alarm anywhere" and "a new resource type" stopped
  > holding when #724 added the logs backlog alarm (`infra/modules/observability/alarm.tf`); the
  > deploy-role grant names only that alarm, so one here would still need its own. The DLQ still
  > has no alarm, now by Andrew's decision and for the reason in the feedback entry of
  > `docs/decisions/control-planes/`.
- **Rate limiting beyond what the route already has.** The route is non-idempotent so `apiRequest`
  never retries it, the modal disables its submit while in flight, and the message is capped
  server-side. A per-user quota is not built.
- **Email or Slack delivery.**

---

## Functional Requirements

### FR-001: The route

#### Description:

One route, declared in `apicommon/contract.py`'s `ROUTES`, handled by a module under `routes/`.

#### Acceptance Criteria:

- [x] The route is `id: "feedback.submit"`, `method: "POST"`, `path: "/v1/feedback"`,
      `idempotent: false`, `plane: "api"`.
- [x] `plane` is `api` and not `user`: the enqueue is the API's own act, and the user plane would
      require granting the portal role `sqs:SendMessage` on this queue — which would let the browser
      write feedback records directly, attributed to whatever username it chose.
- [x] The route is not in `PUBLIC_ROUTES`; an unauthenticated request is refused with the same
      byte-identical refusal every authenticated route gives.
- [x] `scripts/generate_api_contract.py` is re-run and the generated TypeScript is committed; CI's
      regeneration-diff gate passes.
- [x] The browser calls it through `apiRequest('feedback.submit')` — never a URL — and takes its
      retry policy from `apiRetryPolicy`, which yields no retry.

### FR-002: What the route accepts, and what it refuses

#### Description:

Validation is server-side. The client's own checks are a courtesy, not a control.

#### Acceptance Criteria:

- [x] `category` must be one of `bug`, `idea`, `question`, `other`; anything else is `InvalidRequest`.
- [x] `message` must be a non-empty string after trimming, at most 4000 characters; empty, whitespace-
      only or longer is `InvalidRequest`. A test asserts the boundary at 4000 and at 4001.
- [x] `route` is optional, at most 200 characters, and is stored verbatim without interpretation.
- [x] An unknown key in the body is refused by the existing request validator; no new leniency is
      introduced for this route.
- [x] Every refusal's `detail` is operator text and the browser renders wording chosen from the
      **code**, never from the response.
- [x] The route returns 200 with `{submittedAt}` only after `SendMessage` has succeeded. A queue
      failure is a fault, and the caller is told the submission did not happen.

### FR-003: The event, and who it is attributed to

#### Description:

The username comes from the verified token. The body's opinion of who the user is does not exist —
there is no username field in the request.

#### Acceptance Criteria:

- [x] The request type has no username, userId or email field; a test asserts the declared request
      shape carries only `category`, `message` and optional `route`.
- [x] The enqueued event's `username` is the verified `cognito:username` claim.
- [x] `submittedAt` is stamped by the API in UTC, ISO 8601.
- [x] `eventId` is a UUID minted by the API and used as the SQS `MessageDeduplicationId`, so a
      transport-level duplicate lands once.
- [x] The event carries **no token, and no email address**. A test asserts the serialized body
      contains neither an `idToken` field nor the `@` of an address.

### FR-004: The queue

#### Acceptance Criteria:

- [x] A FIFO queue with its **own** DLQ. It does not share another plane's DLQ — a malformed
      feedback submission must not dead-letter somebody's file operation.
- [x] `MessageGroupId` is the UTC date, `YYYY-MM-DD`, taken from the API's `submittedAt`. That makes
      every message destined for one day's object serialize behind the previous one, which is
      precisely the contention the CAS append would otherwise have to retry through.
- [x] The queue's send permission is granted to the API's execution role and to nothing else; a test
      asserts the portal role's policies grant no action on this queue.
- [x] The event source mapping's batch size is 1 — the writer handles one event at a time.

### FR-005: The writer and the daily document

#### Description:

`feedback-writer` reads the day's object, appends the event, writes it back under ETag
compare-and-swap. An absent object is created with `If-None-Match: *`.

#### Acceptance Criteria:

- [x] The key is `feedback/<YYYY>/<MM>/<DD>.json`, derived from the event's `submittedAt`, not from
      the writer's own clock — so the object a message lands in was decided when it was submitted,
      and agrees with the `MessageGroupId` that serialized it.
- [x] With no object for the day, the writer creates one containing exactly the one event, using
      `If-None-Match: *`.
- [x] With an object already present, the writer appends and preserves every existing entry; a test
      writes three events and asserts all three, in submission order.
- [x] A precondition failure re-reads and retries against the fresh ETag, up to a bounded number of
      attempts; exhausting them raises so the message dead-letters rather than being silently lost.
- [x] An existing object that will not parse is **not** overwritten: the writer raises, leaving the
      day's records intact for an operator, in the manner SPEC-159 established for an unreadable
      settings document.
- [x] The writer never deletes an object and holds no `s3:DeleteObject` grant.
- [x] All logging goes through `cpcommon.observability`, and the feedback **message text is never
      logged** — a test asserts the message body does not appear in any emitted record.

### FR-006: The document survives

#### Acceptance Criteria:

- [x] `feedback/` has no admin-bucket lifecycle rule that expires it, and a test asserts that no
      expiring rule's prefix is a prefix of `feedback/`. The existing
      `admin_lifecycle_rules_are_prefix_scoped` check proves every expiring rule *has* a prefix; it
      cannot prove that none of them matches this one.
- [x] The admin bucket's existing versioning, encryption and public-access settings cover the prefix
      with no per-prefix exception. **Said plainly, because the sentence reads as a safety net and
      is not one: versioning on that bucket is `Disabled`**, in common with every bucket here. What
      actually stands between a bad write and a lost day is FR-005's refusal to overwrite a
      document this writer cannot parse.

### FR-007: The button, the modal and the confirmation

#### Acceptance Criteria:

- [x] At `tablet` and above, the header renders one control named `Give feedback` immediately beside
      the help control, for authenticated users only.
- [x] **Below `tablet` the control lives in `AppNavDrawer`, not the header**, and the header gains no
      element at mobile width. The measurement, made once here because three specs depend on it —
      and note the unit, because it is the trap: **`index.css` sets a 14px root**, so every
      rem-named Tailwind size renders 12.5% under its name. At 375px the header carries a `h-11`
      hamburger (**38.5px**, not 44), the `BrandMark` (an `h-8` square at **28px** plus its
      `gap-2` and the wordmark), an `h-8` help control, bell and avatar (**28px** each, not 32),
      and an `h-8 px-3` Sign out, inside `px-4` (**14px**) with `gap-4` (**14px**) outer and
      `gap-3` (**10.5px**) inner spacing. Those fixed parts total **280px of 375**, leaving 95px
      for the "Data Workspace" wordmark and the "Sign out" label together — the wordmark alone
      does not fit, so it is over budget before anything is added, and a seventh control would add
      another 38.5px. SPEC-210's theme control takes the same route into the drawer for the same
      reason, and SPEC-207 adds no element — so the mobile header is unchanged by all three **for
      a signed-in user**. (Signed out there is no drawer, which is why SPEC-210's control is
      header-rendered in that state; Give feedback is authenticated-only and never reaches it.)
- [x] A test at mobile width asserts the header's control count is unchanged and the drawer offers
      `Give feedback`.
- [x] It opens a dialog with a required category and a required multi-line message. **No category
      is preselected** — a default would be the modal answer to every submission, and the field
      exists to record a choice the user made.
- [x] The current route path is captured when the dialog opens and sent with the submission; it is
      not shown as an editable field, and the dialog states that the page you were on is included.
- [x] Submit is disabled until both required fields are filled, and while a submission is in flight.
- [x] Enter submits from the **category** field only — the message is a textarea and Enter inside it
      inserts a newline. Never implicit submission from any field.
- [x] On success the dialog closes and a toast reads a thank-you; the message is cleared, so
      reopening the dialog does not show the last submission.
- [x] On failure the dialog stays open with the message intact and renders wording from
      `lib/errorMessages.ts` chosen by the error code.
- [x] Escape dispatches at the dialog's tree depth, and a submission in flight swallows it.
- [x] `expectNoA11yViolations` runs against the driven container with the dialog open.

### FR-008: The DLQ is not drained, and that is written down

#### Description:

Every other request DLQ is swept into a notification. This one is not.

#### Acceptance Criteria:

- [x] `feedback` is added to `dlq_drain.UNDRAINED_QUEUES` alongside `notifications`, with its reason
      in the module's docstring: the drain notifies from a **verified token** in the message body,
      and this body carries no token by design — the API verified the caller and the browser never
      touches this queue. Draining it would mean notifying from an untrusted body field, which is the
      exact inversion the drain exists to prevent.
- [x] A test asserts every request DLQ Terraform declares is either wired in `SOURCES` or named in
      `UNDRAINED_QUEUES`, so a future queue cannot be silently undrained.
- [x] The user's guarantee is stated in the spec and holds in the code: the 200 means the submission
      was accepted onto the queue. Nothing after that point is something the user can act on, which
      is why nothing after that point notifies them. **And the cost of that, named rather than
      left to be discovered: FR-005 forbids logging the message text, so the durable record of a
      failed submission carries everything except the thing that would let anyone recover it, and
      the dead-letter copy is gone after 14 days.** A submission that dies is unrecoverable, not
      merely unreported. That is accepted for a write-only channel with no reply path; it would
      not be for anything a user is waiting on.

### FR-009: Help content

#### Acceptance Criteria:

- [x] A guide covers where the button is, what the categories mean, and that the page you were on is
      included with the message.
- [x] The guide does not promise a reply, because there is no reply path.

---

## Data Model

```ts
// Generated into apps/portal/src/types/apiContract.generated.ts from the Python declaration.

// The category renders INLINE. The emitter declares only TypedDicts, so a `Literal` alias has no
// standalone form — and widening its closed vocabulary for a cosmetic alias is the one thing the
// generator's own docstring says must not happen casually. The browser derives its own
// `FeedbackCategory` from this request type, so there is still one source.
export type FeedbackSubmitRequest = {
  category: 'bug' | 'idea' | 'question' | 'other';
  message: string;
  route?: string;
};

export type FeedbackSubmitResponse = {
  submittedAt: string;
};
```

```jsonc
// The SQS message body, written by the API.
{
  "schemaVersion": 1,
  "eventId": "0f2c…",
  "username": "acarter",          // from the verified claim, never the body
  "category": "bug",
  "message": "…",
  "route": "/query",
  "submittedAt": "2026-08-28T14:03:11Z"
}
```

```jsonc
// <admin-bucket>/feedback/2026/08/28.json
{
  "version": 1,
  "date": "2026-08-28",
  "entries": [
    {"eventId": "0f2c…", "username": "acarter", "category": "bug",
     "message": "…", "route": "/query", "submittedAt": "2026-08-28T14:03:11Z"}
  ]
}
```

## File & Folder Structure

```
lambdas/
├── api/
│   ├── apicommon/contract.py        # the route + the two TypedDicts
│   └── routes/feedback.py           # validate, stamp, enqueue
└── feedback-writer/
    ├── feedback_writer.py
    └── test_feedback_writer.py

infra/modules/feedback/              # queue, DLQ, writer function, log group, IAM, ESM
└── policies/

apps/portal/src/features/feedback/
├── FeedbackButton.tsx
├── FeedbackDialog.tsx
├── useSubmitFeedback.ts
├── feedback.test.tsx
└── index.ts
```

## Implementation Phases

### Phase 1: The infrastructure

- The `feedback` module: FIFO queue, DLQ, writer function with its placeholder and
  `ignore_changes`, log group, execution role, event source mapping.
- The deploy-role IAM expansion, in its own PR, ahead of the resources.
- The `feedback/` prefix and the no-expiring-rule assertion.

### Phase 2: The writer

- `feedback-writer`, the CAS append, the absent/present/unparseable cases, the bounded retry.
- The `UNDRAINED_QUEUES` entry and the completeness test.
- The no-message-in-logs assertion.

### Phase 3: The route

- The contract declaration, the handler, the validation and its refusals.
- Regenerate the TypeScript; the API's send grant on the queue.

### Phase 4: The browser

- The header button, the dialog, the route capture, the toast.
- Error wording, focus and Escape behaviour, axe.
- The Help guide.
