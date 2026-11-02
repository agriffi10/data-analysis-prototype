---
type: Decision
title: "Hosted UI = Managed Login v2"
description: "The Cognito domain runs Managed Login v2, never the classic Hosted UI; sign-in and signup both route through Amplify `signInWithRedirect`, and CI ensures the default branding until the provider reaches 6.x."
---

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.

## History

### 2026-08-03

- **Settled:** entered the register.
