# Feedback (`apps/portal/src/features/feedback/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

Write-only by design: nothing here reads feedback back, which is what keeps it out of every
rendering and escaping question in the app.

| Symbol | File | Purpose |
|---|---|---|
| `FeedbackDialog` | `features/feedback/FeedbackDialog.tsx` | The modal (`{onClose}`) over `FormDialog`: a category with **no preselection**, a message textarea, and the route captured **when it opens** (not at submit — a user who navigates mid-sentence is the case worth getting right). Enter submits from the category select only. |
| `useSubmitFeedback()` | `features/feedback/useSubmitFeedback.ts` | The mutation. `retry` comes from `apiRetryPolicy('feedback.submit')`, never a literal — a retried submission is a second entry in the day's file with nothing to tell it from a deliberate one. |
| `submitFeedback(input)` | `features/feedback/feedback.service.ts` | `apiRequest('feedback.submit')`. Takes no username: the API stamps the verified caller, and a username this function could pass would be one a caller could choose. |
| `FEEDBACK_CATEGORIES` / `MAX_FEEDBACK_MESSAGE_CHARS` | `features/feedback/feedback.constants.ts` | The four categories in picker order with the wording a user reads, and the message cap **mirrored** from the route (which is the control); `lambdas/test_feedback_caps_agree.py` holds the pair together. |
| `FeedbackCategory` | `features/feedback/feedback.types.ts` | Derived from the generated `FeedbackSubmitRequest['category']`, so the vocabulary has one source. |
