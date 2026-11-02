---
type: Decision
title: "No backend"
description: "The browser holds no AWS credentials and reaches only presigned S3 bytes and Cognito without the API; the live rules are no second API and no new browser-side AWS SDK call on a path an API route serves."
---

Browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).

> **Superseded (2026-08-28).** This premise no longer describes the system. Privileged work moved onto
> seven **control planes** (SPEC-051 onward), and SPEC-192→197 added an **HTTP API** that verifies a
> bearer and serves routes. What survives is the boundary, not the absence, and the two live rules are
> **no second API** and **no new browser-side AWS SDK call on a path an API route already serves**.
> (Updated 2026-08-29: this marker used to say the browser still called S3, Athena and Glue directly
> for most reads. SPEC-198 and SPEC-199 ported both surfaces; what the browser reaches without the API
> is presigned S3 bytes, Cognito, and the control-plane `sqs:SendMessage` enqueues. **Updated again
> for SPEC-202 (2026-09-02):** the enqueues went with SPEC-200's grant removal and the Identity Pool
> went with SPEC-202, so the browser holds **no AWS credentials and no AWS grant at all** — what it
> reaches without the API is presigned S3 bytes and Cognito through Amplify, and nothing else.) Full
> entries: [`docs/decisions/control-planes/`](../control-planes/) and this area's API decisions. Shape:
> `docs/architecture.md` → *The control planes* and *The API layer*.

## History

### 2026-09-02

- **Changed:** SPEC-200's grant removal and SPEC-202's pool retirement left the browser with no AWS credentials and no AWS grant.

### 2026-08-29

- **Changed:** After SPEC-198 and SPEC-199 the browser reached only presigned S3 bytes, Cognito and the control-plane enqueues without the API.

### 2026-08-28

- **Changed:** The no-backend premise was superseded by the control planes and the HTTP API; the boundary survives, not the absence.

### 2026-08-03

- **Settled:** entered the register.
