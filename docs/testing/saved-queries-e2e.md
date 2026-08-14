# Saved queries — the folder marker's two layers

Manual verification for SPEC-173's folder protections (`features/saved-queries/`,
`features/file-browser/protectedFolders.ts`, and the two bucket policies).

**SPEC-173's owed check was unrunnable as written, and that is the finding.** It read: *delete
`{root}saved_queries/DO_NOT_DELETE.txt` through the portal and confirm `AccessDenied`.* The portal
issues **zero** `DeleteObject` against that key — the marker is hidden by basename so it can never
be selected, and selecting the *folder* is refused client-side before any S3 request. A network
trace of both the personal and the shared attempt confirmed it (2026-08-14).

So there are **two layers and they need two checks**. Check 1 exercises the app's guard; check 2
exercises the bucket policy, which check 1 can never reach.

> **Why the portal cannot exercise the bucket policy.** `useFileBrowser` refuses the folder
> client-side via `UNDELETABLE_ROOT_FOLDERS`, and the marker itself is filtered out of the listing
> by basename — so no code path in the SPA ever asks S3 to delete it. The Deny is real and it is
> the layer that matters if the SPA is ever wrong, which is exactly why it needs its own check.

---

## 1. The client-side refusal (portal, personal AND shared)

**Runs in the browser. Takes two minutes.**

**Fixtures.** In your personal space and in a shared space you own: a `saved_queries/` folder (save
any query into each to create it) and, beside it, an **ordinary empty folder** named
`marker_control`. The control is not optional — without it a generic delete failure reads as the
guard working.

**Steps, in each space:**

1. Select `saved_queries` in the file browser.
2. **Before clicking anything:** Delete and Move must render `aria-disabled` with a reason
   (SPEC-186 FR-002), not enabled. Hover or tab to Delete and read the title.
3. Click Delete. **No confirm dialog may open.** Nothing is deleted and no request is sent.
4. Select `marker_control` and delete it. It must delete cleanly.

**Expected wording**, byte for byte:

| Control | Reason |
|---|---|
| Delete | `Saved queries live in this folder, so it can’t be deleted.` |
| Move | `Saved queries live in this folder, so it can’t be moved or renamed.` |

Note the typographic apostrophe (`’`), not `'`.

**Pass:** both spaces refuse with that exact wording, no confirm is reachable, the folder survives,
and `marker_control` deletes.

> Before SPEC-186 FR-002 this refusal arrived **after** the user read *"Delete the folder
> "saved_queries" and everything inside it? … This can't be undone."* and pressed Delete. If a
> confirm still opens, that regression is back.

---

## 2. The bucket-policy Deny (CLI, not the portal)

**This is the layer SPEC-173's check was actually about, and it needs a real `DeleteObject`.**

Both bucket policies deny `s3:DeleteObject` on `*/DO_NOT_DELETE.txt`, and `*` matches `/`, so a
marker at any depth is covered. Nothing in the app can issue that call, so issue it directly.

> **This procedure needs a raw ID token, and that is the whole reason it is fiddly.** The Deny is
> on the **portal role**, which is only reachable through the Cognito Identity Pool — the laptop
> IAM user is not on either bucket's allowlist and would get `AccessDenied` from the *bucket
> policy's allowlist* rather than from the marker Deny, which is a different refusal wearing the
> same name. **Do not paste the token into a shell command**: it goes into shell history and it
> is a live credential. Write it to a file with `600` permissions, read it from there, and delete
> the file when you are done.

**Getting credentials as the portal role:**

1. Sign in to the portal. In the browser devtools, Application → Local Storage, copy the
   **`idToken`** for the signed-in user.
2. `umask 077 && cat > /tmp/idtoken` — paste, then Ctrl-D. (`umask 077` is what makes the file
   `600`; the token never enters history.)
3. Exchange it (substitute your pool ids):

   ```bash
   IDENTITY_ID=$(aws cognito-identity get-id \
     --identity-pool-id "$IDENTITY_POOL_ID" \
     --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
     --query IdentityId --output text)

   aws cognito-identity get-credentials-for-identity \
     --identity-id "$IDENTITY_ID" \
     --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
     --query Credentials
   ```

4. Export the three values as `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
   in a shell you will close afterwards.

**The check, personal:**

```bash
aws s3api delete-object \
  --bucket dat-prod-user-space \
  --key "$USERNAME/saved_queries/DO_NOT_DELETE.txt"
```

**The check, shared:**

```bash
aws s3api delete-object \
  --bucket dat-prod-shared-space \
  --key "$SPACE/saved_queries/DO_NOT_DELETE.txt"
```

**Expected:** `An error occurred (AccessDenied)` on **both**.

**And the control, which is what makes the result mean anything.** Delete an ordinary object in the
same folder — the portal role is allowed to, so a success here proves the refusal above came from
the marker Deny and not from the credentials being wrong:

```bash
aws s3api put-object --bucket dat-prod-user-space \
  --key "$USERNAME/saved_queries/marker_control.txt" --body /dev/null
aws s3api delete-object --bucket dat-prod-user-space \
  --key "$USERNAME/saved_queries/marker_control.txt"
```

Expect the put and the delete to both succeed.

**Afterwards:** `rm -f /tmp/idtoken` and close the shell holding the exported credentials.

**Pass:** two `AccessDenied`s on the markers, a clean delete on the control, and both markers still
present in the portal's listing afterwards (they are hidden, so confirm with `head-object` rather
than by eye).

---

## What each check does NOT prove

- **Check 1 says nothing about the bucket policy.** It never reaches S3.
- **Check 2 says nothing about the app.** A user who never touches the CLI is protected by check
  1's layer alone, and vice versa. Recording either as discharging the other is the mistake this
  file exists to prevent.
