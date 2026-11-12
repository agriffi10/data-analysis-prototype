# shared-space-storage

Bucket 2, where shared spaces' bytes live, and the two things that make it reachable: its Lake
Formation registration (the registration role, the resource, and the data-location grants to the
portal role and the control planes' execution roles) and the portal role's shared-space membership
policy. The plane that manages spaces is a call to [`../control-plane`](../control-plane/README.md)
in `infra/plane-shared-spaces.tf`; this module is what that plane writes into.

- **This bucket has no bucket policy**, which is why a control-plane role missing from the
  user-space bucket's allowlist half-works: every shared-space path succeeds and every personal one
  fails. See `modules/data`.
- **The 60-second deploy-policy wait lives here** and guards the bucket. The plane and the
  transfer reader wait on this module from their root calls, so the wait still precedes them on a
  fresh apply.
- **The portal role's membership policy is a fixed ten slots**, each templated on the user's
  `shared_space_k` tag, so it stays inside the role's inline-policy aggregate however many spaces
  exist. The reasoning is in `infra/planes/shared-spaces/README.md`.
