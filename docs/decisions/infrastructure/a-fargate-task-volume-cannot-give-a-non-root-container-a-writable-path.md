---
type: Decision
title: "A Fargate task volume cannot give a non-root container a writable path (SPEC-193)"
description: "The non-root, read-only container's writable paths are `linuxParameters.tmpfs` mounts, never task volumes, which arrive empty and root-owned and do not initialise from the image. One uid feeds both `user` and every mount option."
---

`readonlyRootFilesystem: true` and a non-root `user` need writable mounts, and the mechanism is
**`linuxParameters.tmpfs`**, whose `mountOptions` take `uid`, `gid` and `mode`. It is measured, and it
reverses two earlier statements of the opposite.

**A task-level volume arrives as a fresh, EMPTY, root-owned directory and does not initialise from the
image.** The container printed `uid=101(nginx)` beside `drwxr-xr-x root root /var/cache/nginx` — a
path the base image ships owned by 101. nginx then died on `mkdir() "/tmp/proxy_temp" failed (13:
Permission denied)`, which reads as a container bug and is not one. `volumes` + `mountPoints`,
`readonlyRootFilesystem` and a non-root user are **any two of the three**.

**The uid is ONE value** feeding both the container's `user` and every mount option. Split, the mount
is silently unwritable by the process that needs it — which is this entire failure in one line — and a
test pins them together.

**Do not "fix" a permission error here by seeding the image or by widening the user.** Seeding `/tmp`
with an owned directory was tried and changed nothing, because nothing is copied.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-08-26

- **Settled:** SPEC-193.
