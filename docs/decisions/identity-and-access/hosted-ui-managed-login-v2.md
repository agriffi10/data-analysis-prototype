---
type: Decision
title: "Hosted UI = Managed Login v2"
description: "The Cognito domain runs Managed Login v2, never the classic Hosted UI; sign-in and sign-up both start at the portal server's `/auth/login`, whose Managed Login page links to sign-up, and CI ensures every app client's default branding until the provider reaches 6.x."
---

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and sign-up both start at the portal server's `/auth/login`, which redirects to Managed Login with PKCE and a nonce; its sign-in page links to sign-up, and the provider exposes no parameter that opens the sign-up form directly. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply for **every** app client (`deploy-infra.yml`), and a test holds the loop to the clients that exist; revisit when the provider is bumped.

## History

### 2026-11-15

- **Changed:** SPEC-262 started sign-in and sign-up at the portal server's `/auth/login` instead of
  Amplify's `signInWithRedirect`, and the branding loop gained the local-development client.

### 2026-08-03

- **Settled:** entered the register.
